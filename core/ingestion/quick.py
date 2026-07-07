"""快速入库：文本 / 剪贴板 / URL，无需先保存文件。

三种快速入库方式：
1. 文本直入库：save_text(text, title) → 临时 .txt → 复用现有流程
2. 剪贴板入库：save_clipboard() → 检测图片/文本 → 自动入库
3. URL 入库：save_url(url) → 抓取网页 → 提取正文 → 入库
"""
from __future__ import annotations

import hashlib
import logging
import re
import subprocess
import tempfile
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


# ---- HTML 正文提取 ----

class _TextExtractor(HTMLParser):
    """简单的 HTML 正文提取器（无额外依赖）。"""

    # 只提取这些标签内的文本
    _GOOD_TAGS = {"p", "div", "span", "h1", "h2", "h3", "h4", "h5", "h6",
                  "li", "td", "th", "article", "section", "blockquote", "pre"}
    # 跳过这些标签
    _SKIP_TAGS = {"script", "style", "nav", "footer", "header", "aside", "noscript"}

    def __init__(self) -> None:
        super().__init__()
        self._pieces: list[str] = []
        self._skip_depth = 0
        self._good_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        if tag in self._GOOD_TAGS:
            self._good_depth += 1
            self._pieces.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag in self._GOOD_TAGS and self._good_depth > 0:
            self._good_depth -= 1
            self._pieces.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            text = data.strip()
            if text:
                self._pieces.append(text + " ")

    def get_text(self) -> str:
        raw = "".join(self._pieces)
        # 清理多余空白
        lines = [l.strip() for l in raw.split("\n")]
        lines = [l for l in lines if l]
        return "\n".join(lines)


def _extract_title(html: str) -> str:
    """从 HTML 中提取标题。"""
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1).strip()[:100]
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.IGNORECASE | re.DOTALL)
    if m:
        # 去 HTML 标签
        return re.sub(r"<[^>]+>", "", m.group(1)).strip()[:100]
    return "网页剪藏"


# ---- 核心函数 ----

def text_to_temp_file(text: str, title: str = "", suffix: str = ".txt") -> Path:
    """将文本保存到临时文件，返回路径。

    Args:
        text: 文本内容
        title: 标题（用作文件名，非法字符会被替换）
        suffix: 文件后缀（.txt / .md）

    Returns:
        临时文件路径
    """
    # 清理标题作为文件名
    safe_title = re.sub(r'[\\/:*?"<>|]', "_", title or "剪藏")[:60]
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = f"{safe_title}_{timestamp}{suffix}"

    # 保存到 storage/uploads/quick/ 目录
    from config import settings
    quick_dir = settings.storage_path / "uploads" / "quick"
    quick_dir.mkdir(parents=True, exist_ok=True)
    file_path = quick_dir / filename
    file_path.write_text(text, encoding="utf-8")
    return file_path


def save_text(text: str, title: str = "") -> Path:
    """文本直入库：保存文本为临时 .txt 文件。

    Args:
        text: 文本内容
        title: 文档标题

    Returns:
        临时文件路径（供后续 _ingest_one 使用）
    """
    if not text.strip():
        raise ValueError("文本内容为空")
    return text_to_temp_file(text, title or "文本笔记", ".txt")


def save_clipboard() -> Tuple[Optional[Path], str]:
    """剪贴板入库：检测剪贴板内容类型并保存。

    Returns:
        (文件路径, 内容类型描述) 或 (None, 错误信息)
    """
    # 1. 先尝试图片（截图）
    try:
        from PIL import ImageGrab
        img = ImageGrab.grabclipboard()
        if img is not None:
            # 保存为 PNG
            from config import settings
            quick_dir = settings.storage_path / "uploads" / "quick"
            quick_dir.mkdir(parents=True, exist_ok=True)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            file_path = quick_dir / f"截图_{timestamp}.png"
            img.save(str(file_path), "PNG")
            return file_path, "image"
    except Exception as e:
        logger.debug(f"剪贴板图片读取失败: {e}")

    # 2. 尝试文本（pbpaste）
    try:
        result = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=2)
        if result.returncode == 0 and result.stdout.strip():
            text = result.stdout.strip()
            # 检测是否是 URL
            if text.startswith("http://") or text.startswith("https://"):
                return save_url(text), "url"
            return save_text(text, "剪贴板笔记"), "text"
    except Exception as e:
        logger.debug(f"pbpaste 失败: {e}")

    return None, "剪贴板为空或不支持"


def save_url(url: str) -> Path:
    """URL 入库：抓取网页正文并保存为 .txt。

    Args:
        url: 网页 URL

    Returns:
        临时文件路径
    """
    import requests

    # 抓取网页
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36",
    }
    resp = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
    resp.encoding = resp.apparent_encoding or "utf-8"
    html = resp.text

    # 提取标题
    title = _extract_title(html)

    # 提取正文
    extractor = _TextExtractor()
    extractor.feed(html)
    text = extractor.get_text()

    if not text.strip() or len(text.strip()) < 20:
        raise ValueError(f"网页正文为空或过短: {url}")

    # 在文本开头加上来源 URL
    text = f"来源: {url}\n标题: {title}\n\n{text}"

    return text_to_temp_file(text, title, ".txt")
