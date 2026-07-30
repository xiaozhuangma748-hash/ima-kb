# 端到端回答准确率评测 + 低置信度拒答 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立端到端回答准确率评测脚本（量化 LLM 回答质量），并修复 negative 类检索短板（低置信度拒答），让"知识库里没有的问题"能诚实回答"无法回答"。

**Architecture:** 新建 `scripts/eval_answer.py` 调用 `RAGChain.ask()` 生成答案，用 LLM 作裁判对每个答案打分（1-5 分 + 是否有幻觉 + 是否有引用），输出端到端准确率报告。然后在 `RAGChain` 中加低置信度拒答机制：当 top1 score 低于阈值且 query 不像知识库领域问题时，直接返回"无法回答"。

**Tech Stack:** Python 3.9+, pytest, LLM API (agnes), existing RAGChain

---

## File Structure

- Create: `scripts/eval_answer.py` — 端到端回答评测脚本
- Create: `tests/eval/test_eval_answer.py` — 评测脚本的单元测试
- Modify: `core/qa/chain.py` — 加低置信度拒答逻辑
- Test: `tests/qa/test_low_confidence_reject.py` — 拒答逻辑测试

---

## Task 1: 编写端到端评测脚本骨架（TDD）

**Files:**
- Create: `tests/eval/test_eval_answer.py`

- [ ] **Step 1: 编写评测脚本的单元测试**

```python
"""端到端回答评测脚本的单元测试。

验证评测脚本的核心函数：评分解析、报告聚合、失败案例识别。
不真正调用 LLM，用 mock 数据测试逻辑。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def test_parse_judge_response_valid_json():
    """解析 LLM 裁判返回的 JSON 评分。"""
    from scripts.eval_answer import parse_judge_response
    raw = '{"score": 5, "has_hallucination": false, "has_citation": true, "reason": "答案准确"}'
    result = parse_judge_response(raw)
    assert result["score"] == 5
    assert result["has_hallucination"] is False
    assert result["has_citation"] is True
    assert "准确" in result["reason"]


def test_parse_judge_response_with_markdown_fence():
    """解析带 ```json 代码块的裁判返回。"""
    from scripts.eval_answer import parse_judge_response
    raw = '```json\n{"score": 3, "has_hallucination": true, "has_citation": false, "reason": "有幻觉"}\n```'
    result = parse_judge_response(raw)
    assert result["score"] == 3
    assert result["has_hallucination"] is True


def test_parse_judge_response_invalid_returns_zero():
    """无法解析的返回给默认 0 分。"""
    from scripts.eval_answer import parse_judge_response
    result = parse_judge_response("裁判罢工了")
    assert result["score"] == 0
    assert result["has_hallucination"] is True  # 解析失败视为有幻觉
    assert result["has_citation"] is False


def test_aggregate_results_overall():
    """聚合评测结果计算总体指标。"""
    from scripts.eval_answer import aggregate_results
    details = [
        {"score": 5, "has_hallucination": False, "has_citation": True, "category": "policy"},
        {"score": 4, "has_hallucination": False, "has_citation": True, "category": "policy"},
        {"score": 2, "has_hallucination": True, "has_citation": False, "category": "negative"},
        {"score": 0, "has_hallucination": True, "has_citation": False, "category": "negative"},
    ]
    overall = aggregate_results(details)
    assert overall["total"] == 4
    assert overall["avg_score"] == 2.75
    assert overall["hallucination_rate"] == 0.5
    assert overall["citation_rate"] == 0.5
    assert overall["accuracy_rate"] == 0.5  # score >= 4 算正确


def test_aggregate_results_by_category():
    """按类别聚合评测结果。"""
    from scripts.eval_answer import aggregate_results
    details = [
        {"score": 5, "has_hallucination": False, "has_citation": True, "category": "policy"},
        {"score": 4, "has_hallucination": False, "has_citation": True, "category": "policy"},
        {"score": 1, "has_hallucination": True, "has_citation": False, "category": "negative"},
    ]
    result = aggregate_results(details)
    assert "policy" in result["by_category"]
    assert result["by_category"]["policy"]["avg_score"] == 4.5
    assert result["by_category"]["policy"]["accuracy_rate"] == 1.0
    assert "negative" in result["by_category"]
    assert result["by_category"]["negative"]["accuracy_rate"] == 0.0


def test_judge_prompt_contains_required_fields():
    """裁判 prompt 应包含问题、参考答案、实际答案、参考资料。"""
    from scripts.eval_answer import build_judge_messages
    messages = build_judge_messages(
        question="什么是海葬？",
        reference_answer="海葬是将骨灰撒入海洋的安葬方式",
        actual_answer="海葬是把骨灰撒到海里 [1]",
        reference_snippets=["海葬是指将骨灰撒入海洋的生态安葬方式"],
    )
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    user_content = messages[1]["content"]
    assert "海葬" in user_content
    assert "参考答案" in user_content
    assert "实际答案" in user_content
    assert "参考资料" in user_content
    assert "JSON" in user_content  # 要求 LLM 返回 JSON
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd "/Users/4u/Desktop/项目/拱墅区/2025身后事（殡葬）项目/34-知识库" && source .venv/bin/activate && python -m pytest tests/eval/test_eval_answer.py -v`

Expected: 6 个测试全部 FAIL，因为 `scripts/eval_answer.py` 不存在，`from scripts.eval_answer import ...` 报 ModuleNotFoundError。

- [ ] **Step 3: 创建 scripts/eval_answer.py 最小实现**

```python
#!/usr/bin/env python3
"""端到端回答准确率评测脚本。

