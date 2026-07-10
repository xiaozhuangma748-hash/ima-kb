# IMA Web 后台 · 设计文档

> 版本: v1.0
> 日期: 2026-07-08
> 状态: 已评审

---

## 1. 概述

基于现有 IMA 知识库 core/ 模块，用 **FastAPI + 单页 HTML** 构建 Web 后台，覆盖 7 个页面，面向 1-5 人内网用户。

**为什么不用 Streamlit**：UI 定制受限、流式输出体验差、并发模型弱、原型图还原成本高。

---

## 2. 技术栈

| 层 | 选型 | 说明 |
|---|---|---|
| Web 框架 | FastAPI | 异步、SSE 原生支持、自动 API 文档 |
| 模板 | Jinja2 (FastAPI 内置) | 渲染单页 HTML |
| 前端 | 原生 HTML/CSS/JS + vis.js CDN | 零构建工具 |
| 异步 | uvicorn | FastAPI 默认 ASGI 服务器 |
| 后端复用 | core/ 全部模块 | 零改动 |

新增 Python 依赖: `fastapi`, `uvicorn`, `python-multipart`（文件上传）

---

## 3. 目录结构

```
web/
├── __init__.py
├── app.py                  # FastAPI 应用工厂 + 路由注册
├── routes/
│   ├── __init__.py
│   ├── qa.py               # /api/qa/stream SSE 流式问答
│   ├── ingest.py           # /api/ingest 文件上传/URL（剪贴板端点未实现）
│   ├── search.py           # /api/search 混合检索
│   ├── analyze.py          # /api/analyze 数据分析 + /api/analyze/export 导出
│   ├── stats.py            # /api/stats 仪表盘
│   ├── graph.py            # /api/graph 知识图谱
│   └── pet.py              # /api/pet 宠物管理
├── templates/
│   └── index.html          # 单页 HTML（复用原型图 CSS + 新增 JS）
└── static/
    ├── app.js              # 重定向入口（仅 `import './js/app.js'`）
    └── js/                 # 11 个 ES Module
        ├── app.js          # 入口聚合（DOMContentLoaded 时初始化各模块）
        ├── nav.js          # 页面切换 + 人格/开关控件
        ├── qa.js           # SSE 流式问答 + 引用面板 + 侧边栏折叠
        ├── ingest.js       # 文件拖拽 + URL 入库 + Tab 切换
        ├── search.js       # 顶栏搜索 + 搜索页 + 关键词高亮
        ├── analyze.js      # Excel 上传 + 统计渲染 + AI 解读
        ├── dashboard.js    # 仪表盘数据加载
        ├── graph.js        # vis.js Network + 邻居查询
        ├── pet.js          # 宠物状态展示 + 交互按钮
        ├── state.js        # 全局状态（abortController/chatHistory/graphNetwork/activeSourceCard）
        └── utils.js        # 公共工具（escapeHtml/formatSize/showError）
```

---

## 4. API 规格

### 4.1 全局页面

```
GET /           → 返回 index.html（Jinja2 渲染）
                  Template 中注入初始数据: 统计数字、标签列表、图谱节点数
```

### 4.2 AI 问答

```
POST /api/qa/stream
  Body: JSON {question: string (required), history: array, persona: string ("auto"|"scholar"|"warrior"|"artisan", default "auto")}
  Response: text/event-stream

  SSE 事件格式: data-only（无 event: 行），每条 `data: {JSON}\n\n`，JSON 内 type 字段区分类型:
    stage  → {type: "stage", stage: "检索"|"生成", count: int}    检索阶段进度提示
    token  → {type: "token", text: "..."}                         逐字输出
    done   → {type: "done", answer: "...", citations: [{marker, title, paragraph_num, doc_id}],
              sources: [{doc_id, doc_title, score}], pet_events: [...]}   完整载荷结束标记
    error  → {type: "error", message: "..."}                      错误信息
```

### 4.3 文档入库

```
POST /api/ingest/upload
  Body: multipart/form-data, files[] (多文件)
  Response: {
    results: [{filename, status: "success"|"failed", doc_id?, tags[], chunks, error?}, ...]
  }

POST /api/ingest/url
  Body: JSON {url: string}
  Response: {status, doc_id, title, tags, chunks}

POST /api/ingest/clip   (注：未实现，前端 UI 已就位但无后端端点)
  Body: multipart/form-data, content (text or image)
  Response: {status, doc_id, title}  (规划中复用 core/ingestion/quick.py)
```

### 4.4 搜索

```
GET /api/search
  Query: q (string), tags (逗号分隔字符串, optional), use_vector (bool, default true), use_rerank (bool, default true),
         sort (string, "score"|"date"|"name"), limit (int, default 10)
  Response: {
    results: [{doc_id, doc_title, snippet, content, score, tags[], file_type, created_at}, ...],
    total: int,
    time_ms: float
  }
  注: 无 highlights[] 字段，关键词高亮由前端 search.js 正则实现（<mark> 标签包裹）
```

### 4.5 数据分析

```
POST /api/analyze
  Body: multipart/form-data, file (Excel/CSV/TSV/JSON)
  Query: sheet (string, optional), ai_insight (bool, default false)
  Response: {
    filename, sheets[],
    current_sheet: {
      columns: [{name, dtype, null_count, unique_count, min, max, mean, top_values[]}, ...],
      preview_rows: [...],
      ai_insight?: string    (仅 ai_insight=true 时)
    }
  }
  注: 无 ascii_chart 字段（未实现）

GET /api/analyze/export
  Query: key (string, required — POST analyze 返回的缓存 key)
  Response: application/octet-stream (Markdown 报告下载)
```

