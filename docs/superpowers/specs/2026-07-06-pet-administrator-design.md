# 宠物知识库管理员 · 设计文档

> **状态**：已获用户批准（2026-07-06，分 6 节逐节确认）
> **前置依赖**：虚拟宠物系统 v4.0（`core/pet/` 已实现，47 测试全过）
> **目标**：把宠物从装饰角色升级为"知识库管理员"——宠物作为 AI 助手的人格化化身，具备精准召回 + 长期记忆 + 分系人格三大能力。

---

## 1. 目标与范围

### 1.1 用户需求

1. **精准召回 + 原文溯源**：基于用户问题，精准召回知识库信源，结合模型深度思考能力，输出可靠回答并支持原文溯源。
2. **长期记忆 + 用户偏好**：具备长期记忆，了解用户使用偏好，可处理复杂任务，并生成多种所需的知识产物，越用越懂你。
3. **宠物管理员**：把宠物升级为知识库管理员人格化化身。

### 1.2 核心决策（已确认）

| 决策点 | 选择 |
|--------|------|
| 集成形态 | **替代现有问答**——所有 AI 交互都通过宠物，宠物是唯一入口 |
| 记忆范围 | **偏好 + 工作流 + 任务**——最完整的记忆能力 |
| 召回技术 | **混合检索 + LLM 重排**——BM25 + 向量 + cross-encoder 重排 |
| 人格影响 | **分系决定风格**——scholar/warrior/artisan 三种回答风格 |
| 架构方案 | **方案 A 分层架构**——retrieval/memory/persona 独立模块 + pet/administrator 编排层 |

### 1.3 不在本期范围

- 多用户支持（单人单机）
- 向量模型微调
- Web 界面改造（仅改 REPL + CLI）
- 知识图谱增强（保留现有 graph 模块不变）

---

## 2. 整体架构

### 2.1 模块分层

```
用户提问
   ↓
┌─────────────────────────────────────────┐
│  core/pet/administrator.py  (编排层)     │
│  - 接收用户输入                           │
│  - 加载用户记忆（profile/workflow/tasks） │
│  - 调度检索 → 重排 → 生成                 │
│  - 应用宠物人格风格                       │
└─────────────────────────────────────────┘
   ↓                ↓                ↓
┌──────────┐  ┌──────────────┐  ┌──────────┐
│ retrieval│  │   memory     │  │  persona │
│ - hybrid │  │ - profile    │  │ - styles │
│ - rerank │  │ - workflow   │  │ - prompts│
│ - cite   │  │ - tasks      │  │          │
└──────────┘  └──────────────┘  └──────────┘
   ↓                ↓                ↓
┌─────────────────────────────────────────┐
│  core/llm/client.py  (底层 LLM 调用)     │
└─────────────────────────────────────────┘
   ↓
回答 + 引用溯源 + 记忆更新
```

### 2.2 一次完整问答的数据流

1. **用户输入** "骨灰安置有哪些政策？"
2. **编排层** 加载用户 profile（喜欢表格、关注杭州地区）+ tasks（"正在整理殡葬政策对比"）
3. **检索层** 并行执行：
   - BM25 检索 → top 10
   - 向量检索 → top 10
   - 合并去重 → 候选 15 篇
4. **重排层** LLM 对 15 候选打分 → top 5
5. **生成层** 拼接：
   - system prompt（含宠物人格 + 用户偏好 + 当前任务上下文）
   - 检索到的 5 段原文（含 doc_id + 段落号）
   - 用户问题
   - → LLM 生成回答
6. **引用结构化** 从回答中提取引用标记 `[1][2]`，映射到 doc_id + 段落号
7. **输出** 回答 + 引用列表（可点击溯源）
8. **记忆更新** 记录本次提问主题、用户是否满意（如继续追问视为满意）

### 2.3 与现有 REPL 的集成

`repl.py` 的 `_handle_chat` 改为调用 `administrator.ask(question)`，不再直接调用 `RAGChain`。现有 `/agent`、`/read`、`/compare` 等命令保留，但内部也走 administrator 编排（统一人格 + 记忆）。

