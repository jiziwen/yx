"""M2.5 隔离实验清单、逐批费用对账与30天全目录清理；从不调用收费接口。"""

import argparse
import fcntl
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1] / ".data/evals/m25"


def timestamp():
    """统一UTC截止时间。"""
    return datetime.now(timezone.utc)


def create(root=ROOT):
    """建立独立实验目录，不读取主项目、照片、Key或已有账单。"""
    run_id = str(uuid4())
    folder = root / run_id
    folder.mkdir(parents=True, mode=0o700)
    for name in ("objects", "reports", "cache", "backups"):
        (folder / name).mkdir(mode=0o700)
    value = {
        "id": run_id,
        "created_at": timestamp().isoformat(),
        "expires_at": (timestamp() + timedelta(days=30)).isoformat(),
        "budget_cny": 100,
        "quality_approved": False,
        "readiness": {
            "adult_consent": False,
            "two_theme_rights": False,
            "dedicated_test_key": False,
            "provider_processing_disclosed": False,
            "engineering_passed": False,
        },
        "batches": [],
        "samples": [
            {
                "id": f"B{i + 1:02}",
                "person": f"P{i // 4 + 1}",
                "theme": f"T{i % 4 // 2 + 1}",
                "output": i % 2 + 1,
                "status": "pending",
                "identity_rating": None,
                "delivery_rating": None,
            }
            for i in range(12)
        ],
    }
    (folder / "manifest.json").write_text(json.dumps(value, ensure_ascii=False, indent=2))
    return value


def folder_for(run_id, root=ROOT):
    """只允许工具根内的UUID目录，拒绝软链接和已过期/已清理备份恢复。"""
    if str(UUID(run_id)) != run_id:
        raise ValueError("invalid run id")
    folder = root / run_id
    if folder.is_symlink() or (root / "tombstones" / run_id).exists():
        raise ValueError("expired or revoked experiment")
    if folder.resolve().parent != root.resolve():
        raise ValueError("invalid isolated folder")
    return folder


def begin_batch(value, estimate, purpose):
    """未知费用阻止下一批；100元为规划预算而非供应商金额硬封顶。"""
    if timestamp() >= datetime.fromisoformat(value["expires_at"]):
        raise ValueError("实验已过期")
    if not all(value["readiness"].values()):
        raise ValueError("授权、主题、独立Key、供应商说明和工程检查尚未就绪")
    if any(batch["actual_cny"] is None for batch in value["batches"]):
        raise ValueError("上一批实际费用未知，必须先核账")
    actual = sum(batch["actual_cny"] for batch in value["batches"])
    if (
        not __import__("math").isfinite(estimate)
        or estimate < 0
        or actual + estimate > value["budget_cny"]
        or not purpose.strip()
    ):
        raise ValueError("预算不足或调用清单不完整")
    batch = {
        "id": str(uuid4()),
        "purpose": purpose,
        "estimate_cny": estimate,
        "actual_cny": None,
        "bill_reference": None,
        "created_at": timestamp().isoformat(),
    }
    value["batches"].append(batch)
    return batch


def reconcile(value, batch_id, actual, bill):
    """必须填写实际账单依据；失败/重做/诊断等均计入，超预算也如实记录。"""
    if not __import__("math").isfinite(actual) or actual < 0 or not bill.strip():
        raise ValueError("实际费用和账单依据缺失")
    batch = next(batch for batch in value["batches"] if batch["id"] == batch_id)
    if batch["actual_cny"] is not None:
        raise ValueError("已对账记录不可覆盖，请单独记录差额批次")
    batch.update(actual_cny=actual, bill_reference=bill)


def ensure_idle(folder):
    """关批次前必须停隔离服务且所有收费队列已终结，未知任务不能跨批核账。"""
    import sqlite3

    database = folder / "database.db"
    if not database.exists():
        return
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in ("jobs", "agent_runs", "knowledge_index_jobs"):
            if (
                table in tables
                and connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE status NOT IN ('succeeded','failed','cancelled')"
                ).fetchone()[0]
            ):
                raise ValueError("仍有未终结或待核对任务，请完成核对后再核账")


def cleanup(root=ROOT):
    """到期删除本轮目录内照片、数据库、报告、缓存和备份，外部墓碑拒绝恢复复活。"""
    removed = []
    root.mkdir(parents=True, exist_ok=True)
    for folder in root.iterdir():
        if folder.is_symlink() or not folder.is_dir() or folder.name == "tombstones":
            continue
        manifest = folder / "manifest.json"
        if not manifest.exists():
            continue
        value = json.loads(manifest.read_text())
        if timestamp() < datetime.fromisoformat(value["expires_at"]):
            continue
        (root / "tombstones").mkdir(exist_ok=True)
        (root / "tombstones" / folder.name).write_text(timestamp().isoformat())
        shutil.rmtree(folder)
        removed.append(folder.name)
    return removed


def main():
    """操作清单需人工提供实测与账单，工具不伪造批准或启动生成。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=["prepare", "report", "begin-batch", "reconcile", "cleanup", "export-candidate", "launch"],
    )
    parser.add_argument("--run")
    parser.add_argument("--amount", type=float)
    parser.add_argument("--note")
    parser.add_argument("--batch")
    parser.add_argument("--candidate")
    args = parser.parse_args()
    if args.action in {"export-candidate", "launch"}:
        from evals.m25_runtime import export_candidate, launch

        if args.action == "export-candidate":
            print(json.dumps(export_candidate(args.run, args.candidate)))
        else:
            launch(args.run)
    elif args.action == "prepare":
        print(json.dumps(create(), ensure_ascii=False, indent=2))
    elif args.action == "cleanup":
        print(json.dumps(cleanup()))
    else:
        folder = folder_for(args.run)
        with (folder / ".lock").open("a") as lock, (folder / ".runtime-lock").open("a") as runtime_lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if args.action in {"begin-batch", "reconcile"}:
                try:
                    fcntl.flock(runtime_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise ValueError("请先停止隔离服务再核账或打开下一批") from exc
            path = folder / "manifest.json"
            value = json.loads(path.read_text())
            if args.action in {"begin-batch", "reconcile"}:
                ensure_idle(folder)
            if args.action == "begin-batch":
                begin_batch(value, args.amount, args.note)
            elif args.action == "reconcile":
                reconcile(value, args.batch, args.amount, args.note)
            path.write_text(json.dumps(value, ensure_ascii=False, indent=2))
            print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
