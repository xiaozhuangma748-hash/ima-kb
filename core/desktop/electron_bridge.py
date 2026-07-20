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
    """配置日志（basicConfig，幂等）。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
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

        try:
            for event in self._pet_admin.ask_stream(question, history=history):
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
