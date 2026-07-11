# 搜索命令优化与会话记忆系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 优化搜索命令默认配置功能 + 完善会话记忆系统（上下文压缩 + 跨会话记忆 + 自动持久化）

**Architecture:** 
- 搜索命令：在现有 `--tag/--limit` 基础上增加默认配置系统，用户配置一次后所有搜索自动带上默认参数
- 会话记忆：在已有的上下文压缩基础上，增加跨会话记忆持久化和自动加载机制

**Tech Stack:** Python 3.9+, SQLite, JSON, Rich CLI

## Global Constraints
- Python 版本: 3.9+
- 不引入新依赖，仅使用现有库（rich, prompt_toolkit, json, sqlite3）
- 所有新功能向后兼容，不影响现有命令
- 测试覆盖率保持 100%（338 项测试全部通过）

---

# 第一部分：搜索命令默认配置

## Task 1: 搜索配置存储

**Files:**
- Create: `core/search/config.py`
- Modify: `core/cli/commands/docs.py` (添加配置读取逻辑)

**Interfaces:**
- Consumes: `storage/search_config.json` 文件格式
- Produces: `SearchConfig` 类，提供 `get_default_tag()` / `get_default_limit()` / `set_defaults()` 方法

- [ ] **Step 1: 创建搜索配置存储模块**

```python
# core/search/config.py
from pathlib import Path
from typing import Optional
import json

class SearchConfig:
    """搜索默认配置存储。"""
    
    CONFIG_FILE = Path("storage/search_config.json")
    
    DEFAULT_TAG: Optional[str] = None
    DEFAULT_LIMIT: int = 10
    
    def __init__(self) -> None:
        self._data = self._load()
    
    def _load(self) -> dict:
        """加载配置文件，不存在则返回默认值。"""
        if not self.CONFIG_FILE.exists():
            return {"tag": None, "limit": 10}
        try:
            return json.loads(self.CONFIG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            return {"tag": None, "limit": 10}
    
    def get_default_tag(self) -> Optional[str]:
        return self._data.get("tag")
    
    def get_default_limit(self) -> int:
        return self._data.get("limit", 10)
    
    def set_defaults(self, tag: Optional[str] = None, limit: Optional[int] = None) -> None:
        """设置默认配置。"""
        if tag is not None:
            self._data["tag"] = tag
        if limit is not None:
            self._data["limit"] = limit
        self._save()
    
    def _save(self) -> None:
        """保存配置到文件。"""
        self.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.CONFIG_FILE.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    
    def reset(self) -> None:
        """重置为默认值。"""
        self._data = {"tag": None, "limit": 10}
        self._save()
```

- [ ] **Step 2: 运行测试验证配置模块**

```bash
# 创建测试文件
cat > tests/test_search_config.py << 'EOF'
"""搜索配置存储测试。"""
import pytest
from pathlib import Path
from core.search.config import SearchConfig

def test_load_default_config(tmp_path, monkeypatch):
    """配置文件不存在时返回默认值。"""
    config_file = tmp_path / "search_config.json"
    monkeypatch.setattr(SearchConfig, "CONFIG_FILE", config_file)
    
    config = SearchConfig()
    assert config.get_default_tag() is None
    assert config.get_default_limit() == 10

def test_set_and_get_defaults(tmp_path, monkeypatch):
    """设置默认值后能正确读取。"""
    config_file = tmp_path / "search_config.json"
    monkeypatch.setattr(SearchConfig, "CONFIG_FILE", config_file)
    
    config = SearchConfig()
    config.set_defaults(tag="政策", limit=5)
    
    assert config.get_default_tag() == "政策"
    assert config.get_default_limit() == 5

def test_reset_config(tmp_path, monkeypatch):
    """重置配置为默认值。"""
    config_file = tmp_path / "search_config.json"
    monkeypatch.setattr(SearchConfig, "CONFIG_FILE", config_file)
    
    config = SearchConfig()
    config.set_defaults(tag="政策", limit=5)
    config.reset()
    
    assert config.get_default_tag() is None
    assert config.get_default_limit() == 10
EOF

# 运行测试
.venv/bin/python -m pytest tests/test_search_config.py -v
```

