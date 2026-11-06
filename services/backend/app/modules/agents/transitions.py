"""可撤销创作意图的衔接；转换目录用途，不扩展私有素材或生成权限。"""

import re

SUBJECT_ONLY_NOTES = "只替换为已选人物参考中的人物；保留底图人物站位、朝向、姿势、画面占比、构图、背景、服装和色调，不镜像、不拉近或重新构图。"


def explicit_subject_only(text):
    """仅兜底无歧义的直接短指令；复杂语义、否定、疑问仍交给LLM理解。"""
    value = re.sub(r"[\s，,。.!！]", "", text)
    return bool(
        re.fullmatch(
            r"(?:请|帮我|麻烦)?(?:只(?:要)?(?:把)?(?:替换|更换|换)(?:一下)?(?:人物|人|主角)|(?:只)?把(?:人物|人|主角)(?:替换|更换|换)(?:一下)?(?:就行|即可|就可以)(?:了)?)(?:其他(?:都)?(?:不变|不动|保持原样))?",
            value,
        )
    )


def normalize_transition(answer, context):
    """模型显式改模式时转接当前图库选择；旧版错填另一用途的镜头也归位。"""
    proposal = answer.proposal
    if proposal is None:
        return
    facts = context["facts"]
    original = facts["draft"]
    same_style = proposal.style_id in (None, original["style_id"])
    selected = original["style_shot_ids"] if original["mode"] == "portrait" else original["shot_ids"]
    direct = (
        proposal.intent == "user_request"
        and not facts.get("vision")
        and explicit_subject_only(context.get("text", ""))
        and same_style
        and bool(selected)
        and original["mode"] in {"portrait", "template"}
    )
    if direct:
        proposal.mode, proposal.subject_only = "template", True
        proposal.notes, proposal.mood = SUBJECT_ONLY_NOTES, "沿用底图色调与光线"
    target = proposal.mode or original["mode"]
    if target == "text" and proposal.notes is not None:
        from app.modules.executions.prompts import visual_requirements

        proposal.notes = visual_requirements(proposal.notes, target)
    if proposal.subject_only is True and target != "template":
        raise ValueError("subject-only replacement requires template base")
    if proposal.mode is None or proposal.mode == original["mode"]:
        return
    if target in {"template", "portrait"}:
        field = "shot_ids" if target == "template" else "style_shot_ids"
        other = "style_shot_ids" if target == "template" else "shot_ids"
        # 显式空数组表示取消选择，不得又悄悄选回；切换套系不带旧套系镜头。
        values = getattr(proposal, field)
        if values is None:
            values = getattr(proposal, other)
            if values is None and same_style:
                values = selected
                if not values and original["mode"] in {"text", "edit"}:
                    values = original["style_shot_ids"]
            setattr(proposal, field, values or [])
        setattr(proposal, other, [])
    if proposal.subject_only is None:
        proposal.subject_only = target == "template"
    if target != "template":
        proposal.subject_only = False