---

## 3. 检索层（core/retrieval/）

### 3.1 文件结构

```
core/retrieval/
├── __init__.py
├── hybrid.py      # BM25 + 向量混合检索
├── vector.py      # 向量索引（embedding + 存储）
├── rerank.py      # LLM 重排序
└── citation.py    # 引用结构化 + 溯源映射
```

### 3.2 向量索引（vector.py）

- **Embedding 模型**：BAAI/bge-small-zh-v1.5（本地，512 维，中文优化）
- **向量库**：ChromaDB（轻量、纯 Python、支持持久化）
- **存储路径**：`storage/vectors/`（与 SQLite 同级）
- **接口**：
  - `build_index(chunks: List[Chunk]) -> None` — 全量构建
  - `add_chunk(chunk: Chunk) -> None` — 增量添加（ingest 时调用）
  - `search(query: str, top_k: int = 10) -> List[VectorResult]`
- **降级策略**：模型加载失败时自动降级为纯 BM25，记日志不报错

### 3.3 混合检索（hybrid.py）

- **融合策略**：RRF（Reciprocal Rank Fusion），公式 `score = Σ 1/(k + rank_i)`，k=60
- **接口**：
  - `search(query: str, top_k: int = 10) -> List[HybridResult]`
  - 内部并行调用 BM25 + 向量，RRF 融合后返回 top_k
- **HybridResult** 包含：`doc_id, chunk_id, score, source`（bm25/vector/both）

### 3.4 LLM 重排序（rerank.py）

- **方法**：cross-encoder 风格，让 LLM 对每个候选打分（0-10）
- **批量优化**：一次 LLM 调用处理所有候选（不是每篇单独调用）
- **接口**：
  - `rerank(query: str, candidates: List[HybridResult], top_n: int = 5) -> List[RerankResult]`
- **RerankResult** 额外包含：`reason`（LLM 给出的相关性理由）
- **降级策略**：LLM 调用失败时保留原顺序，仅记日志

### 3.5 引用结构化（citation.py）

- **回答中的引用标记**：`[1]`、`[2]` 形式，对应 doc_id
- **接口**：
  - `extract_citations(answer: str, sources: List[RerankResult]) -> List[Citation]`
  - `Citation` 包含：`marker`（"[1]"）、`doc_id`、`title`、`paragraph_num`、`snippet`（原文片段）
- **溯源展示**：REPL 中引用以 `[1] 标题 §段落` 格式显示，可点击跳转
- **原文片段提取**：从原 chunk 中截取与引用最相关的 50-100 字片段

### 3.6 检索流程示例

```
query = "骨灰安置政策"
↓
hybrid.search(query, top_k=15)
  ├─ BM25 → top 10（关键词匹配）
  └─ vector.search(query, top_k=10)（语义匹配）
  → RRF 融合 → 15 候选
↓
rerank.rerank(query, candidates, top_n=5)
  → LLM 批量打分 → top 5
↓
生成回答后 → citation.extract_citations(answer, sources)
  → [1] 殡葬管理条例 §3, [2] 杭州市骨灰安置办法 §5
```

### 3.7 CLI 新增命令

- `ima rebuild --vector` — 重建向量索引
- `ima search "词" --hybrid` — 使用混合检索（默认）
- `ima search "词" --bm25` — 仅 BM25（对比测试用）

---

## 4. 记忆层（core/memory/）

### 4.1 文件结构

```
core/memory/
├── __init__.py
├── profile.py      # 用户偏好（主题/风格/格式）
├── workflow.py     # 工作流模式（命令组合记录）
├── tasks.py        # 跨会话任务（未完成事项）
└── store.py        # JSON 持久化 + 增量更新
```

### 4.2 记忆存储结构

统一存储在 `storage/memory.json`：

