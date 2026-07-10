# IMA 虚拟宠物系统 · 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 IMA 个人知识库增加虚拟宠物系统，宠物随知识库使用习惯升级，Lv5 时按使用倾向自动分系（学者/战士/工匠），ASCII 艺术展示。

**Architecture:** 新建 `core/pet/` 模块（Pet dataclass + 业务逻辑 + JSON 持久化），REPL 启动页加宠物子区块，10 处行为埋点驱动经验获取，每日任务系统 + 道具商店增加游戏性。

**Tech Stack:** Python 3.9+ dataclasses / rich (CLI 渲染) / JSON 持久化 / pytest

## Global Constraints

- Python ≥ 3.9（不使用 3.10+ 语法，如 `X | Y` 联合类型，用 `Optional[X]`）
- 文件命名：snake_case
- 中文注释 + 英文变量名
- 不修改 .gitignore / pyproject.toml 除非必要
- 测试框架：pytest（已存在于项目）
- 所有时间用 ISO 字符串存储
- 路径含中文，用 Path 对象处理

---

## File Structure

```
core/pet/
├── __init__.py          # 导出 Pet / PetStorage / ArtLibrary
├── pet.py               # Pet dataclass + 升级/分系/衰减逻辑
├── storage.py           # PetStorage（JSON 读写）
├── art.py               # ArtLibrary（ASCII 加载器）
├── arts/                # ASCII 艺术文本文件（共 35 个）
│   ├── none_1.txt ... none_5.txt         # 通用阶段 Lv1-5
│   ├── scholar_1.txt ... scholar_10.txt  # 学者系 Lv1-10
│   ├── warrior_1.txt ... warrior_10.txt  # 战士系 Lv1-10
│   └── artisan_1.txt ... artisan_10.txt  # 工匠系 Lv1-10
├── interact.py          # 5 个互动命令处理
├── tasks.py             # 每日任务系统
└── shop.py              # 道具商店

tests/pet/
├── __init__.py
├── test_pet.py          # Pet 类单元测试
├── test_storage.py      # 持久化测试
├── test_interact.py     # 互动测试
├── test_tasks.py        # 每日任务测试
└── test_shop.py         # 商店测试

repl.py                  # 修改：加 /pet 命令 + 启动页宠物子区块 + 10 处埋点
config.py                # 修改：加 pet 衰减速率配置
storage/pet.json         # 运行时生成：宠物状态
```

---

## Task 1: 创建 Pet dataclass + 升级阈值

**Files:**
- Create: `core/pet/__init__.py`
- Create: `core/pet/pet.py`
- Create: `tests/pet/__init__.py`
- Create: `tests/pet/test_pet.py`

**Interfaces:**
- Produces: `Pet` dataclass, `Pet.exp_needed() -> int`, `Pet.exp_remaining() -> int`

- [ ] **Step 1: 创建模块骨架**

```python
# core/pet/__init__.py
"""虚拟宠物系统。"""
from core.pet.pet import Pet, BranchType
from core.pet.storage import PetStorage
from core.pet.art import ArtLibrary

__all__ = ["Pet", "BranchType", "PetStorage", "ArtLibrary"]
```

- [ ] **Step 2: 写 Pet dataclass + 升级阈值测试**

```python
# tests/pet/test_pet.py
"""Pet 类单元测试。"""
import pytest
from core.pet.pet import Pet


def test_new_pet_has_default_values():
    p = Pet(name="小白")
    assert p.name == "小白"
    assert p.level == 1
    assert p.exp == 0
    assert p.branch is None
    assert p.hunger == 80
    assert p.mood == 80
    assert p.energy == 100
    assert p.cleanliness == 80
    assert p.exp_multi == 1.0


def test_exp_needed_lv1():
    p = Pet(name="小白", level=1)
    assert p.exp_needed() == 100  # 100 * 1^1.5 = 100


def test_exp_needed_lv5():
    p = Pet(name="小白", level=5)
    assert p.exp_needed() == 1118  # floor(100 * 5^1.5) = floor(1118.03) = 1118


def test_exp_needed_lv10():
    p = Pet(name="小白", level=10)
    assert p.exp_needed() == 3162  # floor(100 * 10^1.5)


def test_exp_remaining_lv1_with_50_exp():
    p = Pet(name="小白", level=1, exp=50)
    assert p.exp_remaining() == 50  # 100 - 50


def test_exp_remaining_max_level():
    p = Pet(name="小白", level=10, exp=5000)
    assert p.exp_remaining() == 0  # 已达最高级
```

- [ ] **Step 3: 运行测试确认失败**

Run: `pytest tests/pet/test_pet.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.pet'`

- [ ] **Step 4: 实现 Pet dataclass**

```python
# core/pet/pet.py
"""Pet 类：虚拟宠物状态 + 升级逻辑。"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


# 分系类型
BranchType = Optional[str]  # None / "scholar" / "warrior" / "artisan"

# 等级上限
MAX_LEVEL = 10


@dataclass
class Pet:
    """虚拟宠物状态。"""

    # 基本信息
    name: str
    level: int = 1
    exp: int = 0
    branch: BranchType = None

    # 5 维属性（0-100）
    hunger: int = 80
    mood: int = 80
    energy: int = 100
    cleanliness: int = 80
    exp_multi: float = 1.0

    # 行为统计（分系判定用）
    stats: dict = field(default_factory=lambda: {
        "ingest": 0, "qa": 0, "read": 0, "report": 0,
        "agent": 0, "compare": 0,
        "analyze": 0, "smart": 0, "retag": 0,
        "graph_build": 0,
    })

    # 道具栏
    inventory: list = field(default_factory=list)

    # 时间戳（ISO 字符串）
    last_interact: str = ""
    last_decay: str = ""
    created_at: str = ""

    # 每日任务
    daily_tasks: list = field(default_factory=list)
    daily_reset_at: str = ""
    # 任务历史（7 天不重复用）：[{"date": "2026-07-05", "task_ids": [...]}]
    task_history: list = field(default_factory=list)

    # 限时效果
    active_effects: list = field(default_factory=list)

    def exp_needed(self) -> int:
        """当前等级升到下一级所需经验（纯公式，MAX_LEVEL 由 exp_remaining/gain_exp 守卫）。"""
        return math.floor(100 * (self.level ** 1.5))

    def exp_remaining(self) -> int:
        """距离升级还差多少经验。"""
        if self.level >= MAX_LEVEL:
            return 0
        return max(0, self.exp_needed() - self.exp)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/pet/test_pet.py -v`
Expected: 6 passed

- [ ] **Step 6: 提交**

```bash
git add core/pet/__init__.py core/pet/pet.py tests/pet/__init__.py tests/pet/test_pet.py
git commit -m "feat(pet): add Pet dataclass with level thresholds"
```

---

## Task 2: gain_exp 方法（经验获取 + 升级 + 分系触发）

**Files:**
- Modify: `core/pet/pet.py` (append methods)
- Modify: `tests/pet/test_pet.py` (append tests)

**Interfaces:**
- Consumes: Task 1 的 `Pet` dataclass
- Produces: `Pet.gain_exp(amount: int, action_type: str) -> dict` 返回事件信息

- [ ] **Step 1: 写 gain_exp 测试**

```python
# 追加到 tests/pet/test_pet.py 末尾

def test_gain_exp_increases_exp():
    p = Pet(name="小白", level=1, exp=0)
    events = p.gain_exp(50, "ingest")
    assert p.exp == 50
    assert p.stats["ingest"] == 1
    assert events["leveled_up"] is False


def test_gain_exp_triggers_level_up():
    p = Pet(name="小白", level=1, exp=50)
    events = p.gain_exp(60, "ingest")  # 50+60=110 > 100
    assert p.level == 2
    assert p.exp == 10  # 110 - 100 = 10
    assert events["leveled_up"] is True
    assert events["new_level"] == 2


def test_gain_exp_multi_level_up():
    p = Pet(name="小白", level=1, exp=0)
    # 一次给 2000 经验，应该连升多级
    events = p.gain_exp(2000, "ingest")
    assert p.level > 2
    assert events["leveled_up"] is True


def test_gain_exp_mood_penalty():
    p = Pet(name="小白", level=1, exp=0, mood=20)  # mood < 30
    p.gain_exp(100, "qa")
    # 经验应该是 100 * 0.7 = 70
    assert p.exp == 70


def test_gain_exp_branch_trigger_at_lv5():
    p = Pet(name="小白", level=4, exp=780, stats={
        "ingest": 10, "qa": 50, "read": 5, "report": 2,
        "agent": 0, "compare": 0,
        "analyze": 0, "smart": 0, "retag": 0,
        "graph_build": 0,
    })
    events = p.gain_exp(50, "qa")  # 升到 Lv5
    assert p.level == 5
    assert p.branch == "scholar"  # scholar 系行为最多
    assert events["branched"] is True
    assert events["branch"] == "scholar"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/pet/test_pet.py -v`
Expected: FAIL with `AttributeError: 'Pet' object has no attribute 'gain_exp'`

- [ ] **Step 3: 实现 gain_exp + 分系判定**

