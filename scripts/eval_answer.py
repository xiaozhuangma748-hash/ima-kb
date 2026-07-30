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
        answer_obj: Optional[Answer] = None
        actual_answer = ""
        snippets: List[str] = []
        try:
            answer_obj = chain.ask(question, enable_hyde=False, enable_decompose=False)
            actual_answer = answer_obj.content
            retrieved = answer_obj.retrieved or []
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
            "low_confidence": answer_obj.low_confidence if answer_obj else False,
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