```json
{
  "profile": {
    "preferred_format": "table",
    "preferred_style": "auto",
    "focus_topics": ["骨灰安置", "杭州市政策"],
    "focus_regions": ["杭州市", "拱墅区"],
    "interaction_count": 42,
    "last_active": "2026-07-06T15:30:00"
  },
  "workflow": {
    "patterns": [
      {
        "sequence": ["ingest", "analyze", "report"],
        "count": 5,
        "last_used": "2026-07-06T14:00:00"
      }
    ],
    "suggestions_enabled": true
  },
  "tasks": [
    {
      "id": "task_001",
      "description": "整理殡葬政策对比报告",
      "created_at": "2026-07-05T10:00:00",
      "updated_at": "2026-07-06T15:30:00",
      "status": "in_progress",
      "related_docs": ["862e0973", "a1b2c3d4"],
      "context": "用户在整理拱墅区殡葬政策对比"
    }
  ],
  "history": {
    "recent_queries": [
      {"query": "骨灰安置政策", "timestamp": "...", "satisfied": true}
    ]
  }
}
```

### 4.3 用户偏好（profile.py）

- **自动学习**：每次问答后，LLM 异步提取主题/地区/格式偏好
- **格式判定**：分析用户提问中的"表格"、"列表"等关键词 + 历史选择
- **地区识别**：从提问中抽取地名实体（杭州、拱墅区等）
- **`preferred_style`**：默认 `"auto"`（跟随宠物分系），用户可通过 `/pet style` 显式覆盖为 `scholar/warrior/artisan`
- **接口**：
  - `get_profile() -> Profile`
  - `update_from_query(query: str, answer: str, feedback: Optional[str]) -> None`
  - `update_format_preference(format: str) -> None`
  - `update_style_preference(style: str) -> None`（`/pet style` 调用）

### 4.4 工作流模式（workflow.py）

- **模式识别**：记录连续命令序列（窗口 30 分钟内），统计频次
- **推荐触发**：当用户执行某命令后，若存在高频后续命令，主动推荐
- **接口**：
  - `record_command(cmd: str, timestamp: str) -> None`
  - `detect_pattern() -> Optional[List[str]]`
  - `suggest_next(current_cmd: str) -> Optional[str]`

### 4.5 跨会话任务（tasks.py）

- **任务来源**：
  1. 用户显式声明（`/pet task 整理骨灰安置政策对比`）— 始终启用
  2. LLM 从对话中推断（用户说"我正在整理…"时自动捕获）— 受 `auto_capture` 开关控制，默认开启，用户可通过 `/memory config auto_capture off` 关闭
- **任务上下文**：记录相关文档 ID，下次提问时自动注入
- **接口**：
  - `add_task(description: str, related_docs: List[str] = None) -> str`
  - `update_task(task_id: str, status: str) -> None`
  - `get_active_tasks() -> List[Task]`
  - `link_doc(task_id: str, doc_id: str) -> None`
- **`Task` 数据结构**（供编排层引用）：
  ```python
  @dataclass
  class Task:
      id: str
      description: str
      created_at: str
      updated_at: str
      status: str  # pending/in_progress/completed
      related_docs: List[str]
      context: str
  ```

### 4.6 持久化（store.py）

- **格式**：JSON（与 pet.json 同级）
- **写入策略**：每次更新原子写入（临时文件 + rename）
- **备份**：损坏时备份为 `memory.json.bak.{ts}`（沿用 pet.json 的策略）
- **接口**：
  - `load() -> MemoryData`
  - `save(data: MemoryData) -> None`
  - `update(section: str, key: str, value: Any) -> None`

### 4.7 记忆注入到 system prompt

每次 LLM 调用前，编排层将记忆组装为上下文：

```
## 用户偏好
- 回答格式：表格
- 关注主题：骨灰安置、杭州市政策
- 关注地区：杭州市、拱墅区

## 当前任务
- 整理殡葬政策对比报告（进行中，已关联 2 篇文档）

## 最近提问
- 骨灰安置政策（2 小时前，已满意）

## 工作流建议
- 你常用 ingest → analyze → report 流程，已 ingest 后可考虑 analyze
```

### 4.8 REPL 新增命令

- `/memory` — 查看当前记忆（profile + tasks）
- `/memory profile` — 查看偏好详情
- `/memory tasks` — 查看任务列表
- `/memory task <描述>` — 添加任务
- `/memory clear` — 清空记忆（带确认）
- `/memory forget <section>` — 清除某部分（profile/workflow/tasks/history）