```python
# 追加到 core/pet/pet.py 末尾（在 Pet 类内部）

    # 分系判定用的行为映射
    SCHOLAR_KEYS = {"ingest", "qa", "read", "report"}
    WARRIOR_KEYS = {"agent", "compare"}
    ARTISAN_KEYS = {"analyze", "smart", "retag"}
    # graph_build 中性，不计入分系

    def _determine_branch(self) -> str:
        """根据 stats 判定分系。平局时随机选择。"""
        import random
        scholar_score = sum(self.stats.get(k, 0) for k in self.SCHOLAR_KEYS)
        warrior_score = sum(self.stats.get(k, 0) for k in self.WARRIOR_KEYS)
        artisan_score = sum(self.stats.get(k, 0) for k in self.ARTISAN_KEYS)
        scores = [
            ("scholar", scholar_score),
            ("warrior", warrior_score),
            ("artisan", artisan_score),
        ]
        max_score = max(s for _, s in scores)
        # 平局时随机选一个（避免永远 scholar）
        winners = [name for name, s in scores if s == max_score]
        return random.choice(winners) if len(winners) > 1 else winners[0]

    def gain_exp(self, amount: int, action_type: str) -> dict:
        """获取经验，可能触发升级和分系。

        Args:
            amount: 基础经验值
            action_type: 行为类型（ingest/qa/analyze/agent/...）

        Returns:
            事件信息 dict：
                - leveled_up: bool
                - new_level: int (若升级)
                - branched: bool
                - branch: str (若分系)
        """
        events = {"leveled_up": False, "branched": False}

        # 1. 累计行为统计
        if action_type in self.stats:
            self.stats[action_type] += 1

        # 2. 心情惩罚
        actual_amount = amount
        if self.mood < 30:
            actual_amount = int(actual_amount * 0.7)
        # 3. 清理过期限时效果，再计算实际经验加成倍率
        self.clean_expired_effects()
        actual_amount = int(actual_amount * self.get_active_exp_multi())

        # 4. 累加经验
        self.exp += actual_amount

        # 5. 检查升级（可能连升多级）
        while self.level < MAX_LEVEL and self.exp >= self.exp_needed():
            self.exp -= self.exp_needed()
            self.level += 1
            events["leveled_up"] = True
            events["new_level"] = self.level

            # 6. Lv5 触发分系
            if self.level == 5 and self.branch is None:
                self.branch = self._determine_branch()
                events["branched"] = True
                events["branch"] = self.branch

        # Lv10 满级，经验封顶不再累积（保留溢出经验但不升级）
        if self.level >= MAX_LEVEL:
            # 经验继续累积但不升级，UI 显示"已达最高级"
            pass

        return events
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/pet/test_pet.py -v`
Expected: 11 passed (原 6 + 新 5)

- [ ] **Step 5: 提交**

```bash
git add core/pet/pet.py tests/pet/test_pet.py
git commit -m "feat(pet): implement gain_exp with level up and branch trigger"
```

---

## Task 3: JSON 持久化（PetStorage）

**Files:**
- Create: `core/pet/storage.py`
- Create: `tests/pet/test_storage.py`

**Interfaces:**
- Consumes: Task 1 的 `Pet` dataclass
- Produces: `PetStorage` 类 with `load() -> Optional[Pet]`, `save(pet: Pet) -> None`, `create(name: str) -> Pet`

- [ ] **Step 1: 写持久化测试**

```python
# tests/pet/test_storage.py
"""PetStorage 持久化测试。"""
import json
from pathlib import Path
import pytest
from core.pet.pet import Pet
from core.pet.storage import PetStorage


def test_load_returns_none_when_file_missing(tmp_path):
    storage = PetStorage(storage_path=tmp_path)
    assert storage.load() is None


def test_save_and_load_roundtrip(tmp_path):
    storage = PetStorage(storage_path=tmp_path)
    pet = Pet(name="小白", level=5, exp=300, branch="scholar")
    storage.save(pet)

    loaded = storage.load()
    assert loaded is not None
    assert loaded.name == "小白"
    assert loaded.level == 5
    assert loaded.exp == 300
    assert loaded.branch == "scholar"


def test_create_new_pet(tmp_path):
    storage = PetStorage(storage_path=tmp_path)
    pet = storage.create("小白")
    assert pet.name == "小白"
    assert pet.level == 1
    assert pet.exp == 0
    # 已保存到磁盘
    assert (tmp_path / "pet.json").exists()


def test_load_corrupted_json_returns_none_and_backups(tmp_path):
    # 写入损坏的 JSON
    (tmp_path / "pet.json").write_text("{invalid json", encoding="utf-8")
    storage = PetStorage(storage_path=tmp_path)
    loaded = storage.load()
    assert loaded is None
    # 备份文件存在
    backups = list(tmp_path.glob("pet.json.bak.*"))
    assert len(backups) == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/pet/test_storage.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 PetStorage**

```python
# core/pet/storage.py
"""宠物状态 JSON 持久化。"""
from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from core.pet.pet import Pet


class PetStorage:
    """宠物状态存储（JSON 文件）。"""

    def __init__(self, storage_path: Optional[Path] = None) -> None:
        if storage_path is None:
            from config import settings
            storage_path = settings.storage_path
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.file_path = self.storage_path / "pet.json"

    def load(self) -> Optional[Pet]:
        """加载宠物状态。文件不存在返回 None，损坏返回 None 并备份。"""
        if not self.file_path.exists():
            return None
        try:
            data = json.loads(self.file_path.read_text(encoding="utf-8"))
            return Pet(**data)
        except (json.JSONDecodeError, TypeError) as e:
            # 备份损坏的文件（用 parent / name.bak.ts 避免后缀替换问题）
            bak = self.file_path.parent / f"{self.file_path.name}.bak.{int(time.time())}"
            self.file_path.rename(bak)
            return None

    def save(self, pet: Pet) -> None:
        """保存宠物状态。"""
        data = asdict(pet)
        self.file_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def create(self, name: str) -> Pet:
        """创建新宠物并保存。"""
        pet = Pet(name=name)
        pet.created_at = _now_iso()
        pet.last_decay = _now_iso()
        pet.last_interact = _now_iso()
        self.save(pet)
        return pet


def _now_iso() -> str:
    """当前时间的 ISO 字符串。"""
    from datetime import datetime
    return datetime.now().isoformat()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/pet/test_storage.py -v`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add core/pet/storage.py tests/pet/test_storage.py
git commit -m "feat(pet): add JSON persistence with corruption backup"
```

---

## Task 4: ASCII 艺术加载器（ArtLibrary）

**Files:**
- Create: `core/pet/art.py`
- Create: `core/pet/arts/none_1.txt` ... `none_5.txt` (5 个通用阶段)
- Create: `core/pet/arts/scholar_1.txt` ... `scholar_10.txt` (10 个学者系)
- Create: `core/pet/arts/warrior_1.txt` ... `warrior_10.txt` (10 个战士系)
- Create: `core/pet/arts/artisan_1.txt` ... `artisan_10.txt` (10 个工匠系)
- Create: `tests/pet/test_art.py`

**Interfaces:**
- Produces: `ArtLibrary.get(branch: Optional[str], level: int, small: bool = False) -> str`

- [ ] **Step 1: 写 ArtLibrary 测试**

```python
# tests/pet/test_art.py
"""ASCII 艺术加载器测试。"""
from core.pet.art import ArtLibrary


def test_get_none_branch_lv1():
    lib = ArtLibrary()
    art = lib.get(None, 1)
    assert isinstance(art, str)
    assert len(art) > 0


def test_get_scholar_lv6():
    lib = ArtLibrary()
    art = lib.get("scholar", 6)
    assert isinstance(art, str)
    assert len(art) > 0


def test_get_missing_file_returns_fallback():
    lib = ArtLibrary()
    # Lv99 不存在，应该返回占位符
    art = lib.get("scholar", 99)
    assert "Lv99" in art


def test_get_small_variant():
    lib = ArtLibrary()
    art = lib.get("scholar", 6, small=True)
    assert isinstance(art, str)
    # 小尺寸应该比大尺寸短，且行数 ≤ 6
    full_art = lib.get("scholar", 6, small=False)
    assert len(art) < len(full_art)  # 严格小于
    assert art.count("\n") <= 6      # 小尺寸最多 6 行
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/pet/test_art.py -v`
Expected: FAIL

- [ ] **Step 3: 创建占位符 ASCII 艺术文件**

为每个形态创建一个简单的占位符文本文件。例如 `core/pet/arts/none_1.txt`：

```
   .---.
  /     \
 |       |
  \     /
   '---'
   [蛋]
```

`core/pet/arts/none_2.txt`：
```
   /\_/\
  ( o.o )
   > ^ <
  [幼崽]
```

依此类推，为 35 个形态创建占位符（none_1 到 none_5，scholar_1 到 scholar_10，warrior_1 到 warrior_10，artisan_1 到 artisan_10）。

小尺寸变体由代码动态截断大尺寸前 6 行（`ArtLibrary.get(small=True)`），无需单独创建 `_small` 文件。

- [ ] **Step 4: 实现 ArtLibrary**

