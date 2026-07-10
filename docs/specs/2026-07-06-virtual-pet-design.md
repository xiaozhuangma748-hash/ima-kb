# IMA 虚拟宠物系统 · 设计文档

> **日期**：2026-07-06
> **状态**：设计已确认，待实现
> **作者**：用户 + AI 协同设计
> **关联项目**：IMA 个人知识库 v4.0

---

## 0. 背景与目标

### 起源

用户希望为 IMA 个人知识库增加一个**虚拟宠物系统**，宠物随知识库内容增加而升级、随用户使用习惯而进化形态。核心诉求：**让知识库管理游戏化，提升使用粘性**。

### 设计原则

1. **渐进式**：宠物随知识库自然成长，不需要刻意"刷"
2. **行为驱动**：使用习惯决定进化方向（不手动选分支）
3. **视觉化**：ASCII 艺术，与项目 CLI 风格一致
4. **轻干扰**：状态栏被动展示 + 偶尔主动互动

### 非目标

- 不做多用户/社交（暂不考虑）
- 不做付费/商城真实货币（仅游戏内经验兑换）
- 不做移动端（仅 REPL + Web）

---

## 1. 模块架构

```
core/pet/
├── __init__.py
├── pet.py          # Pet 类：状态、属性、升级逻辑、分系判定
├── art.py          # ASCII 艺术库（35 形态加载器）
├── arts/           # ASCII 艺术文本文件（每形态一个 .txt，共 35 个）
│   ├── none_1.txt ... none_5.txt         # 通用阶段 Lv1-5
│   ├── scholar_1.txt ... scholar_10.txt  # 学者系 Lv1-10
│   ├── warrior_1.txt ... warrior_10.txt  # 战士系 Lv1-10
│   └── artisan_1.txt ... artisan_10.txt  # 工匠系 Lv1-10
├── tasks.py        # 每日任务系统（任务池、刷新、完成判定）
├── shop.py         # 道具商店（道具列表、购买、使用）
├── interact.py     # 互动命令处理（feed/play/train/wash/sleep）
└── storage.py      # 持久化（JSON 读写）

repl.py             # 加 /pet 子命令分发 + 启动页加宠物子区块
config.py           # 加 pet 相关配置（衰减速率等）
```

### 埋点位置

在以下方法成功执行后调用 `pet.gain_exp(amount, action_type)`：

| 方法 | 经验 | 行为类型 |
|---|---|---|
| `_cmd_ingest`（每入库 1 个文件） | +30 | ingest |
| `_handle_chat`（每次问答） | +10 | qa |
| `_cmd_analyze` | +15 | analyze |
| `_cmd_report` | +20 | report |
| `_cmd_agent` | +15 | agent |
| `_cmd_read` | +10 | read |
| `_cmd_compare` | +10 | compare |
| `_cmd_graph build` | +30 | graph_build |
| `/smart` 路由成功 | +8 | smart |
| `ima retag` | +10 | retag |

---

## 2. 宠物状态模型

```python
@dataclass
class Pet:
    # 基本信息
    name: str                        # 宠物名字（/pet name 可改）
    level: int = 1                   # 1-10
    exp: int = 0                     # 当前经验
    branch: Optional[str] = None     # None / "scholar" / "warrior" / "artisan"

    # 5 维属性（0-100，超过 100 截断）
    hunger: int = 80                 # 饱食度（高=饱，低=饿，0 时扣经验）
    mood: int = 80                   # 心情（低时经验获取 -30%）
    energy: int = 100                # 能量（互动消耗，问答恢复）
    cleanliness: int = 80            # 清洁度（低时心情加速衰减）
    exp_multi: float = 1.0           # 经验加成倍率（来自道具，限时）

    # 行为统计（用于 Lv5 自动分系）
    stats: dict = field(default_factory=lambda: {
        "ingest": 0, "qa": 0, "read": 0, "report": 0,    # scholar 倾向
        "agent": 0, "compare": 0,                         # warrior 倾向
        "analyze": 0, "smart": 0, "retag": 0,             # artisan 倾向
        "graph_build": 0,                                 # 三系都加（中性）
    })

    # 道具栏
    inventory: list = field(default_factory=list)  # [{"item_id": "fish", "count": 3}]

    # 时间戳（用于离线衰减计算）
    last_interact: str = ""          # ISO 时间
    last_decay: str = ""             # 上次属性衰减时间
    created_at: str = ""

    # 每日任务
    daily_tasks: list = field(default_factory=list)
    daily_reset_at: str = ""
    # 任务历史（7 天不重复用）：[{"date": "2026-07-05", "task_ids": [...]}]
    task_history: list = field(default_factory=list)

    # 限时道具效果
    active_effects: list = field(default_factory=list)  # [{"effect": "exp_multi", "value": 2.0, "expires_at": "..."}]
```

