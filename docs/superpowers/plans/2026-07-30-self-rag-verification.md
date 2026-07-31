# Self-RAG 答案验证 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 RAGChain 答案生成后加 Self-RAG 自我验证——逐句检查答案内容是否真的被检索资料支持，不通过的句子标注"⚠️ 未经资料支持"或触发重新生成，直接砍掉幻觉。

**Architecture:** 新建 `core/qa/self_verifier.py` 模块，接收 question + answer + snippets，调用 LLM 逐句验证并返回 `VerificationResult`（含验证后的答案、是否有幻觉、幻觉句子列表）。在 `RAGChain.ask()` 的 LLM 生成之后、引用校验之前接入。带配置开关（默认开启），失败回退到原答案，最大重生成 1 次防止死循环。

**Tech Stack:** Python 3.9+, LLM API, existing RAGChain

---

## File Structure

- Create: `core/qa/self_verifier.py` — Self-RAG 验证模块（独立、可测、可配置开关）
- Create: `tests/qa/test_self_verifier.py` — 验证模块单元测试
- Modify: `core/qa/chain.py` — ask() 方法在 LLM 生成后接入验证
- Modify: `config.py` — 加 `enable_self_verify` / `self_verify_max_retries` 配置

---

## Task 1: 编写 Self-RAG 验证模块单元测试（TDD）

**Files:**
- Create: `tests/qa/test_self_verifier.py`

- [x] **Step 1: 编写验证模块的单元测试**

