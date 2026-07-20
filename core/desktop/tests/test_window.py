"""桌面宠物窗口配置测试（Task 2）。

验证 ``core.desktop.window`` 模块的核心契约：
1. ``create_window()`` 返回的 ``WindowConfig`` 字段符合 spec（无边框/置顶/透明/拖拽/尺寸/标题）。
2. ``create_window()`` 支持自定义 HTML 路径，URL 正确指向该文件。
3. 默认 URL 使用 ``file://`` 协议（pywebview 加载本地文件的标准方式）。
4. 静态资源文件（``index.html`` / ``style.css``）实际存在于 ``static/`` 目录。

关键设计：本测试不依赖 pywebview 实际安装，因为 ``create_window()`` 只构造数据类，
不调用 ``webview.create_window()``。这使测试在 CI 无 GUI 环境也能运行。
"""

from pathlib import Path

from core.desktop.window import WindowConfig, create_window


def test_window_config_defaults():
    """``create_window()`` 返回的 ``WindowConfig`` 默认字段应符合 spec。

    Spec 要求：
    - frameless=True（无边框）
    - on_top=True（始终置顶）
    - transparent=True（透明背景）
    - easy_drag=True（可拖拽）
    - size=(180, 240)（默认尺寸）
    - title="IMA Desktop Pet"
    """
    config = create_window()
    assert isinstance(config, WindowConfig), (
        f"期望 create_window() 返回 WindowConfig，实际返回 {type(config).__name__}"
    )
    assert config.frameless is True, "frameless 应为 True（无边框窗口）"
    assert config.on_top is True, "on_top 应为 True（始终置顶）"
    assert config.transparent is True, "transparent 应为 True（透明背景）"
    assert config.easy_drag is True, "easy_drag 应为 True（启用拖拽）"
    assert config.size == (180, 240), f"size 应为 (180, 240)，实际为 {config.size}"
    assert config.title == "IMA Desktop Pet", (
        f"title 应为 'IMA Desktop Pet'，实际为 {config.title!r}"
    )


def test_window_config_custom_html():
    """传入自定义 html_path 时，``WindowConfig.url`` 应正确指向该文件。"""
    custom_path = Path(__file__).parent.parent / "static" / "index.html"
    config = create_window(html_path=str(custom_path))
    expected_url = custom_path.resolve().as_uri()
    assert config.url == expected_url, (
        f"自定义路径 URL 应为 {expected_url}，实际为 {config.url}"
    )


def test_window_config_url_is_file_scheme():
    """默认 ``WindowConfig.url`` 应使用 ``file://`` 协议。

    pywebview 加载本地 HTML 文件的标准方式是 ``file://`` URL，
    相对路径或裸路径在 macOS WebKit 下可能无法正确加载。
    """
    config = create_window()
    assert config.url.startswith("file://"), (
        f"url 应以 'file://' 开头，实际为 {config.url!r}"
    )


def test_window_config_url_points_to_static_index():
    """默认 ``WindowConfig.url`` 应指向 ``core/desktop/static/index.html``。"""
    config = create_window()
    expected_suffix = "/core/desktop/static/index.html"
    assert config.url.endswith(expected_suffix), (
        f"url 应以 {expected_suffix!r} 结尾，实际为 {config.url!r}"
    )


def test_window_config_hidden_default_false():
    """``WindowConfig.hidden`` 默认应为 False（启动即显示窗口）。

    Spec 要求默认尺寸 180×240，启动即显示；hidden 用于托盘菜单切换显隐。
    """
    config = create_window()
    assert config.hidden is False, "hidden 默认应为 False（启动即显示）"


def test_index_html_exists():
    """``core/desktop/static/index.html`` 文件应实际存在。

    Task 2 应创建该文件作为桌面宠物主页面骨架。
    """
    index_html = Path(__file__).parent.parent / "static" / "index.html"
    assert index_html.exists(), f"index.html 应存在于 {index_html}"
    assert index_html.is_file(), f"{index_html} 应为文件而非目录"


def test_style_css_exists():
    """``core/desktop/static/style.css`` 文件应实际存在。

    Task 2 应创建该文件，包含透明背景与点击穿透关键 CSS。
    """
    style_css = Path(__file__).parent.parent / "static" / "style.css"
    assert style_css.exists(), f"style.css 应存在于 {style_css}"
    assert style_css.is_file(), f"{style_css} 应为文件而非目录"


def test_index_html_contains_pet_img():
    """``index.html`` 应包含 ``<img id="pet-img">`` 元素（spec 要求，GIF 动画替换 Canvas）。"""
    index_html = Path(__file__).parent.parent / "static" / "index.html"
    content = index_html.read_text(encoding="utf-8")
    assert '<img id="pet-img"' in content, (
        "index.html 应包含 <img id=\"pet-img\"> 元素"
    )
    # 默认 src 指向 cats/cat_idle.gif
    assert 'src="cats/cat_idle.gif"' in content, (
        "index.html 默认 src 应为 'cats/cat_idle.gif'"
    )
    # 默认尺寸 120×120
    assert 'width="120"' in content and 'height="120"' in content, (
        "index.html <img> 默认尺寸应为 120×120"
    )


def test_index_html_contains_bubble_div():
    """``index.html`` 应包含隐藏的气泡 div 占位（spec 要求）。"""
    index_html = Path(__file__).parent.parent / "static" / "index.html"
    content = index_html.read_text(encoding="utf-8")
    assert 'id="bubble"' in content, 'index.html 应包含 id="bubble" 的 div'


def test_style_css_contains_pointer_events_none():
    """``style.css`` 应包含全局 ``pointer-events: none``（点击穿透关键）。"""
    style_css = Path(__file__).parent.parent / "static" / "style.css"
    content = style_css.read_text(encoding="utf-8")
    assert "pointer-events: none" in content, (
        "style.css 应包含 'pointer-events: none'（全局点击穿透）"
    )


def test_style_css_contains_transparent_background():
    """``style.css`` 应包含 ``background: transparent``（透明背景关键）。"""
    style_css = Path(__file__).parent.parent / "static" / "style.css"
    content = style_css.read_text(encoding="utf-8")
    assert "background: transparent" in content, (
        "style.css 应包含 'background: transparent'（透明背景）"
    )