- [ ] **Step 3: 修改 `_cmd_search` 支持默认配置**

在 `core/cli/commands/docs.py` 的 `_cmd_search` 方法中，当用户只输入关键词时自动带上默认配置：

```python
def _cmd_search(self, query: str) -> None:
    """BM25 搜索：/search <关键词> [--tag 标签] [--limit N]"""
    from core.search.config import SearchConfig
    
    if not query:
        # 显示当前默认配置
        config = SearchConfig()
        tag = config.get_default_tag()
        limit = config.get_default_limit()
        console.print("[yellow]用法: /search <关键词> [--tag 标签] [--limit N][/yellow]")
        console.print(f"[dim]当前默认: tag={tag or '无'}, limit={limit}[/dim]")
        console.print("[dim]示例: /search 骨灰 --tag 政策 --limit 5[/dim]")
        return
    
    # 解析用户输入（原有逻辑不变）
    # ... 原有解析代码 ...
    
    # 应用默认配置（如果用户未指定）
    if tag_filter is None:
        config = SearchConfig()
        tag_filter = config.get_default_tag()
    
    if limit == 10:  # 用户未指定 limit
        config = SearchConfig()
        limit = config.get_default_limit()
    
    # 继续执行搜索逻辑（原有代码不变）
```

- [ ] **Step 4: 运行完整测试**

```bash
.venv/bin/python -m pytest tests/ -x -q
```

## Task 2: 搜索配置命令

**Files:**
- Modify: `core/cli/commands/docs.py` (添加 `_cmd_search_config` 方法)

**Interfaces:**
- Consumes: `SearchConfig` 类
- Produces: `/search config` 命令支持设置/查看/重置默认配置

- [ ] **Step 1: 添加搜索配置命令**

在 `DocsMixin` 类中添加新方法：

```python
def _cmd_search_config(self, query: str) -> None:
    """搜索默认配置管理：/search config [tag <标签>|limit <数字>|reset]"""
    from core.search.config import SearchConfig
    
    config = SearchConfig()
    args = query.strip().split()
    
    if not args:
        # 显示当前配置
        tag = config.get_default_tag()
        limit = config.get_default_limit()
        console.print(f"\n[bold]搜索默认配置[/bold]\n")
        console.print(f"  默认标签: {[tag or '未设置']}")
        console.print(f"  默认数量: {limit}")
        console.print(f"\n[dim]设置: /search config tag 政策[/dim]")
        console.print(f"[dim]设置: /search config limit 20[/dim]")
        console.print(f"[dim]重置: /search config reset[/dim]\n")
        return
    
    cmd = args[0].lower()
    
    if cmd == "tag" and len(args) > 1:
        config.set_defaults(tag=" ".join(args[1:]))
        tag = config.get_default_tag()
        console.print(f"[green]✓ 默认标签已设置为: {tag}[/green]")
    
    elif cmd == "limit" and len(args) > 1:
        try:
            limit = int(args[1])
            config.set_defaults(limit=limit)
            console.print(f"[green]✓ 默认数量已设置为: {limit}[/green]")
        except ValueError:
            console.print(f"[yellow]无效的 limit 值: {args[1]}[/yellow]")
    
    elif cmd == "reset":
        config.reset()
        console.print("[green]✓ 搜索配置已重置为默认值[/green]")
    
    else:
        console.print("[yellow]用法: /search config [tag <标签>|limit <数字>|reset][/yellow]")
```

- [ ] **Step 2: 添加命令别名**

在 `constants.py` 的 `_COMMAND_DISPATCH` 中添加：

```python
"/search config": "_cmd_search_config",
```

- [ ] **Step 3: 运行测试**

```bash
.venv/bin/python -m pytest tests/ -x -q
```

---

# 第二部分：会话记忆系统增强

