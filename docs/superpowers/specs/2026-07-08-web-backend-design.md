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
│   ├── ingest.py           # /api/ingest 文件上传/URL/剪贴板
│   ├── search.py           # /api/search 混合检索
│   ├── analyze.py          # /api/analyze 数据分析
│   ├── stats.py            # /api/stats 仪表盘
│   ├── graph.py            # /api/graph 知识图谱
│   └── pet.py              # /api/pet 宠物管理
├── templates/
│   └── index.html          # 单页 HTML（复用原型图 CSS + 新增 JS）
└── static/
    └── app.js              # 前端交互 JS
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
GET /api/qa/stream
  Query: q (string, required), persona (string, "auto"|"scholar"|"warrior"|"artisan", default "auto")
  Response: text/event-stream

  SSE event 类型:
    token    → {text: "..."}             逐字输出
    citation → {marker: "[1]", title: "...", snippet: "...", score: 0.96}
    done     → {}                        结束标记
    error    → {message: "..."}          错误信息
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

POST /api/ingest/clip
  Body: multipart/form-data, content (text or image)
  Response: {status, doc_id, title}  (复用 core/ingestion/quick.py)
```

### 4.4 搜索

```
GET /api/search
  Query: q (string), tags[] (array, optional), vector (bool, default true), rerank (bool, default true),
         sort (string, "score"|"date"|"name"), limit (int, default 10)
  Response: {
    results: [{doc_title, snippet, highlights[], score, tags[], file_type, created_at, doc_id}, ...],
    total: int,
    time_ms: float
  }
```

### 4.5 数据分析

```
POST /api/analyze
  Body: multipart/form-data, file (Excel/CSV/TSV/JSON)
  Query: sheet (string, optional), ai_insight (bool, default false)
  Response: {
    filename, sheets[],
    current_sheet: {
      columns: [{name, dtype, null_count, unique_count, min, max, mean, top_values[], ascii_chart?}, ...],
      preview_rows: [...],
      ai_insight?: string    (仅 ai_insight=true 时)
    }
  }

GET /api/analyze/export
  Query: same as POST analyze params (cached session)
  Response: application/octet-stream (Markdown 报告下载)
```

### 4.6 仪表盘

```
GET /api/stats
  Response: {
    documents: int, chunks: int, tags: int, graph_nodes: int,
    by_type: {pdf: int, docx: int, ...},
    top_tags: [{name, count}, ...],
    alerts: [{severity, message, doc_id?}, ...],
    recent_docs: [{title, file_type, tags, chunks, created_at}, ...],
    health_score: int
  }
```

### 4.7 知识图谱

```
GET /api/graph/data
  Response: {
    elements: {nodes: [{id, label, type, doc_count, degree}], edges: [{source, target, label}]},
    stats: {nodes, edges, by_type}
  }

GET /api/graph/neighbors/{node_id}
  Response: {node: {...}, neighbors: [{node, type, relation_label}, ...]}

POST /api/graph/build
  Body: JSON {force: bool}
  Response: {status, stats: {nodes, edges}}

GET /api/graph/export
  Response: text/html (自包含 vis.js HTML)
```

### 4.8 宠物管理

```
GET /api/pet/status
  Response: {name, level, xp, xp_next, style, mood, hunger, energy, cleanliness, intellect}

POST /api/pet/interact
  Body: JSON {action: "feed"|"play"|"train"}
  Response: {pet: {...}, message: string}

POST /api/pet/style
  Body: JSON {style: "scholar"|"warrior"|"artisan"|"auto"}
  Response: {pet: {...}, message: string}

POST /api/pet/adopt
  Body: JSON {name: string}
  Response: {pet: {...}, ascii_art: string}
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

新增 `static/app.js`，约 200 行：

```
模块划分:
├── Navigation       页面切换 + 面包屑
├── QAController     SSE 流式接收 + 消息气泡渲染 + 引用面板更新
├── IngestController  文件拖拽/选择 + FormData 上传 + 进度列表
├── SearchController  API 搜索 + 结果渲染 + 标签筛选
├── AnalyzeController 文件上传 + Sheet 切换 + AI 解读
├── Dashboard         fetch stats 填充指标卡
├── GraphController   vis.js Network 初始化 + 邻居查询
├── PetController     状态展示 + 交互按钮
└── Toggle            开关组件
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