### Pet 类方法

| 方法 | 说明 |
|---|---|
| `exp_needed()` | 当前等级升到下一级所需经验（纯公式 `floor(100 * level^1.5)`，无 MAX_LEVEL 守卫） |
| `exp_remaining()` | 距离升级还差多少经验（Lv10 时返回 0） |
| `gain_exp(amount, action_type)` | 获取经验，可能触发升级和分系，返回事件 dict |
| `_determine_branch()` | 根据 stats 判定分系，平局时 random.choice 随机选择 |
| `apply_decay()` | 应用离线衰减，返回衰减信息 dict |
| `clean_expired_effects()` | 清理 active_effects 中已过期的限时效果，返回清理数量 |
| `get_active_exp_multi()` | 获取当前生效的经验加成倍率（综合 exp_multi 和 active_effects） |
| `has_auto_revive()` | 是否持有未触发的凤凰之羽效果 |
| `consume_auto_revive()` | 消耗一个凤凰之羽效果（hunger=0 时免扣经验） |
| `reset_stats()` | 重置行为统计（stats），不影响等级/经验/属性 |
| `clear_active_effects()` | 清空所有限时效果，返回清除数量 |

### 升级阈值

`exp_needed = floor(100 * level^1.5)`

| 等级 | 升级所需经验 | 累计经验 |
|---|---|---|
| 1→2 | 100 | 100 |
| 2→3 | 282 | 382 |
| 3→4 | 519 | 901 |
| 4→5 | 800 | 1701 |
| 5→6 | 1118 | 2819 |
| 6→7 | 1469 | 4288 |
| 7→8 | 1852 | 6140 |
| 8→9 | 2262 | 8402 |
| 9→10 | 2700 | 11102 |

### 分系判定（Lv5 时触发）

将 `stats` 字典按 3 系分组求和，取最大组作为 branch：

```python
SCHOLAR_KEYS = {"ingest", "qa", "read", "report"}
WARRIOR_KEYS = {"agent", "compare"}
ARTISAN_KEYS = {"analyze", "smart", "retag"}
# graph_build 中性，不计入分系判定

scholar_score = sum(stats[k] for k in SCHOLAR_KEYS)
warrior_score = sum(stats[k] for k in WARRIOR_KEYS)
artisan_score = sum(stats[k] for k in ARTISAN_KEYS)

scores = [("scholar", scholar_score), ("warrior", warrior_score), ("artisan", artisan_score)]
max_score = max(s for _, s in scores)
# 平局时随机选一个（避免永远 scholar）
winners = [name for name, s in scores if s == max_score]
branch = random.choice(winners) if len(winners) > 1 else winners[0]
```

若并列则随机选择（避免永远偏向 scholar），并提示用户「检测到你偏向 XXX 系，已为你进化为 XXX」。

---

## 3. 5 维属性与衰减

| 属性 | 范围 | 衰减速率 | 影响 |
|---|---|---|---|
| hunger | 0-100 | -1.5/小时 | 0 时每小时扣 10 经验 |
| mood | 0-100 | -0.5/小时 | <30 时经验获取 -30% |
| energy | 0-100 | 不自动衰减 | 互动消耗，问答 +2/次 |
| cleanliness | 0-100 | -0.3/小时 | <30 时心情衰减速率 ×2 |
| exp_multi | 1.0 | 道具限时 | 经验获取倍率 |