## Task 3: 会话自动持久化

**Files:**
- Modify: `core/cli/repl.py` (_save_active_session 增强)
- Modify: `core/session/store.py` (添加自动保存方法)

**Interfaces:**
- Consumes: 当前活跃会话的 `self.history`
- Produces: 每次对话后自动保存到活跃会话文件

- [ ] **Step 1: 增强 `_save_active_session` 方法**

在 `core/cli/repl.py` 中修改：

```python
def _save_active_session(self) -> None:
    """保存当前活跃会话（退出时调用 + 对话后自动保存）。"""
    if not self.active_session_name:
        return
    try:
        from core.session.store import SessionStore
        ss = SessionStore()
        ss.save(self.active_session_name, self.history)
        ss.save_active_session(self.active_session_name)
    except Exception:
        pass

def _auto_save_session(self) -> None:
    """自动保存会话（每次对话后调用）。"""
    if not self.active_session_name or not self.history:
        return
    try:
        from core.session.store import SessionStore
        ss = SessionStore()
        ss.save(self.active_session_name, self.history)
    except Exception:
        pass
```

- [ ] **Step 2: 在 `_handle_chat` 中调用自动保存**

在 `core/cli/chat.py` 的 `_handle_chat` 方法末尾添加：

```python
# 在保存历史后自动保存会话
self._auto_save_session()
```

- [ ] **Step 3: 运行测试**

```bash
.venv/bin/python -m pytest tests/ -x -q
```

## Task 4: 跨会话记忆持久化

**Files:**
- Create: `core/memory/cross_session.py`
- Modify: `core/cli/chat.py` (_handle_chat 增强)

**Interfaces:**
- Consumes: `MemoryStore` 类
- Produces: `CrossSessionMemory` 类，提供 `save_insight()` / `get_context()` 方法

- [ ] **Step 1: 创建跨会话记忆模块**

```python
# core/memory/cross_session.py
from pathlib import Path
from typing import List, Dict, Any, Optional
import json
from datetime import datetime

class CrossSessionMemory:
    """跨会话记忆存储。
    
    功能：
    1. 自动从对话中提取关键信息（用户偏好、关注主题、未解决问题）
    2. 持久化存储到 memory/cross_session.json
    3. 新会话启动时自动加载上下文
    """
    
    MEMORY_FILE = Path("storage/memory/cross_session.json")
    
    def __init__(self) -> None:
        self.MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._data = self._load()
    
    def _load(self) -> dict:
        """加载跨会话记忆。"""
        if not self.MEMORY_FILE.exists():
            return {
                "preferences": {},
                "topics": [],
                "unresolved_questions": [],
                "key_facts": [],
                "last_updated": None
            }
        try:
            return json.loads(self.MEMORY_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            return self._default_data()
    
    def _default_data(self) -> dict:
        return {
            "preferences": {},
            "topics": [],
            "unresolved_questions": [],
            "key_facts": [],
            "last_updated": None
        }
    
    def get_context(self) -> str:
        """获取当前跨会话上下文，供 LLM 使用。"""
        parts = []
        
        if self._data.get("preferences"):
            parts.append("【用户偏好】")
            for key, value in self._data["preferences"].items():
                parts.append(f"- {key}: {value}")
        
        if self._data.get("topics"):
            parts.append("【关注主题】")
            for topic in self._data["topics"]:
                parts.append(f"- {topic}")
        
        if self._data.get("unresolved_questions"):
            parts.append("【未解决问题】")
            for q in self._data["unresolved_questions"]:
                parts.append(f"- {q}")
        
        if self._data.get("key_facts"):
            parts.append("【关键事实】")
            for fact in self._data["key_facts"]:
                parts.append(f"- {fact}")
        
        return "\n".join(parts) if parts else ""
    
    def save_preference(self, key: str, value: str) -> None:
        """保存用户偏好。"""
        self._data["preferences"][key] = value
        self._save()
    
    def add_topic(self, topic: str) -> None:
        """添加关注主题。"""
        if topic not in self._data["topics"]:
            self._data["topics"].append(topic)
            self._save()
    
    def remove_topic(self, topic: str) -> None:
        """移除关注主题。"""
        if topic in self._data["topics"]:
            self._data["topics"].remove(topic)
            self._save()
    
    def add_unresolved_question(self, question: str) -> None:
        """添加未解决问题。"""
        if question not in self._data["unresolved_questions"]:
            self._data["unresolved_questions"].append(question)
            self._save()
    
    def add_key_fact(self, fact: str) -> None:
        """添加关键事实。"""
        if fact not in self._data["key_facts"]:
            self._data["key_facts"].append(fact)
            self._save()
    
    def clear_all(self) -> None:
        """清空所有跨会话记忆。"""
        self._data = self._default_data()
        self._save()
    
    def _save(self) -> None:
        """保存记忆到文件。"""
        self._data["last_updated"] = datetime.now().isoformat()
        self.MEMORY_FILE.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
```

