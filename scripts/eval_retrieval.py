#!/usr/bin/env python3
"""检索质量评测脚本。

用法：
    python scripts/eval_retrieval.py                      # 默认评测（带 rerank）
    python scripts/eval_retrieval.py --no-rerank          # 不带 rerank（baseline）
    python scripts/eval_retrieval.py --reranker llm       # 指定用 LLM reranker
    python scripts/eval_retrieval.py --top-k 10          # 改 top_k
    python scripts/eval_retrieval.py --report md          # 输出 Markdown 报告

指标：
    Recall@k   前 k 条结果是否命中标准答案
    MRR        平均倒数排名（1/rank，越接近 1 越好）
    HitRate    至少 1 条命中的问题占比
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

# 项目根目录加入 sys.path
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

# 设置 HF 镜像（中国大陆）
if not os.environ.get("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

from config import settings
from core.storage import Storage
from core.retrieval.hybrid import HybridRetriever, HybridResult
from core.retrieval.rerank import create_reranker


# ============================================================
# 评测指标
# ============================================================

def _is_hit(result: HybridResult, expected_keywords: List[str], expected_titles: List[str]) -> bool:
    """检查单个结果是否命中标准答案。

    命中条件（OR）：
    1. result.content 包含 expected_keywords 中的任一关键词
    2. result.doc_title 包含 expected_titles 中的任一子串
    """
    content = (result.content or "").lower()
    title = (result.doc_title or "").lower()
    for kw in expected_keywords:
        if kw.lower() in content:
            return True
    for t in expected_titles:
        if t.lower() in title:
            return True
    return False


def compute_recall_at_k(results: List[HybridResult], expected_kw: List[str], expected_t: List[str], k: int) -> int:
    """Recall@k：前 k 条结果是否命中（二值，0/1）。"""
    for r in results[:k]:
        if _is_hit(r, expected_kw, expected_t):
            return 1
    return 0


def compute_mrr(results: List[HybridResult], expected_kw: List[str], expected_t: List[str]) -> float:
    """MRR：1/rank（第一个命中结果的排名的倒数）。"""
    for i, r in enumerate(results, 1):
        if _is_hit(r, expected_kw, expected_t):
            return 1.0 / i
    return 0.0


def compute_ndcg_at_k(results: List[HybridResult], expected_kw: List[str], expected_t: List[str], k: int) -> float:
    """NDCG@k：归一化折损累积增益（命中=1，未命中=0）。"""
    dcg = 0.0
    for i, r in enumerate(results[:k], 1):
        rel = 1.0 if _is_hit(r, expected_kw, expected_t) else 0.0
        dcg += rel / (1.0 + i)  # 简化版 DCG：rel/log2(i+1) 的近似
    # IDCG：所有命中都排在前面的理想情况
    idcg = sum(1.0 / (1.0 + i) for i in range(1, min(k, len(results)) + 1))
    return dcg / idcg if idcg > 0 else 0.0


# ============================================================
# 评测流程
# ============================================================

def load_dataset(path: Path) -> List[dict]:
    """加载评测集。"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("questions", [])


