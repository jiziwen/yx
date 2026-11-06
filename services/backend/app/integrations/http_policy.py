"""上游 HTTP 退避仅暂停通道新提交，不作为重发已有任务的理由。"""

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from math import ceil


def retry_after_seconds(value: str | None) -> int | None:
    """解析标准秒数或 HTTP 日期；不等待、不回显供应商头。"""
    if not value:
        return None
    try:
        if value.strip().isdigit():
            return max(1, min(int(value), 86400 * 365))
        date = parsedate_to_datetime(value)
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        return max(1, min(ceil((date - datetime.now(timezone.utc)).total_seconds()), 86400 * 365))
    except (ValueError, TypeError, OverflowError):
        return None