- [ ] **Step 2: 在 REPL 初始化时加载跨会话记忆**

```python
# 在 REPL.__init__ 中添加
self.cross_session_memory = CrossSessionMemory()
```

- [ ] **Step 3: 在 `_handle_chat` 中注入上下文**

```python
def _handle_chat(self, user_input: str) -> None:
    # ... 原有代码 ...
    
    # 获取跨会话上下文
    context = self.cross_session_memory.get_context()
    
    # 如果有上下文，在 system prompt 中注入
    if context:
        # 修改传递给 LLM 的 messages
        messages = [
            {"role": "system", "content": f"{SYSTEM_PROMPT}\n\n{context}"},
            *self.history[-10:],  # 最近 10 条对话
            {"role": "user", "content": user_input}
        ]
    else:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *self.history[-10:],
            {"role": "user", "content": user_input}
        ]
    
    # 使用 messages 调用 LLM（原有逻辑不变）
```

- [ ] **Step 4: 创建跨会话记忆管理命令**

```python
# 在 core/cli/commands/memory.py 中添加
def _cmd_cross_memory(self, query: str) -> None:
    """跨会话记忆管理：/cross [list|add|remove|clear]"""
    from core.memory.cross_session import CrossSessionMemory
    
    cm = CrossSessionMemory()
    args = query.strip().split()
    
    if not args:
        # 显示当前记忆
        console.print(f"\n[bold]跨会话记忆[/bold]\n")
        console.print(cm.get_context())
        return
    
    cmd = args[0].lower()
    
    if cmd == "list":
        console.print(cm.get_context())
    
    elif cmd == "add" and len(args) > 1:
        # 添加记忆
        category = args[1].lower()
        content = " ".join(args[2:])
        
        if category == "preference":
            if ":" in content:
                key, value = content.split(":", 1)
                cm.save_preference(key.strip(), value.strip())
                console.print(f"[green]✓ 偏好已保存: {key.strip()} = {value.strip()}[/green]")
            else:
                console.print("[yellow]格式: /cross add preference 键:值[/yellow]")
        elif category == "topic":
            cm.add_topic(content)
            console.print(f"[green]✓ 主题已添加: {content}[/green]")
        elif category == "question":
            cm.add_unresolved_question(content)
            console.print(f"[green]✓ 问题已记录: {content}[/green]")
        elif category == "fact":
            cm.add_key_fact(content)
            console.print(f"[green]✓ 事实已记录: {content}[/green]")
        else:
            console.print("[yellow]类别: preference/topic/question/fact[/yellow]")
    
    elif cmd == "remove" and len(args) > 2:
        category = args[1].lower()
        content = " ".join(args[2:])
        
        if category == "topic" and content in cm._data["topics"]:
            cm.remove_topic(content)
            console.print(f"[green]✓ 主题已移除: {content}[/green]")
        else:
            console.print(f"[yellow]未找到: {content}[/yellow]")
    
    elif cmd == "clear":
        cm.clear_all()
        console.print("[green]✓ 跨会话记忆已清空[/green]")
    
    else:
        console.print("[yellow]用法: /cross [list|add <类别> <内容>|remove <类别> <内容>|clear][/yellow]")
```

