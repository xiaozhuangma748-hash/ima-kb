"""数据分析器：读取表格 + 自动分析 + LLM 解读 + 终端字符图。

用法：
    from core.analyze.analyzer import DataAnalyzer
    az = DataAnalyzer()
    result = az.analyze("path/to/file.xlsx")
    # result 含字段：file_info / preview / describe / missing / correlations / insights
    az.render(result)             # 终端渲染（含字符图）
    az.ask(result, "按月份汇总")  # 追问
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from config import settings
from core.llm.client import get_llm, LLMError


console = Console()


# ============================================================
# 数据结构
# ============================================================

@dataclass
class AnalysisResult:
    """一次分析的结果汇总。"""
    file_path: str
    file_name: str
    file_type: str           # xlsx / csv / tsv / json
    sheet_name: Optional[str] = None  # Excel 时的 sheet
    rows: int = 0
    cols: int = 0
    columns: List[str] = field(default_factory=list)
    dtypes: Dict[str, str] = field(default_factory=dict)
    preview: List[Dict[str, Any]] = field(default_factory=list)  # 前 5 行
    describe: Dict[str, Any] = field(default_factory=dict)       # 数值列描述统计
    value_counts: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)  # 分类列 Top 值
    missing: Dict[str, int] = field(default_factory=dict)        # 每列缺失数
    correlations: List[Dict[str, Any]] = field(default_factory=list)  # 相关性 Top
    insights: str = ""        # LLM 生成的中文解读


# ============================================================
# 分析器
# ============================================================

class DataAnalyzer:
    """数据表智能分析器。"""

    SUPPORTED = {".xlsx", ".xls", ".csv", ".tsv", ".json"}

    def __init__(self) -> None:
        if not settings.has_llm():
            raise LLMError("LLM 未配置，数据分析需要 AGNES_API_KEY")
        self.llm = get_llm()

    # ---- 入口 ----

    def analyze(self, file_path: str | Path, sheet_name: Optional[str] = None) -> AnalysisResult:
        """读取文件并做全量分析。

        Args:
            file_path: 数据文件路径
            sheet_name: Excel 的 sheet 名（None 取第一个）
        """
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {path}")
        if path.suffix.lower() not in self.SUPPORTED:
            raise ValueError(f"不支持的格式: {path.suffix}（支持 {self.SUPPORTED}）")

        # 1. 读取
        df, sheet_used = self._read(path, sheet_name)

        # 2. 基础统计
        result = AnalysisResult(
            file_path=str(path),
            file_name=path.name,
            file_type=path.suffix.lower().lstrip("."),
            sheet_name=sheet_used,
            rows=len(df),
            cols=len(df.columns),
            columns=list(df.columns),
            dtypes={str(c): str(df[c].dtype) for c in df.columns},
        )

        # 3. 预览（前 5 行，转 dict，处理 numpy 类型）
        result.preview = self._safe_records(df.head(5))

        # 4. 描述统计（数值列）
        num_cols = df.select_dtypes(include="number").columns.tolist()
        if num_cols:
            desc = df[num_cols].describe().to_dict()
            # 转 JSON 安全类型
            result.describe = json.loads(json.dumps(desc, default=str))

        # 5. 分类列 Top 值（前 10）
        cat_cols = df.select_dtypes(include=["object", "category", "bool"]).columns.tolist()
        for c in cat_cols[:8]:  # 最多 8 列
            vc = df[c].value_counts().head(10)
            result.value_counts[str(c)] = [
                {"value": str(v), "count": int(n)}
                for v, n in vc.items()
            ]

        # 6. 缺失值
        result.missing = {str(c): int(df[c].isna().sum()) for c in df.columns}

        # 7. 相关性（数值列 ≥2 个时）
        if len(num_cols) >= 2:
            corr = df[num_cols].corr()
            pairs = []
            seen = set()
            for i, c1 in enumerate(num_cols):
                for j, c2 in enumerate(num_cols):
                    if i >= j:
                        continue
                    key = (c1, c2)
                    if key in seen:
                        continue
                    seen.add(key)
                    val = float(corr.loc[c1, c2])
                    if pd.isna(val):
                        continue
                    pairs.append({"col1": str(c1), "col2": str(c2), "corr": round(val, 3)})
            pairs.sort(key=lambda x: abs(x["corr"]), reverse=True)
            result.correlations = pairs[:10]

        # 8. LLM 解读
        result.insights = self._generate_insights(result)

        return result

    # ---- 读取 ----

    def _read(self, path: Path, sheet_name: Optional[str]) -> tuple[pd.DataFrame, Optional[str]]:
        """读取文件，返回 (df, sheet_used)。"""
        ext = path.suffix.lower()
        if ext == ".csv":
            # 自动尝试 utf-8 / gbk
            for enc in ("utf-8", "gbk", "gb2312", "latin-1"):
                try:
                    return pd.read_csv(path, encoding=enc), None
                except UnicodeDecodeError:
                    continue
            return pd.read_csv(path), None
        if ext == ".tsv":
            return pd.read_csv(path, sep="\t"), None
        if ext == ".json":
            return pd.read_json(path), None
        if ext in (".xlsx", ".xls"):
            if sheet_name:
                return pd.read_excel(path, sheet_name=sheet_name), sheet_name
            # 默认读第一个 sheet
            xl = pd.ExcelFile(path)
            first = xl.sheet_names[0]
            return pd.read_excel(path, sheet_name=first), first
        raise ValueError(f"不支持的格式: {ext}")

    def list_sheets(self, file_path: str | Path) -> List[str]:
        """列出 Excel 的所有 sheet 名。"""
        path = Path(file_path).expanduser().resolve()
        if path.suffix.lower() not in (".xlsx", ".xls"):
            return []
        return list(pd.ExcelFile(path).sheet_names)

    # ---- LLM 解读 ----

    def _generate_insights(self, result: AnalysisResult) -> str:
        """调 LLM 生成中文解读。"""
        # 构造 prompt（精简，避免超 token）
        payload = {
            "file": result.file_name,
            "type": result.file_type,
            "rows": result.rows,
            "cols": result.cols,
            "columns": result.columns[:20],
            "dtypes": {k: v for k, v in list(result.dtypes.items())[:20]},
            "describe": result.describe,
            "missing_top": dict(sorted(result.missing.items(), key=lambda x: -x[1])[:5]),
            "value_counts_top": {
                k: v[:3] for k, v in list(result.value_counts.items())[:5]
            },
            "correlations_top": result.correlations[:5],
        }

        prompt = f"""请基于以下数据表分析结果，用中文给出**简洁**的数据洞察（300 字以内）：

