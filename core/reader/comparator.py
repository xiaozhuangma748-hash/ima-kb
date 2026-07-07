"""智能对比模式：AI 对比两个文档/数据表的异同。

用法：
    from core.reader.comparator import Comparator
    cmp = Comparator()
    result = cmp.compare_docs(doc_id_a, doc_id_b)
    result = cmp.compare_files(file_a, file_b)
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from config import settings
from core.llm.client import get_llm, LLMError
from core.storage import Storage


class Comparator:
    """智能对比器。"""

    def __init__(self, storage: Optional[Storage] = None) -> None:
        if not settings.has_llm():
            raise LLMError("LLM 未配置，智能对比需要 AGNES_API_KEY")
        self.llm = get_llm()
        self.storage = storage or Storage()

    # ---- 文档对比 ----

    def compare_docs(self, doc_id_a: str, doc_id_b: str) -> str:
        """对比两个已入库文档。"""
        doc_a, content_a = self._load_doc(doc_id_a)
        doc_b, content_b = self._load_doc(doc_id_b)

        return self._llm_compare(
            title_a=doc_a.title,
            content_a=content_a,
            title_b=doc_b.title,
            content_b=content_b,
            kind="文档",
        )

    def compare_files(self, file_a: Path, file_b: Path) -> str:
        """对比两个外部文件（文本/数据表）。"""
        # 简单读取（文本文件直接读，数据表转字符串预览）
        content_a = self._read_file(Path(file_a))
        content_b = self._read_file(Path(file_b))

        return self._llm_compare(
            title_a=Path(file_a).name,
            content_a=content_a,
            title_b=Path(file_b).name,
            content_b=content_b,
            kind="文件",
        )

    def compare_doc_and_file(self, doc_id: str, file_path: Path) -> str:
        """对比入库文档和外部文件。"""
        _, content_a = self._load_doc(doc_id)
        content_b = self._read_file(Path(file_path))
        doc = self.storage.get_document(doc_id) or self._find_doc(doc_id)

        return self._llm_compare(
            title_a=doc.title if doc else doc_id,
            content_a=content_a,
            title_b=Path(file_path).name,
            content_b=content_b,
            kind="文档与文件",
        )

    # ---- 内部 ----

    def _load_doc(self, doc_id: str):
        """加载入库文档。"""
        if len(doc_id) < 32:
            doc = self._find_doc(doc_id)
            if doc is None:
                raise FileNotFoundError(f"未找到文档: {doc_id}")
            doc_id = doc.id
        else:
            doc = self.storage.get_document(doc_id)
            if doc is None:
                raise FileNotFoundError(f"未找到文档: {doc_id}")
        chunks = self.storage.get_chunks(doc_id)
        content = "\n\n".join(c.content for c in chunks)
        return doc, content

    def _find_doc(self, doc_id: str):
        for d in self.storage.list_documents(limit=10000):
            if d.id.startswith(doc_id):
                return d
        return None

    def _read_file(self, path: Path) -> str:
        """读取外部文件。"""
        path = path.expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {path}")
        ext = path.suffix.lower()
        # 数据表
        if ext in (".xlsx", ".xls", ".csv", ".tsv"):
            import pandas as pd
            if ext == ".csv":
                df = pd.read_csv(path)
            elif ext == ".tsv":
                df = pd.read_csv(path, sep="\t")
            else:
                df = pd.read_excel(path)
            return df.to_string()
        # 文本/Word/PDF 走 parser
        try:
            from core.ingestion.parser import parse
            parsed = parse(path)
            return parsed.text
        except Exception as e:
            return f"[读取失败: {e}]"

    def _llm_compare(self, title_a: str, content_a: str,
                     title_b: str, content_b: str, kind: str) -> str:
        """调 LLM 做对比。"""
        # 截断避免超 token
        max_len = 4000
        if len(content_a) > max_len:
            content_a = content_a[:max_len] + "\n[截断...]"
        if len(content_b) > max_len:
            content_b = content_b[:max_len] + "\n[截断...]"

        prompt = f"""请对比以下两个{kind}，生成结构化对比报告（Markdown 格式）。

# {kind} A：{title_a}
{content_a}

---

# {kind} B：{title_b}
{content_b}

---

请输出对比报告，包含以下章节：

## 1. 概览对比
- 两者各自的核心主题、规模、对象
- 一句话总结差异

## 2. 共同点
- 列出 3-5 个共同点（编号列表）

## 3. 主要差异
- 列出 3-5 个主要差异（编号列表）
- 每项标明 A 是怎样、B 是怎样

## 4. 关键数字对比
- 如有数字（标准、金额、比例等），用表格对比

## 5. 适用场景对比
- 各自适用什么场景、对象

## 6. 综合建议
- 选择建议、注意事项

请直接输出报告（不要 ```markdown 包裹）。"""

        messages = [
            {
                "role": "system",
                "content": "你是政策分析专家，擅长对比两份文档/数据的异同并给出可执行建议。",
            },
            {"role": "user", "content": prompt},
        ]
        return self.llm.chat(messages, temperature=0.3, max_tokens=1500)
