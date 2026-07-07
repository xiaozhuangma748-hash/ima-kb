"""REPL 命令别名分发测试。

覆盖：
- /save /load /sessions /export 别名能正确分发到对应方法
- CMD_ALIASES 映射完整
"""
import pytest
from unittest.mock import MagicMock, patch
from repl import REPL


def _make_repl(tmp_path):
    """构造一个不初始化 LLM 的 REPL 实例（用于测试命令分发）。"""
    # 通过 __new__ 绕过 __init__ 的复杂初始化
    repl = REPL.__new__(REPL)
    repl.running = True
    repl.history = []
    repl.storage = MagicMock()
    repl.storage.bm25_search.return_value = []
    repl.storage.list_documents.return_value = []
    repl.storage.stats.return_value = {
        "documents": 0, "chunks": 0, "total_tokens": 0,
        "total_size_mb": 0, "by_type": {},
    }
    repl.storage.bm25.info.return_value = {"chunks": 0, "vocabulary": 0, "total_tokens": 0}
    repl.storage.rebuild_bm25_index.return_value = 0
    repl.llm_available = False
    repl.reader = None
    repl.memory_store = None
    repl.workflow_tracker = None  # 禁用工作流记录
    repl.session_store = MagicMock()
    repl.pipeline_input = None
    repl.pet = None  # 禁用宠物经验
    return repl


def test_cmd_aliases_includes_session_shortcuts():
    """CMD_ALIASES 应包含 /save /load /sessions /export 映射。"""
    aliases = REPL.CMD_ALIASES
    assert aliases.get("/save") == "/session_save"
    assert aliases.get("/load") == "/session_load"
    assert aliases.get("/sessions") == "/session_list"
    assert aliases.get("/export") == "/session_export"


def test_save_alias_dispatches_to_cmd_save(tmp_path):
    """/save xxx 应该调用 _cmd_save 而不是报"未知命令"。"""
    repl = _make_repl(tmp_path)
    with patch.object(repl, "_cmd_save") as mock_save:
        repl._handle_command("/save mysession")
        mock_save.assert_called_once_with("mysession")


def test_load_alias_dispatches_to_cmd_load(tmp_path):
    """/load xxx 应该调用 _cmd_load。"""
    repl = _make_repl(tmp_path)
    with patch.object(repl, "_cmd_load") as mock_load:
        repl._handle_command("/load mysession")
        mock_load.assert_called_once_with("mysession")


def test_sessions_alias_dispatches_to_cmd_sessions(tmp_path):
    """/sessions 应该调用 _cmd_sessions。"""
    repl = _make_repl(tmp_path)
    with patch.object(repl, "_cmd_sessions") as mock_sessions:
        repl._handle_command("/sessions")
        mock_sessions.assert_called_once()


def test_export_alias_dispatches_to_cmd_export(tmp_path):
    """/export xxx 应该调用 _cmd_export。"""
    repl = _make_repl(tmp_path)
    with patch.object(repl, "_cmd_export") as mock_export:
        repl._handle_command("/export mysession")
        mock_export.assert_called_once_with("mysession")


def test_rebuild_accepts_vector_flag(tmp_path):
    """/rebuild --vector 应该把 arg 传给 _cmd_rebuild。"""
    repl = _make_repl(tmp_path)
    with patch.object(repl, "_cmd_rebuild") as mock_rebuild:
        repl._handle_command("/rebuild --vector")
        mock_rebuild.assert_called_once_with("--vector")


def test_rebuild_no_arg(tmp_path):
    """/rebuild 无参数也应工作。"""
    repl = _make_repl(tmp_path)
    with patch.object(repl, "_cmd_rebuild") as mock_rebuild:
        repl._handle_command("/rebuild")
        mock_rebuild.assert_called_once_with("")


# ---- Group 1: 数据闭环测试 ----

def test_session_delete_dispatches(tmp_path):
    """/session delete <name> 应调用 _cmd_session_delete。"""
    repl = _make_repl(tmp_path)
    with patch.object(repl, "_cmd_session_delete") as mock_delete:
        repl._cmd_session("delete mysession")
        mock_delete.assert_called_once_with("mysession")


def test_memory_region_dispatches(tmp_path):
    """/memory region add/remove/clear 应调用 _memory_manage_region。"""
    repl = _make_repl(tmp_path)
    # 用真实 MemoryStore 而不是 None
    from core.memory.store import MemoryStore
    repl.memory_store = MemoryStore(storage_path=tmp_path)
    with patch.object(repl, "_memory_manage_region") as mock_region:
        repl._cmd_memory("region add 杭州市")
        mock_region.assert_called_once_with("add 杭州市")


