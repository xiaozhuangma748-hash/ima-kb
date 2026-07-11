# IMA 个人知识库 · 项目交接文档

> 本文档供下一次会话快速理解项目状态，便于继续开发。
> 最后更新：2026-07-12（BM25 匹配度提升 + 跨会话记忆自动提取 + 搜索默认配置 + 会话管理系统）

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
| **P3 体系** | 终端交互式 REPL + `ima` 全局命令 | ✅ 完成 |
| **P4 增强** | OCR 补齐 + 自动标签 + 分发安装脚本 + Claude Code 风格 CLI + 知识图谱 | ✅ 完成 |
| **P5 智能化** | 宠物管理员 v4.0 + 混合检索（BM25+向量+RRF+重排）+ 记忆系统 + 人格风格 + 增量同步 + 质量检查 + 近似去重 + 子命令菜单 + 数据分析 + 报告生成 + **Web 前端（7 页面完整实现）** | ✅ 完成 |
| **P6 性能优化** | BM25 倒排索引 + SQLite WAL 模式 + 连接池 + 懒加载 + 异步 SSE + Web 组件复用 + Agent 输出 Trae 垂直风格 + BM25 索引智能重建 + 命令补全完善 | ✅ 完成 |
| **P7 智能增强** | BM25 匹配度提升（归一化+多模式分词+IDF 截断+b=0.5）+ 跨会话记忆自动提取（LLM 分析对话提取偏好/主题/问题/事实）+ 搜索默认配置（/search config）+ 会话管理系统（独立记忆+自动持久化+跨会话恢复）+ 启动页优化 + 命令补全完善 | ✅ 完成 |

### 实测可用功能

