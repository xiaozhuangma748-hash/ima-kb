# IMA 个人知识库 · 安装指南

> 给同事的简明安装说明。如果你是开发者，详细文档请看 `HANDOFF.md`。

---

## 🚀 一行命令安装（推荐）

```bash
git clone https://github.com/xiaozhuangma748-hash/ima-kb.git && cd ima-kb && ./install.sh
```

**就这样。** 脚本会自动完成所有事情：检查 Python → 创建虚拟环境 → 装依赖 → 配置 `ima` 命令 → 验证。

> **完整安装（含向量检索 + OCR，推荐）**：
> ```bash
> ./install.sh --vector --ocr
> ```

---

## 📋 完整流程（3 步）

### 第 1 步：克隆仓库

```bash
git clone https://github.com/xiaozhuangma748-hash/ima-kb.git
cd ima-kb
```

### 第 2 步：运行安装脚本

```bash
./install.sh                 # 标准安装
# 或
./install.sh --vector --ocr  # 完整安装（推荐：向量检索 + OCR）
```

脚本会自动做 6 件事：

| 步骤 | 做什么 | 失败怎么办 |
|---|---|---|
| 1 | 检查 Python 3.9+ | 装 Python：`brew install python@3.11` |
| 2 | 创建 `.venv` 虚拟环境 | 已存在会跳过 |
| 3 | 装依赖 + 注册 `ima` 命令 | 网络问题重试 |
| 4 | 生成 `.env` 配置文件 | 已存在会跳过 |
| 5 | 把 `ima` 命令加到 `~/.zshrc` | 新开终端生效 |
| 6 | 验证 `ima --help` 可用 | 看报错信息 |

**安装选项**：

| 选项 | 说明 |
|---|---|
| `--vector` | 安装向量检索依赖（chromadb + sentence-transformers，约 2GB） |
| `--ocr` | 安装 OCR 依赖（PaddleOCR 主 + Tesseract 降级） |
| `--dev` | 安装开发工具（pytest 等） |
| `--no-venv` | 不创建虚拟环境 |

### 第 3 步：配置 API Key

安装脚本结束后，**必须**做这一步：

```bash
vim .env
```

把这一行的 `sk-在这里填入你的key` 改成真实的 key：

```env
AGNES_API_KEY=sk-你的真实key
```

保存退出。然后**新开一个终端窗口**（让 `ima` 命令生效）。

> **Key 获取**：联系项目负责人获取 Agnes AI 的 API Key。

---

## ✅ 验证安装

```bash
ima --help          # 看到 CLI 帮助就说明装好了
ima stats           # 知识库统计
ima                 # 进入交互式 REPL
```

进入 REPL 后输入 `/pet adopt 小白` 领养宠物，然后直接输入问题即可体验 AI 问答。

---

## 🎯 开始使用

### 终端 REPL（推荐）

```bash
ima
```

进入后会看到欢迎面板。常用命令：

| 命令 | 作用 |
|---|---|
| 直接输入问题 | AI 问答（宠物管理员回答，带引用溯源） |
| `/ingest 路径` | 入库文件（PDF/Word/Excel/PPT/图片...） |
| `/agent` | AI Agent 模式（数据分析） |
| `/search 关键词` | 搜索（`/s` 是别名） |
| `/search config` | 设置搜索默认 tag/limit |
| `/cross list` | 查看跨会话记忆（AI 自动提取） |
| `/cross add topic <内容>` | 手动添加跨会话记忆 |
| `/web` | **启动 Web 后台**（后台线程，不阻塞 REPL） |
| `/web stop` | **停止 Web 后台** |
| `/se save [名称]` | 保存当前会话 |
| `/se load <名称>` | 恢复已保存的会话 |
| `/pet` | 查看宠物状态 |
| `/pet adopt <名>` | 领养宠物 |
| `/pet name <新名>` | 宠物改名 |
| `/pet style scholar` | 切换人格风格（scholar/warrior/artisan/auto） |
| `/memory` | 查看记忆（偏好/任务/工作流） |
| `/tags` | 查看所有标签 |
| `/graph stats` | 知识图谱统计 |
| `/help` | 完整帮助 |
| `/exit` | 退出 |

> **💡 命令补全**：输入 `/` 自动弹出所有命令 + 中文描述，输入 `/s` 匹配所有 s 开头命令，用 ↑↓ 选择、Tab 确认。

### 命令行单次执行

```bash
ima ingest ~/Documents/政策文件/        # 入库整个目录
ima analyze ~/Desktop/数据.xlsx          # 分析 Excel（含多 sheet）
ima search "骨灰"                        # 搜索
ima ask "退役军人抚恤金标准？"            # AI 问答（宠物管理员风格）
ima memory                              # 查看记忆
ima rebuild --vector                    # 重建索引（含向量）
ima graph build                         # 构建知识图谱
ima graph export                        # 导出 HTML 图谱可视化
```