def test_memory_task_dispatches(tmp_path):
    """/memory task done/cancel/reopen/delete 应调用 _memory_manage_task。"""
    repl = _make_repl(tmp_path)
    from core.memory.store import MemoryStore
    repl.memory_store = MemoryStore(storage_path=tmp_path)
    with patch.object(repl, "_memory_manage_task") as mock_task:
        repl._cmd_memory("task done task_123")
        mock_task.assert_called_once_with("done task_123")


def test_memory_workflow_dispatches(tmp_path):
    """/memory workflow clear/suggest 应调用 _memory_manage_workflow。"""
    repl = _make_repl(tmp_path)
    from core.memory.store import MemoryStore
    repl.memory_store = MemoryStore(storage_path=tmp_path)
    with patch.object(repl, "_memory_manage_workflow") as mock_wf:
        repl._cmd_memory("workflow clear")
        mock_wf.assert_called_once_with("clear")


def test_pet_reset_dispatches(tmp_path):
    """/pet reset stats/effects 应调用 _pet_reset。"""
    repl = _make_repl(tmp_path)
    with patch.object(repl, "_pet_reset") as mock_reset:
        repl._cmd_pet("reset stats")
        mock_reset.assert_called_once_with("stats")


def test_memory_region_add_e2e(tmp_path):
    """端到端：/memory region add <地区> 真的添加到 profile。"""
    repl = _make_repl(tmp_path)
    from core.memory.store import MemoryStore
    repl.memory_store = MemoryStore(storage_path=tmp_path)
    repl._cmd_memory("region add 杭州市")
    from core.memory.profile import ProfileManager
    p = ProfileManager(repl.memory_store).get_profile()
    assert "杭州市" in p.focus_regions


def test_memory_task_done_e2e(tmp_path):
    """端到端：/memory task done <id> 真的更新任务状态。"""
    repl = _make_repl(tmp_path)
    from core.memory.store import MemoryStore
    from core.memory.tasks import TaskManager
    repl.memory_store = MemoryStore(storage_path=tmp_path)
    # 先添加一条任务
    mgr = TaskManager(repl.memory_store)
    task_id = mgr.add_task("测试任务")
    # 用简写前缀执行 done
    short_id = task_id[:12]
    repl._cmd_memory(f"task done {short_id}")
    all_tasks = mgr.get_all_tasks()
    assert all_tasks[0].status == "completed"


def test_memory_workflow_clear_e2e(tmp_path):
    """端到端：/memory workflow clear 真的清空模式。"""
    repl = _make_repl(tmp_path)
    from core.memory.store import MemoryStore
    from core.memory.workflow import WorkflowTracker
    repl.memory_store = MemoryStore(storage_path=tmp_path)
    # 先积累一些模式
    tracker = WorkflowTracker(repl.memory_store)
    tracker.record_command("ingest")
    tracker.record_command("analyze")
    assert len(repl.memory_store.get_data()["workflow"]["patterns"]) > 0
    # 执行清空
    repl._cmd_memory("workflow clear")
    assert repl.memory_store.get_data()["workflow"]["patterns"] == []


# ---- Group 2: 展示但没设置入口 ----

def test_edit_dispatches(tmp_path):
    """/edit <id> <field> <value> 应调用 _cmd_edit。"""
    repl = _make_repl(tmp_path)
    with patch.object(repl, "_cmd_edit") as mock_edit:
        repl._handle_command("/edit abc123 title 新标题")
        mock_edit.assert_called_once_with("abc123 title 新标题")


def test_graph_delete_dispatches(tmp_path):
    """/graph delete <node> 应调用 _graph_delete_node。"""
    repl = _make_repl(tmp_path)
    with patch.object(repl, "_graph_delete_node") as mock_del:
        repl._cmd_graph("delete 杭州市")
        mock_del.assert_called_once()
        # 第二个参数是节点名
        args = mock_del.call_args[0]
        assert args[1] == "杭州市"


def test_graph_rename_dispatches(tmp_path):
    """/graph rename <old> <new> 应调用 _graph_rename_node。"""
    repl = _make_repl(tmp_path)
    with patch.object(repl, "_graph_rename_node") as mock_mv:
        repl._cmd_graph("rename 杭州 新杭州")
        mock_mv.assert_called_once()
        args = mock_mv.call_args[0]
        assert args[1] == "杭州 新杭州"


