"""逐题、逐次抽样比较不可变评测报告；不发请求，不覆盖原始模型结果。"""

import argparse
import json
from pathlib import Path


def differences(before, after):
    """用case_id+sample定位，避免同题最后一次成功掩盖早先失败。"""
    previous = {(case["case_id"], case.get("sample", 0)): case for case in before["cases"]}
    results = []
    for case in after["cases"]:
        identity = (case["case_id"], case.get("sample", 0))
        old = previous.get(identity)
        if old is None or old.get("passed") != case.get("passed"):
            results.append(
                {
                    "case_id": identity[0],
                    "sample": identity[1] or None,
                    "before": old.get("passed") if old else None,
                    "after": case.get("passed"),
                }
            )
    return results


def main():
    """比较文件与原报告并排保存，保留失败及其准确抽样编号。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--candidate", required=True)
    args = parser.parse_args()
    baseline = json.loads(Path(args.baseline).read_text())
    path = Path(args.candidate)
    candidate = json.loads(path.read_text())
    report = {
        "baseline_report": str(Path(args.baseline).resolve()),
        "candidate_report": str(path.resolve()),
        "baseline_release": baseline.get("candidate_release"),
        "candidate_release": candidate.get("candidate_release"),
        "case_differences": differences(baseline, candidate),
        "all_samples_passed": candidate["passed"],
        "quality_approved": False,
    }
    target = path.with_name("comparison.json")
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(target)


if __name__ == "__main__":
    main()
