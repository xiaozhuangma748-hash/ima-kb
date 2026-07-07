"""智能阅读模式：逐段展示文档 + AI 解读 + 互动提问。

用法（一般通过 REPL 的 /read 命令使用）：
    from core.reader.reader import SmartReader
    sr = SmartReader()
    sr.open(doc_id)             # 打开文档
    sr.show_chunk(0)            # 显示第 0 段 + AI 解读
    sr.next() / sr.prev()       # 翻段
    sr.ask("这段什么意思")      # 针对当前段提问
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from config import settings
from core.llm.client import get_llm, LLMError
from core.storage import Storage


@dataclass
class ReadingState:
    """阅读状态。"""
    doc_id: str
    doc_title: str
    total_chunks: int
    current_index: int = 0


class SmartReader:
    """智能阅读器：逐段阅读 + AI 实时解读。"""

    def __init__(self, storage: Optional[Storage] = None) -> None:
        if not settings.has_llm():
            raise LLMError("LLM 未配置，智能阅读需要 AGNES_API_KEY")
        self.llm = get_llm()
        self.storage = storage or Storage()
        self.state: Optional[ReadingState] = None
        self.chunks: List = []

    def open(self, doc_id: str) -> ReadingState:
        """打开文档进入阅读模式。"""
        # 支持简写
        if len(doc_id) < 32:
            docs = self.storage.list_documents(limit=10000)
            matched = [d for d in docs if d.id.startswith(doc_id)]
            if not matched:
                raise FileNotFoundError(f"未找到文档: {doc_id}")
            doc_id = matched[0].id

        doc = self.storage.get_document(doc_id)
        if doc is None:
            raise FileNotFoundError(f"未找到文档: {doc_id}")

        self.chunks = self.storage.get_chunks(doc_id)
        if not self.chunks:
            raise ValueError(f"文档无分块: {doc.title}")

        self.state = ReadingState(
            doc_id=doc_id,
            doc_title=doc.title,
            total_chunks=len(self.chunks),
        )
        return self.state

    def current_chunk(self):
        """获取当前分块。"""
        if self.state is None or not self.chunks:
            return None
        return self.chunks[self.state.current_index]

    def next(self):
        """下一段。返回新分块或 None（已到最后）。"""
        if self.state is None:
            return None
        if self.state.current_index < self.state.total_chunks - 1:
            self.state.current_index += 1
            return self.current_chunk()
        return None

    def prev(self):
        """上一段。"""
        if self.state is None:
            return None
        if self.state.current_index > 0:
            self.state.current_index -= 1
            return self.current_chunk()
        return None

    def goto(self, index: int):
        """跳到指定段。"""
        if self.state is None:
            return None
        if 0 <= index < self.state.total_chunks:
            self.state.current_index = index
            return self.current_chunk()
        return None

    def interpret(self) -> str:
        """AI 解读当前段。"""
        chunk = self.current_chunk()
        if chunk is None:
            return "（无内容）"

        prompt = f"""请简要解读以下文档片段（150 字以内）：

标题：{self.state.doc_title}
第 {self.state.current_index + 1}/{self.state.total_chunks} 段

内容：
{chunk.content}

请输出：
1. 这段讲什么（一句话）
2. 关键信息（数字、条件、对象等）
3. 如有难懂的地方，简单解释"""

        messages = [
            {"role": "system", "content": "你是政策解读助手，简洁明了地解释文档内容。"},
            {"role": "user", "content": prompt},
        ]
        return self.llm.chat(messages, temperature=0.2, max_tokens=400)

    def ask(self, question: str) -> str:
        """针对当前段 + 文档上下文提问。"""
        chunk = self.current_chunk()
        if chunk is None:
            return "（无内容）"

        # 取前后各 1 段作为上下文
        ctx_before = self.chunks[self.state.current_index - 1].content \
            if self.state.current_index > 0 else ""
        ctx_after = self.chunks[self.state.current_index + 1].content \
            if self.state.current_index < len(self.chunks) - 1 else ""

        prompt = f"""用户在阅读文档「{self.state.doc_title}」时提问。

当前段（第 {self.state.current_index + 1}/{self.state.total_chunks} 段）：
{chunk.content}

上一段：
{ctx_before[:500]}

下一段：
{ctx_after[:500]}

用户问题：{question}

请基于当前段（必要时参考前后段）回答。回答要具体、引用原文关键句。"""

        messages = [
            {"role": "system", "content": "你是阅读助手，帮助用户理解文档具体内容。"},
            {"role": "user", "content": prompt},
        ]
        return self.llm.chat(messages, temperature=0.3, max_tokens=600)

    def close(self) -> None:
        """退出阅读模式。"""
        self.state = None
        self.chunks = []