```python
# core/pet/art.py
"""ASCII 艺术加载器。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional


ARTS_DIR = Path(__file__).parent / "arts"


class ArtLibrary:
    """ASCII 艺术加载器。"""

    def get(
        self,
        branch: Optional[str],
        level: int,
        small: bool = False,
    ) -> str:
        """加载指定形态的 ASCII 艺术。

        Args:
            branch: None / "scholar" / "warrior" / "artisan"
            level: 1-10
            small: True 返回缩略版

        Returns:
            ASCII 艺术字符串
        """
        branch_key = branch or "none"
        suffix = "_small" if small else ""
        path = ARTS_DIR / f"{branch_key}_{level}{suffix}.txt"

        if not path.exists():
            # 尝试加载大尺寸再截断
            if small:
                full_path = ARTS_DIR / f"{branch_key}_{level}.txt"
                if full_path.exists():
                    lines = full_path.read_text(encoding="utf-8").split("\n")[:6]
                    return "\n".join(lines)

            # 都没有，返回占位符
            return self._fallback(branch, level, small)

        return path.read_text(encoding="utf-8")

    def _fallback(self, branch: Optional[str], level: int, small: bool = False) -> str:
        """占位符。small=True 时返回更短的版本。

        采用 block-style 像素风格，避免 ??? 占位。
        """
        branch_label = branch or "未分系"
        if small:
            return f"""
  ▄▄▄
 ▄●●▄
 ▀██▀
[{branch_label} Lv{level}]
"""
        return f"""
   ▄▄▄▄
  ▄●  ●▄
  █▄██▄█
   ▀██▀
    ▐  ▌
 [{branch_label} Lv{level}]
"""
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/pet/test_art.py -v`
Expected: 4 passed

- [ ] **Step 6: 提交**

```bash
git add core/pet/art.py core/pet/arts/ tests/pet/test_art.py
git commit -m "feat(pet): add ASCII art library with 35 placeholder forms"
```

---

## Task 5: 互动命令处理（interact.py）

**Files:**
- Create: `core/pet/interact.py`
- Create: `tests/pet/test_interact.py`

**Interfaces:**
- Consumes: Task 1-2 的 `Pet` 类
- Produces: `PetInteractor` 类 with `feed(pet)`, `play(pet)`, `train(pet)`, `wash(pet)`, `sleep(pet)`

- [ ] **Step 1: 写互动测试**

