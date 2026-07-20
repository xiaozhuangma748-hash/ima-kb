# IMA-KB 桌面宠物

基于 pywebview + pystray 的桌面宠物，与知识库原生打通：对话检索、拖拽入库、CLI 状态联动。

## 架构

```
┌─────────────────────────────────────────────────┐
│  主进程 (core/desktop/app.py)                    │
│  ┌───────────┐  ┌──────────┐  ┌──────────────┐ │
│  │ pywebview │  │ IPC Server│  │ DesktopBridge│ │
│  │ (WKWebView)│  │ (Unix sock)│  │ (JS Bridge) │ │
│  └─────┬─────┘  └─────┬────┘  └──────┬───────┘ │
│        │               │              │         │
│  ┌─────┴─────┐  ┌─────┴────┐  ┌─────┴───────┐ │
│  │  pet.js   │  │ CLI/Tray │  │ PetAdmin     │ │
│  │ (GIF/UI)  │  │ (IPC客户端)│  │ (RAG流水线) │ │
│  └───────────┘  └──────────┘  └─────────────┘ │
└─────────────────────────────────────────────────┘
         ↕ subprocess              ↕ IPC
┌─────────────────┐    ┌──────────────────┐
│ 托盘子进程       │    │ CLI (ima-pet)    │
│ (tray_runner.py)│    │ (cli_sync.py)    │
│ pystray + AppKit│    │ state/ask/ingest │
└─────────────────┘    └──────────────────┘
```

## 快速启动

```bash
# 方式一：双击启动（macOS）
# 双击 启动桌面宠物.command

# 方式二：命令行
./ima-desktop

# 方式三：Python 模块
./.venv/bin/python -m core.desktop.app
```

## 功能

### 1. 对话检索（双击宠物 → 输入问题）
- 双击宠物 → 弹出输入框 → 输入问题
- 状态联动：listening → thinking → retrieving → ranking → answering → celebrating
- 流式输出：token 逐字推送
- 引用溯源：答案末尾显示来源文档

### 2. 拖拽入库（拖文件到宠物）
- 拖拽文件到宠物 → 弹出确认提示 → 确认后入库
- 状态联动：ingesting → analyzing → celebrating
- 入库结果：气泡提示"已入库"或"已存在"

### 3. 托盘菜单（菜单栏猫爪图标）
- 切换状态：12 个 GIF 状态手动切换
- 切换人格：scholar / warrior / artisan / neutral / auto
- 勿扰模式 / 音效开关 / 尺寸切换
- 显示统计 / 退出

### 4. CLI 状态联动
```bash
# 检查桌宠是否运行
./ima-pet status

# 手动切换状态
./ima-pet state thinking

# 带状态联动的问答（替代 ima ask）
./ima-pet ask "什么是殡葬改革"

# 带状态联动的入库（替代 ima ingest）
./ima-pet ingest /path/to/file.pdf
```

### 5. IPC 通信
- Socket: `/tmp/ima-desktop-pet.sock`
- 协议: JSON over Unix domain socket
- 支持: set_state / get_pet_info / get_stats / show_bubble / switch_style / ping

## 12 个宠物状态

| 状态 | GIF | 触发场景 |
|------|-----|---------|
| idle | idle.gif | 默认待机 |
| listening | listening.gif | 用户输入问题 |
| thinking | thinking.gif | 开始处理 |
| retrieving | retrieving.gif | BM25/向量检索 |
| ranking | ranking.gif | LLM 重排 |
| answering | answering.gif | 生成回答 |
| celebrating | celebrating.gif | 任务完成 |
| error | error.gif | 出错 |
| sleeping | sleeping.gif | 闲置待机 |
| ingesting | ingesting.gif | 文件入库 |
| analyzing | analyzing.gif | 分析/分块 |
| notifying | notifying.gif | 通知提醒 |

## 文件结构

```
core/desktop/
├── app.py              # 主入口
├── bridge.py           # Python↔JS 桥接
├── window.py           # 窗口配置
├── tray.py             # 托盘管理
├── tray_runner.py      # 独立托盘进程（macOS）
├── ipc.py              # IPC 通信（Unix socket）
├── cli_sync.py         # CLI 状态联动
├── states.py           # PetState 枚举
├── renderer.py         # AsciiArtLoader
├── pet_wrapper.py      # DesktopPetAdministrator
├── ingest_helper.py    # 入库助手
├── mobile_server.py    # Mobile 同步（可选）
├── settings.py         # 配置持久化
└── static/
    ├── index.html      # 宠物 UI
    ├── pet.js          # 前端逻辑
    └── *.gif           # 12 个状态动画

根目录:
├── ima-desktop             # 启动脚本
├── ima-pet                 # CLI 状态联动脚本
├── 启动桌面宠物.command     # macOS 双击启动
├── requirements-desktop.txt # 桌宠依赖
└── install-desktop.sh      # 安装脚本
```

## 零侵入保证

- `core/desktop/` 为独立新增模块，不修改项目任何现有文件
- 删除 `core/desktop/` + 根目录 `ima-desktop` / `ima-pet` / `requirements-desktop.txt` / `install-desktop.sh` 即可完全回退
- 知识库原有代码（`run.py` / `core/pet/` / `core/retrieval/` / `web/` 等）零改动