---

## 🐾 宠物知识库管理员

IMA v4.0 的核心特色：**所有 AI 交互都通过宠物管理员进行**。

### 快速上手

```bash
ima                          # 进入 REPL
/pet adopt 小白              # 领养宠物（第一次必须做）
/pet name 大白               # 改名（随时可改）
骨灰安置有哪些政策？          # 直接问问题，宠物会回答
```

### 四种人格风格

| 风格 | 特点 | 适合场景 |
|---|---|---|
| `scholar`（学者） | 深度分析、引用密集、表格对比 | 政策对比、深度研究 |
| `warrior`（战士） | 直接结论、行动建议、简洁有力 | 快速问答、执行指导 |
| `artisan`（工匠） | 结构化、小标题、可视化 | 报告生成、流程说明 |
| `neutral`（通用） | 平衡风格、先结论后引用 | 日常问答 |

切换风格：`/pet style scholar`（或 `warrior` / `artisan` / `neutral` / `auto`）

### 宠物养成

- 每次问答宠物获得经验，最高等级 Lv10；Lv5 时分系（scholar/warrior/artisan）
- `/pet feed` 喂食、`/pet play` 玩耍、`/pet train` 训练
- 宠物状态（心情/饱食/能量）影响回答质量

### 记忆系统

- **用户偏好**：自动学习你关注的主题和地区
- **跨会话任务**：`/memory add 整理殡葬政策对比` 添加任务
- **工作流推荐**：系统会学习你的命令习惯，推荐下一步操作

---

## 🔧 可选功能

### 向量检索（推荐开启）

向量检索让搜索更智能（语义匹配，不只是关键词）。安装：

```bash
./install.sh --vector
```

