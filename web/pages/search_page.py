"""搜索页面：BM25 智能搜索。"""
from __future__ import annotations

import streamlit as st

from core.storage import Storage


def render(storage: Storage) -> None:
    st.title("🔍 BM25 智能搜索")

    st.caption("基于 jieba 中文分词 + BM25 算法，懂中文、懂词频权重")

    # ---- 搜索输入（全宽，优先展示） ----
    query = st.text_input(
        "输入搜索词",
        placeholder="如：骨灰 奖补 / 退役军人抚恤 / 2000元补贴",
    )

    # ---- 标签筛选 + 返回数 ----
    try:
        all_tags = list(storage.list_all_tags().keys())
    except Exception:
        all_tags = []

    selected_tag = None
    col_filter, col_topk = st.columns([3, 1])

    with col_filter:
        if all_tags:
            selected_tag = st.selectbox(
                "按标签筛选（可选）",
                options=["（不筛选）"] + all_tags,
                index=0,
            )
            if selected_tag == "（不筛选）":
                selected_tag = None

    with col_topk:
        top_k = st.number_input("返回数", min_value=1, max_value=50, value=10)

    # ---- 搜索 ----
    if query.strip():
        with st.spinner("搜索中..."):
            try:
                # 如有标签筛选，扩大候选数后过滤
                fetch_k = int(top_k) * 5 if selected_tag else int(top_k)
                results = storage.bm25_search(query.strip(), top_k=fetch_k)
            except Exception as e:
                st.error(f"搜索失败: {e}")
                return

        if selected_tag:
            tagged_docs = storage.list_documents_by_tag(selected_tag)
            allowed_ids = {d.id for d in tagged_docs}
            results = [r for r in results if r.doc_id in allowed_ids]

        if not results:
            hint = f"且带标签 '{selected_tag}'" if selected_tag else ""
            st.warning(f"未找到与 '{query}'{hint} 相关的内容")
            return

        tag_hint = f" · 标签筛选: {selected_tag}" if selected_tag else ""
        st.success(f"找到 {len(results)} 条相关结果{tag_hint}")

        for i, r in enumerate(results, 1):
            with st.container(border=True):
                # 标题行：缩小分数列，用 caption 展示
                col_score, col_title = st.columns([1, 6])
                with col_score:
                    st.caption(f"Score: {r.score:.2f}")
                with col_title:
                    st.write(f"**[{i}] {r.doc_title}**")
                    st.caption(f"doc: {r.doc_id[:8]} · chunk: {r.chunk_id}")

                # 内容
                st.markdown(r.content)

                # 所属文档链接（替代按钮）
                st.caption(
                    f"[查看所属文档详情](#) "
                    f'<span style="font-size:0.75rem;color:gray">doc: {r.doc_id[:8]}</span>',
                    unsafe_allow_html=True,
                )
                if st.button("查看所属文档详情", key=f"btn_{i}_{r.chunk_id}"):
                    st.session_state["show_doc"] = r.doc_id
                    st.rerun()
    else:
        # 未搜索时显示统计
        st.info("👆 输入搜索词开始搜索")
        st.divider()
        with st.expander("💡 搜索技巧"):
            st.markdown("""
- **多词搜索**：`骨灰 奖补 标准` 多个词一起搜
- **短语搜索**：`节地生态安葬` 整句作为关键词
- **数字搜索**：`2000元` `300元` 也能搜
- **代码搜索**：英文也能搜，如 `cosine_similarity`
- BM25 比 LIKE 强在：懂中文分词（骨灰/安葬），懂词频权重（罕见词更优先）
- BM25 不擅长：同义词、语义理解（搜"安葬"找不到"埋葬"），那是 AI 问答的事
""")

    # ---- 详情弹窗 ----
    if "show_doc" in st.session_state and st.session_state["show_doc"]:
        doc_id = st.session_state["show_doc"]
        doc = storage.get_document(doc_id)
        if doc:
            with st.expander(f"📄 {doc.title} · 详情", expanded=True):
                col_a, col_b, col_c = st.columns([2, 2, 2])
                with col_a:
                    st.metric("类型", doc.file_type)
                    st.metric("分块数", doc.chunk_count)
                with col_b:
                    st.metric("大小", f"{doc.file_size} bytes")
                    st.metric("Tokens", doc.total_tokens)
                with col_c:
                    st.metric("语言", doc.language)
                    st.metric("入库时间", doc.created_at[:19])
                st.caption(f"原路径: {doc.file_path}")
                if doc.tags:
                    tag_str = "  ".join(f"`{t}`" for t in doc.tags)
                    st.caption(f"标签: {tag_str}")

                st.divider()
                chunks = storage.get_chunks(doc_id)
                for c in chunks[:5]:
                    st.caption(f"Chunk #{c.index} · {c.token_count} tokens")
                    st.write(c.content[:500] + ("..." if len(c.content) > 500 else ""))
                if len(chunks) > 5:
                    st.caption(f"... 还有 {len(chunks) - 5} 块")

                if st.button("关闭详情"):
                    st.session_state["show_doc"] = None
                    st.rerun()
