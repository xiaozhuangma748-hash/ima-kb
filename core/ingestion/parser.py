"""多格式文档解析器。

支持格式：
- PDF (.pdf)            → PyMuPDF（扫描版自动走 OCR）
- Word (.docx)          → python-docx
- Word (.doc)           → macOS textutil
- Excel (.xlsx)         → openpyxl
- PowerPoint (.pptx)    → python-pptx
- 图片 (.png/.jpg/...)  → Tesseract OCR（中文+英文）
- Markdown (.md/.markdown) → 纯文本读取
- 文本 (.txt/.log)      → 纯文本读取
- 代码 (.py/.js/...)    → 纯文本读取，带语言标签
- HTML (.html/.htm)     → trafilatura 抽取正文

OCR 依赖（可选）：
- 系统：brew install tesseract tesseract-lang
- Python：pip install pytesseract pillow

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
# OCR 工具（基于 Tesseract，可选依赖）
# ============================================================

# 是否已经检测过 tesseract 可用性
_ocr_checked = False
_ocr_available = False


def _check_ocr() -> bool:
    """检测 OCR（tesseract + pytesseract）是否可用。"""
    global _ocr_checked, _ocr_available
    if _ocr_checked:
        return _ocr_available
    _ocr_checked = True
    try:
        import pytesseract  # type: ignore
        # 检测 tesseract 可执行文件
        from shutil import which
        if which("tesseract") is None:
            _ocr_available = False
        else:
            _ocr_available = True
    except ImportError:
        _ocr_available = False
    return _ocr_available


def reset_ocr_cache() -> None:
    """重置 OCR 可用性检测缓存。

    应用场景：用户在 REPL 运行期间安装了 tesseract，
    调用此函数后下次解析会重新检测，无需重启进程。
    """
    global _ocr_checked, _ocr_available
    _ocr_checked = False
    _ocr_available = False


def _ocr_image(image) -> str:
    """对 PIL Image 做 OCR，返回识别文本。

    Args:
        image: PIL.Image 对象

    Returns:
        识别出的文本（中文 + 英文）
    """
    import pytesseract  # type: ignore
    # chi_sim+eng：中文简体 + 英文
    return pytesseract.image_to_string(image, lang="chi_sim+eng")


def _ocr_pdf_page(page) -> str:
    """对 PDF 单页做 OCR（用于扫描版 PDF）。

    Args:
        page: fitz.Page 对象

    Returns:
        识别出的文本
    """
    import fitz  # PyMuPDF
    # 渲染页面为图片（DPI 200 兼顾速度和准确率）
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
