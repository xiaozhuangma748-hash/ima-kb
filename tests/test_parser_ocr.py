"""OCR 缓存重置和 PDF OCR 失败页码记录测试。"""
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from core.ingestion import parser


def test_reset_ocr_cache_clears_flag():
    """reset_ocr_cache 应清除已检测标记。"""
    # 先标记为已检测
    parser._ocr_checked = True
    parser._ocr_available = True
    # 重置
    parser.reset_ocr_cache()
    assert parser._ocr_checked is False
    assert parser._ocr_available is False


def test_reset_ocr_cache_allows_redetect():
    """reset_ocr_cache 后 _check_ocr 应重新检测。"""
    import sys

    # 确保 pytesseract 可导入（mock 注入 sys.modules）
    if "pytesseract" not in sys.modules:
        sys.modules["pytesseract"] = MagicMock()

    # 模拟 PaddleOCR 不可用（import 抛 ImportError）
    real_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__
    def mock_import(name, *args, **kwargs):
        if name == "paddleocr":
            raise ImportError("mocked: paddleocr not available")
        return real_import(name, *args, **kwargs)

    # 模拟首次检测：PaddleOCR 和 Tesseract 都不可用
    with patch("shutil.which", return_value=None), \
         patch("builtins.__import__", side_effect=mock_import):
        parser.reset_ocr_cache()
        assert parser._check_ocr() is False
        assert parser._ocr_checked is True
        assert parser._ocr_available is False

    # 模拟安装后重置并重新检测：tesseract 可用
    with patch("shutil.which", return_value="/usr/local/bin/tesseract"):
        parser.reset_ocr_cache()
        assert parser._check_ocr() is True
        assert parser._ocr_available is True


def test_reset_ocr_cache_idempotent():
    """多次调用 reset_ocr_cache 应安全。"""
    parser.reset_ocr_cache()
    parser.reset_ocr_cache()
    parser.reset_ocr_cache()
    assert parser._ocr_checked is False


def test_parse_pdf_records_ocr_failed_pages(tmp_path):
    """PDF OCR 失败的页码应记录到 meta.ocr_failed_pages。"""
    # 构造一个扫描版 PDF（每页文本层为空）
    try:
        import fitz  # type: ignore
    except ImportError:
        pytest.skip("PyMuPDF 未安装")

    pdf_path = tmp_path / "scan.pdf"
    doc = fitz.open()
    for _ in range(3):
        page = doc.new_page()
        # 不插入任何文本，模拟扫描版
    doc.save(str(pdf_path))
    doc.close()

    # 模拟 OCR 可用但每页都失败
    with patch.object(parser, "_check_ocr", return_value=True), \
         patch.object(parser, "_ocr_pdf_page", side_effect=Exception("OCR 失败")):
        result = parser._parse_pdf(pdf_path)

    assert "ocr_failed_pages" in result.meta
    # 3 页都失败
    failed = result.meta["ocr_failed_pages"].split(",")
    assert len(failed) == 3


def test_parse_pdf_records_ocr_empty_pages_as_failed(tmp_path):
    """OCR 返回空文本的页码也应记录到 ocr_failed_pages。"""
    try:
        import fitz  # type: ignore
    except ImportError:
        pytest.skip("PyMuPDF 未安装")

    pdf_path = tmp_path / "scan.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(str(pdf_path))
    doc.close()

    with patch.object(parser, "_check_ocr", return_value=True), \
         patch.object(parser, "_ocr_pdf_page", return_value=""):  # OCR 返回空
        result = parser._parse_pdf(pdf_path)

    assert "ocr_failed_pages" in result.meta


def test_parse_image_closes_file_handle(tmp_path):
    """Bug 10 修复验证：Image.open 应使用 with 语句关闭文件句柄。

    场景：批量 OCR 时未关闭文件句柄会触发 ResourceWarning 并可能耗尽 fd。
    验证：调用 _parse_image 后，PIL Image 的 fp 应为 None（已关闭）。
    """
    import sys

    # 构造一个最小 PNG 图片
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        pytest.skip("Pillow 未安装")

    img_path = tmp_path / "test.png"
    Image.new("RGB", (10, 10), color="white").save(str(img_path))

    # 捕获 Image.open 返回的对象，验证它被关闭
    opened_images = []
    real_image_open = Image.open

    def spy_image_open(path, *args, **kwargs):
        img = real_image_open(path, *args, **kwargs)
        opened_images.append(img)
        return img

    # 模拟 OCR 可用 + _ocr_image 返回文本
    with patch.object(parser, "_check_ocr", return_value=True), \
         patch.object(parser, "_ocr_image", return_value="模拟 OCR 文本"), \
         patch("PIL.Image.open", side_effect=spy_image_open):
        result = parser._parse_image(img_path)

    # 验证返回了非空文本
    assert result.text == "模拟 OCR 文本"

    # Bug 10 修复关键断言：with 语句退出后 Image 对象的 fp 应已关闭
    assert len(opened_images) == 1, "Image.open 应被调用一次"
    # with 语句会调用 __exit__，PIL Image 的 __exit__ 会关闭 fp
    assert opened_images[0].fp is None, \
        "Image.open 应使用 with 语句，确保文件句柄已关闭（fp 应为 None）"