### 离线衰减

启动时计算 `last_decay` 到现在的时间差，一次性扣减属性：
- 总衰减封顶 -50（防止长期不玩归零）
- 若离线 >7 天，提示「小X很想你～」（注：自动恢复 hunger 至 50 的功能尚未实现，当前仅提示）

### 能量恢复

- 每次问答 +2 energy（封顶 100）（注：此功能尚未实现，当前 energy 仅通过 `/pet sleep` 恢复）
- `/pet sleep` 一次 +50 energy，1 小时冷却

---

## 4. 互动命令

| 命令 | 作用 | 消耗 | 收益 |
|---|---|---|---|
| `/pet` | 查看宠物详情面板 | 无 | 无 |
| `/pet adopt` | 领养宠物（首次） | 0 | 创建 Lv1 蛋 |
| `/pet feed` | 喂食 | -10 energy, -5 exp | +30 hunger, +5 mood |
| `/pet play` | 玩耍 | -15 energy | +40 mood, -10 hunger, +10 exp |
| `/pet train` | 训练 | -25 energy, -10 mood | +50 exp（高效升级） |
| `/pet wash` | 清洁 | -5 energy | +50 cleanliness, +5 mood |
| `/pet sleep` | 睡觉（恢复能量） | 0（1 小时冷却） | +50 energy, +10 mood |
| `/pet name <新名>` | 改名 | 0 | 无 |
| `/pet style <风格>` | 切换人格风格（scholar/warrior/artisan/auto） | 0 | 临时覆盖分系风格 |
| `/pet reset` | 重置行为统计（stats） | 0 | 清空 stats 字典（不影响等级/经验/属性） |
| `/pet bag` | 查看道具栏 | 0 | 无 |
| `/pet tasks` | 查看每日任务进度 | 0 | 无 |
| `/pet shop` | 浏览道具商店 | 0 | 无 |
| `/pet buy <id>` | 购买道具 | 扣经验 | 道具入栏 |
| `/pet use <id>` | 使用道具 | 0 | 道具效果生效 |

### 互动限制

- energy < 10 时不能 `/pet train` / `/pet play`
- hunger < 20 时不能 `/pet train`（要先喂食）
- mood < 20 时 `/pet train` 效果减半（+25 exp 而非 +50）
- `/pet sleep` 后 1 小时内不能再 sleep（防刷）

---

## 5. 每日任务

### 刷新机制

每天 0:00 自动刷新 3 个任务。首次启动时若 `daily_reset_at` 不是今天则触发刷新。

### 任务池（12 个，每天随机抽 3 个）

| 任务 ID | 描述 | 目标 | 奖励经验 |
|---|---|---|---|
| ingest1 | 入库 1 个文档 | 1 | +100 |
| ingest3 | 入库 3 个文档 | 3 | +250 |
| qa5 | 问 5 个问题 | 5 | +80 |
| qa10 | 问 10 个问题 | 10 | +180 |
| analyze1 | 使用 /analyze 1 次 | 1 | +120 |
| agent1 | 使用 /agent 完成任务 1 次 | 1 | +150 |
| read1 | 用 /read 阅读 1 个文档 | 1 | +100 |
| report1 | 生成 1 份报告 | 1 | +150 |
| graph_build | 构建知识图谱 | 1 | +200 |
| compare1 | 用 /compare 对比 1 次 | 1 | +120 |
| smart3 | 用 /smart 路由 3 次 | 3 | +100 |
| tag_retag | 重新打标签 1 次 | 1 | +120 |

### 完成判定

在埋点处检查 `daily_tasks` 中匹配的任务，更新 progress，达成时：
1. 自动发放经验
2. 标记 `completed: true`
3. 在 REPL 显示提示 `[green]✓ 每日任务完成: XXX (+150 经验)[/green]`

---

## 6. 道具商店

