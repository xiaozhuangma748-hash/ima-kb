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
    """PDF OCR 失败的页码应记录到 meta.ocr_failed_pages。

    新实现路径：_parse_pdf → _render_pdf_page_to_png + _parallel_ocr_pages → _ocr_png_bytes
    """
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

    # 模拟 OCR 可用但每页都失败（_ocr_png_bytes 抛异常）
    with patch.object(parser, "_check_ocr", return_value=True), \
         patch.object(parser, "_ocr_png_bytes", side_effect=Exception("OCR 失败")):
        result = parser._parse_pdf(pdf_path)

    assert "ocr_failed_pages" in result.meta
    # 3 页都失败
    failed = result.meta["ocr_failed_pages"].split(",")
    assert len(failed) == 3


def test_parse_pdf_records_ocr_empty_pages_as_failed(tmp_path):
    """OCR 返回空文本的页码也应记录到 ocr_failed_pages。

    新实现路径：_parse_pdf → _render_pdf_page_to_png + _parallel_ocr_pages → _ocr_png_bytes
    """
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
         patch.object(parser, "_ocr_png_bytes", return_value=""):  # OCR 返回空
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


# ============================================================
# 并行 OCR 测试（P1-性能: 扫描 PDF 并行 OCR）
# ============================================================

class TestParallelOcrPages:
    """_parallel_ocr_pages 并行 OCR 测试。"""

    def test_empty_input_returns_empty_dict(self):
        """空输入应返回空字典。"""
        assert parser._parallel_ocr_pages([], []) == {}

    def test_single_page_returns_result(self):
        """单页 OCR 应返回正确结果。"""
        with patch.object(parser, "_ocr_png_bytes", return_value="文本A"):
            result = parser._parallel_ocr_pages([1], [b"fake_png_bytes"])
        assert result == {1: "文本A"}

    def test_multiple_pages_all_succeed(self):
        """多页并行 OCR 全部成功。"""
        # 用 png_bytes 内容区分不同页
        def fake_ocr(png_bytes):
            return f"文本-{png_bytes.decode()}"

        with patch.object(parser, "_ocr_png_bytes", side_effect=fake_ocr):
            result = parser._parallel_ocr_pages(
                [1, 2, 3], [b"page1", b"page2", b"page3"],
                max_workers=3,
            )
        assert result[1] == "文本-page1"
        assert result[2] == "文本-page2"
        assert result[3] == "文本-page3"

    def test_partial_failure_returns_empty_for_failed(self):
        """部分页失败时，失败页返回空字符串，不阻塞其他页。"""
        call_count = {"n": 0}

        def fake_ocr(png_bytes):
            call_count["n"] += 1
            if png_bytes == b"fail_page":
                raise RuntimeError("模拟 OCR 失败")
            return f"OK-{png_bytes.decode()}"

        with patch.object(parser, "_ocr_png_bytes", side_effect=fake_ocr):
            result = parser._parallel_ocr_pages(
                [1, 2, 3], [b"ok1", b"fail_page", b"ok3"],
                max_workers=2,
            )
        assert result[1] == "OK-ok1"
        assert result[2] == ""  # 失败页返回空
        assert result[3] == "OK-ok3"
        # 所有页都被调用（失败的也调用了）
        assert call_count["n"] == 3

    def test_max_workers_capped_by_task_count(self):
        """max_workers 不超过任务数。"""
        # 2 个任务，max_workers=10，应正常完成
        with patch.object(parser, "_ocr_png_bytes", return_value="OK") as mock:
            parser._parallel_ocr_pages([1, 2], [b"a", b"b"], max_workers=10)
        assert mock.call_count == 2

    def test_env_var_controls_workers(self, monkeypatch):
        """环境变量 IMA_PDF_OCR_WORKERS 控制并发度。"""
        monkeypatch.setenv("IMA_PDF_OCR_WORKERS", "1")
        # 串行模式应正常工作
        with patch.object(parser, "_ocr_png_bytes", return_value="OK"):
            result = parser._parallel_ocr_pages(
                [1, 2, 3], [b"a", b"b", b"c"],
            )
        assert len(result) == 3


class TestParsePdfParallelOcr:
    """_parse_pdf 并行 OCR 集成测试。"""

    def test_parallel_ocr_pages_recorded_in_meta(self, tmp_path):
        """扫描版 PDF 多页 OCR 成功后应记录到 meta.ocr_pages。"""
        try:
            import fitz  # type: ignore
        except ImportError:
            pytest.skip("PyMuPDF 未安装")

        pdf_path = tmp_path / "scan.pdf"
        doc = fitz.open()
        for _ in range(3):
            doc.new_page()
        doc.save(str(pdf_path))
        doc.close()

        # mock _ocr_png_bytes 返回不同的非空文本（避免被页眉页脚检测误删）
        page_texts = [
            "第一页的 OCR 内容，包含一些文字用于测试。",
            "第二页的 OCR 内容，包含不同的文字。",
            "第三页的 OCR 内容，再次不同的文字。",
        ]
        text_iter = iter(page_texts)

        with patch.object(parser, "_check_ocr", return_value=True), \
             patch.object(parser, "_ocr_png_bytes", side_effect=lambda _: next(text_iter)):
            result = parser._parse_pdf(pdf_path)

        assert "ocr_used" in result.meta
        assert "ocr_pages" in result.meta
        ocr_pages = result.meta["ocr_pages"].split(",")
        assert len(ocr_pages) == 3
        # 文本应包含 OCR 内容
        for t in page_texts:
            assert t in result.text

    def test_parallel_ocr_results_not_corrupted(self, tmp_path):
        """多页 OCR 结果不应错位（每页内容对应正确）。"""
        try:
            import fitz  # type: ignore
        except ImportError:
            pytest.skip("PyMuPDF 未安装")

        pdf_path = tmp_path / "scan.pdf"
        doc = fitz.open()
        for _ in range(3):
            doc.new_page()
        doc.save(str(pdf_path))
        doc.close()

        # 用稳定的标记性内容（足够长且含中文，避免被页眉页脚检测误删）
        page_texts = [
            "UNIQUE_MARKER_PAGE_ONE_UNIQUE_CONTENT_HERE",
            "UNIQUE_MARKER_PAGE_TWO_UNIQUE_CONTENT_HERE",
            "UNIQUE_MARKER_PAGE_THREE_UNIQUE_CONTENT_HERE",
        ]
        text_iter = iter(page_texts)

        with patch.object(parser, "_check_ocr", return_value=True), \
             patch.object(parser, "_ocr_png_bytes", side_effect=lambda _: next(text_iter)):
            result = parser._parse_pdf(pdf_path)

        # 应有 3 个 --- Page N --- 标记
        assert result.text.count("--- Page") == 3
        # 每页的标记内容都应出现在结果中
        for t in page_texts:
            assert t in result.text
