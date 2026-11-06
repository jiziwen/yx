"""公开发布知识只读工具；embedding在事务外，权限/来源在数据库保护内校验。"""

from app.integrations.contracts import ProviderFailure

from .schemas import SearchArguments, SearchResult
from .service import embedder, search, spec


class KnowledgeSearchTool:
    """创作/客服都可检索面向客户的知识，不接触项目照片或未发布内容。"""

    name, version, title = "search_knowledge", "1", "查询已发布知识"
    role, roles, scope, read_only = "creative", ("creative", "support"), "published_knowledge", True
    requires = ("knowledge",)
    input_model, output_model = SearchArguments, SearchResult

    def prepare(self, app, arguments, timeout_ms):
        """向量查询不可用时采用固定评测覆盖的关键词降级，策略明确返回。"""
        from evals.m25_runtime import check as check_experiment

        check_experiment(app.state.settings, paid=True)
        try:
            vectors, _ = embedder(app).embed([arguments.query], timeout_seconds=timeout_ms / 1000)
            return vectors[0], spec(app)
        except ProviderFailure:
            if not app.state.config["knowledge"]["keyword_fallback"]:
                raise
            return None, spec(app)

    def read(self, app, db, scope, arguments, prepared=None):
        """只读取有效发布指针，输入无文档身份或可扩展权限。"""
        vector, embedding_spec = prepared or (None, spec(app))
        return search(app, db, arguments.query, vector, embedding_spec)