1. **数据概览**：行列数、字段类型分布
2. **关键发现**：异常值、强相关性、分布偏斜、缺失严重的列
3. **业务建议**：基于数据特征给出 2-3 条分析建议

数据 JSON：
```json
{json.dumps(payload, ensure_ascii=False, indent=2)}
```

请直接输出洞察，不要重复 JSON 内容。"""

        messages = [
            {"role": "system", "content": "你是数据分析师，擅长从表格统计结果中提炼有价值的业务洞察。"},
            {"role": "user", "content": prompt},
        ]
        try:
            return self.llm.chat(messages, temperature=0.3, max_tokens=600)
        except Exception as e:
            return f"（LLM 解读失败: {type(e).__name__}: {e}）"

    # ---- 追问 ----

    def ask(self, result: AnalysisResult, question: str) -> str:
        """基于已分析的结果追问。

        Args:
            result: 之前 analyze() 的结果
            question: 用户的追问，如 "按月份汇总"、"哪个区数据最多"
        """
        # 重新读文件取原始数据（因为追问可能需要原文）
        path = Path(result.file_path)
        if not path.exists():
            return "❌ 原始文件已不存在，无法追问"

        try:
            df, _ = self._read(path, result.sheet_name)
        except Exception as e:
            return f"❌ 重新读取文件失败: {e}"

        # 先尝试用 pandas 直接回答（常见问法）
        direct = self._try_direct_answer(df, question)
        if direct:
            return direct

        # 否则给 LLM 完整上下文
        preview_str = df.head(20).to_string()
        stats_str = df.describe(include="all").to_string() if len(df) > 0 else ""

        prompt = f"""用户对数据表「{result.file_name}」提问。

数据预览（前 20 行）：
{preview_str}

描述统计：
{stats_str}

字段类型：{result.dtypes}

用户问题：{question}

