# AI 问答模块 Redesign 实施计划

> **Goal:** 将 AI 问答页改为居中窄列、可折叠右侧来源面板的现代 AI 聊天界面

**Architecture:** 通过修改 `index.html` 的 HTML 结构与 CSS，以及 `qa.js` 的渲染和交互逻辑，实现新布局。不改动后端 API。

**Tech Stack:** HTML/CSS/JS (Vanilla), FastAPI + Jinja2 模板

## 全局约束

- 保持 Python 3.9+ 兼容
- 不引入新的前端框架或依赖
- 继续使用 `?v=${staticVersion}` 绕过模块缓存
- 浏览器缓存：修改后需 Cmd+Shift+R 强制刷新

---

### Task 1: 调整 HTML 结构（index.html）

**Files:**
- Modify: `web/templates/index.html`

**Steps:**
- [ ] 隐藏 AI 问答页的 `page-header`（保留元素，通过 CSS 控制显示/高度）
- [ ] 将 `.qa-layout` 改为居中布局，主聊天区最大宽度 `760px`
- [ ] 把右侧 `.qa-sidebar` 改为可滑出的抽屉结构（默认隐藏）
- [ ] 在输入框区域添加「引用来源」常驻展开按钮
- [ ] 把推荐问题从右侧边栏移到空状态/输入框上方区域
- [ ] 为 AI 消息添加头像容器，为用户消息调整气泡结构

### Task 2: 重写 AI 问答 CSS（index.html）

**Files:**
- Modify: `web/templates/index.html`

**Steps:**
- [ ] `.qa-layout` 居中，移除固定高度，使用 flex 布局
- [ ] `.chat-area` 居中，max-width `760px`，调整消息间距
- [ ] `.msg-ai` 左侧头像 + 无气泡内容；`.msg-user` 右侧气泡
- [ ] `.msg-content` Markdown 样式：表格、列表、标题、代码块
- [ ] `.chat-input-wrapper` 悬浮底部，输入框大圆角胶囊样式
- [ ] 引用编号 `.citation` 改为药丸标签，hover 效果
- [ ] 右侧来源抽屉 `.qa-drawer`、遮罩 `.qa-drawer-overlay` 样式
- [ ] 来源卡片 `.source-card` 紧凑样式
- [ ] 空状态 `.chat-empty` 推荐问题 chips 横向布局

### Task 3: 更新交互逻辑（qa.js）

**Files:**
- Modify: `web/static/js/qa.js`

**Steps:**
- [ ] 新增 `toggleSourcesPanel(show?)` 函数控制抽屉开关
- [ ] 点击引用编号时打开抽屉并高亮对应来源卡片
- [ ] 点击输入框「引用来源」按钮切换抽屉
- [ ] 点击遮罩层关闭抽屉
- [ ] `appendMessage` 为 AI 消息添加头像 HTML
- [ ] `clearChat` 的推荐问题渲染改为 chips 横向布局
- [ ] 保留 `highlightSourceCard` 逻辑，兼容抽屉内滚动

### Task 4: 验证与测试

**Files:**
- 不涉及新文件

**Steps:**
- [ ] 重启 Web 服务
- [ ] 浏览器访问 QA 页，检查无页头、居中布局
- [ ] 发送问题，检查 AI 消息头像、用户气泡、Markdown 表格样式
- [ ] 点击引用编号，检查右侧抽屉滑出并高亮来源
- [ ] 点击「引用来源」按钮，检查抽屉开关
- [ ] 清空对话，检查空状态推荐问题布局