```python
"""Self-RAG 答案验证模块单元测试。

验证模块的核心功能：解析 LLM 返回的验证结果、标注幻觉句子、
构造验证后的答案。不真正调用 LLM，用 mock 测试逻辑。
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def test_parse_verify_response_all_grounded():
    """所有句子都有依据时返回 has_hallucination=False。"""
    from core.qa.self_verifier import parse_verify_response
    raw = '{"sentences": [{"text": "海葬是骨灰撒入海洋", "grounded": true, "citation": 1}], "has_hallucination": false}'
    result = parse_verify_response(raw)
    assert result["has_hallucination"] is False
    assert len(result["sentences"]) == 1
    assert result["sentences"][0]["grounded"] is True
    assert result["sentences"][0]["citation"] == 1


def test_parse_verify_response_has_hallucination():
    """有幻觉句子时返回 has_hallucination=True。"""
    from core.qa.self_verifier import parse_verify_response
    raw = '{"sentences": [{"text": "海葬免费", "grounded": false, "citation": null}, {"text": "海葬需申请", "grounded": true, "citation": 2}], "has_hallucination": true}'
    result = parse_verify_response(raw)
    assert result["has_hallucination"] is True
    assert len(result["sentences"]) == 2
    assert result["sentences"][0]["grounded"] is False
    assert result["sentences"][1]["grounded"] is True


def test_parse_verify_response_with_markdown_fence():
    """解析带 ```json 代码块的返回。"""
    from core.qa.self_verifier import parse_verify_response
    raw = '```json\n{"sentences": [], "has_hallucination": false}\n```'
    result = parse_verify_response(raw)
    assert result["has_hallucination"] is False


def test_parse_verify_response_invalid_returns_unverified():
    """无法解析时返回 None 表示跳过验证（不破坏原答案）。"""
    from core.qa.self_verifier import parse_verify_response
    result = parse_verify_response("验证失败")
    assert result is None


def test_mark_ungrounded_sentences():
    """给幻觉句子加 ⚠️ 标注。"""
    from core.qa.self_verifier import mark_ungrounded_sentences
    sentences = [
        {"text": "海葬是骨灰撒入海洋", "grounded": True, "citation": 1},
        {"text": "海葬完全免费", "grounded": False, "citation": None},
        {"text": "需提前申请", "grounded": True, "citation": 2},
    ]
    result = mark_ungrounded_sentences(sentences)
    assert "海葬是骨灰撒入海洋" in result
    assert "⚠️ 未经资料支持" in result
    assert "海葬完全免费" in result
    # 有依据的句子不应有标注
    assert "海葬是骨灰撒入海洋 ⚠️" not in result


def test_build_verify_messages_contains_required_fields():
    """验证 prompt 应包含问题、答案、参考资料。"""
    from core.qa.self_verifier import build_verify_messages
    messages = build_verify_messages(
        question="什么是海葬？",
        answer="海葬是把骨灰撒到海里 [1]。海葬完全免费。",
        snippets=["海葬是指将骨灰撒入海洋的生态安葬方式"],
    )
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    user_content = messages[1]["content"]
    assert "海葬" in user_content
    assert "参考资料" in user_content
    assert "JSON" in user_content


def test_self_verifier_no_hallucination_returns_original():
    """无幻觉时返回原答案，不修改。"""
    from core.qa.self_verifier import SelfVerifier, VerificationResult

    mock_llm = MagicMock()
    # LLM 返回：所有句子都有依据
    mock_llm.chat.return_value = '{"sentences": [{"text": "海葬是骨灰撒入海洋", "grounded": true, "citation": 1}], "has_hallucination": false}'
    verifier = SelfVerifier(llm=mock_llm)

    result = verifier.verify(
        question="什么是海葬？",
        answer="海葬是把骨灰撒到海里 [1]。",
        snippets=["海葬是指将骨灰撒入海洋的生态安葬方式"],
    )
    assert isinstance(result, VerificationResult)
    assert result.has_hallucination is False
    assert result.verified_answer == "海葬是把骨灰撒到海里 [1]。"
    assert result.needs_regenerate is False


def test_self_verifier_has_hallucination_marks_sentences():
    """有幻觉时标注幻觉句子，needs_regenerate=False（标注而非重生成）。"""
    from core.qa.self_verifier import SelfVerifier

    mock_llm = MagicMock()
    mock_llm.chat.return_value = '{"sentences": [{"text": "海葬是骨灰撒入海洋", "grounded": true, "citation": 1}, {"text": "海葬完全免费", "grounded": false, "citation": null}], "has_hallucination": true}'
    verifier = SelfVerifier(llm=mock_llm)

    result = verifier.verify(
        question="什么是海葬？",
        answer="海葬是骨灰撒入海洋 [1]。海葬完全免费。",
        snippets=["海葬是指将骨灰撒入海洋的生态安葬方式"],
    )
    assert result.has_hallucination is True
    assert "⚠️ 未经资料支持" in result.verified_answer
    assert "海葬完全免费" in result.verified_answer
    # 默认模式只标注不重生成
    assert result.needs_regenerate is False


def test_self_verifier_llm_failure_returns_unverified():
    """LLM 调用失败时返回 None（跳过验证，保留原答案）。"""
    from core.qa.self_verifier import SelfVerifier

    mock_llm = MagicMock()
    mock_llm.chat.side_effect = Exception("API 挂了")
    verifier = SelfVerifier(llm=mock_llm)

    result = verifier.verify(
        question="什么是海葬？",
        answer="海葬是骨灰撒到海里 [1]。",
        snippets=["海葬是指将骨灰撒入海洋"],
    )
    assert result is None


def test_self_verifier_disabled_returns_none():
    """enable=False 时直接返回 None。"""
    from core.qa.self_verifier import SelfVerifier

    mock_llm = MagicMock()
    verifier = SelfVerifier(llm=mock_llm, enabled=False)
    result = verifier.verify("问题", "答案", ["资料"])
    assert result is None
    mock_llm.chat.assert_not_called()
```

- [x] **Step 2: 运行测试验证失败**

Run: `cd "/Users/4u/Desktop/项目/拱墅区/2025身后事（殡葬）项目/34-知识库" && source .venv/bin/activate && python -m pytest tests/qa/test_self_verifier.py -v`

Expected: 9 个测试全部 FAIL，因为 `core/qa/self_verifier.py` 不存在。

- [x] **Step 3: 提交测试**

```bash
git add tests/qa/test_self_verifier.py
git commit -m "test: Self-RAG 答案验证模块单元测试"
```

---

## Task 2: 实现 Self-RAG 验证模块

**Files:**
- Create: `core/qa/self_verifier.py`

- [x] **Step 1: 创建 self_verifier.py**

```python
"""Self-RAG 答案自我验证模块。

在 RAGChain 生成答案后，调用 LLM 逐句验证答案是否被检索资料支持：
- 有依据的句子保留
- 无依据的句子（幻觉）标注 "⚠️ 未经资料支持"
- LLM 调用失败时跳过验证，保留原答案（不破坏现有流程）

参考论文：Self-RAG (Asai et al., 2023.10, arXiv:2310.11511)
本项目用 Prompt 工程版，不训练专门模型。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


# ============================================================
# 数据结构
# ============================================================

@dataclass
class VerificationResult:
    """验证结果。"""
    has_hallucination: bool  # 是否检测到幻觉
    verified_answer: str  # 验证后的答案（幻觉句子已标注）
    needs_regenerate: bool = False  # 是否需要重新生成（默认 False，只标注）
    hallucinated_sentences: List[str] = field(default_factory=list)


