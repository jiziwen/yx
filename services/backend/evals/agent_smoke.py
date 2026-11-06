"""显式真实 LLM 联通测试；隔离静物需求、零图片调用，可扩展记忆与只读工具场景。"""

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor
from time import monotonic, sleep
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import ROOT, Settings
from app.core.db import make_engine
from app.main import create_app
from app.modules.agents.models import AgentRun
from app.modules.executions.models import Approval, Plan
from app.modules.media_jobs.models import Job
from app.modules.operations.models import ModelRelease, ModelSettingHead
from app.workers.agent_runtime import process_run


def main():
    """只复制后台非敏感配置；每轮按配置限制模型调用，不发送既有项目。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--memory-tools", action="store_true")
    parser.add_argument("--stream", action="store_true")
    parser.add_argument("--brief-history", action="store_true")
    args = parser.parse_args()
    if not args.live:
        parser.error("需显式 --live 才允许真实 LLM 请求")
    if sum([args.stream, args.memory_tools, args.brief_history]) > 1:
        parser.error("真实验收场景请分开运行，避免无意扩大付费范围")
    source = Settings()
    engine = make_engine(source.database_url)
    with engine.connect() as connection:
        head = connection.execute(
            select(ModelSettingHead.release_id).where(ModelSettingHead.key == "ai302")
        ).scalar_one()
        profile = connection.execute(
            select(ModelRelease.settings_json).where(ModelRelease.id == head)
        ).scalar_one()
    engine.dispose()
    if not profile["llm"]["enabled"]:
        raise SystemExit("真实 LLM 未启用，未发送请求")
    directory = ROOT / ".data/evals/agent-live" / str(uuid4())
    directory.mkdir(parents=True)
    url = "sqlite:///" + str(directory / "smoke.db")
    original = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    report = {
        "model": profile["llm"]["model"],
        "max_output_tokens": profile["llm"]["max_tokens"],
        "turns": [],
        "passed": False,
        "image_calls": 0,
        "scenario": "native_reply_stream"
        if args.stream
        else "confirmed_memory_and_read_tools"
        if args.memory_tools
        else "structured_brief_and_history"
        if args.brief_history
        else "clarify_and_propose",
    }
    started = monotonic()
    try:
        command.upgrade(Config("alembic.ini"), "head")
        settings = source.model_copy(
            update={"database_url": url, "storage_root": directory / "objects", "app_env": "test"}
        )
        app = create_app(settings)
        with TestClient(app) as client:
            assert (
                client.post(
                    "/api/v1/admin/auth/login", json={"username": "admin", "password": source.admin_password}
                ).status_code
                == 200
            )
            assert (
                client.put(
                    "/api/v1/admin/model-settings/ai302", json={"expected_revision": 0, **profile}
                ).status_code
                == 200
            )
            phone = "13900008888"
            code = client.post("/api/v1/web/auth/code", json={"phone": phone}).json()["debug_code"]
            assert (
                client.post("/api/v1/web/auth/login", json={"phone": phone, "code": code}).status_code == 200
            )
            project = client.post(
                "/api/v1/web/projects",
                headers={"Idempotency-Key": str(uuid4())},
                json={"title": "Agent 合成静物验收", "kind": "portrait"},
            ).json()
            style = next(
                s for s in client.get("/api/v1/web/catalog").json()["styles"] if s["kind"] == "portrait"
            )
            draft = {
                "mode": "text",
                "style_id": style["id"],
                "aspect_ratio": "3:4",
                "count": 1,
                "variants": 1,
                "mood": "尚未确定",
                "notes": "",
                "change": "",
                "keep": [],
                "reference_asset_ids": [],
                "base_asset_id": None,
                "shot_ids": [],
                "style_shot_ids": [],
                "positions": {},
            }
            prompts = [
                (
                    "我想创作一张图片，但是还没想好拍什么。请先问我一个最重要的问题，不要直接整理提案。",
                    "needs_input",
                ),
                (
                    "我选无图文生图，不上传人物或底图。请整理一张3:4的静物画面：薰衣草色丝绸上放一台复古相机，梦幻柔光，冷紫与奶油白，画面不要人物、不要文字。无需再问，先给提案，不要生成图片。",
                    "plan_ready",
                ),
            ]
            if args.memory_tools:
                prompts = [
                    (
                        "请提议记住这条长期创作要求：画面不要文字或水印。只把它放在memory_suggestion供我确认，不要生成提案或图片。",
                        "answer",
                    ),
                    (
                        "我现在还有几次可用？有没有生成任务？请调用只读工具查询实际次数和任务状态，再告诉我已记住哪些要求，不要生成图片。",
                        "answer",
                    ),
                    (
                        "请结合已记住的长期要求，整理一张3:4无图文生图静物提案：薰衣草色丝绸上一台复古相机，梦幻柔光，不要人物。无需再追问，先给提案不要生成。",
                        "plan_ready",
                    ),
                ]
            if args.stream:
                prompts = [
                    (
                        "请先用80到120字中文简要介绍你如何陪我整理光线、画幅、配色与拍摄要求，放在reply里；然后整理一张3:4无图文生图静物提案：薰衣草色丝绸上的复古相机、柔和自然光，不要人物和文字。不用追问，不要调用图片。",
                        "plan_ready",
                    )
                ]
            if args.brief_history:
                prompts = [
                    (
                        "请只提出创作需求卡建议 brief_suggestion：场景为薰衣草色丝绸上的复古相机，光线为自然柔光，禁止项为不要人物和文字。outcome用answer，先供我确认，不要正式提案或图片。",
                        "answer",
                    ),
                    (
                        "请调用search_project_history，按原文关键词‘复古相机’查询我们之前聊过的画面，引用本轮来源。仅回溯，不要生成。",
                        "answer",
                    ),
                    (
                        "请结合已确认的需求卡整理一张3:4、1张的无图文生图静物提案，不要追问，不要生成图片。",
                        "plan_ready",
                    ),
                ]
            for turn_index, (text, expected) in enumerate(prompts):
                response = client.post(
                    f"/api/v1/web/projects/{project['id']}/messages",
                    json={
                        "client_message_id": str(uuid4()),
                        "text": text,
                        "expected_revision": project["brief_revision"],
                        "draft": draft,
                    },
                )
                assert response.status_code == 202
                run_id = response.json()["id"]
                if args.stream:
                    observed = []
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        future = pool.submit(process_run, app, run_id)
                        while not future.done():
                            with app.state.sessions() as db:
                                current = db.get(AgentRun, run_id)
                                preview = current.reply_preview
                                if preview and (not observed or observed[-1]["seq"] != preview["seq"]):
                                    observed.append(
                                        {**preview, "elapsed_seconds": round(monotonic() - started, 3)}
                                    )
                            sleep(0.03)
                        future.result()
                    report["observed_previews"] = observed
                    assert len(observed) >= 2, "未观察到完成前的真实多段回复"
                else:
                    process_run(app, run_id)
                state = client.get(f"/api/v1/web/agent-runs/{run_id}").json()
                with app.state.sessions() as db:
                    usage = db.get(AgentRun, run_id).usage_json
                report["turns"].append(
                    {
                        key: state[key]
                        for key in (
                            "id",
                            "status",
                            "outcome",
                            "calls",
                            "tool_calls",
                            "memory_revision",
                            "error_code",
                        )
                    }
                )
                report["turns"][-1].update(usage=usage, actual_cost_micros=None)
                assert state["status"] == "succeeded" and state["outcome"] == expected, (
                    state.get("error_code") or "unexpected outcome"
                )
                if args.brief_history and turn_index == 0:
                    memory_url = f"/api/v1/web/projects/{project['id']}/memory"
                    current = client.get(memory_url).json()
                    view = client.get(f"/api/v1/web/projects/{project['id']}/conversation").json()
                    suggested = view["messages"][-1]["brief_suggestion_json"]
                    assert (
                        current["fields"] == {}
                        and suggested
                        and {"scene", "lighting", "avoid"}.issubset(suggested)
                    )
                    saved = client.put(
                        memory_url,
                        json={
                            "expected_revision": current["revision"],
                            "expected_privacy_epoch": current["privacy_epoch"],
                            "requirements": current["requirements"],
                            "fields": suggested,
                            "source_run_id": run_id,
                        },
                    )
                    assert saved.status_code == 200
                    report["confirmed_fields"] = saved.json()["fields"]
                if args.brief_history and turn_index == 1:
                    view = client.get(f"/api/v1/web/projects/{project['id']}/conversation").json()
                    observations = view["messages"][-1]["observations_json"]
                    assert {item["name"] for item in observations} == {"search_project_history"}
                    assert observations[0]["status"] == "ok" and observations[0]["data"]["messages"]
                    report["history_observations"] = observations
                if args.memory_tools and turn_index == 0:
                    memory_url = f"/api/v1/web/projects/{project['id']}/memory"
                    current = client.get(memory_url).json()
                    assert current["requirements"] == []
                    conversation = client.get(f"/api/v1/web/projects/{project['id']}/conversation").json()
                    suggested = conversation["messages"][-1]["memory_suggestion_json"]
                    assert suggested and any("水印" in item for item in suggested)
                    saved = client.put(
                        memory_url,
                        json={
                            "expected_revision": current["revision"],
                            "expected_privacy_epoch": current["privacy_epoch"],
                            "requirements": suggested,
                            "source_run_id": run_id,
                        },
                    )
                    assert saved.status_code == 200
                    report["confirmed_memory"] = saved.json()["requirements"]
                if args.memory_tools and turn_index == 1:
                    conversation = client.get(f"/api/v1/web/projects/{project['id']}/conversation").json()
                    observations = conversation["messages"][-1]["observations_json"]
                    assert {item["name"] for item in observations} == {"get_entitlements", "get_job_status"}
                    assert all(item["status"] == "ok" for item in observations)
                    assert (
                        next(
                            item["data"]["available"]
                            for item in observations
                            if item["name"] == "get_entitlements"
                        )
                        == 0
                    )
                    assert (
                        next(
                            item["data"]["total"] for item in observations if item["name"] == "get_job_status"
                        )
                        == 0
                    )
                    report["read_observations"] = observations
            view = client.get(f"/api/v1/web/projects/{project['id']}/conversation").json()
            report["synthetic_messages"] = [
                {"role": m["role"], "text": m["text"], "proposal": m["proposal_json"]}
                for m in view["messages"]
            ]
            assert len(view["messages"]) == len(prompts) * 2 and view["messages"][-1]["proposal_json"]
            if args.stream:
                assert view["runs"][-1]["reply_preview"] is None
                assert view["messages"][-1]["text"].startswith(report["observed_previews"][0]["text"])
            if args.brief_history:
                assert all(
                    value in view["messages"][-1]["proposal_json"]["notes"]
                    for value in report["confirmed_fields"].values()
                )
            if args.memory_tools:
                assert all(
                    item in view["messages"][-1]["proposal_json"]["notes"]
                    for item in report["confirmed_memory"]
                )
            with app.state.sessions() as db:
                report["side_effect_counts"] = {
                    model.__tablename__: db.scalar(select(func.count()).select_from(model))
                    for model in (Plan, Approval, Job)
                }
            assert not any(report["side_effect_counts"].values())
            report["passed"] = True
        app.state.engine.dispose()
    finally:
        if original is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original
        report["elapsed_seconds"] = round(monotonic() - started, 2)
        path = directory / "report.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(
            json.dumps(
                {k: report[k] for k in ("passed", "model", "turns", "image_calls", "elapsed_seconds")},
                ensure_ascii=False,
            )
        )
        print("Report:", path)


if __name__ == "__main__":
    main()