| ID | 名称 | 价格（经验） | 效果 |
|---|---|---|---|
| fish | 小鱼干 | 50 | +30 hunger |
| ball | 玩具球 | 80 | +40 mood |
| soap | 洗浴套装 | 60 | +50 cleanliness |
| energy_drink | 能量饮料 | 100 | +50 energy |
| exp_potion | 经验药水 | 150 | 2 小时内 exp_multi=2.0 |
| super_food | 顶级饲料 | 150 | +50 hunger +20 mood |
| phoenix_down | 凤凰之羽 | 500 | hunger=0 时自动消耗，防止扣经验 1 次 |
| rename_card | 重置卡 | 100 | 将低于 80 的属性恢复到 80（保留高于 80 的属性） |

### 购买流程

1. `/pet buy fish` → 检查经验是否 ≥50
2. 扣 50 经验（不会扣到负数，最低保留 0）
3. 道具入栏（若已存在则 count +1）
4. 提示「✓ 购买成功，剩余经验 470」

### 使用流程

1. `/pet use fish` → 检查库存
2. 应用效果（修改属性）
3. 库存 -1
4. 提示「小白吃得津津有味 ❤️+30」

---

## 7. ASCII 艺术规格

### 形态列表（共 35 个文件）

| 等级 | 通用阶段 | 学者系 | 战士系 | 工匠系 |
|---|---|---|---|---|
| Lv1 | 蛋 | - | - | - |
| Lv2 | 幼崽 | - | - | - |
| Lv3 | 小兽 | - | - | - |
| Lv4 | 亚成 | - | - | - |
| Lv5 | 分系动画 | - | - | - |
| Lv6 | - | 小鸮 | 幼狼 | 小獾 |
| Lv7 | - | 学者鸮 | 战狼 | 匠獾 |
| Lv8 | - | 智者鸮 | 银狼 | 巧匠獾 |
| Lv9 | - | 贤者鸮 | 苍狼 | 大师獾 |
| Lv10 | - | 时空鸮 | 神狼 | 神匠獾 |

### 文件格式

- 路径：`core/pet/arts/{branch}_{level}.txt`（branch 为 `none` 时表示通用阶段）
- 尺寸：
  - **大尺寸**（详情页 `/pet` 用）：约 15 行 × 30 列
  - **小尺寸**（启动页用）：约 6 行 × 20 列（`_small` 变体由代码动态截断大尺寸前 6 行，无需单独创建文件）
- 配色（用 rich 渲染）：
  - 通用阶段：白色
  - 学者系：青色（cyan）
  - 战士系：红色（red）
  - 工匠系：黄色（yellow）

### 加载器

```python
class ArtLibrary:
    def get(self, branch: Optional[str], level: int, small: bool = False) -> str:
        """加载指定形态的 ASCII 艺术。

        Args:
            branch: None / "scholar" / "warrior" / "artisan"
            level: 1-10
            small: True 返回缩略版（启动页用）
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
            return self._fallback(branch, level, small)  # 占位符
        return path.read_text(encoding="utf-8")

    def _fallback(self, branch: Optional[str], level: int, small: bool = False) -> str:
        """占位符。采用 block-style 像素风格，避免 ??? 占位。"""
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

---

## 8. REPL 集成

### 启动页布局（修订版）

保持两栏，宠物融入 Welcome 栏顶部：

```
┌─────────── Logo 面板 ───────────┐
│         ███ IMA ███             │
├──────────────────┬──────────────┤
│  ┌─ Welcome ───┐ │  ┌─ Tips ──┐ │
│  │ 🐾 小白 Lv5 │ │  │  命令    │ │
│  │  /\___/\    │ │  │  提示    │ │
│  │ ( o o )     │ │  │          │ │
│  │  \ ^ /      │ │  │          │ │
│  │ ❤️80 ⚡60   │ │  │          │ │
│  │ 😊70 🛁85   │ │  │          │ │
│  │ ✨520/800   │ │  │          │ │
│  │ ─────────   │ │  │          │ │
│  │ 📊 知识库   │ │  │          │ │
│  │ 文档 27     │ │  │          │ │
│  │ 分块 156    │ │  │          │ │
│  │ Tokens 82k  │ │  │          │ │
│  │ LLM ✓ 在线  │ │  │          │ │
│  │ 主题 claude │ │  │          │ │
│  └─────────────┘ │  └─────────┘ │
└──────────────────┴──────────────┘
```

### 宠物子区块内容

- 标题：`🐾 {name} (Lv{level} {branch_label})`
- ASCII 艺术（小尺寸 6 行 × 20 列，上色）
- 紧凑属性条：`❤️{hunger} ⚡{energy} 😊{mood} 🛁{cleanliness}`（一行）
- 经验进度：`✨ {exp}/{exp_needed} [dim]→Lv{level+1} 还需 {exp_remaining}[/dim]`
- 分隔线：`─` × 20

### 宠物未领养时

显示「🐾 虚拟宠物 / 未领养 / /pet adopt 领养」

### 首次领养流程

1. `/pet adopt` → 提示输入名字
2. 用户输入名字 → 创建 Lv1 蛋
3. 启动页立即显示宠物

### 命令分发

```python
elif cmd == "/pet":
    parts = arg.split(maxsplit=1)
    sub = parts[0].lower() if parts else ""
    sub_arg = parts[1].strip() if len(parts) > 1 else ""
    self._cmd_pet(sub, sub_arg)
