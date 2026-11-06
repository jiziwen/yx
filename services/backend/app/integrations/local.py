"""开发适配器；输出带标识的测试卡片，不伪装为模型生成照片。"""

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

from app.integrations.contracts import ImageRequest, ImageResult


class LocalStorage:
    """本地私有文件存储；对象键不能逃逸配置根目录。"""

    def __init__(self, options: dict, settings):
        """初始化当前适配器或错误，不从浏览器接受凭证与权限。"""
        self.root = settings.storage_root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, key: str) -> Path:
        """拒绝路径遍历和绝对路径，调用者只能使用服务端 UUID 对象键。"""
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise ValueError("无效对象键")
        return path

    def put(self, key: str, content: bytes) -> None:
        """原子替换，避免进程崩溃留下半个文件。"""
        path = self.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(content)
        temporary.replace(path)

    def get(self, key: str) -> bytes:
        """读取私有对象；授权由 assets 服务负责。"""
        return self.path(key).read_bytes()

    def delete(self, key: str) -> None:
        """幂等删除，允许恢复清理时重复执行。"""
        self.path(key).unlink(missing_ok=True)


class MockImageProvider:
    """只验证流程的图片插件，不读取人物或调用远程服务。"""

    def __init__(self, options: dict, settings):
        """初始化当前适配器或错误，不从浏览器接受凭证与权限。"""
        self.label = options.get("label", "YINGXU / DEVELOPMENT SAMPLE")

    def generate(self, request: ImageRequest) -> ImageResult:
        """生成可下载的测试卡片；成片元数据明确 development_sample。"""
        x, y = map(int, request.aspect_ratio.split(":"))
        scale = max(1, 800 // max(x, y))
        width, height = x * scale, y * scale
        image = Image.new("RGB", (width, height), "#eee7dd")
        draw = ImageDraw.Draw(image)
        for row in range(height):
            draw.line(
                (0, row, width, row),
                fill=(
                    int(239 - row / height * 35),
                    int(230 - row / height * 45),
                    int(220 - row / height * 35),
                ),
            )
        draw.rectangle((30, 30, width - 30, height - 30), outline="#8b645d", width=2)
        draw.text((50, height // 2 - 35), self.label, fill="#5d3939", font_size=18)
        draw.text(
            (50, height // 2 + 4),
            "Workflow verified. No portrait was generated.",
            fill="#5d3939",
            font_size=14,
        )
        draw.text((50, height - 80), request.request_key[:18], fill="#5d3939", font_size=13)
        output = BytesIO()
        image.save(output, "PNG")
        return ImageResult(output.getvalue(), development_sample=True)


class MockLLMProvider:
    """显式开发样例，仅供无密钥工程验收；不伪装真实模型理解。"""

    def __init__(self, options: dict, settings):
        """初始化当前适配器或错误，不从浏览器接受凭证与权限。"""
        pass

    def draft(self, messages: list[dict]) -> dict:
        """返回显式开发响应，不能提交业务操作。"""
        import json

        facts = json.loads(messages[1]["content"].split("：", 1)[1])
        observations = next(
            (
                m["content"].split("：", 1)[1]
                for m in messages
                if m["content"].startswith("本轮服务端只读查询结果")
            ),
            None,
        )
        text = next(
            m["content"]
            for m in reversed(messages)
            if m["role"] == "user" and not m["content"].startswith("本轮服务端只读查询结果")
        )
        # 显式开发样例命令只用于无付费的端到端验收，不模拟通用自然语言理解。
        if observations:
            evidence = [
                item
                for obs in json.loads(observations)
                if obs["name"] == "search_knowledge" and obs["status"] == "ok"
                for item in (obs.get("data") or {}).get("evidence", [])
            ]
            if evidence:
                return {
                    "outcome": "answer",
                    "reply": "开发样例：" + evidence[0]["text"][:160] + "[1]",
                    "tool_sources": [item["id"] for item in json.loads(observations)],
                    "citations": [evidence[0]["chunk_id"]],
                }
            return {
                "outcome": "answer",
                "reply": "开发样例：已读取项目快照，请以下方查询结果为准。",
                "tool_sources": [item["id"] for item in json.loads(observations)],
            }
        if text == "查询项目状态":
            return {
                "tool_calls": [
                    {"name": item["name"], "arguments": {}}
                    for item in facts.get("read_tools", [])
                    if item["name"] in {"get_entitlements", "get_job_status"}
                ]
            }
        if text.startswith("查询知识："):
            return {
                "tool_calls": [
                    {"name": "search_knowledge", "arguments": {"query": text.split("：", 1)[1][:160]}}
                ]
            }
        if text.startswith("查询项目历史："):
            return {
                "tool_calls": [
                    {"name": "search_project_history", "arguments": {"query": text.split("：", 1)[1][:80]}}
                ]
            }
        if text.startswith("整理需求卡："):
            labels = {field["label"]: field["key"] for field in facts["memory"].get("field_definitions", [])}
            fields = {}
            for part in text.split("：", 1)[1].split("；"):
                label, separator, value = part.partition("=")
                if separator and label in labels:
                    fields[labels[label]] = value[:160]
            return {
                "outcome": "answer",
                "reply": "开发样例：请检查需求卡建议，确认后才会保存。",
                "brief_suggestion": fields,
            }
        if text.startswith("请记住："):
            return {
                "outcome": "answer",
                "reply": "开发样例：请确认要记住的原话要求。",
                "memory_suggestion": [text.split("：", 1)[1][:160]],
            }
        if facts.get("role") == "support":
            return {
                "outcome": "answer",
                "reply": "开发样例：这里可以查询规则或请求人工客服。创作提案请返回工作室整理。",
            }
        notes = facts["draft"]["notes"]
        if text == "测试目录切换：风格参考换成第二张，第一张不要了":
            gallery = facts["selection"]["active_catalog_gallery"]
            return {
                "outcome": "plan_ready",
                "reply": "开发样例：已换为第二张风格参考，人物照片保持不变。",
                "proposal": {
                    "intent": "user_request",
                    gallery["target_field"]: [gallery["items"][1]["id"]],
                },
            }
        if text.startswith("测试自由切换："):
            target = {"设计写真": "portrait", "文字创作": "text", "修改照片": "edit"}.get(
                text.split("：", 1)[1]
            )
            if target:
                return {
                    "outcome": "plan_ready",
                    "reply": "开发样例：已按本轮意图调整创作方式，等待你确认生成。",
                    "proposal": {
                        "intent": "user_request",
                        "mode": target,
                        "subject_only": False,
                        "notes": "按本轮新意图创作紫色花园",
                        "change": "调整光线",
                    },
                }
        if text in {"只替换人物", "把人物替换就行了"}:
            return {
                "outcome": "plan_ready",
                "reply": "开发样例：只替换人物，保留底图站位、朝向、姿势、构图和色调。",
                "proposal": {"intent": "user_request", "notes": text},
            }
        if text.startswith("测试明确修改："):
            return {
                "outcome": "plan_ready",
                "reply": "开发样例：明确修改已整理，请检查确认卡。",
                "proposal": {
                    "intent": "user_request",
                    "mode": "text",
                    "notes": (notes + "；" + text.split("：", 1)[1])[:1000],
                },
            }
        return {
            "outcome": "plan_ready",
            "reply": "开发样例：已将原话整理为便签。真实需求理解需要启用后台 LLM。",
            "questions": [],
            "proposal": {"notes": (notes + "；" + text if notes else text)[:1000]},
        }

    def stream_complete(self, messages, on_content, timeout_seconds=None):
        """显式本地样例流；只有测试命令延时，不伪装成真实模型 token。"""
        import json
        from time import sleep

        from app.integrations.contracts import LLMResult

        data = self.draft(messages)
        slow = any(m["role"] == "user" and m["content"].startswith("测试流式回复") for m in messages)
        if slow:
            data["reply"] = (
                "开发样例：这段文字来自本地测试流，用来验证回复逐步出现、断线恢复和最终消息替换，照片仍须你确认才会生成。"
            )
        raw = json.dumps(data, ensure_ascii=False)
        if slow:
            encoded = json.dumps(data["reply"], ensure_ascii=False)
            start = raw.index(encoded)
            on_content(raw[: start + 1])
            for char in encoded[1:-1]:
                on_content(char)
                sleep(0.08)
            on_content(raw[start + len(encoded) - 1 :])
        else:
            for index in range(0, len(raw), 100):
                on_content(raw[index : index + 100])
        return LLMResult(data)