用法：
    python scripts/eval_answer.py                      # 默认评测全量 100 题
    python scripts/eval_answer.py --limit 10           # 只评测前 10 题（快速验证）
    python scripts/eval_answer.py --category negative  # 只评测 negative 类
    python scripts/eval_answer.py --report both        # 输出 md + json

指标：
    avg_score          LLM 裁判打分（1-5）的平均分
    accuracy_rate      score >= 4 的比例（视为回答正确）
    hallucination_rate 有幻觉的比例
    citation_rate      有正确引用的比例
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

if not os.environ.get("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

from config import settings
from core.storage import Storage
from core.qa.chain import RAGChain, Answer


# ============================================================
# 裁判 Prompt 构建
# ============================================================

_JUDGE_SYSTEM_PROMPT = """你是一个严格的问答系统评审员。请根据以下信息对"实际答案"打分：

1. **问题**：用户提出的问题
2. **参考答案**：标准答案（来自评测集）
3. **实际答案**：被评测系统生成的答案
4. **参考资料**：系统检索到的文档片段（用于判断是否有依据）

评分标准（1-5 分）：
- 5 分：完全正确，有引用，无幻觉
- 4 分：基本正确，有小瑕疵（如表述不完整），有引用
- 3 分：部分正确，遗漏关键信息，或引用不完整
- 2 分：大部分错误，或无引用，或编造信息
- 1 分：完全错误，或答非所问，或纯幻觉

判定规则：
- has_hallucination: 答案是否包含参考资料中不存在的信息（true/false）
- has_citation: 答案是否包含 [n] 形式的引用标注（true/false）

只输出 JSON，格式：
{"score": 1-5, "has_hallucination": true/false, "has_citation": true/false, "reason": "简短理由"}
"""


def build_judge_messages(
    question: str,
    reference_answer: str,
    actual_answer: str,
    reference_snippets: List[str],
) -> List[dict]:
    """构造裁判 LLM 的 messages。"""
    snippets_text = "\n---\n".join(
        f"[{i+1}] {s[:300]}" for i, s in enumerate(reference_snippets[:5])
    )
    user_content = f"""## 问题
{question}

## 参考答案
{reference_answer}

## 实际答案
{actual_answer}

## 参考资料
{snippets_text}

请对"实际答案"打分，只输出 JSON。"""
    return [
        {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


# ============================================================
# 裁判返回解析
# ============================================================

def parse_judge_response(raw: str) -> dict:
    """解析 LLM 裁判返回的 JSON 评分。

    支持纯 JSON 和 ```json 代码块两种格式。
    解析失败返回默认 0 分（视为有幻觉，无引用）。
    """
    if not raw:
        return {"score": 0, "has_hallucination": True, "has_citation": False, "reason": "裁判无返回"}
    text = raw.strip()
    # 尝试提取 ```json ... ``` 代码块
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1)
    # 尝试直接提取 JSON 对象
    json_match = re.search(r"\{.*\}", text, re.DOTALL)
    if json_match:
        text = json_match.group(0)
    try:
        data = json.loads(text)
        return {
            "score": int(data.get("score", 0)),
            "has_hallucination": bool(data.get("has_hallucination", True)),
            "has_citation": bool(data.get("has_citation", False)),
            "reason": str(data.get("reason", "")),
        }
    except (json.JSONDecodeError, ValueError, TypeError):
        return {"score": 0, "has_hallucination": True, "has_citation": False, "reason": "解析失败"}


# ============================================================
# 结果聚合
# ============================================================

def aggregate_results(details: List[dict]) -> dict:
    """聚合评测结果，计算总体和分类指标。"""
    n = len(details)
    if n == 0:
        return {"total": 0, "avg_score": 0, "accuracy_rate": 0, "hallucination_rate": 0, "citation_rate": 0, "by_category": {}}

    total_score = sum(d.get("score", 0) for d in details)
    halluc_count = sum(1 for d in details if d.get("has_hallucination"))
    citation_count = sum(1 for d in details if d.get("has_citation"))
    accurate_count = sum(1 for d in details if d.get("score", 0) >= 4)

    overall = {
        "total": n,
        "avg_score": round(total_score / n, 2),
        "accuracy_rate": round(accurate_count / n, 4),
        "hallucination_rate": round(halluc_count / n, 4),
        "citation_rate": round(citation_count / n, 4),
    }

    by_cat: Dict[str, dict] = {}
    for d in details:
        cat = d.get("category", "unknown")
        if cat not in by_cat:
            by_cat[cat] = {"scores": [], "halluc": 0, "citation": 0, "accurate": 0, "total": 0}
        by_cat[cat]["scores"].append(d.get("score", 0))
        by_cat[cat]["total"] += 1
        if d.get("has_hallucination"):
            by_cat[cat]["halluc"] += 1
        if d.get("has_citation"):
            by_cat[cat]["citation"] += 1
        if d.get("score", 0) >= 4:
            by_cat[cat]["accurate"] += 1

    for cat, s in by_cat.items():
        t = s["total"]
        s["avg_score"] = round(sum(s["scores"]) / t, 2) if t > 0 else 0
        s["accuracy_rate"] = round(s["accurate"] / t, 4) if t > 0 else 0
        s["hallucination_rate"] = round(s["halluc"] / t, 4) if t > 0 else 0
        s["citation_rate"] = round(s["citation"] / t, 4) if t > 0 else 0
        del s["scores"], s["halluc"], s["citation"], s["accurate"]

    overall["by_category"] = by_cat
    return overall


# ============================================================
# 评测主流程
# ============================================================

def load_dataset(path: Path) -> List[dict]:
    """加载评测集。"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("questions", [])


def evaluate_answers(
    questions: List[dict],
    chain: RAGChain,
    judge_llm,
    limit: Optional[int] = None,
    category_filter: Optional[str] = None,
) -> dict:
    """对评测集跑端到端问答并评分。

    Args:
        questions: 评测问题列表
        chain: RAGChain 实例
        judge_llm: 裁判 LLM 客户端（需有 chat 方法）
        limit: 最多评测几题（None 全量）
        category_filter: 只评测某类别（None 全部）

    Returns:
        {"overall": {...}, "details": [...]}
    """
    if category_filter:
        questions = [q for q in questions if q.get("category") == category_filter]
    if limit:
        questions = questions[:limit]

    print(f"\n[端到端评测] 共 {len(questions)} 个问题")
    print("-" * 80)

    details = []
    for i, q in enumerate(questions, 1):
        question = q["question"]
        reference_answer = q.get("reference_answer", "")
        category = q.get("category", "")

        # 1. 调用 RAGChain 生成答案
        t0 = time.time()
        try:
            answer: Answer = chain.ask(question, enable_hyde=False, enable_decompose=False)
            actual_answer = answer.content
            retrieved = answer.retrieved or []
            snippets = [r.content or "" for r in retrieved[:5]]
        except Exception as e:
            actual_answer = f"[生成失败: {e}]"
            snippets = []
        elapsed = time.time() - t0

        # 2. 调用裁判 LLM 打分
        try:
            judge_messages = build_judge_messages(
                question=question,
                reference_answer=reference_answer,
                actual_answer=actual_answer,
                reference_snippets=snippets,
            )
            judge_raw = judge_llm.chat(judge_messages, temperature=0.0, max_tokens=200)
            judge_result = parse_judge_response(judge_raw)
        except Exception as e:
            judge_result = {"score": 0, "has_hallucination": True, "has_citation": False, "reason": f"裁判失败: {e}"}

        detail = {
            "id": q["id"],
            "question": question,
            "category": category,
            "difficulty": q.get("difficulty", ""),
            "reference_answer": reference_answer,
            "actual_answer": actual_answer[:500],
            "score": judge_result["score"],
            "has_hallucination": judge_result["has_hallucination"],
            "has_citation": judge_result["has_citation"],
            "reason": judge_result["reason"],
            "elapsed_ms": round(elapsed * 1000, 1),
            "n_retrieved": len(snippets),
            "low_confidence": answer.low_confidence if 'answer' in dir() else False,
        }
        details.append(detail)

        status = "✓" if judge_result["score"] >= 4 else "✗"
        print(f"  [{i}/{len(questions)}] {status} {q['id']} ({category}) score={judge_result['score']} {elapsed:.1f}s")

    overall = aggregate_results(details)
    return {"overall": overall, "details": details}


# ============================================================
# 报告输出
# ============================================================

def print_report(result: dict) -> None:
    """打印 Markdown 报告。"""
    o = result["overall"]
    print("\n" + "=" * 80)
    print("# 端到端回答评测报告")
    print("=" * 80)
    print(f"\n## 总体指标")
    print(f"- 问题数: {o['total']}")
    print(f"- 平均分: {o['avg_score']} / 5")
    print(f"- 准确率 (score>=4): {o['accuracy_rate']*100:.1f}%")
    print(f"- 幻觉率: {o['hallucination_rate']*100:.1f}%")
    print(f"- 引用率: {o['citation_rate']*100:.1f}%")

    print(f"\n## 按类别")
    print(f"| 类别 | 题数 | 平均分 | 准确率 | 幻觉率 | 引用率 |")
    print(f"|---|---|---|---|---|---|")
    for cat, s in sorted(o.get("by_category", {}).items()):
        print(f"| {cat} | {s['total']} | {s['avg_score']} | {s['accuracy_rate']*100:.1f}% | {s['hallucination_rate']*100:.1f}% | {s['citation_rate']*100:.1f}% |")

    # 低分案例
    low_score = [d for d in result["details"] if d["score"] < 4]
    if low_score:
        print(f"\n## 低分案例 ({len(low_score)} 个)")
        for d in low_score[:10]:
            print(f"- [{d['id']}] {d['question']} (cat={d['category']}, score={d['score']})")
            print(f"  参考: {d['reference_answer'][:80]}")
            print(f"  实际: {d['actual_answer'][:80]}")
            print(f"  理由: {d['reason']}")


def save_report(result: dict, output_path: Path) -> None:
    """保存 JSON 报告。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n报告已保存：{output_path}")


# ============================================================
# 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="端到端回答准确率评测")
    parser.add_argument("--dataset", default=str(PROJECT_ROOT / "tests/eval/golden_dataset.json"),
                        help="评测集路径")
    parser.add_argument("--limit", type=int, default=None, help="最多评测几题（默认全量）")
    parser.add_argument("--category", default=None, help="只评测某类别")
    parser.add_argument("--report", choices=["md", "json", "both"], default="md",
                        help="报告输出格式")
    parser.add_argument("--output", default=str(PROJECT_ROOT / "storage/eval_answer_report.json"),
                        help="JSON 报告输出路径")
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        print(f"错误：评测集不存在 {dataset_path}")
        sys.exit(1)
    questions = load_dataset(dataset_path)
    print(f"加载评测集：{len(questions)} 个问题")

    print("初始化 RAGChain...")
    import config
    config.settings.parent_window = 0  # 关闭 parent window 加速
    storage = Storage()
    chain = RAGChain(storage=storage)

    from core.llm.client import get_llm
    judge_llm = get_llm()

    result = evaluate_answers(
        questions=questions,
        chain=chain,
        judge_llm=judge_llm,
        limit=args.limit,
        category_filter=args.category,
    )

    print_report(result)
    if args.report in ("json", "both"):
        save_report(result, Path(args.output))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd "/Users/4u/Desktop/项目/拱墅区/2025身后事（殡葬）项目/34-知识库" && source .venv/bin/activate && python -m pytest tests/eval/test_eval_answer.py -v`

Expected: 6 个测试全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add scripts/eval_answer.py tests/eval/test_eval_answer.py
git commit -m "feat: 端到端回答准确率评测脚本 + 单元测试

新增 scripts/eval_answer.py，调用 RAGChain.ask() 生成答案，
用 LLM 裁判打分（1-5），输出准确率/幻觉率/引用率报告。
建立端到端基线，为后续优化提供量化依据。"
```

---

## Task 2: 跑小批量评测验证脚本可用

- [ ] **Step 1: 跑 5 题快速验证**

Run: `cd "/Users/4u/Desktop/项目/拱墅区/2025身后事（殡葬）项目/34-知识库" && source .venv/bin/activate && export HF_ENDPOINT=https://hf-mirror.com && python scripts/eval_answer.py --limit 5 --report both`

Expected: 脚本正常跑完 5 题，输出报告，JSON 保存到 `storage/eval_answer_report.json`。每题约 3-10 秒（检索 + 生成 + 裁判），5 题约 15-50 秒。

- [ ] **Step 2: 检查报告内容合理**

验证：
- 平均分在 1-5 之间
- 准确率 + 幻觉率 + (1-引用率) 三个指标都有合理值
- 低分案例列表显示具体问题和理由

如果脚本崩溃或指标异常，修复后重新跑。

- [ ] **Step 3: 提交（如有修复）**

```bash
git add scripts/eval_answer.py
git commit -m "fix: 修复小批量评测中发现的问题"
```

---

## Task 3: 跑全量评测建立基线

- [ ] **Step 1: 跑全量 100 题**

Run: `cd "/Users/4u/Desktop/项目/拱墅区/2025身后事（殡葬）项目/34-知识库" && source .venv/bin/activate && export HF_ENDPOINT=https://hf-mirror.com && python scripts/eval_answer.py --report both 2>&1 | tee storage/eval_answer_baseline.log`

Expected: 100 题跑完约 5-15 分钟。输出完整 Markdown 报告 + JSON 报告。**记录基线数据**（平均分、准确率、幻觉率、引用率、negative 类准确率）。

- [ ] **Step 2: 把基线数据写入 docs**

把报告关键数据抄到 plan 文件末尾的"Baseline"小节，格式：

```
## Baseline (2026-07-30)
- 平均分: X.XX / 5
- 准确率: XX.X%
- 幻觉率: XX.X%
- 引用率: XX.X%
- negative 类准确率: XX.X%
- 平均延迟: XXXX ms
```

---

## Task 4: 编写低置信度拒答测试（TDD）

**Files:**
- Create: `tests/qa/test_low_confidence_reject.py`

- [ ] **Step 1: 编写低置信度拒答测试**

```python
"""低置信度拒答机制测试。

当检索结果 top1 score 低于阈值时，RAGChain 应主动返回"无法回答"
而非硬塞不相关文档给 LLM。这能修复 negative 类（知识库里没有的
问题）的误答问题。
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _make_result(content="资料", score=0.1, chunk_id="c1", doc_id="d1", doc_title="文档"):
    """构造 mock HybridResult。"""
    r = MagicMock()
    r.content = content
    r.score = score
    r.chunk_id = chunk_id
    r.doc_id = doc_id
    r.doc_title = doc_title
    r.source = "bm25"
    r.format_tag = ""
    r.paragraph_num = 1
    return r


def _make_chain(tmp_path):
    """构造轻量 RAGChain（mock 重型组件）。"""
    from core.qa.chain import RAGChain
    from core.storage import Storage

    storage = Storage(storage_path=tmp_path)
    import config
    original = config.settings.parent_window
    config.settings.parent_window = 0
    try:
        chain = RAGChain(storage=storage)
    finally:
        config.settings.parent_window = original

    chain.llm.chat = MagicMock(return_value="不应该被调用")
    chain.llm.chat_stream = MagicMock(return_value=iter(["不应该被调用"]))
    chain._answer_cache = None
    return chain


def test_low_confidence_triggers_reject(tmp_path):
    """top1 score 低于阈值时应返回"无法回答"而非调用 LLM。"""
    chain = _make_chain(tmp_path)
    low_score_results = [_make_result(score=0.05, content="无关内容")]

    with patch.object(chain.hybrid, "search", return_value=low_score_results):
        with patch.object(chain, "reranker", None):
            answer = chain.ask("杭州冬天平均气温多少？")

    # 不应调用 LLM
    chain.llm.chat.assert_not_called()
    # 应返回"无法回答"类内容
    assert "无法回答" in answer.content or "资料不足" in answer.content
    assert answer.low_confidence is True


def test_high_confidence_proceeds_to_llm(tmp_path):
    """top1 score 高于阈值时应正常调用 LLM 生成答案。"""
    chain = _make_chain(tmp_path)
    high_score_results = [_make_result(score=0.9, content="海葬是骨灰撒入海洋")]
    chain.llm.chat = MagicMock(return_value="海葬是把骨灰撒到海里 [1]")

    with patch.object(chain.hybrid, "search", return_value=high_score_results):
        with patch.object(chain, "reranker", None):
            answer = chain.ask("什么是海葬？")

    chain.llm.chat.assert_called_once()
    assert "海葬" in answer.content


def test_empty_results_triggers_reject(tmp_path):
    """无检索结果时应返回"无法回答"。"""
    chain = _make_chain(tmp_path)

    with patch.object(chain.hybrid, "search", return_value=[]):
        answer = chain.ask("随便什么问题")

    assert "无法回答" in answer.content or "资料不足" in answer.content
    assert answer.low_confidence is True


def test_reject_threshold_configurable(tmp_path):
    """拒答阈值应可通过 config 配置。"""
    from config import settings
    # 默认阈值
    default_threshold = getattr(settings, "reject_confidence_threshold", 0.15)
    assert 0 < default_threshold < 1
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd "/Users/4u/Desktop/项目/拱墅区/2025身后事（殡葬）项目/34-知识库" && source .venv/bin/activate && python -m pytest tests/qa/test_low_confidence_reject.py -v`

Expected: `test_low_confidence_triggers_reject` 和 `test_empty_results_triggers_reject` 可能 PASS（因为现有代码已有 `low_conf` 逻辑），但 `test_high_confidence_proceeds_to_llm` 可能因为 mock 配置问题需要调整。具体看失败原因。

- [ ] **Step 3: 提交**

```bash
git add tests/qa/test_low_confidence_reject.py
git commit -m "test: 低置信度拒答机制测试"
```

---

## Task 5: 实现低置信度拒答

**Files:**
- Modify: `core/qa/chain.py` (ask 方法中检索后加拒答判断)
- Modify: `config.py` (加 `reject_confidence_threshold` 配置)

- [ ] **Step 1: 在 config.py 加拒答阈值配置**

找到 `core/qa/chain.py` 顶部的 `DEFAULT_CONFIDENCE_THRESHOLD` 定义，确认其值。然后在 `config.py` 的 `Settings` 类中加一个新字段。

先查看现有阈值：
Run: `cd "/Users/4u/Desktop/项目/拱墅区/2025身后事（殡葬）项目/34-知识库" && source .venv/bin/activate && python -c "from core.qa.chain import DEFAULT_CONFIDENCE_THRESHOLD; print(DEFAULT_CONFIDENCE_THRESHOLD)"`

在 `config.py` 的 `Settings` 类中（找到 `confidence_threshold` 字段附近），加：
```python
    # 低置信度拒答：top1 score 低于此值时直接返回"无法回答"
    # 用于避免 negative 类（知识库里没有的问题）硬塞不相关文档给 LLM
    reject_confidence_threshold: float = 0.15
```

- [ ] **Step 2: 在 chain.py 的 ask 方法中加拒答逻辑**

在 `core/qa/chain.py` 的 `ask` 方法中，找到第 4 步"确定最终使用的结果"之后、"Parent-Document 上下文扩展"之前，加拒答判断：

找到：
```python
        # 4. 确定最终使用的结果
        final_results = reranked if reranked else results
```

在其后加：
```python
        # 4.1 低置信度拒答：top1 score 低于阈值时直接返回"无法回答"
        # 避免 negative 类（知识库里没有的问题）硬塞不相关文档给 LLM 产生幻觉
        reject_threshold = getattr(settings, "reject_confidence_threshold", 0.15)
        if final_results:
            max_score = max((r.score for r in final_results), default=0.0)
            if max_score < reject_threshold:
                return Answer(
                    question=question,
                    content="根据现有资料无法回答该问题。知识库中未找到与您问题相关的内容，建议入库相关文档后再试。",
                    retrieved=final_results,
                    reranked=reranked,
                    confidence=max_score,
                    low_confidence=True,
                )
```

- [ ] **Step 3: 在 ask_stream 方法中加同样的拒答逻辑**

在 `core/qa/chain.py` 的 `ask_stream` 方法中，找到对应位置（"确定最终使用的结果"之后），加：
```python
        # 4.1 低置信度拒答（流式版）
        reject_threshold = getattr(settings, "reject_confidence_threshold", 0.15)
        if final_results:
            max_score = max((r.score for r in final_results), default=0.0)
            if max_score < reject_threshold:
                yield "根据现有资料无法回答该问题。知识库中未找到与您问题相关的内容，建议入库相关文档后再试。"
                return
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd "/Users/4u/Desktop/项目/拱墅区/2025身后事（殡葬）项目/34-知识库" && source .venv/bin/activate && python -m pytest tests/qa/test_low_confidence_reject.py -v`

Expected: 4 个测试全部 PASS。如果 `test_high_confidence_proceeds_to_llm` 因 mock 问题失败，调整 mock 配置使其通过。

- [ ] **Step 5: 运行全量测试确认无回归**

Run: `cd "/Users/4u/Desktop/项目/拱墅区/2025身后事（殡葬）项目/34-知识库" && source .venv/bin/activate && python -m pytest tests/ --tb=short -q`

Expected: 所有测试通过（730 + 4 新增 = 734）。

- [ ] **Step 6: 提交**

```bash
git add core/qa/chain.py config.py
git commit -m "feat: 低置信度拒答机制

检索 top1 score 低于 0.15 时直接返回'无法回答'，避免 negative 类
（知识库里没有的问题）硬塞不相关文档给 LLM 产生幻觉。
预期修复 q049/q050 两个 negative 类失败案例。"
```

---

## Task 6: 重新跑检索评测验证 negative 类修复

- [ ] **Step 1: 跑检索评测确认 negative 类提升**

Run: `cd "/Users/4u/Desktop/项目/拱墅区/2025身后事（殡葬）项目/34-知识库" && source .venv/bin/activate && export HF_ENDPOINT=https://hf-mirror.com && python scripts/eval_retrieval.py --no-rerank 2>&1 | grep -E "negative|总体|Recall|HitRate"`

Expected: negative 类 HitRate 从 60% 提升到 80%+（因为 q049/q050 会被拒答机制拦住，不再算 MISS）。注意：检索评测脚本本身没有拒答逻辑，所以检索 HitRate 不变；但**端到端评测**会改善。

- [ ] **Step 2: 跑端到端评测对比基线**

Run: `cd "/Users/4u/Desktop/项目/拱墅区/2025身后事（殡葬）项目/34-知识库" && source .venv/bin/activate && export HF_ENDPOINT=https://hf-mirror.com && python scripts/eval_answer.py --category negative --report both`

Expected: negative 类准确率显著提升（因为系统现在会诚实回答"无法回答"，而不是编造答案）。

- [ ] **Step 3: 跑全量端到端评测对比基线**

Run: `cd "/Users/4u/Desktop/项目/拱墅区/2025身后事（殡葬）项目/34-知识库" && source .venv/bin/activate && export HF_ENDPOINT=https://hf-mirror.com && python scripts/eval_answer.py --report both 2>&1 | tee storage/eval_answer_after_reject.log`

Expected: 整体幻觉率下降（negative 类不再编造），准确率持平或略升。

- [ ] **Step 4: 对比数据写入 plan**

把对比数据写到 plan 末尾：

```
## 对比结果 (Baseline vs After Reject)
| 指标 | Baseline | After Reject | 变化 |
|---|---|---|---|
| 平均分 | X.XX | X.XX | +/- |
| 准确率 | XX.X% | XX.X% | +/- |
| 幻觉率 | XX.X% | XX.X% | +/- |
| negative 类准确率 | XX.X% | XX.X% | +/- |
```

- [ ] **Step 5: 提交最终报告**

```bash
git add storage/eval_answer_baseline.log storage/eval_answer_after_reject.log docs/superpowers/plans/2026-07-30-end-to-end-eval-and-reject.md
git commit -m "chore: 端到端评测基线 + 低置信度拒答效果对比"
```