# ============================================================
# 裁判 Prompt
# ============================================================

_VERIFY_SYSTEM_PROMPT = """你是一个严格的答案验证员。请逐句检查"答案"中的每个句子是否被"参考资料"支持。

判定规则：
- grounded=true：该句子的信息能在参考资料中找到依据（可 paraphrase）
- grounded=false：该句子的信息在参考资料中找不到依据（幻觉/编造）
- citation：该句子依据来自第几条参考资料（1-based），无依据时为 null

只输出 JSON，格式：
{
  "sentences": [
    {"text": "句子原文", "grounded": true/false, "citation": 1 或 null}
  ],
  "has_hallucination": true/false
}
"""


def build_verify_messages(
    question: str,
    answer: str,
    snippets: List[str],
) -> List[dict]:
    """构造验证 LLM 的 messages。"""
    snippets_text = "\n---\n".join(
        f"[{i+1}] {s[:400]}" for i, s in enumerate(snippets[:5])
    )
    user_content = f"""## 问题
{question}

## 答案（需逐句验证）
{answer}

## 参考资料
{snippets_text}

请逐句验证答案，只输出 JSON。"""
    return [
        {"role": "system", "content": _VERIFY_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


# ============================================================
# 解析裁判返回
# ============================================================

def parse_verify_response(raw: str) -> Optional[dict]:
    """解析 LLM 验证返回的 JSON。

    支持纯 JSON 和 ```json 代码块。
    解析失败返回 None（调用方应跳过验证，保留原答案）。
    """
    if not raw:
        return None
    text = raw.strip()
    # 提取 ```json ... ``` 代码块
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1)
    # 提取 JSON 对象
    json_match = re.search(r"\{.*\}", text, re.DOTALL)
    if json_match:
        text = json_match.group(0)
    try:
        data = json.loads(text)
        if "sentences" not in data or "has_hallucination" not in data:
            return None
        return {
            "sentences": data["sentences"],
            "has_hallucination": bool(data["has_hallucination"]),
        }
    except (json.JSONDecodeError, ValueError, TypeError):
        return None


# ============================================================
# 标注幻觉句子
# ============================================================

def mark_ungrounded_sentences(sentences: List[dict]) -> str:
    """构造验证后的答案文本，给幻觉句子加 ⚠️ 标注。

    Args:
        sentences: [{"text": "...", "grounded": true/false, "citation": 1 或 null}]

    Returns:
        验证后的答案文本（幻觉句子标注 ⚠️）
    """
    parts = []
    for s in sentences:
        text = s.get("text", "")
        grounded = s.get("grounded", True)
        if grounded:
            parts.append(text)
        else:
            parts.append(f"{text} ⚠️ 未经资料支持")
    return "".join(parts)


# ============================================================
# SelfVerifier 主类
# ============================================================

class SelfVerifier:
    """Self-RAG 答案验证器。

    用法：
        verifier = SelfVerifier(llm=get_llm())
        result = verifier.verify(question, answer, snippets)
        if result is not None:
            answer = result.verified_answer  # 用验证后的答案替换
    """

    def __init__(
        self,
        llm,
        enabled: bool = True,
        max_retries: int = 0,  # 默认 0 = 只标注不重生成
    ) -> None:
        self.llm = llm
        self.enabled = enabled
        self.max_retries = max_retries

    def verify(
        self,
        question: str,
        answer: str,
        snippets: List[str],
    ) -> Optional[VerificationResult]:
        """验证答案是否被资料支持。

        Args:
            question: 用户问题
            answer: LLM 生成的答案
            snippets: 检索到的资料片段

        Returns:
            VerificationResult，或 None（验证跳过/失败时）
        """
        if not self.enabled:
            return None
        if not answer.strip() or not snippets:
            return None

        try:
            messages = build_verify_messages(question, answer, snippets)
            raw = self.llm.chat(messages, temperature=0.0, max_tokens=400)
        except Exception as e:
            logger.warning(f"Self-RAG 验证 LLM 调用失败，跳过: {e}")
            return None

        parsed = parse_verify_response(raw)
        if parsed is None:
            logger.warning("Self-RAG 验证返回解析失败，跳过")
            return None

        sentences = parsed["sentences"]
        has_halluc = parsed["has_hallucination"]
        verified = mark_ungrounded_sentences(sentences) if has_halluc else answer
        hallucinated = [s["text"] for s in sentences if not s.get("grounded", True)]

        return VerificationResult(
            has_hallucination=has_halluc,
            verified_answer=verified,
            needs_regenerate=False,  # 默认只标注不重生成
            hallucinated_sentences=hallucinated,
        )
```

- [x] **Step 2: 运行测试验证通过**

Run: `cd "/Users/4u/Desktop/项目/拱墅区/2025身后事（殡葬）项目/34-知识库" && source .venv/bin/activate && python -m pytest tests/qa/test_self_verifier.py -v`

Expected: 9 个测试全部 PASS。

- [x] **Step 3: 提交**

```bash
git add core/qa/self_verifier.py
git commit -m "feat: Self-RAG 答案验证模块

新增 core/qa/self_verifier.py：
- 逐句验证答案是否被检索资料支持
- 幻觉句子标注 ⚠️ 未经资料支持
- LLM 调用失败时跳过验证，保留原答案（不破坏现有流程）
- 默认只标注不重生成（max_retries=0）"
```

---

## Task 3: 在 config.py 加配置开关

**Files:**
- Modify: `config.py`

- [x] **Step 1: 加配置字段**

在 `config.py` 的 `Settings` 类中，找到 `reject_confidence_threshold` 字段附近，加：

```python
    # ---- Self-RAG 答案验证 ----
    # 启用后 LLM 生成答案后逐句验证是否被资料支持，幻觉句子标注 ⚠️
    # 关闭后直接返回 LLM 原始答案（省一次 LLM 调用）
    enable_self_verify: bool = field(default_factory=lambda: _get_env("ENABLE_SELF_VERIFY", "1") == "1")
    # Self-RAG 验证失败后是否重新生成（0=只标注不重生成，推荐；1=重生成一次）
    self_verify_max_retries: int = field(default_factory=lambda: int(_get_env("SELF_VERIFY_MAX_RETRIES", "0")))
```

- [x] **Step 2: 验证配置加载**

Run: `cd "/Users/4u/Desktop/项目/拱墅区/2025身后事（殡葬）项目/34-知识库" && source .venv/bin/activate && python -c "from config import settings; print('enable_self_verify:', settings.enable_self_verify); print('max_retries:', settings.self_verify_max_retries)"`

Expected: 输出 `enable_self_verify: True` 和 `max_retries: 0`

- [x] **Step 3: 提交**

```bash
git add config.py
git commit -m "feat: 加 Self-RAG 验证配置开关 enable_self_verify"
```

---

## Task 4: 在 RAGChain.ask() 中接入 Self-RAG 验证

**Files:**
- Modify: `core/qa/chain.py`

- [x] **Step 1: 在 chain.py 顶部加 import**

在 `core/qa/chain.py` 的 import 区域（现有 `from core.qa.citation_validator import ...` 附近），加：

```python
from core.qa.self_verifier import SelfVerifier, VerificationResult
```

- [x] **Step 2: 在 RAGChain.__init__ 中初始化 SelfVerifier**

找到 `RAGChain.__init__` 方法，在 `self.reranker = ...` 之后加：

```python
        # Self-RAG 答案验证器（可选，失败回退原答案）
        self.self_verifier: Optional[SelfVerifier] = None
        if getattr(settings, "enable_self_verify", True) and self.llm is not None:
            try:
                self.self_verifier = SelfVerifier(
                    llm=self.llm,
                    enabled=True,
                    max_retries=getattr(settings, "self_verify_max_retries", 0),
                )
            except Exception:
                self.self_verifier = None
```

- [x] **Step 3: 在 ask() 的 LLM 生成之后接入验证**

在 `core/qa/chain.py` 的 `ask` 方法中，找到 line 445 `content = self.llm.chat(...)` 之后、line 459 `# 7. 构造引用列表` 之前，加：

```python
        # 6.1 Self-RAG 答案验证：逐句检查答案是否被资料支持
        # 幻觉句子标注 ⚠️ 未经资料支持，失败回退原答案
        if self.self_verifier is not None and content.strip():
            try:
                snippets_for_verify = [r.content or "" for r in final_results[:5]]
                verify_result = self.self_verifier.verify(
                    question=question,
                    answer=content,
                    snippets=snippets_for_verify,
                )
                if verify_result is not None and verify_result.has_hallucination:
                    # 用标注后的答案替换
                    content = verify_result.verified_answer
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"Self-RAG 验证异常，跳过: {e}")
```

- [x] **Step 4: 在 ask_stream() 中也接入验证**

在 `ask_stream` 方法中，找到流式生成结束后（`full_content = "".join(...)` 之后），加：

```python
        # Self-RAG 验证（流式版：验证后只追加警告，不替换已流式输出的内容）
        if self.self_verifier is not None and full_content.strip():
            try:
                snippets_for_verify = [r.content or "" for r in final_results[:5]]
                verify_result = self.self_verifier.verify(
                    question=question,
                    answer=full_content,
                    snippets=snippets_for_verify,
                )
                if verify_result is not None and verify_result.has_hallucination:
                    yield "\n\n⚠️ 注意：以上回答中部分内容未经资料支持，请谨慎参考。"
            except Exception:
                pass
```

- [x] **Step 5: 运行已有测试确认无回归**

Run: `cd "/Users/4u/Desktop/项目/拱墅区/2025身后事（殡葬）项目/34-知识库" && source .venv/bin/activate && python -m pytest tests/qa/ tests/test_context_engine.py -v --tb=short 2>&1 | tail -20`

Expected: 所有现有测试继续通过（SelfVerifier 在 mock 测试中 llm.chat 返回固定字符串，验证可能触发但失败回退不影响）。

如果 `test_context_engine.py` 的 mock chain 因为新增 SelfVerifier 初始化失败，在 mock chain 构造时设置 `chain.self_verifier = None` 跳过验证。

- [x] **Step 6: 提交**

```bash
git add core/qa/chain.py
git commit -m "feat: RAGChain.ask() 接入 Self-RAG 答案验证

LLM 生成答案后逐句验证是否被资料支持：
- 幻觉句子标注 ⚠️ 未经资料支持
- 验证失败回退原答案，不破坏现有流程
- 流式版在末尾追加警告（不替换已输出内容）"
```

---

## Task 5: 跑 negative 类端到端评测对比

- [x] **Step 1: 跑 negative 类评测（Self-RAG 启用）**

Run: `cd "/Users/4u/Desktop/项目/拱墅区/2025身后事（殡葬）项目/34-知识库" && source .venv/bin/activate && export HF_ENDPOINT=https://hf-mirror.com && export PYTHONUNBUFFERED=1 && python scripts/eval_answer.py --category negative --report both --output storage/eval_answer_negative_with_selfrag.json 2>&1`

Expected: 5 题约 5-8 分钟（每题多一次 LLM 验证调用）。记录平均分、准确率、幻觉率、引用率。

- [x] **Step 2: 对比数据**

对比三组数据：
- Baseline（无硬拒答、无 Self-RAG）：平均 4.6，准确率 80%，幻觉率 0%，引用率 40%
- After Reject（有硬拒答、无 Self-RAG）：平均 4.6，准确率 80%，幻觉率 0%，引用率 60%
- After Self-RAG（有硬拒答、有 Self-RAG）：？

预期：Self-RAG 对 negative 类影响不大（因为这些答案本来就是"无法回答"），但对其他类别（policy/process 等）可能有显著幻觉下降效果。

- [x] **Step 3: 跑其他类别评测（可选，验证 Self-RAG 对真实问题的效果）**

Run: `cd "/Users/4u/Desktop/项目/拱墅区/2025身后事（殡葬）项目/34-知识库" && source .venv/bin/activate && export HF_ENDPOINT=https://hf-mirror.com && export PYTHONUNBUFFERED=1 && python scripts/eval_answer.py --category policy --limit 10 --report both --output storage/eval_answer_policy_with_selfrag.json 2>&1`

Expected: 10 题约 10-15 分钟。对比幻觉率是否下降。

- [x] **Step 4: 提交评测报告**

```bash
git add storage/eval_answer_negative_with_selfrag.json storage/eval_answer_policy_with_selfrag.json
git commit -m "chore: Self-RAG 端到端评测对比报告"
```

---

## Task 6: 运行全量测试确认无回归

- [x] **Step 1: 跑全量测试**

Run: `cd "/Users/4u/Desktop/项目/拱墅区/2025身后事（殡葬）项目/34-知识库" && source .venv/bin/activate && python -m pytest tests/ --tb=short -q 2>&1 | tail -10`

Expected: 全部通过（740 + 9 新增 = 749 passed, 0 failed）。如果 `test_context_engine.py` 因 SelfVerifier 初始化失败，在 mock chain 构造时加 `chain.self_verifier = None`。

- [x] **Step 2: 修复任何回归（如有）**

如果有测试因 SelfVerifier 初始化或验证逻辑失败：
1. 在 mock chain 测试中设置 `chain.self_verifier = None`
2. 不要禁用生产环境的 SelfVerifier

- [x] **Step 3: 提交修复（如有）**

```bash
git add tests/
git commit -m "fix: 修复 Self-RAG 接入导致的测试回归"
```
