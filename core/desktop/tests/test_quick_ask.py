"""快速问答气泡测试（Task 7）。

验证 ``static/index.html`` / ``static/pet.js`` / ``static/style.css`` 的快速问答
气泡契约（不实际启动 pywebview，仅做内容契约校验）：

1. ``index.html`` 含 ``#bubble-input-area`` / ``#bubble-input`` / ``#bubble-answer``
   / ``#bubble-citations`` 四个子元素，且输入框有 ``placeholder="问点什么？"``。
2. ``pet.js`` 含 ``setupQuickAsk`` / ``submitQuickAsk`` / ``escapeHtml`` 函数，含
   ``dblclick`` 监听与 ``window.pywebview.api.ask`` 调用，含增强版引用 ``data-doc-id``。
3. ``style.css`` 含 ``#bubble-input`` / ``#bubble-answer`` / ``#bubble-citations`` 样式。

测试以"内容包含"方式验证，与 ``test_renderer.py`` 风格保持一致。
"""
from __future__ import annotations

from pathlib import Path

# 资源目录
_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
_INDEX_HTML_PATH = _STATIC_DIR / "index.html"
_PET_JS_PATH = _STATIC_DIR / "pet.js"
_STYLE_CSS_PATH = _STATIC_DIR / "style.css"


def _read_html() -> str:
    return _INDEX_HTML_PATH.read_text(encoding="utf-8")


def _read_js() -> str:
    return _PET_JS_PATH.read_text(encoding="utf-8")


def _read_css() -> str:
    return _STYLE_CSS_PATH.read_text(encoding="utf-8")


# === index.html 契约 ===

def test_index_html_contains_bubble_input_area():
    """``index.html`` 应含 ``id="bubble-input-area"`` 子元素。"""
    content = _read_html()
    assert 'id="bubble-input-area"' in content, (
        "index.html 应包含 id=\"bubble-input-area\""
    )


def test_index_html_contains_bubble_input():
    """``index.html`` 应含 ``id="bubble-input"`` 输入框，且 placeholder 正确。"""
    content = _read_html()
    assert 'id="bubble-input"' in content, (
        "index.html 应包含 id=\"bubble-input\""
    )
    assert 'placeholder="问点什么？"' in content, (
        "输入框 placeholder 应为 '问点什么？'"
    )


def test_index_html_contains_bubble_answer():
    """``index.html`` 应含 ``id="bubble-answer"`` 答案区。"""
    content = _read_html()
    assert 'id="bubble-answer"' in content, (
        "index.html 应包含 id=\"bubble-answer\""
    )


def test_index_html_contains_bubble_citations():
    """``index.html`` 应含 ``id="bubble-citations"`` 引用区。"""
    content = _read_html()
    assert 'id="bubble-citations"' in content, (
        "index.html 应包含 id=\"bubble-citations\""
    )


# === pet.js 契约 ===

def test_pet_js_contains_setup_quick_ask():
    """``pet.js`` 应含 ``function setupQuickAsk`` 函数。"""
    content = _read_js()
    assert "function setupQuickAsk" in content, (
        "pet.js 应包含 'function setupQuickAsk'"
    )


def test_pet_js_contains_dblclick_listener():
    """``pet.js`` 应含 ``dblclick`` 事件监听（双击宠物图像触发气泡）。"""
    content = _read_js()
    assert "dblclick" in content, "pet.js 应包含 'dblclick' 事件监听"


def test_pet_js_contains_submit_quick_ask():
    """``pet.js`` 应含 ``submitQuickAsk`` 函数与 ``window.pywebview.api.ask`` 调用。"""
    content = _read_js()
    assert "function submitQuickAsk" in content, (
        "pet.js 应包含 'function submitQuickAsk'"
    )
    assert "window.pywebview.api.ask" in content, (
        "submitQuickAsk 应通过 window.pywebview.api.ask 调用 Python 后端"
    )


def test_pet_js_contains_escape_html():
    """``pet.js`` 应含 ``escapeHtml`` 函数（XSS 防护）。"""
    content = _read_js()
    assert "function escapeHtml" in content, (
        "pet.js 应包含 'function escapeHtml'（XSS 防护）"
    )


def test_pet_js_contains_show_citations_enhanced():
    """``pet.js`` 增强版 ``showCitations`` 应含 ``data-doc-id`` 属性。"""
    content = _read_js()
    assert "data-doc-id" in content, (
        "showCitations 增强版应包含 'data-doc-id' 属性"
    )


def test_bubble_manager_preserves_child_structure():
    """``BubbleManager`` 不应直接替换 ``#bubble`` 的 ``innerHTML``，避免破坏子结构。"""
    content = _read_js()
    start = content.find("class BubbleManager")
    end = content.find("\n}", start)
    class_body = content[start:end]
    assert "innerHTML" not in class_body, (
        "BubbleManager 类内部不应直接操作 innerHTML"
    )


def test_pet_js_preserves_bubble_answer_child():
    """``pet.js`` 的 ``updateBubble`` / ``appendAnswer`` 应操作 ``#bubble-answer``，保留该子元素。"""
    content = _read_js()
    assert "getElementById('bubble-answer')" in content, (
        "pet.js 应保留并操作 #bubble-answer 子元素"
    )


def test_pet_js_preserves_bubble_citations_child():
    """``pet.js`` 的 ``showCitations`` / ``updateBubble`` 应操作 ``#bubble-citations``，保留该子元素。"""
    content = _read_js()
    assert "getElementById('bubble-citations')" in content, (
        "pet.js 应保留并操作 #bubble-citations 子元素"
    )


def test_pet_js_submit_quick_ask_tries_stream_and_fallback():
    """``submitQuickAsk`` 应先尝试 ``window.pywebview.api.ask_stream``，并保留 ``ask`` 降级路径。"""
    content = _read_js()
    assert "window.pywebview.api.ask_stream" in content, (
        "submitQuickAsk 应调用 window.pywebview.api.ask_stream"
    )
    assert "window.pywebview.api.ask" in content, (
        "submitQuickAsk 应保留 window.pywebview.api.ask 降级调用"
    )


def test_pet_js_append_answer_appends_to_answer_area():
    """``appendAnswer(chunk)`` 应将内容追加到 ``#bubble-answer``。"""
    content = _read_js()
    start = content.find("function appendAnswer")
    end = content.find("\n}", start)
    func_body = content[start:end]
    assert "bubble-answer" in func_body, (
        "appendAnswer 函数体内应引用 #bubble-answer"
    )
    assert "+=" in func_body, (
        "appendAnswer 应使用 += 追加内容到答案区"
    )


# === style.css 契约 ===

def test_style_css_contains_bubble_input_style():
    """``style.css`` 应含 ``#bubble-input`` 样式定义。"""
    content = _read_css()
    assert "#bubble-input" in content, (
        "style.css 应包含 '#bubble-input' 样式"
    )


def test_style_css_contains_bubble_answer_style():
    """``style.css`` 应含 ``#bubble-answer`` 样式定义。"""
    content = _read_css()
    assert "#bubble-answer" in content, (
        "style.css 应包含 '#bubble-answer' 样式"
    )


def test_style_css_contains_bubble_citations_style():
    """``style.css`` 应含 ``#bubble-citations`` 样式定义。"""
    content = _read_css()
    assert "#bubble-citations" in content, (
        "style.css 应包含 '#bubble-citations' 样式"
    )