```

`_cmd_pet` 内部根据 sub 分发到 interact.py 的对应方法。

### 行为埋点示例

```python
# 在 _cmd_ingest 成功后
self.pet.gain_exp(30, "ingest")

# 在 _cmd_agent 成功后
self.pet.gain_exp(15, "agent")

# 在 _handle_chat 成功后
self.pet.gain_exp(10, "qa")
```

`gain_exp` 内部流程：
1. 增加 stats[action_type]
2. 计算实际经验 = amount × exp_multi × (mood < 30 ? 0.7 : 1.0)
3. 累加 exp
4. 检查升级（可能连升多级）
5. Lv5 触发分系
6. 检查每日任务进度
7. 持久化到 JSON

---

## 9. 错误处理与边界

| 场景 | 处理 |
|---|---|
| 宠物状态文件不存在 | 自动创建 Lv1 蛋（不自动领养，等用户 `/pet adopt`） |
| JSON 损坏 | 备份到 `pet.json.bak.{timestamp}`，重建 |
| 升级时触发分系 | 进入分系动画，3 秒后自动选 branch |
| 能量不足互动 | 友好提示「{name} 累坏了，让它睡会儿吧～」 |
| 长期不玩（>7 天） | 属性衰减封顶 -50，提示「{name} 很想你～」 |
| 经验扣到 0 | 不会降级 |
| 道具重复使用 | 合并到 inventory 的 count |
| 等级已满（Lv10） | 经验继续累积，但不再升级（显示「已达最高级」） |
| 分系后想换系 | 暂不支持（不可逆，鼓励重新养一个） |
| 多个并发互动 | 串行处理（单线程 REPL 不存在） |

---

## 10. 测试策略

### 单元测试

- `tests/pet/test_pet.py` - Pet 类
  - 升级逻辑（包括连升多级）
  - 分系判定（不同 stats 分布）
  - 属性衰减（按时间差）
  - 互动效果（feed/play/train/wash/sleep 各项）
  - 边界值（属性 0/100、经验 0/最大值）
- `tests/pet/test_tasks.py` - 每日任务
  - 任务刷新（跨天触发）
  - 完成判定（埋点触发）
  - 重复完成防御
- `tests/pet/test_shop.py` - 道具商店
  - 购买（经验足够/不足）
  - 使用（库存管理）
  - 限时道具效果过期

### 集成测试

- `tests/pet/test_integration.py` - REPL 集成
  - 入库 → 经验增加
  - 问答 → 经验增加 + 能量恢复
  - 升级 → 形态切换
  - Lv5 → 自动分系

### 手动验收

- [ ] 启动 REPL，看到宠物子区块
- [ ] `/pet adopt 小白` → 创建宠物
- [ ] `/ingest` 一文件 → 经验 +30
- [ ] `/pet` → 看到详情面板
- [ ] `/pet feed` → hunger 增加
- [ ] 连续问答 5 次 → 每日任务完成
- [ ] 升到 Lv5 → 自动分系动画
- [ ] `/pet shop` → 看到商店
- [ ] `/pet buy fish` → 道具入栏
- [ ] `/pet use fish` → 效果生效

---

## 11. 实施顺序

按依赖关系分 4 个阶段：

### 阶段 1：基础（2 天）
1. `core/pet/pet.py` - Pet 类 + 升级/分系逻辑
2. `core/pet/storage.py` - JSON 持久化
3. `core/pet/art.py` - ASCII 艺术加载器（先做占位符）
4. `tests/pet/test_pet.py` - 单元测试

### 阶段 2：交互（2 天）
5. `core/pet/interact.py` - 5 个互动命令
6. `core/pet/tasks.py` - 每日任务系统
7. `core/pet/shop.py` - 道具商店
8. REPL 加 `/pet` 子命令分发

### 阶段 3：集成（2 天）
9. `repl.py` 启动页加宠物子区块
10. 行为埋点（10 处）
11. ASCII 艺术（35 个文件，小尺寸由代码动态截断）
12. 离线衰减计算

### 阶段 4：打磨（1 天）
13. 分系动画
14. 错误处理与边界
15. 集成测试
16. 手动验收

**总工作量**：7-10 天

---

## 12. 后续扩展（非本设计范围）

- **多宠物**：同时养多只，每只独立成长
- **宠物对战**：宠物间 PK（基于属性随机胜负）
- **宠物图鉴**：收集所有形态的图鉴系统
- **Web 端**：Streamlit 加宠物页面（动画 + 互动按钮）
- **社交**：导出宠物状态分享给朋友
- **季节限定**：节日特殊形态（春节限定皮肤）
- **成就系统**：解锁成就获得稀有道具

---

## 附录 A：经验值平衡性分析

假设用户日常使用 IMA 的频率：
- 每天入库 2 文档（+60）
- 每天问 10 个问题（+100）
- 每周用 1 次 analyze（+15）
- 每周用 1 次 agent（+15）

**日均经验**：约 165

| 等级 | 升级所需 | 累计 | 按日均 165 估算 |
|---|---|---|---|
| 1→2 | 100 | 100 | 0.6 天 |
| 2→3 | 282 | 382 | 2.3 天 |
| 3→4 | 519 | 901 | 5.5 天 |
| 4→5 | 800 | 1701 | 10.3 天 |
| 5→6 | 1118 | 2819 | 17.1 天 |
| 6→7 | 1469 | 4288 | 26.0 天 |
| 7→8 | 1852 | 6140 | 37.2 天 |
| 8→9 | 2262 | 8402 | 50.9 天 |
| 9→10 | 2700 | 11102 | 67.3 天 |

**结论**：
- Lv5（分系）约 10 天达成，节奏合适
- Lv10（满级）约 2 个多月，长期目标合理
- 每日任务奖励（约 300-500 经验/天）可显著加速

---

## 附录 B：埋点位置详细列表

| 文件 | 方法 | 经验 | 触发条件 |
|---|---|---|---|
| `repl.py` | `_handle_chat` | +10 | LLM 回答成功后 |
| `repl.py` | `_cmd_ingest` | +30 × n | 每入库 1 个文件 |
| `repl.py` | `_cmd_analyze` | +15 | 分析成功后 |
| `repl.py` | `_cmd_report` | +20 | 报告生成成功后 |
| `repl.py` | `_cmd_read` | +10 | 进入阅读模式后 |
| `repl.py` | `_cmd_compare` | +10 | 对比成功后 |
| `repl.py` | `_cmd_agent` | +15 | Agent 任务完成后 |
| `repl.py` | `_cmd_smart` | +8 | 路由成功后 |
| `repl.py` | `_cmd_graph` | +30 | build 子命令成功后 |
| `run.py` | `retag` 命令 | +10 | 重新打标签成功后 |

---

**设计文档结束。请审阅后告知是否需要调整。**