def evaluate(
    questions: List[dict],
    retriever: HybridRetriever,
    reranker=None,
    top_k: int = 6,
    top_n: int = 5,
) -> dict:
    """对评测集跑一遍检索并计算指标。

    Args:
        questions: 评测问题列表
        retriever: 混合检索器
        reranker: 重排序器（None 表示不重排）
        top_k: 检索候选数
        top_n: 重排后返回数量

    Returns:
        {
            "overall": {"recall@5": ..., "mrr": ..., "ndcg@5": ..., "hit_rate": ...},
            "by_category": {cat: {...}},
            "details": [{question_id, hit, rank, ...}, ...],
        }
    """
    results_detail = []
    hit_count = 0

    print(f"\n[评测] 共 {len(questions)} 个问题，top_k={top_k}, rerank={'yes' if reranker else 'no'}")
    print("-" * 80)

    for i, q in enumerate(questions, 1):
        query = q["question"]
        expected_kw = q.get("expected_doc_keywords", [])
        expected_t = q.get("expected_doc_titles_containing", [])

        # 检索
        t0 = time.time()
        try:
            results = retriever.search(query, top_k=top_k, use_cache=False)
        except Exception as e:
            print(f"  [{i}/{len(questions)}] {q['id']} 检索失败: {e}")
            results_detail.append({
                "id": q["id"], "question": query, "category": q.get("category", ""),
                "hit": False, "rank": -1, "n_results": 0, "error": str(e),
            })
            continue

        # 重排序
        if reranker:
            try:
                reranked = reranker.rerank(query, results, top_n=min(top_n, len(results)))
                # RerankResult → 临时对象供 _is_hit 使用
                from core.retrieval.hybrid import HybridResult as _HR
                eval_results = [
                    _HR(chunk_id=r.chunk_id, doc_id=r.doc_id, score=r.score,
                        source=r.source, content=r.content, doc_title=r.doc_title,
                        paragraph_num=getattr(r, "paragraph_num", 0))
                    for r in reranked
                ]
            except Exception as e:
                print(f"  [{i}/{len(questions)}] {q['id']} 重排失败，用原结果: {e}")
                eval_results = results
        else:
            eval_results = results

        elapsed = time.time() - t0

        # 计算指标
        recall5 = compute_recall_at_k(eval_results, expected_kw, expected_t, 5)
        mrr = compute_mrr(eval_results, expected_kw, expected_t)
        ndcg5 = compute_ndcg_at_k(eval_results, expected_kw, expected_t, 5)
        hit = recall5 == 1

        if hit:
            hit_count += 1

        # 找到第一个命中的 rank
        rank = -1
        for idx, r in enumerate(eval_results, 1):
            if _is_hit(r, expected_kw, expected_t):
                rank = idx
                break

        results_detail.append({
            "id": q["id"],
            "question": query,
            "category": q.get("category", ""),
            "difficulty": q.get("difficulty", ""),
            "hit": hit,
            "rank": rank,
            "n_results": len(eval_results),
            "recall@5": recall5,
            "mrr": mrr,
            "ndcg@5": ndcg5,
            "elapsed_ms": round(elapsed * 1000, 1),
            "top1_title": eval_results[0].doc_title if eval_results else "",
        })

        status = "HIT " if hit else "MISS"
        rank_str = f"rank={rank}" if rank > 0 else "rank=-"
        print(f"  [{i}/{len(questions)}] {status} {q['id']} ({q.get('category','')}) {rank_str} {elapsed:.2f}s")

    # 汇总
    n = len(results_detail)
    if n == 0:
        return {"overall": {}, "by_category": {}, "details": []}

    overall = {
        "recall@5": round(sum(d.get("recall@5", 0) for d in results_detail) / n, 4),
        "mrr": round(sum(d.get("mrr", 0) for d in results_detail) / n, 4),
        "ndcg@5": round(sum(d.get("ndcg@5", 0) for d in results_detail) / n, 4),
        "hit_rate": round(hit_count / n, 4),
        "avg_latency_ms": round(sum(d.get("elapsed_ms", 0) for d in results_detail) / n, 1),
        "total": n,
    }

    # 按类别分组
    by_cat: Dict[str, dict] = {}
    for d in results_detail:
        cat = d.get("category", "unknown")
        if cat not in by_cat:
            by_cat[cat] = {"hits": 0, "total": 0, "mrr_sum": 0.0, "recall_sum": 0.0}
        by_cat[cat]["total"] += 1
        if d.get("hit"):
            by_cat[cat]["hits"] += 1
        by_cat[cat]["mrr_sum"] += d.get("mrr", 0)
        by_cat[cat]["recall_sum"] += d.get("recall@5", 0)
    for cat, s in by_cat.items():
        s["hit_rate"] = round(s["hits"] / s["total"], 4) if s["total"] > 0 else 0
        s["mrr"] = round(s["mrr_sum"] / s["total"], 4) if s["total"] > 0 else 0
        s["recall@5"] = round(s["recall_sum"] / s["total"], 4) if s["total"] > 0 else 0
        del s["hits"], s["total"], s["mrr_sum"], s["recall_sum"]

    return {"overall": overall, "by_category": by_cat, "details": results_detail}


# ============================================================
# 报告输出
# ============================================================