### 4.9 隐私与控制

- 所有记忆数据本地存储，不上传
- 用户可随时查看、编辑、清除
- 首次启用时提示"将记录你的使用偏好以提供个性化服务"

---

## 5. 人格层（core/persona/）

### 5.1 文件结构

```
core/persona/
├── __init__.py
├── styles.py       # 三种人格风格定义
└── prompts.py      # 分系 system prompt 模板
```

### 5.2 三种人格风格

#### scholar（学者）— 深度分析型

- **性格**：严谨、博学、引用密集
- **回答特点**：
  - 先给结论，再展开论证
  - 必带原文引用 `[1]`，多个引用支撑同一观点
  - 偏好表格对比、条文列举
  - 主动指出例外情况和边界条件
- **语气**：正式、客观，少用第一人称

#### warrior（战士）— 直接行动型

- **性格**：果断、高效、行动导向
- **回答特点**：
  - 开门见山给答案
  - 引用最少但最相关（1-2 个）
  - 主动给行动建议（"建议你..."、"下一步可..."）
  - 偏好列表、步骤
- **语气**：简洁、有力，多用动词

#### artisan（工匠）— 结构化型

- **性格**：细致、有条理、注重呈现
- **回答特点**：
  - 结构化分块（背景/分类/标准/对比）
  - 必带小标题
  - 偏好表格、流程图描述
  - 主动总结要点
- **语气**：温和、清晰，引导式

### 5.3 system prompt 模板

三种模板结构一致，差异在风格指令和引用规则：

- `SCHOLAR_SYSTEM`：每个观点必须有原文引用，偏好表格对比
- `WARRIOR_SYSTEM`：引用最少（最多 3 个），主动给行动建议
- `ARTISAN_SYSTEM`：必带小标题，偏好表格，每节至少 1 个引用

模板统一占位符：`{pet_name}`、`{level}`、`{user_profile}`、`{user_tasks}`、`{retrieved_context}`

### 5.4 未分系时的中性风格

宠物 Lv1-4 未分系时，使用**中性风格**：

- 综合三种特点：先结论 + 适度引用 + 简单结构化
- system prompt 较短，不强制风格
- 目的：让用户在分系前体验中性，分系后感受明显差异

### 5.5 人格与宠物状态联动

- **mood < 30**：回答中加一句"（宠物心情低落，回答可能不够完整，建议先 /pet play）"
- **hunger < 30**：回答中加一句"（宠物饿了，建议 /pet feed）"
- **energy < 30**：回答变简短（强制 max_tokens 减半）

### 5.6 风格切换的灵活性

虽然分系决定主风格，但用户可临时覆盖：

- `/pet style scholar` — 临时切到学者风格（不改宠物分系）
- `/pet style auto` — 恢复跟随宠物分系

---

## 6. 编排层（core/pet/administrator.py）+ REPL 集成

### 6.1 编排层核心接口

```python
class PetAdministrator:
    """宠物知识库管理员：编排检索 + 记忆 + 人格 + LLM。"""

    def __init__(
        self,
        pet: Pet,
        storage: Storage,
        memory_store: MemoryStore,
        art_library: ArtLibrary,
    ) -> None: ...

    def ask(self, query: str, style_override: Optional[str] = None) -> AnswerResult:
        """主入口：用户提问 → 带引用的回答。"""
        # 1. 加载记忆
        # 2. 混合检索
        # 3. LLM 重排
        # 4. 组装 system prompt（人格 + 记忆 + 检索资料）
        # 5. LLM 生成
        # 6. 提取引用
        # 7. 异步更新记忆
        # 8. 宠物获得经验
```

### 6.2 AnswerResult 数据结构

```python
@dataclass
class AnswerResult:
    text: str                          # LLM 回答文本
    citations: List[Citation]          # 引用列表（来自 core/retrieval/citation.py）
    sources: List[RerankResult]        # 完整溯源信息（来自 core/retrieval/rerank.py）
    pet_events: dict                   # 宠物事件（升级/分系等）
    related_tasks: List[Task] = None   # 相关未完成任务（来自 core/memory/tasks.py，可选）
```

