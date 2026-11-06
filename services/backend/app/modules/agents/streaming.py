"""从不完整 JSON 中提取顶层可见 reply；没有截取任意字段的正则或隐藏推理。"""

import json


def string_prefix(value: str) -> str | None:
    """只解码完整转义/代理对；半个 Unicode 转义留待后续，不输出替换乱码。"""
    if not value.startswith('"'):
        return None
    end = 1
    while end < len(value):
        char = value[end]
        if char == '"':
            return json.loads(value[: end + 1])
        if ord(char) < 32:
            return None
        if char == "\\":
            if end + 1 >= len(value):
                break
            escape = value[end + 1]
            if escape == "u":
                if len(value) < end + 6:
                    break
                code = int(value[end + 2 : end + 6], 16)
                width = 6
                if 0xD800 <= code <= 0xDBFF:
                    if len(value) < end + 12:
                        break
                    if (
                        value[end + 6 : end + 8] != "\\u"
                        or not 0xDC00 <= int(value[end + 8 : end + 12], 16) <= 0xDFFF
                    ):
                        return None
                    width = 12
                elif 0xDC00 <= code <= 0xDFFF:
                    return None
                end += width
                continue
            if escape not in '"\\/bfnrt':
                return None
            end += 2
            continue
        if 0xD800 <= ord(char) <= 0xDFFF:
            return None
        end += 1
    return json.loads(value[:end] + '"')


def reply_prefix(raw: str) -> str | None:
    """要求已知 outcome；仅顶层 reply 可流出，任意顺序的前置完整字段可跳过。"""
    decoder, offset, outcome, seen = json.JSONDecoder(), 0, None, set()
    raw = raw.lstrip()
    if not raw.startswith("{"):
        return None
    offset = 1
    try:
        while True:
            offset += len(raw[offset:]) - len(raw[offset:].lstrip())
            key, offset = decoder.raw_decode(raw, offset)
            if not isinstance(key, str) or key in seen:
                return None
            seen.add(key)
            offset += len(raw[offset:]) - len(raw[offset:].lstrip())
            if raw[offset] != ":":
                return None
            offset += 1
            offset += len(raw[offset:]) - len(raw[offset:].lstrip())
            if key == "reply":
                if outcome not in {"answer", "needs_input", "plan_ready"} or "tool_calls" in seen:
                    return None
                result = string_prefix(raw[offset:])
                return result if result is not None and len(result) <= 1200 else None
            value, offset = decoder.raw_decode(raw, offset)
            if key == "outcome":
                outcome = value if isinstance(value, str) else None
            offset += len(raw[offset:]) - len(raw[offset:].lstrip())
            if raw[offset] != ",":
                return None
            offset += 1
    except (ValueError, IndexError, TypeError):
        return None
