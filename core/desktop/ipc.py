"""桌面宠物 IPC 通信（Unix domain socket）。

设计目的：
- macOS 上 pystray 的 AppKit 后端与 pywebview 的 NSApplication 冲突，
  托盘必须在独立进程中运行。IPC 让独立托盘进程能驱动主 pywebview 进程。
- CLI（``ima pet-state <state>``）也需要向运行中的桌宠发送状态变更。

协议：
- 传输层：Unix domain socket（``/tmp/ima-desktop-pet.sock``）
- 消息格式：每行一个 JSON 对象（``\\n`` 分隔）
- 请求：``{"action": "set_state", "state": "thinking"}``
- 响应：``{"success": true, "data": {...}}``

零侵入约束：
- 本模块属于 ``core/desktop/`` 新增模块，不修改项目任何现有文件。
"""
from __future__ import annotations

import json
import logging
import os
import socket
import threading
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

SOCKET_PATH = "/tmp/ima-desktop-pet.sock"


class IpcServer:
    """IPC 服务端（在主 pywebview 进程中运行）。

    监听 Unix domain socket，接收 JSON 命令，转发给 ``bridge`` 执行。
    """

    def __init__(self, bridge=None) -> None:
        self._bridge = bridge
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self) -> None:
        """启动 IPC 服务（非阻塞，在独立线程中监听）。"""
        # 清理残留 socket 文件
        try:
            if os.path.exists(SOCKET_PATH):
                os.unlink(SOCKET_PATH)
        except Exception:
            pass

        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(SOCKET_PATH)
        self._sock.listen(5)
        self._sock.settimeout(0.5)
        self._running = True

        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()
        logger.info(f"IPC 服务已启动: {SOCKET_PATH}")

    def stop(self) -> None:
        """停止 IPC 服务。"""
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        try:
            if os.path.exists(SOCKET_PATH):
                os.unlink(SOCKET_PATH)
        except Exception:
            pass
        logger.info("IPC 服务已停止")

    def _accept_loop(self) -> None:
        """接受连接循环。"""
        while self._running and self._sock:
            try:
                conn, _ = self._sock.accept()
                threading.Thread(
                    target=self._handle_client, args=(conn,), daemon=True
                ).start()
            except socket.timeout:
                continue
            except OSError:
                break

    def _handle_client(self, conn: socket.socket) -> None:
        """处理单个客户端连接，支持单响应与多响应（流式）列表。"""
        try:
            # ask_stream 可能包含 LLM 生成，timeout 需要覆盖长请求
            conn.settimeout(60)
            buf = b""
            while True:
                data = conn.recv(4096)
                if not data:
                    break
                buf += data
                # 按行处理
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if line.strip():
                        result = self._process(json.loads(line))
                        # _process 可返回 dict / list[dict] / generator；
                        # generator 用于 ask_stream 边生成边推送
                        if hasattr(result, "__iter__") and not isinstance(result, (dict, list)):
                            for response in result:
                                conn.sendall((json.dumps(response, ensure_ascii=False) + "\n").encode())
                        else:
                            responses = result if isinstance(result, list) else [result]
                            for response in responses:
                                conn.sendall((json.dumps(response, ensure_ascii=False) + "\n").encode())
        except Exception as e:
            logger.warning(f"IPC 客户端处理异常: {e}")
        finally:
            conn.close()

    def _process(self, request: dict) -> dict:
        """处理单条 JSON 请求，返回响应 dict。"""
        action = request.get("action", "")
        try:
            if action == "set_state":
                state = request.get("state", "")
                if self._bridge:
                    ok = self._bridge.set_state(state)
                    return {"success": ok, "state": state}
                return {"success": False, "error": "bridge 未初始化"}

            elif action == "get_pet_info":
                if self._bridge:
                    return {"success": True, "data": self._bridge.get_pet_info()}
                return {"success": False, "error": "bridge 未初始化"}

            elif action == "get_stats":
                if self._bridge:
                    return {"success": True, "data": self._bridge.get_stats()}
                return {"success": False, "error": "bridge 未初始化"}

            elif action == "show_bubble":
                msg = request.get("message", "")
                if self._bridge:
                    escaped = msg.replace("'", "\\'")
                    self._bridge._call_js(f"showBubble('{escaped}')")
                    return {"success": True}
                return {"success": False, "error": "bridge 未初始化"}

            elif action == "switch_style":
                style = request.get("style", "")
                if self._bridge:
                    ok = self._bridge.switch_style(style)
                    return {"success": ok, "style": style}
                return {"success": False, "error": "bridge 未初始化"}

            elif action == "ping":
                return {"success": True, "data": "pong"}

            else:
                return {"success": False, "error": f"未知 action: {action}"}

        except Exception as e:
            logger.error(f"IPC 处理失败 (action={action}): {e}")
            return {"success": False, "error": str(e)}


class IpcClient:
    """IPC 客户端（供托盘进程 / CLI 使用）。

    连接到运行中的桌宠主进程，发送 JSON 命令。
    """

    def __init__(self, socket_path: str = SOCKET_PATH) -> None:
        self._socket_path = socket_path

    def is_server_running(self) -> bool:
        """检查桌宠主进程是否在运行（socket 是否存在且可连接）。"""
        if not os.path.exists(self._socket_path):
            return False
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(1)
            sock.connect(self._socket_path)
            sock.sendall(b'{"action":"ping"}\n')
            resp = sock.recv(4096)
            sock.close()
            data = json.loads(resp.strip())
            return data.get("success", False)
        except Exception:
            return False

    def send(self, action: str, **kwargs) -> dict:
        """发送命令到桌宠主进程。

        Args:
            action: 命令名（set_state / get_pet_info / get_stats /
                    show_bubble / switch_style / ping）
            **kwargs: 命令参数

        Returns:
            响应 dict（``{"success": bool, ...}``）

        Raises:
            ConnectionError: 桌宠主进程未运行
        """
        if not os.path.exists(self._socket_path):
            raise ConnectionError("桌宠未运行（socket 文件不存在）")

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(5)
        try:
            sock.connect(self._socket_path)
            request = json.dumps({"action": action, **kwargs}, ensure_ascii=False)
            sock.sendall((request + "\n").encode())
            response = sock.recv(8192)
            return json.loads(response.strip())
        finally:
            sock.close()

    def set_state(self, state: str) -> bool:
        """便捷方法：切换宠物状态。"""
        result = self.send("set_state", state=state)
        return result.get("success", False)

    def show_bubble(self, message: str) -> bool:
        """便捷方法：显示气泡消息。"""
        result = self.send("show_bubble", message=message)
        return result.get("success", False)

    def get_pet_info(self) -> dict:
        """便捷方法：获取宠物信息。"""
        result = self.send("get_pet_info")
        return result.get("data", {})

    def get_stats(self) -> dict:
        """便捷方法：获取知识库统计。"""
        result = self.send("get_stats")
        return result.get("data", {})
