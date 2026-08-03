"""多格式文档解析器。

支持格式：
- PDF (.pdf)            → PyMuPDF（扫描版自动走 OCR）
- Word (.docx)          → python-docx
- Word (.doc)           → macOS textutil
- Excel (.xlsx)         → openpyxl
- PowerPoint (.pptx)    → python-pptx
- 图片 (.png/.jpg/...)  → PaddleOCR（优先）/ Tesseract（降级）
- Markdown (.md/.markdown) → 纯文本读取
- 文本 (.txt/.log)      → 纯文本读取
- 代码 (.py/.js/...)    → 纯文本读取，带语言标签
- HTML (.html/.htm)     → trafilatura 抽取正文

OCR 依赖（可选，任一即可）：
- PaddleOCR（推荐，精度高）：pip install paddlepaddle paddleocr
- Tesseract（降级）：brew install tesseract tesseract-lang + pip install pytesseract pillow

OCR 流程：图片预处理（灰度+二值化+放大）→ PaddleOCR → 降级 Tesseract

返回统一的 ParsedDocument 结构。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Optional


@dataclass
class ParsedDocument:
    """解析后的统一文档结构。

    Attributes:
        text: 提取出的纯文本内容
        title: 文档标题（默认为文件名，不带扩展名）
        file_path: 原文件路径
        file_type: 文件类型（扩展名，小写）
        language: 内容语言（如 'zh' / 'en' / 'code' / 'unknown'）
        meta: 额外元信息（页数、作者等）
        format_tag: 格式标签（'excel'/'ppt'/'code'/'markdown'/'docx'/'pdf'/'image'/'text'/'html'），
                    用于下游 chunker 和 chain 做格式感知处理
    """

    text: str
    title: str
    file_path: Path
    file_type: str
    language: str = "unknown"
    meta: Dict[str, str] = field(default_factory=dict)
    format_tag: str = "text"


# ---- 支持的文件类型 ----
# 注：代码文件（.py/.js/.ts/...）按用户决策不入库，已从支持列表移除
SUPPORTED_EXTENSIONS = {
    ".pdf", ".docx", ".doc", ".xlsx", ".pptx",
    ".md", ".markdown",
    ".txt", ".log",
    ".html", ".htm",
    # 图片（OCR）
    ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp",
}

# 代码文件后缀 → 语言标签
_CODE_LANGUAGES: Dict[str, str] = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".tsx": "typescript", ".jsx": "javascript",
    ".java": "java", ".go": "go", ".rs": "rust",
    ".c": "c", ".cpp": "cpp", ".h": "c", ".hpp": "cpp",
    ".cs": "csharp", ".rb": "ruby", ".php": "php",
    ".swift": "swift", ".kt": "kotlin", ".scala": "scala",
    ".sh": "shell", ".bash": "shell",
    ".sql": "sql", ".yaml": "yaml", ".yml": "yaml",
    ".json": "json", ".xml": "xml", ".toml": "toml",
    ".ini": "ini", ".conf": "conf",
}


class ParseError(Exception):
    """文档解析失败。"""


# ============================================================
# OCR 工具（PaddleOCR 优先，Tesseract 降级，可选依赖）
# ============================================================

# OCR 引擎检测缓存
_ocr_checked = False
_ocr_available = False

# PaddleOCR 单例（初始化慢，全局复用）
_paddle_ocr = None
_paddle_ocr_failed = False  # 标记 PaddleOCR 不可用，避免反复尝试

# PaddleX layout_parsing 单例（版面分析，首次加载慢）
_layout_pipeline = None
_layout_pipeline_failed = False


def _get_layout_pipeline():
    """获取 PaddleX layout_parsing pipeline 单例（懒加载）。

    layout_parsing 集成了版面检测（17类区域）+ 表格识别（SLANet_plus）+
    印章识别 + 文档预处理（方向矫正+去弯曲），输出结构化的 parsing_res_list。

    Returns:
        pipeline 实例，或 None（不可用）
    """
    global _layout_pipeline, _layout_pipeline_failed
    if _layout_pipeline_failed:
        return None
    if _layout_pipeline is not None:
        return _layout_pipeline
    try:
        import logging
        import os as _os
        # 静默 PaddleX 日志
        for name in ("paddleocr", "paddle", "paddlex", "ppocr"):
            logging.getLogger(name).setLevel(logging.ERROR)
        # PaddleX 用 print 输出模型加载信息，重定向 stdout/stderr
        _devnull_fd = _os.open(_os.devnull, _os.O_WRONLY)
        _saved_stdout_fd = _os.dup(1)
        _saved_stderr_fd = _os.dup(2)
        _os.dup2(_devnull_fd, 1)
        _os.dup2(_devnull_fd, 2)
        try:
            from paddlex import create_pipeline  # type: ignore
            _layout_pipeline = create_pipeline(pipeline="layout_parsing", device="cpu")
        finally:
            _os.dup2(_saved_stdout_fd, 1)
            _os.dup2(_saved_stderr_fd, 2)
            _os.close(_devnull_fd)
            _os.close(_saved_stdout_fd)
            _os.close(_saved_stderr_fd)
        return _layout_pipeline
    except Exception:
        _layout_pipeline_failed = True
        return None


def _check_ocr() -> bool:
    """检测 OCR 是否可用（PaddleOCR 或 Tesseract 任一可用即可）。"""
    global _ocr_checked, _ocr_available
    if _ocr_checked:
        return _ocr_available
    _ocr_checked = True
    # 1. 检测 PaddleOCR
    try:
        from paddleocr import PaddleOCR  # type: ignore  # noqa: F401
        _ocr_available = True
        return True
    except ImportError:
        pass
    # 2. 降级：检测 Tesseract
    try:
        import pytesseract  # type: ignore  # noqa: F401
        from shutil import which
        if which("tesseract") is not None:
            _ocr_available = True
            return True
    except ImportError:
        pass
    _ocr_available = False
    return False


def reset_ocr_cache() -> None:
    """重置 OCR 可用性检测缓存。

    应用场景：用户在 REPL 运行期间安装了 OCR 依赖，
    调用此函数后下次解析会重新检测，无需重启进程。
    """
    global _ocr_checked, _ocr_available, _paddle_ocr, _paddle_ocr_failed
    global _layout_pipeline, _layout_pipeline_failed
    _ocr_checked = False
    _ocr_available = False
    _paddle_ocr = None
    _paddle_ocr_failed = False
    _layout_pipeline = None
    _layout_pipeline_failed = False


def _get_paddle_ocr():
    """获取 PaddleOCR 单例（懒加载）。

    Returns:
        PaddleOCR 实例，或 None（不可用）
    """
    global _paddle_ocr, _paddle_ocr_failed
    if _paddle_ocr_failed:
        return None
    if _paddle_ocr is not None:
        return _paddle_ocr
    try:
        import logging
        import os as _os
        import sys as _sys
        # 静默 PaddleOCR / PaddleX 的日志（print + logging 双管齐下）
        logging.getLogger("paddleocr").setLevel(logging.ERROR)
        logging.getLogger("paddle").setLevel(logging.ERROR)
        logging.getLogger("paddlex").setLevel(logging.ERROR)
        logging.getLogger("ppocr").setLevel(logging.ERROR)
        # PaddleOCR 用 print 输出模型加载信息，重定向 stdout/stderr
        _devnull_fd = _os.open(_os.devnull, _os.O_WRONLY)
        _saved_stdout_fd = _os.dup(1)
        _saved_stderr_fd = _os.dup(2)
        _os.dup2(_devnull_fd, 1)
        _os.dup2(_devnull_fd, 2)
        try:
            from paddleocr import PaddleOCR  # type: ignore
            _paddle_ocr = PaddleOCR(lang="ch")
        finally:
            _os.dup2(_saved_stdout_fd, 1)
            _os.dup2(_saved_stderr_fd, 2)
            _os.close(_devnull_fd)
            _os.close(_saved_stdout_fd)
            _os.close(_saved_stderr_fd)
        return _paddle_ocr
    except Exception:
        _paddle_ocr_failed = True
        return None


def _preprocess_image(image):
    """图片预处理：灰度化 + 二值化 + 放大，提升 OCR 识别率。

    Args:
        image: PIL.Image 对象

    Returns:
        预处理后的 PIL.Image（L 模式，灰度二值化）
    """
    from PIL import Image, ImageOps  # type: ignore

    # 1. 转灰度
    if image.mode != "L":
        image = image.convert("L")

    # 2. 如果分辨率较低，放大 2 倍（提升小字识别）
    w, h = image.size
    if w < 1000:
        image = image.resize((w * 2, h * 2), Image.LANCZOS)

    # 3. 自动对比度
    image = ImageOps.autocontrast(image)

    # 4. Otsu 自适应二值化（对扫描公文效果显著）
    import numpy as np  # type: ignore
    arr = np.array(image)
    # 简单 Otsu：用 PIL 内置的点操作近似
    threshold = arr.mean()
    arr_bin = (arr > threshold) * 255
    image = Image.fromarray(arr_bin.astype("uint8"), mode="L")

    return image


def _ocr_image_paddle(image) -> str:
    """用 PaddleOCR 识别图片，返回文本。

    Args:
        image: PIL.Image 对象

    Returns:
        识别出的文本
    """
    import numpy as np  # type: ignore
    ocr = _get_paddle_ocr()
    if ocr is None:
        return ""
    # PIL → numpy array
    arr = np.array(image)
    result = ocr.predict(arr)
    if not result:
        return ""
    # PaddleOCR 3.x 返回结果：list of dict-like
    texts = []
    for item in result:
        # 3.x API：item.json['res']['rec_texts']
        if hasattr(item, "json"):
            res = item.json.get("res", {})
            rec_texts = res.get("rec_texts", [])
            texts.extend(rec_texts)
        elif isinstance(item, dict):
            rec_texts = item.get("rec_texts", [])
            texts.extend(rec_texts)
    return "\n".join(texts)


def _ocr_image_tesseract(image) -> str:
    """用 Tesseract 识别图片（降级方案）。"""
    import pytesseract  # type: ignore
    return pytesseract.image_to_string(image, lang="chi_sim+eng")


def _clean_ocr_text(text: str) -> str:
    """OCR 文本后处理：清理乱码、合并断行、去除中文间空格。

    处理：
    1. 去除 OCR 误识别的几何符号/特殊符号（■●□◆○等）
    2. 去除中文字符之间的空格（OCR 常随机插入）
    3. 合并视觉换行（复用 _merge_visual_line_breaks）
    4. 压缩连续空格
    """
    if not text or not text.strip():
        return text

    # 1. 去除 OCR 常见乱码符号（几何图形、装饰符号）
    # 保留正文标点和常规符号
    text = re.sub(r"[\u25A0-\u25FF\u2600-\u27BF\u2B00-\u2BFF]", "", text)

    # 2. 去除中文字符之间的空格
    # 模式：中文+空格+中文 → 中文+中文（只处理单空格，避免破坏英文短语）
    text = re.sub(r"([\u4e00-\u9fff])\s+([\u4e00-\u9fff])", r"\1\2", text)
    # 连续处理多次（处理"中 中 中"这种情况）
    for _ in range(3):
        new_text = re.sub(r"([\u4e00-\u9fff])\s+([\u4e00-\u9fff])", r"\1\2", text)
        if new_text == text:
            break
        text = new_text

    # 3. 压缩连续空格（3+ 空格 → 1 个）
    text = re.sub(r"[ \t]{3,}", " ", text)

    # 4. 合并视觉换行
    text = _merge_visual_line_breaks(text)

    return text


def _html_table_to_markdown(html: str) -> str:
    """把 PaddleX 表格识别输出的 HTML 转为 Markdown 表格。

    PaddleX table_recognition 输出 <table><tr><td>...</td></tr></table> 格式，
    转为 Markdown `| cell | cell |` 格式以提升检索友好度。
    解析失败时返回原始 HTML。
    """
    if not html or "<" not in html:
        return html
    try:
        from html.parser import HTMLParser

        class _TableParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.rows: list[list[str]] = []
                self._cur_row: list[str] | None = None
                self._cur_cell: list[str] = []
                self._in_cell = False

            def handle_starttag(self, tag, attrs):
                if tag == "tr":
                    self._cur_row = []
                elif tag in ("td", "th"):
                    self._in_cell = True
                    self._cur_cell = []

            def handle_endtag(self, tag):
                if tag == "tr" and self._cur_row is not None:
                    self.rows.append(self._cur_row)
                    self._cur_row = None
                elif tag in ("td", "th") and self._cur_row is not None:
                    cell_text = "".join(self._cur_cell).strip().replace("\n", " ")
                    self._cur_row.append(cell_text)
                    self._in_cell = False

            def handle_data(self, data):
                if self._in_cell:
                    self._cur_cell.append(data)

        parser = _TableParser()
        parser.feed(html)
        if not parser.rows:
            return html

        # 转为 Markdown 表格
        lines: list[str] = []
        for i, row in enumerate(parser.rows):
            if not row:
                continue
            lines.append("| " + " | ".join(row) + " |")
            if i == 0:
                lines.append("| " + " | ".join("---" for _ in row) + " |")
        return "\n".join(lines) if lines else html
    except Exception:
        return html


def _ocr_image_with_layout(image) -> str:
    """用 PaddleX layout_parsing 做版面感知 OCR，返回结构化文本。

    相比 _ocr_image（纯 OCR 拍平）的改进：
    - 识别 doc_title / paragraph_title / text / table 等区域类型
    - paragraph_title 转为 `## 标题`，让 chunker 按标题切分
    - table 区域的 HTML 转 Markdown 表格，保留行列结构
    - 丢弃 header / footer 噪音

    Args:
        image: PIL.Image 对象

    Returns:
        结构化文本（带 Markdown 标记），或空字符串（不可用/失败时）
    """
    pipeline = _get_layout_pipeline()
    if pipeline is None:
        return ""

    import numpy as np  # type: ignore
    import io

    # PIL → 图片路径或 numpy（PaddleX predict 接受路径或 ndarray）
    arr = np.array(image)
    try:
        result = pipeline.predict(input=arr)
    except Exception:
        # ndarray 输入失败时尝试保存临时文件再传路径
        import tempfile
        tmp_path: Optional[str] = None
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            image.save(tmp, format="PNG")
            tmp_path = tmp.name
        try:
            result = pipeline.predict(input=tmp_path)
        finally:
            if tmp_path:
                _os_unlink(tmp_path)

    parts: list[str] = []
    for r in result:
        res = r.json.get("res", {}) if hasattr(r, "json") else {}
        parsing_list = res.get("parsing_res_list", [])
        for block in parsing_list:
            label = block.get("block_label", "")
            content = block.get("block_content", "")
            if not content or not content.strip():
                continue
            # 按区域类型结构化
            if label == "doc_title":
                parts.append("# " + content.strip())
            elif label == "paragraph_title":
                parts.append("## " + content.strip())
            elif label in ("text", "other_text"):
                parts.append(content.strip())
            elif label == "table":
                # 表格 HTML → Markdown
                md_table = _html_table_to_markdown(content)
                parts.append(md_table)
            elif label in ("header", "footer"):
                # 丢弃页眉页脚噪音
                continue
            elif label == "figure":
                # 图片区域跳过（无文本）
                continue
            else:
                # 其他类型（印章等）保留文本
                parts.append(content.strip())
        break  # 只取第一页/第一张图

    return _clean_ocr_text("\n\n".join(parts)) if parts else ""


def _os_unlink(path: str) -> None:
    """安全删除临时文件。"""
    try:
        import os
        os.unlink(path)
    except Exception:
        pass


def _ocr_image(image) -> str:
    """对 PIL Image 做 OCR，返回识别文本。

    优先级：
    1. PaddleX layout_parsing（版面感知，保留标题/表格结构，需 enable_layout_parsing=True）
    2. PaddleOCR predict（纯 OCR 文本，精度高）
    3. Tesseract（降级方案，外部预处理）

    所有 OCR 输出统一走 _clean_ocr_text 后处理。

    Args:
        image: PIL.Image 对象

    Returns:
        识别出的文本（已清理）
    """
    from config import settings

    # 1. 优先 PaddleX layout_parsing（版面感知，保留结构）
    if settings.enable_layout_parsing:
        try:
            layout_text = _ocr_image_with_layout(image)
            if layout_text.strip():
                return layout_text  # _ocr_image_with_layout 内部已调用 _clean_ocr_text
        except Exception:
            # layout_parsing 失败时降级到 PaddleOCR predict（某些图片版面分析兼容性问题）
            pass

    # 2. 降级 PaddleOCR predict（纯 OCR 文本）
    paddle_text = _ocr_image_paddle(image)
    if paddle_text.strip():
        return _clean_ocr_text(paddle_text)

    # 3. 再降级 Tesseract（外部预处理提升识别率）
    try:
        processed = _preprocess_image(image)
        tesseract_text = _ocr_image_tesseract(processed)
        if tesseract_text.strip():
            return _clean_ocr_text(tesseract_text)
        return ""
    except Exception:
        return ""


def _ocr_pdf_page(page) -> str:
    """对 PDF 单页做 OCR（用于扫描版 PDF）。

    Args:
        page: fitz.Page 对象

    Returns:
        识别出的文本
    """
    import fitz  # PyMuPDF
    # 渲染页面为图片（DPI 200，PaddleOCR 内部会做超分辨率）
    pix = page.get_pixmap(dpi=200)
    from PIL import Image  # type: ignore
    import io
    image = Image.open(io.BytesIO(pix.tobytes("png")))
    return _ocr_image(image)


# ============================================================
# 各格式解析函数
# ============================================================

def _extract_pdf_page_blocks(page) -> list[str]:
    """用 get_text("dict") 提取单页文本块，按阅读顺序排序。

    相比 page.get_text() 的改进：
    - 按 (y0, x0) 排序，恢复阅读顺序（多栏布局下避免左右栏交错）
    - 返回块列表，每块是 span 文本拼接，保留段落边界
    - 检测多栏布局，按栏内顺序输出

    Args:
        page: fitz.Page 对象

    Returns:
        该页的文本块列表（每块对应一个 block，已按阅读顺序排序）
    """
    import fitz  # noqa: F401  PyMuPDF
    page_dict = page.get_text("dict")
    blocks = page_dict.get("blocks", [])

    # 提取文本块（跳过图片块）
    text_blocks: list[dict] = []
    for b in blocks:
        if b.get("type", 0) != 0:  # 0=文本, 1=图片
            continue
        lines = b.get("lines", [])
        if not lines:
            continue
        # 拼接 block 内所有 line 的 span 文本
        block_text_parts: list[str] = []
        max_font_size = 0.0
        for line in lines:
            line_text = "".join(span.get("text", "") for span in line.get("spans", []))
            if line_text.strip():
                block_text_parts.append(line_text)
                for span in line.get("spans", []):
                    sz = span.get("size", 0)
                    if sz > max_font_size:
                        max_font_size = sz
        block_text = "\n".join(block_text_parts).strip()
        if not block_text:
            continue
        bbox = b.get("bbox", [0, 0, 0, 0])  # (x0, y0, x1, y1)
        text_blocks.append({
            "text": block_text,
            "x0": bbox[0], "y0": bbox[1], "x1": bbox[2], "y1": bbox[3],
            "font_size": max_font_size,
        })

    if not text_blocks:
        return []

    # ---- 多栏检测 ----
    # 若 block 的 x 坐标明显分成左右两组（gap > 页宽 15%），按栏排序
    page_width = page.rect.width if hasattr(page, "rect") else 0
    if page_width > 0 and len(text_blocks) >= 4:
        x0_values = sorted(b["x0"] for b in text_blocks)
        mid_x = page_width / 2
        left_count = sum(1 for x in x0_values if x < mid_x)
        right_count = len(x0_values) - left_count
        # 若左右各有至少 2 块，判定为双栏，按 (栏, y0, x0) 排序
        if left_count >= 2 and right_count >= 2:
            for b in text_blocks:
                b["col"] = 0 if b["x0"] < mid_x else 1
            text_blocks.sort(key=lambda b: (b["col"], b["y0"], b["x0"]))
        else:
            text_blocks.sort(key=lambda b: (b["y0"], b["x0"]))
    else:
        text_blocks.sort(key=lambda b: (b["y0"], b["x0"]))

    return [b["text"] for b in text_blocks]


def _detect_header_footer(page_texts: list[list[str]], min_repeat: int = 3) -> tuple[set[str], set[str]]:
    """检测 PDF 的页眉页脚（在多页重复出现的短文本块）。

    Args:
        page_texts: 每页的文本块列表
        min_repeat: 至少在 N 页出现才算页眉页脚

    Returns:
        (header_set, footer_set) 需要过滤的文本集合
    """
    if len(page_texts) < min_repeat:
        return set(), set()

    from collections import Counter
    # 统计每页首块和末块的出现频次
    first_blocks: Counter = Counter()
    last_blocks: Counter = Counter()
    for blocks in page_texts:
        if blocks:
            # 归一化：去除空白和页码数字
            first = re.sub(r"\s+", "", blocks[0])[:50]
            last = re.sub(r"\s+", "", blocks[-1])[:50]
            if first:
                first_blocks[first] += 1
            if last:
                last_blocks[last] += 1

    # 出现在 >= min_repeat 页的首/末块视为页眉页脚
    page_count = len(page_texts)
    threshold = max(min_repeat, page_count // 2)
    header_set = {t for t, c in first_blocks.items() if c >= threshold}
    footer_set = {t for t, c in last_blocks.items() if c >= threshold}

    # 额外检测：纯数字（页码）或纯页码+短文字
    for blocks in page_texts:
        if blocks:
            for idx in (0, -1):
                txt = re.sub(r"\s+", "", blocks[idx])[:50]
                # 纯数字 或 "数字 文字" 形式的页码
                if re.match(r"^\d{1,3}$", txt) or re.match(r"^.{0,10}\d{1,3}$", txt):
                    if idx == 0:
                        header_set.add(txt)
                    else:
                        footer_set.add(txt)

    return header_set, footer_set


def _is_header_footer(text: str, header_set: set, footer_set: set) -> bool:
    """判断文本块是否为页眉页脚。"""
    normalized = re.sub(r"\s+", "", text)[:50]
    if not normalized:
        return False
    if normalized in header_set or normalized in footer_set:
        return True
    # 模糊匹配：页眉页脚集合中的项是否是当前文本的前缀/后缀
    for h in header_set:
        if h and (normalized.startswith(h) or normalized.endswith(h)):
            return True
    for f in footer_set:
        if f and (normalized.startswith(f) or normalized.endswith(f)):
            return True
    return False


def _merge_visual_line_breaks(text: str) -> str:
    """合并 PDF 视觉换行（单 \\n），保留段落分隔（双 \\n）。

    PDF 提取的文本中，单 \\n 是视觉换行（同一行的折行），双 \\n 是段落分隔。
    对单 \\n 做合并处理：
    - 行尾是中文标点（。！？；）或全角符号 → 保留换行（段落结束）
    - 行尾是英文句号/问号/感叹号+空格 → 保留换行
    - 行首是中文标点（、，。等）→ 合并到上一行（标点不该行首）
    - 行首是列表标记（1. （1） • 等）→ 保留换行
    - 其他情况：合并（去掉 \\n，中文直接拼接，英文加空格）

    用于 _parse_pdf 的文本后处理，让 BM25 bigram 短语匹配恢复有效。
    """
    if not text:
        return text

    # 先规范化 Windows 换行
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # 把 3+ 换行压缩为 2 个（段落分隔）
    text = re.sub(r"\n{3,}", "\n\n", text)

    lines = text.split("\n")
    result: list[str] = []
    buffer = ""

    # 中文行尾标点（段落结束标志）
    cn_end_puncts = set("。！？；：…」』）】》")
    # 中文行首标点（不该行首，应合并到上一行）
    cn_start_puncts = set("、，。！？；：…」』）】》")
    # 列表/标题标记（行首应保留换行）
    list_pattern = re.compile(
        r"^(?:"
        r"\d+[.、）)]"          # 1. 1、 1） 1)
        r"|[（(]\d+[）)]"       # （1） (1)
        r"|[一二三四五六七八九十]+[、.）)]"  # 一、 二.
        r"|第[一二三四五六七八九十百千]+[章节条]"  # 第一章
        r"|●|•|◆|■|★|☆"      # 项目符号
        r"|[【\[《「『]"       # 引号开头
        r"|#{1,6}\s"           # Markdown 标题
        r")"
    )

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            # 空行：如果 buffer 非空，可能是段落分隔
            if buffer:
                result.append(buffer)
                buffer = ""
            result.append("")
            continue

        if not buffer:
            buffer = stripped
            continue

        buffer_end = buffer[-1] if buffer else ""
        line_start = stripped[0] if stripped else ""

        # 判断是否应该保留换行（新起一段）
        should_new_line = False

        # 1. 上一行以段落结束标点结尾
        if buffer_end in cn_end_puncts:
            should_new_line = True
        # 2. 上一行以英文句末标点结尾
        elif buffer_end in {".", "!", "?", ";"} and len(buffer) >= 2 and (buffer[-2] == " " or buffer[-2].isascii()):
            should_new_line = True
        # 3. 当前行以列表/标题标记开头
        elif list_pattern.match(stripped):
            should_new_line = True
        # 4. 当前行首是中文标点（不该行首）→ 合并
        elif line_start in cn_start_puncts:
            should_new_line = False
        # 5. 当前行是全大写英文（可能是标题）
        elif stripped.isupper() and len(stripped) > 3 and stripped.isascii():
            should_new_line = True
        # 6. buffer 和当前行长度都较短（可能是标题行）
        elif len(buffer) < 20 and len(stripped) < 20 and not cn_start_puncts.intersection(stripped):
            # 短行可能是标题，保留换行
            should_new_line = True

        if should_new_line:
            result.append(buffer)
            buffer = stripped
        else:
            # 合并：中文直接拼接，中英/英英之间加空格
            if buffer_end.isascii() and line_start.isascii():
                buffer = buffer + " " + stripped
            elif buffer_end.isascii() or line_start.isascii():
                buffer = buffer + " " + stripped
            else:
                buffer = buffer + stripped

    if buffer:
        result.append(buffer)

    return "\n".join(result).strip()


def _parse_pdf(file_path: Path) -> ParsedDocument:
    """解析 PDF：先尝试提取文本层（结构感知），若为空则走 OCR。

    改进点（P0）：
    - 用 get_text("dict") 按阅读顺序提取，检测多栏布局
    - 检测并去除重复的页眉页脚
    - 合并视觉换行（单 \\n），保留段落分隔（双 \\n）
    - 保留页码分隔标记（\\n\\n--- Page N ---\\n\\n），供下游分块使用

    Args:
        file_path: PDF 文件路径

    Returns:
        ParsedDocument
    """
    import fitz  # PyMuPDF

    raw_page_texts: list[list[str]] = []  # 每页的文本块列表（未去页眉页脚）
    page_count = 0
    ocr_pages: list[int] = []
    ocr_failed_pages: list[int] = []

    with fitz.open(file_path) as doc:
        page_count = len(doc)
        for i, page in enumerate(doc):
            blocks = _extract_pdf_page_blocks(page)
            total_text = "\n".join(blocks).strip()
            # 判断该页是否需要 OCR：文本层几乎为空（< 50 字符）
            if total_text and len(total_text) >= 50:
                raw_page_texts.append(blocks)
            else:
                # 走 OCR
                if _check_ocr():
                    try:
                        ocr_text = _ocr_pdf_page(page)
                        if ocr_text.strip():
                            # _ocr_image 已内置 _clean_ocr_text 后处理（含视觉换行合并）
                            raw_page_texts.append([ocr_text])
                            ocr_pages.append(i + 1)
                        else:
                            raw_page_texts.append([])
                            ocr_failed_pages.append(i + 1)
                    except Exception:
                        raw_page_texts.append([])
                        ocr_failed_pages.append(i + 1)
                else:
                    raw_page_texts.append([])

    # 检测页眉页脚
    header_set, footer_set = _detect_header_footer(raw_page_texts)

    # 组装最终文本：去页眉页脚 + 合并视觉换行 + 页码分隔标记
    page_sections: list[str] = []
    for i, blocks in enumerate(raw_page_texts):
        if not blocks:
            continue
        filtered: list[str] = []
        for b in blocks:
            if not _is_header_footer(b, header_set, footer_set):
                filtered.append(b)
        if not filtered:
            continue
        page_text = "\n".join(filtered)
        # 合并视觉换行
        page_text = _merge_visual_line_breaks(page_text)
        # 加页码分隔标记（供 chunker 识别页边界）
        page_sections.append(f"--- Page {i + 1} ---\n{page_text}")

    text = "\n\n".join(page_sections).strip()

    meta: Dict[str, str] = {"page_count": str(page_count)}
    if ocr_pages:
        meta["ocr_pages"] = ",".join(str(p) for p in ocr_pages)
        meta["ocr_used"] = "true"
    if ocr_failed_pages:
        meta["ocr_failed_pages"] = ",".join(str(p) for p in ocr_failed_pages)
    if header_set:
        meta["header_removed"] = "true"
    if footer_set:
        meta["footer_removed"] = "true"

    return ParsedDocument(
        text=text,
        title=file_path.stem,
        file_path=file_path,
        file_type=".pdf",
        language="unknown",
        meta=meta,
        format_tag="pdf",
    )


def _parse_image(file_path: Path) -> ParsedDocument:
    """解析图片：走 OCR 提取文本。

    Args:
        file_path: 图片文件路径

    Returns:
        ParsedDocument
    """
    if not _check_ocr():
        # OCR 不可用，返回空文档（让上层跳过）
        return ParsedDocument(
            text="",
            title=file_path.stem,
            file_path=file_path,
            file_type=file_path.suffix.lower(),
            meta={"ocr_unavailable": "true"},
            format_tag="image",
        )

    from PIL import Image  # type: ignore

    try:
        # Bug 10 修复：用 with 语句确保文件句柄关闭
        # 批量 OCR 场景下未关闭句柄会触发 ResourceWarning 并可能耗尽 fd
        with Image.open(file_path) as image:
            text = _ocr_image(image)
    except Exception as e:
        raise ParseError(f"图片 OCR 失败 [{file_path.name}]: {type(e).__name__}: {e}")

    return ParsedDocument(
        text=text.strip(),
        title=file_path.stem,
        file_path=file_path,
        file_type=file_path.suffix.lower(),
        language="unknown",
        meta={"ocr_used": "true"},
        format_tag="image",
    )


def _parse_docx(file_path: Path) -> ParsedDocument:
    """解析 Word .docx：提取段落 + 表格内容，保留 Heading 样式层级。

    样式感知：
    - 识别 `paragraph.style.name`（Heading 1/2/3/Title 等），转为 Markdown 风格的 `#`/`##`/`###` 标记
    - 列表样式（List Bullet/List Number）保留为 `-`/`1.` 前缀
    - 让下游 chunker 能按标题层级切分，并填充 heading 字段供 reranker 使用
    """
    from docx import Document

    doc = Document(str(file_path))
    parts: list[str] = []

    # 1. 段落文本（样式感知）
    for p in doc.paragraphs:
        text = p.text.strip()
        if not text:
            continue
        style_name = (p.style.name or "").strip() if p.style else ""
        # Heading 1/2/3/4/5/6 → Markdown #/##/###/####/#####/######
        if style_name.lower().startswith("heading"):
            try:
                level = int(style_name.split()[-1])
                level = max(1, min(6, level))
                parts.append("#" * level + " " + text)
            except (ValueError, IndexError):
                parts.append("# " + text)  # 无法解析层级，按 H1 处理
        elif style_name.lower() == "title":
            parts.append("# " + text)
        elif style_name.lower().startswith("list bullet"):
            parts.append("- " + text)
        elif style_name.lower().startswith("list number"):
            parts.append("1. " + text)
        else:
            parts.append(text)

    # 2. 表格内容（键值对序列化，与 xlsx 一致）
    for tbl_idx, table in enumerate(doc.tables):
        rows = table.rows
        if not rows:
            continue
        # 第一行作为表头
        headers = [
            (cell.text.strip() if cell.text.strip() else f"列{i+1}")
            for i, cell in enumerate(rows[0].cells)
        ]
        for row in rows[1:]:
            pairs = []
            for i, cell in enumerate(row.cells):
                if i >= len(headers):
                    break
                val = cell.text.strip()
                if val:
                    pairs.append(f"{headers[i]}={val}")
            if pairs:
                parts.append("[表格] " + " | ".join(pairs))

    text = "\n\n".join(parts)
    return ParsedDocument(
        text=text,
        title=file_path.stem,
        file_path=file_path,
        file_type=".docx",
        meta={"paragraph_count": str(len(doc.paragraphs))},
        format_tag="docx",
    )


def _parse_doc(file_path: Path) -> ParsedDocument:
    """解析旧版 Word .doc：用 macOS 自带 textutil 转成纯文本。

    Args:
        file_path: .doc 文件路径

    Returns:
        ParsedDocument

    Raises:
        ParseError: textutil 不可用或转换失败
    """
    import subprocess
    from shutil import which

    if which("textutil") is None:
        raise ParseError(
            f"解析 .doc 需要 macOS textutil（系统自带），当前环境不可用: {file_path.name}"
        )

    try:
        # textutil -convert txt -stdout 输出到 stdout
        result = subprocess.run(
            ["textutil", "-convert", "txt", "-stdout", str(file_path)],
            capture_output=True,
            text=True,
            check=True,
        )
        text = result.stdout.strip()
    except subprocess.CalledProcessError as e:
        raise ParseError(f"textutil 转换失败 [{file_path.name}]: {e.stderr}") from e

    return ParsedDocument(
        text=text,
        title=file_path.stem,
        file_path=file_path,
        file_type=".doc",
        meta={"converter": "textutil"},
        format_tag="docx",
    )


def _parse_xlsx(file_path: Path) -> ParsedDocument:
    """解析 Excel .xlsx：每行序列化为「表头=值」的键值对文本。

    优化点（解决行被切断、表头数据关联丢失问题）：
    1. 每行数据前缀表头字段名，形成 "列名1=值1 | 列名2=值2" 的语义完整单元
    2. 每行作为一个独立记录，永不切断单行
    3. 表头信息重复到每行，向量嵌入能感知字段语义
    """
    from openpyxl import load_workbook

    wb = load_workbook(str(file_path), read_only=True, data_only=True)
    sheet_texts: list[str] = []
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue

        # 第一行作为表头
        header_row = rows[0]
        headers = [
            (str(c).strip() if c is not None else f"列{i+1}")
            for i, c in enumerate(header_row)
        ]

        # 数据行序列化为键值对
        # 每行前缀「文档=DocTitle」注入文档标题语义，让 BM25 能命中标题里的关键词
        # 例：xlsx 标题"2025年智能服务终端配置安装情况"含"智能"二字，
        # 但原 chunk 内容只有 sheet 名"钱塘安装情况"，缺"智能"
        # 注入后 BM25 能命中"智能终端怎么安装"类查询
        doc_title = file_path.stem
        records: list[str] = []
        for row_idx, row in enumerate(rows[1:], start=2):
            if all(cell is None or str(cell).strip() == "" for cell in row):
                continue
            pairs = []
            for i, cell in enumerate(row):
                if i >= len(headers):
                    break
                val = "" if cell is None else str(cell).strip()
                # 跳过完全空值的列
                if val:
                    pairs.append(f"{headers[i]}={val}")
            if pairs:
                records.append(f"[{sheet_name}] 文档={doc_title} | " + " | ".join(pairs))

        if records:
            sheet_texts.append("\n".join(records))

    wb.close()

    text = "\n\n".join(sheet_texts)
    return ParsedDocument(
        text=text,
        title=file_path.stem,
        file_path=file_path,
        file_type=".xlsx",
        meta={"sheet_count": str(len(wb.sheetnames))},
        format_tag="excel",
    )


def _parse_pptx(file_path: Path) -> ParsedDocument:
    """解析 PowerPoint .pptx：提取每页幻灯片文本 + 表格 + 备注。

    优化：
    - 提取 slide 标题作为 metadata（供 reranker 和引用溯源使用）
    - 提取 notes_slide 备注（讲者备注，常含关键补充信息）
    - 在 `## Slide N` 后注入 `[标题] xxx` 标记，保留标题语义
    """
    from pptx import Presentation

    prs = Presentation(str(file_path))
    slide_texts: list[str] = []
    slide_titles: list[str] = []  # 用于 meta
    for idx, slide in enumerate(prs.slides, start=1):
        texts: list[str] = []
        slide_title = ""

        # 1. 提取 slide 标题（优先用 placeholders.title）
        try:
            if slide.shapes.title is not None and slide.shapes.title.has_text_frame:
                slide_title = slide.shapes.title.text.strip()
        except Exception:
            pass

        # 2. 普通文本框 + 表格
        for shape in slide.shapes:
            # 跳过 title shape（已单独提取）
            if slide.shapes.title is not None and shape == slide.shapes.title:
                continue
            # 2.1 普通文本框
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    line = para.text.strip()
                    if line:
                        texts.append(line)
            # 2.2 表格 shape
            if shape.has_table:
                tbl = shape.table
                rows = tbl.rows
                if not rows:
                    continue
                headers = [
                    (cell.text.strip() if cell.text.strip() else f"列{i+1}")
                    for i, cell in enumerate(rows[0].cells)
                ]
                for row in rows[1:]:
                    pairs = []
                    for i, cell in enumerate(row.cells):
                        if i >= len(headers):
                            break
                        val = cell.text.strip()
                        if val:
                            pairs.append(f"{headers[i]}={val}")
                    if pairs:
                        texts.append("[幻灯片表格] " + " | ".join(pairs))

        # 3. 备注（notes_slide）— 讲者备注常含关键补充信息
        try:
            if slide.has_notes_slide:
                notes_text = slide.notes_slide.notes_text_frame.text.strip()
                if notes_text:
                    texts.append("[备注] " + notes_text)
        except Exception:
            pass

        if texts or slide_title:
            # 在 `## Slide N` 后注入标题标记（如有），保留标题语义供下游 chunker 使用
            header = f"## Slide {idx}"
            if slide_title:
                header += f"\n# {slide_title}"
            slide_texts.append(header + "\n" + "\n".join(texts))
            slide_titles.append(slide_title)

    text = "\n\n".join(slide_texts)
    return ParsedDocument(
        text=text,
        title=file_path.stem,
        file_path=file_path,
        file_type=".pptx",
        meta={
            "slide_count": str(len(prs.slides)),
            "slide_titles": " | ".join(t for t in slide_titles if t),
        },
        format_tag="ppt",
    )


def _parse_html(file_path: Path) -> ParsedDocument:
    """解析 HTML：用 trafilatura 抽取正文。"""
    import trafilatura

    html_text = file_path.read_text(encoding="utf-8", errors="ignore")
    text = trafilatura.extract(html_text) or ""
    return ParsedDocument(
        text=text.strip(),
        title=file_path.stem,
        file_path=file_path,
        file_type=".html",
        meta={"extractor": "trafilatura"},
        format_tag="html",
    )


def _parse_plain(file_path: Path) -> ParsedDocument:
    """解析纯文本 / Markdown：直接读取。"""
    text = file_path.read_text(encoding="utf-8", errors="ignore")
    ext = file_path.suffix.lower()
    # Markdown 文件打 markdown tag，其他打 text tag
    format_tag = "markdown" if ext in (".md", ".markdown") else "text"
    return ParsedDocument(
        text=text,
        title=file_path.stem,
        file_path=file_path,
        file_type=ext,
        format_tag=format_tag,
    )


def _parse_code(file_path: Path) -> ParsedDocument:
    """解析代码文件：保留原文 + 标注语言。"""
    text = file_path.read_text(encoding="utf-8", errors="ignore")
    language = _CODE_LANGUAGES.get(file_path.suffix.lower(), "code")
    return ParsedDocument(
        text=text,
        title=file_path.stem,
        file_path=file_path,
        file_type=file_path.suffix.lower(),
        language=language,
        meta={"is_code": "true"},
    )


# ============================================================
# 解析器注册表
# ============================================================

_PARSER_MAP: Dict[str, Callable[[Path], ParsedDocument]] = {
    ".pdf": _parse_pdf,
    ".docx": _parse_docx,
    ".doc": _parse_doc,
    ".xlsx": _parse_xlsx,
    ".pptx": _parse_pptx,
    ".html": _parse_html,
    ".htm": _parse_html,
    # 图片（OCR）
    ".png": _parse_image,
    ".jpg": _parse_image,
    ".jpeg": _parse_image,
    ".tif": _parse_image,
    ".tiff": _parse_image,
    ".bmp": _parse_image,
    ".webp": _parse_image,
}

# Markdown / 文本类
for ext in (".md", ".markdown", ".txt", ".log"):
    _PARSER_MAP[ext] = _parse_plain

# 注：代码文件按用户决策不入库，不再注册到 _PARSER_MAP


# ============================================================
# 公共 API
# ============================================================

def parse(file_path: Path | str) -> ParsedDocument:
    """解析单个文件，返回 ParsedDocument。

    Args:
        file_path: 文件路径（Path 或字符串）

    Returns:
        ParsedDocument

    Raises:
        FileNotFoundError: 文件不存在
        ParseError: 不支持的格式或解析失败
    """
    path = Path(file_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"文件不存在：{path}")
    if not path.is_file():
        raise ParseError(f"不是文件：{path}")

    ext = path.suffix.lower()
    parser = _PARSER_MAP.get(ext)
    if parser is None:
        raise ParseError(
            f"不支持的文件格式：{ext}。"
            f"支持的格式：{', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    try:
        return parser(path)
    except ParseError:
        raise
    except Exception as e:
        raise ParseError(f"解析失败 [{path.name}]: {type(e).__name__}: {e}") from e


def is_supported(file_path: Path | str) -> bool:
    """判断文件是否支持解析。"""
    return Path(file_path).suffix.lower() in SUPPORTED_EXTENSIONS
