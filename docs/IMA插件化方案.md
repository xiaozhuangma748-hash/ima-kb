# IMA 知识库插件化方案评估（接入 DeepSeek Harness Agent）

> 评估日期：2026-02 ｜ 状态：方案评估（未编码）
> 目标：让 DSH Agent（"我"）能够在对话中直接检索、问答本项目（IMA 殡葬政策 RAG 知识库），并评估三种插件的形态、成本与推荐路径。

---

## 1. 项目现状盘点（可作为插件的能力）

| 能力 | 入口 | 现状 |
|---|---|---|
| 文档入库（PDF/Word/Excel/PPT/图片/Markdown + OCR） | `ima ingest <路径>` | 已有 storage/uploads 政策文件若干 |
| 混合检索（BM25 + bge 向量 + Cross-Encoder 重排） | `ima search "<词>"` / Web `GET /search` | 索引已建（bm25_index.pkl、chroma/） |
| RAG 问答（含 Agentic 模式、自验证、引用溯源） | `ima ask "<问题>"` / Web `POST /qa/stream`（SSE） | 依赖外部 LLM（Agnes AI / DeepSeek，见 .env） |
| 文档查看 / 列表 / 统计 | `ima show <doc_id>` / `ima list` / `ima stats` | 有 |
| 知识图谱 / 报告 / Excel 分析 | `ima graph` / `ima report` / `ima analyze` | 有，锦上添花 |

技术要点（对接时直接复用，无需重写）：

- CLI 入口 `run.py`（Click），虚拟环境 `.venv`（Python 3.9），entry point `ima = "run:cli"`。
- Web 层已有 FastAPI 路由：`GET /search`（支持 q/tags/use_vector/use_rerank/sort/limit）、`POST /qa/stream`（SSE）、另有 analyze/graph/ingest/pet/stats 路由。
- `ima ask -o json` 可输出结构化结果（answer + citations + sources），`search --plain` 可输出纯文本便于管道消费。
- 已知坑：headless ask 前置要求"已领养宠物"（`has_pet` 校验）；Web `/qa/stream` 无此限制。插件接入时优先走 Web 路由或直接调用 services 层，绕开宠物门槛。

---

## 2. 三种插件形态对比

### 形态 A：动态 Cordis 插件（临时，当前会话生效）

- **做法**：用 `cordis_define` 在 Host 侧注册一个插件，通过 `harness.registerTool` 暴露 `ima_search` / `ima_ask` / `ima_show` / `ima_list` 等模型工具；工具内部以子进程调用 `run.py` 或 HTTP 调用已启动的 Web 服务。
- **优点**：立即可用；不污染磁盘配置；可随时 `cordis_stop`/`undefine` 卸载；审批流程成熟。
- **缺点**：进程重启即失效，仅限当前会话；每次工具调用如果走 CLI 子进程，Python 冷启动 + chromadb 加载有秒级延迟（建议配合常驻 Web 服务解决）。
- **适用**：先验证价值、试用手感。

### 形态 B：持久 Agent 预设（每次新会话都带）

- **做法**：复制 shipped 的 `standard` 预设到 `~/.dsh/.agent-presets/ima-assistant/`，在 `agent.cordis.yml` 中加入：① 工具行（封装 CLI/HTTP 的工具包，或受限 bash 工具 + 固定调用脚本）；② 系统提示（"殡葬政策知识库助理"人设、知识库路径、杭州/拱墅区政策背景）；③ 可选技能目录。
- **优点**：新开任何会话即自带能力；人设、提示词、工具可统一维护；与既有 `minzheng-qc-assistant` 技能生态一致。
- **缺点**：需要沙箱提权写 `~/.dsh`（用户会看到审批）；工具包需要作为可用包存在（要么用受限 bash 行，要么新增一个 npm 包，后者较重）；预设挂载校验（`standingKeyFor`）要求组 realm 处理得当。
- **适用**：长期复用的最终形态。

### 形态 C：技能 Skill（按需加载，任何会话可用）

