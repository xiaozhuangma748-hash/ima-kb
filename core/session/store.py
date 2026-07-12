"""会话持久化：保存/恢复/导出对话历史。

用法：
    from core.session.store import SessionStore
    ss = SessionStore()
    ss.save("topic_name", history)      # 保存
    sessions = ss.list_sessions()       # 列出
    history = ss.load("topic_name")     # 恢复
    ss.export("topic_name", "out.md")   # 导出 Markdown
    ss.delete("topic_name")             # 删除
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class SessionStore:
    """会话存储（JSON 文件持久化）。"""

    def __init__(self, storage_dir: Optional[Path] = None) -> None:
        if storage_dir is None:
            storage_dir = Path("storage/sessions")
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _safe_name(self, name: str) -> str:
        """把会话名转成安全的文件名。"""
        import re
        safe = re.sub(r'[^\w\u4e00-\u9fa5\-]', '_', name.strip())
        return safe or "untitled"

    def _path(self, name: str) -> Path:
        return self.storage_dir / f"{self._safe_name(name)}.json"

    # ---- 活跃会话 ----

    ACTIVE_SESSION_FILE = "active_session.json"

    def _active_path(self) -> Path:
        return self.storage_dir / self.ACTIVE_SESSION_FILE

    def create_session(self, name: Optional[str] = None) -> str:
        """创建新会话，设为活跃会话，返回会话名。"""
        if name is None:
            name = f"会话_{datetime.now().strftime('%m%d_%H%M')}"
        safe_name = self._safe_name(name)
        path = self.storage_dir / f"{safe_name}.json"
        data = {
            "name": name,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "message_count": 0,
            "meta": {},
            "history": [],
        }
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        # 设为活跃会话
        active = {
            "name": name,
            "safe_name": safe_name,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        self._active_path().write_text(
            json.dumps(active, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return name

    def get_active_session(self) -> Optional[str]:
        """获取活跃会话名，不存在返回 None。"""
        if not self._active_path().exists():
            return None
        try:
            data = json.loads(self._active_path().read_text(encoding="utf-8"))
            return data.get("name")
        except Exception:
            return None

    def save_active_session(self, name: str) -> None:
        """更新活跃会话记录。"""
        active = {
            "name": name,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        self._active_path().write_text(
            json.dumps(active, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ---- 增删改查 ----

    def save(self, name: str, history: List[Dict[str, Any]],
             meta: Optional[Dict[str, Any]] = None) -> Path:
        """保存会话。

        Args:
            name: 会话名（可中文）
            history: 对话历史 [{role, content}, ...]
            meta: 元信息（如文档数、tag 等）
        Returns:
            保存的文件路径
        """
        data = {
            "name": name,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "message_count": len(history),
            "meta": meta or {},
            "history": history,
        }
        path = self._path(name)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def load(self, name: str) -> Optional[List[Dict[str, Any]]]:
        """加载会话。返回 history 列表，不存在返回 None。"""
        path = self._path(name)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data.get("history", [])
        except Exception:
            return None

    def list_sessions(self) -> List[Dict[str, Any]]:
        """列出所有已保存的会话。按保存时间倒序。"""
        sessions = []
        for f in self.storage_dir.glob("*.json"):
            # 排除活跃会话记录文件（它不是真正的会话存档）
            if f.name == self.ACTIVE_SESSION_FILE:
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                sessions.append({
                    "name": data.get("name", f.stem),
                    "saved_at": data.get("saved_at", ""),
                    "message_count": data.get("message_count", 0),
                    "meta": data.get("meta", {}),
                    "file": f.name,
                })
            except Exception:
                continue
        sessions.sort(key=lambda x: x["saved_at"], reverse=True)
        return sessions

    def delete(self, name: str) -> bool:
        """删除会话。返回是否删除成功。"""
        path = self._path(name)
        if path.exists():
            path.unlink()
            return True
        return False

    def get_meta(self, name: str) -> Optional[Dict[str, Any]]:
        """获取会话元信息。"""
        path = self._path(name)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return {
                "name": data.get("name", ""),
                "saved_at": data.get("saved_at", ""),
                "message_count": data.get("message_count", 0),
                "meta": data.get("meta", {}),
            }
        except Exception:
            return None

    # ---- 导出 ----

    def export_markdown(self, name: str, output_path: Optional[Path] = None) -> Path:
        """把会话导出为 Markdown 文件。

        Args:
            name: 会话名
            output_path: 输出路径（None 则导出到 storage/sessions/<name>.md）
        Returns:
            导出文件路径
        """
        history = self.load(name)
        if history is None:
            raise FileNotFoundError(f"会话不存在: {name}")

        meta = self.get_meta(name) or {}
        if output_path is None:
            output_path = self.storage_dir / f"{self._safe_name(name)}.md"

        lines = [
            f"# 对话记录：{name}",
            "",
            f"- 保存时间：{meta.get('saved_at', '')}",
            f"- 消息数：{meta.get('message_count', len(history))}",
            "",
            "---",
            "",
        ]
        for msg in history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "user":
                lines.append(f"## 🧑 用户")
                lines.append("")
                lines.append(content)
                lines.append("")
            elif role == "assistant":
                lines.append(f"## 🤖 AI")
                lines.append("")
                lines.append(content)
                lines.append("")
            elif role == "system":
                lines.append(f"_系统: {content}_")
                lines.append("")
            lines.append("---")
            lines.append("")

        output_path.write_text("\n".join(lines), encoding="utf-8")
        return output_path

    def export_json(self, name: str, output_path: Optional[Path] = None) -> Path:
        """导出为 JSON（含完整元信息）。"""
        path = self._path(name)
        if not path.exists():
            raise FileNotFoundError(f"会话不存在: {name}")
        if output_path is None:
            output_path = self.storage_dir / f"{self._safe_name(name)}.json"
        output_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        return output_path