```python
# tests/pet/test_interact.py
"""互动命令测试。"""
import pytest
from core.pet.pet import Pet
from core.pet.interact import PetInteractor, InteractError


def test_feed_increases_hunger():
    p = Pet(name="小白", hunger=50, energy=80, exp=100)
    interactor = PetInteractor()
    result = interactor.feed(p)
    assert p.hunger == 80  # 50 + 30
    assert p.energy == 70  # 80 - 10
    assert p.exp == 95  # 100 - 5
    assert p.mood == 85  # 80 + 5
    assert "吃饱了" in result["message"]


def test_play_increases_mood():
    p = Pet(name="小白", mood=50, energy=80, hunger=80)
    interactor = PetInteractor()
    result = interactor.play(p)
    assert p.mood == 90  # 50 + 40
    assert p.energy == 65  # 80 - 15
    assert p.hunger == 70  # 80 - 10
    assert p.exp == 10  # 0 + 10
    assert "开心" in result["message"]


def test_train_gives_exp():
    p = Pet(name="小白", energy=80, mood=80)
    interactor = PetInteractor()
    result = interactor.train(p)
    assert p.energy == 55  # 80 - 25
    assert p.mood == 70  # 80 - 10
    assert p.exp == 50
    assert "学到" in result["message"]


def test_train_blocked_by_low_energy():
    p = Pet(name="小白", energy=5)  # < 10
    interactor = PetInteractor()
    with pytest.raises(InteractError) as exc:
        interactor.train(p)
    assert "累" in str(exc.value)


def test_train_blocked_by_low_hunger():
    p = Pet(name="小白", energy=80, hunger=10)  # < 20
    interactor = PetInteractor()
    with pytest.raises(InteractError) as exc:
        interactor.train(p)
    assert "饿" in str(exc.value)


def test_train_mood_penalty_halves_exp():
    """train 内 mood<20 时经验减半（25），再经 gain_exp 的 mood<30 全局惩罚 ×0.7 = 17。

    双层惩罚设计：train 主动检查 + gain_exp 全局检查。
    """
    p = Pet(name="小白", energy=80, mood=20)  # mood=20 不算 <20，train 给 50
    interactor = PetInteractor()
    interactor.train(p)
    # mood=20 ≥ 20，train 给 50；但 mood=20 < 30，gain_exp 再 ×0.7 = 35
    assert p.exp == 35

    p2 = Pet(name="小白", energy=80, mood=19)  # < 20，train 给 25
    interactor.train(p2)
    # mood=19 < 20，train 给 25；mood=19 < 30，gain_exp 再 ×0.7 = 17
    assert p2.exp == 17


def test_wash_increases_cleanliness():
    p = Pet(name="小白", cleanliness=30, energy=80)
    interactor = PetInteractor()
    result = interactor.wash(p)
    assert p.cleanliness == 80  # 30 + 50
    assert p.energy == 75  # 80 - 5
    assert p.mood == 85  # 80 + 5


def test_sleep_restores_energy():
    p = Pet(name="小白", energy=30)
    interactor = PetInteractor()
    result = interactor.sleep(p)
    assert p.energy == 80  # 30 + 50
    assert p.mood == 90  # 80 + 10
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/pet/test_interact.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 PetInteractor**

```python
# core/pet/interact.py
"""宠物互动命令处理。"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.pet.pet import Pet


class InteractError(Exception):
    """互动失败（如能量不足）。"""


class PetInteractor:
    """互动命令处理器。"""

    SLEEP_COOLDOWN_SECONDS = 3600  # 1 小时冷却

    def feed(self, pet: "Pet") -> dict:
        """喂食：+30 hunger, +5 mood, -10 energy, -5 exp。"""
        if pet.energy < 10:
            raise InteractError(f"{pet.name} 累坏了，让它睡会儿吧～")
        pet.hunger = min(100, pet.hunger + 30)
        pet.mood = min(100, pet.mood + 5)
        pet.energy -= 10
        pet.exp = max(0, pet.exp - 5)
        self._touch(pet)
        return {"message": f"{pet.name} 吃饱了 ❤️+30"}

    def play(self, pet: "Pet") -> dict:
        """玩耍：+40 mood, -10 hunger, -15 energy, +10 exp。"""
        if pet.energy < 15:
            raise InteractError(f"{pet.name} 累坏了，让它睡会儿吧～")
        pet.mood = min(100, pet.mood + 40)
        pet.hunger = max(0, pet.hunger - 10)
        pet.energy -= 15
        events = pet.gain_exp(10, "play")
        self._touch(pet)
        return {"message": f"{pet.name} 玩得很开心 😊+40"}

    def train(self, pet: "Pet") -> dict:
        """训练：-25 energy, -10 mood, +50 exp（高效升级）。"""
        if pet.energy < 10:
            raise InteractError(f"{pet.name} 累坏了，让它睡会儿吧～")
        if pet.hunger < 20:
            raise InteractError(f"{pet.name} 饿了，先喂点东西吧～")
        pet.energy -= 25
        pet.mood = max(0, pet.mood - 10)
        # 心情低时训练效果减半
        exp_gain = 25 if pet.mood < 20 else 50
        events = pet.gain_exp(exp_gain, "train")
        self._touch(pet)
        msg = f"{pet.name} 学到了新东西 ✨+{exp_gain}"
        if events.get("leveled_up"):
            msg += f"  🎉 升到 Lv{events['new_level']}！"
        return {"message": msg, "events": events}

    def wash(self, pet: "Pet") -> dict:
        """清洁：+50 cleanliness, +5 mood, -5 energy。"""
        pet.cleanliness = min(100, pet.cleanliness + 50)
        pet.mood = min(100, pet.mood + 5)
        pet.energy = max(0, pet.energy - 5)
        self._touch(pet)
        return {"message": f"{pet.name} 洗得干干净净 🛁+50"}

    def sleep(self, pet: "Pet") -> dict:
        """睡觉：+50 energy, +10 mood（1 小时冷却）。"""
        now = datetime.now()
        if pet.last_interact:
            last = datetime.fromisoformat(pet.last_interact)
            if (now - last).total_seconds() < self.SLEEP_COOLDOWN_SECONDS:
                remaining = self.SLEEP_COOLDOWN_SECONDS - int((now - last).total_seconds())
                mins = remaining // 60
                raise InteractError(f"{pet.name} 刚睡过，{mins} 分钟后再试～")
        pet.energy = min(100, pet.energy + 50)
        pet.mood = min(100, pet.mood + 10)
        self._touch(pet)
        return {"message": f"{pet.name} 睡了个好觉 ⚡+50"}

    def _touch(self, pet: "Pet") -> None:
        """更新 last_interact 时间戳。"""
        pet.last_interact = datetime.now().isoformat()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/pet/test_interact.py -v`
Expected: 8 passed

- [ ] **Step 5: 提交**

```bash
git add core/pet/interact.py tests/pet/test_interact.py
git commit -m "feat(pet): add 5 interaction commands (feed/play/train/wash/sleep)"
```

---

## Task 6: 每日任务系统（tasks.py）

**Files:**
- Create: `core/pet/tasks.py`
- Create: `tests/pet/test_tasks.py`

**Interfaces:**
- Produces: `DailyTaskManager` 类 with `refresh(pet)`, `check_progress(pet, action_type: str) -> list`, `list_tasks(pet) -> list`

- [ ] **Step 1: 写每日任务测试**

```python
# tests/pet/test_tasks.py
"""每日任务测试。"""
from datetime import datetime, timedelta
from core.pet.pet import Pet
from core.pet.tasks import DailyTaskManager, TASK_POOL


def test_refresh_creates_3_tasks():
    p = Pet(name="小白")
    mgr = DailyTaskManager()
    mgr.refresh(pet=p)
    assert len(p.daily_tasks) == 3
    for task in p.daily_tasks:
        assert "task_id" in task
        assert "progress" in task
        assert "completed" in task


def test_refresh_resets_at_midnight():
    p = Pet(name="小白", daily_reset_at="2026-07-05T23:59:00")
    mgr = DailyTaskManager()
    # 模拟跨天
    now = datetime(2026, 7, 6, 8, 0)
    if mgr.should_refresh(p, now=now):
        mgr.refresh(pet=p, now=now)
    assert "2026-07-06" in p.daily_reset_at


def test_check_progress_completes_task():
    p = Pet(name="小白")
    mgr = DailyTaskManager()
    # 手动设置一个 qa5 任务
    p.daily_tasks = [{
        "task_id": "qa5",
        "description": "问 5 个问题",
        "target": 5,
        "reward": 80,
        "progress": 4,
        "completed": False,
    }]
    # 触发第 5 次问答
    completed = mgr.check_progress(p, "qa")
    assert len(completed) == 1
    assert completed[0]["task_id"] == "qa5"
    assert completed[0]["reward"] == 80


def test_check_progress_no_match():
    p = Pet(name="小白")
    mgr = DailyTaskManager()
    p.daily_tasks = [{
        "task_id": "ingest1",
        "description": "入库 1 个文档",
        "target": 1,
        "reward": 100,
        "progress": 0,
        "completed": False,
    }]
    # 触发 qa，不匹配 ingest
    completed = mgr.check_progress(p, "qa")
    assert len(completed) == 0


def test_check_progress_skips_completed():
    p = Pet(name="小白")
    mgr = DailyTaskManager()
    p.daily_tasks = [{
        "task_id": "qa5",
        "description": "问 5 个问题",
        "target": 5,
        "reward": 80,
        "progress": 5,
        "completed": True,
    }]
    completed = mgr.check_progress(p, "qa")
    assert len(completed) == 0  # 已完成，不再触发
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/pet/test_tasks.py -v`
Expected: FAIL

- [ ] **Step 3: 实现每日任务系统**

```python
# core/pet/tasks.py
"""每日任务系统。"""
from __future__ import annotations

import random
from datetime import datetime, date
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from core.pet.pet import Pet


# 任务池：task_id → 定义
TASK_POOL = [
    {"task_id": "ingest1", "action": "ingest", "target": 1, "reward": 100, "description": "入库 1 个文档"},
    {"task_id": "ingest3", "action": "ingest", "target": 3, "reward": 250, "description": "入库 3 个文档"},
    {"task_id": "qa5", "action": "qa", "target": 5, "reward": 80, "description": "问 5 个问题"},
    {"task_id": "qa10", "action": "qa", "target": 10, "reward": 180, "description": "问 10 个问题"},
    {"task_id": "analyze1", "action": "analyze", "target": 1, "reward": 120, "description": "使用 /analyze 1 次"},
    {"task_id": "agent1", "action": "agent", "target": 1, "reward": 150, "description": "使用 /agent 完成任务 1 次"},
    {"task_id": "read1", "action": "read", "target": 1, "reward": 100, "description": "用 /read 阅读 1 个文档"},
    {"task_id": "report1", "action": "report", "target": 1, "reward": 150, "description": "生成 1 份报告"},
    {"task_id": "graph_build", "action": "graph_build", "target": 1, "reward": 200, "description": "构建知识图谱"},
    {"task_id": "compare1", "action": "compare", "target": 1, "reward": 120, "description": "用 /compare 对比 1 次"},
    {"task_id": "smart3", "action": "smart", "target": 3, "reward": 100, "description": "用 /smart 路由 3 次"},
    {"task_id": "tag_retag", "action": "retag", "target": 1, "reward": 120, "description": "重新打标签 1 次"},
]

# 每天抽 3 个
TASKS_PER_DAY = 3


class DailyTaskManager:
    """每日任务管理器。"""

    def refresh(self, pet: "Pet", now: Optional[datetime] = None) -> None:
        """刷新今日任务。7 天内尽量不重复（保证任务多样性）。"""
        if now is None:
            now = datetime.now()
        # 排除最近 7 天用过的任务
        recent_ids = set()
        if hasattr(pet, "task_history") and pet.task_history:
            # task_history: [{"date": "2026-07-05", "task_ids": ["qa5", "ingest1"]}, ...]
            cutoff = now.date()
            for entry in pet.task_history:
                try:
                    entry_date = datetime.fromisoformat(entry["date"]).date()
                    if (cutoff - entry_date).days < 7:
                        recent_ids.update(entry["task_ids"])
                except (ValueError, KeyError):
                    continue
        # 候选池：未在 7 天内出现过的任务
        candidates = [t for t in TASK_POOL if t["task_id"] not in recent_ids]
        # 如果排除后不够 3 个，从全池补
        if len(candidates) < TASKS_PER_DAY:
            candidates = TASK_POOL
        chosen = random.sample(candidates, TASKS_PER_DAY)
        pet.daily_tasks = [
            {
                "task_id": t["task_id"],
                "description": t["description"],
                "target": t["target"],
                "reward": t["reward"],
                "progress": 0,
                "completed": False,
                "action": t["action"],
            }
            for t in chosen
        ]
        pet.daily_reset_at = now.isoformat()
        # 记录到历史
        if not hasattr(pet, "task_history") or pet.task_history is None:
            pet.task_history = []
        pet.task_history.append({
            "date": now.date().isoformat(),
            "task_ids": [t["task_id"] for t in chosen],
        })
        # 只保留最近 14 天
        pet.task_history = pet.task_history[-14:]

    def should_refresh(self, pet: "Pet", now: Optional[datetime] = None) -> bool:
        """判断是否需要刷新（公开方法）。"""
        if now is None:
            now = datetime.now()
        if not pet.daily_reset_at:
            return True
        try:
            last = datetime.fromisoformat(pet.daily_reset_at)
            return last.date() < now.date()
        except (ValueError, TypeError):
            return True

    # 兼容旧调用
    _should_refresh = should_refresh

    def check_progress(self, pet: "Pet", action_type: str) -> List[dict]:
        """检查任务进度，返回新完成的任务列表。

        Args:
            pet: 宠物
            action_type: 行为类型（ingest/qa/analyze/...）

        Returns:
            新完成的任务列表（每个含 task_id / reward）
        """
        newly_completed: List[dict] = []
        for task in pet.daily_tasks:
            if task["completed"]:
                continue
            if task["action"] != action_type:
                continue
            task["progress"] += 1
            if task["progress"] >= task["target"]:
                task["completed"] = True
                newly_completed.append({
                    "task_id": task["task_id"],
                    "reward": task["reward"],
                    "description": task["description"],
                })
        return newly_completed

    def list_tasks(self, pet: "Pet") -> List[dict]:
        """列出今日任务（含进度）。"""
        return pet.daily_tasks
```

- [ ] **Step 4: 修复测试中的 bug**

测试代码已修正：`test_refresh_creates_3_tasks` 用 `p` 而非 `pet`，`test_refresh_resets_at_midnight` 用公开方法 `should_refresh`。

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/pet/test_tasks.py -v`
Expected: 5 passed

- [ ] **Step 6: 提交**

```bash
git add core/pet/tasks.py tests/pet/test_tasks.py
git commit -m "feat(pet): add daily task system with 12-task pool"
```

---

## Task 7: 道具商店（shop.py）

**Files:**
- Create: `core/pet/shop.py`
- Create: `tests/pet/test_shop.py`

**Interfaces:**
- Produces: `Shop` 类 with `list_items() -> list`, `buy(pet, item_id) -> dict`, `use(pet, item_id) -> dict`

- [ ] **Step 1: 写商店测试**

```python
# tests/pet/test_shop.py
"""道具商店测试。"""
import pytest
from core.pet.pet import Pet
from core.pet.shop import Shop, ShopError


def test_list_items_returns_all():
    shop = Shop()
    items = shop.list_items()
    assert len(items) == 8  # 8 种道具
    ids = [i["id"] for i in items]
    assert "fish" in ids
    assert "exp_potion" in ids


def test_buy_success():
    p = Pet(name="小白", exp=500)
    shop = Shop()
    result = shop.buy(p, "fish")
    assert p.exp == 450  # 500 - 50
    assert len(p.inventory) == 1
    assert p.inventory[0]["item_id"] == "fish"
    assert p.inventory[0]["count"] == 1
    assert "购买成功" in result["message"]


def test_buy_insufficient_exp():
    p = Pet(name="小白", exp=30)
    shop = Shop()
    with pytest.raises(ShopError) as exc:
        shop.buy(p, "fish")  # 需要 50 经验
    assert "经验不足" in str(exc.value)
    assert p.exp == 30  # 未扣


def test_buy_stacks_inventory():
    p = Pet(name="小白", exp=500, inventory=[{"item_id": "fish", "count": 2}])
    shop = Shop()
    shop.buy(p, "fish")
    assert p.inventory[0]["count"] == 3


def test_use_fish():
    p = Pet(name="小白", hunger=50, inventory=[{"item_id": "fish", "count": 1}])
    shop = Shop()
    result = shop.use(p, "fish")
    assert p.hunger == 80  # 50 + 30
    assert p.inventory[0]["count"] == 0


def test_use_not_in_inventory():
    p = Pet(name="小白")
    shop = Shop()
    with pytest.raises(ShopError) as exc:
        shop.use(p, "fish")
    assert "没有" in str(exc.value)


def test_use_exp_potion_activates_effect():
    p = Pet(name="小白", inventory=[{"item_id": "exp_potion", "count": 1}])
    shop = Shop()
    shop.use(p, "exp_potion")
    # 应该激活限时效果
    assert len(p.active_effects) == 1
    assert p.active_effects[0]["effect"] == "exp_multi"
    assert p.active_effects[0]["value"] == 2.0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/pet/test_shop.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 Shop**

```python
# core/pet/shop.py
"""道具商店。"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.pet.pet import Pet


