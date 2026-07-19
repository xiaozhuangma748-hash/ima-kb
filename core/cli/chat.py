"""AI 对话 Mixin。

从 repl.py 第 3789-4114 行迁移：
- ``_handle_chat()`` AI 对话（多轮历史 + RAG 检索 + 流式输出）
- ``_render_answer()`` 渲染带引用的管理员回答
- ``_render_citations_and_events()`` 只渲染引用溯源和宠物事件
- ``_record_workflow()`` 记录命令到工作流追踪器
"""
from __future__ import annotations

import os
import sys
from typing import Optional

from rich.live import Live
from rich.spinner import Spinner
from rich.panel import Panel
from rich.markdown import Markdown
from rich.text import Text

from core.ui.theme import get_theme
from core.llm.client import LLMError
from core.qa.chain import RAGChain
from core.pet.administrator import AnswerResult
from core.cli.constants import console
from core.cli.welcome import _record_activity
from config import settings


# 宠物互动意图识别：自然语言 → 互动动作
# 命中后短路到 _pet_interact，避免 LLM "嘴上喂" 但状态不变
_PET_INTENT_RULES = [
    # (action, 中文关键词, 英文关键词)
    ("feed",   ("喂", "喂食", "喂养", "吃的", "吃东西", "加食物", "加粮", "投喂", "饱食"), ("feed",)),
    ("play",   ("玩", "玩耍", "陪玩", "逗", "互动一下", "游戏"), ("play",)),
    ("wash",   ("洗", "洗澡", "清洁", "清理", "打扫", "清扫", "卫生"), ("wash", "clean")),
    ("train",  ("训练", "练习", "学习"), ("train",)),
    ("sleep",  ("睡", "睡觉", "休息", "歇", "歇会", "睡一会", "睡一会儿"), ("sleep", "rest")),
    # 恢复能量：智能路由（优先道具，否则 sleep），不走 PetInteractor 直接方法
    ("restore_energy", ("加能量", "补充能量", "恢复能量", "能量加", "充能", "回能",
                         "加一下能量", "能量加上", "补能量", "回血"), ()),
]

# 宠物状态查询关键词：命中后返回真实状态，而非让 LLM 编造
_PET_QUERY_KEYWORDS = (
    "能量", "饱食", "心情", "清洁", "状态", "等级", "经验", "属性",
    "怎么样", "还好吗", "还有吗", "多少", "进度", "任务",
    "道具栏", "有什么道具", "有什么东西", "背包",
    "lv", "level",
)

# 宠物改名关键词：用正则提取新名字
_PET_RENAME_KEYWORDS = ("改名", "名字改成", "叫", "重新命名", "改名叫")


def _detect_pet_intent(text: str) -> Optional[str]:
    """识别自然语言中的宠物互动意图。

    Returns:
        命中的动作名 (feed/play/wash/train/sleep)，未命中返回 None
    """
    t = text.strip().lower()
    if not t or len(t) > 60:
        # 过长输入多半是正经问答，不走宠物短路
        return None
    # 去掉前导"帮我"/"请"/"给"等口语词，避免误判
    stripped = t
    for prefix in ("帮我", "请", "给", "麻烦", "能不能", "可以", "帮"):
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix):]
    stripped = stripped.strip()
    if not stripped:
        return None
    for action, cn_words, en_words in _PET_INTENT_RULES:
        for w in cn_words:
            if w in stripped:
                return action
        for w in en_words:
            if w in stripped.split():
                return action
    return None


def _is_pet_query(text: str) -> bool:
    """识别宠物状态查询意图（如"宠物能量还有吗"）。

    与 _detect_pet_intent 互补：互动意图走短路执行，
    查询意图走返回真实状态。
    """
    t = text.strip().lower()
    if not t or len(t) > 80:
        return False
    # 必须同时包含"宠物"或宠物名字相关线索，避免误判普通问句
    has_pet_marker = any(k in t for k in ("宠物", "它", "小林", "小黑", "小白"))
    # 但"宠物能量/状态"这种直接问法也算
    has_query_kw = any(k in t for k in _PET_QUERY_KEYWORDS)
    return has_pet_marker and has_query_kw