- ✅ 多格式入库（PDF/Word/Excel/PPT/MD/TXT/HTML/代码/**图片/扫描 PDF/.doc**，共 40+ 种，含 20+ 种代码语言）
- ✅ 内容去重（SHA256 hash）
- ✅ BM25 中文分词搜索（jieba）
- ✅ RAG 问答带引用编号
- ✅ 流式输出（已修复 Agnes 空 choices chunk 问题）
- ✅ 多轮对话（REPL 保留 5 轮历史）
- ✅ `ima` 全局终端命令（pip install -e . 注册）
- ✅ **OCR 补齐**（Tesseract + pytesseract，4 扫描 PDF + 4 PNG 入库）
- ✅ **自动标签**（LLM 生成，27 文档共 67 个标签，可按标签筛选）
- ✅ **REPL 命令自动补全**（prompt_toolkit，输入 `/` 弹出命令列表 + 中文描述 + 子命令中文描述）
- ✅ **Claude Code 风格 CLI**（左右分栏欢迎面板，参照 Claude Code v2.1：左区 Welcome back! + 像素机器人 + 模型信息，右区 Tips + Recent activity，竖线分隔 + 顶部标题线 + 橙色提示符 + 流式 `⏺` 标记）
- ✅ **AI 回答 Markdown 渲染**（`rich.Markdown` 渲染，**加粗**、列表、代码块等正确显示）
- ✅ **知识图谱**（LLM 抽取实体关系，networkx 存储，vis.js 可视化）
- ✅ **Web 后台**（7 个页面完整实现：AI 问答 / 文档入库 / 搜索 / 数据分析 / 仪表盘 / 知识图谱 / 宠物管理，FastAPI 后端 + 单页 HTML+JS 前端）
- ✅ **一键安装**（`install.sh` + `pyproject.toml`，支持 `--ocr` / `--dev` / `--no-venv` / `--vector`）
- ✅ **宠物管理员 v4.0**（统一 AI 交互入口，4 种人格风格 scholar/warrior/artisan/neutral，像素风 ASCII 艺术）
- ✅ **混合检索**（BM25 + 向量 bge-small-zh-v1.5 + RRF 融合 k=60 + LLM 重排序，四层流水线）
- ✅ **记忆系统**（用户偏好 + 跨会话任务 + jieba 主题提取 + 非重叠 2-gram 工作流识别）
- ✅ **增量同步**（`ima sync`，文件 mtime/hash 追踪，仅处理变更）
- ✅ **质量检查**（`ima health`，检测空文档/超长块/低质量内容）
- ✅ **近似去重**（`ima dedup`，SimHash 64 位指纹 + 汉明距离 ≤3 判重）
- ✅ **数据分析**（`/analyze` 命令，Excel 多 sheet 自动统计 + 字符图 + AI 解读）
- ✅ **报告生成**（`/report` 命令，Markdown 报告自动生成）
- ✅ **子命令菜单**（8 个主命令 `/memory /pet /graph /sync /session /tag /dedup /health` 用 `radiolist_dialog` 弹出选择菜单）
- ✅ **快速入库**（`/note`/`/clip`/`/url` 命令，支持剪贴板/URL/截图 OCR）
- ✅ **会话管理**（`/session save/load/list`，跨会话恢复对话历史）
- ✅ **性能优化**（BM25 倒排索引 + SQLite WAL 模式 + 连接池 + 懒加载 + 异步 SSE + Web 组件全局复用）
- ✅ **Agent 输出 Trae 垂直风格**（图标+标题+缩进内容，无竖线装饰）
- ✅ **BM25 索引智能重建**（启动时自动检测 chunk_id 过期情况，无需手动 `ima rebuild`）
- ✅ **命令补全完善**（/theme /memory /web /pet /graph 子命令补全注册）
- ✅ **工作流分析**（`/memory workflow analyze` 检测低效操作链）
- ✅ **BM25 匹配度提升**（文本归一化 NFKC + 多模式分词并集 + IDF 截断 + b=0.5 降低长文档惩罚）
- ✅ **跨会话记忆自动提取**（每轮对话后 LLM 自动提取偏好/主题/问题/事实，去重合并，按会话名隔离存储）
- ✅ **搜索默认配置**（`/search config tag/limit/reset`，持久化默认参数）
- ✅ **会话管理系统**（启动时命名会话，每个会话独立记忆文件，自动保存 + 跨会话恢复）
- ✅ **启动页优化**（左区顺序：Welcome → 宠物 → 会话名 → 模型 → 路径；活动记录上限 50 条 + 7 天自动清理）
- ✅ **命令补全完善**（/cross 加入 COMMAND_LIST，/search config 三级补全，/cross add 三级补全）

---

## 🏗️ 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.9+（兼容 macOS 自带 3.9.6） |
| CLI 框架 | click + rich + prompt_toolkit（补全 + `radiolist_dialog` 子命令菜单） |
| 元数据库 | SQLite（单文件 metadata.db） |
| 文档解析 | PyMuPDF / python-docx / openpyxl / python-pptx / trafilatura / **Pillow + pytesseract（OCR）** / **macOS textutil（.doc）** |
| 中文检索 | jieba（搜索引擎模式 + 全模式并集）+ 自实现 BM25（k1=1.5, b=0.5, IDF 截断）+ NFKC 文本归一化 |
| **向量检索**（P5） | **ChromaDB + sentence-transformers（bge-small-zh-v1.5）+ RRF 融合 + LLM 重排序** |
| LLM | Agnes AI（OpenAI 兼容协议，模型 `agnes-2.0-flash`） |
| 知识图谱 | networkx + vis.js（HTML 可视化） |
| **Web 后端**（P5） | **FastAPI + uvicorn + SSE（流式问答）+ 7 个 API 路由模块** |
| **Web 前端**（P5） | **单页 HTML + JS（7 页面侧边栏切换 + vis.js 图谱 + SSE 流式）** |
| **记忆系统**（P5） | **MemoryStore（JSON 原子写入）+ TaskManager + ProfileManager（jieba 主题）+ WorkflowTracker（2-gram）** |
| **跨会话记忆**（P7） | **CrossSessionMemory（按会话名隔离 JSON 存储）+ MemoryExtractor（LLM 自动提取，温度 0.1）** |
| **搜索配置**（P7） | **SearchConfig（JSON 持久化默认 tag/limit）** |
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
├── run.py                        # CLI 入口（22 个顶层命令 + graph 5 子命令，无子命令时进入 REPL）
├── repl.py                       # 交互式 REPL（IMA v4.0 · Claude Code 风格 + 40+ 子命令）
│
├── core/
│   ├── ingestion/
│   │   ├── parser.py             # 多格式解析（40+ 种，含 20+ 代码语言）+ OCR 降级 + .doc textutil
│   │   ├── chunker.py            # 智能分块（按段落+重叠+句子边界）
│   │   └── quick.py              # 快速入库（/note /clip /url）
│   ├── llm/
│   │   ├── client.py             # Agnes LLM 客户端（chat / chat_stream）
│   │   └── degrade.py            # 统一降级提示
│   ├── search/
│   │   ├── bm25.py               # BM25 索引 + 检索（P7: 归一化+多模式分词+IDF 截断+b=0.5）
│   │   └── config.py             # P7: 搜索默认配置（/search config）
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
│   │   ├── workflow.py           # WorkflowTracker（非重叠 2-gram）
│   │   ├── cross_session.py       # P7: 跨会话记忆（四类：偏好/主题/问题/事实，按会话名隔离）
│   │   └── extractor.py           # P7: LLM 自动提取器（每轮对话后提取值得记住的信息）
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
│   │   ├── arts/                 # 35 个 ASCII 艺术文件（scholar/warrior/artisan × 10 级 + none × 5 级）
│   │   └── storage.py            # 宠物持久化
│   ├── session/                  # P5 新增：会话管理
│   │   └── store.py              # 跨会话历史保存/恢复
│   ├── sync/                     # P5 新增：同步与质量
│   │   ├── tracker.py            # 增量同步（mtime/hash 追踪）
│   │   ├── checker.py            # 质量检查（空文档/超长块）
│   │   └── dedup.py              # SimHash 近似去重（64 位指纹 + 汉明距离）
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
├── web/                          # P5 已完成：Web 前端 + 后端 API
│   ├── app.py                    # FastAPI 主应用（create_app 工厂函数）
│   ├── routes/
│   │   ├── qa.py                 # SSE 流式问答 API（检索→重排→人格→LLM→引用→记忆）
│   │   ├── ingest.py             # 文档入库 API（多文件上传 + URL 网页入库）
│   │   ├── search.py             # 混合检索 API（BM25+向量+重排+标签筛选）
│   │   ├── analyze.py            # 数据分析 API（上传+统计+AI解读+报告导出）
│   │   ├── stats.py              # 仪表盘统计 API
│   │   ├── graph.py              # 知识图谱 API（data/neighbors/build/export）
│   │   └── pet.py                # 宠物管理 API（status/interact/style/adopt）
│   ├── templates/
│   │   └── index.html            # 单页应用（7 页面，~1000 行，侧边栏导航切换）
│   └── static/
│       └── app.js                # 前端交互脚本（635 行，SSE/拖拽/搜索/图谱/宠物等）
│
├── tests/                        # 323+ 测试
│   ├── retrieval/                # 混合检索测试
│   ├── memory/                   # 记忆系统测试
│   ├── pet/                      # 宠物系统测试
│   ├── persona/                  # 人格测试
│   ├── sync/                     # 同步/去重测试
│   └── ...
│
├── test_data/                    # 6 个测试文件
│
└── storage/                      # 本地数据（gitignore）
    ├── metadata.db               # SQLite 元数据
    ├── bm25_index.pkl            # BM25 持久化索引
    ├── file_tracker.db           # 文件同步追踪数据库
    ├── theme.json                # 主题配置持久化
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
- `cli` group（**注意**：之前的 bug 是 chat 命令放在 cli 定义之前导致 NameError，已修复，新增命令要放在 `cli` 之后）
- **顶层命令**（22个）：`web` `chat` `ingest` `note` `clip` `url` `list` `search` `ask` `show` `stats` `retag` `delete` `rebuild` `memory` `watch` `report` `analyze` `sync` `health` `dedup` `graph`
- **`graph` 子命令组**（5 个）：
  - `ima graph build [--force] [-d ID] [-n N]`：调 LLM 抽取实体关系构建图谱
  - `ima graph stats [-t TYPE]`：图谱统计 + 节点列表
  - `ima graph neighbors <名称>`：查询节点邻居
  - `ima graph export [-o PATH]`：导出 HTML 可视化
  - `ima graph clear`：清空图谱

### `repl.py` — IMA REPL（v4.0 · Claude Code 风格）
- **欢迎面板**：左窄右宽布局（左 32 列：mascot+宠物信息+状态 / 右：Tips+Recent activity），中间 `│` dim 竖线分隔，顶部标题线 `── IMA v4.0 ──`，输入框前 dim 提示 `/help for shortcuts` / `Ctrl+C to exit`
- **命令补全**：自定义 `CommandCompleter`（继承 `Completer`）取代旧 `NestedCompleter`
  - 输入 `/` 弹出所有命令 + 中文描述
  - 输入 `/s` 自动匹配 search/session/show/stats/sync 等 s 开头命令
  - 子命令也带中文描述（如 `/memory ` 弹出 clear清空/format格式/style风格...）
  - 支持多级嵌套（如 `/memory format ` → table表格/list列表/prose散文）
  - 别名自动解析（`/m` → `/memory` 子命令）
- **AI 回答 Markdown 渲染**：`_render_answer()` 用 `rich.Markdown(result.text)` 渲染，**粗体**、列表、标题正确显示
- **橙色 `>` 提示符**（Claude Code 风格）
- **AI 对话**：橙色 `⏺` 圆点标记 + 首 token Spinner + 流式输出
- **Web 后台**：`/web` 后台线程启动 FastAPI、`/web stop` 关闭；支持 `--host --port` 参数
- 命令：`/help /search /ingest /list /show /tags /tag /delete /stats /rebuild /clear /web /web stop /exit /quit`
- 多轮对话：保留最近 10 条 history（5 轮）
- **已移除**：自适应 Logo 切换（`_pick_logo`、`ASCII_LOGO_SMALL`、`ASCII_LOGO_MINI`）

### `core/ingestion/parser.py` — 多格式解析
- **支持 40+ 种格式**：PDF/Word(.docx/.doc)/Excel/PPT/MD/TXT/HTML/代码(20+ 种语言)/图片(.png/.jpg/.jpeg/.tif/.tiff/.bmp/.webp)
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
- `pyproject.toml`：`name="ima-kb"` `version="4.0.0"` `requires-python=">=3.9"`，入口点 `ima = "run:cli"`，`py-modules=["run", "repl", "config"]`
- `install.sh`：6 步流程（Python 检查 → venv → pip install + `pip install -e .` → .env 配置 → zsh/bash ima 命令 → 验证）
- 选项：`--ocr`（装 Tesseract 语言包）/ `--dev`（开发依赖）/ `--no-venv`（用系统 Python）

### `ima-command.zsh` — 全局命令（保留兼容）
- 已 `source` 到 `~/.zshrc`
- 现已可由 `pip install -e .` 替代（推荐用 pip install）
- 用法：`ima` / `ima search "词"` / `ima ask "问题"`

---

## 🚀 使用方式

### 终端（推荐）
```bash
ima                    # 进入 REPL（Claude Code 风格界面）
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
> /web                     # 启动 Web 后台
> /web stop                # 停止 Web 后台
> /clear                  # 清空对话
> /exit
```

---

## ✅ P4 完成总结（2026-07-06）

P4 全部 5 个任务已完成，IMA 升级到 v4.0：

| 任务 | 实现方式 | 文件 |
|---|---|---|
| **OCR 补齐** | Tesseract + pytesseract，支持 6 种图片格式 + 扫描 PDF 自动 OCR | `core/ingestion/parser.py` |
| **自动标签** | LLM 生成 3-5 个主题标签，入库时自动调用 | `core/classify/tagger.py` |
| **分发安装** | `pyproject.toml` 定义入口点 + `install.sh` 一键安装 | 根目录 |
| **Claude Code 风格 CLI** | ASCII Logo + 分栏面板 + 橙色提示符 + `⏺` 流式标记 + 命令补全 | `repl.py` |
| **知识图谱** | LLM 抽取实体关系 + networkx 存储 + vis.js 可视化 | `core/graph/` |

### 数据规模变化
- 文档：15 → **27**（OCR 补齐 10 + .doc 2）
- 支持格式：8 → **40+ 种**（加图片/扫描 PDF/.doc/20+ 种代码语言）
- 标签：0 → **67 个**（覆盖 27 文档）
- 知识图谱：**98 节点 / 131 边**（24/27 文档成功抽取）
- 跳过文件：8 → **0**

---

## ⏳ 后续可优化方向（非必须）

> 已评估难度和工作量，按从易到难排序。建议按此顺序推进。

| # | 优化项 | 难度 | 工作量 | 状态 | 核心要点 |
|---|---|---|---|---|---|
| 1 | **Embedding 缓存层** | ★ | ~1 小时 | ❌ 未做 | vector.py 加 SQLite 缓存（chunk hash → embedding），处理失效即可 |
| ✅ | ~~**OCR 优化：PaddleOCR**~~ | ★★ | 1-2 小时 | ✅ **2026-07-12 完成** | PaddleOCR 为主引擎（原图直传，内部自带预处理），Tesseract 降级（外部预处理：灰度+二值化+放大）；DPI 200；见 [parser.py](file:///core/ingestion/parser.py) |
| 3 | **图谱扩展：人物/时间/金额** | ★★★ | 2-3 小时 | ❌ 未做 | LLM prompt 调优 + 新关系类型 + store/visualizer 适配 + 重建图谱验证 |
| 4 | **多用户：FastAPI + 隔离** | ★★★★★ | 8-12 小时 | ❌ 未做 | 断层式最难：全栈改造，所有 storage/bm25/vector/graph 加 user_id，认证体系从零写 |
| ✅ | ~~**Web 端开发：7 页面 FastAPI + 前端**~~ | — | — | ✅ **P5 已完成** | 7 页面 + 7 API 全部实现，见 web/ 目录；PRD 原定 Streamlit 方案改为 FastAPI 原生方案 |
| ✅ | ~~**向量检索：ChromaDB + BM25 混合**~~ | — | — | ✅ **P5 已完成** | BM25 + 向量 + RRF(k=60) + LLM 重排四层流水线，见 core/retrieval/ |

---

## ⚠️ 已知问题与注意事项

1. **jieba 启动提示**：每次启动会输出 `Building prefix dict from the default dictionary ...`，正常现象，可忽略
2. **流式 chunk 空 choices**：Agnes 偶尔发空 chunk，已在 `client.py:88` 修复
3. **.env 不要提交**：包含真实 API Key，`.gitignore` 已忽略
4. **storage/ 不要提交**：用户私有数据，`.gitignore` 已忽略
5. **Python 版本**：项目兼容 Python 3.9+（macOS 自带 3.9.6），但 3.10+ 体验更好
6. **prompt_toolkit 中文宽度**：补全菜单已用 wcwidth 处理中文对齐，若仍有偏移可升级 prompt_toolkit
7. **`def list()` 命名陷阱**：曾用 `list()` 作函数名覆盖内置 `list()`，已改名为 `list_docs` 并用 `@cli.command(name="list")` 修复
8. **pyproject.toml py-modules**：因 `run.py` 在根目录不在包内，必须显式声明 `py-modules = ["run", "repl", "config"]`，否则 `pip install -e .` 后 `ima` 找不到 `run` 模块
9. ~~**`.streamlit/config.toml` 残留~~：✅ 已删除（2026-07-09）
10. **版本号已统一**：`pyproject.toml` 版本已从 `3.1.0` 更新为 `4.0.0`，与代码 v4.0 一致（已修复）

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

# 7. 导出图谱 HTML
ima graph export
open storage/graph.html

# 8. 启动 Web 后台
ima web
# 浏览器打开 http://127.0.0.1:8501，检查 7 个页面
```

如果以上全部通过，说明环境完好。

---

## 💡 设计决策记录

1. **为什么用 BM25 而不是向量检索**：用户资料以政策文档为主，关键词匹配足够准；BM25 免费、本地、秒级，向量检索需要额外 API 费用和向量化预处理
2. **为什么用 Agnes 而不是 DeepSeek**：用户已有 Agnes API Key，先跑通再说；接口是 OpenAI 兼容的，后续切换其他 LLM 只改 `config.py`
3. **为什么用 ChromaDB + BM25 混合**（P5 更新）：BM25 关键词匹配 + 向量语义检索 + RRF 融合 + LLM 重排，四层流水线互补；向量库不可用时自动降级为纯 BM25
4. **`ima` 命令通过 pip install -e . 注册**：比 zsh function 更标准，自动同步更新；老的 `ima-command.zsh` 保留兼容
5. **为什么用 prompt_toolkit 而不是 rich Prompt**：rich Prompt 不支持弹窗式补全菜单，prompt_toolkit 的 Completer 是终端补全标准方案；自定义 `CommandCompleter` 支持中文描述 + 子命令嵌套；子命令菜单用 `radiolist_dialog`（带边框、方向键导航）
6. **为什么用 networkx + vis.js 而不是 pyvis**：networkx 提供图算法支持（degree、neighbors 等），vis.js 直接 CDN 嵌入无依赖，pyvis 只是对 vis.js 的薄包装
7. **为什么图谱抽取用 temperature=0.1**：实体关系抽取要求确定性输出，低温保证 LLM 输出稳定可解析的 JSON
8. **为什么宠物管理员是统一入口**（P5 新增）：所有 AI 交互走 PetAdministrator，串联检索→重排→prompt→LLM→引用→记忆→宠物经验，失败时降级到 RAGChain
9. **为什么主题提取用 jieba 分词**（P5 新增）：比简单 `[:10]` 截断更智能，"骨灰安置政策"→"骨灰安置"；并加了 4 级过滤（空白/停用词/单字/代词开头）
10. **为什么不把入库文件保存成 .md 替代 SQLite**（2026-07-12 评估）：经过完整利弊分析后决定**不替代**，理由如下：
    - **分块无处存**：chunks 表存分块内容，.md 只能存原文 → 每次启动都要重新分块（39 篇文档 812 chunks，冷启动慢 3-5 秒）
    - **BM25 索引失效**：`bm25_index.pkl` 序列化了 `chunk_id → 文本` 映射，.md 重新分块后 chunk_id 变化，索引要重建
    - **向量索引失效**：ChromaDB 用 chunk_id 关联向量，chunk_id 不稳定 → 向量检索全废
    - **元数据查询慢**：title/tags/meta 要塞 frontmatter，`ima list`/`ima stats` 要扫整个目录而非一条 SQL
    - **去重检查慢**：当前 `content_hash` 索引 O(log n)，改 .md 要读所有文件算 hash
    - **并发写入风险**：REPL + web 同时写同一 .md 会冲突，SQLite 有事务保护
    - **结论**：保留 SQLite 作为主存储，如需人类可读/Git 追踪可采用折中方案（SQLite + 额外导出 .md 副本到 `storage/markdown/`），改动量小且不破坏检索架构

---

**项目状态**：P1-P5 全部完成（含 Web 前端 7 页面），IMA v4.0 已部署到 GitHub（仓库 `xiaozhuangma748-hash/ima-kb`），323 个测试（319 通过 / 4 失败为已知老问题），可用于日常使用。后续优化方向见上方「后续待办」章节（5 项剩余，无高优先级待办）。

---

## 📋 今日工作总结（2026-07-08）

### ✅ 已完成

| # | 任务 | 影响文件 | 说明 |
|---|---|---|---|
| 1 | **修复子命令补全消失** | `repl.py` | 输入空格后 `parts` 丢失尾部空格导致找不到子命令，增加 `trailing` 检测 |
| 2 | **子命令中文描述** | `repl.py` | 新增 `_SUB_MENU_DESC` 字典（tuple path → 中文描述），补全菜单显示中文解释 |
| 3 | **修复 Markdown 渲染** | `repl.py` | `_render_answer` 改用 `rich.Markdown(result.text)`，**粗体**、列表、标题正确显示 |
| 4 | **启动页重构** | `repl.py` | 左窄右宽布局（左 32 列 / 右自适应），中间 `│` dim 竖线分隔，顶部标题线，底部快捷键提示行，像素宠物缩小 |
| 5 | **底部边框对齐** | `repl.py` | 用 `Console.capture()` 动态测量左侧面板高度，统一设置两个面板 `height` |
| 6 | **移除死代码** | `repl.py` | 删除 `_pick_logo`、`ASCII_LOGO_SMALL`、`ASCII_LOGO_MINI` |
| 7 | **修复主题切换丢宠物** | `repl.py` | `_cmd_theme` 补上 `pet=self.pet` 参数 |
| 8 | **更新文档** | `HANDOFF.md`, `INSTALL.md` | 同步所有变更到交接文档和安装指南 |
| 9 | **宠物 block-style 像素化 + 进度条** | `core/pet/arts/`、`core/pet/art.py`、`repl.py` | 补充 scholar/warrior/artisan 1-10 级 30 个 + none 1-5 级 5 个像素图；fallback 占位符也改为 block-style；`/pet` 状态数值改为彩色进度条（饱食/心情/能量/清洁/经验） |
| 10 | **修复背包显示 + use 序号** | `repl.py` | `buy()` 存的 `{item_id, count}` 没有 name/effect，背包显示从 `shop.list_items()` 查找名称和效果；`/pet use 1` 支持序号映射到 item_id |
| 11 | **智能路由 404 降级提示** | `repl.py` | `/smart` LLM 调用失败时检测 404 → 给出切换模型建议 + 手动命令替代方案 |
| 12 | **图谱抽取优化** | `core/graph/extractor.py`、`repl.py` | 提示词放宽为非限定"政策文档"；内容<50字跳过LLM调用；空结果显示"无可抽取实体"而非模糊错误 |
| 13 | **图谱导出自动打开浏览器** | `repl.py`、`run.py` | `/graph export` 完成后 `webbrowser.open()` 自动在浏览器中打开，不再需要手动 `open` |
| 14 | **工作流 suggest 无参数显示状态** | `repl.py` | `/memory workflow suggest` 不加参数时显示当前开关状态，不再报"无效值" |
| 15 | **全量命令操作逻辑统计** | — | 梳理 67+ 命令的操作逻辑，含 15 类别、分发流程、核心方法映射 |

### ❌ 未完成（下一步）

| # | 任务 | 优先级 | 说明 |
|---|---|---|---|
| 1 | **PDF 重新解析** | 🟡 中 | OCR 已安装可用，但之前入库的 PDF 是在装 OCR 前入库的，需 `/reparse` 重新解析提取内容 |
| 2 | **Embedding 缓存层** | 🟡 低 | `vector.py` 可加 SQLite 缓存（chunk hash → embedding） |
| 3 | **OCR 优化** | 🟡 低 | 可选替换为 PaddleOCR |

---

## 📋 文档修正记录（2026-07-09）

经核实代码与文档不符后，以下内容已修正：

| # | 修正项 | 旧说法 | 修正为 |
|---|---|---|---|
| 1 | ASCII 艺术文件 | 20 个（4风格×5等级） | 35 个（scholar/warrior/artisan×10级 + none×5级） |
| 2 | 宠物分系等级 | Lv6 分系 | Lv5 分系，MAX_LEVEL=10 |
| 3 | run.py 命令数 | "21个命令"（列表不完整） | 21个顶层命令+5个graph子命令=26，列出全部名称 |
| 4 | storage/ 目录 | 列了不存在的graph.json | 移除graph.json，加file_tracker.db和theme.json |
| 5 | test_data/ | 5个文件 | 6个文件 |
| 6 | 测试数量 | 153+ | 323+ |
| 7 | Web 默认端口 | 文档写8000 | 实际默认8501（run.py+repl.py） |
| 8 | 版本号不一致 | ✅ 已修复 | pyproject.toml 统一为 4.0.0（2026-07-10） |
| 9 | Web 前端状态 | "页面为空/未实现" | 7页面+7API全部已实现 |
| 10 | PRD 技术栈 | Streamlit | FastAPI（实际实现） |
| 11 | INSTALL.md 宠物等级 | Lv6 分系 | Lv5 分系 |

---

## 📅 后续待办（优化方向）

> Web 前端 7 页面已全部完成，当前无高优先级待办。

### 优先级排序

| # | 任务 | 优先级 | 说明 |
|---|---|---|---|
| 1 | **Embedding 缓存层** | 🟡 低 | `vector.py` 加 SQLite 缓存（chunk hash → embedding），处理失效即可 |
| 2 | **图谱扩展** | 🟡 低 | 新增人物/时间/金额等实体类型，需重建图谱验证 |
| 3 | **多用户隔离** | 🔴 高（仅如需内网多人） | 全栈改造，所有 storage 加 user_id，认证体系从零写 |
| ✅ | ~~**PDF 重新解析**~~ | — | ✅ **2026-07-12 完成**：8 个 PDF 全部用 PaddleOCR 重新入库，39 篇文档 812 chunks |
| ✅ | ~~**OCR 优化：PaddleOCR**~~ | — | ✅ **2026-07-12 完成**：PaddleOCR 主引擎 + Tesseract 降级，见 [parser.py](file:///core/ingestion/parser.py) |

### Web 前端已完成确认

7 个页面 + 7 个后端 API 已全部实现：

| 页面 | 前端实现 | 后端 API | 核心功能 |
|---|---|---|---|
| 💬 AI 问答 | `index.html` #page-qa | `qa.py` SSE `/api/qa/stream` | 左右分栏、人格 chips、流式输出、引用溯源 |
| 📥 文档入库 | `index.html` #page-ingest | `ingest.py` upload+url | 拖拽上传、URL 入库、入库进度、标签显示 |
| 🔍 搜索 | `index.html` #page-search | `search.py` `/api/search` | 标签筛选、向量/重排开关、高亮、相关度色条 |
| 📊 数据分析 | `index.html` #page-analyze | `analyze.py` upload+export | Sheet 切换、统计卡、AI 解读、报告导出 |
| 📈 仪表盘 | `index.html` #page-dashboard | `stats.py` `/api/stats` | 4 指标卡、标签分布、质量告警、最近入库 |
| 🕸️ 知识图谱 | `index.html` #page-graph | `graph.py` data/neighbors/build/export | vis.js 网络可视化、邻居查询、重建、导出 |
| 🐾 宠物管理 | `index.html` #page-pet | `pet.py` status/interact/style/adopt | ASCII 艺术、状态条、4 人格卡片、互动 |

**启动方式**：REPL 里 `/web`（默认 127.0.0.1:8501），或 `uvicorn web.app:create_app --factory --host 0.0.0.0 --port 8501`

### Web 技术方案说明

- **前端**：单页 HTML（`web/templates/index.html`）+ JS（`web/static/app.js`），侧边栏导航切换 7 个页面
- **后端**：FastAPI（`web/app.py`）+ 7 个路由模块（`web/routes/`），复用 core/ 模块
- **原型图**：`docs/prototype/web-prototype.html`（设计参考，实际实现基于 FastAPI 原生方案而非 Streamlit）
- **PRD**：`docs/PRD-web-backend.md`（注意：PRD 原定 Streamlit 方案，实际改为 FastAPI 原生）

---

## 🆕 2026-07-09 更新：问答优化 + 生图能力集成

### 一、问答链路升级

#### 1. 混合检索取代纯 BM25

**之前**：REPL 聊天只使用 `BM25Index.bm25_search()`，只能做关键词匹配。

**现在**：`RAGChain` 使用 `HybridRetriever`（BM25 + 向量 + RRF 融合）+ `Reranker`（LLM 重排序），四层检索流水线。

改动文件：
- `core/qa/chain.py` — 完全重写，集成 `HybridRetriever` 和 `Reranker`
- `repl.py` — `_handle_chat` 降级路径改用 `RAGChain.ask()` 同步模式

#### 2. 多轮对话 Query Expansion

**之前**：每轮对话独立检索，追问时丢失上下文。

**现在**：`_expand_query()` 从上文 AI 回答中提取关键短句，拼接到当前查询。例如：
- 用户："殡葬补贴多少？" → AI："2000 元"
- 用户："骨灰盒也有吗？" → 实际检索："骨灰盒 也有吗 殡葬补贴 2000 元"

#### 3. 检索置信度阈值

**之前**：不管检索结果多差，都喂给 LLM。

**现在**：
- 最高检索分数低于阈值时，Prompt 中加入警告："⚠️ 检索结果相关度较低，请谨慎回答"
- 无检索结果时直接返回"根据现有资料无法回答该问题"

#### 4. Agent 工具调用结构化

**之前**：用 `<tool>xxx</tool><args>yyy</args>` XML 格式，正则解析容易失败。

**现在**：
- 优先使用 JSON 格式：`{"tool": "search", "args": "骨灰"}`
- 保留 XML 格式向后兼容
- `_parse_tool_call()` 双格式支持

#### 5. 重排序 JSON 解析健壮性

**之前**：直接 `json.loads(response)`，LLM 多输出一点文字就失败。

**现在**：`Reranker._parse_scores()` 三级降级：
1. 直接 `json.loads`
2. 正则提取 `[...]` 或 `{...}` 片段
3. 清理 markdown code block 标记（```json ... ```）

### 二、生图能力集成

#### 新增模块：`core/image/`

| 文件 | 功能 |
|---|---|
| `core/image/__init__.py` | 模块入口，导出 `ImageGenerator` 和 `ImageError` |
| `core/image/generator.py` | 封装 Agnes Image 2.1 Flash API |

**三种生图能力**：

| 方法 | 说明 | 示例 |
|---|---|---|
| `text_to_image(prompt)` | 文生图 | 直接描述想要的图像 |
| `doc_to_image(title, content, style)` | 基于文档内容生图 | 自动提取主题 + 风格化 |
| `daily_card(topics, date, style)` | 生成每日知识卡片 | 竖版分享卡片 |

**技术细节**：
- 复用 LLM 的 OpenAI 客户端（相同的 `base_url` + `api_key`）
- 自动中文→英文 prompt 翻译（通过 LLM 增强）
- 3 次重试 + 指数退避
- 支持 URL 和 base64 两种响应格式

#### 新增 CLI 命令

| 命令 | 功能 | 示例 |
|---|---|---|
| `/pic <描述>` | 直接文生图 | `/pic 一只在竹林中散步的猫` |
| `/draw <文档ID> [--style 风格]` | 基于文档生成配图 | `/draw 862e0973 --style 水墨` |
| `/daily [--topics 主题1,主题2]` | 生成每日知识卡片 | `/daily --topics 政策,补贴` |

#### 新增配置项（`.env`）

```env
# ===== 图像生成（Agnes Image 2.1 Flash）=====
IMAGE_MODEL=agnes-image-2.1-flash
IMAGE_SIZE=1024x1024
IMAGE_RESPONSE_FORMAT=url
```

#### 配置文件变更

- `config.py` — 新增 `image_model`, `image_size`, `image_response_format`, `images_dir` 属性
- `repl.py` — 新增 `_cmd_draw()`, `_cmd_daily()`, `_cmd_pic()` 方法
- `HELP_TEXT` — 新增 3 个生图命令说明
- `COMMAND_LIST` — 新增 `/draw`, `/daily`, `/pic` 命令条目

### 三、改动文件清单

| 文件 | 变更类型 | 说明 |
|---|---|---|
| `config.py` | 修改 | 新增图像生成配置项 |
| `.env` | 修改 | 新增 IMAGE_MODEL 等配置 |
| `core/qa/chain.py` | **重写** | 混合检索 + query expansion + 置信度阈值 |
| `core/retrieval/rerank.py` | 修改 | 健壮 JSON 解析（三级降级） |
| `core/agent/agent.py` | **重写** | JSON 工具调用 + XML 向后兼容 |
| `core/image/__init__.py` | **新增** | 图像生成模块入口 |
| `core/image/generator.py` | **新增** | ImageGenerator 实现 |
| `repl.py` | 修改 | 新增 3 个生图命令 + 帮助文本 + COMMAND_LIST |

### 四、测试

- **319 个测试通过**，4 个失败为已有的 `test_subcommand_menu.py` 问题（与本次改动无关）

---

##  2026-07-10 更新：REPL 模块化拆分 + 启动页重构 + 前端 JS 模块化

### 一、REPL 模块化拆分

原 `repl.py`（约 4300 行）拆分为 `core/cli/` 目录：

| 模块 | 职责 |
|---|---|
| `core/cli/main.py` | REPL 启动入口 |
| `core/cli/repl.py` | REPL 主类（命令分发 + AI 对话） |
| `core/cli/chat.py` | AI 对话渲染逻辑 |
| `core/cli/completer.py` | 命令自动补全 |
| `core/cli/welcome.py` | 启动页渲染 + 活动记录 |
| `core/cli/constants.py` | 常量、命令列表、别名表、console 实例 |
| `core/cli/commands/` | 各命令处理器（agent/docs/graph/memory/pet/pipe/session/sync/analyze） |

根目录 `repl.py` 现为薄封装，仅 `from core.cli.main import main` 委托执行。

### 二、启动页重构

参照 Claude Code v2.1 风格，左右分栏布局：
- 左区：`Welcome back!` + 像素机器人 ASCII 图 + 模型信息
- 右区：Tips + Recent activity
- 中间 `│` 竖线分隔，顶部标题线

### 三、前端 JS 模块化

`web/static/app.js` 拆分到 `web/static/js/` 目录，按页面/职责分离：

| 模块 | 职责 |
|---|---|
| `nav.js` | 侧边栏导航 + 页面切换 |
| `qa.js` | AI 问答（SSE 流式） |
| `ingest.js` | 文档入库（拖拽上传） |
| `search.js` | 混合检索 |
| `analyze.js` | 数据分析 |
| `dashboard.js` | 仪表盘 |
| `graph.js` | 知识图谱（vis.js） |
| `pet.js` | 宠物管理 |
| `state.js` | 全局状态管理 |
| `utils.js` | 通用工具函数 |

---

## 🆕 2026-07-11 更新：性能优化 + Agent 输出样式重构

### 一、性能优化（P6）

#### 1. BM25 倒排索引

**之前**：BM25 搜索遍历所有文档计算词频，O(N) 复杂度。

**现在**：`core/search/bm25.py` 新增倒排索引（term → chunk_id 列表），搜索时只遍历含目标词的文档，大幅提升检索速度。

#### 2. SQLite WAL 模式

**之前**：SQLite 默认 journal_mode=DELETE，写操作阻塞读操作。

**现在**：`core/storage.py` 启用 WAL 模式（`PRAGMA journal_mode=WAL`），支持并发读写，提升 Web 后台响应速度。

#### 3. 连接池优化

**之前**：每次请求创建新 SQLite 连接。

**现在**：Web 路由模块（`web/routes/`）全局复用 Storage/VectorIndex 实例，避免重复初始化。

#### 4. 懒加载

**之前**：启动时加载所有组件（jieba、向量模型等），冷启动慢。

**现在**：`core/retrieval/vector.py`、`core/search/bm25.py` 等组件改为懒加载，首次使用时才初始化。

#### 5. 异步 SSE

**之前**：SSE 流式问答使用同步生成器。

**现在**：`web/routes/qa.py` 改用 `async generator`，提升并发处理能力。

#### 6. BM25 索引智能重建

**之前**：每次启动都提示"BM25 索引数量与数据库 chunk 数不匹配，请执行 `ima rebuild`"。

**现在**：`core/storage.py` 的 `_sync_bm25_from_db()` 智能检测：当所有 chunk_id 都过期时自动重建索引，无需手动干预。

### 二、Agent 输出样式重构

#### 之前（竖线时间线风格）

```
│
│ ◉  思考  7.2s · 用户询问"什么是政策"...
│  ✓ search 政策 定义
│  ✓ search  (1156 字符)
```

#### 现在（Trae 垂直风格）

```
  [T]  思考  7.2s
  这是一个关于"爱情"定义的哲学或心理学问题。虽然知识库中可能有关于文学、心理学
  或社会学的文档涉及爱情，但作为一个通用概念，我可以直接基于常识和广泛的知识...

  [OK]  search  (1288 字符)

  [T]  思考  9.3s
  搜索结果主要关于殡葬服务和战略发展，并没有直接提供关于"爱情"的学术或哲学定义...

  [OK]  search  (956 字符)

✓ 完成 · 31.5s · 共 2 步
```

**设计要点**：
- 无竖线装饰，层次靠缩进区分
- 每个步骤有图标 + 标题（`[T]` 思考、`[OK]` 工具调用、`[ERR]` 错误）
- 内容缩进显示在标题下方
- 思考内容截断到 150 字符，自动换行时保持缩进对齐

### 三、命令补全完善

**之前**：`/theme`、`/memory`、`/web`、`/pet`、`/graph` 等命令输入空格后不显示子选项。

**现在**：在 `core/cli/constants.py` 的 `_SUB_MENU_NESTED` 中注册所有子命令，补全菜单正常显示。

### 四、工作流分析

新增 `/memory workflow analyze` 命令，检测低效操作链（如重复搜索、无效命令序列），给出改进建议。

### 五、改动文件清单

| 文件 | 变更类型 | 说明 |
|---|---|---|
| `core/search/bm25.py` | **重写** | 倒排索引 + 智能重建 |
| `core/storage.py` | 修改 | WAL 模式 + 连接池 + 智能重建 |
| `core/retrieval/vector.py` | 修改 | 懒加载 |
| `core/cli/commands/agent.py` | **重写** | Trae 垂直风格输出 |
| `core/cli/constants.py` | 修改 | 补全注册 |
| `core/cli/commands/memory.py` | 修改 | 工作流分析 |
| `web/app.py` | 修改 | 组件全局复用 |
| `web/routes/*.py` | 修改 | 异步 SSE + 组件复用 |

### 六、测试

- **337 个测试全部通过**（之前 323 个 + 新增 14 个）
- 之前失败的 4 个测试已修复（调整子命令菜单触发条件）

---

## 🆕 2026-07-12 更新：BM25 匹配度提升 + 跨会话记忆 + 搜索配置 + 会话管理（P7）

### 一、BM25 匹配度提升

**之前**：BM25 使用默认参数，长文档被过度惩罚，分词单一。

**现在**：
- **文本归一化**：NFKC 规范化全角/半角字符
- **多模式分词**：搜索引擎模式 + 全模式并集，提高召回
- **IDF 截断**：避免极端高频词主导评分
- **b=0.5**：降低长文档惩罚（默认 0.75），更适合政策文档

### 二、跨会话记忆自动提取

**之前**：记忆系统仅记录任务和主题，不会从对话中主动提取有价值信息。

**现在**：
- 每轮对话后 LLM 自动分析，提取四类信息：偏好 / 主题 / 问题 / 事实
- 提取温度 0.1，保证稳定性
- 按会话名隔离存储，不同会话互不干扰
- 去重合并，避免重复记忆

### 三、搜索默认配置

新增 `/search config` 命令，持久化默认搜索参数：
- `/search config tag <标签>` - 设置默认标签筛选
- `/search config limit <数量>` - 设置默认返回数量
- `/search config reset` - 重置为默认值
- `/search config` - 查看当前配置

### 四、会话管理系统

**之前**：会话仅能手动 save/load，记忆不隔离。

**现在**：
- 启动时命名会话（支持默认会话）
- 每个会话独立记忆文件，自动保存
- 跨会话恢复对话历史和记忆
- 与跨会话记忆系统联动

### 五、启动页优化

左区显示顺序调整为：Welcome → 宠物 → 会话名 → 模型 → 路径。
活动记录上限 50 条，超过 7 天自动清理。

### 六、命令补全完善

- `/cross` 加入 COMMAND_LIST
- `/search config` 三级补全（tag/limit/reset）
- `/cross add` 三级补全（preference/topic/question/fact）

### 七、P7 新增命令

| 命令 | 功能 |
|---|---|
| `/search config` | 设置/查看搜索默认配置（tag/limit/reset） |
| `/cross list` | 查看跨会话记忆 |
| `/cross add preference\|topic\|question\|fact <内容>` | 手动添加记忆 |
| `/cross remove topic <内容>` | 删除某条记忆 |
| `/cross clear` | 清空所有跨会话记忆 |

### 八、改动文件清单

| 文件 | 变更类型 | 说明 |
|---|---|---|
| `core/search/bm25.py` | 修改 | 归一化 + 多模式分词 + IDF 截断 + b=0.5 |
| `core/search/config.py` | **新增** | 搜索默认配置（JSON 持久化） |
| `core/memory/cross_session.py` | **新增** | 跨会话记忆（按会话名隔离） |
| `core/memory/extractor.py` | **新增** | LLM 自动提取器 |
| `core/cli/repl.py` | 修改 | 会话管理 + 启动页优化 |
| `core/cli/constants.py` | 修改 | 命令补全注册 |