### 6.3 REPL 集成改动

#### `_handle_chat` 改为走 administrator

```python
def _handle_chat(self, text: str) -> None:
    if not self.administrator:
        self._legacy_rag_chat(text)  # 降级
        return
    result = self.administrator.ask(text)
    self._render_answer(result)
    if result.pet_events.get("leveled_up"):
        self._render_level_up(result.pet_events)
    if result.pet_events.get("branched"):
        self._render_branch_event(result.pet_events)
```

#### 回答渲染（带引用）

```
┌─────────────────────────────────────────────┐
│ 🦉 小白 (Lv5 学者)                            │
├─────────────────────────────────────────────┤
│ 根据相关规定，骨灰安置方式可分为四类[1]，      │
│ 其中生态安置包括树葬、海葬等形式[2]。           │
│                                              │
│ ┌─ 引用溯源 ─────────────────────────────┐  │
│ │ [1] 殡葬管理条例 §3                     │  │
│ │     "...骨灰安置分为四类..."            │  │
│ │ [2] 杭州市骨灰安置办法 §5               │  │
│ │     "...生态安置包括树葬..."            │  │
│ └────────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
```

- 引用编号在回答中是 `[1]` 形式
- 底部"引用溯源"区块显示 doc 标题、段落号、原文片段
- REPL 中可输入 `[1]` 查看完整文档（调用 `/show <doc_id>`）

### 6.4 工作流推荐触发

```python
def _post_command_hook(self, cmd: str) -> None:
    suggestion = self.memory.workflow.suggest_next(cmd)
    if suggestion:
        console.print(f"\n[dim]💡 常用下一步：/{suggestion}（基于你的使用习惯）[/dim]")
```

### 6.5 其他命令的统一接入

| 现有命令 | 改造方式 |
|---------|---------|
| `/agent` | 走 administrator，但用 Agent 模式（多步推理），保留人格 + 记忆 |
| `/read` | 走 administrator，单文档深度阅读，人格风格应用 |
| `/compare` | 走 administrator，对比分析，人格风格应用 |
| `/report` | 走 administrator，报告生成，人格风格应用 |
| `/analyze` | 数据分析逻辑不变（保持 analyzer.py 原有处理），但回答阶段走 administrator 的人格 + 记忆注入 |

### 6.6 降级策略

| 故障点 | 降级行为 |
|-------|---------|
| 向量索引未构建 | 自动用纯 BM25，提示"向量索引未构建，运行 `ima rebuild --vector`" |
| LLM 重排失败 | 保留 hybrid 顺序，记日志 |
| LLM 生成失败 | 返回检索到的原文片段 + 提示"LLM 不可用，已展示原文" |
| 记忆文件损坏 | 备份后重置为空记忆，提示用户 |
| 宠物未领养 | 降级为原有 RAGChain，无人格无记忆 |

### 6.7 性能考量

- **向量检索**：bge-small-zh-v1.5 在 CPU 上约 50ms/查询，可接受
- **LLM 重排**：1 次调用处理 15 候选，约 2-3 秒
- **LLM 生成**：原有 RAGChain 约 3-5 秒，加人格后无明显差异
- **总延迟**：约 5-8 秒（vs 原 3-5 秒），换取质量提升可接受

### 6.8 CLI 新增命令

- `ima rebuild --vector` — 构建向量索引
- `ima ask "问题"` — CLI 一次性问答（不进 REPL）
- `ima memory` — 查看记忆
- `ima memory --clear` — 清空记忆

---

## 7. 错误处理 + 测试策略

### 7.1 错误处理分级

#### P0 — 必须阻断（用户可见错误 + 退出）

| 场景 | 处理 |
|------|------|
| 记忆文件损坏且无法备份 | 抛 `MemoryCorruptionError`，提示用户检查 `storage/memory.json` |
| 宠物状态损坏且无法备份 | 抛 `PetCorruptionError`，提示用户重新 `/pet adopt` |
| LLM API 配置缺失 | 启动时检测，提示配置 `AGNES_API_KEY` |

