"""Electron 桌面宠物 Python 后端入口。

不启动 pywebview GUI，仅初始化 PetAdministrator 与 IpcServer，
供 Electron 主进程通过 Unix domain socket 驱动。

零侵入约束：
- 本模块属于 ``core/desktop/`` 新增模块，不修改项目任何现有文件。
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time

# 中国大陆镜像：向量模型下载前必须设置
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

from core.desktop.ipc import IpcServer, SOCKET_PATH

logger = logging.getLogger(__name__)


def _create_pet_administrator():
    """创建并返回 PetAdministrator 实例（参考 app._create_pet_administrator）。"""
    try:
        from core.pet.storage import PetStorage
        from core.storage import Storage
        from core.memory.store import MemoryStore
        from core.retrieval.hybrid import HybridRetriever
        from core.retrieval.rerank import Reranker
        from core.llm.client import get_llm
        from core.pet.administrator import PetAdministrator

        pet_storage = PetStorage()
        pet = pet_storage.load()
        if not pet:
            return None

        storage = Storage()
        memory = MemoryStore()

        vector_index = None
        try:
            from core.retrieval.vector import VectorIndex
            vector_index = VectorIndex()
        except Exception as e:
            logger.info(f"VectorIndex 不可用，降级为纯 BM25: {e}")

        hybrid = HybridRetriever(
            bm25_index=storage.bm25,
            vector_index=vector_index,
            storage=storage,
        )
        llm = get_llm()
        reranker = Reranker(llm)

        return PetAdministrator(
            pet=pet, storage=storage, memory_store=memory,
            hybrid_retriever=hybrid, reranker=reranker, llm=llm,
        )
    except Exception as e:
        logger.error(f"创建 PetAdministrator 失败: {e}")
        return None


def _setup_logging() -> None:
    """配置日志(basicConfig,幂等)。

    安全:强制输出到 stderr,避免与 stdout 的 JSON 协议混合
    (Electron 主进程解析 stdout 的 JSON 行,日志混入会导致 JSON.parse 失败)。
    """
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


class ElectronIpcServer(IpcServer):
    """Electron 专用 IPC 服务端。

    复用 ``IpcServer`` 的 socket 基础设施，但用自定义 ``_process``
    直接操作 ``PetAdministrator``，不依赖 pywebview Bridge。
    """

    def __init__(self, pet_admin, storage) -> None:
        # 父类要求 bridge，Electron 场景下不需要，传 None
        super().__init__(bridge=None)
        self._pet_admin = pet_admin
        self._storage = storage

    def _process(self, request: dict):
        """处理单条 JSON 请求；ask_stream 返回 list 实现流式事件。"""
        action = request.get("action", "")
        try:
            if action == "ask_stream":
                return self._handle_ask_stream(request)
            if action == "ingest":
                return self._handle_ingest(request)
            if action == "get_pet_info":
                return self._handle_get_pet_info()
            if action == "get_stats":
                return self._handle_get_stats()
            if action == "show_doc":
                return self._handle_show_doc(request)
            if action == "ping":
                return {"success": True, "data": "pong"}
            if action == "push_content":
                return self._handle_push_content(request)
            if action == "push_token":
                return self._handle_push_token(request)
            if action == "push_done":
                return self._handle_push_done(request)
            if action == "push_stage":
                return self._handle_push_stage(request)
            if action == "set_state":
                return self._handle_set_state(request)
            if action == "exec_cli_command":
                return self._handle_exec_cli_command(request)
            return {"success": False, "error": f"未知 action: {action}"}
        except Exception as e:
            logger.error(f"IPC 处理失败 (action={action}): {e}")
            return {"success": False, "error": str(e)}

    def _handle_ask_stream(self, request: dict):
        """消费 PetAdministrator.ask_stream，边生成边推送给前端。"""
        if not self._pet_admin:
            yield {"success": False, "error": "宠物管理员未初始化"}
            return

        question = request.get("question", "")
        history = request.get("history") or []
        citations = []

        # 桌面宠物气泡场景：简洁模式，限制长度，禁用表格
        compact_prompt = (
            "你在桌面宠物的小气泡中回答，显示空间非常有限（约 190px 宽）。\n"
            "请遵守：\n"
            "1. 回答简洁，直接给结论，总长度不超过 200 字\n"
            "2. 不要使用 Markdown 表格（太宽会溢出）\n"
            "3. 用简短的列表或分点说明，每点不超过 30 字\n"
            "4. 省略寒暄和重复问题\n"
            "5. 关键事实保留 [n] 引用标记"
        )

        try:
            for event in self._pet_admin.ask_stream(
                question,
                history=history,
                max_tokens=512,
                extra_system_prompt=compact_prompt,
            ):
                etype = event.get("type")
                if etype == "token":
                    yield {"type": "token", "chunk": event.get("text", "")}
                elif etype == "stage":
                    yield {
                        "type": "stage",
                        "stage": event.get("stage", ""),
                        "count": event.get("count", 0),
                    }
                elif etype == "source_count":
                    yield {
                        "type": "source_count",
                        "count": event.get("count", 0),
                    }
                elif etype == "done":
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
            yield {"type": "done", "success": True, "citations": citations}
        except Exception as e:
            logger.error(f"ask_stream 处理失败: {e}")
            yield {"type": "error", "success": False, "error": str(e)}

    def _handle_ingest(self, request: dict):
        """拖拽入库。"""
        from core.desktop.ingest_helper import ingest_file

        file_path = request.get("file_path", "")
        result = ingest_file(file_path, storage=self._storage)
        return {"success": True, "data": result}

    def _handle_get_pet_info(self):
        """获取宠物信息。"""
        if not self._pet_admin or not self._pet_admin.pet:
            return {"success": False, "error": "宠物未领养"}
        pet = self._pet_admin.pet
        return {
            "success": True,
            "data": {
                "name": pet.name,
                "branch": pet.branch or "scholar",
                "level": pet.level,
                "exp": pet.exp,
            },
        }

    def _handle_get_stats(self):
        """获取知识库统计。"""
        if not self._storage:
            return {"success": False, "error": "storage 未初始化"}
        try:
            docs = self._storage.list_documents()
            return {
                "success": True,
                "data": {
                    "total_docs": len(docs),
                    "total_chunks": sum(d.chunk_count for d in docs),
                },
            }
        except Exception as e:
            return {"success": False, "error": f"获取统计失败: {e}"}

    def _handle_show_doc(self, request: dict):
        """在新终端打开文档详情（复用 bridge.show_doc 逻辑）。"""
        doc_id = request.get("doc_id", "")
        try:
            subprocess.Popen([sys.executable, "-m", "run", "show", doc_id])
            return {"success": True}
        except Exception as e:
            logger.error(f"show_doc 失败: {e}")
            return {"success": False, "error": str(e)}

    def _handle_set_state(self, request: dict):
        """切换桌宠状态：通过 stdout 通知 Electron 主进程。"""
        state = request.get("state", "")
        valid_states = {
            "idle", "listening", "thinking", "retrieving", "ranking",
            "answering", "celebrating", "error", "sleeping",
            "ingesting", "analyzing", "notifying",
        }
        if state not in valid_states:
            return {"success": False, "error": f"无效状态: {state}"}
        # 通过 stdout 发送 JSON，Electron main.js 监听并调用 setState
        import json as json_module
        print(json_module.dumps({"type": "set_state", "state": state}), flush=True)
        return {"success": True, "state": state}

    def _handle_exec_cli_command(self, request: dict):
        """P4: 桌宠命令面板 — 轻量命令执行器。

        支持常用查询命令，直接调用 storage/pet_admin API，
        不需要启动完整 REPL。
        """
        cmd = request.get("command", "").strip()
        if not cmd:
            return {"success": False, "error": "命令为空"}

        # 去掉 / 前缀
        if cmd.startswith("/"):
            cmd = cmd[1:]

        parts = cmd.split(maxsplit=1)
        main_cmd = parts[0].lower()
        sub_arg = parts[1].strip() if len(parts) > 1 else ""

        # 命令别名（与 REPL CMD_ALIASES 保持一致）
        aliases = {
            "ls": "list", "s": "search", "st": "stats",
            "t": "todo", "m": "memory",
            "tag": "tags",
        }
        # help 输入容错：h/h/he/hel 都是 help
        if main_cmd in ("h", "he", "hel"):
            main_cmd = "help"
        # 其他未识别但可唯一前缀匹配的命令也允许
        if main_cmd not in {
            "list", "search", "stats", "tags", "todo", "memory",
            "help", "sessions", "session",
        }:
            candidates = [
                c for c in ("list", "search", "stats", "tags", "todo",
                            "memory", "help", "sessions")
                if c.startswith(main_cmd)
            ]
            if len(candidates) == 1:
                main_cmd = candidates[0]
            elif len(candidates) > 1:
                return {
                    "success": False,
                    "error": (
                        f"命令 /{main_cmd} 有歧义，匹配到多个: "
                        + "/".join(candidates)
                        + "\n请输入更明确的前缀"
                    ),
                }
        main_cmd = aliases.get(main_cmd, main_cmd)

        try:
            if main_cmd == "list":
                return self._exec_list()
            elif main_cmd == "search":
                return self._exec_search(sub_arg)
            elif main_cmd == "stats":
                return self._exec_stats()
            elif main_cmd == "tags":
                return self._exec_tags()
            elif main_cmd == "todo":
                return self._exec_todo(sub_arg)
            elif main_cmd == "memory":
                return self._exec_memory(sub_arg)
            elif main_cmd == "help":
                return self._exec_help()
            elif main_cmd in ("sessions", "session"):
                return self._exec_sessions()
            else:
                return {
                    "success": False,
                    "error": f"桌宠命令面板暂不支持 /{main_cmd}\n支持: /list /search /stats /tags /todo /memory /sessions /help",
                }
        except Exception as e:
            logger.error(f"exec_cli_command 失败 ({cmd}): {e}")
            return {"success": False, "error": str(e)}

    def _exec_list(self):
        """列出文档。"""
        docs = self._storage.list_documents(limit=50)
        if not docs:
            return {"success": True, "output": "知识库为空"}
        lines = [f"📋 知识库文档（共 {len(docs)} 条）"]
        for d in docs[:10]:
            tags = "、".join(d.tags) if d.tags else "-"
            lines.append(f"- **{d.title}** · {d.file_type} · {d.chunk_count}块 · {tags}")
        if len(docs) > 10:
            lines.append(f"... 还有 {len(docs) - 10} 条")
        return {"success": True, "output": "\n".join(lines)}

    def _exec_search(self, keyword: str):
        """搜索文档。"""
        if not keyword:
            return {"success": False, "error": "用法: /search <关键词>"}
        results = self._storage.bm25_search(keyword, top_k=5)
        if not results:
            return {"success": True, "output": f"未找到与 '{keyword}' 相关的内容"}
        lines = [f"🔍 搜索 '{keyword}' → {len(results)} 条结果"]
        for i, r in enumerate(results[:5], 1):
            preview = r.content[:80].replace("\n", " ")
            lines.append(f"{i}. **{r.doc_title}** ({r.score:.2f})")
            lines.append(f"   {preview}...")
        return {"success": True, "output": "\n".join(lines)}

    def _exec_stats(self):
        """统计信息。"""
        docs = self._storage.list_documents()
        total_chunks = sum(d.chunk_count for d in docs)
        total_tokens = sum(d.total_tokens for d in docs)
        lines = [
            f"📊 知识库统计",
            f"- 文档数: {len(docs)}",
            f"- 总分块: {total_chunks}",
            f"- 总 Tokens: {total_tokens}",
        ]
        if self._pet_admin and self._pet_admin.pet:
            pet = self._pet_admin.pet
            lines.append(f"- 宠物: {pet.name} (Lv.{pet.level})")
        return {"success": True, "output": "\n".join(lines)}

    def _exec_tags(self):
        """列出标签。"""
        tags = self._storage.list_all_tags()
        if not tags:
            return {"success": True, "output": "还没有标签"}
        lines = [f"🏷 所有标签（共 {len(tags)} 个）"]
        tag_items = list(tags.items())[:10]
        lines.append("、".join(f"{t}×{c}" for t, c in tag_items))
        if len(tags) > 10:
            lines.append(f"... 还有 {len(tags) - 10} 个")
        return {"success": True, "output": "\n".join(lines)}

    def _exec_todo(self, sub_arg: str):
        """任务列表。"""
        from core.todo.manager import TodoManager
        mgr = TodoManager()
        items = mgr.list_day()
        stats = mgr.stats_day()
        today = stats["date"]
        if not items:
            return {"success": True, "output": f"📋 今日任务 · {today}\n暂无任务"}
        lines = [f"📋 今日任务 · {today} ({stats['done']}/{stats['total']})"]
        for i, item in enumerate(items[:8], 1):
            mark = "✓" if item.status == "done" else "○" if item.status == "pending" else "✗"
            lines.append(f"{mark} {i}. {item.description}")
        if len(items) > 8:
            lines.append(f"... 还有 {len(items) - 8} 条")
        return {"success": True, "output": "\n".join(lines)}

    def _exec_memory(self, sub_arg: str):
        """记忆概览。"""
        from core.memory.store import MemoryStore
        store = MemoryStore()
        data = store.get_data()
        profile = data.get("profile", {})
        tasks = data.get("tasks", [])
        active = [t for t in tasks if t.get("status") != "completed"]
        lines = ["🧠 记忆概览"]
        lines.append(f"- 互动次数: {profile.get('interaction_count', 0)}")
        lines.append(f"- 关注主题: {', '.join(profile.get('focus_topics', [])[:3]) or '(无)'}")
        lines.append(f"- 任务: {len(active)} 个未完成 / 共 {len(tasks)} 个")
        return {"success": True, "output": "\n".join(lines)}

    def _exec_sessions(self):
        """会话列表。"""
        from core.session.store import SessionStore
        ss = SessionStore()
        sessions = ss.list_sessions()
        if not sessions:
            return {"success": True, "output": "暂无已保存的会话"}
        lines = [f"📋 已保存会话（共 {len(sessions)} 个）"]
        for s in sessions[:6]:
            lines.append(f"- **{s['name']}** · {s['message_count']}条 · {s['saved_at'][:10]}")
        if len(sessions) > 6:
            lines.append(f"... 还有 {len(sessions) - 6} 个")
        return {"success": True, "output": "\n".join(lines)}

    def _exec_help(self):
        """帮助。"""
        lines = [
            "📖 桌宠命令面板",
            "- /list — 列出文档",
            "- /search <关键词> — 搜索",
            "- /stats — 统计信息",
            "- /tags — 标签列表",
            "- /todo — 今日任务",
            "- /memory — 记忆概览",
            "- /sessions — 会话列表",
            "- /help — 帮助",
        ]
        return {"success": True, "output": "\n".join(lines)}

    def _handle_push_content(self, request: dict):
        """CLI 推送内容到桌面宠物（通过 stdout 通知 Electron 主进程转发）。"""
        import json as json_module
        content = request.get("content", "")
        msg_type = request.get("msg_type", "info")
        if not content:
            return {"success": False, "error": "content 为空"}
        # 通过 stdout 发送 JSON，Electron main.js 监听并转发给 renderer
        print(json_module.dumps({
            "type": "push_content",
            "content": content,
            "msg_type": msg_type,
        }), flush=True)
        return {"success": True}

    def _handle_push_token(self, request: dict):
        """CLI 流式 token 推送到桌面宠物气泡。"""
        import json as json_module
        text = request.get("text", "")
        if text:
            print(json_module.dumps({
                "type": "push_token",
                "text": text,
            }), flush=True)
        return {"success": True}

    def _handle_push_done(self, request: dict):
        """CLI 流式完成推送。"""
        import json as json_module
        print(json_module.dumps({
            "type": "push_done",
            "answer": request.get("answer", ""),
        }), flush=True)
        return {"success": True}

    def _handle_push_stage(self, request: dict):
        """CLI 阶段提示推送。"""
        import json as json_module
        print(json_module.dumps({
            "type": "push_stage",
            "stage": request.get("stage", ""),
            "count": request.get("count", 0),
        }), flush=True)
        return {"success": True}


def main() -> None:
    """Electron 后端主入口。"""
    _setup_logging()

    pet_admin = _create_pet_administrator()
    if pet_admin is None:
        print("请先在 REPL 中执行 /pet adopt 领养宠物")
        sys.exit(1)

    ipc = ElectronIpcServer(pet_admin=pet_admin, storage=pet_admin.storage)
    ipc.start()
    logger.info(f"Electron 桌宠后端已启动，socket: {SOCKET_PATH}")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("收到退出信号")
    finally:
        ipc.stop()
        logger.info("Electron 桌宠后端已退出")


if __name__ == "__main__":
    main()
