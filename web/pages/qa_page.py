"""AI 问答页面：对话式 RAG。"""
from __future__ import annotations

import streamlit as st

from config import settings
from core.storage import Storage
from core.llm.client import LLMError
from core.qa.chain import RAGChain, SYSTEM_PROMPT, _build_user_prompt


def render(storage: Storage) -> None:
    st.title("💬 AI 问答")

    st.caption("基于知识库的 RAG 问答 · 带 [1][2] 引用编号 · 支持多轮对话")

    # ---- LLM 检查 ----
    if not settings.has_llm():
        st.error("LLM 未配置，请在 .env 中设置 AGNES_API_KEY")
        st.info("参考 `.env.example` 配置 Agnes AI API Key")
        return

    # ---- 初始化 session state ----
    if "messages" not in st.session_state:
        st.session_state.messages = []  # 显示用消息列表
    if "history" not in st.session_state:
        st.session_state.history = []   # 发给 LLM 的历史（含 system + user_prompt）

    # ---- 信息栏：对话长度 + 模型状态 ----
    conv_len = len(st.session_state.messages)
    model_name = getattr(settings, "llm_model", None) or "默认"
    col_info1, col_info2 = st.columns([1, 1])
    with col_info1:
        st.caption(f"对话轮数: {conv_len // 2} 轮 ({conv_len} 条消息)")
    with col_info2:
        st.caption(f"LLM 模型: {model_name}")

    # ---- 工具栏 ----
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        if st.button("🗑️ 清空对话"):
            st.session_state.messages = []
            st.session_state.history = []
            st.rerun()
    with col2:
        top_k = st.number_input(
            "Top-K",
            min_value=1, max_value=20, value=settings.rag_top_k,
            key="top_k_input",
            label_visibility="collapsed",
        )
    with col3:
        st.markdown(
            '<span style="color:#888;font-size:0.85em;">按 Enter 发送</span>',
            unsafe_allow_html=True,
        )

    st.divider()

    # ---- 显示历史消息 ----
    for msg in st.session_state.messages:
        role = msg["role"]
        with st.chat_message(role):
            if role == "user":
                st.write(msg["content"])
            else:
                st.write(msg["content"])
                if msg.get("citations"):
                    with st.expander(f"📚 引用来源 ({len(msg['citations'])} 条)"):
                        for c in msg["citations"]:
                            st.caption(
                                f"[{c['index']}] **{c['doc_title']}** · 相关度 {c['score']}"
                            )
                            st.caption(c["preview"])
                # 复制回答按钮
                _copy_key = f"copy_{msg['content'][:20]}"
                if st.button("📋 复制回答", key=_copy_key):
                    st.code(msg["content"], language=None)
                    st.toast("已复制到剪贴板", icon="✅")

    # ---- 输入框 ----
    if query := st.chat_input("输入你的问题..."):
        # 显示用户消息
        st.session_state.messages.append({"role": "user", "content": query})
        with st.chat_message("user"):
            st.write(query)

        # AI 回答
        with st.chat_message("assistant"):
            # 1. 检索
            with st.spinner("🔍 检索相关资料..."):
                results = storage.bm25_search(query, top_k=int(top_k))
                if results:
                    st.caption(f"✓ 检索到 {len(results)} 条相关资料")
                else:
                    st.warning("⚠ 未检索到相关资料，AI 将基于通用知识回答（不推荐）")

            # 2. LLM 生成
            try:
                rag = RAGChain(storage=storage)
            except LLMError as e:
                st.error(f"LLM 初始化失败: {e}")
                return

            user_prompt = _build_user_prompt(query, results)
            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            messages.extend(st.session_state.history)
            messages.append({"role": "user", "content": user_prompt})

            # 流式输出
            with st.spinner("🤖 生成中..."):
                content_placeholder = st.empty()
                full_content = ""
                try:
                    for token in rag.llm.chat_stream(messages, temperature=0.3):
                        full_content += token
                        content_placeholder.markdown(full_content + " ▌")
                    content_placeholder.markdown(full_content)
                except LLMError as e:
                    st.error(f"LLM 调用失败: {e}")
                    return

            # 3. 显示引用
            citations = []
            if results:
                with st.expander(f"📚 引用来源 ({len(results)} 条)"):
                    for i, r in enumerate(results, 1):
                        st.caption(
                            f"[{i}] **{r.doc_title}** · 相关度 {r.score:.2f}"
                        )
                        st.caption(r.content[:200] + "...")
                        citations.append({
                            "index": i,
                            "doc_title": r.doc_title,
                            "doc_id": r.doc_id,
                            "chunk_id": r.chunk_id,
                            "score": round(r.score, 3),
                            "preview": r.content[:150] + ("..." if len(r.content) > 150 else ""),
                        })

            # 4. 复制回答按钮（新消息）
            if st.button("📋 复制回答", key=f"copy_new_{full_content[:20]}"):
                st.code(full_content, language=None)
                st.toast("已复制到剪贴板", icon="✅")

            # 5. 保存到历史
            st.session_state.messages.append({
                "role": "assistant",
                "content": full_content,
                "citations": citations,
            })
            # 发给 LLM 的历史用原始 prompt（不是显示文本）
            st.session_state.history.append({"role": "user", "content": user_prompt})
            st.session_state.history.append({"role": "assistant", "content": full_content})
            # 保留最近 10 条（5 轮）
            if len(st.session_state.history) > 10:
                st.session_state.history = st.session_state.history[-10:]
