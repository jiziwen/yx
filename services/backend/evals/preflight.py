"""真实供应商联调前检查；只读取配置和授权素材，不调用付费接口。"""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import Settings
from app.core.plugins import load_symbol
from app.integrations.contracts import AsyncImageProvider, ImageProvider
from app.integrations.secrets import provider_secret
from app.modules.assets.service import normalize_image
from evals.prepare import prepare


class AuthorizedFixture(BaseModel):
    """私有验收素材必须有摘要、未过期授权和明确供应商使用范围。"""

    model_config = ConfigDict(extra="forbid")
    key: str
    file: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    subject_id: str
    authorization_version: str = Field(min_length=1)
    authorized_providers: list[str] = Field(min_length=1)
    authorized_until: datetime


class FixtureManifest(BaseModel):
    """清单放入私有目录；仓库中的模板不含照片和真实身份。"""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1]
    version: str
    fixtures: list[AuthorizedFixture] = Field(min_length=1)


def inspect_provider(settings: Settings, provider_id: str, manifest: Path | None = None) -> dict:
    """检查可联调性而非质量放行，输出不含密钥、素材路径或上游正文。"""
    config = settings.application_config()
    definition = config["providers"].get(provider_id)
    blockers = []
    if not definition or definition["kind"] != "image":
        raise ValueError("指定图片供应商未注册")
    options = definition["options"]
    credentials = (
        bool(provider_secret(settings, options["api_key_env"]))
        if options.get("api_key_env")
        else definition["development_only"]
    )
    if not credentials:
        blockers.append("provider_credentials_missing")
    protocol = "not_instantiated"
    if credentials:
        try:
            provider = load_symbol(definition["entrypoint"])(options, settings)
            protocol = (
                "asynchronous"
                if isinstance(provider, AsyncImageProvider)
                else "synchronous"
                if isinstance(provider, ImageProvider)
                else "invalid"
            )
            if protocol == "invalid":
                blockers.append("provider_contract_invalid")
        except Exception:
            blockers.append("provider_configuration_invalid")
    if definition["development_only"]:
        blockers.append("development_provider_cannot_measure_identity")
    required = set(prepare()["required_private_fixtures"])
    verified = set()
    if manifest is None:
        blockers.append("authorized_fixture_manifest_missing")
    else:
        try:
            data = FixtureManifest.model_validate_json(manifest.read_bytes())
            if len({item.key for item in data.fixtures}) != len(data.fixtures):
                raise ValueError("duplicate")
            root = manifest.resolve().parent
            for fixture in data.fixtures:
                path = (root / fixture.file).resolve()
                if (
                    not path.is_relative_to(root)
                    or provider_id not in fixture.authorized_providers
                    or fixture.authorized_until.tzinfo is None
                    or fixture.authorized_until <= datetime.now(timezone.utc)
                ):
                    raise ValueError("authorization")
                if fixture.subject_id != fixture.key.split("/")[0]:
                    raise ValueError("subject")
                content = path.read_bytes()
                if (
                    len(content) > settings.max_upload_bytes
                    or hashlib.sha256(content).hexdigest() != fixture.sha256
                ):
                    raise ValueError("checksum")
                normalize_image(content)
                verified.add(fixture.key)
            if not required.issubset(verified):
                blockers.append("fixture_coverage_incomplete")
        except Exception:
            blockers.append("fixture_manifest_invalid")
    capabilities = definition["capabilities"]
    if capabilities.get("max_subjects", 0) < 2 or capabilities.get("max_reference_images", 0) < 2:
        blockers.append("couple_cases_exceed_declared_capabilities")
    return {
        "schema_version": 1,
        "status": "blocked_for_measurement" if blockers else "ready_for_measurement",
        "provider_id": provider_id,
        "adapter_version": definition["version"],
        "enabled": definition["enabled"],
        "release_status": definition["release_status"],
        "credentials_present": credentials,
        "protocol": protocol,
        "verified_fixture_count": len(verified),
        "missing_fixture_keys": sorted(required - verified),
        "blockers": blockers,
        "paid_calls": 0,
        "quality_approved": False,
        "actual_cost": None,
        "release_gates": [
            "authorized_output_reviews",
            "measured_billing_and_latency",
            "confirmed_release_thresholds",
            "production_storage_and_sms",
        ],
    }


def main():
    """报告成功生成也不能视作实际供应商通过；require-ready 用于联调准备门禁。"""
    parser = argparse.ArgumentParser(description="M1 供应商联调前检查，不发送图片")
    parser.add_argument("--provider", default="ai302-image")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args()
    report = inspect_provider(Settings(), args.provider, args.manifest)
    target = Path(".data/evals/provider-preflight.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{report['provider_id']}: {report['status']}; paid_calls=0; quality_approved=false")
    if args.require_ready and report["blockers"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
