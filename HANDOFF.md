# IMA 个人知识库 · 项目交接文档

> 本文档供下一次会话快速理解项目状态，便于继续开发。
> 最后更新：2026-07-07（P5 全部完成 + 宠物管理员 v4.0 + 混合检索 + 增量同步 + 子命令菜单）

---

## 📌 项目背景

**用户目标**：把电脑里散落的资料（PDF / Word / Excel / PPT / Markdown / 网页 / 代码）整理成一个可搜索、可问答的个人知识库。

**用户偏好**（来自 user_profile.md）：
- 中文交流，Python 熟练
- 不喜欢横向滚动流程图，偏好纵向布局
- 数据展示偏好随机月分布而非均匀
- 区分"照料中心"和"食堂"数据（非本项目相关）

---

## 🎯 项目当前状态

### 已完成阶段

| 阶段 | 内容 | 状态 |
|---|---|---|
| **P1 骨架** | 项目结构 + 多格式解析 + SQLite 存储 + CLI 入库 | ✅ 完成 |
| **P2 智能** | BM25 中文检索 + Agnes LLM 接入 + RAG 问答（流式/非流式） | ✅ 完成 |
| **P3 体系** | Streamlit Web 界面 + 终端交互式 REPL + `ima` 全局命令 | ✅ 完成 |
| **P4 增强** | OCR 补齐 + 自动标签 + 分发安装脚本 + Claude Code 风格 CLI + 知识图谱 | ✅ 完成 |
| **P5 智能化** | 宠物管理员 v4.0 + 混合检索（BM25+向量+RRF+重排）+ 记忆系统 + 人格风格 + 增量同步 + 质量检查 + 近似去重 + 子命令菜单 + 数据分析 + 报告生成 | ✅ 完成 |

### 实测可用功能

