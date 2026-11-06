"""可信、可插拔的图片提示词编译；保存方案时冻结，Worker不重新拼接冲突指令。"""

import json
import re
from hashlib import sha256

from app.core.plugins import load_symbol

DEFAULT_CONFIG = {
    "entrypoint": "app.modules.executions.prompts:compose",
    "version": "creation-v5-zh",
    "options": {},
}


def visual_requirements(value, mode):
    """兼容旧聊天产生的文生图路由说明；只移除完整固定句式，保留画面限制与引号文字。"""
    value = value.strip()
    if mode != "text":
        return value
    value = re.sub(r"^纯文字生成(?:一张)?", "", value, count=1)
    parts = re.split(r"(?<=[，,；;。\n])", value)
    routing = r"(?:人物)?不使用(?:已上传的?|上传的?)?(?:人物参考照片|人物参考照|参考照片|参考图)"
    return "".join(
        part for part in parts if not re.fullmatch(routing, part.strip().rstrip("，,；;。"))
    ).strip("，,；;。\n ")


def image_directions(spec, inputs):
    """按实际文件序号说明图片用途和人物位置，不向供应商泄露内部资产或人物ID。"""
    subjects = list(dict.fromkeys(item["subject_id"] for item in inputs if item.get("subject_id")))
    positions = {
        item["subject_id"]: {"left": "左侧人物", "right": "右侧人物", "only": "唯一人物"}[item["position"]]
        for item in spec.get("subject_bindings", [])
    }
    lines = []
    for index, item in enumerate(inputs, 1):
        if item["role"] == "base":
            purpose = "底图，以此图为基础修改"
        elif item["role"] == "style":
            purpose = "风格参考，仅借鉴色调、光线和氛围，不复制人物身份与构图"
        else:
            subject = item.get("subject_id")
            target = (
                "底图中的" + positions[subject]
                if subject in positions
                else f"人物{subjects.index(subject) + 1}"
                if subject in subjects
                else "人物"
            )
            purpose = f"{target}的参考照，仅用于人物身份与面部特征"
        lines.append(f"第{index}张图是{purpose}。")
    return "\n".join(lines)


def compose(spec, inputs, options):
    """只发送中文画面要求与必要图片指引；套系名称、路由说明和内部字段留在应用内。"""
    mode = spec["mode"]
    directions = image_directions(spec, inputs)
    if mode == "template" and spec.get("subject_only"):
        instructions = (
            "只将底图中指定人物的身份与面部特征替换为对应参考人物，自然融入原照片。"
            "严格保留底图人物的站位、身体与头部朝向、视线、姿势、动作、画面占比和镜头距离；"
            "保留拍摄角度、构图、背景结构、物体位置、服装造型、光线、曝光、白平衡与色调。"
            "不要镜像、翻转、移动或放大人物，不拉近、裁切、重新布景、添加暖色、改变光线或换装。"
            "不要照搬人物参考照的姿势、构图、服装、背景、光线和色调。"
        )
        return f"{instructions}\n{directions}".strip()
    instructions = {
        "template": "将底图中的指定人物替换为对应参考人物；除下方明确要求修改的部分外，保留底图的站位、朝向、姿势、画面占比、构图与色调，不照搬人物参考照的姿势和构图。",
        "portrait": "根据人物参考照创作新的写真，遵循下方场景与构图要求。",
        "edit": "只修改底图中下方明确要求调整的部分，其余细节保持不变。",
        "text": "",
    }[mode]
    notes = visual_requirements(spec.get("notes", ""), mode)
    details = [notes]
    if mood := spec.get("mood", "").strip():
        if mood not in notes:
            details.append(f"画面氛围：{mood}。")
    if mode == "edit":
        if spec.get("keep"):
            details.append(f"保留：{'、'.join(spec['keep'])}。")
        details.append(f"修改要求：{spec.get('change', '')}")
    return "\n".join(part for part in [instructions, *details, directions] if part)


def prompt_policy_hash(config):
    """当前编译规则的摘要用于重建未确认卡片，已确认任务始终使用冻结文本。"""
    return sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()


def freeze_prompts(spec, config):
    """入口与选项仅来自可信部署；逐交付项实际提示词纳入方案content_hash。"""
    builder = load_symbol(config["entrypoint"])
    for item in spec["items"]:
        value = builder(spec, item["inputs"], config.get("options", {}))
        if not isinstance(value, str) or not value.strip() or len(value) > 16000:
            raise ValueError("invalid creation prompt plugin result")
        item["prompt"] = value
    spec["prompt_version"] = config["version"]
    spec["prompt_policy_hash"] = prompt_policy_hash(config)


def legacy_prompt(spec, inputs):
    """已确认旧任务沿用原编译语义，部署不能偷偷改变既有外部执行。"""
    mode = spec.get("mode", "portrait")
    directions = {
        "template": "Use the base image's scene and composition. Replace only the explicitly bound subjects using their person references.",
        "portrait": "Design a new portrait using person references for identity; style inputs guide atmosphere, not identity.",
        "edit": f"Edit the base image. Preserve: {', '.join(spec.get('keep', []))}. Change: {spec.get('change', '')}.",
        "text": "Create an original image from the text. No identity reference images are supplied.",
    }
    roles = "; ".join(
        f"Image {index + 1}: {item.get('role', 'person')}, subject {item.get('subject_id', 'none')}"
        for index, item in enumerate(inputs)
    )
    return f"{spec['style_name']}; {spec['mood']}; {spec['notes']}. {directions[mode]} {roles}. Bindings: {spec.get('subject_bindings', [])}"
