"""目录编号与已选私有素材分开；不发送照片、不执行生成。"""

import json

import pytest
from sqlalchemy import func, select
from test_agent import draft, install, send, snapshot
from test_creative_flow import create_project, image_bytes, login

from app.modules.agents.context import catalog_styles, validate_proposal
from app.modules.agents.models import AgentRun
from app.modules.agents.schemas import AgentAnswer
from app.modules.agents.tools import CatalogTool, NoArguments, ToolScope
from app.modules.executions.models import Approval, Plan
from app.modules.media_jobs.models import Job
from app.workers.agent_runtime import process_run


@pytest.mark.parametrize("mode,field", [("portrait", "style_shot_ids"), ("template", "shot_ids")])
def test_catalog_selection_matches_visible_order_without_touching_person(client, app, mode, field):
    """两张目录图加一张上传照不能误报只有一张；更换数组替代而非追加。"""
    login(client)
    project = create_project(client)
    subject = client.post(
        f"/api/v1/web/projects/{project['id']}/subjects",
        json={"subject_key": "person_a", "display_name": "合成人物", "declared": True},
    ).json()
    asset = client.post(
        f"/api/v1/web/projects/{project['id']}/uploads",
        data={"subject_id": subject["id"]},
        files={"file": ("synthetic.png", image_bytes(), "image/png")},
    ).json()
    project = client.get(f"/api/v1/web/projects/{project['id']}").json()
    style = catalog_styles(app, project["kind"])[0]
    first, second = style["shots"][:2]
    current = {
        **draft(),
        "mode": mode,
        "style_id": style["id"],
        field: [first["id"]],
        "reference_asset_ids": [asset["id"]],
        "positions": {subject["id"]: "only"},
    }

    def respond(messages):
        """检查实际发送模型的事实，而非用预置ID掩盖上下文缺失。"""
        facts = json.loads(messages[1]["content"].split("：", 1)[1])
        gallery = facts["selection"]["active_catalog_gallery"]
        assert gallery["target_field"] == field and gallery["source"] == "catalog"
        assert gallery["items"][0] == {"id": first["id"], "display_position": 1, "selected": True}
        assert gallery["items"][1] == {"id": second["id"], "display_position": 2, "selected": False}
        assert len(facts["materials"]) == 1 and facts["materials"][0]["id"] == asset["id"]
        assert facts["selection"]["person_reference_ids"] == [asset["id"]]
        assert "not_full_project_gallery" in facts["selection"]["private_materials_scope"]
        assert "storage_key" not in messages[1]["content"] and "base64" not in messages[1]["content"]
        return {
            "outcome": "plan_ready",
            "reply": "已换成第二张，人物参考不变。",
            "proposal": {"intent": "user_request", field: [gallery["items"][1]["id"]]},
        }

    provider = install(app, [respond])
    run, _ = send(client, project, "参考换成第二张，第一张不要了", draft=current)
    assert process_run(app, run["id"])
    patch = snapshot(client, project)["messages"][-1]["proposal_json"]
    updated = {**current, **{k: v for k, v in patch.items() if v is not None}}
    assert updated[field] == [second["id"]]
    assert updated["reference_asset_ids"] == [asset["id"]]
    assert all(updated[key] == current[key] for key in ("mode", "style_id", "notes", "positions", "count"))
    assert len(provider.messages) == 1
    with app.state.sessions() as db:
        record = db.get(AgentRun, run["id"])
        facts = record.context_json["facts"]
        for invalid in (
            {field: [asset["id"]]},
            {field: ["nonexistent-shot"]},
            {"reference_asset_ids": [second["id"]]},
        ):
            with pytest.raises(ValueError):
                validate_proposal(
                    AgentAnswer(outcome="plan_ready", reply="测试", proposal=invalid), record.context_json
                )
        tool = CatalogTool().read(
            app, db, ToolScope("", project["id"], project["privacy_epoch"]), NoArguments()
        )
        assert tool["styles"] == facts["catalog"]["styles"]
        for model in (Plan, Approval, Job):
            assert db.scalar(select(func.count()).select_from(model)) == 0
