"""业务错误契约：只公开可操作原因，不泄露供应商及内部凭证。"""


class DomainError(Exception):
    """携带稳定错误码与 HTTP 状态，由 API 统一包装 request_id。"""

    def __init__(self, code: str, message: str, status: int = 409):
        """初始化当前适配器或错误，不从浏览器接受凭证与权限。"""
        self.code, self.message, self.status = code, message, status
        super().__init__(message)