class ShopError(Exception):
    """商店操作失败。"""


# 道具定义
ITEMS = [
    {"id": "fish", "name": "小鱼干", "price": 50, "effect": {"hunger": 30}},
    {"id": "ball", "name": "玩具球", "price": 80, "effect": {"mood": 40}},
    {"id": "soap", "name": "洗浴套装", "price": 60, "effect": {"cleanliness": 50}},
    {"id": "energy_drink", "name": "能量饮料", "price": 100, "effect": {"energy": 50}},
    {"id": "exp_potion", "name": "经验药水", "price": 150, "effect": {"exp_multi": 2.0, "duration_sec": 7200}},
    {"id": "super_food", "name": "顶级饲料", "price": 150, "effect": {"hunger": 50, "mood": 20}},
    {"id": "phoenix_down", "name": "凤凰之羽", "price": 500, "effect": {"auto_revive": True}},
    {"id": "rename_card", "name": "重置卡", "price": 100, "effect": {"reset_stats": True}},
]


class Shop:
    """道具商店。"""

    def list_items(self) -> list:
        """列出所有道具。"""
        return [{"id": i["id"], "name": i["name"], "price": i["price"], "effect": i["effect"]} for i in ITEMS]

    def _find_item(self, item_id: str) -> dict:
        for item in ITEMS:
            if item["id"] == item_id:
                return item
        raise ShopError(f"未知道具: {item_id}")

    def buy(self, pet: "Pet", item_id: str) -> dict:
        """购买道具。"""
        item = self._find_item(item_id)
        if pet.exp < item["price"]:
            raise ShopError(f"经验不足，需要 {item['price']}，当前 {pet.exp}")
        pet.exp -= item["price"]
        # 加入库存
        for inv in pet.inventory:
            if inv["item_id"] == item_id:
                inv["count"] += 1
                break
        else:
            pet.inventory.append({"item_id": item_id, "count": 1})
        return {"message": f"✓ 购买成功 {item['name']}，剩余经验 {pet.exp}"}

    def use(self, pet: "Pet", item_id: str) -> dict:
        """使用道具。"""
        item = self._find_item(item_id)
        # 查找库存
        inv_idx = -1
        for i, inv in enumerate(pet.inventory):
            if inv["item_id"] == item_id and inv["count"] > 0:
                inv_idx = i
                break
        if inv_idx < 0:
            raise ShopError(f"没有 {item['name']}，先去 /pet buy 吧")

        # 应用效果
        effect = item["effect"]
        if "hunger" in effect:
            pet.hunger = min(100, pet.hunger + effect["hunger"])
        if "mood" in effect:
            pet.mood = min(100, pet.mood + effect["mood"])
        if "cleanliness" in effect:
            pet.cleanliness = min(100, pet.cleanliness + effect["cleanliness"])
        if "energy" in effect:
            pet.energy = min(100, pet.energy + effect["energy"])
        if "exp_multi" in effect:
            # 限时效果
            expires = datetime.now() + timedelta(seconds=effect.get("duration_sec", 3600))
            pet.active_effects.append({
                "effect": "exp_multi",
                "value": effect["exp_multi"],
                "expires_at": expires.isoformat(),
            })
        if "reset_stats" in effect:
            # 重置卡：把属性都恢复到 80
            pet.hunger = max(pet.hunger, 80)
            pet.mood = max(pet.mood, 80)
            pet.cleanliness = max(pet.cleanliness, 80)
            pet.energy = max(pet.energy, 80)

        # 扣库存
        pet.inventory[inv_idx]["count"] -= 1

        return {"message": f"{pet.name} 用了 {item['name']}"}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/pet/test_shop.py -v`
Expected: 7 passed

- [ ] **Step 5: 提交**

```bash
git add core/pet/shop.py tests/pet/test_shop.py
git commit -m "feat(pet): add item shop with 8 items and active effects"
```

---

## Task 8: 离线衰减计算

**Files:**
- Modify: `core/pet/pet.py` (append `apply_decay` method)
- Modify: `tests/pet/test_pet.py` (append tests)

**Interfaces:**
- Produces: `Pet.apply_decay() -> dict` 返回衰减信息

- [ ] **Step 1: 写衰减测试**

```python
# 追加到 tests/pet/test_pet.py

def test_apply_decay_reduces_attributes():
    from datetime import datetime, timedelta
    p = Pet(name="小白", hunger=90, mood=90, cleanliness=90)
    # 模拟 5 小时前
    p.last_decay = (datetime.now() - timedelta(hours=5)).isoformat()
    decay = p.apply_decay()
    # hunger: -1.5/h * 5h = -7.5 → int(90-7.5) = int(82.5) = 82
    assert p.hunger == 82
    # mood: -0.5/h * 5h = -2.5 → int(90-2.5) = int(87.5) = 87
    assert p.mood == 87
    # cleanliness: -0.3/h * 5h = -1.5 → int(90-1.5) = int(88.5) = 88
    assert p.cleanliness == 88


def test_apply_decay_capped_at_50():
    from datetime import datetime, timedelta
    p = Pet(name="小白", hunger=100, mood=100, cleanliness=100)
    # 模拟 100 小时前
    p.last_decay = (datetime.now() - timedelta(hours=100)).isoformat()
    p.apply_decay()
    # 总衰减封顶 -50
    assert p.hunger >= 50
    assert p.mood >= 50
    assert p.cleanliness >= 50


def test_apply_decay_zero_hunger_deducts_exp():
    from datetime import datetime, timedelta
    p = Pet(name="小白", hunger=0, exp=100)
    p.last_decay = (datetime.now() - timedelta(hours=2)).isoformat()
    p.apply_decay()
    # hunger=0 时每小时扣 10 经验，2 小时扣 20
    assert p.exp == 80
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/pet/test_pet.py -v`
Expected: FAIL with `AttributeError: 'Pet' object has no attribute 'apply_decay'`

- [ ] **Step 3: 实现 apply_decay**

```python
# 追加到 core/pet/pet.py 的 Pet 类内部

    # 衰减速率（每小时）— v2 平衡：周末两天不上线不会触底
    HUNGER_DECAY_PER_HOUR = 1.5
    MOOD_DECAY_PER_HOUR = 0.5
    CLEANLINESS_DECAY_PER_HOUR = 0.3
    MAX_DECAY_CAP = 50  # 单次离线衰减封顶
    HUNGER_ZERO_EXP_PENALTY = 10  # hunger=0 时每小时扣经验

    def apply_decay(self) -> dict:
        """应用离线衰减，返回衰减信息。"""
        from datetime import datetime

        if not self.last_decay:
            self.last_decay = datetime.now().isoformat()
            return {"hours": 0}

        try:
            last = datetime.fromisoformat(self.last_decay)
        except (ValueError, TypeError):
            self.last_decay = datetime.now().isoformat()
            return {"hours": 0}

        now = datetime.now()
        hours = (now - last).total_seconds() / 3600.0
        if hours < 0.1:  # 不到 6 分钟，不衰减
            return {"hours": 0}

        # 计算各项衰减
        hunger_decay = min(self.MAX_DECAY_CAP, hours * self.HUNGER_DECAY_PER_HOUR)
        mood_decay = min(self.MAX_DECAY_CAP, hours * self.MOOD_DECAY_PER_HOUR)
        cleanliness_decay = min(self.MAX_DECAY_CAP, hours * self.CLEANLINESS_DECAY_PER_HOUR)

        # cleanliness 低时心情加速衰减
        if self.cleanliness < 30:
            mood_decay *= 2

        self.hunger = max(0, int(self.hunger - hunger_decay))
        self.mood = max(0, int(self.mood - mood_decay))
        self.cleanliness = max(0, int(self.cleanliness - cleanliness_decay))

        # hunger=0 时扣经验
        exp_loss = 0
        if self.hunger == 0:
            exp_loss = int(hours * self.HUNGER_ZERO_EXP_PENALTY)
            self.exp = max(0, self.exp - exp_loss)

        self.last_decay = now.isoformat()

        return {
            "hours": round(hours, 1),
            "hunger_loss": int(hunger_decay),
            "mood_loss": int(mood_decay),
            "cleanliness_loss": int(cleanliness_decay),
            "exp_loss": exp_loss,
        }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/pet/test_pet.py -v`
Expected: 14 passed (原 11 + 新 3)

- [ ] **Step 5: 提交**

```bash
git add core/pet/pet.py tests/pet/test_pet.py
git commit -m "feat(pet): add offline attribute decay with 50-point cap"
```

---

## Task 9: REPL /pet 命令分发 + 启动页宠物子区块

**Files:**
- Modify: `repl.py` (加 `_cmd_pet` 方法 + 启动页宠物子区块 + 初始化 pet 属性)
- Modify: `core/pet/__init__.py` (导出新类)

**Interfaces:**
- Consumes: Task 1-8 所有模块
- Produces: REPL 内 `/pet` 子命令 + 启动页宠物展示

- [ ] **Step 1: 修改 repl.py 导入和初始化**

在 `repl.py` 顶部导入区追加：

```python
from core.pet.pet import Pet
from core.pet.storage import PetStorage
from core.pet.art import ArtLibrary
from core.pet.interact import PetInteractor, InteractError
from core.pet.tasks import DailyTaskManager
from core.pet.shop import Shop, ShopError
```

在 `REPL.__init__` 末尾追加：

```python
        # 虚拟宠物
        self.pet: Optional[Pet] = None
        self.pet_storage = PetStorage()
        self.pet_interactor = PetInteractor()
        self.task_manager = DailyTaskManager()
        self.shop = Shop()
        self.art_lib = ArtLibrary()
        # 加载宠物 + 应用衰减
        self.pet = self.pet_storage.load()
        if self.pet is not None:
            self.pet.apply_decay()
            self.pet_storage.save(self.pet)
