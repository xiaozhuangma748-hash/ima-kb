"""Stratified Silence — 地层美学全局主题 CSS。

基于 Stratified Silence 设计哲学：
- 深褐暖色调地质背景（#1a1816）
- 地层纹理的卡片和面板
- Anthropic 品牌色系（橙 #d97757、蓝 #6a9bcc、绿 #788c5d）
- Georgia 衬线字体为主，SF Mono 等宽为辅
- 锐利直角，0 圆角
- 极致克制的标本式标注排版
- 大量留白 + 清晰地质层级

在 app.py 中通过 st.markdown(theme_css(), unsafe_allow_html=True) 注入。
"""
from __future__ import annotations

STRATIFIED_CSS = r"""
<!-- ========== STRATIFIED SILENCE THEME ========== -->
<style>
@import url('https://fonts.googleapis.com/css2?family=Georgia:wght@400;500;600;700&display=swap');

/* === 全局变量 === */
:root {
    --ss-bg-primary: #1a1816;
    --ss-bg-secondary: #2a2520;
    --ss-bg-tertiary: #3d352c;
    --ss-bg-card: #2e2822;
    --ss-bg-card-hover: #3a322a;
    --ss-bg-input: #1e1b18;
    --ss-bg-elevated: #342e28;

    --ss-text-primary: #e8e6dc;
    --ss-text-secondary: #b0aea5;
    --ss-text-tertiary: #8a8070;
    --ss-text-muted: #5c5245;

    --ss-accent-orange: #d97757;
    --ss-accent-orange-muted: rgba(217, 119, 87, 0.15);
    --ss-accent-orange-border: rgba(217, 119, 87, 0.3);
    --ss-accent-blue: #6a9bcc;
    --ss-accent-blue-muted: rgba(106, 155, 204, 0.15);
    --ss-accent-green: #788c5d;
    --ss-accent-green-muted: rgba(120, 140, 93, 0.15);

    --ss-border: rgba(255, 255, 255, 0.06);
    --ss-border-subtle: rgba(255, 255, 255, 0.03);
    --ss-border-hover: rgba(255, 255, 255, 0.1);
    --ss-border-accent: rgba(217, 119, 87, 0.25);

    --ss-shadow-sm: 0 1px 3px rgba(0, 0, 0, 0.3);
    --ss-shadow-md: 0 2px 8px rgba(0, 0, 0, 0.4);
    --ss-shadow-accent: 0 2px 12px rgba(217, 119, 87, 0.15);

    --ss-font-serif: 'Georgia', 'New York', 'Times New Roman', serif;
    --ss-font-mono: 'SF Mono', 'Menlo', 'Consolas', monospace;

    --ss-transition: 0.2s ease;
}

/* === 基础字体：Georgia 衬线 === */
.stApp, .stApp p, .stApp span, .stApp div, .stApp li,
.stApp label, .stApp th, .stApp td, .stApp caption,
.stApp button, .stApp input, .stApp select, .stApp textarea {
    font-family: var(--ss-font-serif) !important;
    letter-spacing: 0.01em !important;
}

/* === 标题层级：地质标注风格 === */
.stApp h1 {
    font-size: 26px !important;
    font-weight: 700 !important;
    color: var(--ss-text-primary) !important;
    padding-bottom: 16px !important;
    border-bottom: 1px solid var(--ss-border) !important;
    margin-bottom: 28px !important;
    letter-spacing: 0.02em !important;
}

.stApp h2, .stApp [data-testid="stSidebar"] h2 {
    font-size: 17px !important;
    font-weight: 600 !important;
    color: var(--ss-text-primary) !important;
    margin-top: 28px !important;
    margin-bottom: 12px !important;
    letter-spacing: 0.015em !important;
}

.stApp h3 {
    font-size: 14px !important;
    font-weight: 600 !important;
    color: var(--ss-text-secondary) !important;
    margin-top: 20px !important;
    margin-bottom: 8px !important;
    letter-spacing: 0.02em !important;
}

.stApp h4 {
    font-size: 12px !important;
    font-weight: 600 !important;
    color: var(--ss-text-tertiary) !important;
    text-transform: uppercase !important;
    letter-spacing: 0.08em !important;
}

/* === 主背景：深褐暖色 + 微妙地层纹理 === */
.stApp {
    background-color: var(--ss-bg-primary) !important;
    color: var(--ss-text-primary) !important;
    background-image:
        repeating-linear-gradient(
            0deg,
            transparent,
            transparent 80px,
            rgba(255, 255, 255, 0.008) 80px,
            rgba(255, 255, 255, 0.008) 81px
        ),
        repeating-linear-gradient(
            0deg,
            transparent,
            transparent 240px,
            rgba(255, 255, 255, 0.015) 240px,
            rgba(255, 255, 255, 0.015) 242px
        ) !important;
    background-attachment: fixed !important;
}

/* === 主内容区 === */
.main .block-container {
    padding-top: 2.5rem !important;
    padding-bottom: 4rem !important;
    padding-left: 3rem !important;
    padding-right: 3rem !important;
    max-width: 1300px !important;
}

/* === Metric 卡片：地层截面质感 === */
.stMetric {
    background: var(--ss-bg-card) !important;
    border: 1px solid var(--ss-border) !important;
    border-top: 2px solid var(--ss-accent-orange-muted) !important;
    border-radius: 0px !important;
    padding: 20px 22px !important;
    box-shadow: var(--ss-shadow-sm),
        inset 0 1px 0 rgba(255, 255, 255, 0.03),
        inset 0 -1px 0 rgba(0, 0, 0, 0.15) !important;
    transition: all var(--ss-transition) !important;
    position: relative !important;
}

.stMetric::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 2px;
    background: var(--ss-accent-orange);
    opacity: 0;
    transition: opacity var(--ss-transition);
}

.stMetric:hover {
    border-color: var(--ss-border-hover) !important;
    background-color: var(--ss-bg-card-hover) !important;
}

.stMetric:hover::before {
    opacity: 1;
}

.stMetricLabel {
    color: var(--ss-text-tertiary) !important;
    font-size: 10px !important;
    font-weight: 600 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.1em !important;
    margin-bottom: 8px !important;
}

.stMetricValue {
    color: var(--ss-text-primary) !important;
    font-size: 22px !important;
    font-weight: 700 !important;
    letter-spacing: -0.01em !important;
}

/* === 列间距 === */
div[data-testid="stHorizontalBlock"] {
    gap: 20px !important;
}

/* === 按钮：标本标签风格 === */
.stButton > button {
    font-family: var(--ss-font-serif) !important;
    font-size: 13px !important;
    font-weight: 600 !important;
    letter-spacing: 0.03em !important;
    border: 1px solid var(--ss-border) !important;
    border-radius: 0px !important;
    padding: 10px 22px !important;
    cursor: pointer !important;
    transition: all var(--ss-transition) !important;
    line-height: 1.4 !important;
    position: relative !important;
}

.stButton > button[kind="primary"],
.stButton > button[data-testid="stFormSubmitButton"] {
    background: var(--ss-accent-orange) !important;
    color: #1a1816 !important;
    border-color: #c06840 !important;
    box-shadow: var(--ss-shadow-accent) !important;
}

.stButton > button[kind="primary"]:hover,
.stButton > button[data-testid="stFormSubmitButton"]:hover {
    background: #e0865f !important;
    transform: translateY(-1px) !important;
    box-shadow: 0 4px 16px rgba(217, 119, 87, 0.25) !important;
}

.stButton > button[kind="primary"]:active,
.stButton > button[data-testid="stFormSubmitButton"]:active {
    transform: translateY(0) !important;
    box-shadow: var(--ss-shadow-sm) !important;
}

.stButton > button[kind="secondary"] {
    background-color: var(--ss-bg-card) !important;
    color: var(--ss-text-secondary) !important;
}

.stButton > button[kind="secondary"]:hover {
    background-color: var(--ss-bg-card-hover) !important;
    color: var(--ss-text-primary) !important;
    border-color: var(--ss-border-hover) !important;
}

/* === 输入框：深色岩层质感 === */
.stTextInput > div > div > input,
.stTextArea > div > div > textarea,
.stNumberInput > div > div > input,
.stSelectbox > div > div > select {
    font-family: var(--ss-font-serif) !important;
    font-size: 13px !important;
    background-color: var(--ss-bg-input) !important;
    color: var(--ss-text-primary) !important;
    border: 1px solid var(--ss-border) !important;
    border-radius: 0px !important;
    padding: 10px 14px !important;
    box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.2) !important;
    transition: all var(--ss-transition) !important;
}

.stTextInput > div > div > input:focus,
.stTextArea > div > div > textarea:focus,
.stNumberInput > div > div > input:focus {
    border-color: var(--ss-accent-orange) !important;
    box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.2), 0 0 0 2px var(--ss-accent-orange-muted) !important;
}

/* === 文件上传 === */
.stFileUploader > div > div {
    background-color: var(--ss-bg-card) !important;
    border: 1px dashed var(--ss-border-hover) !important;
    border-radius: 0px !important;
    padding: 32px !important;
    transition: all var(--ss-transition) !important;
}

.stFileUploader > div > div:hover {
    border-color: var(--ss-accent-orange-border) !important;
    background-color: var(--ss-bg-card-hover) !important;
}

/* === 数据表格：地质编目风格 === */
.stDataFrame {
    border: 1px solid var(--ss-border) !important;
    border-radius: 0px !important;
    overflow: hidden !important;
}

.stDataFrame table {
    border-collapse: collapse !important;
}

.stDataFrame th {
    background-color: var(--ss-bg-tertiary) !important;
    color: var(--ss-text-secondary) !important;
    border: none !important;
    border-bottom: 2px solid var(--ss-border) !important;
    font-size: 10px !important;
    font-weight: 700 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.08em !important;
    padding: 12px 16px !important;
    white-space: nowrap !important;
}

.stDataFrame td {
    background-color: var(--ss-bg-card) !important;
    color: var(--ss-text-primary) !important;
    border: none !important;
    border-bottom: 1px solid var(--ss-border-subtle) !important;
    padding: 10px 16px !important;
    font-size: 13px !important;
}

.stDataFrame tr:hover td {
    background-color: var(--ss-bg-card-hover) !important;
}

.stDataFrame tr:last-child td {
    border-bottom: none !important;
}

/* === Divider：地层不整合面 === */
hr, .stDivider {
    border: none !important;
    border-top: 1px solid var(--ss-border) !important;
    margin: 32px 0 !important;
    box-shadow: none !important;
}

/* === Expander === */
.streamlit-expanderHeader {
    font-size: 13px !important;
    font-weight: 600 !important;
    letter-spacing: 0.04em !important;
    background-color: var(--ss-bg-card) !important;
    border: 1px solid var(--ss-border) !important;
    border-left: 2px solid var(--ss-accent-orange-muted) !important;
    border-radius: 0px !important;
    color: var(--ss-text-primary) !important;
    padding: 14px 18px !important;
}

.streamlit-expanderHeader:hover {
    background-color: var(--ss-bg-card-hover) !important;
    border-left-color: var(--ss-accent-orange) !important;
}

[data-testid="stSidebar"] details,
.streamlit-expanderDetails {
    border: 1px solid var(--ss-border) !important;
    border-radius: 0px !important;
}

/* === Tab：地层标签 === */
.stTabs [data-baseweb="tab-list"] {
    gap: 0px !important;
}

.stTabs [data-baseweb="tab"] {
    font-family: var(--ss-font-serif) !important;
    font-size: 12px !important;
    font-weight: 600 !important;
    letter-spacing: 0.05em !important;
    text-transform: uppercase !important;
    background-color: transparent !important;
    border: 1px solid transparent !important;
    border-bottom: none !important;
    border-radius: 0px !important;
    color: var(--ss-text-muted) !important;
    padding: 10px 20px !important;
    transition: all var(--ss-transition) !important;
}

.stTabs [data-baseweb="tab"]:hover {
    color: var(--ss-text-secondary) !important;
    background-color: var(--ss-bg-card) !important;
}

.stTabs [aria-selected="true"] {
    background: var(--ss-bg-card) !important;
    color: var(--ss-accent-orange) !important;
    border-color: var(--ss-border) !important;
}

.stTabs [data-baseweb="tab-highlight"] {
    background: var(--ss-accent-orange) !important;
    height: 2px !important;
}

.stTabs [data-baseweb="tab-content"] {
    border: 1px solid var(--ss-border) !important;
    border-top: 2px solid var(--ss-accent-orange) !important;
    border-radius: 0px !important;
    padding: 24px !important;
    background-color: var(--ss-bg-primary) !important;
}

/* === Alert === */
.stAlert {
    border-radius: 0px !important;
    border: 1px solid !important;
    border-left: 3px solid !important;
    box-shadow: var(--ss-shadow-sm) !important;
    padding: 14px 18px !important;
}

[data-testid="stAlert"] {
    background-color: var(--ss-bg-card) !important;
}

.stAlert[data-baseweb="notification"][kind="info"] {
    border-color: rgba(106, 155, 204, 0.3) !important;
    border-left-color: var(--ss-accent-blue) !important;
}

.stAlert[data-baseweb="notification"][kind="success"] {
    border-color: rgba(120, 140, 93, 0.3) !important;
    border-left-color: var(--ss-accent-green) !important;
}

.stAlert[data-baseweb="notification"][kind="warning"] {
    border-color: rgba(217, 119, 87, 0.3) !important;
    border-left-color: var(--ss-accent-orange) !important;
}

.stAlert[data-baseweb="notification"][kind="error"] {
    border-color: rgba(200, 80, 80, 0.3) !important;
    border-left-color: #c85050 !important;
}

/* === 容器 (border=True) === */
.stContainer {
    border: 1px solid var(--ss-border) !important;
    border-left: 2px solid var(--ss-accent-orange-muted) !important;
    border-radius: 0px !important;
    padding: 18px 20px !important;
    margin-bottom: 12px !important;
    background-color: var(--ss-bg-card) !important;
    transition: all var(--ss-transition) !important;
}

.stContainer:hover {
    border-left-color: var(--ss-accent-orange) !important;
}

/* === Chat === */
.stChatMessage {
    background-color: var(--ss-bg-card) !important;
    border: 1px solid var(--ss-border) !important;
    border-radius: 0px !important;
    padding: 18px 22px !important;
    margin-bottom: 12px !important;
}

.stChatMessage[data-testid="stChatMessage-user"] {
    border-left: 2px solid var(--ss-accent-orange) !important;
    background-color: var(--ss-bg-secondary) !important;
}

.stChatMessage[data-testid="stChatMessage-assistant"] {
    border-left: 2px solid var(--ss-accent-green) !important;
    background-color: var(--ss-bg-primary) !important;
}

.stChatInputContainer textarea {
    font-family: var(--ss-font-serif) !important;
    font-size: 13px !important;
    background-color: var(--ss-bg-input) !important;
    color: var(--ss-text-primary) !important;
    border: 1px solid var(--ss-border) !important;
    border-radius: 0px !important;
    padding: 14px 18px !important;
}

.stChatInputContainer textarea:focus {
    border-color: var(--ss-accent-orange) !important;
    box-shadow: 0 0 0 2px var(--ss-accent-orange-muted) !important;
}

/* === Progress === */
.stProgress > div > div > div {
    background: var(--ss-accent-orange) !important;
    border-radius: 0px !important;
}

/* === Spinner === */
.stSpinner > div {
    border-color: var(--ss-border) !important;
    border-top-color: var(--ss-accent-orange) !important;
}

/* === Caption：标本标注 === */
.stCaption, .stCaption p {
    color: var(--ss-text-muted) !important;
    font-size: 11px !important;
    font-family: var(--ss-font-mono) !important;
    letter-spacing: 0.04em !important;
    line-height: 1.5 !important;
    margin-top: 4px !important;
}

/* === 正文段落 === */
.stApp .stMarkdown p,
.stApp .stWrite p {
    font-size: 14px !important;
    line-height: 1.85 !important;
    color: var(--ss-text-primary) !important;
    margin-bottom: 10px !important;
}

/* === Code Block === */
.stCodeBlock {
    background-color: var(--ss-bg-primary) !important;
    border: 1px solid var(--ss-border) !important;
    border-radius: 0px !important;
    padding: 14px !important;
}

pre, code {
    font-family: var(--ss-font-mono) !important;
    font-size: 12px !important;
}

/* === Chart === */
.stAreaChart, .stBarChart {
    border: 1px solid var(--ss-border) !important;
    border-radius: 0px !important;
}

/* === Download Button === */
.stDownloadButton > button {
    font-size: 11px !important;
    font-weight: 600 !important;
    font-family: var(--ss-font-mono) !important;
    letter-spacing: 0.05em !important;
    border: 1px solid var(--ss-accent-orange-border) !important;
    border-radius: 0px !important;
    background: var(--ss-accent-orange-muted) !important;
    color: var(--ss-accent-orange) !important;
    padding: 8px 18px !important;
}

/* === Selectbox === */
.stSelectbox > div > div {
    background-color: var(--ss-bg-input) !important;
    border: 1px solid var(--ss-border) !important;
    border-radius: 0px !important;
}

/* === Scrollbar：岩层纹理 === */
::-webkit-scrollbar {
    width: 8px;
    height: 8px;
}

::-webkit-scrollbar-track {
    background: var(--ss-bg-primary);
}

::-webkit-scrollbar-thumb {
    background: var(--ss-bg-tertiary);
    border: 1px solid var(--ss-border);
}

::-webkit-scrollbar-thumb:hover {
    background: var(--ss-bg-card-hover);
}

::-webkit-scrollbar-corner {
    background: var(--ss-bg-primary);
}

/* === 顶部装饰线：地质标记 === */
.stApp::before {
    content: '';
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    height: 2px;
    background: var(--ss-accent-orange);
    z-index: 9999;
    opacity: 0.6;
}

/* ========== STRATIFIED SILENCE ICON NAV (侧边栏) ========== */

/* 侧边栏整体 */
section[data-testid="stSidebar"] {
    width: 72px !important;
    min-width: 72px !important;
    padding: 0 !important;
    display: flex !important;
    flex-direction: column !important;
    align-items: center !important;
    overflow: hidden !important;
    background: linear-gradient(180deg, #221f1b 0%, #1a1816 100%) !important;
    border-right: 1px solid var(--ss-border) !important;
}

section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
    width: 100% !important;
    padding: 0 !important;
}

section[data-testid="stSidebar"] [data-testid="stSidebarContent"] > div {
    width: 100% !important;
    padding: 0 6px !important;
}

section[data-testid="stSidebar"] [data-testid="stSidebarContent"] > div > div > div {
    padding-left: 0 !important;
    padding-right: 0 !important;
}

/* 图标导航容器 */
.ima-icon-nav {
    display: flex;
    flex-direction: column;
    align-items: center;
    width: 100%;
    padding-top: 16px;
    padding-bottom: 16px;
    gap: 4px;
}

.ima-nav-brand {
    display: flex;
    flex-direction: column;
    align-items: center;
    margin-bottom: 12px;
}

.ima-nav-logo {
    width: 40px;
    height: 40px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 0px !important;
    background: var(--ss-bg-tertiary) !important;
    border: 1px solid var(--ss-border) !important;
    transition: all var(--ss-transition);
}

.ima-nav-logo:hover {
    border-color: var(--ss-accent-orange-border) !important;
}

.ima-nav-divider {
    width: 32px;
    height: 1px;
    background: var(--ss-border);
    margin: 8px 0;
}

.ima-nav-item {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    width: 52px;
    height: 52px;
    border-radius: 0px !important;
    text-decoration: none;
    cursor: pointer;
    transition: all var(--ss-transition);
    gap: 3px;
    color: var(--ss-text-muted);
    border: 1px solid transparent !important;
}

.ima-nav-item:hover {
    background: var(--ss-bg-card) !important;
    color: var(--ss-text-secondary);
    border-color: var(--ss-border) !important;
}

.ima-nav-item-active {
    background: var(--ss-accent-orange-muted) !important;
    color: var(--ss-accent-orange) !important;
    border-color: var(--ss-accent-orange-border) !important;
}

.ima-nav-icon {
    font-size: 18px;
    line-height: 1;
}

.ima-nav-label {
    font-family: var(--ss-font-mono) !important;
    font-size: 8px !important;
    font-weight: 500;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    white-space: nowrap;
}

.ima-nav-spacer {
    flex: 1;
    min-height: 24px;
}

.ima-nav-footer {
    display: flex;
    flex-direction: column;
    align-items: center;
    margin-top: 8px;
}

.ima-nav-status {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
}

.ima-status-dot {
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background: var(--ss-accent-green);
}

.ima-status-text {
    font-family: var(--ss-font-mono) !important;
    font-size: 7px !important;
    color: var(--ss-text-muted);
    letter-spacing: 0.1em;
    text-transform: uppercase;
}

/* 侧边栏统计 */
.ima-sidebar-stats {
    margin-top: 12px;
    padding: 0 4px;
    width: 100%;
}

.ima-stat-row {
    display: flex;
    justify-content: center;
    gap: 8px;
    margin-bottom: 4px;
}

.ima-stat-item {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;
}

.ima-stat-label {
    font-family: var(--ss-font-mono) !important;
    font-size: 7px !important;
    color: var(--ss-text-muted);
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.08em;
}

.ima-stat-value {
    font-family: var(--ss-font-serif) !important;
    font-size: 13px !important;
    color: var(--ss-text-primary);
    font-weight: 700;
    letter-spacing: -0.01em;
}

/* LLM 状态 */
.ima-llm-status {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px solid var(--ss-border);
    font-family: var(--ss-font-mono) !important;
    font-size: 7px !important;
    color: var(--ss-text-muted);
    letter-spacing: 0.08em;
    text-transform: uppercase;
}

.ima-llm-dot {
    width: 5px;
    height: 5px;
    border-radius: 50%;
}

.ima-llm-ready .ima-llm-dot {
    background: var(--ss-accent-green);
}

.ima-llm-off .ima-llm-dot {
    background: #c85050;
}
</style>
"""


def theme_css() -> str:
    """返回 Stratified Silence 地层美学主题 CSS。"""
    return STRATIFIED_CSS
