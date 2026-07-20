# IMA-KB 桌面宠物（独立版）

参照 [clawd-on-desk](https://github.com/rullerzhou-afk/clawd-on-desk) 的 Electron 架构，用 Python 知识库配套的像素猫 GIF 实现的桌面宠物。**完全独立于知识库代码**，验证无误后再对接。

## 快速启动

**方式一（推荐，真机双击）**：双击 `启动桌面宠物.command`
（如遇"无法打开"，右键 → 打开 → 打开）

**方式二（命令行）**：
```bash
cd desktop-pet
npm start          # 或：env -u NODE_OPTIONS -u ELECTRON_RUN_AS_NODE ./node_modules/.bin/electron .
```

## 功能

| 功能 | 说明 |
|---|---|
| 12 状态动画 | idle/listening/thinking/retrieving/ranking/answering/celebrating/error/sleeping/ingesting/analyzing/notifying |
| 透明置顶窗体 | 无边框、始终置顶、所有工作区可见 |
| 拖拽移动 | 按住宠物拖动，松手记住位置 |
| 位置记忆 | 重启后恢复上次位置（`~/Library/Application Support/ima-kb-desktop-pet/desktop-pet-settings.json`） |
| 闲置睡眠 | 5 分钟无键鼠操作 → 自动 sleeping；活动后唤醒回 idle |
| 托盘菜单 | 菜单栏图标：手动切任意状态 / 免打扰 / 开机自启 / 退出 |
| 免打扰 | 锁定 sleeping，不被自动唤醒 |
| 开机自启 | 托盘勾选后生效 |

## 状态机

- 常驻态：`idle`（默认）、`sleeping`
- 工作态（对应知识库 RAG 流水线）：`listening → thinking → retrieving → ranking → answering`
- 事件态：`celebrating`/`error`/`notifying` 播 2-2.5s 后自动回 idle；`ingesting`/`analyzing` 由外部控制
- 优先级：手动切换 > 外部事件 > 自动（闲置/唤醒）

## 对接知识库（预留，未启用）

`src/state_machine.js` 暴露 `transition(state, source)`；`main.js` 已注册 IPC `external-event`。
未来知识库 `PetAdministrator` 只需在检索/重排/回答等节点发事件即可驱动宠物切换状态，无需改宠物代码。

## 项目结构

```
desktop-pet/
├── main.js                  # 主进程：窗体+托盘+闲置检测+IPC
├── preload.js               # 安全桥
├── renderer/
│   ├── index.html           # 透明窗体 + GIF
│   └── renderer.js          # 拖拽 + 状态切换
├── src/
│   ├── state_machine.js     # 12 状态状态机
│   └── settings.js          # 配置持久化（防抖+原子写入）
├── assets/                  # 12 个像素猫 GIF（复制自 cat-agent-showcase）
├── 启动桌面宠物.command      # macOS 双击启动器
└── package.json
```

## 打包成 .app（可选）

```bash
npm run dist   # electron-builder，需先 npm i -D electron-builder
```

## 依赖

- Node.js（开发用 22.x）
- Electron ^33（`npm install` 自动安装；国内慢可设 `ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/`）
