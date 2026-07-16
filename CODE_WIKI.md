# IMA 个人知识库 · Code Wiki

> **版本**：v4.1（宠物知识库管理员 · 工业级 RAG 流水线） · pyproject 版本号 `4.1.0`
> **代码仓库**：`xiaozhuangma748-hash/ima-kb`
> **最后更新**：2026-07-15（检索性能优化：语义缓存 + 查询路由 + 并发检索 + LaTeX 输出清理）
> **Python 兼容性**：3.9+（macOS 自带 3.9.6 即可运行）

---

## 目录

- [1. 项目概述](#1-项目概述)
- [2. 项目目录结构](#2-项目目录结构)
- [3. 整体架构](#3-整体架构)
- [4. 配置中心](#4-配置中心)
- [5. 入口层](#5-入口层)
- [6. 核心模块详解](#6-核心模块详解)
- [7. Web 后端与前端](#7-web-后端与前端)
- [8. 测试体系](#8-测试体系)
- [9. 依赖关系总览](#9-依赖关系总览)
- [10. 项目运行方式](#10-项目运行方式)
- [11. 设计决策与亮点](#11-设计决策与亮点)

---

## 1. 项目概述

### 1.1 项目定位

**IMA 个人知识库**（ima-kb）是一个本机优先的个人知识管理工具，把电脑里散落的资料（PDF / Word / Excel / PPT / Markdown / 网页 / 代码 / 图片）整理成一个**可搜索、可问答、可分析**的本地知识库。

核心理念：
- **本地优先**：所有数据（SQLite + JSON + 向量库）都在本机 `storage/` 目录
- **多入口**：CLI 命令 + 交互式 REPL + Web 后台三套入口共享同一套 core 服务
- **混合检索**：BM25 关键词 + 向量语义 + RRF 融合 + LLM 重排序，四层流水线
- **虚拟宠物管理员**：所有 AI 交互统一由 PetAdministrator 编排，串联检索 → 重排 → 人格 → LLM → 引用 → 记忆 → 经验

### 1.2 技术栈

| 层 | 选型 |
|---|---|
| 运行时 | Python 3.9+ |
| CLI 框架 | click + rich + prompt_toolkit |
| 元数据库 | SQLite（单文件 `metadata.db`） |
| 文档解析 | PyMuPDF / python-docx / openpyxl / python-pptx / trafilatura / PaddleOCR（主）+ pytesseract（降级）/ macOS textutil（.doc） |
| 中文检索 | jieba + 自实现 BM25 |
| 向量检索 | ChromaDB + sentence-transformers（`BAAI/bge-small-zh-v1.5`） |
| LLM | Agnes AI（OpenAI 兼容协议，`agnes-2.0-flash`） |
| 图像生成 | Agnes Image 2.1 Flash |
| 知识图谱 | networkx + vis.js（HTML 可视化） |
| Web 后端 | FastAPI + uvicorn + SSE 流式问答 |
| Web 前端 | 单页 HTML + 原生 JS + vis.js + marked.js |
| 记忆系统 | MemoryStore（JSON 原子写入）+ jieba 主题提取 |
| 人格系统 | 4 风格 scholar/warrior/artisan/neutral + 像素风 ASCII 艺术 |
| Agent | LLM ReAct 模式 + 6 个内置工具 |
| 近似去重 | SimHash（64 位指纹 + 汉明距离） |

### 1.3 功能矩阵

| 类别 | 功能 | 入口 |
|---|---|---|
|  **入库** | 40+ 种格式解析 + OCR 降级 + SHA256 去重 + LLM 自动标签 | `ima ingest` / `/ingest` / `/note` `/clip` `/url` |
| **检索** | BM25 + 向量 + RRF 融合 + LLM 重排 + 语义缓存 + 并发检索 | `ima search` / `/search` / `/api/search` |
| **问答** | RAG + 多轮对话 + 引用溯源 + 置信度阈值 + 查询路由（闲聊跳过检索）+ LaTeX 输出清理 | `ima ask` / 直接输入 / `/api/qa/stream`（SSE） |
| **Agent** | ReAct 工具调用（search/list_docs/get_doc/read/read_multi/analyze） | `/agent` |
| **知识图谱** | LLM 抽取实体关系 + networkx 存储 + vis.js 可视化 | `ima graph build/stats/neighbors/export` |
| **数据分析** | Excel/CSV/TSV/JSON 统计 + 字符图 + AI 解读 | `ima analyze` / `/analyze` |
| **报告生成** | Markdown 结构化报告（6 章节） | `ima report` / `/report` |
| **文档阅读** | 逐段展示 + AI 解读 + 互动提问 | `/read` |
| **文档对比** | 两文档/文件异同对比（6 章节 Markdown） | `/compare` |
| **图像生成** | 文生图 / 文档配图 / 每日知识卡片 | `/pic` `/draw` `/daily` |
| **同步** | 增量同步（mtime + hash 双重检测） | `ima sync` |
| **质量检查** | 空文档/超长块/OCR 乱码检测 + 健康分 | `ima health` |
| **近似去重** | SimHash 64 位指纹 + 汉明距离 ≤3 判重 | `ima dedup` |
| **会话管理** | 跨会话历史保存/加载/导出 Markdown | `/session save/load/list` |
| **记忆系统** | 用户偏好 + 跨会话任务 + jieba 主题 + 工作流模式 | `ima memory` / `/memory` |
| **虚拟宠物** | 等级/经验/5 维属性/分系/互动/商店/每日任务 | `/pet adopt/interact/buy/use/style` |
| **Web 后台** | 7 页面单页应用（AI 问答 / 入库 / 搜索 / 分析 / 仪表盘 / 图谱 / 宠物） | `ima web` / `/web` |

---

## 2. 项目目录结构

```
ima-kb/
├── config.py                     # 配置中心（Settings 单例）
├── run.py                        # CLI 入口（23 个顶层命令 + graph 5 子命令）
├── repl.py                       # 交互式 REPL 入口（薄封装，委托 core/cli/）
├── pyproject.toml                # 打包配置，入口点 ima = "run:cli"
├── requirements.txt              # 依赖清单
├── install.sh                    # 一键安装脚本
├── .env.example                  # 环境变量模板
├── HANDOFF.md                    # 项目交接文档
├── INSTALL.md                    # 安装指南
│
├── core/                         # 核心业务模块
│   ├── storage.py                # SQLite 存储层
│   ├── cli/                      # 交互式 REPL（模块化拆分）
│   │   ├── main.py               #   REPL 启动入口
│   │   ├── repl.py               #   REPL 主类（命令分发 + AI 对话）
│   │   ├── chat.py               #   AI 对话渲染逻辑
│   │   ├── completer.py          #   命令自动补全（CommandCompleter）
│   │   ├── welcome.py            #   启动页渲染 + 活动记录
│   │   ├── constants.py          #   常量、命令列表、别名表、console 实例
│   │   └── commands/             #   各命令处理器（Mixin 模式）
│   │       ├── agent.py          #     /agent /smart 命令
│   │       ├── analyze.py        #     /analyze 命令
│   │       ├── docs.py           #     /search /ingest /list /read 等文档命令
│   │       ├── graph.py          #     /graph 子命令
│   │       ├── memory.py         #     /memory 子命令
│   │       ├── pet.py            #     /pet 子命令
│   │       ├── pipe.py           #     管道操作
│   │       ├── session.py        #     /session 子命令
│   │       ├── sync.py           #     /sync /health /dedup 命令
│   │       └── todo.py           #     /todo 每日任务命令
│   ├── setup/                    # 首次运行引导
│   │   └── wizard.py             #   配置向导（API Key 检测 + 初始化）
│   ├── ingestion/                # 入库
│   │   ├── parser.py             #   多格式解析（40+ 种，含 20+ 代码语言 + OCR）
│   │   ├── chunker.py            #   智能分块
│   │   └── quick.py              #   快速入库（note/clip/url）
│   ├── search/bm25.py            # BM25 索引
│   ├── retrieval/                # 混合检索 + 性能优化
│   │   ├── vector.py             #   ChromaDB 向量索引
│   │   ├── hybrid.py             #   BM25 + 向量 + RRF 融合（并发检索 + 两级检索 + 语义缓存）
│   │   ├── semantic_cache.py     #   语义缓存（L1 精确 + L2 embedding 相似度，TTL + LRU）
│   │   ├── router.py             #   查询路由（闲聊/知识分流）
│   │   ├── rerank.py             #   LLM 重排序
│   │   └── citation.py           #   引用编号提取
│   ├── llm/
│   │   ├── client.py             #   Agnes LLM 客户端（chat / chat_stream）
│   │   └── degrade.py            #   统一降级提示
│   ├── qa/chain.py               # RAG 问答链
│   ├── pet/
│   │   ├── administrator.py      #   编排层（检索→重排→prompt→LLM→引用→记忆→经验）
│   │   ├── pet.py                #   宠物实体（等级/经验/分系）
│   │   ├── interact.py           #   互动（喂食/玩耍/训练/洗澡/睡觉）
│   │   ├── shop.py               #   商店（8 种道具）
│   │   ├── tasks.py              #   每日任务
│   │   ├── art.py                #   ASCII 艺术加载
│   │   ├── arts/                 #   35 个 ASCII 艺术文件
│   │   └── storage.py            #   宠物持久化
│   ├── memory/                   # 记忆系统
│   │   ├── store.py              #   MemoryStore（JSON 原子写入）
│   │   ├── profile.py            #   ProfileManager（jieba 主题提取）
│   │   ├── tasks.py              #   TaskManager（跨会话任务）
│   │   └── workflow.py           #   WorkflowTracker（2-gram 模式识别）
│   ├── persona/
│   │   ├── prompts.py            #   build_system_prompt（4 风格模板）
│   │   └── styles.py             #   风格元数据定义
│   ├── classify/tagger.py        # LLM 自动标签
│   ├── graph/
│   │   ├── extractor.py          #   LLM 抽取实体关系
│   │   ├── store.py              #   networkx 图谱存储
│   │   └── visualizer.py         #   HTML 可视化（vis.js）
│   ├── sync/
│   │   ├── tracker.py            #   增量同步
│   │   ├── checker.py            #   质量检查
│   │   └── dedup.py              #   SimHash 近似去重
│   ├── analyze/analyzer.py       # 数据表分析
│   ├── report/generator.py       # Markdown 报告生成
│   ├── reader/
│   │   ├── reader.py             #   智能阅读器
│   │   └── comparator.py         #   文档对比
│   ├── agent/                    # LLM Agent
│   │   ├── agent.py              #   ReAct 工具调用主循环
│   │   └── tools/                #   工具注册系统
│   │       ├── base.py           #     @register_tool 装饰器 + Tool 基类
│   │       └── builtin.py        #     内置工具集（search/list_docs/get_doc/read/...）
│   ├── image/generator.py        # 图像生成
│   ├── session/store.py          # 会话管理
│   └── ui/theme.py               # 终端主题（3 套）
│
├── web/                          # Web 后台
│   ├── app.py                    # FastAPI 工厂（create_app）
│   ├── routes/                   # 7 个 API 路由模块
│   │   ├── qa.py                 #   SSE 流式问答
│   │   ├── ingest.py             #   文档入库
│   │   ├── search.py             #   混合检索
│   │   ├── analyze.py            #   数据分析
│   │   ├── stats.py              #   仪表盘
│   │   ├── graph.py              #   知识图谱
│   │   └── pet.py                #   宠物管理
│   ├── templates/index.html      # 单页应用（7 页面）
│   └── static/                   # 前端资源
│       ├── app.js                #   入口重定向（→ js/app.js）
│       └── js/                   #   模块化 JS（按页面拆分）
│           ├── nav.js            #     侧边栏导航 + 页面切换
│           ├── qa.js             #     AI 问答（SSE 流式）
│           ├── ingest.js         #     文档入库（拖拽上传）
│           ├── search.js         #     混合检索
│           ├── analyze.js        #     数据分析
│           ├── dashboard.js      #     仪表盘
│           ├── graph.js          #     知识图谱（vis.js）
│           ├── pet.js            #     宠物管理
│           ├── state.js          #     全局状态管理
│           └── utils.js          #     通用工具函数
│
├── tests/                        # 测试套件（433+ 测试）
│   ├── retrieval/ memory/ pet/ persona/ sync/ ...
│
├── test_data/                    # 6 个测试文件
│
├── docs/                         # 文档
│   ├── PRD-web-backend.md
│   ├── prototype/web-prototype.html
│   └── specs/ superpowers/ ...
│
└── storage/                      # 本地数据（.gitignore）
    ├── metadata.db               #   SQLite 元数据（WAL 模式，含 -shm/-wal 伴生文件）
    ├── bm25_index.pkl            #   BM25 持久化索引
    ├── chroma/                   #   ChromaDB 向量库
    ├── models/bge-small-zh-v1.5/ #   本地向量模型
    ├── memory.json               #   记忆系统持久化
    ├── pet.json                  #   宠物状态持久化
    ├── graph.json                #   知识图谱 networkx 数据
    ├── graph.html                #   知识图谱 HTML 可视化
    ├── activity.json             #   启动页 Recent activity 记录
    ├── agent_config.json         #   Agent 配置（show_thoughts 等）
    ├── todo.json                 #   每日任务数据
    ├── cmd_history               #   命令历史记录
    ├── embedding_cache.db        #   向量缓存（SQLite WAL 模式）
    ├── memory/                   #   跨会话记忆（按会话名隔离，存储在 sessions/<name>/cross_session.json）
    ├── sessions/                 #   会话历史
    ├── uploads/                  #   原文件副本
    ├── uploads/quick/            #   快速入库内容
    ├── cache/                    #   解析缓存
    ├── images/                   #   生成图片
    ├── reports/                  #   生成的报告
    └── theme.json                #   主题配置
```

---

## 3. 整体架构

### 3.1 分层架构

IMA 采用清晰的分层架构，从上到下分为五层：

```
┌─────────────────────────────────────────────────────────────┐
│  入口层（Entry Layer）                                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │  CLI (run.py) │  │ REPL(core/cli)│  │ Web (web/)   │       │
│  │  23 顶层命令  │  │  40+ 子命令   │  │ 7 页面+API   │       │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘       │
└─────────┼─────────────────┼─────────────────┼───────────────┘
          │                 │                 │
          └─────────────────┼─────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  编排层（Orchestration Layer）                                │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  PetAdministrator（宠物知识库管理员）                  │    │
│  │  检索 → 重排 → Prompt → LLM → 引用 → 记忆 → 经验      │    │
│  └─────────────────────────────────────────────────────┘    │
│  ┌──────────────────────┐  ┌──────────────────────┐         │
│  │  RAGChain（问答链）   │  │  Agent（ReAct 工具）  │         │
│  └──────────────────────┘  └──────────────────────┘         │
└─────────────────────────────────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  能力层（Capability Layer）                                   │
│  ┌──────────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐    │
│  │ 检索层        │ │ 记忆系统  │ │ 人格系统  │ │ 宠物系统  │    │
│  │ BM25+向量     │ │ Profile  │ │ 4 风格    │ │ 等级/经验 │    │
│  │ +RRF+重排     │ │ +Tasks   │ │ +Prompt  │ │ +互动/商店│    │
│  │ +语义缓存+路由│ │          │ │          │ │          │    │
│  └──────────────┘ └──────────┘ └──────────┘ └──────────┘    │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐        │
│  │ 知识图谱  │ │ 同步/质量 │ │ 数据分析  │ │ 报告/阅读 │        │
│  │ networkx │ │ +去重    │ │ pandas   │ │ +对比     │        │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘        │
└─────────────────────────────────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  基础层（Foundation Layer）                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ LLM Client   │  │ Storage      │  │ Config       │       │
│  │ (Agnes/OpenAI│  │ (SQLite+文件) │  │ (Settings)   │       │
│  │  兼容协议)    │  │              │  │              │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 核心数据流

#### 入库流

```
用户文件
  │
  ▼
parser.parse(file_path)         → ParsedDocument（统一结构）
  │
  ▼
chunker.chunk_document(doc)     → List[Chunk]（带位置索引）
  │
  ▼
SHA256 去重检查（content_hash[:32] 作为 doc_id）
  │
  ▼
Tagger.generate_tags（可选，LLM 生成 3-5 个标签）
  │
  ▼
Storage.save_document()         → SQLite 写入 + BM25 增量索引 + 向量索引同步
```

#### 问答流（PetAdministrator 编排）

```
用户提问
  │
  ▼
route_query(query)              → 闲聊/问候？直接走 LLM，跳过检索
  │ 否
  ▼
答案语义缓存查询                → query embedding 相似度 ≥0.92？直接返回缓存答案
  │ 未命中
  ▼
ProfileManager.get_profile()    → 加载用户偏好（格式/风格/主题/地区）
TaskManager.get_active_tasks()  → 加载活跃任务
  │
  ▼
HybridRetriever.search(query)   → BM25 + 向量并发检索 + RRF 融合（k=60）
                                  粗排 BM25 top 50，精排向量 top_k，结果写入语义缓存
  │
  ▼
Reranker.rerank(query, top_5)   → LLM 对候选打 0-10 分重排序
  │
  ▼
build_system_prompt(            → 按风格（scholar/warrior/artisan/neutral）
  style, pet, profile,            拼装 system prompt，注入宠物状态警告 + 输出规范
  tasks, sources)                 （禁止 LaTeX、禁止重复引用列表等）
  │
  ▼
LLMClient.chat(messages)        → 生成回答（temperature=0.3）
  │  失败降级 → get_llm_degrade_message()
  ▼
extract_citations(answer)       → 提取 [n] 引用标记映射到 sources
  │
  ▼
_sanitize_latex(answer)         → 清理 $$、\times、\mathbf{} 等 LaTeX 语法
  │
  ▼
写入答案语义缓存
  │
  ▼
ProfileManager.update_from_query() → 更新主题/地区/交互次数
Pet.gain_exp(10, "qa")          → 宠物获得经验，可能升级/分系
  │
  ▼
AnswerResult（text + citations + sources + pet_events）
```

#### Web SSE 问答流

```
浏览器 fetch /api/qa/stream?q=...&persona=...
  │
  ▼
qa.py: HybridRetriever → Reranker → build_system_prompt
  │
  ▼
LLMClient.chat_stream()         → async generator
  │
  ▼
SSE 事件流：
  event: token     data: {text: "<chunk>"}
  event: token     data: {text: "<chunk>"}
  ...
  event: citation  data: {marker, title, snippet, score}
  event: done      data: {full_text: "..."}
```

### 3.3 多入口共享 core 服务

REPL 在后台线程启动 Web 服务，三套入口共享同一份 `storage/` 数据：

```
┌─────────────┐
│  CLI 命令    │ ─────────────────────────┐
│  (run.py)   │                          │
└─────────────┘                          ▼
                                  ┌─────────────┐
┌─────────────┐                  │  core/ 模块  │
│  REPL       │ ────────────────▶│  Storage    │
│  (core/cli) │                  │  HybridRetr │◀────┐
└─────────────┘                  │  PetAdmin   │     │
        │                        │  ...        │     │
        │ 后台线程                 └─────────────┘     │
        ▼                                ▲            │
┌─────────────┐                         │            │
│  Web 后台    │ ────────────────────────┘────────────┘
│  (web/)     │   通过 routes/ 调用 core 模块
└─────────────┘
```

---

## 4. 配置中心

### 文件：[config.py](config.py)

`Settings` dataclass 作为全局配置单例，从 `.env` 加载环境变量，提供统一访问入口。

#### 关键配置项

| 字段 | 默认值 | 说明 |
|---|---|---|
| `agnes_api_key` | （从 .env） | Agnes AI API Key |
| `agnes_base_url` | `https://apihub.agnes-ai.com/v1` | LLM API 基址 |
| `llm_model` | `agnes-2.0-flash` | LLM 模型名 |
| `image_model` | `agnes-image-2.1-flash` | 图像生成模型名 |
| `image_size` | `1024x1024` | 图像默认尺寸 |
| `storage_path` | `./storage` | 本地存储根目录 |
| `chunk_size` | `512` | 分块大小 |
| `chunk_overlap` | `64` | 分块重叠 |
| `rag_top_k` | `6` | RAG 返回条数 |
| `llm_max_tokens` | `1024` | LLM 最大 token |

#### 派生路径属性

- `uploads_dir` — 原文件存储目录
- `chroma_dir` — ChromaDB 持久化目录
- `memory_path` — 记忆数据文件路径
- `db_path` — SQLite 文件路径
- `cache_dir` — 解析缓存目录
- `bm25_index_path` — BM25 索引文件路径
- `images_dir` — 生成图片目录

#### 关键方法

- `ensure_dirs()` — 创建所有必要的存储目录
- `has_llm()` — 判断 API Key 是否有效配置（避免 `sk-xxx` 占位符）

#### 全局单例

```python
settings = Settings()  # 模块级单例，全项目共享
```

---

## 5. 入口层

### 5.1 CLI 入口

#### 文件：[run.py](run.py)

基于 `click` 框架实现的 CLI 入口，通过 `pyproject.toml` 注册为 `ima` 全局命令。

##### 命令组结构

```python
@click.group(invoke_without_command=True)
def cli(ctx):
    """主命令组。不带子命令时默认进入 REPL。"""
    _ensure_dirs()
    if ctx.invoked_subcommand is None:
        from repl import main as repl_main
        repl_main()
```

> ⚠️ **关键约束**：所有 `@cli.command` 必须定义在 `cli` group 之后，否则会触发 `NameError`（项目早期踩过的坑）。

##### 23 个顶层命令

| 命令 | 说明 |
|---|---|
| `web` | 启动 Web 后台（`--host` `--port`） |
| `init` | 首次运行引导或重新配置 |
| `chat` | 进入交互式 REPL |
| `ingest <path>` | 入库文件或目录（递归） |
| `note <text>` | 文本直入库 |
| `clip` | 剪贴板入库（截图/文字/URL 自动识别） |
| `url <url>` | 网页入库（自动提取正文） |
| `list` | 列出所有文档 |
| `search <query>` | BM25 智能搜索（`--tag` `--limit` `--plain`） |
| `ask <question>` | 一次性 RAG 问答（基于 PetAdministrator） |
| `show <doc_id>` | 查看文档详情 |
| `stats` | 知识库统计 |
| `retag` | 重新生成/补全标签（`--force` `-d ID`） |
| `rebuild` | 重建索引（BM25 + 可选向量） |
| `memory` | 记忆管理（format/style/topic/region/task） |
| `watch <dir>` | 监控文件夹自动入库 |
| `report <doc_id>` | 生成 Markdown 报告 |
| `analyze <path>` | 数据表分析 |
| `sync <dir>` | 增量同步目录 |
| `health` | 知识库质量报告 |
| `dedup` | 近似重复扫描 |
| `doctor` | 环境健康检查 |
| `delete <doc_id>` | 删除文档 |

##### `graph` 子命令组（5 个）

| 子命令 | 说明 |
|---|---|
| `graph build` | 构建知识图谱（LLM 抽取实体关系） |
| `graph stats` | 图谱统计 + 节点列表 |
| `graph neighbors <name>` | 查询节点邻居 |
| `graph export` | 导出 HTML 可视化（自动打开浏览器） |
| `graph clear` | 清空图谱 |

##### 关键辅助函数

- `_ingest_one(storage, file_path, verbose, auto_tag)` — 单文件入库核心：解析 → 分块 → 去重 → 自动标签 → 保存，被 `ingest` / `watch` 命令复用

### 5.2 REPL 入口

#### 文件：[repl.py](repl.py) → [core/cli/](core/cli)

项目最核心的交互入口，实现 Claude Code 风格的终端常驻对话界面。原 `repl.py`（约 4300 行）已模块化拆分到 `core/cli/` 目录：

| 模块 | 职责 |
|---|---|
| [main.py](core/cli/main.py) | REPL 启动入口（`main()` 函数） |
| [repl.py](core/cli/repl.py) | REPL 主类（命令分发 + AI 对话） |
| [chat.py](core/cli/chat.py) | AI 对话渲染（Markdown + 引用 + 宠物头像） |
| [completer.py](core/cli/completer.py) | 命令自动补全（CommandCompleter） |
| [welcome.py](core/cli/welcome.py) | 启动页渲染 + 活动记录（按会话过滤） |
| [constants.py](core/cli/constants.py) | 常量、命令列表、别名表、console 实例 |
| [commands/](core/cli/commands) | 各命令处理器（Mixin 模式：agent/docs/graph/memory/pet/pipe/session/sync/analyze） |

> 根目录 `repl.py` 现为薄封装，仅 `from core.cli.main import main` 委托执行。

##### 核心特性

- **欢迎面板**：左右分栏布局（参照 Claude Code v2.1 风格）
  - 左区（约 60%）：`Welcome back!` 欢迎语 + 像素机器人 ASCII 图 + 模型名 + 在线状态
  - 右区（约 40%）：`Tips for getting started`（5 条核心命令） + `Recent activity`（最近 3 条 + 文档统计）
  - 中间 `│` 竖线分隔，顶部边框嵌入 `── IMA v4.1 ──` 标题
  - 使用 `rich.cells.cell_len` 精确计算中文列宽（中文占 2 列），确保排版对齐
- **命令补全**：自定义 `CommandCompleter`（继承 `prompt_toolkit.Completer`）
  - 输入 `/` 弹出所有命令 + 中文描述
  - 子命令多级嵌套（如 `/memory format table`）
  - 别名自动解析（`/s` → `/search`，`/m` → `/memory` 等 28 个别名）
- **AI 回答 Markdown 渲染**：`rich.Markdown` 渲染加粗/列表/标题
- **橙色 `>` 提示符**（Claude Code 风格）
- **流式输出**：橙色 `⏺` 圆点标记 + 首 token Spinner
- **多轮对话**：保留最近 20 条 history（10 轮）
- **管道操作**：`/search 骨灰 | ask 差异`
- **活动记录**：每次操作记录到 `storage/activity.json`，启动页展示英文标签（Search/Ingest/Q&A 等）。**2026-07-15 更新**：活动记录增加 `session` 字段，启动页按当前会话过滤（向后兼容旧记录）

##### `CommandCompleter` 类

```python
class CommandCompleter(Completer):
    def __init__(self, commands, sub_menus, sub_desc):
        """接收命令元组列表、子菜单嵌套 dict、路径元组描述 dict"""
    
    def _resolve(self, cmd: str) -> str:
        """别名解析（如 /s → /search）"""
    
    def get_completions(self, document, complete_event):
        """prompt_toolkit 核心回调，按空格逐级深入子菜单"""
```

##### `REPL` 类核心方法

| 方法分类 | 方法 | 说明 |
|---|---|---|
| **生命周期** | `run()` | 主循环：清屏 → 渲染欢迎面板 → 循环读取分发 |
| **输入分发** | `_handle_pipe` | 管道处理（` \| ` 分段） |
| | `_handle_command` | `/` 命令分发器（含别名展开 + 子命令菜单触发） |
| | `_handle_read_input` | 阅读模式专用输入（n/p/数字/i/q） |
| | `_handle_chat` | AI 对话三层降级：PetAdministrator → 数据分析追问 → RAGChain → 纯 LLM |
| **子命令菜单** | `_show_subcommand_menu` | 用 `radiolist_dialog` 弹出选择菜单 |
| | `_prompt_subcmd_params` | 解析占位符 `<名称>` / `<名称\|a\|b\|c>` 并交互式填充 |
| **AI 渲染** | `_render_answer` | 渲染管理员回答（宠物头像 + Markdown + 引用 + 升级提示） |
| **命令处理器** | `_cmd_search` `_cmd_ingest` `_cmd_analyze` ... | 30+ 个 `/cmd` 处理器 |
| **辅助** | `_record_workflow` | 记录命令到 WorkflowTracker，给出下一步推荐 |
| | `_pet_gain_exp` | 宠物经验埋点（检查每日任务、发放奖励） |
| | `_resolve_doc_id` | 按前缀匹配完整 doc_id |

##### 输入分发责任链

```
用户输入
  │
  ├─ 含 " | "  →  _handle_pipe（管道）
  │
  ├─ 以 "/" 开头  →  _handle_command（命令）
  │     ├─ 别名展开
  │     ├─ 数字编号菜单触发
  │     └─ 子命令菜单触发（radiolist_dialog）
  │
  ├─ 阅读模式中  →  _handle_read_input
  │
  └─ 其他  →  _handle_chat（AI 对话）
        ├─ PetAdministrator 路径（优先）
        ├─ 数据分析追问检测
        └─ RAGChain 路径（降级）
```

##### 重要常量（定义在 [constants.py](core/cli/constants.py)）

- `ASCII_LOGO_LARGE` — IMA 大字 Logo
- `PIXEL_PET_ASCII` — 启动页像素机器人吉祥物（8 行，Claude Code 风格）
- `_LABEL_MAP` — 活动记录英文标签映射（qa→Q&A, search→Search, ingest→Ingest 等）
- `_ICON_MAP` — 活动记录单字母图标映射（备用）
- `HELP_TEXT` — 完整帮助文本（6 大节）
- `COMMAND_LIST` — 36 个 `(命令, 描述)` 元组
- `_SUB_MENU_NESTED` — NestedCompleter 用的多级嵌套子命令字典
- `_SUB_MENU_DESC` — 子命令路径元组 → 中文描述（约 50 条）
- `CMD_ALIASES` — 28 个简写别名映射

### 5.3 Web 入口

#### 文件：[web/app.py](web/app.py)

FastAPI 应用工厂模式。

```python
def create_app() -> FastAPI:
    """工厂函数：
    1. 创建 FastAPI 实例（关闭 docs/redoc）
    2. 添加 CORS 中间件（允许所有来源，适配内网）
    3. 挂载 /static
    4. 懒导入注册 7 个路由模块（统一 /api 前缀）
    5. 内联定义 @app.get("/") 首页路由（渲染 index.html，注入初始统计）
    """
```

##### 启动方式

```bash
# 方式 1：REPL 内启动（后台线程）
ima
> /web
> /web stop

# 方式 2：CLI 命令
ima web
ima web --host 0.0.0.0  # 内网访问
ima web -p 8080          # 指定端口

# 方式 3：uvicorn 直接启动
uvicorn web.app:create_app --factory --host 0.0.0.0 --port 8501
```

默认端口 `8501`。

---

## 6. 核心模块详解

### 6.1 存储层

#### 文件：[core/storage.py](core/storage.py)

SQLite 元数据 + 原文件存储，是整个项目的数据基础。

##### 数据模型

```python
@dataclass
class DocumentRecord:
    """文档记录（对应 documents 表一行）"""
    id: str                        # SHA256(内容)[:32]
    title: str
    file_name: str
    file_path: str                 # 原始路径
    file_type: str                 # 扩展名
    file_size: int
    content_hash: str              # 内容 SHA256，用于去重
    language: str = "unknown"
    meta: Dict[str, str] = field(default_factory=dict)
    created_at: str
    chunk_count: int = 0
    total_tokens: int = 0
    tags: List[str] = field(default_factory=list)

@dataclass
class ChunkRecord:
    """分块记录（对应 chunks 表一行）"""
    id: str                        # f"{doc_id}_{chunk_index}"
    doc_id: str
    index: int
    content: str
    token_count: int
    start_char: int
    end_char: int
```

##### 数据库表结构

- `documents` — 文档元信息（含 `tags` JSON 字段）
- `chunks` — 文档分块（外键 `doc_id` ON DELETE CASCADE）
- 索引：`idx_documents_hash`、`idx_chunks_doc`

##### `Storage` 类关键方法

| 方法 | 说明 |
|---|---|
| `attach_vector_index(vector_index)` | 注入向量索引，使后续 save/delete 自动同步向量 |
| `detach_vector_index()` | 解除向量索引绑定 |
| `save_document(parsed, chunks, copy_file, tags)` | 保存文档（去重 + 复制原文件 + 写 DB + BM25 增量 + 向量同步） |
| `get_document(doc_id)` | 按 ID 查文档 |
| `list_documents(limit, offset)` | 列出文档（按时间倒序） |
| `get_chunks(doc_id)` | 获取文档所有分块 |
| `search_chunks(keyword, limit)` | 关键词 LIKE 模糊搜索（旧版兼容） |
| `bm25_search(query, top_k)` | BM25 检索（自动回填 content 和 doc_title） |
| `stats()` | 知识库统计 |
| `delete_document(doc_id)` | 删除文档（含分块、原文件、BM25、向量索引） |
| `rebuild_bm25_index()` | 从数据库重建 BM25 索引 |
| `rebuild_vector_index(vector_index)` | 全量重建向量索引 |
| `update_document_tags(doc_id, tags)` | 更新标签 |
| `update_document_title(doc_id, title)` | 更新标题 |
| `list_all_tags()` | 统计所有标签及文档数 |
| `list_documents_by_tag(tag)` | 按标签筛选文档 |
| `rename_tag(old, new)` | 重命名标签 |
| `merge_tag(source, target)` | 合并标签 |

##### 设计要点

- **二级目录组织**：原文件副本按 `doc_id[:2]` 子目录存放，避免单目录文件过多
- **启动时同步**：`_sync_bm25_from_db()` 检查 BM25 索引与 DB 数量一致性，不匹配则重建
- **向量索引解耦**：通过 `attach_vector_index` 注入，未注入时只走 BM25
- **向量同步容错**：向量索引同步失败不阻塞入库（只记日志），BM25 仍可用

### 6.2 入库层

#### 6.2.1 多格式解析器

##### 文件：[core/ingestion/parser.py](core/ingestion/parser.py)

统一解析 11+ 种文件格式，输出 `ParsedDocument` 结构。

```python
@dataclass
class ParsedDocument:
    text: str
    title: str
    file_path: Path
    file_type: str
    language: str = "unknown"
    meta: Dict[str, str] = field(default_factory=dict)
```

##### 支持的格式

| 格式 | 解析库 | 说明 |
|---|---|---|
| PDF | PyMuPDF (fitz) | 文本层 < 50 字符自动走 OCR |
| Word .docx | python-docx | 段落提取 |
| Word .doc | macOS textutil | 转 txt 后读取 |
| Excel .xlsx | openpyxl | 逐 sheet 转 TSV |
| PPT .pptx | python-pptx | 逐 slide 提取 |
| 图片 | PaddleOCR（主）+ pytesseract（降级） | PaddleOCR 原图直传（内部自带预处理）；Tesseract 降级时外部预处理（灰度+二值化+放大） |
| Markdown/TXT | 直接读取 | |
| HTML | trafilatura | 正文抽取 |
| 代码 | 直接读取 | 带语言标签 |

##### 关键函数

- `parse(file_path) -> ParsedDocument` — 公共入口，按扩展名分发
- `is_supported(file_path) -> bool` — 判断格式支持
- `_parse_pdf` — PDF 解析（文本层 < 50 字符自动走 OCR）
- `_parse_image` — 图片 OCR
- `_ocr_pdf_page(page)` — PDF 单页渲染为 200 DPI 图片后 OCR
- `_ocr_image(image)` — 图片 OCR 入口：PaddleOCR 优先（原图直传）→ Tesseract 降级（外部预处理）
- `_ocr_image_paddle(image)` — PaddleOCR 识别（处理 3.x API 返回格式）
- `_ocr_image_tesseract(image)` — Tesseract 识别（降级方案）
- `_preprocess_image(image)` — 图片预处理（灰度+自动对比度+Otsu 二值化+小图放大，仅 Tesseract 路径）
- `_get_paddle_ocr()` — PaddleOCR 单例（懒加载，全局复用）
- `_check_ocr()` — 检测 PaddleOCR 或 Tesseract 任一可用（带缓存）
- `reset_ocr_cache()` — 重置 OCR 检测缓存（含 PaddleOCR 单例）

##### 设计模式

- **注册表 + 策略模式**：`_PARSER_MAP` 字典分发，新增格式只需注册一个函数
- **可选依赖延迟导入**：第三方库在函数内 import，缺失时给出明确错误
- **OCR 双引擎降级**：PaddleOCR 优先（原图直传，内部自带预处理）→ Tesseract 降级（外部预处理：灰度+二值化+放大）；OCR 不可用时返回 `meta={"ocr_unavailable": "true"}`

#### 6.2.2 智能分块器

##### 文件：[core/ingestion/chunker.py](core/ingestion/chunker.py)

```python
@dataclass
class Chunk:
    content: str
    index: int
    start_char: int
    end_char: int
    token_count: int = 0
```

##### 分块策略

```python
def chunk_document(doc, chunk_size=512, chunk_overlap=64) -> List[Chunk]:
    """
    管道流程：
    1. 双换行切分段落
    2. 合并过短段落接近目标大小
    3. 长段二次切分（带 overlap，优先在 \n 。 ！ ？ . ； 处切）
    """
```

- 切分搜索范围：`max_size * 0.7` 之后找分隔符
- 分隔符优先级：`\n` > `。` > `！` > `？` > `. ` > `；`
- token 估算：`字符数 // 2`
- 位置追踪：用 `global_pos` 维护每段在原文中的绝对字符位置

#### 6.2.3 快速入库

##### 文件：[core/ingestion/quick.py](core/ingestion/quick.py)

三种无需先保存文件的快速入库，统一保存到 `storage/uploads/quick/`。

| 函数 | 说明 |
|---|---|
| `save_text(text, title)` | 文本直入库 |
| `save_clipboard()` | 剪贴板入库（先试图片 → 再试 pbpaste → URL 自动转发） |
| `save_url(url)` | URL 入库（抓网页 → 提取标题+正文 → 加来源前缀） |

##### 设计要点

- 内置轻量 `_TextExtractor`（基于 `HTMLParser`）作为 trafilatura 的备选
- User-Agent 伪装 Chrome 120
- URL 抓取超时 15s，pbpaste 超时 2s
- 文件名清洗：`re.sub(r'[\\/:*?"<>|]', "_", title)[:60]`

### 6.3 检索层

#### 6.3.1 BM25 索引

##### 文件：[core/search/bm25.py](core/search/bm25.py)

基于 jieba 中文分词的 BM25 关键词检索。**P6 新增倒排索引**，搜索时只遍历含目标词的文档。

```python
@dataclass
class SearchResult:
    chunk_id: str
    doc_id: str
    score: float
    content: str = ""    # 由调用方填充
    doc_title: str = ""  # 由调用方填充
```

##### `BM25Index` 类

| 方法 | 说明 |
|---|---|
| `add(chunk_id, doc_id, content)` | 添加/更新（已存在先 remove） |
| `remove(chunk_id) -> bool` | 删除 |
| `clear()` | 清空 |
| `search(query, top_k=10)` | BM25 打分检索（**倒排索引加速**） |
| `save()` / `_load()` | pickle 持久化（损坏自动重置） |
| `info()` | 返回 chunks/vocabulary/total_tokens |
| `__len__()` | 索引文档数 |

##### 倒排索引（P6 新增）

```python
# 倒排索引结构：term → {chunk_id: tf}
self._inverted_index: Dict[str, Dict[str, int]] = {}
```

搜索时通过倒排索引直接定位含目标词的文档，避免遍历所有文档，大幅提升检索速度。

##### 关键参数

- `k1 = 1.5`（词频饱和参数）
- `b = 0.5`（文档长度归一化参数，**从 0.75 降低**，减少对长文档的惩罚）
- BM25 公式：`score = Σ IDF(qi) * (f*(k1+1)) / (f + k1*(1-b+b*|d|/avgdl))`
- IDF 公式：`IDF(qi) = ln((N - n(qi) + 0.5)/(n(qi) + 0.5) + 1)`，并做 **IDF 截断** `idf = max(0.0, ...)` 避免词在多数文档出现时产生负值反向扣分
- **参数不持久化**：`k1`/`b` 不存入 pickle，作为运行时参数由代码默认值决定，调整参数后无需重建索引即可立即生效

##### 分词

```python
def _normalize_text(text: str) -> str:
    """文本归一化：NFKC 全角转半角 + 英文小写"""

def tokenize(text: str) -> List[str]:
    """归一化 + 多模式分词 + 停用词/单字符标点过滤"""
```

- **文本归一化**：`_normalize_text()` 先做 NFKC 归一化（全角→半角，如 `（）`→`()`、`ＡＢＣ`→`abc`、`１２３`→`123`），再英文小写，消除格式差异
- **多模式分词**：同时用 `jieba.cut_for_search`（搜索引擎模式）+ `jieba.cut(cut_all=True)`（全模式），取并集去重；全模式补充更细粒度切分，提升召回率（可能引入噪音，但 BM25 的 IDF 会自动降低无意义词的权重）
- 内置中英文停用词表 `_STOP_WORDS`，精简自原版，移除了"通过/进行/根据/按照"等在专业文档中可能承载实际语义的词，避免误杀

#### 6.3.2 向量索引

##### 文件：[core/retrieval/vector.py](core/retrieval/vector.py)

基于 ChromaDB + `BAAI/bge-small-zh-v1.5` 的语义向量检索。**核心特点：优雅降级**。

```python
@dataclass
class VectorResult:
    chunk_id: str
    doc_id: str
    score: float
```

##### `VectorIndex` 类

| 方法 | 说明 |
|---|---|
| `is_available() -> bool` | 向量索引是否可用 |
| `build_index(chunks)` | 全量构建（先删后建，带 embedding 缓存） |
| `add_chunk(chunk)` / `add_chunks_batch(chunks)` | 增量添加（带 embedding 缓存） |
| `delete_chunk(chunk_id)` / `delete_document(doc_id) -> int` | 删除（按 metadata 过滤） |
| `search(query, top_k=10)` | 检索（query 也走缓存，distance 转 score：`score = 1.0 - distance`） |
| `cache_stats() -> dict` | 返回 embedding 缓存统计（条目数） |
| `clear_cache()` | 清空 embedding 缓存 |

##### Embedding 缓存层

`_EmbeddingCache` 类通过 SQLite 持久化 `content hash → embedding vector` 映射，避免重建索引时重复计算 embedding：

- 存储路径：`storage/embedding_cache.db`（WAL 模式，支持并发读）
- key 为文本 SHA256 hash，value 为 pickle 序列化的 embedding 向量
- `_embed_with_cache(texts)` 统一入口：先批量查缓存 → 未命中的批量计算 → 写入缓存
- `build_index` / `add_chunk` / `add_chunks_batch` / `search` 均走缓存
- 重建索引时，已缓存的内容秒级完成，无需重新跑模型推理

##### 降级机制

- 模型/依赖加载失败时 `is_available()` 返回 False
- 所有操作静默返回空，系统退化为纯 BM25
- `chromadb` / `sentence_transformers` 在方法内 import，避免模块加载失败影响整个项目

##### 中国大陆友好

```python
# 在 import chromadb 之前设置 HF 镜像
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
```

本地模型路径：`storage/models/bge-small-zh-v1.5/`（需用 curl 从 hf-mirror.com 手动下载 `model.safetensors`）。

#### 6.3.3 混合检索 + RRF 融合（并发 + 两级 + 语义缓存）

##### 文件：[core/retrieval/hybrid.py](core/retrieval/hybrid.py)

```python
@dataclass
class HybridResult:
    chunk_id: str
    doc_id: str
    score: float
    source: str           # "bm25" / "vector" / "both"
    content: str = ""
    doc_title: str = ""
    paragraph_num: int = 0  # 真实段落号（由 storage.enrich_hybrid_results 填充）
```

##### `HybridRetriever` 类

```python
class HybridRetriever:
    def __init__(
        self,
        bm25_index: BM25Index,
        vector_index: VectorIndex,
        storage=None,
        semantic_cache: Optional[SemanticCache] = None,
        enable_cache: bool = True,
    ):
        ...

    def search(self, query: str, top_k: int = 10, use_cache: bool = True) -> List[HybridResult]:
        """
        0. 语义缓存查询（命中直接返回）
        1. BM25 粗排 top 50 + 向量粗排 top 50（并发 ThreadPoolExecutor）
        2. RRF 融合取 top_k
        3. 若有 storage 引用，批量补全 content/doc_title/paragraph_num
        4. 写入语义缓存
        """
```

> **引用溯源修复**：BM25 的 `_DocEntry` 不存 content/title，`VectorResult` 也只有 3 个字段，
> 所以混合检索后的 `HybridResult` 可能 content/doc_title 为空。
> `Storage.enrich_hybrid_results()` 用 chunk_id 批量从 SQLite 查出真实 content/doc_title/index_in_doc，
> 修复了引用溯源标题缺失和段落号虚假问题。

##### RRF 融合算法

```python
RRF_K = 60  # k 越大，排名差异的影响越小

# score = Σ 1/(k + rank)
for rank, r in enumerate(bm25_results, 1):
    scores[r.chunk_id] += 1.0 / (RRF_K + rank)
for rank, r in enumerate(vector_results, 1):
    scores[r.chunk_id] += 1.0 / (RRF_K + rank)
```

##### 并发检索

```python
executor = _get_executor()  # 共享 ThreadPoolExecutor(max_workers=2)
coarse_k = max(top_k * 5, 50)
future_bm25 = executor.submit(self.bm25.search, query, coarse_k)
future_vec = executor.submit(self.vector.search, query, coarse_k)
bm25_results = future_bm25.result(timeout=30)
vector_results = future_vec.result(timeout=30)
```

- BM25 与向量检索并行执行，延迟从串行叠加变为取两者最大值
- 粗排召回 50 个候选，既保证召回率又减少 RRF 计算量

##### 语义缓存集成

`HybridRetriever` 内置 `SemanticCache`，相同/相似 query 直接返回缓存结果：

- L1 精确缓存：query hash 完全匹配（<1ms）
- L2 语义缓存：embedding cosine 相似度 ≥0.92（<5ms）
- 命中后返回缓存的 `HybridResult` 列表，跳过全部检索计算
- 未命中则正常检索，并把结果写入缓存

#### 6.3.4 LLM 重排序

##### 文件：[core/retrieval/rerank.py](core/retrieval/rerank.py)

```python
@dataclass
class RerankResult:
    chunk_id: str
    doc_id: str
    score: float          # 原 hybrid 分数
    source: str
    content: str
    doc_title: str
    relevance_score: float  # LLM 0-10 分
    reason: str
    paragraph_num: int = 0  # 真实段落号（从 HybridResult 透传）
```

##### `Reranker` 类

| 方法 | 说明 |
|---|---|
| `rerank(query, candidates, top_n=5)` | 主入口，失败时调用 `_fallback_results` |
| `_call_llm_for_scores(query, candidates)` | 构造 prompt 让 LLM 返回 JSON 数组（`temperature=0.0`） |
| `_parse_scores(response)` | 静态方法，**三级健壮解析** |
| `_normalize_scores(data)` | 支持列表格式与字典格式 |
| `_fallback_results(candidates, top_n)` | 降级保留原顺序 |

##### 三级 JSON 解析

1. 直接 `json.loads`
2. 正则提取 `[...]` 片段
3. 正则提取 `{...}` 片段，清理 markdown code block 标记

#### 6.3.5 引用编号提取

##### 文件：[core/retrieval/citation.py](core/retrieval/citation.py)

```python
@dataclass
class Citation:
    marker: str        # 如 "[1]"
    doc_id: str
    title: str
    paragraph_num: int
    snippet: str

def extract_citations(answer: str, sources: List[dict]) -> List[Citation]:
    """
    正则 r"\[(\d+)\]" 匹配 [1] [12] [1][2] 等形式
    [1] → sources[0]（1-based 标记转 0-based 索引）
    越界跳过，按出现顺序去重
    """
```

#### 6.3.6 查询路由

##### 文件：[core/retrieval/router.py](core/retrieval/router.py)

根据查询意图决定是否需要走知识库检索，闲聊/问候直接走 LLM，知识查询走完整 RAG。

```python
def route_query(query: str) -> QueryType:
    """返回 'chat' | 'knowledge' | 'greeting'。"""
```

**分流策略**：

| 类型 | 判断条件 | 处理 |
|---|---|---|
| `greeting` | 短文本（≤15 字）+ 含问候关键词（你好/谢谢/hi/早上好等） | 直接 LLM，跳过检索 |
| `chat` | 元问题（你是谁/你能做什么）或短文本无明确信号 | 直接 LLM，跳过检索 |
| `knowledge` | 含政策/流程/金额/什么是/如何等关键词，或长文本 | 走完整 RAG + 缓存 |

**收益**：问候/闲聊响应从 1.5-5s 降至 ~200ms。

#### 6.3.7 语义缓存

##### 文件：[core/retrieval/semantic_cache.py](core/retrieval/semantic_cache.py)

基于 query embedding 相似度匹配的缓存层，与精确缓存互补。

```python
class SemanticCache:
    def __init__(self, threshold=0.92, ttl=1800, max_size=500):
        ...

    def get(self, query, query_embedding=None) -> Optional[CacheEntry]:
        # L1 精确缓存 → L2 语义相似度匹配
        ...

    def put(self, query, query_embedding, answer, citations=None, sources=None):
        # 写入缓存，TTL 过期自动淘汰，超容量 LRU 淘汰
        ...
```

**特点**：

- L1 精确 + L2 语义，命中率 40-60%
- TTL 30 分钟，LRU 淘汰
- 线程安全（`threading.RLock`）
- 同时用于检索层（`HybridRetriever`）和答案层（`PetAdministrator`）

#### 6.3.8 LaTeX 输出清理

##### 文件：[core/cli/chat.py](core/cli/chat.py)、[core/pet/administrator.py](core/pet/administrator.py)

LLM 偶尔会在 Markdown 中输出 LaTeX 数学公式（如 `$$6520.92 \\times 2 = \\mathbf{13,041.84元}$$`），Rich Markdown 无法渲染，会原样显示转义字符，影响可读性。

**三层防护**：

1. **Prompt 禁止**（[core/persona/prompts.py](core/persona/prompts.py)）：system prompt 明确要求"绝对禁止用 LaTeX 公式语法"
2. **流式渲染清理**（[core/cli/chat.py](core/cli/chat.py)）：每个 token 累加后调用 `_sanitize_latex()` 清理
3. **缓存清理**（[core/pet/administrator.py](core/pet/administrator.py)）：答案写入缓存前/缓存命中回放前都清理

**清理规则**：

```python
def _sanitize_latex(text: str) -> str:
    # 去掉 $$ / $ 包装
    # \\times -> ×, \\div -> ÷, \\approx -> ≈, \\leq -> ≤, \\geq -> ≥ ...
    # \\mathbf{...} / \\text{...} -> 只保留花括号内容
    # \\ -> 换行
```

### 6.4 LLM 层

#### 6.4.1 Agnes LLM 客户端

##### 文件：[core/llm/client.py](core/llm/client.py)

封装 Agnes AI（OpenAI 兼容协议）的 LLM 调用。

```python
class LLMError(Exception):
    """LLM 调用失败统一异常"""

class LLMClient:
    def __init__(self):
        """校验 has_llm()，创建 OpenAI(api_key, base_url, timeout=60.0)"""
    
    def chat(self, messages, temperature=0.3, max_tokens=None, max_retries=3) -> str:
        """同步对话，带指数退避重试（1s/2s/4s）"""
    
    def chat_stream(self, messages, temperature=0.3, max_tokens=None) -> Iterator[str]:
        """流式，不重试（避免内容重复）；跳过空 choices chunk"""

def get_llm() -> LLMClient:
    """单例工厂"""
```

##### 重试策略

- 对 `_RETRYABLE_ERRORS`（APIConnectionError/APITimeoutError/APIStatusError）重试
- 对 5xx 状态码单独判断重试
- 指数退避：`wait = 2 ** attempt`
- 流式不重试原则：避免已输出 token 重复

> ⚠️ **关键修复**：`chat_stream` 中要 `if not chunk.choices: continue` 跳过空 chunk（Agnes 会发只含 usage/role 的元 chunk）。

#### 6.4.2 统一降级提示

##### 文件：[core/llm/degrade.py](core/llm/degrade.py)

提供 LLM 不可用时的统一用户可见降级文案。

```python
def get_llm_degrade_message(error=None, has_sources=False, source_count=0) -> str:
    """
    有资料：⚠ LLM 不可用(异常细节)，已降级为检索模式，展示 N 条相关原文
    无资料：⚠ LLM 不可用(异常细节)，且未检索到相关资料
    """
```

内置 `_ERROR_HINTS` 错误类型 → 排查建议映射表（Timeout/ConnectError/RateLimitExceeded/AuthenticationError 等）。

### 6.5 问答编排

#### 6.5.1 RAG 问答链

##### 文件：[core/qa/chain.py](core/qa/chain.py)

RAG 完整流程编排，支持同步与流式两种模式。

```python
@dataclass
class Answer:
    question: str
    content: str
    citations: list
    retrieved: list
    reranked: list
    confidence: float
    low_confidence: bool
    
    @property
    def has_answer(self) -> bool:
        return bool(self.content)

class RAGChain:
    def __init__(self, storage=None, hybrid_retriever=None, reranker=None):
        """支持依赖注入；未传时自建"""
    
    def ask(self, question, top_k=None, history=None) -> Answer:
        """同步问答，8 步流程"""
    
    def ask_stream(self, question, top_k=None, history=None) -> Iterator[str]:
        """流式问答，带进度提示 emoji"""
```

##### `ask` 八步流程

1. Query expansion（有 history 时调用 `_expand_query`，从上文 AI 回答提取关键短句拼接）
2. 混合检索（`hybrid.search`，`top_k = top_k or settings.rag_top_k`）
3. 重排序（通过 `create_reranker()` 工厂创建：优先 Cross-Encoder `bge-reranker-v2-m3`，失败降级 LLM；`top_n=min(settings.reranker_top_n, len)`）
4. 确定最终结果（reranked 优先）
5. 构造 Prompt（置信度阈值 `DEFAULT_CONFIDENCE_THRESHOLD=0.05`，低置信度加警告）
6. LLM 生成（`temperature=0.2`，失败调用 `get_llm_degrade_message`）
7. 构造引用列表
8. 计算置信度（`final_results[0].score`）

#### 6.5.2 宠物知识库管理员（编排层核心）

##### 文件：[core/pet/administrator.py](core/pet/administrator.py)

**所有 AI 交互的统一入口**，串联检索 → 重排 → prompt → LLM → 引用 → 记忆 → 宠物经验。

```python
@dataclass
class AnswerResult:
    text: str
    citations: List[Citation] = field(default_factory=list)
    sources: List[RerankResult] = field(default_factory=list)
    pet_events: dict = field(default_factory=dict)
    related_tasks: Optional[List] = None

class PetAdministrator:
    def __init__(self, pet, storage, memory_store, hybrid_retriever, reranker, llm):
        """依赖注入所有组件"""
    
    def ask(self, query: str, style_override: Optional[str] = None) -> AnswerResult:
        """主入口：用户提问 → 带引用的回答"""
```

##### `ask` 九步流程

1. 加载记忆（profile + active_tasks）
2. 混合检索（`hybrid.search` top_k=15）
3. LLM 重排（`reranker.rerank` top_n=5）
4. 确定风格（style_override → profile.preferred_style → pet.branch → "neutral"）
5. 组装 system prompt（`build_system_prompt`）
6. LLM 生成（`temperature=0.3, max_tokens=1024`，失败降级）
7. 提取引用（`extract_citations`）
8. 更新记忆（`profile_mgr.update_from_query`，静默失败）
9. 宠物获得经验（`pet.gain_exp(10, "qa")`，静默失败）

##### 经验值表

```python
EXP_TABLE = {
    "qa": 10, "ingest": 30, "analyze": 15, "agent": 15,
    "report": 20, "read": 10, "compare": 10, "smart": 8, "graph_build": 30,
}
```

### 6.6 记忆系统

#### 6.6.1 MemoryStore

##### 文件：[core/memory/store.py](core/memory/store.py)

记忆数据的 JSON 持久化层。

```python
DEFAULT_MEMORY = {
    "profile": {...},
    "workflow": {"patterns": [], "suggestions_enabled": True},
    "tasks": [],
    "history": {"recent_queries": []},
}

class MemoryStore:
    def __init__(self, storage_path=None): ...
    def load(self) -> Dict: ...
    def save(self) -> None:
        """原子写入：写 .json.tmp 后 os.replace 覆盖"""
    def update(self, section, key, value): ...
    def get_data(self) -> Dict: ...
    def clear(self) -> None: ...
```

##### 设计要点

- **原子写入**：`temp file + os.replace`，避免崩溃时数据损坏
- **腐败容错**：JSON 解析失败时备份为 `memory.json.bak.{timestamp}` 并回退默认值
- 被 ProfileManager / TaskManager / WorkflowTracker 共同依赖（多模块共享同一份 `memory.json`）

#### 6.6.2 ProfileManager

##### 文件：[core/memory/profile.py](core/memory/profile.py)

管理用户偏好（格式/风格/关注主题/关注地区）。核心特色：**jieba 分词 + 4 级过滤**自动提取主题。

```python
@dataclass
class Profile:
    preferred_format: str
    preferred_style: str
    focus_topics: List[str]
    focus_regions: List[str]
    interaction_count: int
    last_active: str
```

##### 主题提取 4 级过滤

```python
def _extract_topic(query: str) -> str:
    """
    1. 过滤空白词
    2. 过滤停用词（_STOP_WORDS）
    3. 过滤单字词（len(w) >= 2）
    4. 过滤以人称代词开头的词（_PRONOUN_FIRST_CHARS）
    取前 2 个有意义词拼接
    """
```

示例：`"骨灰安置政策"` → `"骨灰安置"`（而非简单 `[:10]` 截断）。

##### 主题去重

包含关系去重：`any(topic in t or t in topic for t in topics)`，上限 10 个。

#### 6.6.3 TaskManager

##### 文件：[core/memory/tasks.py](core/memory/tasks.py)

跨会话任务管理，含上限保护淘汰策略。

```python
@dataclass
class Task:
    id: str               # task_{毫秒时间戳}_{随机4位}
    description: str
    created_at: str
    updated_at: str
    status: str           # pending / in_progress / completed / cancelled
    related_docs: list
    context: str
```

##### 淘汰策略

- `MAX_TASKS = 100`
- 超过上限时按 `retired_rank` 排序：`cancelled: 0, completed: 1, pending: 2, in_progress: 3`
- 优先淘汰 cancelled/completed 中最旧的任务

#### 6.6.4 WorkflowTracker

##### 文件：[core/memory/workflow.py](core/memory/workflow.py)

工作流模式识别：**非重叠 2-gram** 检测常用命令序列。

```python
class WorkflowTracker:
    def record_command(self, cmd: str, timestamp=None) -> None:
        """记录命令 + 非重叠 2-gram 检测"""
    
    def suggest_next(self, current_cmd: str) -> Optional[str]:
        """根据当前命令推荐下一步（count >= 2 才返回）"""
    
    def detect_pattern(self) -> Optional[List[str]]:
        """检测当前是否在常用工作流中"""
```

##### 非重叠 2-gram 算法

- 维护 `pending_pair` 列表，每积累 2 条命令形成一个 pattern
- 形成 pattern 后立即清空 `pending_pair`，避免重叠序列污染统计
- 避免 `(analyze, ingest)` 反向 pattern 污染统计

#### 6.6.5 CrossSessionMemory（跨会话记忆）

##### 文件：[core/memory/cross_session.py](core/memory/cross_session.py)

跨会话持久化用户偏好、关注主题、未解决问题和关键事实，让 AI 在新会话中能"记住"用户的长期信息。

```python
DEFAULT_CROSS_SESSION = {
    "preferences": {},          # dict: 键值对（如 {"格式": "表格", "语言": "中文"}）
    "topics": [],               # list: 关注主题
    "unresolved_questions": [], # list: 未解决问题
    "key_facts": [],            # list: 关键事实
    "last_updated": None,       # ISO 时间戳
}
```

##### `CrossSessionMemory` 类

| 方法 | 说明 |
|---|---|
| `save_preference(key, value)` | 保存单个偏好 |
| `add_topic(topic)` / `remove_topic(topic)` | 添加/移除关注主题（去重） |
| `add_unresolved_question(question)` | 添加未解决问题（去重） |
| `add_key_fact(fact)` | 添加关键事实（去重） |
| `merge_extraction(preferences, topics, questions, facts)` | 批量合并 LLM 提取的记忆，自动去重，返回新增项清单 |
| `get_context() -> str` | 返回格式化上下文文本（四类记忆分段） |
| `clear_all()` | 清空所有记忆 |

##### 设计要点

- **存储路径**：`storage/memory/sessions/<会话名>/cross_session.json`（按会话名隔离存储，REPL 启动时根据会话名创建子目录）
- **线程安全**：`threading.Lock` 保护所有读写
- **原子写入**：写 `.json.tmp` 后 `os.replace` 覆盖，避免崩溃时数据损坏
- **腐败容错**：JSON 解析失败时备份为 `cross_session.json.bak.{timestamp}` 并回退默认值
- **字段校验**：加载时确保 `preferences` 是 dict、其余三个字段是 list，类型错误自动重置

##### `merge_extraction()` 返回值

返回新增项清单，便于上层向用户反馈"记住了什么"：

```python
{
    "preferences": ["键:值", ...],  # 新增/改动的偏好（key 改动也算）
    "topics": [...],                # 新增的主题
    "questions": [...],             # 新增的问题
    "facts": [...],                 # 新增的事实
}
```

#### 6.6.6 MemoryExtractor（自动提取器）

##### 文件：[core/memory/extractor.py](core/memory/extractor.py)

每轮对话结束后，LLM 自动分析对话内容（用户问题 + AI 回答），提取值得跨会话记住的信息，交给 `CrossSessionMemory.merge_extraction()` 合并。

##### `MemoryExtractor` 类

| 方法 | 说明 |
|---|---|
| `extract_and_merge(user_input, assistant_reply)` | 提取一轮对话的记忆并合并，返回新增项清单 |
| `_parse_json(raw)`（静态） | 解析 LLM 输出的 JSON，兼容 markdown 代码块包裹 |

##### 设计要点

- **低温度（0.1）+ 小 max_tokens（300）** 控制成本和稳定性
- **JSON 格式约束**：system prompt 明确要求严格 JSON 输出，定义四类记忆的提取原则（只提取明确或强烈暗示的信息，不猜测）
- **兼容 markdown 代码块**：`_parse_json()` 先尝试提取 ` ```json ... ``` `，再尝试找第一个 `{ ... }` 块
- **类型安全**：对 LLM 返回字段做类型校验（`preferences` 必须是 dict，其余必须是 list），非字符串元素过滤/转换
- **失败静默降级**：LLM 调用失败或 JSON 解析失败均返回空清单，不影响主流程；`max_retries=1` 快速降级
- **触发点**：`chat.py` 的 `_auto_extract_cross_session()`，管理员路径和降级路径都接入
- **用户反馈**：有新增记忆时显示详细反馈

#### 6.6.7 SearchConfig（搜索默认配置）

##### 文件：[core/search/config.py](core/search/config.py)

允许用户设置 `/search` 的默认 tag 和 limit，不用每次输入。

```python
class SearchConfig:
    _default_tag: Optional[str] = None   # 默认标签
    _default_limit: int = 10             # 默认数量
```

##### `SearchConfig` 类

| 方法 | 说明 |
|---|---|
| `get_default_tag() -> Optional[str]` | 获取默认标签 |
| `get_default_limit() -> int` | 获取默认数量 |
| `set_defaults(tag=None, limit=None)` | 设置默认值（`None` 表示不修改对应字段） |
| `reset()` | 重置为默认值（tag=None, limit=10） |

##### 设计要点

- **持久化路径**：`storage/search_config.json`
- **原子写入**：`tempfile.mkstemp` 创建临时文件 + `Path.replace` 重命名，写入失败时清理临时文件
- **腐败容错**：JSON 解析失败时静默使用默认值
- **命令行接口**（在 chat.py 中接入）：
  - `/search config` 显示当前配置
  - `/search config tag <标签>` 设置默认标签
  - `/search config limit <N>` 设置默认数量
  - `/search config reset` 重置
- **自动应用**：搜索时自动应用默认配置（除非用户显式覆盖）

### 6.7 人格系统

#### 6.7.1 System Prompt 构建

##### 文件：[core/persona/prompts.py](core/persona/prompts.py)

```python
def build_system_prompt(style, pet, profile, tasks, sources) -> str:
    """模板填充 + 状态警告拼接"""
```

##### 4 风格模板

| 风格 | 模板常量 | 特点 |
|---|---|---|
| scholar（学者） | `SCHOLAR_SYSTEM` | 先结论后论证，引用密集，表格对比 |
| warrior（战士） | `WARRIOR_SYSTEM` | 开门见山，引用最多 3 个，行动建议 |
| artisan（工匠） | `ARTISAN_SYSTEM` | 结构化分块 ## 小标题，每节至少 1 引用 |
| neutral（通用） | `NEUTRAL_SYSTEM` | 先结论 + 适度引用，语气平和 |

##### 模板字段

- `{pet_name}` / `{level}` — 宠物基本信息
- `{user_profile}` — 用户偏好文本
- `{user_tasks}` — 任务上下文文本
- `{retrieved_context}` — 检索资料文本（每个资料 content 截前 500 字）

##### 宠物状态警告

`_format_pet_state_warnings(pet)` — mood<30 提示玩耍，hunger<30 提示喂食。

#### 6.7.2 风格定义

##### 文件：[core/persona/styles.py](core/persona/styles.py)

```python
STYLE_DESCRIPTIONS = {
    "scholar": {"name": "学者", "emoji": "🦉", "description": "...", "traits": [...]},
    "warrior": {"name": "战士", "emoji": "🐺", "description": "...", "traits": [...]},
    "artisan": {"name": "工匠", "emoji": "🦡", "description": "...", "traits": [...]},
    "neutral": {"name": "通用", "emoji": "🐾", "description": "...", "traits": [...]},
}
```

与 `prompts.py` 的 `_STYLE_TEMPLATES` 形成数据/模板双轨对应。

### 6.8 宠物系统

#### 6.8.1 Pet 实体

##### 文件：[core/pet/pet.py](core/pet/pet.py)

虚拟宠物的核心领域模型。

```python
@dataclass
class Pet:
    name: str
    level: int = 1
    exp: int = 0
    branch: Optional[str] = None  # None / "scholar" / "warrior" / "artisan"
    hunger: int = 80
    mood: int = 80
    energy: int = 100
    cleanliness: int = 80
    exp_multi: float = 1.0
    stats: dict = field(default_factory=dict)  # 行为统计（分系判定）
    inventory: list = field(default_factory=list)
    last_interact: str = ""
    last_decay: str = ""
    created_at: str = ""
    daily_tasks: list = field(default_factory=list)
    daily_reset_at: str = ""
    task_history: list = field(default_factory=list)
    active_effects: list = field(default_factory=list)  # 限时效果
```

##### 关键常量

- `MAX_LEVEL = 10`
- `SCHOLAR_KEYS = {"ingest", "qa", "read", "report"}`
- `WARRIOR_KEYS = {"agent", "compare"}`
- `ARTISAN_KEYS = {"analyze", "smart", "retag"}`
- 衰减率：`HUNGER_DECAY_PER_HOUR=1.5`、`MOOD_DECAY_PER_HOUR=0.5`、`CLEANLINESS_DECAY_PER_HOUR=0.3`
- `MAX_DECAY_CAP = 50`（单次离线衰减封顶）
- `HUNGER_ZERO_EXP_PENALTY = 10`（hunger=0 时每小时扣经验）

##### 关键方法

| 方法 | 说明 |
|---|---|
| `exp_needed()` | 升级所需经验：`floor(100 * level^1.5)` |
| `gain_exp(amount, action_type)` | **核心**：累计 stats → mood<30 惩罚 0.7 倍 → 清理过期效果 → 计算倍率 → 累加 → 连升多级 → Lv5 触发分系 |
| `_determine_branch()` | 按 SCHOLAR/WARRIOR/ARTISAN_KEYS 求和，平局随机选择 |
| `apply_decay()` | 离线衰减（hours 计算，封顶 50；cleanliness<30 时 mood 衰减 ×2；hunger=0 扣经验） |
| `has_auto_revive()` / `consume_auto_revive()` | 凤凰之羽保险机制 |
| `get_active_exp_multi()` | 综合计算经验加成倍率（exp_multi × 所有限时倍率） |

#### 6.8.2 互动

##### 文件：[core/pet/interact.py](core/pet/interact.py)

| 方法 | 效果 | 前置条件 |
|---|---|---|
| `feed(pet)` | +30 hunger, +5 mood, -10 energy, -5 exp | energy >= 10 |
| `play(pet)` | +40 mood, -10 hunger, -15 energy, +10 exp | energy >= 15 |
| `train(pet)` | -25 energy, -10 mood, +50 exp（mood<20 减半） | energy >= 10 且 hunger >= 20 |
| `wash(pet)` | +50 cleanliness, +5 mood, -5 energy | 无 |
| `sleep(pet)` | +50 energy, +10 mood | 距 last_interact > 1 小时 |

`SLEEP_COOLDOWN_SECONDS = 3600`（睡觉冷却 1 小时）。

#### 6.8.3 商店

##### 文件：[core/pet/shop.py](core/pet/shop.py)

8 种道具：

| id | name | price | effect |
|---|---|---|---|
| fish | 小鱼干 | 50 | hunger +30 |
| ball | 玩具球 | 80 | mood +40 |
| soap | 洗浴套装 | 60 | cleanliness +50 |
| energy_drink | 能量饮料 | 100 | energy +50 |
| exp_potion | 经验药水 | 150 | exp_multi ×2.0, 持续 7200 秒 |
| super_food | 顶级饲料 | 150 | hunger +50, mood +20 |
| phoenix_down | 凤凰之羽 | 500 | auto_revive（无过期，触发后消耗） |
| rename_card | 重置卡 | 100 | reset_stats（属性恢复到 80） |

```python
class Shop:
    def list_items(self) -> list: ...
    def buy(self, pet, item_id) -> dict: ...
    def use(self, pet, item_id) -> dict: ...
```

#### 6.8.4 每日任务

##### 文件：[core/pet/tasks.py](core/pet/tasks.py)

- `TASK_POOL`：12 个任务定义，覆盖 10 种行为
- `TASKS_PER_DAY = 3`：每天抽 3 个
- **7 天不重复算法**：排除最近 7 天用过的，不够 3 个则从全池补

```python
class DailyTaskManager:
    def refresh(self, pet, now=None) -> None: ...
    def should_refresh(self, pet, now=None) -> bool: ...
    def check_progress(self, pet, action_type) -> List[dict]: ...
    def list_tasks(self, pet) -> List[dict]: ...
```

#### 6.8.5 ASCII 艺术

##### 文件：[core/pet/art.py](core/pet/art.py)

```python
class ArtLibrary:
    def get(self, branch, level, small=False) -> str:
        """
        加载策略：
        1. 优先加载 {branch_key}_{level}{_small}.txt
        2. small=True 时若不存在，尝试加载大尺寸并截前 6 行
        3. 都没有则返回 _fallback 占位符（block-style 像素风）
        """
```

文件命名约定：`none_1.txt` / `scholar_1.txt` / `warrior_1.txt` / `artisan_1.txt`，共 35 个文件（scholar/warrior/artisan × 10 级 + none × 5 级）。

#### 6.8.6 宠物持久化

##### 文件：[core/pet/storage.py](core/pet/storage.py)

```python
class PetStorage:
    def load(self) -> Optional[Pet]:
        """文件不存在返回 None；损坏备份为 pet.json.bak.{timestamp} 并返回 None"""
    def save(self, pet: Pet) -> None: ...
    def create(self, name: str) -> Pet: ...
```

> ⚠️ `save` 方法未使用原子写入（与 `MemoryStore.save` 不同），存在崩溃时数据损坏风险。

### 6.9 知识图谱

#### 6.9.1 实体关系抽取

##### 文件：[core/graph/extractor.py](core/graph/extractor.py)

```python
@dataclass
class Entity:
    name: str
    type: str        # region / agency / topic
    doc_id: str = ""

@dataclass
class Relation:
    source: str
    target: str
    relation: str    # published_in / published_by / covers_topic
    doc_id: str = ""

@dataclass
class ExtractionResult:
    doc_id: str
    doc_title: str
    entities: List[Entity]
    relations: List[Relation]

class GraphExtractor:
    def extract_from_document(self, doc_id, doc_title, content) -> ExtractionResult:
        """LLM 抽取（temperature=0.1, max_tokens=512），三重 JSON 容错解析"""
```

- 实体类型白名单：`region / agency / topic`
- 关系类型白名单：`published_in / published_by / covers_topic`
- 内容预览截断：`MAX_CONTENT_PREVIEW = 1200`

#### 6.9.2 图谱存储

##### 文件：[core/graph/store.py](core/graph/store.py)

```python
class GraphStore:
    """networkx.Graph（无向图）+ JSON 持久化（storage/graph.json）"""
    
    def add_extraction(self, result: ExtractionResult) -> None:
        """合并相同名称节点，doc_count 累加"""
    def to_cytoscape(self) -> Dict:
        """导出标准 Cytoscape.js 格式"""
    def stats(self) -> Dict: ...
    def neighbors(self, node_name) -> List[Dict]: ...
    def search_nodes(self, keyword) -> List[Dict]: ...
```

##### 节点类型颜色

| 类型 | 颜色 | 含义 |
|---|---|---|
| document | `#FFA500`（橙） | 政策文档 |
| region | `#00CED1`（青） | 地区 |
| agency | `#FF6347`（番茄红） | 机构 |
| topic | `#9370DB`（紫） | 主题 |

#### 6.9.3 HTML 可视化

##### 文件：[core/graph/visualizer.py](core/graph/visualizer.py)

```python
def generate_html(store, output_path=None, title="IMA 知识图谱") -> Path:
    """生成自包含 HTML（vis.js CDN，暗色主题 #1a1a2e）"""
```

- 物理引擎：barnesHut（gravitationalConstant=-8000, springLength=150）
- 节点大小：`min(35, max(10, 10 + degree * 2))`
- 点击节点显示邻居信息面板

### 6.10 同步与质量

#### 6.10.1 增量同步

##### 文件：[core/sync/tracker.py](core/sync/tracker.py)

```python
@dataclass
class SyncResult:
    added: list
    updated: list
    deleted: list
    skipped: list
    errors: list
    
    @property
    def total(self) -> int: ...
    @property
    def has_changes(self) -> bool: ...

class FileTracker:
    """SQLite 表 file_index(file_path PK, doc_id, file_hash, file_mtime, file_size, last_synced)"""
    
    def sync_directory(self, dir_path, storage, on_progress=None) -> SyncResult:
        """
        双重检测：mtime 变了才算 hash，hash 变了才算 modified
        回调：on_progress(action, file_path)，action ∈ added/updated/deleted
        """
```

#### 6.10.2 质量检查

##### 文件：[core/sync/checker.py](core/sync/checker.py)

```python
@dataclass
class QualityReport:
    total_chunks: int
    normal: int
    low_quality: int
    ocr_poor: int
    issues_detail: dict
    
    @property
    def normal_pct(self) -> str: ...
    @property
    def health_score(self) -> int:  # 0-100
```

##### 检查规则

| 规则 | 阈值 | 扣分 |
|---|---|---|
| `empty` | 空内容 | -1.0 |
| `no_text_content` | 无有效文字 | -0.6 |
| `ocr_garbage` | 乱码占比 > 0.3 | -0.5 |
| `too_short` | 长度 < 20 | -0.3 |
| `high_symbol_ratio` | 符号占比 > 0.5 | -0.2 |

#### 6.10.3 SimHash 近似去重

##### 文件：[core/sync/dedup.py](core/sync/dedup.py)

> ⚠️ **实际实现为 SimHash**（非 MinHash+LSH）。

```python
class SimHash:
    @staticmethod
    def compute(text, hash_bits=64) -> int:
        """token → MD5 → 64 位加权向量 → 二值化指纹"""
    
    @staticmethod
    def hamming_distance(hash1, hash2) -> int: ...
    
    @staticmethod
    def similarity(hash1, hash2, hash_bits=64) -> float:
        """1 - distance/bits"""

class DedupScanner:
    def add_chunk(self, chunk_id, doc_id, content) -> None: ...
    def scan(self) -> List[DedupResult]:
        """O(n²) 扫描，单向去重（每个 chunk 只与前面的比较）"""
```

- `_SIMHASH_BITS = 64`
- `_DEFAULT_HAMMING_THRESHOLD = 3`（汉明距离 ≤3 判重复）
- `_DEFAULT_SIMILARITY_THRESHOLD = 0.85`

### 6.11 数据分析

##### 文件：[core/analyze/analyzer.py](core/analyze/analyzer.py)

```python
@dataclass
class AnalysisResult:
    file_info: dict
    preview: list
    describe: dict
    value_counts: dict
    missing: dict
    correlations: dict
    insights: str

class DataAnalyzer:
    def analyze(self, file_path, sheet_name=None) -> AnalysisResult:
        """8 步全量分析"""
    def ask(self, result, question) -> str:
        """追问（先 _try_direct_answer 用 pandas 直接答，失败走 LLM）"""
    def render(self, result) -> None:
        """Rich 终端渲染（Table + 字符图）"""
```

##### 支持格式

`{".xlsx", ".xls", ".csv", ".tsv", ".json"}`，CSV 自动尝试 utf-8/gbk/gb2312/latin-1 编码。

##### 8 步分析流程

1. 读取文件
2. 生成预览（前 5 行）
3. 描述统计（count/mean/std/min/ quartiles/max）
4. 缺失值统计
5. 相关性计算（Top 10）
6. 分类列 Top 值（前 8 列，每列前 10 值）
7. LLM 生成 300 字内洞察（`temperature=0.3`）
8. 返回 `AnalysisResult`

##### 降级优化

`_try_direct_answer` 优先用 pandas 直接答常见问法（如"按月份汇总"），省 LLM 调用。

### 6.12 报告生成

##### 文件：[core/report/generator.py](core/report/generator.py)

```python
class ReportGenerator:
    def generate(self, doc_id, output_path=None) -> Path:
        """
        5 步流程：
        1. 查找文档（支持 ID 前 8 位简写）
        2. 取所有 chunks 拼内容
        3. LLM 生成报告主体（temperature=0.3, max_tokens=2000）
        4. 拼装页眉 + 正文 + 页脚
        5. 写入 storage/reports/{title[:40]}.md
        """
```

报告 6 章节：文档概览 / 关键要点 / 详细解读 / 实施要点 / 关联建议 / 风险提示。

### 6.13 文档阅读

#### 6.13.1 智能阅读器

##### 文件：[core/reader/reader.py](core/reader/reader.py)

```python
@dataclass
class ReadingState:
    doc_id: str
    doc_title: str
    total_chunks: int
    current_index: int = 0

class SmartReader:
    def open(self, doc_id) -> ReadingState: ...
    def next(self) -> Optional[Chunk]: ...
    def prev(self) -> Optional[Chunk]: ...
    def goto(self, index) -> Optional[Chunk]: ...
    def interpret(self) -> str:
        """AI 解读当前段（150 字内）"""
    def ask(self, question) -> str:
        """提问（带前后段上下文，各 500 字）"""
```

#### 6.13.2 文档对比

##### 文件：[core/reader/comparator.py](core/reader/comparator.py)

```python
class Comparator:
    def compare_docs(self, doc_id_a, doc_id_b) -> str: ...
    def compare_files(self, file_a, file_b) -> str: ...
    def compare_doc_and_file(self, doc_id, file_path) -> str: ...
```

统一输出 6 章节 Markdown：概览 / 共同点 / 差异 / 数字对比 / 适用场景 / 建议。

### 6.14 Agent

##### 文件：[core/agent/agent.py](core/agent/agent.py) + [core/agent/tools/](core/agent/tools) + [core/cli/commands/agent.py](core/cli/commands/agent.py)

LLM ReAct 模式工具调用。工具系统已模块化拆分到 `core/agent/tools/`：

- [base.py](core/agent/tools/base.py) — `@register_tool` 装饰器 + `Tool` 基类（name/description/usage/run）
- [builtin.py](core/agent/tools/builtin.py) — 内置工具集实现
- [core/cli/commands/agent.py](core/cli/commands/agent.py) — Agent CLI 命令 + 输出渲染

```python
class Agent:
    def run(self, task, on_step=None, show_thoughts=False) -> str:
        """
        ReAct 循环：Thought → Action → Observation
        达到 MAX_STEPS 强制总结
        on_step(step_type, content) 回调支持进度上报
        show_thoughts: 是否显示思考过程（Hide Thoughts 模式只显示 spinner）
        """
```

##### Agent 输出模式（2026-07-15 更新）

**Show Thoughts 模式**（`/agent think on`）：
- 显示完整的思考过程：`[T] Thinking Xs` → `[OK] tool (N chars)` → 循环
- 每个步骤有图标 + 标题 + 内容缩进

**Hide Thoughts 模式**（`/agent think off`，默认）：
- **只显示单个动态 spinner**：`⠋ Thinking Xs`，X 从任务开始持续增长
- **工具调用和结果完全不打印**
- 使用 `_AgentStatus` + `Live` 组件，`refresh_per_second=8` 确保动画流畅
- **Step 计数器**：在每次 `llm_start` 回调时递增（修复"0 Steps"bug）

```python
class _AgentStatus:
    """动态状态渲染器，实现 __rich_console__ 协议"""
    def __init__(self):
        self._thinking = True
        self._start = time.time()
    
    def __rich_console__(self, console, options):
        if self._thinking:
            elapsed = time.time() - self._start
            desc = f"Thinking {elapsed:.0f}s"
        yield Spinner("dots", text=Text(f" {desc}", style="dim"), style="cyan")
```

**回调逻辑**：
- `llm_start`: 递增 step_n，设置 thinking 状态，启动 Live
- `thought`: 仅 Show Thoughts 模式打印
- `tool`: 仅 Show Thoughts 模式显示工具名 spinner
- `result`: 仅 Show Thoughts 模式打印 `[OK] tool (N chars)`
- `error`: 两种模式都打印（错误需要可见）

##### 6 个内置工具

| 工具 | 说明 |
|---|---|
| `search` | BM25 搜索（top_k=5） |
| `list_docs` | 列所有文档 |
| `get_doc` | 文档详情 + 前 3 段预览 |
| `read` | 读指定段（格式：`doc_id 段号`） |
| `read_multi` | 一次读多段（格式：`doc_id 起-止`，最多 8 段） |
| `analyze` | 数据表分析 |

##### 关键常量

- `MAX_STEPS = 12`
- `MAX_TOKENS = 2000`
- 工具调用格式：`{"tool": "xxx", "args": "yyy"}`（JSON 优先，XML 向后兼容）
- 最终答案：`{"tool": "done", "args": "答案"}`

##### 防重复

`called_tools` set 拦截相同工具+相同参数的重复调用。

### 6.15 图像生成

##### 文件：[core/image/generator.py](core/image/generator.py)

封装 Agnes Image 2.1 Flash API。

```python
class ImageGenerator:
    def text_to_image(self, prompt, enhanced=True, size=None) -> str:
        """文生图，返回 URL"""
    def doc_to_image(self, doc_title, doc_content, style="简洁信息图") -> str:
        """文档配图（先 LLM 增强 prompt）"""
    def daily_card(self, topics, date_str, style="极简卡片") -> str:
        """每日知识卡片（竖版 1024x1792）"""
```

- 复用 LLMClient 的 OpenAI client（相同 base_url + api_key）
- 自动中文 → 英文 prompt 翻译（通过 LLM 增强）
- 3 次重试 + 指数退避
- 单例工厂 `get_image_generator()`

### 6.16 会话管理

##### 文件：[core/session/store.py](core/session/store.py)

```python
class SessionStore:
    def save(self, name, history, meta=None) -> Path: ...
    def load(self, name) -> Optional[List[Dict]]: ...
    def list_sessions(self) -> List[Dict]: ...
    def delete(self, name) -> bool: ...
    def export_markdown(self, name, output_path=None) -> Path:
        """导出 Markdown（含 🧑用户/🤖AI 标记）"""
    def export_json(self, name, output_path=None) -> Path: ...
```

文件名清洗：保留中文/字母/数字/下划线/连字符，`[^\w\u4e00-\u9fa5\-]` → `_`。

### 6.17 标签系统

##### 文件：[core/classify/tagger.py](core/classify/tagger.py)

```python
class Tagger:
    def generate_tags(self, title, file_type, content) -> List[str]:
        """LLM 生成 3-5 个主题标签（temperature=0.2, max_tokens=128）"""
    def generate_tags_for_document(self, parsed: ParsedDocument) -> List[str]: ...

def get_tagger() -> Tagger:
    """单例工厂"""
```

- 内容预览截断：`MAX_CONTENT_PREVIEW = 800`
- 多格式容错解析：JSON 数组 / 逗号分隔 / 空格分隔
- 失败返回空列表不阻塞入库

### 6.18 终端主题

##### 文件：[core/ui/theme.py](core/ui/theme.py)

3 套终端配色主题：

| 主题 | 风格 | 主色 |
|---|---|---|
| `claude`（默认） | Claude Code 风格 | yellow |
| `mimo` | MiMo CODE 风格 | cyan |
| `minimal` | 极简 | white |

```python
@dataclass
class Theme:
    name: str
    label: str
    desc: str
    colors: Dict[str, str]  # primary/secondary/accent/...

def get_theme(name=None) -> Theme: ...
def set_theme(name: str) -> Theme: ...
def list_themes() -> Dict[str, Theme]: ...
```

持久化到 `storage/theme.json`。

---

## 7. Web 后端与前端

### 7.1 API 路由总览

| 路由模块 | 前缀 | 端点 | 说明 |
|---|---|---|---|
| [qa.py](web/routes/qa.py) | `/api/qa` | `GET /stream` | SSE 流式问答 |
| [ingest.py](web/routes/ingest.py) | `/api/ingest` | `POST /upload` `POST /url` | 文档入库 |
| [search.py](web/routes/search.py) | `/api` | `GET /search` | 混合检索 |
| [analyze.py](web/routes/analyze.py) | `/api/analyze` | `POST /` `GET /export` | 数据分析 |
| [stats.py](web/routes/stats.py) | `/api` | `GET /stats` | 仪表盘统计 |
| [graph.py](web/routes/graph.py) | `/api/graph` | `GET /data` `GET /neighbors/{name}` `POST /build` `GET /export` | 知识图谱 |
| [pet.py](web/routes/pet.py) | `/api/pet` | `GET /status` `POST /interact` `POST /style` `POST /adopt` | 宠物管理 |

### 7.2 SSE 流式问答

`GET /api/qa/stream?q=...&persona=auto`

SSE 事件类型：

| 事件 | 数据 | 说明 |
|---|---|---|
| `token` | `{text: "<chunk>"}` | 逐 token 推送 |
| `citation` | `{marker, title, snippet, score}` | 引用来源 |
| `done` | `{full_text: "..."}` | 完整回答 |
| `error` | `{message: "..."}` | 错误信息 |

Response headers：
- `Cache-Control: no-cache`
- `Connection: keep-alive`
- `X-Accel-Buffering: no`（防 nginx 缓冲）

### 7.3 单页应用

#### 文件：[web/templates/index.html](web/templates/index.html)

CSS Grid 布局的单页应用：

```
┌─────────┬──────────────────────────┐
│  Logo   │       Topbar（搜索框）    │
├─────────┼──────────────────────────┤
│         │                          │
│ Sidebar │       Main（7 页面）      │
│ (导航)   │   .page.active 显示       │
│         │                          │
└─────────┴──────────────────────────┘
```

##### 7 个页面

| 页面 ID | 功能 | 特性 |
|---|---|---|
| `page-qa` | AI 问答 | 左右分栏、人格 chips、SSE 流式、引用溯源 |
| `page-ingest` | 文档入库 | 拖拽上传、URL 入库、入库进度、标签显示 |
| `page-search` | 搜索 | 标签筛选、向量/重排开关、高亮、相关度色条 |
| `page-analyze` | 数据分析 | Sheet 切换、统计卡、AI 解读、报告导出 |
| `page-dashboard`（默认） | 仪表盘 | 4 指标卡、标签分布、质量告警、最近入库 |
| `page-graph` | 知识图谱 | vis.js 网络可视化、邻居查询、重建、导出 |
| `page-pet` | 宠物管理 | ASCII 艺术、状态条、4 人格卡片、互动 |

### 7.4 前端交互脚本

#### 文件：[web/static/app.js](web/static/app.js) + [web/static/js/](web/static/js)

前端已从单文件 `app.js` 模块化拆分到 `web/static/js/` 目录，按页面/职责分离：

| 模块 | 职责 |
|---|---|
| [app.js](web/static/app.js) | 入口：初始化 + 页面路由调度 |
| [nav.js](web/static/js/nav.js) | 侧边栏导航 + 页面切换 |
| [qa.js](web/static/js/qa.js) | AI 问答（SSE 流式 + Markdown 渲染 + 引用） |
| [ingest.js](web/static/js/ingest.js) | 文档入库（拖拽上传 + URL 入库） |
| [search.js](web/static/js/search.js) | 混合检索（标签筛选 + 高亮 + 相关度色条） |
| [analyze.js](web/static/js/analyze.js) | 数据分析（Sheet 切换 + 统计 + AI 解读） |
| [dashboard.js](web/static/js/dashboard.js) | 仪表盘（指标卡 + 标签分布 + 告警） |
| [graph.js](web/static/js/graph.js) | 知识图谱（vis.Network 可视化 + 邻居查询） |
| [pet.js](web/static/js/pet.js) | 宠物管理（ASCII 艺术 + 状态条 + 互动） |
| [state.js](web/static/js/state.js) | 全局状态管理 |
| [utils.js](web/static/js/utils.js) | 通用工具函数 |

##### 核心函数（分布在各模块中）

| 函数 | 所在模块 | 说明 |
|---|---|---|
| `sendMessage()` | qa.js | SSE 流式接收 + Markdown 渲染 + 引用编号可点击 |
| `handleFiles(files)` | ingest.js | FormData 上传到 `/api/ingest/upload` |
| `doSearch()` | search.js | 调 `/api/search`，关键词高亮（`<mark>` 包裹） |
| `renderAnalyze(data)` | analyze.js | 渲染 sheet tabs + 字段统计 + 预览表格 + AI 解读 |
| `loadDashboard()` | dashboard.js | 调 `/api/stats` 更新指标 + 标签柱状图 + 告警 |
| `loadGraph()` | graph.js | vis.Network 渲染图谱，节点点击调邻居 API |
| `loadPet()` | pet.js | 宠物状态加载与互动 |

##### 设计模式

- **按需加载**：切换页面时才请求该页数据
- **流式处理**：SSE 用 `reader.read()` 递归调用 `process()`
- **事件委托**：`chat-messages` 和 `sources-panel` 用单个监听器 + `closest()` 处理子元素点击

---

## 8. 测试体系

### 8.1 测试规模

**407+ 测试**，覆盖所有核心模块。

### 8.2 测试目录结构

```
tests/
├── retrieval/          # 混合检索测试
│   ├── test_hybrid.py
│   ├── test_vector.py
│   ├── test_rerank.py
│   └── test_citation.py
├── memory/             # 记忆系统测试
│   ├── test_store.py
│   ├── test_profile.py
│   ├── test_tasks.py
│   └── test_workflow.py
├── pet/                # 宠物系统测试
│   ├── test_pet.py
│   ├── test_administrator.py
│   ├── test_interact.py
│   ├── test_shop.py
│   ├── test_storage.py
│   ├── test_tasks.py
│   ├── test_art.py
│   └── test_integration.py
├── persona/            # 人格测试
│   └── test_prompts.py
├── sync/               # 同步/去重测试
│   ├── test_checker.py
│   ├── test_dedup.py
│   └── test_tracker.py
├── todo/               # 每日任务测试
│   └── test_manager.py
├── llm/                # LLM 测试
│   └── test_degrade.py
├── integration/        # 集成测试
│   └── test_pet_admin_flow.py
├── test_administrator_stream.py
├── test_cli_agent.py
├── test_cli_memory.py
├── test_cross_session_memory.py
├── test_graph_store.py
├── test_parser_ocr.py
├── test_repl_aliases.py
├── test_search_config.py
├── test_search_config_integration.py
├── test_session_auto_save.py
├── test_storage_edit.py
├── test_storage_vector_sync.py
├── test_subcommand_menu.py
── test_batch3_fixes.py
```

### 8.3 运行测试

```bash
cd ima-kb
source .venv/bin/activate
pytest tests/ -v
```

---

## 9. 依赖关系总览

### 9.1 模块依赖图

```
config.settings (全局配置单例)
       │
       ├── core/llm/client.py (LLMClient 单例)
       │        ↑
       │        被 tagger / extractor / analyzer / generator /
       │        reader / comparator / agent / image / rerank 引用
       │
       ├── core/storage.py (Storage)
       │        ↑
       │        被 qa.chain / pet.administrator / web.routes.* /
       │        sync.tracker / report.generator / reader.* / agent 引用
       │
       ├── core/search/bm25.py (BM25Index)
       │        ↑
       │        被 storage.py / retrieval/hybrid.py 引用
       │
       ├── core/retrieval/
       │   ├── vector.py (VectorIndex)
       │   │        ↑
       │   │        被 hybrid.py / storage.py(attach) 引用
       │   ├── hybrid.py (HybridRetriever: BM25+Vector+RRF)
       │   │        ↑
       │   │        被 qa.chain / pet.administrator / web.routes.qa/search 引用
       │   ├── rerank.py (Reranker: LLM 打分)
       │   │        ↑
       │   │        被 qa.chain / pet.administrator / web.routes.qa/search 引用
       │   └── citation.py (extract_citations)
       │            ↑
   qa.chain / pet.administrator / web.routes.qa 引用
       │
       ├── core/ingestion/parser.py (parse)
       │        ↑
       │        被 run.py / repl.py / sync.tracker / classify.tagger /
       │        graph.extractor / reader.comparator / web.routes.ingest 引用
       │
       ├── core/pet/administrator.py (PetAdministrator 编排层)
       │        ↑
       │        被 repl.py / run.py(ask) / web.routes.qa 引用
       │
       ├── core/memory/store.py (MemoryStore)
       │        ↑
       │        被 profile.py / tasks.py / workflow.py 共同依赖
       │
       └── web/app.py (create_app 工厂)
                ↑
                被 repl.py(_cmd_web) / run.py(cli_web) 引用
```

### 9.2 核心调用链

#### 入库链

```
run.py:_ingest_one / repl.py:_ingest_one / web/routes/ingest.py:_ingest_file
  → parser.parse(file_path)              # 解析
  → chunker.chunk_document(parsed)       # 分块
  → SHA256 去重检查
  → Tagger.generate_tags_for_document    # 自动标签（可选）
  → Storage.save_document()              # 保存
       → SQLite 写入
       → BM25Index.add() + save()
       → VectorIndex.add_chunks_batch()  # 如果已注入
```

#### 问答链（REPL）

```
repl.py:_handle_chat
  → PetAdministrator.ask(query)          # 优先路径
       → ProfileManager.get_profile()
       → TaskManager.get_active_tasks()
       → HybridRetriever.search(query, top_k=15)
            → BM25Index.search()
            → VectorIndex.search()       # 不可用降级
            → _rrf_fusion()
       → Reranker.rerank(query, candidates, top_n=5)
       → build_system_prompt(style, pet, profile, tasks, sources)
       → LLMClient.chat(messages, temperature=0.3)
       → extract_citations(answer, sources)
       → ProfileManager.update_from_query()
       → Pet.gain_exp(10, "qa")
  → _render_answer(AnswerResult)
  
  # 降级路径
  → RAGChain.ask(question, history)      # PetAdministrator 失败
  → 纯 LLM 对话（流式）                    # RAGChain 失败
```

#### Web SSE 问答链

```
web/routes/qa.py: GET /api/qa/stream
  → HybridRetriever.search()
  → Reranker.rerank()
  → build_system_prompt()
  → LLMClient.chat_stream()              # async generator
  → SSE 事件流：
       event: token     data: {text}
       event: citation  data: {marker, title, snippet}
       event: done      data: {full_text}
```

### 9.3 三套入口的共享与差异

| 能力 | CLI (run.py) | REPL (core/cli) | Web (web/) |
|---|---|---|---|
| 入库 | ✅ `ingest` `note` `clip` `url` | ✅ `/ingest` `/note` `/clip` `/url` | ✅ `/api/ingest/upload` `/api/ingest/url` |
| 搜索 | ✅ `search` | ✅ `/search` | ✅ `/api/search` |
| 问答 | ✅ `ask`（PetAdministrator） | ✅ 直接输入（三层降级） | ✅ `/api/qa/stream`（SSE） |
| 标签 | ✅ `retag` | ✅ `/retag` `/tag` `/tags` | ❌ |
| 统计 | ✅ `stats` | ✅ `/stats` | ✅ `/api/stats` |
| 图谱 | ✅ `graph build/stats/neighbors/export/clear` | ✅ `/graph` 子命令 | ✅ `/api/graph/*` |
| 数据分析 | ✅ `analyze` | ✅ `/analyze`（含追问） | ✅ `/api/analyze` |
| 报告 | ✅ `report` | ✅ `/report` | ❌ |
| 阅读 | ❌ | ✅ `/read` | ❌ |
| 对比 | ❌ | ✅ `/compare` | ❌ |
| Agent | ❌ | ✅ `/agent` | ❌ |
| 图像生成 | ❌ | ✅ `/pic` `/draw` `/daily` | ❌ |
| 同步 | ✅ `sync` | ✅ `/sync` | ❌ |
| 质量 | ✅ `health` | ✅ `/health` | ✅（仪表盘告警） |
| 去重 | ✅ `dedup` | ✅ `/dedup` | ❌ |
| 记忆 | ✅ `memory` | ✅ `/memory` | ❌ |
| 宠物 | ❌ | ✅ `/pet` 全套 | ✅ `/api/pet/*` |
| 会话 | ❌ | ✅ `/session save/load/list` | ❌ |
| 主题 | ❌ | ✅ `/theme` | ❌ |
| 监控 | ✅ `watch` | ❌ | ❌ |
| Web 后台 | ✅ `web` | ✅ `/web` `/web stop` | — |

---

## 10. 项目运行方式

### 10.1 安装

#### 方式 1：一键安装脚本（推荐）

```bash
cd ima-kb
bash install.sh              # 基础安装
bash install.sh --ocr        # 含 OCR 支持
bash install.sh --vector     # 含向量检索支持
bash install.sh --dev        # 含开发依赖
bash install.sh --no-venv    # 用系统 Python（不推荐）
```

`install.sh` 6 步流程：Python 检查 → venv → pip install + `pip install -e .` → .env 配置 → zsh/bash ima 命令 → 验证。

#### 方式 2：手动安装

```bash
cd ima-kb
python3 -m venv .venv
source .venv/bin/activate
pip install -e .              # 注册 ima 命令

# 可选：OCR 支持（推荐 PaddleOCR，精度更高）
pip install paddlepaddle paddleocr
# 降级方案：Tesseract
brew install tesseract tesseract-lang
pip install pytesseract

# 可选：向量检索支持
pip install chromadb sentence-transformers
# 下载向量模型（中国大陆需用 hf-mirror.com）
curl -L https://hf-mirror.com/BAAI/bge-small-zh-v1.5/resolve/main/model.safetensors \
  -o storage/models/bge-small-zh-v1.5/model.safetensors
```

#### 配置 .env

```bash
cp .env.example .env
# 编辑 .env，填入 AGNES_API_KEY
```

```env
AGNES_API_KEY=your_api_key_here
AGNES_BASE_URL=https://apihub.agnes-ai.com/v1
LLM_MODEL=agnes-2.0-flash
IMAGE_MODEL=agnes-image-2.1-flash
```

### 10.2 运行

#### 终端（推荐）

```bash
ima                          # 进入 REPL（Claude Code 风格界面）
ima search "骨灰"            # BM25 搜索
ima search "骨灰" --tag 殡葬改革  # 按标签筛选
ima ask "退役军人抚恤金？"    # 单次 RAG 问答
ima stats                    # 知识库统计
ima ingest ~/Documents/政策文件/  # 入库目录
ima graph build --force      # 构建知识图谱
ima graph stats              # 图谱统计
ima graph neighbors "杭州市"  # 查询节点关系
ima graph export             # 导出 HTML 可视化
ima web                      # 启动 Web 后台
ima web --host 0.0.0.0       # 内网访问
```

#### REPL 内部

```
> /help                       # 查看帮助
> /stats                      # 知识库统计
> /tags                       # 查看所有标签
> /search 骨灰                 # BM25 搜索
> /ingest ~/Documents/政策文件/  # 入库
> 退役军人抚恤金有什么新规定？   # AI 问答（流式）
> /analyze data.xlsx          # 数据分析
> /report 24ea6ac3            # 生成报告
> /read 24ea6ac3              # 智能阅读
> /compare doc1 doc2          # 文档对比
> /agent 分析所有关于骨灰安置的政策  # Agent 模式
> /pic 一只在竹林中散步的猫      # 文生图
> /draw 862e0973 --style 水墨  # 文档配图
> /pet                        # 宠物管理
> /memory                     # 记忆管理
> /web                        # 启动 Web 后台
> /web stop                   # 停止 Web 后台
> /session save my_session    # 保存会话
> /clear                      # 清空对话
> /exit                       # 退出
```

#### Web 后台

```bash
ima web                       # 默认 http://127.0.0.1:8501
ima web --host 0.0.0.0        # 内网访问
ima web -p 8080               # 指定端口
```

7 个页面：AI 问答 / 文档入库 / 搜索 / 数据分析 / 仪表盘 / 知识图谱 / 宠物管理。

### 10.3 验证清单

```bash
cd ima-kb
source .venv/bin/activate

# 1. 确认 ima 命令可用
ima --help

# 2. 知识库统计
ima stats

# 3. 知识图谱统计
ima graph stats

# 4. BM25 搜索（带标签筛选）
ima search "骨灰" --tag 殡葬改革

# 5. RAG 问答
ima ask "退役军人抚恤金有什么新规定？"

# 6. 进 REPL
ima
> /help
> /stats
> /tags
> 退役军人抚恤金有什么新规定？
> /exit

# 7. 导出图谱 HTML
ima graph export
open storage/graph.html

# 8. 启动 Web 后台
ima web
# 浏览器打开 http://127.0.0.1:8501，检查 7 个页面
```

---

## 11. 设计决策与亮点

### 11.1 关键设计决策

| # | 决策 | 理由 |
|---|---|---|
| 1 | **BM25 + 向量混合检索 + 语义缓存 + 查询路由** | BM25 关键词匹配 + 向量语义检索 + RRF 融合 + LLM 重排，四层流水线互补；并发检索降低延迟；语义缓存命中相似问题；查询路由让闲聊跳过检索；向量库不可用时自动降级为纯 BM25 |
| 2 | **Agnes AI（OpenAI 兼容协议）** | 用户已有 API Key；接口兼容，后续切换其他 LLM 只改 `config.py` |
| 3 | **`ima` 命令通过 pip install -e . 注册** | 比 zsh function 更标准，自动同步更新 |
| 4 | **prompt_toolkit + radiolist_dialog** | rich Prompt 不支持弹窗式补全菜单；prompt_toolkit 是终端补全标准方案 |
| 5 | **networkx + vis.js 而非 pyvis** | networkx 提供图算法支持，vis.js 直接 CDN 嵌入无依赖 |
| 6 | **图谱抽取用 temperature=0.1** | 实体关系抽取要求确定性输出，低温保证 LLM 输出稳定可解析的 JSON |
| 7 | **宠物管理员是统一入口** | 所有 AI 交互走 PetAdministrator，串联检索→重排→prompt→LLM→引用→记忆→经验，失败时降级到 RAGChain |
| 8 | **主题提取用 jieba 分词** | 比简单 `[:10]` 截断更智能，"骨灰安置政策"→"骨灰安置"；4 级过滤保证质量 |
| 9 | **SimHash 而非 MinHash+LSH** | 64 位指纹 + 汉明距离，O(n²) 扫描对中小规模知识库足够 |
| 10 | **JSON 原子写入** | MemoryStore 用 `temp file + os.replace`，避免崩溃时数据损坏 |
| 11 | **不把入库文件保存成 .md 替代 SQLite**（2026-07-12 评估） | 完全替代会破坏 chunks 分块存储、BM25 索引（chunk_id 映射）、ChromaDB 向量索引；元数据查询和去重检查都会变慢；并发写入有冲突风险。保留 SQLite 为主存储，如需人类可读可采用折中方案（额外导出 .md 副本到 `storage/markdown/`） |

### 11.2 架构亮点

#### 1. 多层降级机制

任何单点故障都不会让整体崩溃：

- **VectorIndex 不可用** → 纯 BM25
- **Reranker 失败** → 用原混合结果
- **LLM 失败** → 降级检索模式提示（`get_llm_degrade_message`）
- **PetAdministrator 失败** → RAGChain
- **RAGChain 失败** → 纯 LLM 对话
- **向量索引同步失败** → 不阻塞入库（BM25 仍可用）

#### 2. 依赖注入与单例并存

- `RAGChain` / `PetAdministrator` 接受外部注入的 retriever/reranker/storage，便于测试
- `get_llm()` / `get_tagger()` / `get_image_generator()` 提供全局单例，避免重复创建

#### 3. 置信度门控

RRF 分数低于阈值时：
- 在 Prompt 中注入警告："⚠️ 检索结果相关度较低，请谨慎回答"
- 标记 `low_confidence=True`，主动告知用户"资料不足"而非强行回答

#### 4. 健壮的 LLM 输出解析

`Reranker._parse_scores` 三级 fallback：
1. 直接 `json.loads`
2. 正则提取 `[...]` 片段
3. 正则提取 `{...}` 片段，清理 markdown code block 标记

应对 LLM 返回 markdown 包裹或额外文字的情况。

#### 5. 中国大陆友好

- `vector.py` 在 import 前设置 `HF_ENDPOINT=https://hf-mirror.com`
- 本地模型路径 `storage/models/bge-small-zh-v1.5/`（用 curl 从 hf-mirror.com 下载）
- GitHub push 改用 SSH（HTTPS 在国内会超时）

#### 6. 跨模块一致性

- **腐败容错**：MemoryStore / PetStorage / GraphStore 都用 `.bak.{timestamp}` 备份策略
- **容量上限 + 淘汰策略**：topics(10) / tasks(100) / patterns(50) / task_history(14天) / recent_commands(10)
- **TYPE_CHECKING 防循环依赖**：interact/shop/tasks 均用 `if TYPE_CHECKING: from core.pet.pet import Pet`

#### 7. 检索性能三层优化

- **查询路由**：闲聊/问候直接走 LLM，避免无意义检索（1.5-5s → ~200ms）
- **语义缓存**：L1 精确 + L2 embedding 相似度，命中率 40-60%，重复/相似问题 <10ms
- **并发检索**：BM25 与向量检索并行，粗排 top 50 再精排，降低整体延迟 30-50%

#### 8. 输出可读性防御

- **Prompt 层**：system prompt 禁止 LaTeX、重复引用列表、非标准符号
- **渲染层**：流式输出时实时清理 `$$`、`times`、`mathbf{}` 等 LaTeX 语法
- **缓存层**：缓存写入/命中前都执行清理，保证旧缓存也不会污染显示

#### 9. 风格分系三重映射

| 分系 | styles.py emoji | prompts.py 模板 | pet.py 行为键 |
|---|---|---|---|
| scholar | 🦉 学者 | SCHOLAR_SYSTEM | ingest/qa/read/report |
| warrior | 🐺 战士 | WARRIOR_SYSTEM | agent/compare |
| artisan | 🦡 工匠 | ARTISAN_SYSTEM | analyze/smart/retag |
| neutral | 🐾 通用 | NEUTRAL_SYSTEM | - |

三个文件通过 style 字符串保持一致联动，构成完整的分系生态。

### 11.3 已知问题与注意事项

1. **jieba 启动提示**：每次启动会输出 `Building prefix dict...`，正常现象
2. **流式 chunk 空 choices**：Agnes 偶尔发空 chunk，已在 `client.py` 修复
3. **.env 不要提交**：包含真实 API Key，`.gitignore` 已忽略
4. **storage/ 不要提交**：用户私有数据，`.gitignore` 已忽略
5. **Python 版本**：兼容 3.9+，但 3.10+ 体验更好
6. **`def list()` 命名陷阱**：曾用 `list()` 作函数名覆盖内置 `list()`，已改名为 `list_docs`
7. **pyproject.toml py-modules**：必须显式声明 `py-modules = ["run", "repl", "config"]`，否则 `pip install -e .` 后 `ima` 找不到 `run` 模块
8. **版本号已统一**：`pyproject.toml` 版本为 `4.1.0`，与代码 v4.1 一致（已修复）
9. **PetStorage.save 非原子写入**：与 `MemoryStore.save` 不同，存在崩溃时数据损坏风险
10. **向量模型大文件**：`model.safetensors` 需用 curl 从 hf-mirror.com 手动下载，HF 镜像 CDN 重定向会超时

### 11.4 后续优化方向

| # | 优化项 | 难度 | 说明 |
|---|---|---|---|
| 1 | **图谱扩展** | ★★★ | 新增人物/时间/金额等实体类型 |
| 2 | **多用户隔离** | ★★★★★ | 全栈改造，所有 storage 加 user_id，认证体系从零写 |
| ✅ | ~~**Embedding 缓存层**~~ | — | ✅ **2026-07-15 完成**：`vector.py` 已加 SQLite 缓存（chunk hash → embedding） |
| ✅ | ~~**语义缓存 + 查询路由 + 并发检索**~~ | — | ✅ **2026-07-15 完成**：`semantic_cache.py` + `router.py` + `hybrid.py` 并发改造 |
| ✅ | ~~**LaTeX 输出清理**~~ | — | ✅ **2026-07-15 完成**：`chat.py` + `administrator.py` 渲染层/缓存层双重清理 |
| ✅ | ~~**PDF 重新解析**~~ | — | ✅ **2026-07-12 完成**：8 个 PDF 全部用 PaddleOCR 重新入库 |
| ✅ | ~~**OCR 优化：PaddleOCR**~~ | — | ✅ **2026-07-12 完成**：PaddleOCR 主引擎（原图直传）+ Tesseract 降级（外部预处理），见 [parser.py](file:///core/ingestion/parser.py) |

---

**项目状态**：P1-P7 全部完成（含 Web 前端 7 页面）+ P0-P5 工业级 RAG 流水线（Cross-Encoder/HyDE/Parent-Document/Lost-in-Middle/LRU 持久化缓存/引用验证），IMA v4.1 已部署到 GitHub（仓库 `xiaozhuangma748-hash/ima-kb`），564 测试通过，可用于日常使用。

---

*本文档由代码分析自动生成，最后更新：2026-07-15*