```

- [ ] **Step 2: 在 COMMAND_LIST 加 /pet 命令**

在 `repl.py` 的 `COMMAND_LIST` 列表末尾（`/quit` 之前）插入：

```python
    ("/pet",     "虚拟宠物（adopt/feed/play/train/wash/sleep/shop/tasks）"),
```

- [ ] **Step 3: 在 _handle_command 加分发**

在 `_handle_command` 方法的 elif 链中加（`/theme` 之前）：

```python
        elif cmd == "/pet":
            self._cmd_pet(arg)
```

- [ ] **Step 4: 实现 _cmd_pet 方法**

在 REPL 类中添加：

```python
    def _cmd_pet(self, arg: str) -> None:
        """虚拟宠物子命令。"""
        parts = arg.split(maxsplit=1)
        sub = parts[0].lower() if parts else ""
        sub_arg = parts[1].strip() if len(parts) > 1 else ""

        if sub in ("", "status"):
            self._pet_show_status()
        elif sub == "adopt":
            self._pet_adopt(sub_arg)
        elif sub == "feed":
            self._pet_interact("feed")
        elif sub == "play":
            self._pet_interact("play")
        elif sub == "train":
            self._pet_interact("train")
        elif sub == "wash":
            self._pet_interact("wash")
        elif sub == "sleep":
            self._pet_interact("sleep")
        elif sub == "name":
            self._pet_rename(sub_arg)
        elif sub == "tasks":
            self._pet_show_tasks()
        elif sub == "shop":
            self._pet_show_shop()
        elif sub == "buy":
            self._pet_buy(sub_arg)
        elif sub == "use":
            self._pet_use(sub_arg)
        else:
            console.print("[bold]虚拟宠物[/bold] [dim](/pet 子命令)[/dim]\n")
            console.print("  [cyan]/pet[/cyan]                查看宠物状态")
            console.print("  [cyan]/pet adopt <名字>[/cyan]    领养宠物")
            console.print("  [cyan]/pet feed[/cyan]            喂食")
            console.print("  [cyan]/pet play[/cyan]            玩耍")
            console.print("  [cyan]/pet train[/cyan]           训练")
            console.print("  [cyan]/pet wash[/cyan]            清洁")
            console.print("  [cyan]/pet sleep[/cyan]           睡觉（恢复能量）")
            console.print("  [cyan]/pet name <新名>[/cyan]     改名")
            console.print("  [cyan]/pet tasks[/cyan]           每日任务")
            console.print("  [cyan]/pet shop[/cyan]            道具商店")
            console.print("  [cyan]/pet buy <id>[/cyan]        购买道具")
            console.print("  [cyan]/pet use <id>[/cyan]        使用道具")

    def _pet_show_status(self) -> None:
        """显示宠物详情面板。"""
        if self.pet is None:
            console.print("[yellow]还没有宠物，输入 /pet adopt <名字> 领养[/yellow]")
            return
        p = self.pet
        branch_label = {"scholar": "学者", "warrior": "战士", "artisan": "工匠"}.get(p.branch, "未分系")
        art = self.art_lib.get(p.branch, p.level)
        color = {"scholar": "cyan", "warrior": "red", "artisan": "yellow"}.get(p.branch, "white")

        from rich.text import Text
        from rich.panel import Panel
        from rich.align import Align
        from rich.console import Group

        art_text = Text(art, style=color)
        info = Group(
            art_text,
            Text(""),
            Text.from_markup(f"  [bold magenta]{p.name}[/bold magenta]  Lv{p.level} {branch_label}"),
            Text(""),
            Text.from_markup(f"  ❤️ 饱食   {p.hunger}/100"),
            Text.from_markup(f"  😊 心情   {p.mood}/100"),
            Text.from_markup(f"  ⚡ 能量   {p.energy}/100"),
            Text.from_markup(f"  🛁 清洁   {p.cleanliness}/100"),
            Text(""),
            Text.from_markup(f"  ✨ 经验   {p.exp}/{p.exp_needed()}" + (
                f"  [dim]→Lv{p.level+1} 还需 {p.exp_remaining()}[/dim]" if p.level < 10 else "  [dim](最高级)[/dim]"
            )),
        )
        console.print(Panel(info, border_style="magenta", title=f"[bold magenta]🐾 {p.name}[/bold magenta]", padding=(1, 2)))

    def _pet_adopt(self, name: str) -> None:
        """领养宠物。"""
        if self.pet is not None:
            console.print(f"[yellow]已经领养过 {self.pet.name} 了[/yellow]")
            return
        if not name:
            console.print("[yellow]用法: /pet adopt <名字>[/yellow]")
            return
        self.pet = self.pet_storage.create(name)
        console.print(f"[bold green]✓ 领养成功！[/bold green] 你的宠物叫 [magenta]{name}[/magenta]")
        self._pet_show_status()

    def _pet_interact(self, action: str) -> None:
        """执行互动。"""
        if self.pet is None:
            console.print("[yellow]还没有宠物，/pet adopt 领养[/yellow]")
            return
        try:
            method = getattr(self.pet_interactor, action)
            result = method(self.pet)
            self.pet_storage.save(self.pet)
            console.print(f"[green]{result['message']}[/green]")
        except InteractError as e:
            console.print(f"[yellow]{e}[/yellow]")

    def _pet_rename(self, new_name: str) -> None:
        """改名。"""
        if self.pet is None:
            console.print("[yellow]还没有宠物[/yellow]")
            return
        if not new_name:
            console.print("[yellow]用法: /pet name <新名字>[/yellow]")
            return
        old = self.pet.name
        self.pet.name = new_name
        self.pet_storage.save(self.pet)
        console.print(f"[green]✓ {old} 改名为 {new_name}[/green]")

    def _pet_show_tasks(self) -> None:
        """显示每日任务。"""
        if self.pet is None:
            console.print("[yellow]还没有宠物[/yellow]")
            return
        # 检查是否需要刷新
        if self.task_manager._should_refresh(self.pet):
            self.task_manager.refresh(self.pet)
            self.pet_storage.save(self.pet)
        tasks = self.task_manager.list_tasks(self.pet)
        if not tasks:
            console.print("[yellow]今日任务已刷新，请稍后再试[/yellow]")
            return
        from rich.table import Table
        t = Table(title="📋 今日任务", border_style="magenta")
        t.add_column("任务", style="white")
        t.add_column("进度", style="cyan")
        t.add_column("奖励", style="yellow")
        t.add_column("状态", style="green")
        for task in tasks:
            status = "✓ 完成" if task["completed"] else "进行中"
            t.add_row(
                task["description"],
                f"{task['progress']}/{task['target']}",
                f"+{task['reward']}",
                status,
            )
        console.print(t)

    def _pet_show_shop(self) -> None:
        """显示商店。"""
        from rich.table import Table
        t = Table(title="🛒 道具商店", border_style="yellow")
        t.add_column("ID", style="cyan")
        t.add_column("名称", style="white")
        t.add_column("价格", style="yellow")
        t.add_column("效果", style="dim")
        for item in self.shop.list_items():
            effect_str = str(item["effect"])
            t.add_row(item["id"], item["name"], f"{item['price']} 经验", effect_str)
        console.print(t)
        console.print("[dim]用 /pet buy <id> 购买，/pet use <id> 使用[/dim]")

    def _pet_buy(self, item_id: str) -> None:
        """购买道具。"""
        if self.pet is None:
            console.print("[yellow]还没有宠物[/yellow]")
            return
        if not item_id:
            console.print("[yellow]用法: /pet buy <id>[/yellow]")
            return
        try:
            result = self.shop.buy(self.pet, item_id)
            self.pet_storage.save(self.pet)
            console.print(f"[green]{result['message']}[/green]")
        except ShopError as e:
            console.print(f"[red]{e}[/red]")

    def _pet_use(self, item_id: str) -> None:
        """使用道具。"""
        if self.pet is None:
            console.print("[yellow]还没有宠物[/yellow]")
            return
        if not item_id:
            console.print("[yellow]用法: /pet use <id>[/yellow]")
            return
        try:
            result = self.shop.use(self.pet, item_id)
            self.pet_storage.save(self.pet)
            console.print(f"[green]{result['message']}[/green]")
        except ShopError as e:
            console.print(f"[red]{e}[/red]")