#### P1 — 降级（用户可见提示 + 继续运行）

| 场景 | 降级行为 | 用户提示 |
|------|---------|---------|
| 向量索引缺失 | 纯 BM25 | "向量索引未构建，仅用 BM25。运行 `ima rebuild --vector` 启用混合检索" |
| 向量模型加载失败 | 纯 BM25 | "向量模型加载失败（{原因}），已降级为 BM25" |
| LLM 重排失败 | 保留 hybrid 顺序 | "⚠ 重排序失败，结果未优化" |
| LLM 生成失败 | 返回原文片段 | "⚠ LLM 不可用，已展示检索原文" |
| 记忆更新失败 | 跳过更新 | 日志记录，不打扰用户 |
| 单次检索超时（>10s） | 截断结果 | "⚠ 检索超时，结果可能不完整" |

#### P2 — 静默降级（仅日志）

| 场景 | 行为 |
|------|------|
| 工作流推荐失败 | 不显示推荐 |
| 引用提取失败 | 回答照常显示，无引用区块 |
| 记忆 profile 提取失败 | 跳过本次更新 |
| 宠物经验更新失败 | 跳过，不影响回答 |

### 7.2 重试策略

```python
# LLM 调用重试（沿用现有 core/llm/client.py）
max_retries = 3
backoff = [1, 2, 4]  # 指数退避秒数
retry_on = [ConnectionError, TimeoutError, RateLimitError]
```

新增重试点：
- **向量检索**：1 次重试，间隔 1 秒（ChromaDB 偶发 IO 问题）
- **重排 LLM 调用**：复用现有重试机制

### 7.3 测试文件结构

```
tests/
├── retrieval/
│   ├── __init__.py
│   ├── test_vector.py        # 向量索引
│   ├── test_hybrid.py        # 混合检索 + RRF
│   ├── test_rerank.py        # LLM 重排序
│   └── test_citation.py      # 引用提取
├── memory/
│   ├── __init__.py
│   ├── test_profile.py       # 偏好学习
│   ├── test_workflow.py      # 工作流识别
│   ├── test_tasks.py         # 任务记忆
│   └── test_store.py         # 持久化
├── persona/
│   ├── __init__.py
│   └── test_prompts.py       # prompt 模板渲染
├── pet/
│   └── test_administrator.py # 编排层集成测试
└── integration/
    └── test_pet_admin_flow.py # 端到端流程
```

### 7.4 单元测试重点

**检索层**：
- `test_hybrid.py`：RRF 融合正确性、空结果处理、top_k 边界
- `test_rerank.py`：mock LLM 返回打分、降级（LLM 失败时保留顺序）
- `test_citation.py`：`[1][2]` 提取、多引用合并、无引用回答处理

**记忆层**：
- `test_profile.py`：从 query 提取主题、格式偏好学习、地区识别
- `test_workflow.py`：命令序列识别、频次统计、推荐触发
- `test_tasks.py`：任务 CRUD、关联文档、状态流转
- `test_store.py`：JSON 读写、损坏备份、原子写入

**人格层**：
- `test_prompts.py`：三种模板渲染、占位符替换、中性风格

**编排层**：
- `test_administrator.py`：mock 各子模块，验证调用顺序、降级路径、记忆注入

### 7.5 集成测试（端到端）