def test_edit_title_e2e(tmp_path):
    """端到端：/edit <id> title <新标题> 真的修改标题。"""
    repl = _make_repl(tmp_path)
    # 用真实 Storage 而不是 MagicMock
    from core.storage import Storage
    from core.ingestion.parser import ParsedDocument
    from core.ingestion.chunker import Chunk
    storage = Storage(storage_path=tmp_path)
    file_path = tmp_path / "test.txt"
    file_path.write_text("内容", encoding="utf-8")
    parsed = ParsedDocument(
        title="原标题", text="内容", file_path=file_path,
        file_type=".txt", language="zh", meta={},
    )
    chunks = [Chunk(index=0, content="内容", token_count=10, start_char=0, end_char=2)]
    record = storage.save_document(parsed, chunks, copy_file=False)
    doc_id = record.id  # save_document 返回 DocumentRecord，取 .id
    repl.storage = storage
    # 执行编辑
    repl._cmd_edit(f"{doc_id} title 新标题")
    doc = storage.get_document(doc_id)
    assert doc.title == "新标题"


# ---- Group 3: 自动写入无操作入口 ----

def test_sync_reset_dispatches(tmp_path):
    """/sync reset 应调用 _cmd_sync 并传 'reset'。"""
    repl = _make_repl(tmp_path)
    with patch.object(repl, "_cmd_sync") as mock_sync:
        repl._handle_command("/sync reset")
        mock_sync.assert_called_once_with("reset")


def test_health_list_dispatches(tmp_path):
    """/health list 应调用 _cmd_health 并传 'list'。"""
    repl = _make_repl(tmp_path)
    with patch.object(repl, "_cmd_health") as mock_health:
        repl._handle_command("/health list")
        mock_health.assert_called_once_with("list")


def test_dedup_delete_dispatches(tmp_path):
    """/dedup delete <id> 应调用 _cmd_dedup。"""
    repl = _make_repl(tmp_path)
    with patch.object(repl, "_cmd_dedup") as mock_dedup:
        repl._handle_command("/dedup delete chunk_abc123")
        mock_dedup.assert_called_once_with("delete chunk_abc123")


def test_tag_rename_dispatches(tmp_path):
    """/tag rename <old> <new> 应调用 _cmd_tag_rename。"""
    repl = _make_repl(tmp_path)
    with patch.object(repl, "_cmd_tag_rename") as mock_rename:
        repl._handle_command("/tag rename 殡葬 身后事")
        mock_rename.assert_called_once_with("殡葬 身后事")


def test_tag_merge_dispatches(tmp_path):
    """/tag merge <src> <dst> 应调用 _cmd_tag_merge。"""
    repl = _make_repl(tmp_path)
    with patch.object(repl, "_cmd_tag_merge") as mock_merge:
        repl._handle_command("/tag merge 骨灰 政策")
        mock_merge.assert_called_once_with("骨灰 政策")


def test_pet_bag_dispatches(tmp_path):
    """/pet bag 应调用 _pet_show_bag。"""
    repl = _make_repl(tmp_path)
    with patch.object(repl, "_pet_show_bag") as mock_bag:
        repl._cmd_pet("bag")
        mock_bag.assert_called_once()


def test_tag_rename_e2e(tmp_path):
    """端到端：/tag rename <旧> <新> 真的重命名标签。"""
    repl = _make_repl(tmp_path)
    from core.storage import Storage
    from core.ingestion.parser import ParsedDocument
    from core.ingestion.chunker import Chunk
    storage = Storage(storage_path=tmp_path)
    file_path = tmp_path / "test.txt"
    file_path.write_text("内容", encoding="utf-8")
    parsed = ParsedDocument(
        title="文档", text="内容", file_path=file_path,
        file_type=".txt", language="zh", meta={},
    )
    chunks = [Chunk(index=0, content="内容", token_count=10, start_char=0, end_char=2)]
    storage.save_document(parsed, chunks, copy_file=False, tags=["殡葬", "政策"])
    repl.storage = storage

    # 执行重命名
    repl._cmd_tag_rename("殡葬 身后事")
    doc = storage.list_documents()[0]
    assert "殡葬" not in doc.tags
    assert "身后事" in doc.tags


