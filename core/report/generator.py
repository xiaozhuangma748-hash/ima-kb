"""一键报告生成：基于文档内容 + LLM 生成结构化 Markdown 分析报告。

用法：
    from core.report.generator import ReportGenerator
    rg = ReportGenerator()
    path = rg.generate(doc_id)              # 生成报告
    path = rg.generate(doc_id, "out.md")    # 指定输出路径
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from config import settings
from core.llm.client import get_llm, LLMError
from core.storage import Storage


class ReportGenerator:
    """基于入库文档生成结构化 Markdown 报告。"""

    def __init__(self, storage: Optional[Storage] = None) -> None:
        if not settings.has_llm():
            raise LLMError("LLM 未配置，生成报告需要 AGNES_API_KEY")
        self.llm = get_llm()
        self.storage = storage or Storage()

    def generate(self, doc_id: str, output_path: Optional[Path] = None) -> Path:
        """生成报告。

        Args:
            doc_id: 文档 ID（支持前 8 位简写）
            output_path: 输出路径（None 则输出到 storage/reports/<title>.md）
        Returns:
            报告文件路径
        """
        # 1. 找文档（支持简写）
        doc = self._find_doc(doc_id)
        if doc is None:
            raise FileNotFoundError(f"未找到文档: {doc_id}")

        # 2. 取所有分块
        chunks = self.storage.get_chunks(doc.id)
        if not chunks:
            raise ValueError(f"文档无分块: {doc.title}")
        content = "\n\n".join(c.content for c in chunks)

        # 3. 调 LLM 生成报告
        report_body = self._llm_generate(doc.title, content, doc.tags)

        # 4. 拼装最终 Markdown
        final_md = self._assemble(doc, chunks, report_body)

        # 5. 写文件
        if output_path is None:
            output_path = Path("storage/reports") / f"{doc.title[:40]}.md"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(final_md, encoding="utf-8")
        return output_path

    # ---- 内部方法 ----

    def _find_doc(self, doc_id: str):
        """支持简写 ID 查找。"""
        if len(doc_id) >= 32:
            return self.storage.get_document(doc_id)
        docs = self.storage.list_documents(limit=10000)
        for d in docs:
            if d.id.startswith(doc_id):
                return d
        return None

    def _llm_generate(self, title: str, content: str, tags: list) -> str:
        """调 LLM 生成报告主体。"""
        # 限制内容长度，避免超 token
        if len(content) > 8000:
            content = content[:8000] + "\n\n[内容过长，已截断...]"

        prompt = f"""请基于以下政策文档内容，生成一份结构化的中文 Markdown 分析报告。

# 文档信息
- 标题：{title}
- 标签：{', '.join(tags) if tags else '无'}

# 文档内容
{content}

# 报告要求
请生成一份包含以下章节的报告（用 Markdown 格式）：

## 1. 文档概览
- 文档类型、发布机构（如能识别）、适用范围
- 核心主题（一句话总结）

## 2. 关键要点
- 列出 3-5 个核心要点（用编号列表）
- 每个要点用 1-2 句话说明

## 3. 详细解读
- 按主题分小节解读关键内容
- 提取具体数字、标准、条件等关键信息
- 标注适用对象和情形

## 4. 实施要点
- 实施主体、流程、时间节点
- 需要关注的配套措施

## 5. 关联建议
- 与其他政策可能的关联点
- 实际应用中的注意事项

## 6. 风险提示
- 可能的歧义或争议点
- 需要进一步明确的问题

请直接输出报告内容（不要 ```markdown 包裹），保持专业客观的语气。"""

        messages = [
            {
                "role": "system",
                "content": "你是政策分析专家，擅长把政策文档转成结构化、可执行的分析报告。",
            },
            {"role": "user", "content": prompt},
        ]
        return self.llm.chat(messages, temperature=0.3, max_tokens=2000)

    def _assemble(self, doc, chunks, report_body: str) -> str:
        """拼装最终 Markdown 报告。"""
        header = f"""# 📋 政策分析报告

> **文档标题**：{doc.title}
> **文档类型**：{doc.file_type}
> **文档标签**：{', '.join(doc.tags) if doc.tags else '无'}
> **分块数**：{doc.chunk_count} 块 / {doc.total_tokens} tokens
> **生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
> **生成工具**：IMA 个人知识库 v4.0

---

"""
        footer = f"""

---

## 📎 元信息

- **文档 ID**：`{doc.id}`
- **原文件**：{doc.file_name}
- **入库时间**：{doc.created_at[:19]}

---

*本报告由 AI 自动生成，仅供辅助理解，具体执行以原文为准。*
"""
        return header + report_body + footer
