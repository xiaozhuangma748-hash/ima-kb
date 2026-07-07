"""仪表盘页面：统计 + 文档列表。"""
from __future__ import annotations

import streamlit as st
import pandas as pd

from core.storage import Storage


def render(storage: Storage) -> None:
    st.title("📊 仪表盘")
    st.caption("知识库运行状态总览")

    st.divider()

    # ---- 统计卡片 ----
    try:
        stats = storage.stats()
        bm25_info = storage.bm25.info()
    except Exception as e:
        st.error(f"读取统计失败: {e}")
        return

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("文档总数", stats["documents"])
    with col2:
        st.metric("分块总数", stats["chunks"])
    with col3:
        st.metric("Token 数", f"{stats['total_tokens']:,}")
    with col4:
        st.metric("存储大小", f"{stats['total_size_mb']} MB")

    st.divider()

    # ---- 类型分布 ----
    col_left, col_right = st.columns([2, 3])

    with col_left:
        st.subheader("📁 按类型分布")
        by_type = stats.get("by_type", {})
        if by_type:
            df_type = pd.DataFrame(
                [{"类型": k, "数量": v} for k, v in by_type.items()]
            )
            st.bar_chart(df_type.set_index("类型"))
            st.dataframe(df_type, width="stretch", hide_index=True)
        else:
            st.info("暂无数据")

    with col_right:
        st.subheader("📈 BM25 索引")
        col_a, col_b = st.columns(2)
        with col_a:
            st.metric("索引分块", bm25_info["chunks"])
        with col_b:
            st.metric("词汇量", bm25_info["vocabulary"])
        st.metric("总 Token", bm25_info["total_tokens"])

        st.divider()

        st.subheader("🏷️ 标签分布")
        try:
            tags = storage.list_all_tags()
        except Exception:
            tags = {}
        if tags:
            # 显示前 10 个最常用标签
            df_tags = pd.DataFrame(
                [{"标签": k, "文档数": v} for k, v in list(tags.items())[:10]]
            )
            st.bar_chart(df_tags.set_index("标签"))
            # 将标签信息格式化显示在柱状图下方
            top_tags = list(tags.items())[:15]
            tag_lines = [f"`{k}` x{v}" for k, v in top_tags]
            st.caption("Top 标签：" + "  |  ".join(tag_lines))
        else:
            st.caption("暂无标签（可在终端运行 `ima retag` 生成）")

        st.divider()

        st.subheader("🔧 索引维护")
        if st.button("🔄 重建 BM25 索引", type="secondary"):
            with st.spinner("重建中..."):
                count = storage.rebuild_bm25_index()
            st.success(f"✓ 重建完成，索引 {count} 个分块")
            st.rerun()

    st.divider()

    # ---- 文档列表 ----
    st.subheader("📄 文档列表")
    try:
        docs = storage.list_documents(limit=500)
    except Exception as e:
        st.error(f"读取文档列表失败: {e}")
        return

    if not docs:
        st.info("知识库为空，去『入库管理』添加文件吧")
        return

    # 转 DataFrame
    rows = []
    for d in docs:
        rows.append({
            "ID": d.id[:8],
            "标题": d.title,
            "类型": d.file_type,
            "标签": "、".join(d.tags) if d.tags else "-",
            "分块": d.chunk_count,
            "Tokens": d.total_tokens,
            "大小(KB)": round(d.file_size / 1024, 1),
            "入库时间": d.created_at[:19],
        })
    df = pd.DataFrame(rows)
    st.dataframe(
        df,
        width="stretch",
        hide_index=True,
        column_config={
            "标题": st.column_config.TextColumn(width="large"),
            "标签": st.column_config.TextColumn(width="medium"),
        },
    )

    st.divider()

    # ---- 删除文档（折叠，避免误操作）----
    with st.expander("🗑️ 删除文档"):
        with st.form("delete_form"):
            short_id = st.text_input("输入文档 ID 前 8 位", placeholder="如 24ea6ac3")
            submitted = st.form_submit_button("删除", type="primary")
            if submitted and short_id:
                # 匹配完整 ID
                all_docs = storage.list_documents(limit=1000)
                matched = [d for d in all_docs if d.id.startswith(short_id.strip())]
                if not matched:
                    st.error(f"未找到 ID 以 {short_id} 开头的文档")
                else:
                    doc = matched[0]
                    if storage.delete_document(doc.id):
                        st.success(f"✓ 已删除：{doc.title}")
                        st.rerun()
                    else:
                        st.error("删除失败")
