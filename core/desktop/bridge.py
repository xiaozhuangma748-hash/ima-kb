"""桌面宠物 Python ↔ JS 桥接（pywebview JSBridge）。

零侵入约束：
- 本模块属于 ``core/desktop/`` 新增模块，不修改项目任何现有文件。
- 不依赖 pywebview 实际安装：测试时可注入 mock ``evaluate_js``；
  生产环境在 ``app.py`` 中通过 ``set_evaluate_js`` 注入实际函数
  （通常为 ``webview.windows[0].evaluate_js``）。

设计：
1. ``DesktopBridge`` 封装所有 Python → JS 的调用（``_call_js``）。
2. ``set_evaluate_js`` 注入实际 ``evaluate_js`` 函数，未注入时静默。
3. JSBridge 暴露的方法（``get_pet_info`` / ``get_ascii`` / ``ask`` / ``ask_stream``
   / ``ingest`` / ``switch_style`` / ``get_stats`` / ``show_doc``）会被
   pywebview 注册到 ``window.pywebview.api.X``，前端 JS 可直接调用。
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
import threading
from typing import Any, Callable, Optional
from urllib.parse import unquote

from core.desktop.states import PetState
from core.desktop.renderer import AsciiArtLoader

logger = logging.getLogger(__name__)


class DesktopBridge:
    """Python ↔ JS 桥接，封装 pywebview API。

    设计：不依赖 pywebview 实际安装。测试时可注入 mock evaluate_js。
    生产环境在 app.py 中创建后，通过 set_evaluate_js 注入实际函数。
    """

    def __init__(
        self,
        ascii_loader: Optional[AsciiArtLoader] = None,
        pet_admin=None,  # DesktopPetAdministrator 实例（避免循环依赖，用 Any）
        storage=None,
    ) -> None:
        self.ascii_loader = ascii_loader or AsciiArtLoader()
        self.pet_admin = pet_admin
        self.storage = storage
        self._evaluate_js: Optional[Callable[[str], Any]] = None
        self._state_history: list[PetState] = []

    def set_evaluate_js(self, fn: Callable[[str], Any]) -> None:
        """注入 evaluate_js 函数（生产环境用 webview.windows[0].evaluate_js）。"""
        self._evaluate_js = fn

    def _call_js(self, js_code: str) -> None:
        """安全调用 evaluate_js（无 pywebview 时静默）。"""
        if self._evaluate_js is not None:
            try:
                self._evaluate_js(js_code)
            except Exception as e:
                logger.warning(f"evaluate_js 调用失败: {e}")

    def notify_state_change(self, state: PetState, payload: Optional[dict] = None) -> None:
        """通知 JS 状态变更。"""
        self._state_history.append(state)
        payload_str = json.dumps(payload or {}, ensure_ascii=False)
        # 转义单引号
        payload_str = payload_str.replace("'", "\\'")
        self._call_js(f"updateState('{state.value}', '{payload_str}')")

    def notify_token(self, chunk: str) -> None:
        """推送流式 token 给 JS。"""
        # JSON 编码避免特殊字符破坏 JS 字符串
        chunk_json = json.dumps(chunk, ensure_ascii=False)
        self._call_js(f"appendAnswer({chunk_json})")

    def notify_citations(self, citations: list[dict]) -> None:
        """推送引用溯源给 JS。"""
        cits_json = json.dumps(citations, ensure_ascii=False)
        self._call_js(f"showCitations({cits_json})")

    # ==== pywebview JSBridge 暴露方法（JS 通过 window.pywebview.api.X 调用） ====

    def get_pet_info(self) -> dict:
        """获取宠物信息（JS 启动时调用）。"""
        if self.pet_admin and self.pet_admin.pet:
            pet = self.pet_admin.pet
            return {
                "name": pet.name,
                "branch": pet.branch or "scholar",
                "level": pet.level,
                "exp": pet.exp,
            }
        return {"name": "未领养", "branch": "none", "level": 1, "exp": 0}

    def get_ascii(self, state: str) -> str:
        """获取指定状态的 ASCII 艺术（向后兼容，已切换为 GIF 动画）。

        Returns:
            空字符串（GIF 切换在 JS 端通过 setCatGif(state) 完成）。
        """
        return ""

    def ask(self, question: str) -> str:
        """JS 调用：快速问答（同步返回完整答案）。"""
        if not self.pet_admin:
            return "宠物管理员未初始化"
        try:
            result = self.pet_admin.ask(question)
            # 推送引用溯源
            citations = [
                {
                    "marker": c.marker,
                    "title": c.title,
                    "paragraph_num": c.paragraph_num,
                    "doc_id": c.doc_id,
                }
                for c in result.citations
            ]
            self.notify_citations(citations)
            return result.text
        except Exception as e:
            logger.error(f"ask 失败: {e}")
            self.notify_state_change(PetState.ERROR)
            return f"出错：{e}"

    def ask_stream(self, question: str) -> dict:
        """JS 调用：流式问答（非生成器，避免 pywebview JSON 序列化失败）。

        内部消费 ``pet_admin.ask_stream()`` 生成器，每 token 通过
        ``evaluate_js`` 实时推回 JS（``notify_token``），引用溯源在
        ``done`` 事件时推送。

        Returns:
            ``{"success": bool, "text": str, "error": str}``
        """
        if not self.pet_admin:
            return {"success": False, "error": "宠物管理员未初始化"}

        full_text = ""
        try:
            for event in self.pet_admin.ask_stream(question):
                evt_type = event.get("type")
                if evt_type == "token":
                    chunk = event.get("text", "")
                    full_text += chunk
                    self.notify_token(chunk)
                elif evt_type == "stage":
                    stage = event.get("stage", "")
                    if "检索" in stage or "retriev" in stage.lower():
                        self.notify_state_change(PetState.RETRIEVING)
                    elif "重排" in stage or "rank" in stage.lower():
                        self.notify_state_change(PetState.RANKING)
                    elif "生成" in stage or "回答" in stage or "answer" in stage.lower():
                        self.notify_state_change(PetState.ANSWERING)
                elif evt_type == "done":
                    result = event.get("result")
                    if result and result.citations:
                        citations = [
                            {
                                "marker": c.marker,
                                "title": c.title,
                                "paragraph_num": c.paragraph_num,
                                "doc_id": c.doc_id,
                            }
                            for c in result.citations
                        ]
                        self.notify_citations(citations)

            # 完成后切到 celebrating，2 秒后回 idle
            self.notify_state_change(PetState.CELEBRATING)
            threading.Timer(2.0, lambda: self.notify_state_change(PetState.IDLE)).start()

            return {"success": True, "text": full_text}

        except Exception as e:
            logger.error(f"ask_stream 失败: {e}")
            self.notify_state_change(PetState.ERROR)
            return {"success": False, "error": str(e)}

    def ingest(self, file_path: str) -> dict:
        """JS 调用：拖拽入库（Task 1 修复）。

        流程：
        1. 解析 ``file://`` 前缀并 URL 解码。
        2. 通知 JS 进入 ``ingesting`` 状态（携带文件名）。
        3. 调用 ``ingest_helper.ingest_file`` 复用 ``run._ingest_one`` 入库。
        4. 成功 → ``celebrating`` + 气泡提示；失败 → ``error`` + 气泡提示。
        5. 等待 2 秒后回到 ``idle``，使用 ``threading.Timer`` 避免阻塞 pywebview 线程。

        Returns:
            ``{success, error, file_name, doc_id}``
        """
        from pathlib import Path

        from core.desktop.ingest_helper import ingest_file

        # 解析 file:// 前缀并 URL 解码
        cleaned_path = unquote(file_path)
        if cleaned_path.startswith("file://"):
            cleaned_path = cleaned_path[7:]

        # 通知 JS 进入 ingesting 状态
        self.notify_state_change(PetState.INGESTING, {"name": Path(cleaned_path).name})

        result = ingest_file(cleaned_path, storage=self.storage)

        if result.get("success"):
            file_name = result.get("file_name", "")
            err = result.get("error")
            if err == "already_exists":
                # 文件已入库，给用户友好提示但状态仍是 celebrating
                self.notify_state_change(
                    PetState.CELEBRATING, {"name": file_name, "exists": True}
                )
                self._call_js(f"showBubble('已存在：{file_name}')")
            else:
                self.notify_state_change(
                    PetState.CELEBRATING, {"name": file_name}
                )
                self._call_js(f"showBubble('已入库：{file_name}')")
        else:
            self.notify_state_change(PetState.ERROR, {"error": result.get("error")})
            err = result.get("error", "")
            # 简化错误提示，避免气泡内换行/截断
            short_err = err
            if "文件不存在" in err:
                short_err = f"找不到文件：{Path(cleaned_path).name}"
            elif len(err) > 60:
                short_err = err[:57] + "..."
            self._call_js(f"showBubble('失败：{short_err}')")

        # 2 秒后回到 idle，让用户看清 celebrating/error 状态
        threading.Timer(2.0, lambda: self.notify_state_change(PetState.IDLE)).start()

        return result

    def set_state(self, state: str) -> bool:
        """手动切换宠物状态（供托盘菜单 / IPC / CLI 调用）。

        Args:
            state: 状态名（idle/listening/thinking/retrieving/ranking/
                   answering/celebrating/error/sleeping/ingesting/
                   analyzing/notifying）

        Returns:
            True 表示切换成功；False 表示状态名无效。
        """
        try:
            pet_state = PetState(state)
        except (ValueError, KeyError):
            valid = [s.value for s in PetState]
            logger.warning(f"无效状态 '{state}'，可选: {valid}")
            return False

        # 通知 JS 切换 GIF + 状态显示
        self._call_js(f"setCatGif('{state}')")
        self.notify_state_change(pet_state)

        # 事件态（celebrating/error/notifying）2 秒后自动回 idle
        event_states = {
            PetState.CELEBRATING, PetState.ERROR, PetState.NOTIFYING
        }
        if pet_state in event_states:
            threading.Timer(2.0, lambda: self.notify_state_change(PetState.IDLE)).start()

        return True

    def switch_style(self, style: str) -> bool:
        """JS 调用：切换人格。"""
        if self.pet_admin and self.pet_admin.pet:
            try:
                self.pet_admin.pet.branch = style
                self._call_js(f"updatePetStyle('{style}')")
                return True
            except Exception as e:
                logger.error(f"switch_style 失败: {e}")
        return False

    def get_stats(self) -> dict:
        """JS 调用：获取知识库统计。"""
        if self.storage:
            try:
                docs = self.storage.list_documents()
                return {
                    "total_docs": len(docs),
                    "total_chunks": sum(d.chunk_count for d in docs),
                }
            except Exception:
                pass
        return {"total_docs": 0, "total_chunks": 0}

    def show_doc(self, doc_id: str) -> bool:
        """JS 调用：在新终端执行 ima show <doc_id>。

        优先级：
        1. ``sys.executable -m run show <doc_id>``（最可靠，不依赖 PATH）
        2. ``ima show <doc_id>``（兜底，需 pip install -e .）
        """
        try:
            # 优先用当前 Python 解释器直接跑 run 模块，避免依赖 PATH 中的 ima 命令
            subprocess.Popen([sys.executable, "-m", "run", "show", doc_id])
            return True
        except Exception as e:
            logger.warning(f"sys.executable -m run 启动失败，回退到 ima: {e}")
            try:
                subprocess.Popen(["ima", "show", doc_id])
                return True
            except Exception as e2:
                logger.error(f"show_doc 失败（两种方式都失败）: {e2}")
                return False
