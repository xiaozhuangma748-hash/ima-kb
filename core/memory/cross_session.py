"""跨会话记忆：持久化用户偏好、关注主题、未解决问题和关键事实。"""
from __future__ import annotations

import copy
import json
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import settings

logger = logging.getLogger(__name__)


# 默认记忆结构
DEFAULT_CROSS_SESSION: Dict[str, Any] = {
    "preferences": {},
    "topics": [],
    "unresolved_questions": [],
    "key_facts": [],
    "last_updated": None,
}


class CrossSessionMemory:
    """跨会话记忆存储。

    记忆文件路径: storage/memory/cross_session.json
    """

    def __init__(self, storage_path: Optional[Path] = None) -> None:
        if storage_path is None:
            storage_path = settings.storage_path / "memory"
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.file_path = self.storage_path / "cross_session.json"
        self._data: Dict[str, Any] = copy.deepcopy(DEFAULT_CROSS_SESSION)
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> Dict[str, Any]:
        """加载 JSON，损坏则返回默认值。"""
        if not self.file_path.exists():
            self._data = copy.deepcopy(DEFAULT_CROSS_SESSION)
            return self._data
        try:
            raw = json.loads(self.file_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError(f"顶层数据类型错误: {type(raw).__name__}")
            self._data = raw
            # 确保所有字段存在且类型正确
            if not isinstance(self._data.get("preferences"), dict):
                self._data["preferences"] = {}
            for list_key in ("topics", "unresolved_questions", "key_facts"):
                if not isinstance(self._data.get(list_key), list):
                    self._data[list_key] = []
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            bak = self.file_path.parent / f"{self.file_path.name}.bak.{int(time.time())}"
            try:
                self.file_path.rename(bak)
                logger.warning(f"跨会话记忆文件损坏，已备份到 {bak}: {e}")
            except OSError:
                pass
            self._data = copy.deepcopy(DEFAULT_CROSS_SESSION)
        return self._data

    def _save(self) -> None:
        """保存 JSON，更新 last_updated（原子写入）。"""
        self._data["last_updated"] = datetime.now().isoformat()
        tmp_path = self.file_path.with_suffix(".json.tmp")
        try:
            tmp_path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(str(tmp_path), str(self.file_path))
        except OSError as e:
            logger.error(f"跨会话记忆保存失败: {e}")
            # 清理临时文件
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass

    def get_context(self) -> str:
        """返回格式化上下文文本。"""
        sections: List[str] = []

        # 用户偏好
        prefs = self._data.get("preferences", {})
        if prefs:
            lines = [f"- {k}: {v}" for k, v in prefs.items()]
            sections.append("【用户偏好】\n" + "\n".join(lines))
        else:
            sections.append("【用户偏好】")

        # 关注主题
        topics = self._data.get("topics", [])
        if topics:
            lines = [f"- {t}" for t in topics]
            sections.append("【关注主题】\n" + "\n".join(lines))
        else:
            sections.append("【关注主题】")

        # 未解决问题
        questions = self._data.get("unresolved_questions", [])
        if questions:
            lines = [f"- {q}" for q in questions]
            sections.append("【未解决问题】\n" + "\n".join(lines))
        else:
            sections.append("【未解决问题】")

        # 关键事实
        facts = self._data.get("key_facts", [])
        if facts:
            lines = [f"- {f}" for f in facts]
            sections.append("【关键事实】\n" + "\n".join(lines))
        else:
            sections.append("【关键事实】")

        return "\n\n".join(sections)

    def save_preference(self, key: str, value: str) -> None:
        """保存用户偏好。"""
        if not key or not key.strip():
            return
        with self._lock:
            self._data["preferences"][key.strip()] = value
            self._save()

    def add_topic(self, topic: str) -> None:
        """添加关注主题（去重）。"""
        topic = topic.strip()
        if not topic:
            return
        with self._lock:
            topics = self._data["topics"]
            if topic not in topics:
                topics.append(topic)
                self._save()

    def remove_topic(self, topic: str) -> None:
        """移除关注主题。"""
        topic = topic.strip()
        if not topic:
            return
        with self._lock:
            topics = self._data["topics"]
            if topic in topics:
                topics.remove(topic)
                self._save()

    def add_unresolved_question(self, question: str) -> None:
        """添加未解决问题（去重）。"""
        question = question.strip()
        if not question:
            return
        with self._lock:
            questions = self._data["unresolved_questions"]
            if question not in questions:
                questions.append(question)
                self._save()

    def add_key_fact(self, fact: str) -> None:
        """添加关键事实（去重）。"""
        fact = fact.strip()
        if not fact:
            return
        with self._lock:
            facts = self._data["key_facts"]
            if fact not in facts:
                facts.append(fact)
                self._save()

    def clear_all(self) -> None:
        """清空所有记忆。"""
        with self._lock:
            self._data = copy.deepcopy(DEFAULT_CROSS_SESSION)
            self._save()

    def merge_extraction(
        self,
        preferences: Optional[Dict[str, str]] = None,
        topics: Optional[List[str]] = None,
        questions: Optional[List[str]] = None,
        facts: Optional[List[str]] = None,
    ) -> Dict[str, List[str]]:
        """合并自动提取的记忆（去重），返回新增项清单。

        用于自动提取场景：LLM 提取出记忆后调用此方法合并到现有记忆。
        所有写入都做去重处理，已存在的项不会重复添加。

        Args:
            preferences: 偏好字典（key → value），按 key 覆盖
            topics: 关注主题列表
            questions: 未解决问题列表
            facts: 关键事实列表

        Returns:
            新增项清单，格式：
            {
                "preferences": ["键:值", ...],  # 新增的偏好（key 改动也算）
                "topics": [...],                # 新增的主题
                "questions": [...],             # 新增的问题
                "facts": [...],                 # 新增的事实
            }
        """
        added: Dict[str, List[str]] = {
            "preferences": [],
            "topics": [],
            "questions": [],
            "facts": [],
        }

        with self._lock:
            changed = False
            # 偏好：按 key 覆盖，记录改动
            if preferences:
                for k, v in preferences.items():
                    k = k.strip()
                    v = v.strip() if isinstance(v, str) else str(v)
                    if not k:
                        continue
                    old = self._data["preferences"].get(k)
                    if old != v:
                        self._data["preferences"][k] = v
                        added["preferences"].append(f"{k}:{v}")
                        changed = True

            # 主题：去重添加
            if topics:
                for t in topics:
                    t = t.strip() if isinstance(t, str) else str(t)
                    if not t or t in self._data["topics"]:
                        continue
                    self._data["topics"].append(t)
                    added["topics"].append(t)
                    changed = True

            # 问题：去重添加
            if questions:
                for q in questions:
                    q = q.strip() if isinstance(q, str) else str(q)
                    if not q or q in self._data["unresolved_questions"]:
                        continue
                    self._data["unresolved_questions"].append(q)
                    added["questions"].append(q)
                    changed = True

            # 事实：去重添加
            if facts:
                for f in facts:
                    f = f.strip() if isinstance(f, str) else str(f)
                    if not f or f in self._data["key_facts"]:
                        continue
                    self._data["key_facts"].append(f)
                    added["facts"].append(f)
                    changed = True

            if changed:
                self._save()

        return added
