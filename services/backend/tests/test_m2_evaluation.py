"""评测差异按抽样编号比较，不能用最后一题覆盖早期失败。"""

from evals.compare import differences


def test_repeated_sample_difference_retains_prior_failure():
    """同题第一次失败、第二次成功仍能单独追踪第一次修复。"""
    baseline = {
        "cases": [
            {"case_id": "citation", "sample": 1, "passed": False},
            {"case_id": "citation", "sample": 2, "passed": True},
        ]
    }
    candidate = {
        "cases": [
            {"case_id": "citation", "sample": 1, "passed": True},
            {"case_id": "citation", "sample": 2, "passed": True},
        ]
    }
    assert differences(baseline, candidate) == [
        {"case_id": "citation", "sample": 1, "before": False, "after": True}
    ]
