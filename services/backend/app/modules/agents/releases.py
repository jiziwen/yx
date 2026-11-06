"""Git管理的精确Release快照与生产门禁，不把工程通过冒充质量审核通过。"""

import hashlib
import json
from pathlib import Path

import yaml

from app.core.config import ROOT
from app.core.errors import DomainError
from app.modules.catalog.live import current_catalog


def code_files():
    """绑定整个后端手写代码，权限、API和索引Worker的变更同样进入Release。"""
    return sorted((ROOT / "app").rglob("*.py"))


def release_snapshot(app, policy, agent_config=None):
    """冻结代码、模型、提示词、图、工具/上下文/检索及目录摘要，凭证仅逻辑标识。"""
    path = Path(app.state.config["agent"]["release_file"])
    if not path.is_absolute():
        path = ROOT / path
    definition = yaml.safe_load(path.read_text())
    if definition.get("schema_version") != 1 or not all(
        definition.get(k)
        for k in (
            "id",
            "prompt_version",
            "graph_version",
            "context_version",
            "retrieval_version",
            "dataset_version",
            "rubric_version",
        )
    ):
        raise ValueError("Agent Release缺少版本契约")
    code = {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in code_files()
    }
    from app.modules.agents.context import fingerprint
    from app.modules.knowledge.service import spec

    dataset_digest = hashlib.sha256((ROOT / "resources/agent/m2-cases.json").read_bytes()).hexdigest()
    manifest = {
        "release_id": definition["id"],
        "schema_version": 1,
        "dataset_digest": dataset_digest,
        "embedding_spec": spec(app),
        "versions": {k: v for k, v in definition.items() if k not in {"quality_report", "routing"}},
        "routing": definition["routing"],
        "code_digest": fingerprint(code),
        "model_policy": policy,
        "agent_config_digest": fingerprint(agent_config or app.state.config["agent"]),
        "knowledge_config_digest": fingerprint(app.state.config["knowledge"]),
        "catalog_digest": fingerprint(
            {key: value for key, value in app.state.catalog.items() if not key.startswith("_")}
        ),
    }
    manifest["release_digest"] = fingerprint(manifest)
    if app.state.settings.app_env == "production":
        report_path = definition.get("quality_report")
        if not report_path:
            raise DomainError("AGENT_RELEASE_NOT_APPROVED", "Agent Release尚未通过质量审核", 503)
        source = Path(report_path)
        if not source.is_absolute():
            source = ROOT / source
        report = json.loads(source.read_text())
        if (
            report.get("scope") != "live_samples"
            or report.get("sample_count", 0) < 2
            or report.get("dataset_version") != definition["dataset_version"]
            or report.get("rubric_version") != definition["rubric_version"]
            or report.get("candidate_release") != manifest["release_digest"]
            or report.get("quality_approved") is not True
            or report.get("critical_failures") != []
            or not report.get("reviewed_by")
            or type(report.get("actual_cost_micros")) is not int
            or report.get("actual_cost_micros", -1) < 0
            or not report.get("bill_reference")
            or not report.get("quality_review")
            or not complete_cases(report, manifest["release_digest"])
        ):
            raise DomainError("AGENT_RELEASE_NOT_APPROVED", "Agent Release评测或审核不匹配", 503)
    # 管理员发布的数据版本独立于代码/提示词质量版本；每轮仍冻结并在提交前复核。
    manifest["runtime_catalog_digest"] = fingerprint(
        {key: value for key, value in current_catalog(app).items() if not key.startswith("_")}
    )
    return manifest


def select_role(app, text, entry_mode="auto"):
    """入口优先；混合创作请求优先creative，纯业务/规则问题走support。"""
    if entry_mode == "support_only":
        return "support"
    path = Path(app.state.config["agent"]["release_file"])
    if not path.is_absolute():
        path = ROOT / path
    routing = yaml.safe_load(path.read_text())["routing"]
    support = any(term in text for term in routing["support_terms"])
    # “生成进度/生成失败”属于状态问题；生成新图/改画面才是创作。
    reduced = text
    for term in ("生成进度", "生成失败", "生成状态", "生成任务", "拍摄次数"):
        reduced = reduced.replace(term, "")
    creative = any(term in reduced for term in routing["creative_terms"])
    return "support" if support and not creative else "creative"


def complete_cases(report, digest):
    """检查完整逐项证据而非信任汇总布尔值，重复或缺少抽样均拒绝。"""
    dataset = json.loads((ROOT / "resources/agent/m2-cases.json").read_text())
    count = report.get("sample_count")
    rows = report.get("cases")
    if type(count) is not int or not 2 <= count <= 3 or not isinstance(rows, list):
        return False
    expected = {(case["id"], None) for case in dataset["routing"]}
    expected |= {(case["id"], index) for case in dataset["live"] for index in range(1, count + 1)}
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            return False
        key = (row.get("case_id"), row.get("sample"))
        if key not in expected or key in seen or row.get("passed") is not True:
            return False
        if key[1] is not None and (row.get("status") != "succeeded" or row.get("release_digest") != digest):
            return False
        seen.add(key)
    return seen == expected
