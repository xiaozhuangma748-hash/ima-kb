"""桌面宠物窗口配置（Task 2）。

零侵入约束：
- 本模块属于 ``core/desktop/`` 新增模块，不修改项目任何现有文件。
- WindowConfig 是纯数据类，不依赖 pywebview 实际安装，可在无依赖环境测试。
- launch_window() 才会真正调用 pywebview，仅由 app.main() 在依赖齐全时调用。

设计要点：
- create_window() 返回 WindowConfig（不直接调用 webview.create_window()），
  这使测试可以在 pywebview 未安装时验证窗口配置。
- launch_window(config) 接收 WindowConfig 并真正启动 pywebview 窗口。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

__all__ = ["WindowConfig", "create_window", "launch_window"]

# 默认窗口尺寸：宽 180，高 240（GIF 120×120 + 外边距 12×2 + 顶部气泡预留约 96px）
DEFAULT_SIZE: Tuple[int, int] = (180, 240)

# 默认窗口标题
DEFAULT_TITLE: str = "IMA Desktop Pet"


@dataclass
class WindowConfig:
    """pywebview 窗口配置数据类。

    字段对应 ``webview.create_window()`` 的关键参数，但不直接持有 webview 对象，
    便于在 pywebview 未安装时构造与测试。

    Attributes:
        url: 待加载的页面 URL（``file://`` 协议指向 ``static/index.html``）。
        title: 窗口标题。
        frameless: 是否无边框（透明置顶窗口必须 True）。
        on_top: 是否始终置顶。
        transparent: 是否透明背景（macOS WebKit 与 Windows Edge WebView2 均支持）。
        easy_drag: 是否启用 pywebview 内置拖拽（鼠标按住 body 任意位置可拖动）。
        size: 窗口尺寸 (width, height)，默认 (180, 240)。
        hidden: 是否隐藏窗口（False 表示启动即显示）。
    """

    url: str
    title: str = DEFAULT_TITLE
    frameless: bool = True
    on_top: bool = True
    transparent: bool = True
    easy_drag: bool = True
    size: Tuple[int, int] = DEFAULT_SIZE
    hidden: bool = False


def _default_html_path() -> Path:
    """返回默认 HTML 页面路径 ``core/desktop/static/index.html``。"""
    return Path(__file__).parent / "static" / "index.html"


def _path_to_file_url(path: Path) -> str:
    """将本地路径转换为 ``file://`` URL。

    使用 ``pathlib.Path.as_uri()``，自动处理跨平台路径分隔符与绝对路径要求。
    """
    return path.resolve().as_uri()


def create_window(html_path: Optional[str] = None) -> WindowConfig:
    """构造窗口配置（不调用 pywebview）。

    Args:
        html_path: 可选的 HTML 页面路径。未提供时使用 ``core/desktop/static/index.html``。

    Returns:
        WindowConfig 实例，包含 pywebview 启动窗口所需全部参数。

    Note:
        本函数不依赖 pywebview，可在无依赖环境测试。
        实际启动窗口由 :func:`launch_window` 完成。
    """
    path = Path(html_path) if html_path else _default_html_path()
    url = _path_to_file_url(path)
    return WindowConfig(url=url)


def launch_window(config: WindowConfig) -> None:
    """根据配置启动 pywebview 窗口（实际调用 webview API）。

    本函数仅在 :func:`core.desktop.app.main` 中、且 pywebview 已安装时调用。
    测试不直接调用此函数（用 mock 验证）。

    Args:
        config: 由 :func:`create_window` 构造的窗口配置。

    Raises:
        ImportError: pywebview 未安装时抛出（应由调用方在调用前检测）。
    """
    import webview  # 延迟导入：仅在真正启动窗口时才要求 pywebview 可用

    webview.create_window(
        title=config.title,
        url=config.url,
        width=config.size[0],
        height=config.size[1],
        frameless=config.frameless,
        on_top=config.on_top,
        transparent=config.transparent,
        easy_drag=config.easy_drag,
        hidden=config.hidden,
    )
    webview.start()
