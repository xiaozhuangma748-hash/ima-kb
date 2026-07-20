"""Mobile 同步服务（可选模块，Task 11 占位实现）。

零侵入约束：
- 本模块属于 ``core/desktop/`` 新增模块，不修改项目任何现有文件。
- 仅依赖 fastapi/uvicorn（可选），未安装时 ``is_mobile_server_available`` 返回 False，
  ``app.main()`` 会跳过启动，不影响桌面宠物主流程。

说明：
- 当前为最小可用实现：提供健康检查与配置同步端点，便于局域网内移动端查看。
- 未安装 fastapi/uvicorn 时整体降级为不可用（静默）。
"""
from __future__ import annotations

import logging
import threading
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

__all__ = ["is_mobile_server_available", "start_mobile_server"]

_DEFAULT_PORT = 8765


def is_mobile_server_available() -> bool:
    """检测 fastapi 与 uvicorn 是否可用。"""
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
        return True
    except Exception:
        return False


def _build_app():
    """构造 FastAPI 应用（延迟导入，未安装时不触发）。"""
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    app = FastAPI(title="IMA Desktop Pet Sync", docs_url=None, redoc_url=None)

    @app.get("/health")
    def health():
        return JSONResponse({"ok": True, "service": "ima-desktop-pet"})

    @app.get("/settings")
    def get_settings():
        try:
            from core.desktop.settings import DesktopPetSettings
            return DesktopPetSettings.load().to_dict()
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    return app


def start_mobile_server(port: int = _DEFAULT_PORT) -> Tuple[int, threading.Thread]:
    """在后台线程启动 Mobile 同步服务。

    Args:
        port: 监听端口（默认 8765）。

    Returns:
        (port, thread)：实际端口与运行线程。

    Raises:
        RuntimeError: fastapi/uvicorn 未安装。
    """
    if not is_mobile_server_available():
        raise RuntimeError("fastapi/uvicorn 未安装")

    import uvicorn

    app = _build_app()
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True, name="mobile-sync")
    thread.start()
    logger.info(f"Mobile 同步服务已启动: http://0.0.0.0:{port}/health")
    return port, thread
