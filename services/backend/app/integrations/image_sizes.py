"""常用尺寸仅作默认值；其他画幅及明确像素尺寸直接交给供应商。"""

from app.core.errors import DomainError

IMAGE_SIZES = {
    "3:4": "768x1024",
    "4:3": "1024x768",
    "1:1": "1024x1024",
    "2:3": "832x1248",
    "3:2": "1248x832",
    "16:9": "1536x864",
    "9:16": "864x1536",
}


def output_size(choice, sizes=None):
    """保留明确像素尺寸；其他比例按整数倍换算，不检查供应商尺寸白名单或像素限制。"""
    value = choice.replace("×", "x")
    if "x" in value:
        return value
    if value in (sizes or {}):
        return sizes[value]
    if value in IMAGE_SIZES:
        return IMAGE_SIZES[value]
    try:
        width, height = map(int, value.split(":"))
        scale = max(1, 1024 // max(width, height))
    except (ValueError, ZeroDivisionError) as exc:
        raise DomainError("INVALID_SPEC", "画幅请填写宽:高，像素尺寸请填写宽x高", 422) from exc
    return f"{width * scale}x{height * scale}"


def image_capabilities(capabilities):
    """历史画幅配置不再是限制；向页面和Agent统一公开不限尺寸的应用策略。"""
    return {**capabilities, "aspect_ratios": list(IMAGE_SIZES), "arbitrary_size": True}