```

- [ ] **Step 5: 启动页加宠物子区块（紧凑横版，2 行）**

修改 `repl.py:83` 的 `_render_welcome_panel` 函数签名加 `pet` 参数，并在 `repl.py:114` 的 `left_content = Group(` 内最前面插入宠物紧凑区块。

**修改 1**：函数签名（`repl.py:83`）

```python
# 原：def _render_welcome_panel(stats: dict, llm_available: bool) -> None:
def _render_welcome_panel(stats: dict, llm_available: bool, pet: Optional["Pet"] = None) -> None:
```

**修改 2**：在 `repl.py:114` 的 `left_content = Group(` 内最前面插入宠物 2 行

原代码（`repl.py:113-126`）：
```python
    status_line = "[green]✓ 在线[/green]" if llm_available else "[red]✗ 未配置[/red]"
    left_content = Group(
        Text("📊 知识库状态", style=f"bold {t.colors['secondary']}"),
        Text(""),
        Text.from_markup(f"  文档总数   [{t.colors['secondary']}]{stats['documents']}[/{t.colors['secondary']}]"),
        Text.from_markup(f"  分块总数   [{t.colors['secondary']}]{stats['chunks']}[/{t.colors['secondary']}]"),
        Text.from_markup(f"  总 Tokens  [{t.colors['secondary']}]{stats['total_tokens']:,}[/{t.colors['secondary']}]"),
        Text.from_markup(f"  原文件大小 [{t.colors['secondary']}]{stats['total_size_mb']} MB[/{t.colors['secondary']}]"),
        Text(""),
        Text.from_markup(f"  LLM 状态   {status_line}"),
        Text.from_markup(f"  模型       [dim]{settings.llm_model}[/dim]"),
        Text(""),
        Text.from_markup(f"  当前主题   [{t.colors['primary']}]{t.label}[/{t.colors['primary']}] [dim](/theme 切换)[/dim]"),
    )
```

改为（在 "📊 知识库状态" 之前插入宠物 2 行 + 分隔空行）：
```python
    status_line = "[green]✓ 在线[/green]" if llm_available else "[red]✗ 未配置[/red]"
    # 宠物紧凑横版：1 行头像 + 1 行属性条（共 2 行）
    pet_line1, pet_line2 = _render_pet_compact(pet) if pet else _render_pet_empty_compact()
    left_content = Group(
        pet_line1,  # 🐾 小白 (Lv5 学者)
        pet_line2,  # ❤️80 ⚡90 😊75 🛁88 ✨120/200
        Text("─" * 30, style="dim"),  # 分隔线
        Text("📊 知识库状态", style=f"bold {t.colors['secondary']}"),
        Text(""),
        Text.from_markup(f"  文档总数   [{t.colors['secondary']}]{stats['documents']}[/{t.colors['secondary']}]"),
        Text.from_markup(f"  分块总数   [{t.colors['secondary']}]{stats['chunks']}[/{t.colors['secondary']}]"),
        Text.from_markup(f"  总 Tokens  [{t.colors['secondary']}]{stats['total_tokens']:,}[/{t.colors['secondary']}]"),
        Text.from_markup(f"  原文件大小 [{t.colors['secondary']}]{stats['total_size_mb']} MB[/{t.colors['secondary']}]"),
        Text(""),
        Text.from_markup(f"  LLM 状态   {status_line}"),
        Text.from_markup(f"  模型       [dim]{settings.llm_model}[/dim]"),
        Text(""),
        Text.from_markup(f"  当前主题   [{t.colors['primary']}]{t.label}[/{t.colors['primary']}] [dim](/theme 切换)[/dim]"),
    )
```

**新增函数**（放在 `_render_welcome_panel` 之后，`HELP_TEXT` 之前，约 `repl.py:196`）：

```python
def _render_pet_compact(pet: "Pet") -> tuple:
    """渲染宠物紧凑横版（2 行）。返回 (line1, line2)。"""
    branch_label = {"scholar": "学者", "warrior": "战士", "artisan": "工匠"}.get(pet.branch, "未分系")
    color = {"scholar": "cyan", "warrior": "red", "artisan": "yellow"}.get(pet.branch, "white")
    # 单行 Emoji 头像（按系别）
    avatar = {"scholar": "🦉", "warrior": "🐺", "artisan": "🦡"}.get(pet.branch, "🐣")
    line1 = Text.from_markup(
        f"  [{color}]{avatar}[/{color}] [bold magenta]{pet.name}[/bold magenta] "
        f"[dim]Lv{pet.level} {branch_label}[/dim]"
    )
    line2 = Text.from_markup(
        f"  ❤️{pet.hunger} ⚡{pet.energy} 😊{pet.mood} 🛁{pet.cleanliness} "
        f"✨{pet.exp}/{pet.exp_needed()}"
        + (f" [dim]→{pet.exp_remaining()}[/dim]" if pet.level < 10 else " [dim](满级)[/dim]")
    )
    return line1, line2


def _render_pet_empty_compact() -> tuple:
    """未领养宠物的占位（2 行）。"""
    return (
        Text.from_markup("  🐣 [bold magenta]虚拟宠物[/bold magenta] [dim]/pet adopt 领养[/dim]"),
        Text(""),  # 空行占位
    )
```

**修改 3**：`REPL.run()` 调用处（约 `repl.py:355`）

```python
# 原：_render_welcome_panel(stats, self.llm_available)
_render_welcome_panel(stats, self.llm_available, pet=self.pet)
```

- [ ] **Step 6: 运行语法检查**

Run: `python -c "import ast; ast.parse(open('repl.py').read()); print('OK')"`
Expected: OK

- [ ] **Step 7: 提交**

```bash
git add repl.py core/pet/__init__.py
git commit -m "feat(pet): integrate pet into REPL with /pet commands and welcome panel"
```

---

## Task 10: 行为埋点（9 处）

**Files:**
- Modify: `repl.py` (在 9 个方法中加埋点)

**Interfaces:**
- Consumes: Task 9 的 `self.pet`
- Produces: 经验获取触发

- [ ] **Step 1: 加埋点辅助方法**

在 REPL 类中加：

```python
    def _pet_gain_exp(self, amount: int, action_type: str) -> None:
        """宠物获取经验（埋点辅助方法）。"""
        if self.pet is None:
            return
        events = self.pet.gain_exp(amount, action_type)
        # 检查每日任务进度
        completed = self.task_manager.check_progress(self.pet, action_type)
        # 发放任务奖励
        for task in completed:
            self.pet.gain_exp(task["reward"], "task_reward")
            console.print(f"[green]✓ 每日任务完成: {task['description']} (+{task['reward']} 经验)[/green]")
        # 升级提示
        if events.get("leveled_up"):
            console.print(f"[bold magenta]🎉 {self.pet.name} 升到 Lv{events['new_level']}！[/bold magenta]")
        # 分系提示
        if events.get("branched"):
            branch_label = {"scholar": "学者", "warrior": "战士", "artisan": "工匠"}.get(events["branch"], "")
            console.print(f"[bold magenta]✨ {self.pet.name} 进化为 {branch_label}系！[/bold magenta]")
        self.pet_storage.save(self.pet)
```

- [ ] **Step 2: 在 9 处方法中加埋点**

在以下方法的成功执行后加 `self._pet_gain_exp(...)` 调用：

1. `_handle_chat` 末尾（LLM 回答成功后）：
```python
self._pet_gain_exp(10, "qa")
# 同时恢复能量
if self.pet:
    self.pet.energy = min(100, self.pet.energy + 2)
    self.pet_storage.save(self.pet)
```

2. `_cmd_ingest` 在每个文件入库成功后（在 `if result is True:` 分支内）：
```python
self._pet_gain_exp(30, "ingest")
```

3. `_cmd_analyze` 成功后：
```python
self._pet_gain_exp(15, "analyze")
```

4. `_cmd_report` 成功后：
```python
self._pet_gain_exp(20, "report")
```

5. `_cmd_read` 进入阅读模式后：
```python
self._pet_gain_exp(10, "read")
```

6. `_cmd_compare` 成功后：
```python
self._pet_gain_exp(10, "compare")
```

7. `_cmd_agent` 成功后：
```python
self._pet_gain_exp(15, "agent")
```

8. `_cmd_smart` 路由成功后：
```python
self._pet_gain_exp(8, "smart")
```

9. `_cmd_graph` build 子命令成功后：
```python
self._pet_gain_exp(30, "graph_build")
```

**经验数值表（v2，平衡后）**：

| 行为 | 经验 | 备注 |
|---|---|---|
| qa | 10 | 10 个问题 ≈ 1 次升级（Lv1→2 需 100） |
| ingest | 30 | 入库 4 个文档升 Lv2 |
| analyze | 15 | |
| agent | 15 | |
| report | 20 | |
| read | 10 | |
| compare | 10 | |
| smart | 8 | |
| graph_build | 30 | 高奖励（一次性）|

10. `run.py` 的 `retag` 命令成功后（这条需要改 run.py，但 retag 是 CLI 命令不在 REPL 里，可以跳过或加到 REPL 的 /retag 等价命令里——目前 REPL 没有 /retag，所以跳过这条，只在 9 处埋点）。

- [ ] **Step 3: 运行语法检查**

Run: `python -c "import ast; ast.parse(open('repl.py').read()); print('OK')"`
Expected: OK

- [ ] **Step 4: 手动测试**

启动 REPL，领养宠物，入库一个文件，检查经验是否增加：

```bash
ima
# 在 REPL 内：
/pet adopt 小白
/ingest test_data/sample.md
/pet
# 应该看到 exp 增加 50
```

- [ ] **Step 5: 提交**

```bash
git add repl.py
git commit -m "feat(pet): add 9 behavior tracking points for exp gain"  
# 注：原计划 10 处，retag 是 CLI 命令不在 REPL 内，实际 9 处
```

---

## Task 11: 创建 ASCII 艺术文件（35 个）

**Files:**
- Create: `core/pet/arts/none_1.txt` 到 `none_5.txt`（5 个通用阶段）
- Create: `core/pet/arts/scholar_1.txt` 到 `scholar_10.txt`（10 个学者系）
- Create: `core/pet/arts/warrior_1.txt` 到 `warrior_10.txt`（10 个战士系）
- Create: `core/pet/arts/artisan_1.txt` 到 `artisan_10.txt`（10 个工匠系）

**说明**：此任务不需要写代码，只需要创建 35 个 ASCII 艺术文本文件。小尺寸变体由代码动态截断。

**尺寸规范（统一风格）**：
- 每个文件 8-12 行（含标签行）
- 宽度 ≤ 20 字符（避免启动页溢出）
- 最后一行必须是 `[系·名 LvX]` 标签（如 `[学者·小鸮 Lv6]`）
- 通用阶段（none_1-5）用动物幼崽主题（蛋→幼崽→小兽→亚成→进化中）
- 学者系（scholar_6-10）用猫头鹰主题，逐级加大 + 加书卷/眼镜/法袍
- 战士系（warrior_6-10）用狼主题，逐级加大 + 加火焰/利爪/铠甲
- 工匠系（artisan_6-10）用獾主题，逐级加大 + 加工具/护目镜/工坊
- Emoji 头像（启动页紧凑横版用）：none=🐣, scholar=🦉, warrior=🐺, artisan=🦡

- [ ] **Step 1: 创建通用阶段 5 个文件**

`core/pet/arts/none_1.txt`（蛋）：
```
      .---.
     /     \
    |       |
     \     /
      '---'
     [Lv1 蛋]
```

`core/pet/arts/none_2.txt`（幼崽）：
```
      /\_/\
     ( o.o )
      > ^ <
     /  _  \
    [Lv2 幼崽]
```

`core/pet/arts/none_3.txt`（小兽）：
```
       /\_/\
      ( o.o )
       > ^ <
      /  _  \
     / /   \ \
    ( )     ( )
    [Lv3 小兽]
```

`core/pet/arts/none_4.txt`（亚成）：
```
        /\___/\
       (  o o  )
        \  ^  /
        /  _  \
       / /   \ \
      ( )     ( )
       |     |
      [Lv4 亚成]
```

`core/pet/arts/none_5.txt`（分系动画 - 三个问号表示选择中）：
```
         ???
      ??  ?  ??
         ???
       /\___/\
      (  ? ?  )
       \  ^  /
      [Lv5 进化中...]
```

- [ ] **Step 2: 创建学者系 10 个文件（猫头鹰主题，青色）**

`core/pet/arts/scholar_6.txt`（小鸮）：
```
        ,___,
        (O,O)
        /)  )
        "" "
     [学者·小鸮 Lv6]