- ✅ 多格式入库（PDF/Word/Excel/PPT/MD/TXT/HTML/代码/**图片/扫描 PDF/.doc**，共 11 种）
- ✅ 内容去重（SHA256 hash）
- ✅ BM25 中文分词搜索（jieba）
- ✅ RAG 问答带引用编号
- ✅ 流式输出（已修复 Agnes 空 choices chunk 问题）
- ✅ 多轮对话（REPL 保留 5 轮历史，Web session_state 保留全部）
- ✅ Streamlit Web 界面（**5 个页面**：仪表盘/搜索/问答/知识图谱/入库）
- ✅ `ima` 全局终端命令（pip install -e . 注册）
- ✅ **OCR 补齐**（Tesseract + pytesseract，4 扫描 PDF + 4 PNG 入库）
- ✅ **自动标签**（LLM 生成，27 文档共 67 个标签，可按标签筛选）
- ✅ **REPL 命令自动补全**（prompt_toolkit，输入 `/` 弹出命令列表）
- ✅ **Claude Code 风格 CLI**（ASCII Logo + 分栏面板 + 橙色提示符 + 流式 `⏺` 标记）
- ✅ **知识图谱**（LLM 抽取实体关系，networkx 存储，vis.js 可视化）
- ✅ **一键安装**（`install.sh` + `pyproject.toml`，支持 `--ocr` / `--dev` / `--no-venv` / `--vector`）
- ✅ **宠物管理员 v4.0**（统一 AI 交互入口，4 种人格风格 scholar/warrior/artisan/neutral，像素风 ASCII 艺术）
- ✅ **混合检索**（BM25 + 向量 bge-small-zh-v1.5 + RRF 融合 k=60 + LLM 重排序，四层流水线）
- ✅ **记忆系统**（用户偏好 + 跨会话任务 + jieba 主题提取 + 非重叠 2-gram 工作流识别）
- ✅ **增量同步**（`ima sync`，文件 mtime/hash 追踪，仅处理变更）
- ✅ **质量检查**（`ima health`，检测空文档/超长块/低质量内容）
- ✅ **近似去重**（`ima dedup`，MinHash + LSH，相似度阈值可调）
- ✅ **数据分析**（`/analyze` 命令，Excel 多 sheet 自动统计 + 字符图 + AI 解读）
- ✅ **报告生成**（`/report` 命令，Markdown 报告自动生成）
- ✅ **子命令菜单**（8 个主命令 `/memory /pet /graph /sync /session /tag /dedup /health` 用 `radiolist_dialog` 弹出选择菜单）
- ✅ **快速入库**（`/note`/`/clip`/`/url` 命令，支持剪贴板/URL/截图 OCR）
- ✅ **会话管理**（`/session save/load/list`，跨会话恢复对话历史）

---

## 🏗️ 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.9+（兼容 macOS 自带 3.9.6） |
| CLI 框架 | click + rich + prompt_toolkit（补全 + `radiolist_dialog` 子命令菜单） |
| Web 框架 | Streamlit |
| 元数据库 | SQLite（单文件 metadata.db） |
| 文档解析 | PyMuPDF / python-docx / openpyxl / python-pptx / trafilatura / **Pillow + pytesseract（OCR）** / **macOS textutil（.doc）** |
| 中文检索 | jieba + 自实现 BM25 |
| **向量检索**（P5） | **ChromaDB + sentence-transformers（bge-small-zh-v1.5）+ RRF 融合 + LLM 重排序** |
| LLM | Agnes AI（OpenAI 兼容协议，模型 `agnes-2.0-flash`） |
| 知识图谱 | networkx + vis.js（HTML 可视化） |
| **记忆系统**（P5） | **MemoryStore（JSON 原子写入）+ TaskManager + ProfileManager（jieba 主题）+ WorkflowTracker（2-gram）** |
| **人格系统**（P5） | **4 风格 scholar/warrior/artisan/neutral + 像素风 ASCII 艺术** |
| API Key | 配置在 `.env` 中（`AGNES_API_KEY`） |

**注意**：P5 已补齐 ChromaDB 向量检索，与 BM25 混合（RRF 融合 + LLM 重排）。向量库不可用时自动降级为纯 BM25，功能正常但语义理解较弱。

---

## 📂 项目结构

```
ima-kb/
├── HANDOFF.md                    # ← 本文档
├── INSTALL.md                    # 同事安装指南
├── requirements.txt              # 含 Pillow + pytesseract + chromadb + sentence-transformers
├── pyproject.toml                # 打包配置，定义 ima = "run:cli" 入口点
├── install.sh                    # 一键安装脚本（--ocr / --dev / --no-venv / --vector）
├── .env                          # ✅ 已配置 AGNES_API_KEY（不要提交 git）
├── .env.example                  # 模板（Agnes 配置）
├── .gitignore
├── config.py                     # 配置中心（Settings 单例）
├── run.py                        # CLI 入口（21 个命令，无子命令时进入 REPL）
├── repl.py                       # 交互式 REPL（IMA v4.0 · Claude Code 风格 + 30+ 子命令）
│
├── core/
│   ├── ingestion/
│   │   ├── parser.py             # 多格式解析（11 种）+ OCR 降级 + .doc textutil
│   │   ├── chunker.py            # 智能分块（按段落+重叠+句子边界）
│   │   └── quick.py              # 快速入库（/note /clip /url）
│   ├── llm/
│   │   ├── client.py             # Agnes LLM 客户端（chat / chat_stream）
│   │   └── degrade.py            # 统一降级提示
│   ├── search/
│   │   └── bm25.py               # BM25 索引 + 检索
│   ├── retrieval/                # P5 新增：混合检索
│   │   ├── vector.py             # ChromaDB + bge-small-zh-v1.5 向量索引
│   │   ├── hybrid.py             # BM25 + 向量 + RRF 融合（k=60）
│   │   ├── rerank.py             # LLM 重排序
│   │   └── citation.py           # 引用编号提取
│   ├── qa/
│   │   └── chain.py              # RAG 问答链（降级到 PetAdministrator 时用）
│   ├── classify/
│   │   └── tagger.py             # LLM 自动标签生成
│   ├── graph/
│   │   ├── extractor.py          # LLM 抽取实体关系（region/agency/topic + 3 种关系）
│   │   ├── store.py              # networkx 图谱存储 + JSON 持久化 + cytoscape 导出
│   │   └── visualizer.py         # 自包含 HTML 可视化（vis.js CDN，暗色主题）
│   ├── memory/                   # P5 新增：记忆系统
│   │   ├── store.py              # MemoryStore（JSON 原子写入）
│   │   ├── tasks.py              # TaskManager（跨会话任务）
│   │   ├── profile.py            # ProfileManager（jieba 主题提取 + 4 级过滤）
│   │   └── workflow.py           # WorkflowTracker（非重叠 2-gram）
│   ├── persona/                  # P5 新增：人格系统
│   │   ├── prompts.py            # build_system_prompt（4 风格分系 prompt）
│   │   └── styles.py             # 风格定义
│   ├── pet/                      # P5 新增：宠物管理员
│   │   ├── administrator.py      # 编排层（检索→重排→prompt→LLM→引用→记忆→经验）
│   │   ├── pet.py                # 宠物实体（等级/经验/状态）
│   │   ├── interact.py           # 喂食/玩耍/训练
│   │   ├── shop.py               # 商店
│   │   ├── tasks.py              # 宠物任务
│   │   ├── art.py                # 像素风 ASCII 艺术加载
│   │   ├── arts/                 # 20 个 ASCII 艺术文件（4 风格 × 5 等级）
│   │   └── storage.py            # 宠物持久化
│   ├── session/                  # P5 新增：会话管理
│   │   └── store.py              # 跨会话历史保存/恢复
│   ├── sync/                     # P5 新增：同步与质量
│   │   ├── tracker.py            # 增量同步（mtime/hash 追踪）
│   │   ├── checker.py            # 质量检查（空文档/超长块）
│   │   └── dedup.py              # 近似去重（MinHash + LSH）
│   ├── analyze/                  # P5 新增：数据分析
│   │   └── analyzer.py           # Excel 多 sheet 统计 + 字符图
│   ├── report/                   # P5 新增：报告生成
│   │   └── generator.py          # Markdown 报告
│   ├── reader/                   # P5 新增：文档阅读
│   │   ├── reader.py             # 文档阅读器
│   │   └── comparator.py         # 文档对比
│   ├── agent/                    # P5 新增：Agent 工具调用
│   │   └── agent.py              # LLM Agent（12 步工具调用）
│   ├── ui/
│   │   └── theme.py              # 终端主题
│   └── storage.py                # SQLite 存储（documents/chunks 表 + tags + 向量同步）
│
├── web/
│   ├── app.py                    # Streamlit 主入口（5 个页面）
│   ├── pixel_theme.py            # 像素风主题
│   └── pages/
│       ├── dashboard.py          # 仪表盘
│       ├── search_page.py        # 搜索页
│       ├── qa_page.py            # AI 问答页（流式）
│       ├── graph_page.py         # 知识图谱页
│       └── ingest_page.py        # 入库管理页
│
├── tests/                        # 153+ 测试
│   ├── retrieval/                # 混合检索测试
│   ├── memory/                   # 记忆系统测试
│   ├── pet/                      # 宠物系统测试
│   ├── persona/                  # 人格测试
│   ├── sync/                     # 同步/去重测试
│   └── ...
│
├── test_data/                    # 5 个测试文件
│
└── storage/                      # 本地数据（gitignore）
    ├── metadata.db               # SQLite 元数据
    ├── bm25_index.pkl            # BM25 持久化索引
    ├── graph.json                # 知识图谱持久化
    ├── graph.html                # 知识图谱 HTML 可视化
    ├── memory.json               # 记忆系统持久化
    ├── pet.json                  # 宠物状态持久化
    ├── sessions/                 # 会话历史
    ├── uploads/                  # 原文件副本
    ├── uploads/quick/            # 快速入库内容
    ├── cache/                    # 解析缓存
    ├── chroma/                   # ChromaDB 向量库
    └── models/bge-small-zh-v1.5/ # 本地向量模型
```

---

## 🔑 关键文件速查

### `config.py` — 配置中心
- `Settings` 类：agnes_api_key / agnes_base_url / llm_model / storage_path / chunk_size(512) / chunk_overlap(64) / rag_top_k(6) / llm_max_tokens(1024)
- `settings.has_llm()`：判断 API Key 是否有效配置
- 全局单例 `settings`

### `run.py` — CLI 入口
- `cli` group（**注意**：之前的 bug 是 chat/web 命令放在 cli 定义之前导致 NameError，已修复，新增命令要放在 `cli` 之后）
- **顶层命令**：`chat` `web` `ingest` `list` `search`（带 `--tag` 筛选） `ask` `show` `stats` `retag`（重打标签） `delete` `rebuild`
- **`graph` 子命令组**（5 个）：
  - `ima graph build [--force] [-d ID] [-n N]`：调 LLM 抽取实体关系构建图谱
  - `ima graph stats [-t TYPE]`：图谱统计 + 节点列表
  - `ima graph neighbors <名称>`：查询节点邻居
  - `ima graph export [-o PATH]`：导出 HTML 可视化
  - `ima graph clear`：清空图谱

### `repl.py` — IMA REPL（v4.0 · Claude Code 风格）
- **欢迎面板**：ASCII Logo（IMA 字符艺术）+ 左右分栏（青色 Welcome / 黄色 Tips）
- **命令补全**：prompt_toolkit WordCompleter，输入 `/` 弹出 13 个命令列表 + 描述
- **橙色 `>` 提示符**（Claude Code 风格）
- **AI 对话**：橙色 `⏺` 圆点标记 + 首 token 显示 Spinner + 流式输出
- 命令：`/help /search /ingest /list /show /tags /tag /delete /stats /rebuild /clear /exit /quit`
- 多轮对话：保留最近 10 条 history（5 轮）

### `core/ingestion/parser.py` — 多格式解析
- **支持 11 种格式**：PDF/Word(.docx/.doc)/Excel/PPT/MD/TXT/HTML/代码/.png/.jpg/.tif/.bmp/.webp
- **OCR 降级**：检测 PDF 无文本层（<50 字符）自动走 Tesseract
- **`.doc` 解析**：调用 macOS `textutil` 转 txt
- **OCR 不可用时**：返回 `meta={"ocr_unavailable": "true"}`，上游友好提示

### `core/classify/tagger.py` — 自动标签
- LLM 生成 3-5 个主题标签
- 入库时自动调用（`run.py` 和 `repl.py` 的 `_ingest_one`）
- 可用 `ima retag` 批量补全/重生成

### `core/graph/extractor.py` — 知识图谱抽取
- `GraphExtractor.extract_from_document(doc_id, doc_title, content)` → `ExtractionResult`
- **实体类型**：region（地区）/ agency（机构）/ topic（主题）
- **关系类型**：published_in（发布于）/ published_by（发布机构）/ covers_topic（涉及主题）
- LLM 提示词：temperature=0.1，max_tokens=512，要求严格 JSON 输出
- 实测：27 文档抽出 24 份有效，图谱 98 节点 / 131 边

### `core/graph/store.py` — 图谱存储
- networkx.Graph（无向图）+ JSON 持久化（`storage/graph.json`）
- 节点类型颜色：document=#FFA500（橙）/ region=#00CED1（青）/ agency=#FF6347（番茄）/ topic=#9370DB（紫）
- `add_extraction()`：合并相同名称节点，doc_count 累加
- `to_cytoscape()`：导出标准 Cytoscape.js 格式（`{elements: {nodes, edges}}`）

### `core/graph/visualizer.py` — HTML 可视化
- `generate_html(store, output_path, title)` → 自包含 HTML
- vis.js CDN，暗色主题（#1a1a2e 背景）
- 节点大小基于连接数（10-35 范围）
- 点击节点显示邻居信息面板

### `core/qa/chain.py` — RAG 问答
- `SYSTEM_PROMPT`：严格基于资料回答 + 引用编号 + 不编造
- `_build_user_prompt()`：构造"参考资料 + 用户问题"格式
- `RAGChain.ask()`：同步问答
- `RAGChain.ask_stream()`：流式问答，先输出检索信息再输出 LLM

### `core/llm/client.py` — Agnes LLM 客户端
- **重要修复**：`chat_stream` 中要 `if not chunk.choices: continue` 跳过空 chunk（Agnes 会发只含 usage/role 的元 chunk）
- 单例模式：`get_llm()` 返回全局 `_client`

### `core/storage.py` — 存储层
- 两张表：`documents`（文档元信息 + tags 字段）+ `chunks`（分块）
- `bm25_search()`：BM25 检索
- `rebuild_bm25_index()`：重建索引
- `save_document()`：保存文档（自动复制原文件到 uploads/）
- `update_document_tags()`：更新标签
- `list_all_tags()` / `list_documents_by_tag()`：标签查询

### `pyproject.toml` + `install.sh` — 分发安装
- `pyproject.toml`：`name="ima-kb"` `version="3.1.0"` `requires-python=">=3.9"`，入口点 `ima = "run:cli"`，`py-modules=["run", "repl", "config"]`
- `install.sh`：6 步流程（Python 检查 → venv → pip install + `pip install -e .` → .env 配置 → zsh/bash ima 命令 → 验证）
- 选项：`--ocr`（装 Tesseract 语言包）/ `--dev`（开发依赖）/ `--no-venv`（用系统 Python）

### `ima-command.zsh` — 全局命令（保留兼容）
- 已 `source` 到 `~/.zshrc`
- 现已可由 `pip install -e .` 替代（推荐用 pip install）
- 用法：`ima` / `ima web` / `ima search "词"` / `ima ask "问题"`

---

## 🚀 使用方式

### 终端（推荐）
```bash
ima                    # 进入 REPL（Claude Code 风格界面）
ima web                # 启动 Web（http://localhost:8501）
ima search "骨灰"      # BM25 搜索
ima search "骨灰" --tag 殡葬改革  # 按标签筛选搜索
ima ask "退役军人抚恤金？"  # 单次 RAG 问答
ima stats              # 知识库统计
ima retag --force      # 重新生成所有标签
ima graph build --force  # 构建知识图谱
ima graph stats        # 图谱统计
ima graph neighbors "杭州市"  # 查询节点关系
ima graph export       # 导出 HTML 可视化（storage/graph.html）
```

### REPL 内部（v4.0 Claude Code 风格）
```
> 退役军人抚恤金有什么新规定？
⏺ AI 流式回答...

> /search 骨灰
> /tags                    # 查看所有标签
> /tag 殡葬改革           # 按标签筛选文档
> /clear                  # 清空对话
> /exit
```

---

## ✅ P4 完成总结（2026-07-06）

P4 全部 5 个任务已完成，IMA 升级到 v4.0：

| 任务 | 实现方式 | 文件 |
|---|---|---|
| **OCR 补齐** | Tesseract + pytesseract，支持 7 种图片格式 + 扫描 PDF 自动 OCR | `core/ingestion/parser.py` |
| **自动标签** | LLM 生成 3-5 个主题标签，入库时自动调用 | `core/classify/tagger.py` |
| **分发安装** | `pyproject.toml` 定义入口点 + `install.sh` 一键安装 | 根目录 |
| **Claude Code 风格 CLI** | ASCII Logo + 分栏面板 + 橙色提示符 + `⏺` 流式标记 + 命令补全 | `repl.py` |
| **知识图谱** | LLM 抽取实体关系 + networkx 存储 + vis.js 可视化 | `core/graph/` |

### 数据规模变化
- 文档：15 → **27**（OCR 补齐 10 + .doc 2）
- 支持格式：8 → **11**（加图片/扫描 PDF/.doc）
- 标签：0 → **67 个**（覆盖 27 文档）
- 知识图谱：**98 节点 / 131 边**（24/27 文档成功抽取）
- 跳过文件：8 → **0**

---

## ⏳ 后续可优化方向（非必须）

> 已评估难度和工作量，按从易到难排序。建议按此顺序推进。

| # | 优化项 | 难度 | 工作量 | 状态 | 核心要点 |
|---|---|---|---|---|---|
| 1 | **Embedding 缓存层** | ★ | ~1 小时 | ❌ 未做 | vector.py 加 SQLite 缓存（chunk hash → embedding），处理失效即可 |
| 2 | **OCR 优化：PaddleOCR** | ★★ | 1-2 小时 | ❌ 未做 | 替换 parser.py 的 OCR 调用；主要痛点是 paddlepaddle ~500MB 依赖 |
| 3 | **图谱扩展：人物/时间/金额** | ★★★ | 2-3 小时 | ❌ 未做 | LLM prompt 调优 + 新关系类型 + store/visualizer 适配 + 重建图谱验证 |
| 4 | **Web 端 REPL** | ★★★★ | 4-6 小时 | ❌ 未做 | Streamlit 非 REPL 设计：radiolist_dialog 无法复用、补全要重写、ASCII 艺术等宽字体 |
| 5 | **多用户：FastAPI + 隔离** | ★★★★★ | 8-12 小时 | ❌ 未做 | 断层式最难：全栈改造，所有 storage/bm25/vector/graph 加 user_id，认证体系从零写 |
| ✅ | ~~**向量检索：ChromaDB + BM25 混合**~~ | — | — | ✅ **P5 已完成** | BM25 + 向量 + RRF(k=60) + LLM 重排四层流水线，见 core/retrieval/ |

---

## ⚠️ 已知问题与注意事项

1. **jieba 启动提示**：每次启动会输出 `Building prefix dict from the default dictionary ...`，正常现象，可忽略
2. **流式 chunk 空 choices**：Agnes 偶尔发空 chunk，已在 `client.py:88` 修复
3. **macOS Streamlit 沙盒**：启动 Web 时设了 `STREAMLIT_HOME=/tmp` 避免创建 `~/.streamlit` 权限问题（`run.py:115`）
4. **.env 不要提交**：包含真实 API Key，`.gitignore` 已忽略
5. **storage/ 不要提交**：用户私有数据，`.gitignore` 已忽略
6. **Python 版本**：项目兼容 Python 3.9+（macOS 自带 3.9.6），但 3.10+ 体验更好
7. **prompt_toolkit 中文宽度**：补全菜单已用 wcwidth 处理中文对齐，若仍有偏移可升级 prompt_toolkit
8. **`def list()` 命名陷阱**：曾用 `list()` 作函数名覆盖内置 `list()`，已改名为 `list_docs` 并用 `@cli.command(name="list")` 修复
9. **pyproject.toml py-modules**：因 `run.py` 在根目录不在包内，必须显式声明 `py-modules = ["run", "repl", "config"]`，否则 `pip install -e .` 后 `ima` 找不到 `run` 模块

---

## 🧪 验证清单（开工时跑一遍）

```bash
cd ima-kb  # 进入项目目录
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

# 6. 进 REPL（Claude Code 风格界面）
ima
> /help
> /stats
> /tags
> 退役军人抚恤金有什么新规定？
> /exit

# 7. Web（含知识图谱页）
ima web
# 浏览器打开 http://localhost:8501 → 切到「🌐 知识图谱」页

# 8. 导出图谱 HTML
ima graph export
open storage/graph.html
```

如果以上全部通过，说明环境完好。

---

## 💡 设计决策记录

1. **为什么用 BM25 而不是向量检索**：用户资料以政策文档为主，关键词匹配足够准；BM25 免费、本地、秒级，向量检索需要额外 API 费用和向量化预处理
2. **为什么用 Agnes 而不是 DeepSeek**：用户已有 Agnes API Key，先跑通再说；接口是 OpenAI 兼容的，后续切换其他 LLM 只改 `config.py`
3. **为什么用 Streamlit 而不是 React**：纯 Python，开发快，单文件部署，个人用够了
4. **为什么用 ChromaDB + BM25 混合**（P5 更新）：BM25 关键词匹配 + 向量语义检索 + RRF 融合 + LLM 重排，四层流水线互补；向量库不可用时自动降级为纯 BM25
5. **`ima` 命令通过 pip install -e . 注册**：比 zsh function 更标准，自动同步更新；老的 `ima-command.zsh` 保留兼容
6. **为什么用 prompt_toolkit 而不是 rich Prompt**：rich Prompt 不支持弹窗式补全菜单，prompt_toolkit 的 WordCompleter 是终端补全标准方案；子命令菜单用 `radiolist_dialog`（带边框、方向键导航）
7. **为什么用 networkx + vis.js 而不是 pyvis**：networkx 提供图算法支持（degree、neighbors 等），vis.js 直接 CDN 嵌入无依赖，pyvis 只是对 vis.js 的薄包装
8. **为什么图谱抽取用 temperature=0.1**：实体关系抽取要求确定性输出，低温保证 LLM 输出稳定可解析的 JSON
9. **为什么宠物管理员是统一入口**（P5 新增）：所有 AI 交互走 PetAdministrator，串联检索→重排→prompt→LLM→引用→记忆→宠物经验，失败时降级到 RAGChain
10. **为什么主题提取用 jieba 分词**（P5 新增）：比简单 `[:10]` 截断更智能，"骨灰安置政策"→"骨灰安置"；并加了 4 级过滤（空白/停用词/单字/代词开头）

---

**项目状态**：P1-P5 全部完成，IMA v4.0 已部署到 GitHub（仓库 `xiaozhuangma748-hash/ima-kb`），153+ 测试通过，可用于日常使用。后续优化方向见上方「后续可优化方向」章节（5 项剩余，已按难度排序）。
