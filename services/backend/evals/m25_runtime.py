"""隔离实验启动与运行前屏障；专用Key、固定目录、费用未知停下一批、到期停止。"""

import json
import os
import subprocess
import time
from pathlib import Path

import yaml

from app.core.errors import DomainError
from evals.m25 import ROOT, cleanup, folder_for, timestamp


def check(settings, *, paid=False):
    """普通主环境不受实验期限影响；标记实验环境必须始终绑定私有目录。"""
    run_id = getattr(settings, "m25_run_id", None)
    if not run_id:
        return
    try:
        folder = folder_for(run_id)
        value = json.loads((folder / "manifest.json").read_text())
        if timestamp() >= __import__("datetime").datetime.fromisoformat(value["expires_at"]):
            raise ValueError("expired")
        if (
            settings.database_url != "sqlite:///" + str(folder / "database.db")
            or settings.storage_root.resolve() != (folder / "objects").resolve()
        ):
            raise ValueError("wrong isolation")
        if paid and (
            not all(value["readiness"].values())
            or not value["batches"]
            or value["batches"][-1]["actual_cny"] is not None
        ):
            raise ValueError("batch not explicitly opened")
    except (ValueError, OSError, KeyError) as exc:
        raise DomainError("EXPERIMENT_PAUSED", "隔离实验已到期、未准备或未打开已核账的新批次", 409) from exc


def export_candidate(run_id, candidate_id):
    """本地管理员导出候选到独立实验，不改主发布指针，不导出生产凭证或项目。"""
    from app.main import create_app
    from app.modules.operations.candidates import candidate_digest
    from app.modules.operations.model_schemas import ModelSettingsInput
    from app.modules.operations.model_settings import compile_providers
    from app.modules.operations.models import ModelCandidate

    folder = folder_for(run_id)
    app = create_app()
    with app.state.sessions() as db:
        row = db.get(ModelCandidate, candidate_id)
        if row is None:
            raise ValueError("candidate not found")
        config = app.state.settings.application_config()
        providers, routes = compile_providers(
            app, ModelSettingsInput(expected_revision=0, **row.settings_json)
        )
        if row.digest != candidate_digest(app, row.settings_json, providers, routes):
            raise ValueError("代码或目录已变化，请重新保存候选后导出")
        for definition in providers.values():
            definition["options"]["api_key_env"] = "AI302_EVAL_API_KEY"
        config["providers"].update(providers)
        config["routes"].update(routes)
        config["image_routes"] = {}
        config["knowledge"]["embedding_options"]["api_key_env"] = "AI302_EVAL_API_KEY"
        manifest_path = folder / "manifest.json"
        value = json.loads(manifest_path.read_text())
        value["candidate"] = {"id": row.id, "digest": row.digest, "settings": row.settings_json}
        manifest_path.write_text(json.dumps(value, ensure_ascii=False, indent=2))
        (folder / "application.yaml").write_text(yaml.safe_dump(config, allow_unicode=True))
    app.state.engine.dispose()
    return {"run": run_id, "candidate": candidate_id, "exported": True}


def launch(run_id):
    """持有运行锁，防止运行中核账关闭批次。"""
    import fcntl

    folder = folder_for(run_id)
    with (folder / ".runtime-lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _launch(run_id)


def _launch(run_id):
    """只启动显式就绪的隔离本地服务；每次生成仍在网页逐单确认，到期停止并清理。"""
    from app.core.config import Settings
    from app.integrations.secrets import provider_secret

    folder = folder_for(run_id)
    settings = Settings(
        m25_run_id=run_id,
        database_url="sqlite:///" + str(folder / "database.db"),
        storage_root=folder / "objects",
    )
    check(settings, paid=True)
    if not (folder / "application.yaml").is_file():
        raise ValueError("请先导出待测候选")
    secret = provider_secret(settings, "AI302_EVAL_API_KEY")
    if not secret:
        raise ValueError("请先配置AI302_EVAL_API_KEY专用实验密钥")
    env = {
        **os.environ,
        "DATABASE_URL": settings.database_url,
        "STORAGE_ROOT": str(settings.storage_root),
        "CONFIG_FILE": str(folder / "application.yaml"),
        "M25_RUN_ID": run_id,
        "AI302_EVAL_API_KEY": secret,
        "AI302_API_KEY": "",
        "APP_ENV": "development",
        "YINGXU_WEB_PORT": "5473",
        "YINGXU_ADMIN_PORT": "5474",
        "YINGXU_API_PORT": "8300",
    }
    project_root = Path(__file__).resolve().parents[3]
    process = subprocess.Popen(["node", "scripts/dev.mjs"], cwd=project_root, env=env)
    try:
        while process.poll() is None:
            check(settings)
            time.sleep(5)
    finally:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        cleanup(ROOT)
