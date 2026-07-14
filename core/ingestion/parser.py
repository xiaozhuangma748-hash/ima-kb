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

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict


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
    """

    text: str
    title: str
    file_path: Path
    file_type: str
    language: str = "unknown"
    meta: Dict[str, str] = field(default_factory=dict)


# ---- 支持的文件类型 ----
SUPPORTED_EXTENSIONS = {
    ".pdf", ".docx", ".doc", ".xlsx", ".pptx",
    ".md", ".markdown",
    ".txt", ".log",
    ".html", ".htm",
    # 图片（OCR）
    ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp",
    # 代码文件
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs",
    ".c", ".cpp", ".h", ".hpp", ".cs", ".rb", ".php", ".swift",
    ".kt", ".scala", ".sh", ".bash", ".sql", ".yaml", ".yml",
    ".json", ".xml", ".toml", ".ini", ".conf",
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
    _ocr_checked = False
    _ocr_available = False
    _paddle_ocr = None
    _paddle_ocr_failed = False


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


def _ocr_image(image) -> str:
    """对 PIL Image 做 OCR，返回识别文本。

    优先使用 PaddleOCR（精度高，内部自带文档预处理），降级到 Tesseract。
    Tesseract 路径会做外部预处理（灰度+二值化+放大）。

    Args:
        image: PIL.Image 对象

    Returns:
        识别出的文本
    """
    # 1. 优先 PaddleOCR（直接传原图，PaddleOCR 内部自带预处理）
    paddle_text = _ocr_image_paddle(image)
    if paddle_text.strip():
        return paddle_text

    # 2. 降级 Tesseract（外部预处理提升识别率）
    try:
        processed = _preprocess_image(image)
        return _ocr_image_tesseract(processed)
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

def _parse_pdf(file_path: Path) -> ParsedDocument:
    """解析 PDF：先尝试提取文本层，若为空则走 OCR。

    Args:
        file_path: PDF 文件路径

    Returns:
        ParsedDocument
    """
    import fitz  # PyMuPDF

    text_parts: list[str] = []
    page_count = 0
    ocr_pages: list[int] = []        # 走 OCR 成功的页码
    ocr_failed_pages: list[int] = []  # 走 OCR 失败的页码

    with fitz.open(file_path) as doc:
        page_count = len(doc)
        for i, page in enumerate(doc):
            text = page.get_text()
            # 判断该页是否需要 OCR：文本层几乎为空（< 50 字符）
            if text.strip() and len(text.strip()) >= 50:
                text_parts.append(text)
            else:
                # 走 OCR
                if _check_ocr():
                    try:
                        ocr_text = _ocr_pdf_page(page)
                        if ocr_text.strip():
                            text_parts.append(ocr_text)
                            ocr_pages.append(i + 1)
                        else:
                            text_parts.append("")
                            ocr_failed_pages.append(i + 1)
                    except Exception:
                        text_parts.append("")
                        ocr_failed_pages.append(i + 1)
                else:
                    text_parts.append("")

    text = "\n\n".join(text_parts).strip()

    meta: Dict[str, str] = {"page_count": str(page_count)}
    if ocr_pages:
        meta["ocr_pages"] = ",".join(str(p) for p in ocr_pages)
        meta["ocr_used"] = "true"
    if ocr_failed_pages:
        meta["ocr_failed_pages"] = ",".join(str(p) for p in ocr_failed_pages)

    return ParsedDocument(
        text=text,
        title=file_path.stem,
        file_path=file_path,
        file_type=".pdf",
        language="unknown",
        meta=meta,
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
        )

    from PIL import Image  # type: ignore

    try:
        image = Image.open(file_path)
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
    )


def _parse_docx(file_path: Path) -> ParsedDocument:
    """解析 Word .docx：提取所有段落。"""
    from docx import Document

    doc = Document(str(file_path))
    text = "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
    return ParsedDocument(
        text=text,
        title=file_path.stem,
        file_path=file_path,
        file_type=".docx",
        meta={"paragraph_count": str(len(doc.paragraphs))},
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
    )


def _parse_xlsx(file_path: Path) -> ParsedDocument:
    """解析 Excel .xlsx：逐 sheet 转成文本表格。"""
    from openpyxl import load_workbook

    wb = load_workbook(str(file_path), read_only=True, data_only=True)
    sheet_texts: list[str] = []
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows_text: list[str] = []
        for row in ws.iter_rows(values_only=True):
            # 跳过全空行
            if all(cell is None or str(cell).strip() == "" for cell in row):
                continue
            rows_text.append("\t".join(str(cell) if cell is not None else "" for cell in row))
        if rows_text:
            sheet_texts.append(f"## Sheet: {sheet_name}\n" + "\n".join(rows_text))
    wb.close()

    text = "\n\n".join(sheet_texts)
    return ParsedDocument(
        text=text,
        title=file_path.stem,
        file_path=file_path,
        file_type=".xlsx",
        meta={"sheet_count": str(len(wb.sheetnames))},
    )


def _parse_pptx(file_path: Path) -> ParsedDocument:
    """解析 PowerPoint .pptx：提取每页幻灯片文本。"""
    from pptx import Presentation

    prs = Presentation(str(file_path))
    slide_texts: list[str] = []
    for idx, slide in enumerate(prs.slides, start=1):
        texts: list[str] = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    line = para.text.strip()
                    if line:
                        texts.append(line)
        if texts:
            slide_texts.append(f"## Slide {idx}\n" + "\n".join(texts))

    text = "\n\n".join(slide_texts)
    return ParsedDocument(
        text=text,
        title=file_path.stem,
        file_path=file_path,
        file_type=".pptx",
        meta={"slide_count": str(len(prs.slides))},
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
    )


def _parse_plain(file_path: Path) -> ParsedDocument:
    """解析纯文本 / Markdown：直接读取。"""
    text = file_path.read_text(encoding="utf-8", errors="ignore")
    return ParsedDocument(
        text=text,
        title=file_path.stem,
        file_path=file_path,
        file_type=file_path.suffix.lower(),
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

# 代码类
for ext in _CODE_LANGUAGES:
    _PARSER_MAP[ext] = _parse_code


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