```

`scholar_1.txt` 到 `scholar_5.txt`（Lv1-5 通用阶段可复用 none 系或留空）、`scholar_7.txt` 到 `scholar_10.txt`：依次加大尺寸 + 增加细节（书卷、眼镜、法袍等元素）。

- [ ] **Step 3: 创建战士系 10 个文件（狼主题，红色）**

`warrior_6.txt`（幼狼）：
```
       /\___/\
      (  o o  )
       \  w  /
       /|   |\
      / |   | \
     [战士·幼狼 Lv6]
```

依此类推到 `warrior_10.txt`（神狼，加火焰、利爪等元素）。`warrior_1.txt` 到 `warrior_5.txt` 同理。

- [ ] **Step 4: 创建工匠系 10 个文件（獾主题，黄色）**

`artisan_6.txt`（小獾）：
```
       /\___/\
      (  o o  )
       \  ~  /
       /|   |\
      / |   | \
     [工匠·小獾 Lv6]
```

依此类推到 `artisan_10.txt`（神匠獾，加工具、护目镜等元素）。`artisan_1.txt` 到 `artisan_5.txt` 同理。

- [ ] **Step 5: 提交**

```bash
git add core/pet/arts/
git commit -m "feat(pet): add 35 ASCII art forms (5 generic + 30 branched)"
```

---

## Task 12: 集成测试 + 错误处理打磨

**Files:**
- Create: `tests/pet/test_integration.py`
- Modify: 各模块（根据测试发现的问题修复）

- [ ] **Step 1: 写集成测试**

```python
# tests/pet/test_integration.py
"""集成测试：模拟完整使用流程。"""
from core.pet.pet import Pet
from core.pet.storage import PetStorage
from core.pet.interact import PetInteractor
from core.pet.tasks import DailyTaskManager
from core.pet.shop import Shop


def test_full_lifecycle(tmp_path):
    """完整生命周期：领养 → 入库 → 升级 → 互动。"""
    storage = PetStorage(storage_path=tmp_path)
    pet = storage.create("小白")
    assert pet.level == 1

    # 模拟入库 2 个文档
    pet.gain_exp(50, "ingest")
    pet.gain_exp(50, "ingest")
    assert pet.level == 2  # 100 经验升 Lv2

    storage.save(pet)

    # 重新加载
    loaded = storage.load()
    assert loaded.name == "小白"
    assert loaded.level == 2


def test_branch_determination_after_lv5(tmp_path):
    """Lv5 时根据行为统计自动分系。"""
    pet = Pet(name="小白", level=4, exp=780)
    # 大量 qa 行为
    for _ in range(20):
        pet.gain_exp(5, "qa")
    # 升到 Lv5 应该触发分系
    assert pet.level >= 5
    assert pet.branch == "scholar"  # qa 多


def test_daily_task_completes_on_qa(tmp_path):
    """每日任务在问答时完成。"""
    pet = Pet(name="小白")
    mgr = DailyTaskManager()
    mgr.refresh(pet=pet)
    # 强制设置 qa5 任务
    pet.daily_tasks = [{
        "task_id": "qa5",
        "description": "问 5 个问题",
        "target": 5,
        "reward": 80,
        "progress": 4,
        "completed": False,
        "action": "qa",
    }]
    completed = mgr.check_progress(pet, "qa")
    assert len(completed) == 1
    assert completed[0]["reward"] == 80


def test_shop_buy_and_use_flow(tmp_path):
    """购买并使用道具。"""
    pet = Pet(name="小白", exp=500, hunger=50)
    shop = Shop()
    shop.buy(pet, "fish")
    assert pet.exp == 450
    shop.use(pet, "fish")
    assert pet.hunger == 80


def test_decay_applied_on_load(tmp_path):
    """加载时应用衰减。"""
    from datetime import datetime, timedelta
    storage = PetStorage(storage_path=tmp_path)
    pet = storage.create("小白")
    pet.hunger = 100
    pet.last_decay = (datetime.now() - timedelta(hours=10)).isoformat()
    storage.save(pet)

    loaded = storage.load()
    decay = loaded.apply_decay()
    assert decay["hours"] >= 10
    assert loaded.hunger < 100  # 衰减了
```

- [ ] **Step 2: 运行所有测试**

Run: `pytest tests/pet/ -v`
Expected: 所有测试通过

- [ ] **Step 3: 修复发现的问题**

根据测试结果修复 bug。

- [ ] **Step 4: 提交**

```bash
git add tests/pet/test_integration.py
git commit -m "test(pet): add integration tests for full lifecycle"
```

---

## 自检清单

完成所有任务后，对照设计文档检查：

- [ ] `core/pet/` 模块完整（pet/storage/art/interact/tasks/shop 6 个文件）
- [ ] 35 个 ASCII 艺术文件已创建
- [ ] REPL 启动页显示宠物子区块
- [ ] `/pet` 子命令可用（11 个子命令）
- [ ] 9 处埋点触发经验获取
- [ ] Lv5 自动分系
- [ ] 每日任务系统工作
- [ ] 道具商店可购买/使用
- [ ] 离线衰减计算正确
- [ ] 所有单元测试通过
- [ ] 集成测试通过

## 执行选择

计划已完成并保存到 `docs/superpowers/plans/2026-07-06-virtual-pet.md`。两种执行方式：

**1. Subagent 驱动（推荐）** - 每个任务派发新 subagent，任务间审查，迭代快

**2. 内联执行** - 在当前会话中按批次执行，每个检查点审查

选哪种？
