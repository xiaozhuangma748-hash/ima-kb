"""桌面宠物管理员包装器（Task 5）。

零侵入约束：
- 本模块属于 ``core/desktop/`` 新增模块，不修改项目任何现有文件。
- 通过继承 ``PetAdministrator`` 并在关键阶段触发状态回调，不改动父类逻辑。

设计：
1. ``DesktopPetAdministrator`` 继承 ``PetAdministrator``，复用其检索/重排/LLM 全流程。
2. 实例属性 ``_on_state_change`` 由 ``app.main()`` 注入为 ``bridge.notify_state_change``，
   从而在问答各阶段推送 GIF 状态到 JS 端。
3. 状态映射对应 RAG 流水线：
   - listening：接收问题
   - retrieving：混合检索（stage=检索）
   - ranking：LLM 重排（stage=重排）
   - thinking：组装 prompt / LLM 首帧前
   - answering：流式输出（首个 token 起）
   - celebrating：完成 / error：失败
4. 所有回调调用包裹 try/except，回调异常绝不影响问答主流程。
"""
from __future__ import annotations

import logging
from typing import Optional

from core.pet.administrator import PetAdministrator, AnswerResult
from core.desktop.states import PetState

logger = logging.getLogger(__name__)

__all__ = ["DesktopPetAdministrator"]


class DesktopPetAdministrator(PetAdministrator):
    """带动图状态反馈的宠物管理员。

    在 ``PetAdministrator`` 基础上，于问答各阶段通过
    ``_on_state_change`` 回调通知桌面宠物切换 GIF 状态。
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # 由 app.main() 注入：bridge.notify_state_change(state, payload)
        self._on_state_change = None

    # ---- 状态推送（容错） ----
    def _emit(self, state: PetState, payload: Optional[dict] = None) -> None:
        """安全推送状态变更；回调缺失或异常均静默。"""
        cb = self._on_state_change
        if cb is None:
            return
        try:
            cb(state, payload)
        except Exception as e:
            logger.warning(f"状态回调失败 ({state}): {e}")

    # ---- 同步问答：在关键节点切换状态 ----
    def ask(self, query: str, **kwargs) -> AnswerResult:
        self._emit(PetState.LISTENING)
        try:
            self._emit(PetState.THINKING)
            result = super().ask(query, **kwargs)
            self._emit(PetState.CELEBRATING)
            self._back_to_idle_later()
            return result
        except Exception as e:
            self._emit(PetState.ERROR, {"error": str(e)})
            self._back_to_idle_later()
            raise

    # ---- 流式问答：按 stage/token 事件精确映射状态 ----
    def ask_stream(self, query: str, **kwargs):
        self._emit(PetState.LISTENING)
        first_token = False
        try:
            for event in super().ask_stream(query, **kwargs):
                etype = event.get("type")
                if etype == "stage":
                    stage = event.get("stage")
                    if stage == "检索":
                        self._emit(PetState.RETRIEVING, {"count": event.get("count")})
                    elif stage == "重排":
                        self._emit(PetState.RANKING, {"count": event.get("count")})
                    elif stage == "缓存":
                        self._emit(PetState.THINKING)
                elif etype == "token":
                    if not first_token:
                        self._emit(PetState.ANSWERING)
                        first_token = True
                elif etype == "done":
                    self._emit(PetState.CELEBRATING)
                yield event
            self._back_to_idle_later()
        except Exception as e:
            self._emit(PetState.ERROR, {"error": str(e)})
            self._back_to_idle_later()
            raise

    # ---- 入库状态（供 bridge.ingest 之外的直接调用场景） ----
    def notify_ingesting(self, name: str = "") -> None:
        self._emit(PetState.INGESTING, {"name": name})

    def notify_analyzing(self, payload: Optional[dict] = None) -> None:
        self._emit(PetState.ANALYZING, payload)

    def notify_notifying(self, payload: Optional[dict] = None) -> None:
        self._emit(PetState.NOTIFYING, payload)

    # ---- 状态收尾 ----
    def _back_to_idle_later(self, delay: float = 2.0) -> None:
        """延迟回到 idle，让用户看清 celebrating/error 状态。"""
        import threading

        def _idle():
            self._emit(PetState.IDLE)

        try:
            threading.Timer(delay, _idle).start()
        except Exception:
            pass
