"""数据分析 — Excel 上传 + 统计 + AI 解读。

POST /api/analyze  上传文件分析
GET  /api/analyze/export  下载分析报告
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, Query, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from config import settings

router = APIRouter(tags=["analyze"])


# 内存缓存分析结果（简单实现，生产环境用 Redis）
_analysis_cache: dict = {}


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

        # 缓存用于导出
        import uuid
        cache_key = str(uuid.uuid4())[:8]
        _analysis_cache[cache_key] = response_data

        # AI 解读
        if ai_insight and settings.has_llm() and result.summary:
            try:
                llm = None
                from core.llm.client import get_llm
                llm = get_llm()
                insight_resp = llm.chat(
                    messages=[{
                        "role": "user",
                        "content": f"你是一个数据分析师。请根据以下数据统计结果，用中文生成一段简洁的趋势解读（200字以内）:\n{result.summary}",
                    }],
                    max_tokens=300,
                )
                response_data["ai_insight"] = insight_resp.get("content", "")
            except Exception:
                response_data["ai_insight"] = "（AI 解读暂时不可用）"

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
    if key not in _analysis_cache:
        raise HTTPException(status_code=404, detail="分析结果已过期，请重新分析")

    data = _analysis_cache[key]
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