def _extract_rename_target(text: str) -> Optional[str]:
    """从"给宠物改名叫小白"等句子中提取新名字。

    支持的句式：
    - 改名叫XX / 改名XX
    - 名字改成XX / 名字改为XX
    - 叫XX（前文需有"宠物"上下文）

    Returns:
        新名字字符串，未命中返回 None
    """
    import re
    t = text.strip()
    if not t or len(t) > 60:
        return None
    # 必须包含"宠物"上下文，否则"我叫张三"这种也会误判
    if "宠物" not in t and "它" not in t:
        return None

    # 优先匹配"改名叫XX""改名XX""名字改成XX""名字改为XX"
    patterns = [
        r"改名叫(.+?)$",
        r"改名(.+?)$",
        r"名字改成(.+?)$",
        r"名字改为(.+?)$",
        r"重新命名(?:为|叫)?(.+?)$",
    ]
    for pat in patterns:
        m = re.search(pat, t)
        if m:
            name = m.group(1).strip()
            # 去掉末尾标点
            name = name.rstrip("。.!！?？了啊")
            if 1 <= len(name) <= 12:
                return name
    return None


class ChatMixin:
    """AI 对话相关方法。"""

    @staticmethod
    def _sanitize_latex(text: str) -> str:
        """清理 LLM 输出的 LaTeX 数学公式，使其在 Markdown 中可读。

        处理规则：
        - $$...$$ / $...$  → 去掉 $ 符号，保留内容
        - \\times          → ×
        - \\div            → ÷
        - \\approx         → ≈
        - \\leq / \\le     → ≤
        - \\geq / \\ge     → ≥
        - \\mathbf{...}    → 只保留花括号内容
        - \\text{...}      → 只保留花括号内容
        """
        import re

        # 1. 去掉 $$...$$ 和 $...$ 的外层符号（保留内容）
        text = re.sub(r"\$\$(.*?)\$\$", r"\1", text, flags=re.DOTALL)
        text = re.sub(r"\$(.*?)\$", r"\1", text, flags=re.DOTALL)

        # 2. 常见 LaTeX 命令替换
        replacements = {
            r"\times": "×",
            r"\div": "÷",
            r"\approx": "≈",
            r"\leq": "≤",
            r"\le": "≤",
            r"\geq": "≥",
            r"\ge": "≥",
            r"\neq": "≠",
            r"\equiv": "≡",
            r"\pm": "±",
            r"\cdot": "·",
        }
        for latex, char in replacements.items():
            text = text.replace(latex, char)

        # 3. \\mathbf{...} / \\text{...} → 只保留花括号内容
        text = re.sub(r"\\mathbf\{(.*?)\}", r"\1", text, flags=re.DOTALL)
        text = re.sub(r"\\text\{(.*?)\}", r"\1", text, flags=re.DOTALL)

        # 4. LaTeX 换行 \\ → 换行符
        text = text.replace("\\\\", "\n")

        # 5. 清理因去掉 $ 后可能残留的换行空格
        text = text.replace("  ", " ")

        return text

    @staticmethod
    def _sanitize_citations(text: str, num_sources: int) -> str:
        """清理越界的 [n] 引用标记。

        LLM 幻觉可能生成 [3] 但实际只有 1 条资料，调用 sanitize_outbound_citations
        删除越界标记，保证正文编号与引用列表一致。
        """
        if num_sources <= 0 or not text:
            return text
        from core.retrieval.citation import sanitize_outbound_citations
        return sanitize_outbound_citations(text, num_sources)

    def _print_token_usage(self, llm_obj=None) -> None:
        """打印最近一次 LLM 调用的 token 使用量。

        Args:
            llm_obj: LLM 客户端实例。未传时优先用 self.administrator.llm，
                    再回退到 self.rag.llm（RAGChain 降级路径）
        """
        try:
            if llm_obj is None:
                llm_obj = getattr(self, "administrator", None)
                if llm_obj is not None:
                    llm_obj = getattr(llm_obj, "llm", None)
                if llm_obj is None:
                    rag = getattr(self, "rag", None)
                    if rag is not None:
                        llm_obj = getattr(rag, "llm", None)
            if llm_obj is None:
                return
            usage = getattr(llm_obj, "last_usage", None)
            if not usage:
                return
            console.print(
                f"[dim]tokens: input={usage.get('input', 0)} "
                f"output={usage.get('output', 0)} "
                f"total={usage.get('total', 0)}[/dim]"
            )
        except Exception:
            pass

    def _handle_chat(self, user_input: str) -> None:
        """AI 对话（带多轮历史 + RAG 检索 + Spinner 动画）。"""
        # 宠物互动意图短路：用户说"帮我喂一下宠物"等自然语言时，
        # 直接调 _pet_interact 真正更新状态，避免 LLM "嘴上喂"但状态不变
        if self.pet is not None:
            intent = _detect_pet_intent(user_input)
            if intent is not None:
                # restore_energy 走智能路由（优先道具，否则 sleep）
                if intent == "restore_energy":
                    self._pet_restore_energy()
                    return
                self._pet_interact(intent)
                return

            # 改名意图：正则提取新名字后调 _pet_rename
            new_name = _extract_rename_target(user_input)
            if new_name is not None:
                self._pet_rename(new_name)
                return

            # 状态查询意图：返回真实状态，避免 LLM 编造
            if _is_pet_query(user_input):
                self._pet_answer_query()
                return

        if not self.llm_available:
            console.print("[red]LLM 未配置，无法问答[/red]")
            console.print("[dim]请在 .env 中设置 AGNES_API_KEY[/dim]")
            return

        # 优先走 PetAdministrator（编排检索 + 重排 + 记忆 + 人格 + 引用）
        # 失败时降级到下方原有 RAG 逻辑
        # 延迟初始化 PetAdministrator
        if self.administrator is None and not self._admin_init_failed and self.pet:
            self._init_administrator()
        # 重置流式输出状态（防止上一次异常残留）
        self._stream_started = False
        self._stream_live = None
        self._stream_text = ""
        if self.administrator is not None and self.current_analysis is None:
            try:
                # 流式输出
                result = None
                live = None  # 动态 spinner：阶段等待时显示
                import time as _time
                _t0 = _time.time()  # 思考计时起点
                # 获取跨会话记忆上下文
                _cross_ctx = None
                if getattr(self, 'cross_session_memory', None) is not None:
                    try:
                        _cross_ctx = self.cross_session_memory.get_context()
                    except Exception:
                        pass
                for event in self.administrator.ask_stream(
                    user_input, history=self.history, summary=self.conversation_summary,
                    cross_session_context=_cross_ctx,
                ):
                    if event["type"] == "stage":
                        # 显示阶段提示 — 用动态 spinner 等待下一阶段
                        stage_text = {"检索": "混合检索", "重排": "LLM 重排"}.get(
                            event["stage"], event["stage"]
                        )
                        # 停掉上一个 spinner（切换阶段）
                        if live is not None:
                            live.stop()
                        live = Live(
                            Spinner("dots", text=f"[dim]{stage_text}...[/dim]"),
                            console=console, transient=True, refresh_per_second=10,
                        )
                        live.start()
                    elif event["type"] == "source_count":
                        # 记录参考资料数量，供 token 流式清理越界 [n] 引用标记使用
                        self._source_count = event.get("count", 0)
                    elif event["type"] == "token":
                        # 逐 token 输出 — 首次 token 前停掉 spinner 并启动 Live
                        if not getattr(self, "_stream_started", False):
                            if live is not None:
                                live.stop()
                                live = None
                            # 首次 token 到达，记录思考时间（在答案后显示）
                            self._first_token_time = _time.time() - _t0
                            self._stream_started = True
                            # 打印 AI 标识行（与降级路径一致，避免用户输入和回答紧贴）
                            if self.pet is not None:
                                avatar = {"scholar": "✻", "warrior": "✦", "artisan": "✼"}.get(self.pet.branch, "✺")
                                color = {"scholar": "cyan", "warrior": "red", "artisan": "yellow"}.get(self.pet.branch, "white")
                                console.print(f"[{color}]{avatar}[/{color}] [bold magenta]{self.pet.name}[/bold magenta]")
                            else:
                                console.print("[bold yellow]>[/bold yellow] [bold cyan]AI[/bold cyan]")
                            console.print()  # 标识行与回答正文之间空一行
                            # Live + Markdown 实时渲染：流式过程中直接渲染 markdown
                            # 避免流式纯文本 + done 后 Markdown 重新渲染导致的重复输出
                            # （transient=True 在内容超出一屏时无法清除已滚动内容）
                            self._stream_live = Live(
                                Markdown(""),
                                console=console,
                                refresh_per_second=12,
                                transient=False,
                            )
                            self._stream_live.start()
                            self._stream_text = ""
                        self._stream_text += event["text"]
                        # 用 Markdown 实时渲染（表格、标题、列表等格式正确显示）
                        # 同时清理 LLM 可能生成的 LaTeX 公式语法和越界 [n] 引用标记
                        sanitized = self._sanitize_latex(self._stream_text)
                        sanitized = self._sanitize_citations(
                            sanitized, getattr(self, "_source_count", 0)
                        )
                        self._stream_live.update(Markdown(sanitized))
                    elif event["type"] == "done":
                        # 收尾：停掉残留 spinner 和 Live（无 token 的极端情况）
                        if live is not None:
                            live.stop()
                            live = None
                        if getattr(self, "_stream_live", None) is not None:
                            self._stream_live.stop()
                            self._stream_live = None
                        result = event["result"]
                        self._stream_started = False
                        _total_time = _time.time() - _t0
                # 安全兜底：循环结束确保 spinner 和 Live 已停
                if live is not None:
                    live.stop()
                    live = None
                if getattr(self, "_stream_live", None) is not None:
                    self._stream_live.stop()
                    self._stream_live = None
                # 不再重新渲染：Live + Markdown 已在流式过程中完成渲染
                # （避免流式纯文本 + done 后 Markdown 重新渲染导致的重复输出）
                console.print()  # 流式结束后换行

                if result is not None:
                    # 只渲染引用溯源和宠物事件，不重复渲染正文（正文已流式输出）
                    self._render_citations_and_events(result)
                    _total = _time.time() - _t0
                    _think_time = getattr(self, "_first_token_time", None)
                    if _think_time is not None:
                        console.print(f"[dim]Thinking {_think_time:.1f}s[/dim]")
                    console.print(f"[dim]Total {_total:.1f}s[/dim]")
                    # token 使用量（统一通过 _print_token_usage 输出）
                    self._print_token_usage()
                    # debug 诊断信息
                    if os.environ.get("IMA_DEBUG"):
                        import time as _time
                        console.print(f"\n  [dim]-- debug --")
                        console.print(f"  [dim]检索结果: {len(result.sources) if result.sources else 0} 条")
                        console.print(f"  [dim]引用数: {len(result.citations) if result.citations else 0}")
                        if result.pet_events:
                            console.print(f"  [dim]宠物事件: {result.pet_events}")
                        console.print(f"  [dim]历史轮数: {len(self.history) // 2}[/dim]")
                    # 保存到对话历史（修复 /session save 无法保存 bug）
                    self.history.append({"role": "user", "content": user_input})
                    self.history.append({"role": "assistant", "content": result.text})
                    # history 超过阈值时触发滚动摘要压缩，保留最近 window 条原文
                    if len(self.history) > settings.history_compress_threshold:
                        self._compress_history()
                    # 记忆持久化 + 工作流记录
                    if self.memory_store is not None:
                        try:
                            self.memory_store.save()
                        except Exception:
                            pass
                    self._record_workflow("qa")
                    _record_activity("qa", user_input[:40], getattr(self, 'active_session_name', None))
                    # 恢复能量
                    if self.pet is not None:
                        self.pet.energy = min(100, self.pet.energy + 2)
                        self.pet_storage.save(self.pet)
                    # 自动保存会话
                    self._auto_save_session()
                    # 跨会话记忆自动提取（每轮都触发，详细反馈）
                    self._auto_extract_cross_session(user_input, result.text)
                return
            except Exception as e:
                # 异常时确保 spinner 和 Live 已停
                try:
                    if live is not None:
                        live.stop()
                    if getattr(self, "_stream_live", None) is not None:
                        self._stream_live.stop()
                        self._stream_live = None
                except Exception:
                    pass
                err_msg = str(e).replace("[", "\\[")
                console.print(f"[yellow]管理员问答失败，降级为普通问答: {err_msg}[/yellow]")
                self._stream_started = False

        # 数据分析追问模式：如果刚 /analyze 过，且用户输入像追问
        if self.current_analysis is not None:
            az, result = self.current_analysis
            # 检测是否是追问（短问题 + 含疑问/分析关键词）
            q = user_input.strip()
            is_followup = (
                len(q) < 100
                and any(k in q for k in ["?", "？", "汇总", "统计", "分组", "排序",
                                          "最大", "最小", "平均", "多少", "哪个", "哪些",
                                          "按", "分布", "趋势", "缺失", "空值", "相关性",
                                          "汇总", "group", "sort", "top", "前"])
            )
            if is_followup:
                console.print("[bold yellow]>[/bold yellow] [dim]基于数据分析回答...[/dim]")
                try:
                    answer = az.ask(result, q)
                    console.print("[bold yellow]>[/bold yellow] [bold cyan]数据分析助手[/bold cyan]")
                    console.print(answer)
                    console.print()
                except Exception as e:
                    err_msg = str(e).replace("[", "\\[")
                    console.print(f"[red]追问失败:[/red] {type(e).__name__}: {err_msg}")
                return

        # 懒加载 RAGChain（已升级为混合检索 + 多轮 query expansion）
        if self.rag is None:
            try:
                self.rag = RAGChain(storage=self.storage)
            except LLMError as e:
                console.print(f"[red]LLM 初始化失败:[/red] {e}")
                self.llm_available = False
                return

        # 使用改进的 RAGChain：混合检索 + 重排序 + 多轮上下文扩展
        import time as _time
        _t0 = _time.time()
        with console.status("[bold yellow]混合检索知识库...[/bold yellow]", spinner="dots"):
            answer = self.rag.ask(user_input, history=self.history)
        _think_time = _time.time() - _t0

        if not answer.has_answer:
            console.print("[yellow]! 知识库中没有相关资料，尝试基于通用知识回答[/yellow]\n")
            # 退化为纯对话（带多轮上下文）
            try:
                # 构建带历史的 messages（窗口大小由 settings.history_window 控制）
                recent_history = (self.history or [])[-settings.history_window:]
                messages = list(recent_history) + [{"role": "user", "content": user_input}]
                # 注入跨会话记忆
                _cross_ctx2 = None
                if getattr(self, 'cross_session_memory', None) is not None:
                    try:
                        _cross_ctx2 = self.cross_session_memory.get_context()
                    except Exception:
                        pass
                if _cross_ctx2:
                    messages.insert(0, {"role": "system", "content": f"## 跨会话记忆\n{_cross_ctx2}"})
                full_content: list[str] = []
                first_token = True
                stream_live = None
                stream_text = ""
                for token in self.rag.llm.chat_stream(messages, temperature=0.5):
                    if first_token:
                        console.print("[bold yellow]>[/bold yellow] [bold cyan]AI[/bold cyan]")
                        stream_live = Live(Text(""), console=console, refresh_per_second=12, transient=True)
                        stream_live.start()
                        first_token = False
                    stream_text += token
                    stream_live.update(Text(stream_text.replace("**", "")))
                    full_content.append(token)
                if stream_live is not None:
                    stream_live.stop()
                # 用 Markdown 重新渲染（transient 已清除流式纯文本）
                assistant_content = "".join(full_content)
                if assistant_content:
                    console.print(Markdown(assistant_content))
                console.print()
                _total = _time.time() - _t0
                console.print(f"[dim]Thinking {_think_time:.1f}s[/dim]")
                console.print(f"[dim]Total {_total:.1f}s[/dim]")
                # token 使用量（纯对话降级路径，直接读 LLM 客户端）
                self._print_token_usage()
            except LLMError:
                console.print("[yellow]（AI 暂时无法回答）[/yellow]\n")
                return
        else:
            # 同步模式：RAGChain 已生成完整回答
            console.print("[bold yellow]>[/bold yellow] [bold cyan]AI[/bold cyan]")
            # 用 Markdown 渲染，支持表格、列表等格式
            console.print(Markdown(answer.content))
            _total = _time.time() - _t0
            console.print(f"[dim]Thinking {_think_time:.1f}s[/dim]")
            console.print(f"[dim]Total {_total:.1f}s[/dim]")
            # token 使用量（RAGChain 同步路径，读 self.rag.llm）
            self._print_token_usage()
            assistant_content = answer.content

        # 显示引用来源
        if answer.citations:
            console.print()
            ref_lines = []
            for c in answer.citations:
                score_str = f" (相关度 {c.get('score', 0):.4f})" if 'score' in c else ""
                source_str = f" [{c.get('source', '?')}]" if 'source' in c else ""
                ref_lines.append(
                    f"  [{c['index']}] [cyan]{c['doc_title']}[/cyan]"
                    f"[dim]{score_str}{source_str}[/dim]"
                )
            if answer.low_confidence:
                ref_lines.insert(0, "  [dim]! 检索相关度较低，仅供参考[/dim]")
            ref_panel = Panel(
                "\n".join(ref_lines),
                border_style="cyan",
                title="[bold cyan]引用来源[/bold cyan]",
                title_align="left",
                padding=(0, 1),
            )
            console.print(ref_panel)
            console.print()

        # 保存历史
        self.history.append({"role": "user", "content": user_input})
        self.history.append({"role": "assistant", "content": assistant_content})
        if len(self.history) > settings.history_compress_threshold:
            self._compress_history()

        # 宠物经验 + 能量
        self._pet_gain_exp(10, "qa")
        if self.pet:
            self.pet.energy = min(100, self.pet.energy + 2)
            self.pet_storage.save(self.pet)
        _record_activity("qa", user_input[:40], getattr(self, 'active_session_name', None))
        # 自动保存会话
        self._auto_save_session()
        # 跨会话记忆自动提取（每轮都触发，详细反馈）
        self._auto_extract_cross_session(user_input, assistant_content)

    # ---- 管理员回答渲染 + 工作流 ----

    def _auto_extract_cross_session(self, user_input: str, assistant_reply: str) -> None:
        """跨会话记忆自动提取（每轮对话后触发）。

        用 LLM 分析本轮对话，提取值得跨会话记住的信息，
        合并到 cross_session_memory，并给出详细反馈。

        失败静默降级，不影响主流程。
        """
        # 前置条件：跨会话记忆可用 + LLM 可用
        if getattr(self, 'cross_session_memory', None) is None:
            console.print("[dim]! 记忆提取跳过: cross_session_memory 未初始化[/dim]")
            return
        if not self.llm_available:
            console.print("[dim]! 记忆提取跳过: LLM 不可用[/dim]")
            return

        try:
            from core.memory.extractor import MemoryExtractor
            from core.llm.client import get_llm

            llm = get_llm()
            extractor = MemoryExtractor(llm=llm, memory=self.cross_session_memory)
            added = extractor.extract_and_merge(user_input, assistant_reply)

            # 详细反馈：显示新增的记忆
            new_items: list[str] = []
            for pref in added.get("preferences", []):
                new_items.append(f"偏好 {pref}")
            for topic in added.get("topics", []):
                new_items.append(f"主题: {topic}")
            for q in added.get("questions", []):
                new_items.append(f"问题: {q}")
            for fact in added.get("facts", []):
                new_items.append(f"事实: {fact}")

            if new_items:
                console.print()
                console.print("[dim]! 已记住:[/dim]")
                for item in new_items:
                    console.print(f"[dim]  + {item}[/dim]")
                console.print("[dim]  (用 /cross list 查看)[/dim]")
        except Exception as e:
            # 提取失败：显示错误（调试用，确认稳定后改回静默）
            console.print(f"[dim]! 记忆提取失败: {e}[/dim]")

    def _compress_history(self) -> None:
        """当 history 超过阈值时，压缩早期对话为滚动摘要。

        - 阈值由 settings.history_compress_threshold 控制（默认 24）
        - 保留最近 settings.history_window 条原文（默认 16，8 轮）
        - 对前 N 条生成增量摘要（基于已有 summary + 早期对话）
        - 摘要失败则简单截断，不影响主流程
        """
        threshold = settings.history_compress_threshold
        window = settings.history_window
        if len(self.history) <= threshold:
            return

        # 早期对话（要被摘要的部分）
        old_messages = self.history[:-window]
        recent_messages = self.history[-window:]
        max_chars = settings.summary_max_chars

        # 构建摘要 prompt（增量：基于旧 summary + 新早期对话）
        if self.conversation_summary:
            prompt = (
                "你是对话摘要助手。请结合已有摘要和以下新对话，更新摘要。\n\n"
                "要求：\n"
                "1. 保留用户的核心需求和关注点\n"
                "2. 保留已给出的关键结论（政策条款、数据、建议）\n"
                "3. 保留未解决的问题或待办事项\n"
                "4. 保留提到的具体文档名/政策名/人名/地名\n"
                "5. 用第三人称，简洁条目式\n"
                f"6. 不超过 {max_chars} 字\n\n"
                f"已有摘要：\n{self.conversation_summary}\n\n"
                "新对话内容：\n"
            )
        else:
            prompt = (
                "你是对话摘要助手。请将以下对话压缩为简洁摘要。\n\n"
                "要求：\n"
                "1. 保留用户的核心需求和关注点\n"
                "2. 保留已给出的关键结论（政策条款、数据、建议）\n"
                "3. 保留未解决的问题或待办事项\n"
                "4. 保留提到的具体文档名/政策名/人名/地名\n"
                "5. 用第三人称，简洁条目式\n"
                f"6. 不超过 {max_chars} 字\n\n"
                "对话内容：\n"
            )

        for msg in old_messages:
            role = "用户" if msg["role"] == "user" else "助手"
            # 每条消息截断到 300 字，避免 prompt 过长
            content = msg["content"][:300]
            prompt += f"\n{role}: {content}\n"

        prompt += "\n更新后的摘要："

        try:
            summary = self.administrator.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=max_chars,
            )
            self.conversation_summary = summary.strip()
            self.history = recent_messages
        except Exception:
            # 摘要失败则简单截断，保留最近 window 条
            self.history = self.history[-window:]

    def _render_answer(self, result: AnswerResult) -> None:
        """渲染带引用的管理员回答：宠物头像标题 + Markdown 回答面板 + 引用溯源 + 经验提示。"""
        t = get_theme()

        # 宠物头像标题栏（带系别标签）
        if self.pet is not None:
            avatar = {"scholar": "✻", "warrior": "✦", "artisan": "✼"}.get(self.pet.branch, "✺")
            color = {"scholar": "cyan", "warrior": "red", "artisan": "yellow"}.get(self.pet.branch, "white")
            branch_label = {"scholar": "学者", "warrior": "战士", "artisan": "工匠"}.get(self.pet.branch, "")
            branch_tag = f" · {branch_label}" if branch_label else ""
            header = (
                f"[{color}]{avatar}[/{color}] "
                f"[bold magenta]{self.pet.name}[/bold magenta] "
                f"[dim]Lv{self.pet.level}{branch_tag}[/dim]"
            )
        else:
            header = f"[{t.colors['ai_marker']}]>[/{t.colors['ai_marker']}] [bold]AI 助手[/bold]"

        # 回答正文（Markdown 渲染，带面板）
        subtitle = (
            f"[dim]基于 {len(result.citations)} 条引用[/dim]"
            if result.citations else "[dim]基于知识库回答[/dim]"
        )
        answer_panel = Panel(
            Markdown(result.text),
            title=header,
            title_align="left",
            border_style=t.colors["border_ai"],
            padding=(1, 2),
            subtitle=subtitle,
            subtitle_align="right",
        )
        console.print(answer_panel)
        console.print()

        # 引用溯源区块（更紧凑的编号列表）
        if result.citations:
            ref_lines = []
            for i, c in enumerate(result.citations, 1):
                ref_lines.append(
                    f"  [bold cyan]{i}.[/bold cyan] [cyan]{c.title}[/cyan] "
                    f"[dim]§{c.paragraph_num} · doc:{c.doc_id[:8]}[/dim]"
                )
            ref_panel = Panel(
                "\n".join(ref_lines),
                border_style="dim cyan",
                title="[dim]引用溯源[/dim]",
                title_align="left",
                padding=(0, 1),
            )
            console.print(ref_panel)
            console.print()

        # 宠物事件提示（升级 / 分系）
        events = result.pet_events or {}
        if events.get("leveled_up"):
            console.print(f"[bold magenta]{self.pet.name if self.pet else '宠物'} 升到 "
                          f"Lv{events.get('new_level', '?')}！[/bold magenta]")
        if events.get("branched"):
            branch_label = {"scholar": "学者", "warrior": "战士", "artisan": "工匠"}.get(
                events.get("branch", ""), "")
            console.print(f"[bold magenta]进化为 {branch_label}系！[/bold magenta]")

    def _render_citations_and_events(self, result: AnswerResult) -> None:
        """只渲染引用溯源和宠物事件（正文已流式输出）。"""
        # 引用溯源区块（更紧凑的编号列表）
        if result.citations:
            ref_lines = []
            for i, c in enumerate(result.citations, 1):
                ref_lines.append(
                    f"  [bold cyan]{i}.[/bold cyan] [cyan]{c.title}[/cyan] "
                    f"[dim]§{c.paragraph_num} · doc:{c.doc_id[:8]}[/dim]"
                )
            ref_panel = Panel(
                "\n".join(ref_lines),
                border_style="dim cyan",
                title="[dim]引用溯源[/dim]",
                title_align="left",
                padding=(0, 1),
            )
            console.print(ref_panel)
            console.print()

        # 宠物事件提示（升级 / 分系）
        events = result.pet_events or {}
        if events.get("leveled_up"):
            console.print(f"[bold magenta]{self.pet.name if self.pet else '宠物'} 升到 "
                          f"Lv{events.get('new_level', '?')}！[/bold magenta]")
        if events.get("branched"):
            branch_label = {"scholar": "学者", "warrior": "战士", "artisan": "工匠"}.get(
                events.get("branch", ""), "")
            console.print(f"[bold magenta]进化为 {branch_label}系！[/bold magenta]")

    def _record_workflow(self, cmd: str) -> None:
        """记录命令到工作流追踪器，并显示下一步推荐。"""
        if self.workflow_tracker is None:
            return
        # 过滤掉不需要记录的命令
        skip = {"/exit", "/quit", "/help", "/clear", "/theme", "/memory"}
        if cmd in skip:
            return
        try:
            self.workflow_tracker.record_command(cmd)
            # 推荐下一步（基于历史模式）
            suggestion = self.workflow_tracker.suggest_next(cmd)
            if suggestion:
                # suggest_next 返回的命令名可能带前导斜杠（与 record_command 入参一致），
                # 统一去掉前导斜杠后再做 friendly 映射或拼接，避免出现 "//agent" 的双斜杠
                normalized = suggestion.lstrip("/")
                friendly = {
                    "qa": "输入问题进行 AI 问答",
                    "search": "/search 搜索文档",
                    "ingest": "/ingest 入库新文件",
                    "analyze": "/analyze 数据分析",
                    "read": "/read 智能阅读",
                    "compare": "/compare 智能对比",
                    "graph": "/graph 知识图谱",
                    "summarize": "/summarize 生成摘要",
                    "daily": "/daily 生成知识卡片",
                    "draw": "/draw 配图",
                }.get(normalized, f"/{normalized}")
                console.print(f"[dim]接下来可以试试: {friendly}[/dim]")
                console.print()
        except Exception:
            # 工作流记录失败不影响主流程
            pass