def print_report(result: dict, mode_label: str) -> None:
    """打印 Markdown 报告到 stdout。"""
    o = result["overall"]
    print("\n" + "=" * 80)
    print(f"# 检索评测报告 ({mode_label})")
    print("=" * 80)
    print(f"\n## 总体指标")
    print(f"- 问题数: {o.get('total', 0)}")
    print(f"- Recall@5: {o.get('recall@5', 0):.4f} ({o.get('recall@5', 0)*100:.1f}%)")
    print(f"- MRR:     {o.get('mrr', 0):.4f}")
    print(f"- NDCG@5:  {o.get('ndcg@5', 0):.4f}")
    print(f"- HitRate: {o.get('hit_rate', 0):.4f} ({o.get('hit_rate', 0)*100:.1f}%)")
    print(f"- 平均延迟: {o.get('avg_latency_ms', 0):.1f} ms")

    print(f"\n## 按类别")
    print(f"| 类别 | Recall@5 | MRR | HitRate |")
    print(f"|---|---|---|---|")
    for cat, s in sorted(result["by_category"].items()):
        print(f"| {cat} | {s['recall@5']:.4f} | {s['mrr']:.4f} | {s['hit_rate']:.4f} |")

    # 失败案例
    misses = [d for d in result["details"] if not d.get("hit")]
    if misses:
        print(f"\n## 失败案例 ({len(misses)} 个)")
        for d in misses[:10]:
            print(f"- [{d['id']}] {d['question']} (cat={d.get('category','')})")
            if d.get("top1_title"):
                print(f"  → top1: {d['top1_title']}")


def save_report(result: dict, output_path: Path, mode_label: str) -> None:
    """保存 JSON 报告。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"mode": mode_label, "result": result}
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\n报告已保存：{output_path}")


# ============================================================
# 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="检索质量评测")
    parser.add_argument("--dataset", default=str(PROJECT_ROOT / "tests/eval/golden_dataset.json"),
                        help="评测集路径")
    parser.add_argument("--top-k", type=int, default=6, help="检索候选数")
    parser.add_argument("--top-n", type=int, default=5, help="重排后返回数量")
    parser.add_argument("--no-rerank", action="store_true", help="不使用 reranker（baseline）")
    parser.add_argument("--reranker", choices=["cross_encoder", "llm", "none"], default=None,
                        help="指定 reranker 类型（覆盖配置）")
    parser.add_argument("--report", choices=["md", "json", "both"], default="md",
                        help="报告输出格式")
    parser.add_argument("--output", default=str(PROJECT_ROOT / "storage/eval_report.json"),
                        help="JSON 报告输出路径")
    args = parser.parse_args()

    # 加载评测集
    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        print(f"错误：评测集不存在 {dataset_path}")
        sys.exit(1)
    questions = load_dataset(dataset_path)
    print(f"加载评测集：{len(questions)} 个问题")

    # 临时覆盖 reranker 配置
    if args.reranker:
        os.environ["RERANKER_TYPE"] = args.reranker
        # 重新加载 settings
        import importlib
        import config
        importlib.reload(config)
        from config import settings as _s
        # 注意：settings 是模块级单例，需要替换
        import core.retrieval.rerank as _rr
        _rr.settings = _s

    # 初始化存储 + 检索器
    print("初始化存储与检索器...")
    storage = Storage()
    # 手动初始化向量索引
    from core.retrieval.vector import VectorIndex
    vector = VectorIndex()
    storage.attach_vector_index(vector)
    bm25 = storage.bm25

    retriever = HybridRetriever(
        bm25_index=bm25,
        vector_index=vector,
        storage=storage,
        enable_cache=False,  # 评测关闭缓存，确保结果稳定
    )

    # 重排序器
    reranker = None
    mode_label = "no-rerank"
    if not args.no_rerank:
        print("初始化重排序器...")
        reranker = create_reranker()
        if reranker is None:
            print("警告：reranker 不可用，退化为 no-rerank 模式")
            mode_label = "no-rerank"
        else:
            from core.retrieval.cross_encoder import CrossEncoderReranker
            from core.retrieval.rerank import Reranker as LLMReranker
            if isinstance(reranker, CrossEncoderReranker):
                mode_label = "cross-encoder"
            elif isinstance(reranker, LLMReranker):
                mode_label = "llm-rerank"
    else:
        mode_label = "no-rerank"

    # 跑评测
    result = evaluate(
        questions=questions,
        retriever=retriever,
        reranker=reranker,
        top_k=args.top_k,
        top_n=args.top_n,
    )

    # 输出报告
    print_report(result, mode_label)
    if args.report in ("json", "both"):
        save_report(result, Path(args.output), mode_label)


if __name__ == "__main__":
    main()