### 4.6 仪表盘

```
GET /api/stats
  Response: {
    documents: int, chunks: int, total_tokens: int, total_size_mb: float,
    tags_count: int, graph_nodes: int, graph_edges: int,
    by_type: {pdf: int, docx: int, ...},
    top_tags: [{name, count}, ...],
    alerts: [{severity, message, doc_id?}, ...],
    recent_docs: [{title, file_type, tags, chunk_count, created_at, doc_id}, ...],
    health_score: int
}
```

### 4.7 知识图谱

```
GET /api/graph/data
  Response: {
    elements: {
      nodes: [{data: {id, label, type, color, doc_count, degree}}],   # cytoscape 格式
      edges: [{data: {id, source, target, relation, label}}]
    },
    stats: {nodes, edges, by_type}
  }

GET /api/graph/neighbors/{name}    # name 为节点名称（支持模糊搜索）
  Response: {
    found: true,
    node: {label, type, doc_count, degree},
    neighbors: [{node, type, relation_label}, ...]
  }
  若未精确匹配:
  Response: {found: false, matches: [{label, ...}], hint: string}

POST /api/graph/build
  Body: JSON {force: bool}
  Response: {status, stats: {nodes, edges}}

GET /api/graph/export
  Response: text/html (自包含 vis.js HTML)
```

### 4.8 宠物管理

```
GET /api/pet/status
  Response: {found: bool, name, level, exp, exp_needed, branch, style, hunger, mood, energy, cleanliness, ascii_art, message}
  注: 不返回 intellect 字段（前端 pet.js 仍引用 data.intellect，存在 bug）

POST /api/pet/interact
  Body: JSON {action: "feed"|"play"|"train"|"sleep"|"wash"}
  Response: {pet: {...}, message: string}

POST /api/pet/style
  Body: JSON {style: "scholar"|"warrior"|"artisan"|"auto"}
  Response: {pet: {...}, message: string}

POST /api/pet/adopt
  Body: JSON {name: string}
  Response: {pet: {...}, ascii_art: string, message: string}
```

---

## 5. CLI 入口

在 `run.py` 新增:

```python
@cli.command(name="web")
@click.option("--host", default="0.0.0.0", help="绑定地址")
@click.option("--port", default=8501, help="端口")
def cli_web(host: str, port: int):
    """启动 Web 后台（内网访问：ima web --host 0.0.0.0）"""
    import uvicorn
    from web.app import create_app
    app = create_app()
    uvicorn.run(app, host=host, port=port)
```

---

## 6. 前端 JS 模块

`static/app.js` 仅作重定向入口（`import './js/app.js'`），实际逻辑拆分到 `static/js/` 下 11 个 ES Module:

```
模块划分:
├── app.js           入口聚合（DOMContentLoaded 时初始化各模块，默认加载仪表盘）
├── nav.js           页面切换 + 人格/开关控件 + 切换 QA 页时取消 SSE
├── qa.js            POST SSE 流式接收 + 消息气泡渲染 + 引用面板动态填充 + 侧边栏折叠 + 多轮历史管理
├── ingest.js        文件拖拽/选择 + FormData 上传 + URL 入库 + Tab 切换
├── search.js        顶栏搜索 + 搜索页 + 关键词正则高亮 + "/" 快捷键
├── analyze.js       文件上传 + 统计渲染 + AI 解读（未接入导出）
├── dashboard.js     fetch stats 填充指标卡 + 标签分布柱状图
├── graph.js         vis.js Network 初始化 + 点击节点邻居查询 + 重建图谱
├── pet.js           状态展示 + 交互按钮（仅 feed/play/train 3 个）+ 人格切换
├── state.js         全局状态（abortController: SSE 取消 / chatHistory: 多轮对话历史 / graphNetwork / activeSourceCard: 引用高亮）
└── utils.js         公共工具（escapeHtml / formatSize / showError）
```

---

## 7. 部署

```bash
# 安装依赖
pip install fastapi uvicorn python-multipart

# 启动（内网可访问）
ima web --host 0.0.0.0 --port 8501

# 后台运行
nohup ima web --host 0.0.0.0 &

# 访问
http://<内网IP>:8501
```

---

## 8. 开发优先级

| 阶段 | 内容 | 预估 |
|---|---|---|
| M1 | `web/app.py` + `routes/qa.py` + SSE + 前端问答页 | 2h |
| M2 | `routes/ingest.py` + `routes/search.py` + 前端入库/搜索页 | 1.5h |
| M3 | `routes/analyze.py` + `routes/stats.py` + 前端分析/仪表盘页 | 1.5h |
| M4 | `routes/graph.py` + `routes/pet.py` + vis.js + 前端图谱/宠物页 | 2h |
| 集成 | `run.py` web 命令 + uvicorn + 依赖更新 | 0.5h |

**总计**: 约 7.5 小时

---

## 9. 自检清单

- [ ] 无外部占位符/TODO
- [ ] API 入参出参定义完整
- [ ] 与现有 core/ 模块接口兼容
- [ ] 原型图 CSS 可完整复用
- [ ] 7 页面 + 1 全局路由, 无遗漏
- [ ] 流式问答使用 SSE, 非轮询