> **注意**：首次使用会自动下载 embedding 模型（约 100MB）。
> 如果网络不好，可手动下载：
> ```bash
> mkdir -p storage/models/bge-small-zh-v1.5
> curl -L -o storage/models/bge-small-zh-v1.5/model.safetensors \
>   'https://hf-mirror.com/BAAI/bge-small-zh-v1.5/resolve/main/model.safetensors'
> ```
> 详见 [向量检索配置](#向量检索配置) 章节。

未安装向量检索时，系统自动降级为纯 BM25 关键词搜索，功能正常但语义理解较弱。

### OCR 支持（识别扫描版 PDF / 图片）

系统支持双 OCR 引擎，自动选择可用的：

```bash
# 方案 1：PaddleOCR（推荐，精度更高）
pip install paddlepaddle paddleocr

# 方案 2：Tesseract（降级方案）
brew install tesseract tesseract-lang
pip install pytesseract

# 或用安装脚本
./install.sh --ocr
```

装好后，入库扫描版 PDF 和图片（PNG/JPG/TIFF）会自动 OCR 识别文字。
PaddleOCR 优先使用（原图直传，内部自带预处理），不可用时降级到 Tesseract（外部预处理：灰度+二值化+放大）。

### 开发模式

```bash
./install.sh --dev    # 装 pytest 等开发工具
```

---

## ⚙️ 配置说明

### .env 文件详解

```env
# ===== LLM API（必填）=====
AGNES_API_KEY=sk-你的真实key          # Agnes AI 的 API Key
AGNES_BASE_URL=https://apihub.agnes-ai.com/v1  # API 地址（一般不用改）
LLM_MODEL=agnes-2.0-flash            # 模型名（一般不用改）

# ===== 存储 =====
STORAGE_PATH=./storage               # 数据存储目录

# ===== 分块参数（一般不用改）=====
CHUNK_SIZE=512                       # 每块最大字符数
CHUNK_OVERLAP=64                     # 块间重叠

# ===== RAG 参数 =====
RAG_TOP_K=6                          # 检索返回数量
LLM_MAX_TOKENS=1024                  # AI 回答最大长度

# ===== 图像生成 =====
IMAGE_MODEL=agnes-image-2.1-flash    # 图像生成模型
IMAGE_SIZE=1024x1024                  # 图像尺寸
IMAGE_RESPONSE_FORMAT=url             # 返回格式：url 或 base64```

### 向量检索配置

向量检索默认使用 `BAAI/bge-small-zh-v1.5` 模型（中文优化，91MB）。

**模型存放位置**：`storage/models/bge-small-zh-v1.5/`

**手动下载**（网络不好时）：
```bash
# 方法 1：用 curl 从 HF 镜像下载
mkdir -p storage/models/bge-small-zh-v1.5
cd storage/models/bge-small-zh-v1.5
curl -L -o model.safetensors 'https://hf-mirror.com/BAAI/bge-small-zh-v1.5/resolve/main/model.safetensors'
# 还需要其他配置文件：
curl -L -o config.json 'https://hf-mirror.com/BAAI/bge-small-zh-v1.5/resolve/main/config.json'
curl -L -o tokenizer.json 'https://hf-mirror.com/BAAI/bge-small-zh-v1.5/resolve/main/tokenizer.json'
curl -L -o vocab.txt 'https://hf-mirror.com/BAAI/bge-small-zh-v1.5/resolve/main/vocab.txt'
curl -L -o modules.json 'https://hf-mirror.com/BAAI/bge-small-zh-v1.5/resolve/main/modules.json'
curl -L -o sentence_bert_config.json 'https://hf-mirror.com/BAAI/bge-small-zh-v1.5/resolve/main/sentence_bert_config.json'
curl -L -o special_tokens_map.json 'https://hf-mirror.com/BAAI/bge-small-zh-v1.5/resolve/main/special_tokens_map.json'
curl -L -o tokenizer_config.json 'https://hf-mirror.com/BAAI/bge-small-zh-v1.5/resolve/main/tokenizer_config.json'
curl -L -o 1_Pooling/config.json 'https://hf-mirror.com/BAAI/bge-small-zh-v1.5/resolve/main/1_Pooling/config.json'
```

**重建向量索引**：
```bash
ima rebuild --vector
```

---

## ❓ 常见问题

### Q: 新终端里 `ima` 命令找不到？

A: 两个原因：
1. 安装后没新开终端 → `source ~/.zshrc` 立即生效
2. 用的不是 zsh → 看 `~/.zshrc` 末尾的 ima 函数，复制到你的 shell 配置

### Q: `ima` 报 "LLM 未配置"？

A: `.env` 文件里的 `AGNES_API_KEY` 没填或填错了。

```bash
cat .env    # 检查内容
vim .env    # 改成真实 key
```

### Q: 启动时提示 "向量索引初始化失败，降级为纯 BM25"？

A: 这是**正常现象**，不影响使用。原因和解决方案：

1. **没装向量依赖** → 运行 `./install.sh --vector`
2. **模型没下载完** → 参考上方的「向量检索配置」章节手动下载
3. **网络问题** → 系统会自动降级为纯 BM25 搜索，功能正常

### Q: 安装时报 Python 版本过低？

A: 项目要求 Python 3.9+。macOS 自带的 Python 可能是 3.9.6（够用），如果更低：

```bash
brew install python@3.11
./install.sh
```

### Q: 入库时跳过了图片/扫描 PDF？

A: 没装 OCR。运行（推荐 PaddleOCR）：

```bash
pip install paddlepaddle paddleocr
# 或降级方案
brew install tesseract tesseract-lang
./install.sh --ocr
```

### Q: `/session save` 提示"当前对话为空"？

A: 已修复。确保先进行至少一轮问答（直接输入问题），再保存。

### Q: 想更新到新版本？

A: 拉新代码后重装：

```bash
git pull
./install.sh
```

### Q: 想完全卸载？

A:

```bash
rm -rf .venv storage
# 从 ~/.zshrc 删除 # >>> IMA 个人知识库 >>> 到 # <<< IMA 个人知识库 <<< 之间的内容
```

---

## 📞 联系

遇到问题看 `HANDOFF.md` 的「已知问题与注意事项」章节，或联系项目负责人。

---

## 🎨 图像生成功能（v4.0 新增）

IMA 现已集成 **Agnes Image 2.1 Flash** 生图能力，可以为知识库内容自动生成配图。

### 使用方法

进入 REPL（`ima`）后使用以下命令：

| 命令 | 功能 | 示例 |
|---|---|---|
| `/pic <描述>` | 直接文生图 | `/pic 一只在竹林中散步的猫` |
| `/draw <文档ID> [--style 风格]` | 基于文档生成配图 | `/draw 862e0973 --style 水墨` |
| `/daily [--topics 主题1,主题2]` | 生成每日知识卡片 | `/daily --topics 政策,补贴` |

### 支持的图像风格

- `简洁信息图`（默认）— 适合政策文档配图
- `水墨` — 中国风水墨画风格
- `赛博` — 赛博朋克风格
- `绘本` — 儿童绘本风格
- `极简卡片` — 适合知识卡片

### 配置

`.env` 文件中已包含生图配置：

```env
IMAGE_MODEL=agnes-image-2.1-flash
IMAGE_SIZE=1024x1024
IMAGE_RESPONSE_FORMAT=url
```

> **注意**：生图使用与 LLM 相同的 `AGNES_API_KEY`，无需额外配置。

### 使用场景

1. **问答配图**：生图后可配合 `/pic` 为知识内容添加可视化
2. **文档插图**：为入库的文档自动生成主题配图
3. **知识卡片**：每日回顾时生成可分享的摘要卡片
4. **汇报材料**：基于文档内容生成配图，辅助制作汇报 PPT
