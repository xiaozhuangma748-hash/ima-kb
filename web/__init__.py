"""IMA Web 后台 — FastAPI + 单页 HTML。

用法:
    ima web                   # 启动 Web 服务（127.0.0.1:8501）
    ima web --host 0.0.0.0    # 内网可访问
"""

from .app import create_app

__all__ = ["create_app"]