- **做法**：在本项目内（或 `~/.dsh` 技能目录）写一个 `SKILL.md`：知识库位置、CLI/API 调用手册、检索→阅读→作答的工作流（推荐"我直接基于检索结果作答"而非依赖 IMA 自带 LLM 链路）、常见政策领域术语表、引用溯源规范。
- **优点**：最轻；纯文档零运行时依赖；任何预设下都能加载（类似现有 `minzheng-qc-assistant`）；不触发沙箱提权。
- **缺点**：不含自带工具，Agent 需借助已有 bash/fs 工具执行命令；依赖 Agent 正确阅读并遵守手册。
- **适用**：作为"接入规范"沉淀，是所有形态的地基。

---

## 3. 推荐方案（分层落地）

**结论：先 A 验证 → 沉淀 C 规范 → 需要时升级 B。三者互补，不冲突。**

### 3.1 接入通道选择（技术关键决策）

| 通道 | 延迟 | 常驻进程 | 复杂度 | 建议 |
|---|---|---|---|---|
| CLI 子进程（`python run.py ...`） | 每次 2–8s（冷启动） | 无 | 低 | 兜底方案 |
| Web API（uvicorn 常驻） | <200ms | 需管理生命周期 | 中 | **推荐**：插件/技能约定先探测 `127.0.0.1:8501/health`，未启动则由插件拉起后台进程，退出时回收 |

推荐以 Web API 为主通道：`GET /search` 拿检索结果，`POST /qa/stream` 拿 RAG 回答（或仅取检索结果由 DSH 模型自答，省 token、更快、不依赖外部 LLM 的可用性）。

### 3.2 工具集设计（形态 A/B 通用）

| 工具 | 实现 | 用途 |
|---|---|---|
| `ima_search` | `GET /search?q=&limit=` 或 `run.py search --plain` | 关键词/语义检索，返回 doc_id、标题、片段、分数 |
| `ima_show` | `run.py show <doc_id>` | 读取单篇政策原文全文 |
| `ima_list` | `run.py list` | 列出知识库文档清单 |
| `ima_ask` | `POST /qa/stream` 或 `run.py ask -o json` | 完整 RAG 问答（带引用溯源），可选 |
| `ima_stats` | `run.py stats` | 知识库统计 |
| `ima_ingest`（可选） | `run.py ingest <路径>` | 入库新政策文件 |

JSON 输出统一走 `-o json` / API 响应，工具返回 JSON-compatible 结构化数据（符合工具返回值必须 JSON 序列化的约束）。

### 3.3 安全与权限

- 项目目录即当前会话工作区，读写无需提权；`~/.dsh` 写入（形态 B）需一次沙箱提权（用户可见审批）。
- 子进程执行 `run.py` 属于 Agent 既有 bash 权限范畴；工具应限制路径参数、避免任意命令注入。
- IMA 的 .env 含 API Key，插件不应回显/导出这些密钥；仅由 IMA 自身进程消费。

### 3.4 工作量估算

| 阶段 | 内容 | 估时 |
|---|---|---|
| A1 动态插件 | Host 插件 + 3 个工具（search/show/list）打通 CLI | 0.5–1 天 |
| A2 通道优化 | 拉起/复用 uvicorn，切换 Web API | 0.5 天 |
| C 技能 | SKILL.md（手册 + 工作流 + 术语表） | 0.5 天 |
| B 预设 | 复制 standard + 工具行 + 人设提示词 + 挂载校验 | 1 天 |

### 3.5 风险

- **延迟**：CLI 冷启动是最大延迟源 → 用常驻 Web 服务缓解。
- **宠物门槛**：headless ask 需宠物 → 走 Web 路由或 services 层绕过。
- **外部 LLM 依赖**：IMA 自带 ask 依赖 Agnes/DeepSeek key → 插件可只做检索、由 DSH 模型作答，双保险。
- **版本耦合**：预设引用具体包版本，升级 DSH 后需重跑挂载校验。

---

## 4. 下一步（待确认后执行）

1. （可选）先做形态 A 动态插件，本会话内体验检索效果；
2. 沉淀形态 C 技能文档到本项目；
3. （可选）升级形态 B 持久预设。
