"""内置工具集：从 ``agent.py`` 迁移的 6 个工具。

每个工具用 ``@register_tool`` 装饰，自动注册到全局 Registry。
文案与逻辑与原 ``_tool_*`` 方法逐字一致；依赖通过 ``ToolContext`` 注入。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Type

from pydantic import BaseModel

from .base import Tool, ToolContext, register_tool


__all__ = [
    "SearchArgs",
    "SearchTool",
    "ListDocsArgs",
    "ListDocsTool",
    "GetDocArgs",
    "GetDocTool",
    "AnalyzeArgs",
    "AnalyzeTool",
    "ReadArgs",
    "ReadTool",
    "ReadMultiArgs",
    "ReadMultiTool",
    "PetInteractArgs",
    "PetInteractTool",
    "PetStatusTool",
    "PetManageArgs",
    "PetManageTool",
    "PetShopArgs",
    "PetShopTool",
]


# ============================================================
# SmartReader 缓存辅助：连续读同一文档时复用 reader 实例
# ============================================================

def _open_reader(context: Optional[ToolContext], doc_id: str):
    """打开 SmartReader，命中缓存时复用实例。

    缓存策略：以 doc_id 前 8 位为 key（与 get_doc 的前缀匹配一致），
    最多缓存 4 个文档的 reader，超过时按 FIFO 淘汰最旧的。

    Returns:
        (smart_reader, state) — state 为 sr.open() 返回的阅读状态
    """
    from core.reader.reader import SmartReader

    cache = getattr(context, "_reader_cache", None) or {}
    cache_max = getattr(context, "_reader_cache_max", 4)
    key = doc_id[:8]  # 与 get_doc 的前缀匹配一致

    # 命中缓存
    if key in cache:
        sr, _opened = cache[key]
        try:
            state = sr.open(doc_id)
            return sr, state
        except Exception:
            # 缓存失效，删除后重新构造
            cache.pop(key, None)

    # 构造新 reader
    sr = SmartReader(storage=context.storage)
    state = sr.open(doc_id)

    # 写入缓存（FIFO 淘汰）
    if len(cache) >= cache_max and cache:
        # 删除最早插入的 key（dict 保持插入顺序）
        oldest = next(iter(cache))
        cache.pop(oldest, None)
    cache[key] = (sr, doc_id)
    context._reader_cache = cache

    return sr, state


# ============================================================
# 1. search — BM25 搜索知识库
# ============================================================

class SearchArgs(BaseModel):
    query: str


@register_tool
@dataclass
class SearchTool(Tool):
    name: str = "search"
    description: str = "搜索知识库（BM25+向量+RRF+Cross-Encoder，按关键词找内容）"
    args_schema: Optional[Type[BaseModel]] = SearchArgs
    prompt_block: str = (
        'search — 搜索知识库（BM25+向量+RRF+Cross-Encoder，按关键词找内容）\n'
        '   {"tool": "search", "args": "搜索关键词"}\n'
        '   返回结果含 doc_id 和 chunk_num，可直接用 read 精读对应段落'
    )

    def _parse_args_str(self, args_str: str) -> Tuple[Dict[str, Any], Optional[str]]:
        query = args_str.strip()
        if not query:
            return {}, "[错误] 搜索关键词不能为空"
        return {"query": query}, None

    def execute(self, context: Optional[ToolContext] = None, *, query: str, **_: Any) -> str:
        # 优先用 HybridRetriever（P0-P5 工业级 RAG 流水线）
        hybrid = getattr(context, "hybrid_retriever", None) if context else None
        if hybrid is not None:
            results = hybrid.search(query, top_k=5)
        else:
            # 降级：纯 BM25
            results = context.storage.bm25_search(query, top_k=5)

        if not results:
            return "[无结果] 未找到相关内容"

        lines = [f"找到 {len(results)} 条结果：\n"]
        for i, r in enumerate(results, 1):
            doc_id = getattr(r, "doc_id", "") or ""
            doc_id_short = doc_id[:8] if doc_id else "?"
            chunk_num = getattr(r, "paragraph_num", 0) or 0
            loc = f"doc={doc_id_short}"
            if chunk_num:
                loc += f" 段={chunk_num}"
            lines.append(f"[{i}] {r.doc_title} (相关度 {r.score:.2f} | {loc})")
            lines.append(f"    {r.content[:200]}...")
        return "\n".join(lines)


# ============================================================
# 2. list_docs — 列出所有已入库文档
# ============================================================

class ListDocsArgs(BaseModel):
    tag: Optional[str] = None
    page: int = 1


@register_tool
@dataclass
class ListDocsTool(Tool):
    name: str = "list_docs"
    description: str = "列出已入库文档（可选 tag 筛选，默认前 30 条）"
    args_schema: Optional[Type[BaseModel]] = ListDocsArgs
    prompt_block: str = (
        'list_docs — 列出已入库文档（可选 tag 筛选，默认前 30 条）\n'
        '   {"tool": "list_docs", "args": ""}             # 全部前 30 条\n'
        '   {"tool": "list_docs", "args": "海葬"}          # 按 tag 筛选\n'
        '   {"tool": "list_docs", "args": "海葬 page=2"}   # tag + 翻页'
    )

    def _parse_args_str(self, args_str: str) -> Tuple[Dict[str, Any], Optional[str]]:
        args = args_str.strip()
        if not args:
            return {}, None
        # 支持 "tag" 或 "tag page=2" 两种格式
        parts = args.split()
        tag = parts[0] if parts else None
        page = 1
        for p in parts[1:]:
            if p.startswith("page="):
                try:
                    page = int(p[5:])
                    if page < 1:
                        page = 1
                except ValueError:
                    pass
        return {"tag": tag, "page": page}, None

    def execute(
        self,
        context: Optional[ToolContext] = None,
        *,
        tag: Optional[str] = None,
        page: int = 1,
        **_: Any,
    ) -> str:
        docs = context.storage.list_documents()
        if not docs:
            return "[空] 知识库中没有文档"

        # tag 筛选（任一 tag 命中即保留）
        if tag:
            filtered = []
            for d in docs:
                if any(tag.lower() in (t or "").lower() for t in (d.tags or [])):
                    filtered.append(d)
            docs = filtered
            if not docs:
                return f"[空] 没有带 tag '{tag}' 的文档"

        total = len(docs)
        page_size = 30
        pages = (total + page_size - 1) // page_size
        if page > pages:
            page = pages if pages > 0 else 1
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        page_docs = docs[start_idx:end_idx]

        header = f"共 {total} 篇文档"
        if tag:
            header += f"（tag='{tag}'）"
        if pages > 1:
            header += f"，第 {page}/{pages} 页"
        lines = [header + "：\n"]
        for d in page_docs:
            lines.append(
                f"  {d.id[:8]}  {d.title}  "
                f"[{d.chunk_count}段] [{','.join(d.tags[:3])}]"
            )
        if pages > 1 and page < pages:
            lines.append(f"\n（还有更多，用 list_docs {'tag' if tag else ''} page={page+1} 翻页）")
        return "\n".join(lines)


# ============================================================
# 3. get_doc — 查看文档详情和前 3 段预览
# ============================================================

class GetDocArgs(BaseModel):
    doc_id: str


@register_tool
@dataclass
class GetDocTool(Tool):
    name: str = "get_doc"
    description: str = "查看文档详情和前 3 段预览"
    args_schema: Optional[Type[BaseModel]] = GetDocArgs
    prompt_block: str = (
        'get_doc — 查看文档详情和前 3 段预览\n'
        '   {"tool": "get_doc", "args": "文档ID前8位"}'
    )

    def _parse_args_str(self, args_str: str) -> Tuple[Dict[str, Any], Optional[str]]:
        args = args_str.strip()
        if not args:
            return {}, "[错误] 请指定文档ID"
        # 不截断，交给 storage.get_document 做前缀匹配（支持 8 位或完整 UUID）
        return {"doc_id": args}, None

    def execute(self, context: Optional[ToolContext] = None, *, doc_id: str, **_: Any) -> str:
        doc = context.storage.get_document(doc_id)
        if not doc:
            return f"[错误] 文档不存在: {doc_id}"

        # 获取前 3 段预览（保留原调用；注意：原代码即如此调用）
        chunks = context.storage.get_chunks_by_doc(doc_id, limit=3)
        preview = "\n".join(
            f"  第{i+1}段：{c.content[:200]}..."
            for i, c in enumerate(chunks)
        )

        return (
            f"文档: {doc.title}\n"
            f"ID: {doc.id}\n"
            f"标签: {', '.join(doc.tags)}\n"
            f"总段落: {doc.chunk_count}\n"
            f"总字数: {doc.total_tokens}\n\n"
            f"前 3 段预览：\n{preview}"
        )


# ============================================================
# 4. read — 读取文档指定段落的原文（1000 字）
# ============================================================

class ReadArgs(BaseModel):
    doc_id: str
    chunk_num: int = 1


@register_tool
@dataclass
class ReadTool(Tool):
    name: str = "read"
    description: str = "读取文档指定段落的原文（1000 字）"
    args_schema: Optional[Type[BaseModel]] = ReadArgs
    prompt_block: str = (
        'read — 读取文档指定段落的原文（1000 字）\n'
        '   {"tool": "read", "args": "文档ID前8位 段落号"}\n'
        '   段落号从 1 开始，如 "862e0973 3" 读第 3 段'
    )

    def _parse_args_str(self, args_str: str) -> Tuple[Dict[str, Any], Optional[str]]:
        args = args_str.strip()
        if not args:
            return {}, "[错误] 请指定文档ID，格式: 文档ID 段落号"

        parts = args.split(None, 1)
        doc_id = parts[0].strip()
        chunk_num = 1
        if len(parts) > 1:
            try:
                chunk_num = int(parts[1].strip())
                if chunk_num < 1:
                    chunk_num = 1
            except ValueError:
                return {}, f"[错误] 段落号必须是数字: {parts[1]}"
        return {"doc_id": doc_id, "chunk_num": chunk_num}, None

    def execute(
        self,
        context: Optional[ToolContext] = None,
        *,
        doc_id: str,
        chunk_num: int = 1,
        **_: Any,
    ) -> str:
        try:
            sr, state = _open_reader(context, doc_id)
            total = state.total_chunks
            if chunk_num > total:
                return f"[错误] 该文档共 {total} 段，你请求第 {chunk_num} 段（超出范围）"
            sr.goto(chunk_num - 1)
            chunk = sr.current_chunk()
            return (
                f"文档: {state.doc_title} (共 {total} 段)\n\n"
                f"第 {chunk_num} 段内容：\n{chunk.content[:1000]}"
            )
        except Exception as e:
            return f"阅读失败: {e}"


# ============================================================
# 5. read_multi — 一次读取多段（高效）
# ============================================================

class ReadMultiArgs(BaseModel):
    doc_id: str
    start: int
    end: int


@register_tool
@dataclass
class ReadMultiTool(Tool):
    name: str = "read_multi"
    description: str = "一次读取多段（高效！比逐段 read 省步数）"
    args_schema: Optional[Type[BaseModel]] = ReadMultiArgs
    prompt_block: str = (
        'read_multi — 一次读取多段（高效！比逐段 read 省步数）\n'
        '   {"tool": "read_multi", "args": "文档ID前8位 起始段-结束段"}\n'
        '   如 "862e0973 1-5" 读第 1 到 5 段'
    )

    def _parse_args_str(self, args_str: str) -> Tuple[Dict[str, Any], Optional[str]]:
        args = args_str.strip()
        if not args:
            return {}, "[错误] 格式: 文档ID 起始段-结束段，如 862e0973 1-5"

        parts = args.split(None, 1)
        if len(parts) < 2:
            return {}, "[错误] 请指定段落范围，如 862e0973 1-5"
        doc_id = parts[0].strip()
        range_str = parts[1].strip()

        range_match = re.match(r"^(\d+)\s*[-~]\s*(\d+)$", range_str)
        if not range_match:
            return {}, f"[错误] 段落范围格式错误: {range_str}，应为 起始-结束，如 1-5"

        start = int(range_match.group(1))
        end = int(range_match.group(2))
        if start < 1:
            start = 1
        if end < start:
            return {}, f"[错误] 结束段 {end} 小于起始段 {start}"
        return {"doc_id": doc_id, "start": start, "end": end}, None

    def execute(
        self,
        context: Optional[ToolContext] = None,
        *,
        doc_id: str,
        start: int,
        end: int,
        **_: Any,
    ) -> str:
        try:
            sr, state = _open_reader(context, doc_id)
            total = state.total_chunks
            if start > total:
                return f"[错误] 起始段 {start} 超出范围（共 {total} 段）"
            if end > total:
                end = total
            if end - start + 1 > 8:
                end = start + 7

            lines = [f"文档: {state.doc_title} (共 {total} 段，读取 {start}-{end} 段)\n"]
            for i in range(start, end + 1):
                sr.goto(i - 1)
                chunk = sr.current_chunk()
                lines.append(f"--- 第 {i} 段 ---\n{chunk.content[:1000]}\n")
            return "\n".join(lines)
        except Exception as e:
            return f"阅读失败: {e}"


# ============================================================
# 6. analyze — 数据表分析（Excel/CSV/JSON）
# ============================================================

class AnalyzeArgs(BaseModel):
    file_path: str


@register_tool
@dataclass
class AnalyzeTool(Tool):
    name: str = "analyze"
    description: str = "数据表分析（Excel/CSV/JSON）"
    args_schema: Optional[Type[BaseModel]] = AnalyzeArgs
    prompt_block: str = (
        'analyze — 数据表分析（Excel/CSV/JSON）\n'
        '   {"tool": "analyze", "args": "文件路径"}'
    )

    def _parse_args_str(self, args_str: str) -> Tuple[Dict[str, Any], Optional[str]]:
        # 原实现只 strip，不检查空值
        return {"file_path": args_str.strip()}, None

    def execute(self, context: Optional[ToolContext] = None, *, file_path: str, **_: Any) -> str:
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            return f"文件不存在: {path}"

        try:
            from core.analyze.analyzer import DataAnalyzer

            az = DataAnalyzer()
            result = az.analyze(path)
            return (
                f"文件: {result.file_name}\n"
                f"规模: {result.rows} 行 × {result.cols} 列\n"
                f"字段: {', '.join(result.columns[:8])}\n"
                f"数值列描述: {list(result.describe.keys())}\n"
                f"缺失值: {sum(1 for v in result.missing.values() if v > 0)} 列有缺失\n"
                f"\nAI 洞察：\n{result.insights}"
            )
        except Exception as e:
            return f"分析失败: {e}"


# ============================================================
# 7. pet_interact — 与虚拟宠物互动（喂食/玩耍/训练/洗澡/睡觉）
# ============================================================

class PetInteractArgs(BaseModel):
    action: str


@register_tool
@dataclass
class PetInteractTool(Tool):
    """与虚拟宠物互动，真正更新宠物状态（饱食/心情/能量/清洁）。

    依赖 ToolContext 中的 pet / pet_interactor / pet_storage（由 REPL 注入）。
    未注入时返回未启用提示，Agent 不会"嘴上喂"。
    """
    name: str = "pet_interact"
    description: str = "与虚拟宠物互动（喂食/玩耍/训练/洗澡/睡觉/恢复能量），真正更新宠物状态"
    args_schema: Optional[Type[BaseModel]] = PetInteractArgs
    prompt_block: str = (
        'pet_interact — 与虚拟宠物互动（喂食/玩耍/训练/洗澡/睡觉/恢复能量）\n'
        '   {"tool": "pet_interact", "args": "feed"}             # 喂食：+30 饱食\n'
        '   {"tool": "pet_interact", "args": "play"}             # 玩耍：+40 心情\n'
        '   {"tool": "pet_interact", "args": "train"}            # 训练：+50 经验\n'
        '   {"tool": "pet_interact", "args": "wash"}             # 洗澡：+50 清洁\n'
        '   {"tool": "pet_interact", "args": "sleep"}            # 睡觉：+50 能量（1h 冷却）\n'
        '   {"tool": "pet_interact", "args": "restore_energy"}   # 智能恢复能量（优先道具，否则 sleep）\n'
        '   当用户要求"喂宠物/给宠物食物/陪宠物玩/清洁宠物/加能量"等时使用此工具'
    )

    _VALID_ACTIONS = ("feed", "play", "train", "wash", "sleep", "restore_energy")

    def _parse_args_str(self, args_str: str) -> Tuple[Dict[str, Any], Optional[str]]:
        action = args_str.strip().lower()
        if not action:
            return {}, "[错误] 请指定动作: feed/play/train/wash/sleep/restore_energy"
        if action not in self._VALID_ACTIONS:
            return {}, f"[错误] 未知动作: {action}，可选: {', '.join(self._VALID_ACTIONS)}"
        return {"action": action}, None

    def execute(self, context: Optional[ToolContext] = None, *, action: str, **_: Any) -> str:
        # 依赖检查：未注入 pet 时返回明确提示，避免 LLM 误以为已执行
        if context is None or context.pet is None or context.pet_interactor is None:
            return "[未启用] 当前会话未加载宠物，无法互动。请用 /pet adopt 领养后再试。"
        pet = context.pet
        interactor = context.pet_interactor
        try:
            # restore_energy 走智能路由：优先道具，否则 sleep
            if action == "restore_energy":
                return self._restore_energy(context, pet, interactor)

            method = getattr(interactor, action)
            result = method(pet)
            # 持久化保存（与 _pet_interact CLI 路径保持一致）
            if context.pet_storage is not None:
                context.pet_storage.save(pet)
            # 返回状态摘要，便于 LLM 在最终答案中给出真实数值
            return (
                f"{result['message']}\n"
                f"当前状态：饱食 {pet.hunger}/100，心情 {pet.mood}/100，"
                f"能量 {pet.energy}/100，清洁 {pet.cleanliness}/100"
            )
        except Exception as e:
            return f"[互动失败] {type(e).__name__}: {e}"

    def _restore_energy(self, context: ToolContext, pet: Any, interactor: Any) -> str:
        """智能恢复能量：优先用 energy_drink 道具，否则 sleep，都失败则提示购买。"""
        # 能量已满
        if pet.energy >= 100:
            return f"{pet.name} 能量已满（{pet.energy}/100），无需恢复"

        # 策略 1：检查背包是否有 energy_drink
        has_drink = any(
            slot.get("item_id") == "energy_drink" and slot.get("count", 0) > 0
            for slot in pet.inventory
        )
        if has_drink and context.pet_shop is not None:
            try:
                result = context.pet_shop.use(pet, "energy_drink")
                if context.pet_storage is not None:
                    context.pet_storage.save(pet)
                return (
                    f"{result['message']}（用了能量饮料，无冷却）\n"
                    f"当前能量 {pet.energy}/100"
                )
            except Exception as e:
                # 道具失败降级到 sleep
                pass

        # 策略 2：尝试 sleep
        try:
            result = interactor.sleep(pet)
            if context.pet_storage is not None:
                context.pet_storage.save(pet)
            return (
                f"{result['message']}\n"
                f"当前能量 {pet.energy}/100"
            )
        except Exception as sleep_err:
            # 策略 3：sleep 冷却中，提示去商店
            return (
                f"[恢复失败] {sleep_err}\n"
                f"提示：可用 pet_shop 工具购买 energy_drink（100 经验），"
                f"无冷却立即恢复 50 能量"
            )


# ============================================================
# 8. pet_status — 查询宠物完整状态
# ============================================================

@register_tool
@dataclass
class PetStatusTool(Tool):
    """查询宠物完整状态：属性、等级经验、分系、道具栏、每日任务进度。

    解决"宠物能量还有吗"/"宠物状态怎么样"等查询类问题，
    返回真实数据而非让 LLM 编造。
    """
    name: str = "pet_status"
    description: str = "查询宠物完整状态（属性/等级/经验/道具栏/任务进度）"
    args_schema: Optional[Type[BaseModel]] = None
    prompt_block: str = (
        'pet_status — 查询宠物完整状态\n'
        '   {"tool": "pet_status", "args": ""}\n'
        '   返回：饱食/心情/能量/清洁/等级/经验/分系/道具栏/今日任务进度\n'
        '   当用户问"宠物能量还有吗/状态怎么样/有什么道具"时使用'
    )

    def _parse_args_str(self, args_str: str) -> Tuple[Dict[str, Any], Optional[str]]:
        # 无参数工具
        return {}, None

    def execute(self, context: Optional[ToolContext] = None, **_: Any) -> str:
        if context is None or context.pet is None:
            return "[未启用] 当前会话未加载宠物。请用 /pet adopt 领养后再试。"
        pet = context.pet
        branch_label = {"scholar": "学者", "warrior": "战士", "artisan": "工匠"}.get(
            pet.branch or "", "未分系"
        )

        # 基础属性
        lines = [
            f"宠物：{pet.name}（Lv{pet.level} {branch_label}）",
            f"属性：饱食 {pet.hunger}/100，心情 {pet.mood}/100，"
            f"能量 {pet.energy}/100，清洁 {pet.cleanliness}/100",
            f"经验：{pet.exp}/{pet.exp_needed()}" + (
                f"（距离 Lv{pet.level + 1} 还需 {pet.exp_remaining()}）"
                if pet.level < 10 else "（已达最高级）"
            ),
        ]

        # 道具栏
        if pet.inventory:
            inv_desc = ", ".join(
                f"{slot.get('item_id', '?')}×{slot.get('count', 0)}"
                for slot in pet.inventory
            )
            lines.append(f"道具栏：{inv_desc}")
        else:
            lines.append("道具栏：空")

        # 每日任务进度
        if context.pet_task_manager is not None and pet.daily_tasks:
            task_lines = []
            for t in pet.daily_tasks:
                status = "✓" if t.get("completed") else f"{t.get('progress', 0)}/{t.get('target', 0)}"
                task_lines.append(f"  - {t.get('description', '?')} [{status}] +{t.get('reward', 0)}")
            lines.append("今日任务：\n" + "\n".join(task_lines))

        # 限时效果
        if pet.active_effects:
            effects_desc = ", ".join(
                f"{e.get('effect', '?')}" for e in pet.active_effects
            )
            lines.append(f"限时效果：{effects_desc}")

        return "\n".join(lines)


# ============================================================
# 9. pet_manage — 宠物管理（改名/切换人格/重置）
# ============================================================

class PetManageArgs(BaseModel):
    action: str
    value: str = ""


@register_tool
@dataclass
class PetManageTool(Tool):
    """宠物管理操作：改名、切换人格风格、重置统计/效果。

    action 取值：
    - rename <新名字>      改名
    - style <scholar|warrior|artisan|auto>  切换人格风格
    - reset_stats          清空行为统计（重新分系判定）
    - reset_effects        清空所有限时效果
    """
    name: str = "pet_manage"
    description: str = "宠物管理（改名/切换人格/重置统计/清空效果）"
    args_schema: Optional[Type[BaseModel]] = PetManageArgs
    prompt_block: str = (
        'pet_manage — 宠物管理（改名/切换人格/重置）\n'
        '   {"tool": "pet_manage", "args": "rename 小白"}          # 改名\n'
        '   {"tool": "pet_manage", "args": "style scholar"}        # 切换学者风格\n'
        '   {"tool": "pet_manage", "args": "reset_stats"}          # 清空行为统计\n'
        '   {"tool": "pet_manage", "args": "reset_effects"}        # 清空限时效果'
    )

    _VALID_ACTIONS = ("rename", "style", "reset_stats", "reset_effects")
    _VALID_STYLES = ("scholar", "warrior", "artisan", "auto")

    def _parse_args_str(self, args_str: str) -> Tuple[Dict[str, Any], Optional[str]]:
        parts = args_str.strip().split(None, 1)
        if not parts or not parts[0]:
            return {}, "[错误] 用法: rename <名字> | style <风格> | reset_stats | reset_effects"
        action = parts[0].lower()
        value = parts[1].strip() if len(parts) > 1 else ""
        if action not in self._VALID_ACTIONS:
            return {}, f"[错误] 未知操作: {action}，可选: {', '.join(self._VALID_ACTIONS)}"
        return {"action": action, "value": value}, None

    def execute(
        self,
        context: Optional[ToolContext] = None,
        *,
        action: str,
        value: str = "",
        **_: Any,
    ) -> str:
        if context is None or context.pet is None:
            return "[未启用] 当前会话未加载宠物。"
        pet = context.pet

        try:
            if action == "rename":
                if not value:
                    return "[错误] 改名需要新名字：rename <新名字>"
                old = pet.name
                pet.name = value
                if context.pet_storage is not None:
                    context.pet_storage.save(pet)
                return f"✓ {old} 改名为 {value}"

            elif action == "style":
                if not value or value not in self._VALID_STYLES:
                    return f"[错误] 风格可选: {', '.join(self._VALID_STYLES)}"
                # 切换人格风格需要写入 memory_store（与 _pet_style 一致）
                # Agent 工具层只更新 pet.branch，profile 持久化交由调用方
                # 这里返回提示，让用户用 /pet style 命令持久化
                return (
                    f"提示：人格风格切换需用 /pet style {value} 命令持久化到 profile。"
                    f"当前 pet.branch={pet.branch or '未分系'}。"
                )

            elif action == "reset_stats":
                pet.reset_stats()
                if context.pet_storage is not None:
                    context.pet_storage.save(pet)
                return "✓ 已清空行为统计（等级/经验/属性保留）"

            elif action == "reset_effects":
                count = pet.clear_active_effects()
                if context.pet_storage is not None:
                    context.pet_storage.save(pet)
                return f"✓ 已清空 {count} 个限时效果"

            else:
                return f"[错误] 未知操作: {action}"

        except Exception as e:
            return f"[管理失败] {type(e).__name__}: {e}"


# ============================================================
# 10. pet_shop — 商店操作（查看/购买/使用道具）
# ============================================================

class PetShopArgs(BaseModel):
    action: str
    item_id: str = ""


@register_tool
@dataclass
class PetShopTool(Tool):
    """宠物商店：查看道具列表、购买道具、使用道具。

    action 取值：
    - list                 列出商店所有道具
    - buy <item_id>        购买道具（消耗经验）
    - use <item_id>        使用道具（应用效果）
    """
    name: str = "pet_shop"
    description: str = "宠物商店（查看/购买/使用道具）"
    args_schema: Optional[Type[BaseModel]] = PetShopArgs
    prompt_block: str = (
        'pet_shop — 宠物商店（查看/购买/使用道具）\n'
        '   {"tool": "pet_shop", "args": "list"}              # 查看商店\n'
        '   {"tool": "pet_shop", "args": "buy fish"}          # 购买小鱼干\n'
        '   {"tool": "pet_shop", "args": "use fish"}          # 使用小鱼干'
    )

    _VALID_ACTIONS = ("list", "buy", "use")

    def _parse_args_str(self, args_str: str) -> Tuple[Dict[str, Any], Optional[str]]:
        parts = args_str.strip().split(None, 1)
        if not parts or not parts[0]:
            return {}, "[错误] 用法: list | buy <id> | use <id>"
        action = parts[0].lower()
        item_id = parts[1].strip() if len(parts) > 1 else ""
        if action not in self._VALID_ACTIONS:
            return {}, f"[错误] 未知操作: {action}，可选: {', '.join(self._VALID_ACTIONS)}"
        return {"action": action, "item_id": item_id}, None

    def execute(
        self,
        context: Optional[ToolContext] = None,
        *,
        action: str,
        item_id: str = "",
        **_: Any,
    ) -> str:
        # list 不需要 pet，但 buy/use 需要
        if action == "list":
            shop = context.pet_shop if context else None
            if shop is None:
                # 降级：直接读静态 ITEMS 定义
                from core.pet.shop import ITEMS
                lines = ["道具商店："]
                for item in ITEMS:
                    lines.append(f"  {item['id']}  {item['name']}  {item['price']}经验")
                return "\n".join(lines)
            items = shop.list_items()
            lines = ["道具商店："]
            for item in items:
                lines.append(f"  {item['id']}  {item['name']}  {item['price']}经验")
            return "\n".join(lines)

        if context is None or context.pet is None or context.pet_shop is None:
            return "[未启用] 当前会话未加载宠物或商店。"

        pet = context.pet
        shop = context.pet_shop

        try:
            if action == "buy":
                if not item_id:
                    return "[错误] 购买需要道具ID：buy <item_id>"
                result = shop.buy(pet, item_id)
                if context.pet_storage is not None:
                    context.pet_storage.save(pet)
                return result["message"] + f"（剩余经验 {pet.exp}）"

            elif action == "use":
                if not item_id:
                    return "[错误] 使用需要道具ID：use <item_id>"
                result = shop.use(pet, item_id)
                if context.pet_storage is not None:
                    context.pet_storage.save(pet)
                return (
                    f"{result['message']}\n"
                    f"当前状态：饱食 {pet.hunger}/100，心情 {pet.mood}/100，"
                    f"能量 {pet.energy}/100，清洁 {pet.cleanliness}/100"
                )

            else:
                return f"[错误] 未知操作: {action}"

        except Exception as e:
            return f"[商店操作失败] {type(e).__name__}: {e}"
