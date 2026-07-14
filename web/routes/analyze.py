"""数据分析 — Excel 上传 + 统计 + AI 解读。

POST /api/analyze  上传文件分析
GET  /api/analyze/export  下载分析报告
"""
from __future__ import annotations

import tempfile
import time
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, Query, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from config import settings

router = APIRouter(tags=["analyze"])


# 内存缓存分析结果（带 TTL，避免长期运行内存泄漏）
# maxsize=50, ttl=3600s（1小时后自动过期）
_analysis_cache: dict = {}
_analysis_cache_ts: dict = {}  # key → 创建时间戳
_CACHE_TTL = 3600  # 1 小时
_CACHE_MAXSIZE = 50


def _cache_put(key: str, value: dict) -> None:
    """写入缓存，超过 maxsize 时清理最老的条目。"""
    _analysis_cache[key] = value
    _analysis_cache_ts[key] = time.time()
    # 超容量时清理最老的
    if len(_analysis_cache) > _CACHE_MAXSIZE:
        oldest_key = min(_analysis_cache_ts, key=_analysis_cache_ts.get)
        _analysis_cache.pop(oldest_key, None)
        _analysis_cache_ts.pop(oldest_key, None)


def _cache_get(key: str) -> dict | None:
    """读取缓存，过期返回 None 并清理。"""
    if key not in _analysis_cache:
        return None
    if time.time() - _analysis_cache_ts.get(key, 0) > _CACHE_TTL:
        _analysis_cache.pop(key, None)
        _analysis_cache_ts.pop(key, None)
        return None
    return _analysis_cache[key]


@router.post("/analyze")
async def analyze(
    file: UploadFile = File(...),
    sheet: str = Query(None, description="Excel sheet 名称"),
    ai_insight: bool = Query(False, description="是否调用 AI 解读"),
):
    """上传数据文件进行分析。"""
    from core.llm.client import LLMError

    suffix = Path(file.filename or "data.xlsx").suffix
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        from core.analyze.analyzer import DataAnalyzer

        az = DataAnalyzer()
        sheets = az.list_sheets(tmp_path)

        if sheet and sheet not in sheets:
            sheet = None

        result = az.analyze(tmp_path, sheet_name=sheet)

        # 构建响应（基于 AnalysisResult dataclass）
        columns = [
            {
                "name": col,
                "dtype": result.dtypes.get(col, "unknown"),
                "null_count": result.missing.get(col, 0),
                "top_values": (result.value_counts.get(col, [])[:5]
                               if col in result.value_counts else []),
            }
            for col in result.columns
        ]

        # 数值列的统计信息
        for col_info in columns:
            col = col_info["name"]
            if col in result.describe:
                desc = result.describe[col]
                if isinstance(desc, dict):
                    col_info["min"] = desc.get("min")
                    col_info["max"] = desc.get("max")
                    col_info["mean"] = desc.get("mean")

        preview_rows = result.preview or []

        response_data = {
            "filename": file.filename,
            "sheets": sheets,
            "current_sheet": sheet or (sheets[0] if sheets else ""),
            "rows": result.rows,
            "cols": result.cols,
            "columns": columns,
            "preview_rows": preview_rows,
            "summary": result.insights or "",
        }

        # 缓存用于导出（带 TTL）
        import uuid
        cache_key = str(uuid.uuid4())[:8]
        _cache_put(cache_key, response_data)

        # AI 解读（基于已有的统计摘要再生成一段趋势洞察）
        if ai_insight and settings.has_llm():
            try:
                from core.llm.client import get_llm

                llm = get_llm()
                insight_resp = llm.chat(
                    messages=[{
                        "role": "user",
                        "content": f"你是一个数据分析师。请根据以下数据统计结果，用中文生成一段简洁的趋势解读（200字以内）:\n{result.insights}",
                    }],
                    max_tokens=300,
                )
                response_data["ai_insight"] = insight_resp if isinstance(insight_resp, str) else insight_resp.get("content", "")
            except Exception as e:
                response_data["ai_insight"] = f"（AI 解读暂时不可用: {type(e).__name__}）"

        response_data["cache_key"] = cache_key
        return response_data

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"分析失败: {e}")

    finally:
        try:
            tmp_path.unlink()
        except Exception:
            pass


@router.get("/analyze/export")
async def analyze_export(key: str = Query(..., description="缓存 key")):
    """导出分析报告为 Markdown 下载。"""
    data = _cache_get(key)
    if data is None:
        raise HTTPException(status_code=404, detail="分析结果已过期，请重新分析")
    md = f"# {data['filename']} · 数据分析报告\n\n"
    md += f"## Sheet: {data['current_sheet']}\n\n"

    if data.get("summary"):
        md += f"### 数据摘要\n\n{data['summary']}\n\n"
    if data.get("ai_insight"):
        md += f"### AI 解读\n\n{data['ai_insight']}\n\n"
    if data.get("columns"):
        md += "### 字段统计\n\n"
        for col in data["columns"]:
            md += f"- **{col['name']}** ({col['dtype']})\n"
            for k, v in col.items():
                if k not in ("name", "dtype"):
                    md += f"  - {k}: {v}\n"
            md += "\n"

    # 写入临时文件
    out_path = Path(settings.storage_path) / "reports" / f"analysis_{key}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")

    return FileResponse(
        out_path,
        media_type="text/markdown",
        filename=f"分析报告_{data['filename']}.md",
    )
