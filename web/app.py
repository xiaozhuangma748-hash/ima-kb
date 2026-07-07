"""Streamlit Web 应用主入口。

启动方式：
    streamlit run web/app.py

页面：
- 仪表盘：统计、文档列表
- 搜索：BM25 智能搜索
- AI 问答：对话式 RAG
- 知识图谱：实体关系可视化
- 入库管理：上传文件、删除
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st

from config import settings
from core.storage import Storage
from web.pixel_theme import theme_css

# ---- 全局配置 ----
st.set_page_config(
    page_title="个人知识库",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---- 注入全局主题 ----
st.markdown(theme_css(), unsafe_allow_html=True)


@st.cache_resource(show_spinner=False)
def get_storage() -> Storage:
    settings.ensure_dirs()
    return Storage()


# ---- 路由定义 ----
PAGES = {
    "仪表盘": "web.pages.dashboard",
    "搜索": "web.pages.search_page",
    "AI 问答": "web.pages.qa_page",
    "知识图谱": "web.pages.graph_page",
    "入库管理": "web.pages.ingest_page",
}

PAGE_KEYS = list(PAGES.keys())

# 通过 query params 确定当前页面
_qp = st.query_params
_current_key = _qp.get("page", [PAGE_KEYS[0]])[0] if "page" in _qp else PAGE_KEYS[0]
if _current_key not in PAGES:
    _current_key = PAGE_KEYS[0]
current_idx = PAGE_KEYS.index(_current_key)


# ---- 侧边栏 ----
with st.sidebar:

    nav_items = [
        {"icon": "📊", "key": "仪表盘"},
        {"icon": "🔍", "key": "搜索"},
        {"icon": "💬", "key": "AI 问答"},
        {"icon": "🌐", "key": "知识图谱"},
        {"icon": "📥", "key": "入库管理"},
    ]

    nav_html = """
    <div class="ima-icon-nav">
        <div class="ima-nav-brand">
            <div class="ima-nav-logo">
                <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
                    <circle cx="14" cy="10" r="5" stroke="#8a8070" stroke-width="1.5" fill="none"/>
                    <circle cx="14" cy="18" r="5" stroke="#8a8070" stroke-width="1.5" fill="none"/>
                    <circle cx="10" cy="14" r="5" stroke="#d97757" stroke-width="1.5" fill="none"/>
                    <circle cx="18" cy="14" r="5" stroke="#788c5d" stroke-width="1.5" fill="none"/>
                </svg>
            </div>
        </div>
        <div class="ima-nav-divider"></div>
    """
    for i, item in enumerate(nav_items):
        active_cls = " ima-nav-item-active" if i == current_idx else ""
        # 使用链接点击跳转到当前 URL + query param，触发 Streamlit rerun
        nav_html += f"""
        <a href="?page={item['key']}" class="ima-nav-item{active_cls}">
            <span class="ima-nav-icon">{item['icon']}</span>
            <span class="ima-nav-label">{item['key']}</span>
        </a>
        """
    nav_html += """
        <div class="ima-nav-spacer"></div>
        <div class="ima-nav-divider"></div>
        <div class="ima-nav-footer">
            <div class="ima-nav-status">
                <span class="ima-status-dot"></span>
                <span class="ima-status-text">在线</span>
            </div>
        </div>
    </div>
    """
    st.markdown(nav_html, unsafe_allow_html=True)

    # 隐藏 Streamlit 侧边栏所有原生控件
    st.markdown("""
    <style>
    section[data-testid="stSidebar"] [data-testid="stSidebarContent"] > div > div > div > div:first-child,
    section[data-testid="stSidebar"] [data-testid="stSidebarContent"] > div > div > div > div:nth-child(2) {
        display: none !important;
    }
    section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] .stCaption,
    section[data-testid="stSidebar"] .stMetric,
    section[data-testid="stSidebar"] .stMarkdown p,
    section[data-testid="stSidebar"] hr {
        display: none !important;
    }
    button[kind="secondary"][aria-label="Hide sidebar"],
    button[kind="secondary"][aria-label="Show sidebar"] {
        display: none !important;
    }
    </style>
    """, unsafe_allow_html=True)

    # 统计指标
    storage = get_storage()
    try:
        stats = storage.stats()
        st.markdown(f"""
        <div class="ima-sidebar-stats">
            <div class="ima-stat-row">
                <div class="ima-stat-item">
                    <span class="ima-stat-label">文档</span>
                    <span class="ima-stat-value">{stats["documents"]}</span>
                </div>
                <div class="ima-stat-item">
                    <span class="ima-stat-label">分块</span>
                    <span class="ima-stat-value">{stats["chunks"]}</span>
                </div>
            </div>
            <div class="ima-stat-row">
                <div class="ima-stat-item">
                    <span class="ima-stat-label">Token</span>
                    <span class="ima-stat-value">{stats['total_tokens']:,}</span>
                </div>
                <div class="ima-stat-item">
                    <span class="ima-stat-label">大小</span>
                    <span class="ima-stat-value">{stats['total_size_mb']}MB</span>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)
    except Exception:
        pass

    llm_ok = settings.has_llm()
    llm_cls = "ima-llm-ready" if llm_ok else "ima-llm-off"
    llm_text = "就绪" if llm_ok else "未配置"
    st.markdown(f"""
    <div class="ima-llm-status {llm_cls}">
        <span class="ima-llm-dot"></span>
        <span>LLM {llm_text}</span>
    </div>
    """, unsafe_allow_html=True)


# ---- 路由到页面 ----
def main() -> None:
    module_name = PAGES[_current_key]
    try:
        import importlib
        mod = importlib.import_module(module_name)
        mod.render(storage)
    except Exception as e:
        st.error(f"页面加载失败: {e}")
        st.exception(e)


if __name__ == "__main__":
    main()