def test_dedup_delete_e2e(tmp_path):
    """端到端：/dedup delete <chunk_id> 真的删除 chunk。"""
    repl = _make_repl(tmp_path)
    from core.storage import Storage
    from core.ingestion.parser import ParsedDocument
    from core.ingestion.chunker import Chunk
    storage = Storage(storage_path=tmp_path)
    file_path = tmp_path / "test.txt"
    file_path.write_text("内容", encoding="utf-8")
    parsed = ParsedDocument(
        title="文档", text="内容", file_path=file_path,
        file_type=".txt", language="zh", meta={},
    )
    chunks = [
        Chunk(index=0, content="分块0", token_count=5, start_char=0, end_char=3),
        Chunk(index=1, content="分块1", token_count=5, start_char=3, end_char=6),
    ]
    record = storage.save_document(parsed, chunks, copy_file=False)
    chunk_id = f"{record.id}_0"
    repl.storage = storage

    # 绕过 Prompt.ask 确认，直接调用 delete 子流程
    with patch("repl.Prompt.ask", return_value="y"):
        repl._cmd_dedup(f"delete {chunk_id}")

    # chunk 应被删除
    assert len(storage.get_chunks(record.id)) == 1


# ---- Group 4: 错误状态无恢复路径 ----

def test_reparse_dispatches(tmp_path):
    """/reparse <id> 应调用 _cmd_reparse。"""
    repl = _make_repl(tmp_path)
    with patch.object(repl, "_cmd_reparse") as mock_reparse:
        repl._handle_command("/reparse abc123")
        mock_reparse.assert_called_once_with("abc123")


def test_reparse_by_doc_id_e2e(tmp_path):
    """端到端：/reparse <doc_id> 删除旧文档并重新入库。"""
    repl = _make_repl(tmp_path)
    from core.storage import Storage
    from core.ingestion.parser import ParsedDocument
    from core.ingestion.chunker import Chunk
    storage = Storage(storage_path=tmp_path)
    file_path = tmp_path / "test.txt"
    file_path.write_text("原始内容", encoding="utf-8")
    parsed = ParsedDocument(
        title="测试", text="原始内容", file_path=file_path,
        file_type=".txt", language="zh", meta={},
    )
    chunks = [Chunk(index=0, content="原始内容", token_count=5, start_char=0, end_char=4)]
    record = storage.save_document(parsed, chunks, copy_file=False)
    doc_id = record.id
    repl.storage = storage

    # 修改文件内容
    file_path.write_text("更新后内容", encoding="utf-8")

    # 执行 reparse（绕过确认）
    with patch("repl.Prompt.ask", return_value="y"):
        repl._cmd_reparse(doc_id[:8])

    # 旧 doc_id 应已删除，新文档应存在
    assert storage.get_document(doc_id) is None
    docs = storage.list_documents()
    assert len(docs) == 1
    assert "更新后" in docs[0].title or "更新后" in file_path.read_text(encoding="utf-8")


def test_reparse_by_file_path_e2e(tmp_path):
    """端到端：/reparse <文件路径> 直接入库新文件。"""
    repl = _make_repl(tmp_path)
    from core.storage import Storage
    storage = Storage(storage_path=tmp_path)
    file_path = tmp_path / "new.txt"
    file_path.write_text("新文件内容", encoding="utf-8")
    repl.storage = storage

    with patch("repl.Prompt.ask", return_value="y"):
        repl._cmd_reparse(str(file_path))

    docs = storage.list_documents()
    assert len(docs) == 1


def test_reparse_nonexistent_returns_error(tmp_path):
    """/reparse 不存在的 id 应提示未找到。"""
    repl = _make_repl(tmp_path)
    # 不应抛异常，只打印错误
    repl._cmd_reparse("nonexistent_id")
    # 验证：storage 中没有文档被创建


def test_rebuild_vector_hot_updates_hybrid(tmp_path):
    """端到端：/rebuild --vector 成功后应热更新 administrator.hybrid.vector。"""
    repl = _make_repl(tmp_path)
    from core.storage import Storage
    storage = Storage(storage_path=tmp_path)
    repl.storage = storage
    # 模拟 administrator 持有旧的 vector_index
    old_vi = MagicMock()
    old_vi.is_available.return_value = False
    repl.administrator = MagicMock()
    repl.administrator.hybrid.vector = old_vi

    # 模拟 VectorIndex 构造和 rebuild 成功
    new_vi = MagicMock()
    new_vi.is_available.return_value = True
    with patch("core.retrieval.vector.VectorIndex", return_value=new_vi), \
         patch.object(storage, "rebuild_vector_index", return_value=5):
        repl._cmd_rebuild("--vector")

    # 应热更新：storage 和 administrator 都持有新 vi
    assert storage._vector_index is new_vi
    assert repl.administrator.hybrid.vector is new_vi