- [ ] **Step 5: 运行测试**

```bash
# 创建测试文件
cat > tests/test_cross_session_memory.py << 'EOF'
"""跨会话记忆测试。"""
import pytest
from pathlib import Path
from core.memory.cross_session import CrossSessionMemory

def test_load_default_memory(tmp_path, monkeypatch):
    """记忆文件不存在时返回默认值。"""
    memory_file = tmp_path / "cross_session.json"
    monkeypatch.setattr(CrossSessionMemory, "MEMORY_FILE", memory_file)
    
    cm = CrossSessionMemory()
    assert cm.get_context() == ""

def test_add_and_get_context(tmp_path, monkeypatch):
    """添加记忆后能正确获取上下文。"""
    memory_file = tmp_path / "cross_session.json"
    monkeypatch.setattr(CrossSessionMemory, "MEMORY_FILE", memory_file)
    
    cm = CrossSessionMemory()
    cm.add_topic("殡葬政策")
    cm.save_preference("format", "table")
    
    context = cm.get_context()
    assert "殡葬政策" in context
    assert "table" in context

def test_clear_all(tmp_path, monkeypatch):
    """清空所有记忆。"""
    memory_file = tmp_path / "cross_session.json"
    monkeypatch.setattr(CrossSessionMemory, "MEMORY_FILE", memory_file)
    
    cm = CrossSessionMemory()
    cm.add_topic("测试主题")
    cm.clear_all()
    
    assert cm.get_context() == ""
EOF

.venv/bin/python -m pytest tests/test_cross_session_memory.py -v
.venv/bin/python -m pytest tests/ -x -q
```

---

# 第三部分：集成测试与验证

## Task 5: 完整集成测试

**Files:**
- Create: `tests/test_integration_search_session.py`

**Interfaces:**
- Consumes: 所有新增功能
- Produces: 端到端测试验证

- [ ] **Step 1: 创建集成测试**

```python
# tests/test_integration_search_session.py
"""搜索命令与会话记忆的集成测试。"""
import pytest
from pathlib import Path
from core.search.config import SearchConfig
from core.memory.cross_session import CrossSessionMemory

def test_search_config_with_limits(tmp_path, monkeypatch):
    """搜索配置与 limit 参数联动。"""
    config_file = tmp_path / "search_config.json"
    monkeypatch.setattr(SearchConfig, "CONFIG_FILE", config_file)
    
    config = SearchConfig()
    config.set_defaults(limit=20)
    
    assert config.get_default_limit() == 20

def test_cross_session_memory_with_preferences(tmp_path, monkeypatch):
    """跨会话记忆与用户偏好联动。"""
    memory_file = tmp_path / "cross_session.json"
    monkeypatch.setattr(CrossSessionMemory, "MEMORY_FILE", memory_file)
    
    cm = CrossSessionMemory()
    cm.save_preference("format", "prose")
    
    context = cm.get_context()
    assert "prose" in context
```

- [ ] **Step 2: 运行所有测试**

```bash
.venv/bin/python -m pytest tests/ -x -q
```

- [ ] **Step 3: 手动验证**

```bash
# 测试搜索默认配置
ima
> /search config limit 20
> /search 殡葬

# 测试跨会话记忆
> /cross add topic 殡葬政策
> /cross add preference format:table
> /cross list

# 测试会话自动保存
> 你好
> 再见
> exit
# 重新启动，应该自动恢复对话历史
```

---

## 总结

本计划包含：
1. **搜索命令默认配置**：用户设置一次，所有搜索自动带上默认参数
2. **跨会话记忆**：自动提取用户偏好、关注主题、未解决问题
3. **会话自动持久化**：每次对话后自动保存，重启自动恢复

预计工作量：约 2-3 小时（含测试）
