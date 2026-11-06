"""联调前检查只核验准备条件，不把合成素材和配置通过伪装成质量通过。"""

import hashlib
import json
from datetime import timedelta

from test_creative_flow import image_bytes

from app.core.db import now
from evals.preflight import inspect_provider


def fixture_manifest(tmp_path):
    """生成有声明的合成验收素材；只能用于检查工具，不用于人脸评分。"""
    content = image_bytes()
    (tmp_path / "synthetic.png").write_bytes(content)
    manifest = {
        "schema_version": 1,
        "version": "synthetic-only",
        "fixtures": [
            {
                "key": key,
                "file": "synthetic.png",
                "sha256": hashlib.sha256(content).hexdigest(),
                "subject_id": key.split("/")[0],
                "authorization_version": "synthetic-test-only",
                "authorized_providers": ["ai302-image"],
                "authorized_until": (now() + timedelta(hours=1)).isoformat(),
            }
            for key in ("person_a/front", "person_a/side", "person_b/front", "person_b/side")
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path, manifest


def test_preflight_is_nonpaid_and_never_approves_quality(app, tmp_path, monkeypatch):
    """准备条件齐全也只允许开始测量，不自动启用供应商或发起请求。"""
    monkeypatch.setenv("AI302_API_KEY", "synthetic-private-secret")
    path, _ = fixture_manifest(tmp_path)
    report = inspect_provider(app.state.settings, "ai302-image", path)
    assert report["status"] == "ready_for_measurement" and report["verified_fixture_count"] == 4
    assert report["paid_calls"] == 0 and not report["quality_approved"] and not report["enabled"]
    assert "synthetic-private-secret" not in json.dumps(report) and "synthetic.png" not in json.dumps(report)


def test_preflight_blocks_unauthorized_or_changed_fixture(app, tmp_path, monkeypatch):
    """授权范围与文件摘要必须在本地核验，缺少/更换素材不允许进入测量。"""
    monkeypatch.setenv("AI302_API_KEY", "synthetic")
    path, manifest = fixture_manifest(tmp_path)
    manifest["fixtures"][0]["authorized_providers"] = ["another-provider"]
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert "fixture_manifest_invalid" in inspect_provider(app.state.settings, "ai302-image", path)["blockers"]
    path, _ = fixture_manifest(tmp_path)
    (tmp_path / "synthetic.png").write_bytes(b"changed")
    assert "fixture_manifest_invalid" in inspect_provider(app.state.settings, "ai302-image", path)["blockers"]