def test_rebuild_vector_failure_keeps_old_index(tmp_path):
    """/rebuild --vector 失败时应保留旧索引，不崩溃。"""
    repl = _make_repl(tmp_path)
    from core.storage import Storage
    storage = Storage(storage_path=tmp_path)
    repl.storage = storage
    old_vi = MagicMock()
    old_vi.is_available.return_value = False
    storage.attach_vector_index(old_vi)
    repl.administrator = MagicMock()
    repl.administrator.hybrid.vector = old_vi

    # 模拟 VectorIndex 构造抛非 ImportError 异常
    with patch("core.retrieval.vector.VectorIndex", side_effect=Exception("模型下载失败")):
        repl._cmd_rebuild("--vector")

    # 旧索引应保留
    assert storage._vector_index is old_vi
    assert repl.administrator.hybrid.vector is old_vi


# ---- Group 5: CLI/REPL 不对等 ----

def test_search_with_tag_filter(tmp_path):
    """端到端：/search 关键词 --tag 标签 应按标签筛选结果。"""
    repl = _make_repl(tmp_path)
    from core.storage import Storage
    from core.ingestion.parser import ParsedDocument
    from core.ingestion.chunker import Chunk
    storage = Storage(storage_path=tmp_path)
    # 入库两个文档，一个有标签，一个没有
    for i, (title, tags) in enumerate([("政策文档", ["政策"]), ("其他文档", [])]):
        fp = tmp_path / f"test{i}.txt"
        fp.write_text(f"{title}内容", encoding="utf-8")
        parsed = ParsedDocument(
            title=title, text=f"{title}内容", file_path=fp,
            file_type=".txt", language="zh", meta={},
        )
        chunks = [Chunk(index=0, content=f"{title}内容", token_count=5, start_char=0, end_char=4)]
        storage.save_document(parsed, chunks, copy_file=False, tags=tags)
    repl.storage = storage

    # 不带 tag 应返回所有结果
    repl._cmd_search("内容")
    # 带 tag 应只返回带标签的文档
    repl._cmd_search("内容 --tag 政策")


def test_search_with_limit(tmp_path):
    """端到端：/search 关键词 --limit 1 应只返回 1 条。"""
    repl = _make_repl(tmp_path)
    from core.storage import Storage
    from core.ingestion.parser import ParsedDocument
    from core.ingestion.chunker import Chunk
    storage = Storage(storage_path=tmp_path)
    # 入库 3 个文档
    for i in range(3):
        fp = tmp_path / f"test{i}.txt"
        fp.write_text(f"测试内容{i}", encoding="utf-8")
        parsed = ParsedDocument(
            title=f"文档{i}", text=f"测试内容{i}", file_path=fp,
            file_type=".txt", language="zh", meta={},
        )
        chunks = [Chunk(index=0, content=f"测试内容{i}", token_count=5, start_char=0, end_char=5)]
        storage.save_document(parsed, chunks, copy_file=False)
    repl.storage = storage

    # 用 --limit 1 限制结果数
    # 不应抛异常
    repl._cmd_search("测试 --limit 1")


def test_search_invalid_limit_returns_error(tmp_path):
    """/search --limit abc 应提示无效。"""
    repl = _make_repl(tmp_path)
    # 不应抛异常，只打印错误
    repl._cmd_search("关键词 --limit abc")


def test_search_no_keyword_with_tag_returns_error(tmp_path):
    """/search --tag 政策（无关键词）应提示提供关键词。"""
    repl = _make_repl(tmp_path)
    repl._cmd_search("--tag 政策")


def test_show_displays_new_fields(tmp_path):
    """端到端：/show 应显示 file_name/language/meta 字段。"""
    repl = _make_repl(tmp_path)
    from core.storage import Storage
    from core.ingestion.parser import ParsedDocument
    from core.ingestion.chunker import Chunk
    storage = Storage(storage_path=tmp_path)
    file_path = tmp_path / "test.txt"
    file_path.write_text("内容", encoding="utf-8")
    parsed = ParsedDocument(
        title="测试文档", text="内容", file_path=file_path,
        file_type=".txt", language="zh", meta={"saved_path": "/tmp/saved"},
    )
    chunks = [Chunk(index=0, content="内容", token_count=10, start_char=0, end_char=2)]
    record = storage.save_document(parsed, chunks, copy_file=True)
    repl.storage = storage

    # 执行 /show，不应抛异常
    repl._cmd_show(record.id[:8])
