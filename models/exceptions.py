class ClientDisconnectedError(Exception):
    """客户端断开连接异常"""
    pass

class QuotaExceededError(Exception):
    """Raised when the AI Studio UI indicates the account is out of free generations."""
    pass