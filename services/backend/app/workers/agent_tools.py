"""Run 内的只读工具预算和证据；执行权、项目范围由 Worker 注入。"""

from pydantic import ValidationError

from app.core.db import now
from app.core.errors import DomainError
from app.integrations.contracts import ProviderFailure
from app.modules.agents.context import fingerprint
from app.modules.agents.schemas import ToolObservation
from app.modules.agents.tools import ReadToolRegistry, ToolScope


class RunReadTools:
    """同一轮累计次数、禁止相同查询空转，状态变化由下一轮显式查询。"""

    def __init__(self, app, run_id, token, progress):
        """只接受 Worker 创建的范围，不从模型读取登录身份。"""
        self.app, self.run_id, self.token, self.progress = app, run_id, token, progress

    def __call__(self, name, arguments):
        """先记录尝试预算，再用只读连接读取；取消或撤销后不发布迟到结果。"""
        from .agent_runtime import lock_run, valid_inputs
        from .runtime import begin_write

        self.progress("querying_tools")
        call_key = fingerprint({"name": name, "arguments": arguments})
        with self.app.state.sessions() as db:
            begin_write(db)
            project, _, run = lock_run(db, self.run_id)
            if run.status != "running" or run.lease_token != self.token:
                raise ProviderFailure("AGENT_CANCELLED")
            valid_inputs(db, project, run, self.app)
            if run.tool_calls >= run.budget_json.get("max_tool_calls", 0):
                raise ProviderFailure("AGENT_TOOL_BUDGET_EXCEEDED")
            run.tool_calls += 1
            sequence = run.tool_calls
            specifications = {item["name"]: item for item in run.context_json["facts"].get("read_tools", [])}
            descriptor = specifications.get(name)
            duplicate = any(item.get("call_key") == call_key for item in run.tool_trace_json)
            frozen = ReadToolRegistry(run.budget_json.get("tools", []))
            scope = ToolScope(
                run.owner_user_id or project.owner_user_id,
                run.project_id,
                run.privacy_epoch,
                run.primary_role,
            )
            from app.modules.agents.steps import start_step

            step = start_step(
                db,
                run,
                "tool",
                name,
                {
                    "call_key": call_key,
                    "scope": "current_project" if project else "published_knowledge",
                    "role": run.primary_role,
                },
            )
            step_id = step.id
            db.commit()
        data, error = None, None
        try:
            current = self.app.state.agent_tools.entries.get(name)
            previous = frozen.entries.get(name)
            if not descriptor or not current or not previous:
                raise DomainError("TOOL_NOT_ALLOWED", "查询未开放", 403)
            if current[1] != previous[1] or current[0].version != descriptor["version"]:
                raise DomainError("TOOL_CONFIG_CHANGED", "查询配置已变化")
            if duplicate:
                raise DomainError("TOOL_REPEAT", "本轮不重复相同查询")
            from app.integrations.call_logging import call_scope

            with call_scope(
                {
                    "run_id": self.run_id,
                    "project_id": scope.project_id,
                    "owner_user_id": scope.user_id,
                    "privacy_epoch": scope.privacy_epoch,
                }
            ):
                data = frozen.read(self.app, scope, name, arguments)
            if name == "search_knowledge" and data:
                for index, evidence in enumerate(data.get("evidence", []), start=1):
                    evidence["citation_key"] = f"K{sequence}-{index}"

        except ValidationError:
            error = "TOOL_INVALID_ARGUMENTS"
        except DomainError as exc:
            error = (
                exc.code
                if exc.code
                in {
                    "TOOL_NOT_ALLOWED",
                    "TOOL_CONFIG_CHANGED",
                    "TOOL_REPEAT",
                    "TOOL_NOT_FOUND",
                    "TOOL_OUTPUT_LIMIT",
                    "TOOL_TIMEOUT",
                    "AUTHORIZATION_CHANGED",
                }
                else "TOOL_UNAVAILABLE"
            )
        except Exception:
            error = "TOOL_UNAVAILABLE"
        observation = ToolObservation(
            id=f"read-{sequence}",
            name=name,
            title=previous[0].title if previous else "只读查询",
            version=descriptor["version"] if descriptor else "unknown",
            status="error" if error else "ok",
            observed_at=now(),
            data=data,
            error_code=error,
        ).model_dump(mode="json")
        self.progress("reading_results")
        with self.app.state.sessions() as db:
            begin_write(db)
            project, _, run = lock_run(db, self.run_id)
            if run.status != "running" or run.lease_token != self.token:
                raise ProviderFailure("AGENT_CANCELLED")
            valid_inputs(db, project, run, self.app)
            run.tool_trace_json = [*run.tool_trace_json, {**observation, "call_key": call_key}]
            from app.modules.agents.steps import end_step

            end_step(db, step_id, error=error)
            from app.modules.agents.models import AgentStep

            saved_step = db.get(AgentStep, step_id)
            saved_step.manifest_json = {
                **saved_step.manifest_json,
                "observation_id": observation["id"],
                "source_ids": [entry["chunk_id"] for entry in (data or {}).get("evidence", [])],
            }
            db.commit()
        return observation