请用中文回答。如果需要可以建议用户用 /analyze 重新分析或指定更具体的字段。
回答要简洁实用，包含具体数字。"""

        messages = [
            {"role": "system", "content": "你是数据分析师助手，基于表格数据回答用户问题。"},
            {"role": "user", "content": prompt},
        ]
        return self.llm.chat(messages, temperature=0.3, max_tokens=600)

    def _try_direct_answer(self, df: pd.DataFrame, question: str) -> Optional[str]:
        """尝试用 pandas 直接回答常见问法（省 LLM 调用）。"""
        q = question.lower()

        # 行列数
        if any(k in q for k in ["多少行", "几行", "多少条", "多少数据", "多少记录"]):
            return f"数据共 {len(df)} 行 × {len(df.columns)} 列"

        # 列名
        if any(k in q for k in ["哪些列", "字段", "列名"]):
            return "字段列表：\n" + "\n".join(f"  · {c} ({df[c].dtype})" for c in df.columns)

        # 缺失值
        if "缺失" in q or "空值" in q:
            miss = df.isna().sum()
            miss = miss[miss > 0].sort_values(ascending=False)
            if len(miss) == 0:
                return "✓ 无缺失值"
            lines = [f"  · {c}: {n} 个缺失" for c, n in miss.items()]
            return "缺失值统计：\n" + "\n".join(lines)

        return None

    # ---- 终端渲染 ----

    def render(self, result: AnalysisResult) -> None:
        """把分析结果渲染到终端。"""
        # 1. 文件信息
        info_table = Table(show_header=False, show_lines=False, border_style="cyan")
        info_table.add_column("key", style="dim", width=12)
        info_table.add_column("value", style="white")
        info_table.add_row("文件", f"[cyan]{result.file_name}[/cyan]")
        if result.sheet_name:
            info_table.add_row("Sheet", result.sheet_name)
        info_table.add_row("格式", result.file_type)
        info_table.add_row("规模", f"[yellow]{result.rows}[/yellow] 行 × [yellow]{result.cols}[/yellow] 列")
        info_table.add_row("字段", ", ".join(result.columns[:8]) + (" ..." if len(result.columns) > 8 else ""))
        console.print(Panel(info_table, title="[bold cyan]📁 文件信息[/bold cyan]", border_style="cyan", padding=(1, 2)))

        # 2. 数据预览
        if result.preview:
            preview_table = Table(title="数据预览（前 5 行）", show_lines=False, border_style="blue")
            for col in result.columns:
                preview_table.add_column(str(col), overflow="fold", max_width=20)
            for row in result.preview:
                preview_table.add_row(*[str(row.get(c, ""))[:30] for c in result.columns])
            console.print(preview_table)

        # 3. 字段类型
        type_groups: Dict[str, List[str]] = {}
        for col, dt in result.dtypes.items():
            type_groups.setdefault(dt, []).append(col)
        type_table = Table(title="字段类型", show_lines=False, border_style="magenta")
        type_table.add_column("类型", style="magenta", width=12)
        type_table.add_column("字段", style="white")
        type_table.add_column("数量", justify="right", style="yellow")
        for dt, cols in type_groups.items():
            type_table.add_row(dt, ", ".join(cols[:6]) + (" ..." if len(cols) > 6 else ""), str(len(cols)))
        console.print(type_table)

        # 4. 描述统计（数值列）
        if result.describe:
            desc_table = Table(title="描述统计（数值列）", show_lines=False, border_style="green")
            desc_table.add_column("指标", style="green", width=10)
            for col in result.describe.keys():
                desc_table.add_column(str(col)[:15], justify="right", overflow="fold")
            for stat in ["count", "mean", "std", "min", "25%", "50%", "75%", "max"]:
                if stat in result.describe.get(next(iter(result.describe)), {}):
                    row = [stat]
                    for col in result.describe.keys():
                        val = result.describe[col].get(stat, "")
                        if isinstance(val, float):
                            row.append(f"{val:.2f}")
                        else:
                            row.append(str(val))
                    desc_table.add_row(*row)
            console.print(desc_table)

            # 5. 数值列分布字符图
            self._render_distribution(result)

        # 6. 分类列 Top 值
        if result.value_counts:
            for col, items in list(result.value_counts.items())[:3]:
                vc_table = Table(title=f"「{col}」值分布 Top {len(items)}", show_lines=False, border_style="yellow")
                vc_table.add_column("值", style="white", overflow="fold")
                vc_table.add_column("数量", justify="right", style="cyan")
                vc_table.add_column("占比", justify="right", style="magenta")
                total = sum(it["count"] for it in items) or 1
                for it in items:
                    pct = it["count"] / total * 100
                    vc_table.add_row(it["value"][:40], str(it["count"]), f"{pct:.1f}%")
                console.print(vc_table)

                # 字符柱状图
                self._render_bar_chart(items, col)

        # 7. 相关性
        if result.correlations:
            corr_table = Table(title="相关性 Top 10", show_lines=False, border_style="red")
            corr_table.add_column("字段 1", style="white")
            corr_table.add_column("字段 2", style="white")
            corr_table.add_column("相关系数", justify="right", style="yellow")
            corr_table.add_column("强度", style="magenta")
            for c in result.correlations:
                v = c["corr"]
                strength = "强" if abs(v) >= 0.7 else "中" if abs(v) >= 0.4 else "弱"
                color = "red" if v > 0 else "blue"
                corr_table.add_row(c["col1"], c["col2"], f"[{color}]{v}[/{color}]", strength)
            console.print(corr_table)

        # 8. 缺失值
        if any(v > 0 for v in result.missing.values()):
            miss_sorted = sorted([(k, v) for k, v in result.missing.items() if v > 0], key=lambda x: -x[1])
            miss_table = Table(title="缺失值统计", show_lines=False, border_style="yellow")
            miss_table.add_column("字段", style="white")
            miss_table.add_column("缺失数", justify="right", style="yellow")
            miss_table.add_column("缺失率", justify="right", style="red")
            for col, n in miss_sorted:
                rate = n / result.rows * 100 if result.rows else 0
                miss_table.add_row(col, str(n), f"{rate:.1f}%")
            console.print(miss_table)

        # 9. LLM 洞察
        if result.insights:
            console.print(Panel(
                Text(result.insights),
                title="[bold green]💡 AI 数据洞察[/bold green]",
                border_style="green",
                padding=(1, 2),
            ))

    # ---- 字符图 ----

    def _render_bar_chart(self, items: List[Dict[str, Any]], col: str) -> None:
        """用 Unicode 块字符画水平柱状图。"""
        if not items:
            return
        max_count = max(it["count"] for it in items)
        max_bar = 30  # 最大柱长
        console.print(f"  [dim]{col} 分布：[/dim]")
        for it in items:
            count = it["count"]
            bar_len = int(count / max_count * max_bar) if max_count else 0
            bar = "█" * bar_len
            label = it["value"][:15].ljust(15)
            console.print(f"  [cyan]{label}[/cyan] [green]{bar}[/green] [yellow]{count}[/yellow]")
        console.print()

    def _render_distribution(self, result: AnalysisResult) -> None:
        """数值列分布直方图（基于 describe 的 min/max/分位数粗略画）。"""
        if not result.describe:
            return
        console.print(f"  [dim]数值列分布概览（基于分位数）：[/dim]")
        for col, stats in result.describe.items():
            if not isinstance(stats, dict):
                continue
            q25 = stats.get("25%", 0)
            q50 = stats.get("50%", 0)
            q75 = stats.get("75%", 0)
            mn = stats.get("min", 0)
            mx = stats.get("max", 0)
            mean = stats.get("mean", 0)
            if not all(isinstance(x, (int, float)) for x in [mn, q25, q50, q75, mx]):
                continue
            # 5 段箱线图：min - 25% - 50% - 75% - max
            span = (mx - mn) or 1
            def pos(v):
                return int((v - mn) / span * 30)
            line = ["─"] * 31
            for i in range(31):
                line[i] = "·"
            # 填充 25%-75% 区间
            for i in range(pos(q25), pos(q75) + 1):
                if 0 <= i < 31:
                    line[i] = "█"
            # 标记分位数
            for i in [pos(mn), pos(q25), pos(q50), pos(q75), pos(mx)]:
                if 0 <= i < 31:
                    line[i] = "■"
            mean_pos = pos(mean)
            if 0 <= mean_pos < 31:
                line[mean_pos] = "▲"
            bar = "".join(line)
            console.print(f"  [cyan]{str(col)[:15]:15s}[/cyan] [{mn:.1f}] {bar} [{mx:.1f}]  μ={mean:.1f}")
        console.print()

    # ---- 工具 ----

    @staticmethod
    def _safe_records(df: pd.DataFrame) -> List[Dict[str, Any]]:
        """转 DataFrame 为 JSON 安全的 records（处理 numpy 类型 + NaN）。"""
        records = df.fillna("").to_dict(orient="records")
        return json.loads(json.dumps(records, default=str))
