"""生成供应商验收准备清单；无远程调用，准备通过不代表身份质量或成本通过。"""

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parent


class ProviderCase(BaseModel):
    """每个样例的独立人物与约束，私有素材只使用引用键。"""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    kind: Literal["portrait", "wedding", "contract"]
    subjects: list[str]
    fixtures: list[str]
    checks: list[str] = Field(min_length=1)


class ProviderDataset(BaseModel):
    """M0 版本化样例集；真实质量、费用和时延门槛留待 M1 实测确认。"""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1]
    version: str
    cases: list[ProviderCase] = Field(min_length=8)
    release_thresholds: dict


def prepare(source: Path = ROOT / "datasets/provider-readiness.json") -> dict:
    """验证覆盖面并产生确定性摘要，明确缺少真实授权素材与评测记录。"""
    content = source.read_bytes()
    dataset = ProviderDataset.model_validate_json(content)
    if len({case.id for case in dataset.cases}) != len(dataset.cases):
        raise ValueError("供应商样例 ID 重复")
    for case in dataset.cases:
        expected = 2 if case.kind == "wedding" else 1 if case.kind == "portrait" else 0
        if len(set(case.subjects)) != expected or (expected and not case.fixtures):
            raise ValueError(f"样例 {case.id} 的人物或素材契约不完整")
    return {
        "schema_version": 1,
        "status": "prepared_not_evaluated",
        "dataset_version": dataset.version,
        "dataset_sha256": hashlib.sha256(content).hexdigest(),
        "case_count": len(dataset.cases),
        "required_private_fixtures": sorted({fixture for case in dataset.cases for fixture in case.fixtures}),
        "quality_approved": False,
        "missing": [
            "authorized_private_fixture_manifest",
            "chosen_provider_and_model",
            "measured_quality_cost_latency",
            "confirmed_release_thresholds",
        ],
    }


def main() -> None:
    """保存非敏感准备报告；退出 0 只表示清单结构有效，不批准真实供应商。"""
    result = prepare()
    target = Path(".data/evals/preparation.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已准备 {result['case_count']} 个供应商样例定义；真实质量/成本尚未评测。")


if __name__ == "__main__":
    main()
