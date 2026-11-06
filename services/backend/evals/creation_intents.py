"""隔离真实LLM四轮意图切换验收；只发送合成素材元信息，零图片生成。"""

import argparse
import io
import json
import os
from copy import deepcopy
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select

from app.core.config import ROOT, Settings
from app.core.db import make_engine
from app.integrations.registry import Gateway
from app.main import create_app
from app.modules.agents.models import AgentRun
from app.modules.media_jobs.models import Job
from app.modules.operations.models import ModelCall, ModelRelease, ModelSettingHead
from app.workers.agent_runtime import process_run


def main():
    """每轮最多两次LLM调用，仅允许现有的一次格式修正；无图片调用/正式确认。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    if not parser.parse_args().live:
        parser.error("真实LLM验收须显式--live")
    source = Settings()
    engine = make_engine(source.database_url)
    with engine.connect() as db:
        head = db.execute(
            select(ModelSettingHead.release_id).where(ModelSettingHead.key == "ai302")
        ).scalar_one()
        release = db.execute(
            select(ModelRelease.providers_json, ModelRelease.routes_json).where(ModelRelease.id == head)
        ).one()
        provider_id = release.routes_json["llm"]
        definition = release.providers_json[provider_id]
    engine.dispose()
    directory = ROOT / ".data/evals/creation-intents" / str(uuid4())
    directory.mkdir(parents=True)
    url = "sqlite:///" + str(directory / "database.db")
    os.environ["DATABASE_URL"] = url
    report = {"passed": False, "model": definition["options"]["model"], "turns": [], "image_calls": 0}
    try:
        command.upgrade(Config("alembic.ini"), "head")
        settings = source.model_copy(
            update={
                "database_url": url,
                "storage_root": directory / "objects",
                "app_env": "test",
                "knowledge_development_embedding": True,
            }
        )
        app = create_app(settings)
        config = deepcopy(app.state.config)
        config["providers"][provider_id], config["routes"]["llm"] = definition, provider_id
        config["agent"].update(max_calls=2, max_tool_calls=0)
        app.state.config = config
        app.state.gateway = Gateway(config, settings)
        app.state.gateway.recorder = app.state.model_calls
        with TestClient(app) as client:
            phone = "13900007777"
            code = client.post("/api/v1/web/auth/code", json={"phone": phone}).json()["debug_code"]
            assert (
                client.post("/api/v1/web/auth/login", json={"phone": phone, "code": code}).status_code == 200
            )
            project = client.post(
                "/api/v1/web/projects",
                headers={"Idempotency-Key": str(uuid4())},
                json={"title": "合成意图切换验收", "kind": "portrait"},
            ).json()
            subject = client.post(
                f"/api/v1/web/projects/{project['id']}/subjects",
                json={"subject_key": "person_a", "display_name": "合成人物", "declared": True},
            ).json()
            output = io.BytesIO()
            Image.new("RGB", (128, 128), "#ad93b7").save(output, format="PNG")
            person = client.post(
                f"/api/v1/web/projects/{project['id']}/uploads",
                data={"subject_id": subject["id"]},
                files={"file": ("synthetic.png", output.getvalue(), "image/png")},
            ).json()
            base = client.post(
                f"/api/v1/web/projects/{project['id']}/uploads",
                data={"purpose": "base", "declared": "true"},
                files={"file": ("base.png", output.getvalue(), "image/png")},
            ).json()
            project = client.get(f"/api/v1/web/projects/{project['id']}").json()
            current = {
                "mode": "portrait",
                "subject_only": False,
                "style_id": "portrait_portrait_01",
                "aspect_ratio": "3:4",
                "count": 1,
                "variants": 1,
                "mood": "更暖一点",
                "notes": "色调更温暖",
                "change": "",
                "keep": [],
                "reference_asset_ids": [person["id"]],
                "base_asset_id": base["id"],
                "shot_ids": ["scene"],
                "style_shot_ids": ["portrait"],
                "positions": {subject["id"]: "only"},
            }
            cases = [
                (
                    "只替换当前选中样片的人物，其他不变。请保留样片站位、朝向、姿势、构图、色调，不要再调暖。请更新草稿，不要生成。",
                    "template",
                    True,
                ),
                (
                    "这次不按样片了，为我重新设计海边写真，换一个新的姿势和构图，继续用这个人物参考。请更新草稿，不要生成。",
                    "portrait",
                    False,
                ),
                (
                    "这次不要任何参考图，改为纯文生图：紫色丝绸上的复古相机，不要人物。更新草稿不要生成。",
                    "text",
                    False,
                ),
                (
                    "现在改为微调我已选中的上传底图，只把光线调亮，保留其他内容，不需要人物参考。请更新草稿，不要生成。",
                    "edit",
                    False,
                ),
            ]
            for text, expected_mode, strict in cases:
                response = client.post(
                    f"/api/v1/web/projects/{project['id']}/messages",
                    json={
                        "client_message_id": str(uuid4()),
                        "text": text,
                        "expected_revision": project["brief_revision"],
                        "draft": current,
                    },
                )
                assert response.status_code == 202, response.text
                run_id = response.json()["id"]
                process_run(app, run_id)
                with app.state.sessions() as db:
                    run = db.get(AgentRun, run_id)
                    state = {
                        "run_id": run.id,
                        "status": run.status,
                        "calls": run.calls,
                        "error_code": run.error_code,
                        "usage": run.usage_json,
                    }
                conversation = client.get(f"/api/v1/web/projects/{project['id']}/conversation").json()
                message = next(
                    (
                        m
                        for m in conversation["messages"]
                        if m["run_id"] == run_id and m["role"] == "assistant"
                    ),
                    None,
                )
                state["message"] = message
                report["turns"].append(state)
                assert state["status"] == "succeeded" and 1 <= state["calls"] <= 2
                assert message and message["proposal_json"], state
                patch = {k: v for k, v in message["proposal_json"].items() if v is not None and k != "intent"}
                current.update(patch)
                assert current["mode"] == expected_mode and current["subject_only"] == strict, state
                if strict:
                    assert current["shot_ids"] == ["portrait"] and current["style_shot_ids"] == []
            with app.state.sessions() as db:
                assert db.scalar(select(func.count()).select_from(Job)) == 0
                report["image_calls"] = db.scalar(
                    select(func.count()).select_from(ModelCall).where(ModelCall.kind == "image")
                )
                assert report["image_calls"] == 0
        app.state.engine.dispose()
        report["passed"] = True
    finally:
        (directory / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(
            json.dumps(
                {
                    "report": str(directory / "report.json"),
                    "passed": report["passed"],
                    "turns": len(report["turns"]),
                    "image_calls": report["image_calls"],
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
