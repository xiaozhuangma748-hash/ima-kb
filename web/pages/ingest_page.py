"""入库管理页面：上传文件、查看进度。"""
from __future__ import annotations

import tempfile
from pathlib import Path

import streamlit as st

from config import settings
from core.storage import Storage
from core.ingestion.parser import parse, is_supported, SUPPORTED_EXTENSIONS, ParseError
from core.ingestion.chunker import chunk_document


def render(storage: Storage) -> None:
    st.title("📥 入库管理")

    # ---- 支持格式提示 ----
    with st.container():
        st.caption(
            f"支持格式：{', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    # ---- 上传方式切换 ----
    tab_upload, tab_path = st.tabs(["📤 拖拽上传", "📁 路径入库"])

    # ===== 拖拽上传 =====
    with tab_upload:
        uploaded_files = st.file_uploader(
            "拖拽文件到这里或点击选择",
            accept_multiple_files=True,
            help=f"支持 {len(SUPPORTED_EXTENSIONS)} 种格式",
        )

        if uploaded_files:
            st.info(f"已选择 {len(uploaded_files)} 个文件")
            if st.button("🚀 开始入库", type="primary"):
                _process_uploads(storage, uploaded_files)

    # ===== 路径入库 =====
    with tab_path:
        st.subheader("从本地路径入库")
        path_str = st.text_input(
            "输入文件或目录路径",
            placeholder="如 ~/Documents/政策文件/ 或 /path/to/file.pdf",
        )
        if st.button("🚀 入库", type="primary"):
            if path_str:
                _process_path(storage, path_str)
            else:
                st.warning("请输入路径")

    st.divider()

    # ---- 最近入库 ----
    st.subheader("🕒 最近入库的 10 条")
    try:
        recent = storage.list_documents(limit=10)
    except Exception as e:
        st.error(f"读取列表失败: {e}")
        return

    if not recent:
        st.info("知识库为空")
        return

    for d in recent:
        with st.container(border=True):
            st.markdown(f"**{d.title}**")
            tag_str = "  ".join(f"`{t}`" for t in d.tags) if d.tags else "无标签"
            st.caption(f"{d.file_name} · {d.created_at[:19]} · {tag_str}")
            m1, m2, m3 = st.columns(3)
            m1.metric("类型", d.file_type)
            m2.metric("分块", d.chunk_count)
            m3.metric("Tokens", d.total_tokens)


def _process_uploads(storage: Storage, uploaded_files) -> None:
    """处理拖拽上传的文件。"""
    progress = st.progress(0, text="准备中...")
    success, fail, skip = 0, 0, 0
    total = len(uploaded_files)

    for i, uploaded in enumerate(uploaded_files, 1):
        progress.progress(
            i / total,
            text=f"入库中... {i}/{total}: {uploaded.name}"
        )

        # 检查格式
        ext = Path(uploaded.name).suffix.lower()
        if not is_supported(uploaded.name):
            st.warning(f"跳过不支持的格式: {uploaded.name} ({ext})")
            skip += 1
            continue

        # 保存到临时文件再解析
        try:
            with tempfile.NamedTemporaryFile(
                delete=False, suffix=ext, prefix="upload_"
            ) as tmp:
                tmp.write(uploaded.getvalue())
                tmp_path = Path(tmp.name)

            # 解析 + 分块
            parsed = parse(tmp_path)
            tmp_path.unlink(missing_ok=True)  # 删临时文件

            if not parsed.text.strip():
                st.warning(f"跳过空内容: {uploaded.name}")
                skip += 1
                continue

            # 改写文件名为真实名称（用于显示）
            parsed.file_path = Path(uploaded.name)
            parsed.title = Path(uploaded.name).stem

            chunks = chunk_document(
                parsed,
                chunk_size=settings.chunk_size,
                chunk_overlap=settings.chunk_overlap,
            )

            # 去重检查
            import hashlib
            content_hash = hashlib.sha256(parsed.text.encode("utf-8")).hexdigest()
            doc_id = content_hash[:32]
            if storage.get_document(doc_id) is not None:
                st.info(f"已存在（跳过）: {uploaded.name}")
                skip += 1
                continue

            # 自动打标签
            tags: list[str] = []
            if settings.has_llm():
                try:
                    from core.classify.tagger import Tagger
                    tagger = Tagger()
                    tags = tagger.generate_tags_for_document(parsed)
                except Exception:
                    pass

            # 保存（不复制原文件，因为 streamlit 上传的是临时数据）
            record = storage.save_document(parsed, chunks, copy_file=False, tags=tags)
            # 手动把上传内容存到 uploads
            target_dir = storage.uploads_dir / record.id[:2]
            target_dir.mkdir(parents=True, exist_ok=True)
            target_path = target_dir / uploaded.name
            target_path.write_bytes(uploaded.getvalue())
            record.meta["saved_path"] = str(target_path)

            success += 1
            tag_str = f" · 标签: {'、'.join(tags)}" if tags else ""
            st.write(f"✓ {uploaded.name} · 分块 {record.chunk_count} / {record.total_tokens} tokens{tag_str}")

        except ParseError as e:
            st.error(f"解析失败: {uploaded.name} - {e}")
            fail += 1
        except Exception as e:
            st.error(f"入库失败: {uploaded.name} - {type(e).__name__}: {e}")
            fail += 1

    progress.empty()
    st.success(f"✓ 完成 · 成功 {success} / 失败 {fail} / 跳过 {skip} / 共 {total}")
    st.button("刷新")


def _process_path(storage: Storage, path_str: str) -> None:
    """从本地路径入库。"""
    path = Path(path_str).expanduser().resolve()
    if not path.exists():
        st.error(f"路径不存在: {path}")
        return

    if path.is_file():
        files = [path]
    else:
        files = []
        for ext in SUPPORTED_EXTENSIONS:
            files.extend(path.rglob(f"*{ext}"))
        files = sorted(set(files))

    if not files:
        st.warning("未找到支持的文件")
        return

    st.info(f"找到 {len(files)} 个文件，开始入库...")
    progress = st.progress(0, text="准备中...")
    success, skip = 0, 0
    total = len(files)

    for i, f in enumerate(files, 1):
        progress.progress(i / total, text=f"入库中... {i}/{total}: {f.name}")
        if _ingest_one_silent(storage, f):
            success += 1
        else:
            skip += 1

    progress.empty()
    st.success(f"✓ 完成 · 成功 {success} / 跳过 {skip} / 共 {total}")
    st.button("刷新")


def _ingest_one_silent(storage: Storage, file_path: Path) -> bool:
    """静默入库单个文件（返回是否成功）。"""
    if not is_supported(file_path):
        return False
    try:
        parsed = parse(file_path)
        if not parsed.text.strip():
            return False
        chunks = chunk_document(
            parsed,
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )
        import hashlib
        content_hash = hashlib.sha256(parsed.text.encode("utf-8")).hexdigest()
        doc_id = content_hash[:32]
        if storage.get_document(doc_id) is not None:
            return False
        # 自动打标签
        tags: list[str] = []
        if settings.has_llm():
            try:
                from core.classify.tagger import Tagger
                tagger = Tagger()
                tags = tagger.generate_tags_for_document(parsed)
            except Exception:
                pass
        storage.save_document(parsed, chunks, copy_file=True, tags=tags)
        return True
    except Exception:
        return False
