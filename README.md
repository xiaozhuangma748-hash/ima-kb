# IMA 个人知识库

> 面向殡葬政策研究领域的个人 RAG 知识库，集成宠物管理员、Agentic RAG、桌面宠物、Web 后台、知识图谱等多种能力。

## 核心特性

- **多模态入库**：PDF / Word / Excel / PPT / 图片 / Markdown，支持 OCR（PaddleOCR + Tesseract 双引擎降级）
- **混合检索**：BM25 关键词 + 向量语义（bge-small-zh-v1.5）+ Cross-Encoder 重排 + 语义缓存
- **Agentic RAG**：Agent 模式主动调工具（search / read / analyze / list_docs），带自我验证与引用校验
- **宠物管理员**：所有 AI 交互通过宠物进行，4 种人格风格（scholar / warrior / artisan / neutral），养成系统（Lv10 + 心情/饱食/能量）
- **桌面宠物**：Electron 透明窗体 + 12 状态动画 + 拖拽入库 + 气泡问答 + 托盘菜单
- **Web 后台**：FastAPI + 原生前端，支持 SSE 流式问答、文档管理、知识图谱可视化
- **记忆系统**：跨会话记忆自动提取、用户偏好学习、工作流推荐
- **知识图谱**：自动抽取实体关系，导出 HTML 可视化

## 快速开始

```bash
git clone https://github.com/xiaozhuangma748-hash/ima-kb.git
cd ima-kb
./bin/install.sh          # 标准安装（默认含向量检索）
# 或
./bin/install.sh --ocr    # 完整安装（向量检索 + OCR）
```

安装完成后编辑 `.env` 填入 API Key，然后：

```bash
ima                       # 进入交互式 REPL
```

第一次使用先领养宠物：`/pet adopt 小白`，然后直接输入问题即可。

详细安装说明见 [INSTALL.md](INSTALL.md)。

## 使用方式

### 终端 REPL（推荐）

```bash
ima                       # 进入 REPL
```

常用命令：

| 命令 | 作用 |
|---|---|
| 直接输入问题 | AI 问答（宠物管理员风格 + 引用溯源） |
| `/ingest 路径` | 入库文件或目录 |
| `/agent 问题` | AI Agent 模式（主动调工具） |
| `/search 关键词` | 搜索（`/s` 是别名） |
| `/pic 描述` | 文生图 |
| `/draw 文档ID` | 基于文档生成配图 |
| `/web` | 启动 Web 后台 |
| `/pet` | 查看宠物状态 |
| `/memory` | 查看记忆 |
| `/graph stats` | 知识图谱统计 |
| `/help` | 完整帮助 |

### 命令行单次执行

```bash
ima ingest ~/Documents/政策文件/        # 入库整个目录
ima analyze ~/Desktop/数据.xlsx          # 分析 Excel
ima search "骨灰"                        # 搜索
ima ask "退役军人抚恤金标准？"            # AI 问答
ima web                                 # 启动 Web 后台
```

### 桌面宠物

```bash
./bin/ima-desktop                        # 启动 Electron 桌面宠物
# 或双击 bin/启动桌面宠物.command
```

详见 [desktop-pet/README.md](desktop-pet/README.md)。

## 项目结构

```
.
├── bin/                    # 安装与启动脚本
│   ├── install.sh          # 一键安装
│   ├── ima-desktop         # 桌面宠物启动器
│   └── ima-command.zsh     # ima 命令注册
├── core/                   # 核心代码
│   ├── agent/              # Agent 模式（工具注册 + 流式输出）
│   ├── analyze/            # 数据表分析
│   ├── classify/           # 文档标签
│   ├── cli/                # CLI 与 REPL
│   ├── desktop/            # 桌面宠物后端（Electron bridge / IPC / pywebview）
│   ├── graph/              # 知识图谱
│   ├── image/              # 图像生成
│   ├── ingestion/          # 文档解析 + 分块 + Contextual Retrieval
│   ├── llm/                # LLM 客户端 + 降级策略
│   ├── memory/             # 记忆系统（跨会话 / 偏好 / 任务）
│   ├── persona/            # 宠物人格风格
│   ├── pet/                # 宠物养成与管理员
│   ├── qa/                 # RAG 问答链（含 Agentic RAG / 自验证 / 引用校验）
│   ├── reader/             # 文档阅读器
│   ├── report/             # 报告生成
│   ├── retrieval/          # 混合检索 + 重排 + 缓存
│   ├── search/             # BM25 索引
│   ├── session/            # 会话持久化
│   ├── sync/               # 文件夹监控同步
│   ├── todo/               # 待办管理
│   └── ui/                 # 终端主题
├── desktop-pet/            # Electron 桌面宠物（main + renderer + assets）
├── docs/                   # 文档与设计规格
├── services/               # 业务服务层
├── tests/                  # 测试套件
├── web/                    # Web 后台（FastAPI + 前端）
├── config.py               # 配置入口
├── run.py                  # CLI 主入口
└── pyproject.toml          # 项目元数据
```

## 技术栈

- **Python 3.9+**：核心运行时
- **LLM**：Agnes AI / DeepSeek（OpenAI 兼容 API）
- **向量检索**：chromadb + sentence-transformers (bge-small-zh-v1.5)
- **重排**：Cross-Encoder
- **OCR**：PaddleOCR（主）+ Tesseract（降级）
- **桌面宠物**：Electron 33+ / Node.js 18+
- **Web 后台**：FastAPI + Uvicorn
- **CLI**：Click + Rich

## 配置

通过 `.env` 文件配置（安装脚本自动生成模板）。主要项：

```env
AGNES_API_KEY=sk-xxx       # LLM API Key（必填）
AGNES_BASE_URL=https://apihub.agnes-ai.com/v1
LLM_MODEL=agnes-2.5-flash

IMAGE_API_KEY=sk-xxx       # 图像 API Key（未填则回退到 AGNES_API_KEY）
IMAGE_MODEL=agnes-image-2.1-flash

STORAGE_PATH=./storage     # 数据存储目录
RAG_TOP_K=6                # 检索返回数量
```

完整配置说明见 [INSTALL.md](INSTALL.md#-配置说明)。

## 文档

- [INSTALL.md](INSTALL.md) — 安装与使用指南
- [desktop-pet/README.md](desktop-pet/README.md) — 桌面宠物说明
- [docs/DESKTOP_PET.md](docs/DESKTOP_PET.md) — 桌面宠物设计文档
- [docs/PRD-web-backend.md](docs/PRD-web-backend.md) — Web 后台 PRD
- [docs/specs/](docs/specs/) — 设计规格
- [docs/superpowers/](docs/superpowers/) — 实施计划与设计文档

## 许可

内部项目，未发布开源许可。