```python
# tests/integration/test_pet_admin_flow.py

def test_full_ask_flow(tmp_path):
    """完整问答流程：检索 → 重排 → 生成 → 引用 → 记忆更新。"""
    # 1. 准备：构建索引 + 创建宠物 + 初始化记忆
    # 2. 提问
    result = admin.ask("骨灰安置政策")
    # 3. 验证
    assert result.text  # 非空回答
    assert len(result.citations) >= 1  # 至少 1 个引用
    assert result.pet_events  # 宠物事件
    # 4. 验证记忆更新
    profile = admin.memory.get_profile()
    assert "骨灰安置" in profile.focus_topics


def test_degradation_vector_missing(tmp_path):
    """向量索引缺失时降级为 BM25。"""
    result = admin.ask("骨灰安置")
    assert result.text  # 仍能回答


def test_degradation_llm_failure(tmp_path):
    """LLM 失败时返回原文片段。"""
    result = admin.ask("骨灰安置")
    assert "原文" in result.text or "不可用" in result.text


def test_persona_style_affects_answer(tmp_path):
    """不同人格产生不同风格回答。"""
    scholar_answer = admin.ask("骨灰安置", style_override="scholar")
    warrior_answer = admin.ask("骨灰安置", style_override="warrior")
    assert len(scholar_answer.citations) >= len(warrior_answer.citations)


def test_memory_persistence_across_sessions(tmp_path):
    """记忆跨会话持久化。"""
    admin.ask("杭州骨灰安置")
    admin.memory.save()
    # 新建 admin 实例模拟重启（复用同一 storage 和 memory 路径）
    admin2 = PetAdministrator(
        pet=PetStorage(storage_path=tmp_path).load(),
        storage=admin.storage,
        memory_store=MemoryStore(storage_path=tmp_path),
        art_library=admin.art,
    )
    profile = admin2.memory.get_profile()
    assert "杭州" in profile.focus_regions
```

### 7.6 测试覆盖目标

- **单元测试**：每个模块独立测试，mock 外部依赖（LLM、embedding）
- **集成测试**：端到端验证流程，使用真实 BM25 + mock LLM
- **降级测试**：每个故障点都有对应的降级测试用例
- **目标覆盖率**：核心逻辑 ≥ 80%，降级路径 100%

### 7.7 性能测试（可选）

```python
def test_hybrid_search_under_500ms():
    """混合检索应在 500ms 内完成（27 篇文档）。"""
    start = time.time()
    results = hybrid.search("骨灰安置", top_k=15)
    assert time.time() - start < 0.5
```

---

## 8. 新增依赖

| 依赖 | 用途 | 安装方式 |
|------|------|---------|
| chromadb | 向量数据库 | `pip install chromadb` |
| sentence-transformers | 加载 bge-small-zh-v1.5 | `pip install sentence-transformers` |

均加入 `requirements.txt`，并在 `install.sh` 中提供 `--vector` 选项控制是否安装向量相关依赖（用户可不装向量依赖，降级为纯 BM25）。

---

## 9. 文件清单总览

### 9.1 新建文件

```
core/retrieval/
├── __init__.py
├── hybrid.py
├── vector.py
├── rerank.py
└── citation.py

core/memory/
├── __init__.py
├── profile.py
├── workflow.py
├── tasks.py
└── store.py

core/persona/
├── __init__.py
├── styles.py
└── prompts.py

core/pet/
└── administrator.py

tests/retrieval/   (4 文件)
tests/memory/      (4 文件)
tests/persona/     (1 文件)
tests/pet/test_administrator.py
tests/integration/test_pet_admin_flow.py
```

### 9.2 修改文件

```
repl.py              # _handle_chat 改走 administrator + 新增 /memory 命令 + 工作流推荐钩子
core/qa/chain.py     # 保留但降级为"宠物未领养时的降级路径"
core/pet/interact.py # 新增 /pet style 命令处理
config.py            # 新增向量/记忆相关配置
requirements.txt     # 新增 chromadb + sentence-transformers
install.sh           # 新增 --vector 选项
```

### 9.3 运行时生成

```
storage/vectors/     # ChromaDB 持久化目录
storage/memory.json  # 记忆数据
```

---

## 10. 实现顺序建议

按依赖关系分 4 个阶段，每阶段产出自包含可测试单元：

1. **阶段 1：检索层**（core/retrieval/）— 可独立测试，不依赖记忆/人格
2. **阶段 2：记忆层**（core/memory/）— 可独立测试，不依赖检索/人格
3. **阶段 3：人格层**（core/persona/）— 可独立测试，仅依赖宠物分系
4. **阶段 4：编排层 + REPL 集成**（core/pet/administrator.py + repl.py）— 整合三层 + 集成测试

---

**设计文档结束。下一步：调用 writing-plans skill 生成详细实现计划。**
