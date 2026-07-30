# 安全与性能修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复项目审查发现的安全漏洞、崩溃 bug 和性能瓶颈,不影响搜索准确度。

**Architecture:** 分两波执行 — 第一波为零风险修复(安全+崩溃),第二波为低风险性能优化。所有改动不触及检索/分块/rerank 算法逻辑。

**Tech Stack:** Python 3.9+, FastAPI, SQLite, threading

---

## 第一波:零风险修复(安全 + 崩溃 bug)

### Task 1: 修复文件上传路径遍历漏洞 (S1)

**Files:**
- Modify: `web/routes/ingest.py:32-53`

- [x] **Step 1: 修复 filename 路径遍历**

将 `original_name` 直接拼接改为取纯文件名,拒绝含路径分隔符的 filename。

### Task 2: 修复 IPC Socket 权限 (S2)

**Files:**
- Modify: `core/desktop/ipc.py:55-56`

- [x] **Step 1: bind 后立即 chmod 0o600**

### Task 3: 修复 Mobile Server 监听地址 (S3)

**Files:**
- Modify: `core/desktop/mobile_server.py:75,80`

- [x] **Step 1: 0.0.0.0 改 127.0.0.1**

### Task 4: 修复 search.py 类型不兼容崩溃 (B1)

**Files:**
- Modify: `web/routes/search.py:66`

- [x] **Step 1: 标签筛选兼容 HybridResult 对象**

### Task 5: 修复 parser.py 临时文件 NameError (B2)

**Files:**
- Modify: `core/ingestion/parser.py:419-426`

- [x] **Step 1: tmp_path 初始化为 None,finally 中守卫**

### Task 6: 修复 electron_bridge stdout 协议混乱 (B3)

**Files:**
- Modify: `core/desktop/electron_bridge.py` — 日志改为强制 stderr

- [x] **Step 1: basicConfig 改为 stream=sys.stderr**

---

## 第二波:低风险性能优化

### Task 7: HybridRetriever/SemanticCache 共享单例 (P1)

**Files:**
- Modify: `web/app.py` — 新增 `_get_shared_hybrid_retriever`
- Modify: `web/routes/search.py:41` — 改用共享实例
- Modify: `services/qa_service.py` — 改用共享实例(通过 app.state 注入)

- [x] **Step 1: app.py 新增 hybrid_retriever 共享单例**
- [x] **Step 2: search.py 和 qa_service.py 改用共享实例**

### Task 8: search.py N+1 改批量查询 (P2)

**Files:**
- Modify: `web/routes/search.py:96-123`
- Modify: `core/storage.py` — 新增 `get_first_chunks_batch` 方法

- [x] **Step 1: storage.py 新增批量查询方法**
- [x] **Step 2: search.py 改用批量查询**

### Task 9: Pet 对象加 threading.Lock

**Files:**
- Modify: `core/pet/pet.py`

- [x] **Step 1: Pet 加 _lock,所有写操作加锁**

### Task 10: LLM 单例加锁

**Files:**
- Modify: `core/llm/client.py:152-160`

- [x] **Step 1: get_llm 加 threading.Lock**

### Task 11: 修复 9 个失效测试

**Files:**
- Modify: `tests/test_subcommand_menu.py` — 5 个 rotten tests
- Modify: `tests/test_repl_aliases.py` — 3 个 e2e 测试状态隔离
- Modify: `tests/test_context_engine.py` — 边界断言

- [x] **Step 1: 修复 test_context_engine.py 边界断言**
- [x] **Step 2: 修复 test_subcommand_menu.py rotten tests**
- [x] **Step 3: 修复 test_repl_aliases.py 状态隔离**

### Task 12: 运行全量测试验证回归

- [x] **Step 1: 运行 pytest 验证所有改动**

结果：727 passed, 0 failed（修复前 9 failed → 全绿）
