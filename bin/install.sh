#!/usr/bin/env bash
# ============================================================
# IMA 个人知识库 · 一键安装脚本  v5.0
# ============================================================
# 用法：
#   curl -fsSL <RAW_URL> | bash           # 远程一键安装
#   ./install.sh                           # 本地安装（全功能推荐）
#   ./install.sh --minimal                 # 最小安装（跳过向量/OCR）
#   ./install.sh --key sk-xxx              # 安装时直接配置 API Key
# ============================================================

set +e  # 不因单个错误退出，各步骤自行处理

# ---- 颜色 ----
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

# ---- 参数 ----
MINIMAL=false
API_KEY=""
OCR_ARG=false
VECTOR_ARG=true

for arg in "$@"; do
    case $arg in
        --minimal)    MINIMAL=true; OCR_ARG=false; VECTOR_ARG=false ;;
        --key)        shift; API_KEY="$1"; shift 2>/dev/null ;;
        --key=*)      API_KEY="${arg#*=}" ;;
        --no-vector)  VECTOR_ARG=false ;;
        --ocr)        OCR_ARG=true ;;
        --help|-h)
            echo "用法: ./install.sh [选项]"
            echo ""
            echo "选项:"
            echo "  --minimal       最小安装（只装核心依赖）"
            echo "  --key sk-xxx    直接设置 API Key（跳过交互询问）"
            echo "  --ocr           同时装 OCR（需系统有 tesseract）"
            echo "  --no-vector     跳过向量检索依赖"
            echo "  --help          显示帮助"
            exit 0 ;;
    esac
done

# ---- 定位项目目录 ----
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo -e "${CYAN}${BOLD}  📚  IMA 个人知识库 · 安装中...  v5.0${NC}"
echo -e "${DIM}  目录: $SCRIPT_DIR${NC}"
echo ""

# ============================================================
# 步骤函数
# ============================================================
_step=0
_step_pass() { _step=$((_step+1)); echo ""; echo -e "${BOLD}[${_step}/6] $1${NC}"; }
_done()      { echo -e "  ${GREEN}✓${NC} $1"; }
_skip()      { echo -e "  ${YELLOW}○${NC} $1"; }
_warn()      { echo -e "  ${YELLOW}⚠${NC} $1"; }
_fail()      { echo -e "  ${RED}✗${NC} $1"; }
_info()      { echo -e "  ${DIM}$1${NC}"; }
_spinner_pid=""

_spin_start() {
    local chars="/-\\|"
    local delay=0.1
    (
        local i=0
        while true; do
            printf "\r  ${DIM}[%c]${NC} %s" "${chars:$i:1}" "$1" >&2
            i=$(( (i+1) % ${#chars} ))
            sleep $delay
        done
    ) &
    _spinner_pid=$!
}

_spin_stop() {
    if [ -n "$_spinner_pid" ]; then
        kill "$_spinner_pid" 2>/dev/null
        wait "$_spinner_pid" 2>/dev/null
        printf "\r\033[K" >&2
        _spinner_pid=""
    fi
}

# ============================================================
# [1/6] 检查 Python + 系统依赖
# ============================================================
_step_pass "检查系统环境"

PYTHON=""
for cmd in python3 python3.12 python3.11 python3.10 python3.9; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null)
        ok=$("$cmd" -c 'import sys; print(1 if sys.version_info >= (3,9) else 0)' 2>/dev/null)
        if [ "$ok" = "1" ]; then
            PYTHON="$cmd"
            PY_VER="$ver"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    _fail "未找到 Python 3.9+，正在尝试安装..."
    if command -v brew &>/dev/null; then
        _info "通过 Homebrew 安装 Python 3.12..."
        if brew install python@3.12 --quiet 2>/dev/null; then
            PYTHON="python3.12"
            PY_VER="3.12"
            _done "Python 3.12 安装完成"
        else
            _fail "Homebrew 安装 Python 失败"
            echo -e "  ${YELLOW}请手动安装: brew install python@3.12${NC}"
            exit 1
        fi
    else
        _fail "请安装 Python 3.9+"
        echo -e "  ${YELLOW}https://www.python.org/downloads/${NC}"
        exit 1
    fi
else
    _done "Python ${PY_VER} ($PYTHON)"
fi

# 检测 tesseract 状态（仅提示）
if command -v tesseract &>/dev/null; then
    _done "Tesseract OCR 已就绪"
else
    if [ "$OCR_ARG" = "true" ]; then
        _warn "OCR 需要 tesseract，正在通过 Homebrew 安装..."
        if command -v brew &>/dev/null; then
            brew install tesseract tesseract-lang --quiet 2>/dev/null && _done "tesseract 安装完成" || _warn "tesseract 安装失败，图片/扫描 PDF 入库时将跳过"
        else
            _warn "未安装 Homebrew，OCR 不可用（不影响其他功能）"
        fi
    else
        _info "未检测到 tesseract（OCR 不可用，不影响其他功能）"
    fi
fi

# ============================================================
# [2/6] 创建虚拟环境
# ============================================================
_step_pass "创建虚拟环境"

if [ ! -d ".venv" ]; then
    if $PYTHON -m venv .venv 2>/dev/null; then
        _done ".venv 创建完成"
    else
        _fail "虚拟环境创建失败"
        exit 1
    fi
else
    _skip ".venv 已存在，跳过"
fi

# 激活
source .venv/bin/activate 2>/dev/null
if [ $? -eq 0 ]; then
    _done "虚拟环境已激活"
else
    _fail "虚拟环境激活失败"
    exit 1
fi

# ============================================================
# [3/6] 安装依赖
# ============================================================
_step_pass "安装 Python 依赖"

# 升级 pip（静默）
_spin_start "升级 pip..."
python -m pip install --upgrade pip --quiet 2>/dev/null
_spin_stop
_done "pip 已更新"

# 核心依赖（带进度）
_spin_start "安装核心依赖（pandas/PyMuPDF/openai/click/rich/fastapi...）"
if pip install -r requirements.txt --quiet --progress-bar off 2>/dev/null; then
    _spin_stop; _done "核心依赖安装完成"
else
    _spin_stop; _fail "核心依赖安装失败，尝试不跳过已安装的包..."
    pip install -r requirements.txt --quiet 2>/dev/null && _done "核心依赖安装完成" || _warn "部分依赖安装失败，请检查网络"
fi

# 注册 ima 命令
_spin_start "注册 ima 命令..."
if pip install -e . --quiet 2>/dev/null; then
    _spin_stop; _done "ima 命令已注册"
else
    _spin_stop; _warn "ima 命令注册失败，可用 python run.py 替代"
fi

# 向量检索依赖（默认安装）
if [ "$MINIMAL" = "false" ] && [ "$VECTOR_ARG" = "true" ]; then
    _spin_start "安装向量检索依赖（chromadb + sentence-transformers，约 2GB）..."
    if pip install chromadb sentence-transformers --quiet --progress-bar off 2>/dev/null; then
        _spin_stop; _done "向量检索依赖安装完成"
    else
        _spin_stop; _warn "向量检索依赖安装失败，将降级为纯 BM25（功能正常）"
    fi
else
    _skip "跳过向量检索依赖（--minimal 或 --no-vector）"
fi

# OCR 依赖
if [ "$OCR_ARG" = "true" ]; then
    _spin_start "安装 OCR 依赖（pytesseract）..."
    if pip install "pytesseract>=0.3.10" --quiet 2>/dev/null; then
        _spin_stop; _done "OCR 依赖安装完成"
    else
        _spin_stop; _warn "OCR 依赖安装失败"
    fi
fi

# ============================================================
# [4/6] 配置 .env
# ============================================================
_step_pass "配置环境变量"

if [ -f ".env" ] && ! grep -q "sk-在这里填入你的key" .env 2>/dev/null; then
    _skip ".env 已配置，跳过"
else
    # 生成 .env 模板
    cat > .env <<'ENVEOF'
# IMA 个人知识库 · 环境配置
# LLM + 图像生成 API（Agnes AI，两功能共用一个 Key）
AGNES_API_KEY=sk-在这里填入你的key
AGNES_BASE_URL=https://apihub.agnes-ai.com/v1
LLM_MODEL=agnes-2.0-flash
IMAGE_MODEL=agnes-image-2.1-flash

# 存储路径（默认项目目录下）
STORAGE_PATH=./storage

# 分块参数
CHUNK_SIZE=512
CHUNK_OVERLAP=64

# RAG 参数
RAG_TOP_K=6
LLM_MAX_TOKENS=1024
ENVEOF

    _done ".env 已生成"

    # 如果用户传了 --key，直接写入
    if [ -n "$API_KEY" ]; then
        if [[ "$API_KEY" == sk-* ]] || [[ "$API_KEY" == ag-* ]]; then
            # macOS sed 需要 "" 做原地替换
            sed -i "" "s|AGNES_API_KEY=.*|AGNES_API_KEY=$API_KEY|" .env 2>/dev/null || \
            sed -i "s|AGNES_API_KEY=.*|AGNES_API_KEY=$API_KEY|" .env
            _done "API Key 已配置"
        else
            _warn "Key 格式异常（应以 sk- 或 ag- 开头），请手动检查 .env"
        fi
    else
        echo ""
        echo -e "  ${BOLD}请输入 Agnes AI 的 API Key${NC}"
        echo -e "  ${DIM}（获取地址: https://agnes-ai.com，直接回车跳过，稍后手动编辑 .env）${NC}"
        echo ""
        printf "  API Key: "
        read -r user_key

        if [ -n "$user_key" ]; then
            if [[ "$user_key" == sk-* ]] || [[ "$user_key" == ag-* ]]; then
                sed -i "" "s|AGNES_API_KEY=.*|AGNES_API_KEY=$user_key|" .env 2>/dev/null || \
                sed -i "s|AGNES_API_KEY=.*|AGNES_API_KEY=$user_key|" .env
                _done "API Key 已配置"
            else
                _warn "Key 格式异常，已跳过。请手动编辑 .env 文件"
            fi
        else
            _warn "跳过 Key 配置，请稍后编辑 .env 文件"
        fi
    fi
fi

# ============================================================
# [5/6] 注册全局命令
# ============================================================
_step_pass "注册全局命令"

_add_ima_command() {
    local rcfile="$1"
    local marker="# >>> IMA 个人知识库 >>>"
    local marker_end="# <<< IMA 个人知识库 <<<"
    local escaped_dir="${SCRIPT_DIR//\//\\/}"  # 转义路径中的 /

    if [ -f "$rcfile" ] && grep -q "$marker" "$rcfile" 2>/dev/null; then
        return 1  # 已存在
    fi

    cat >> "$rcfile" <<EOF

$marker
# IMA 个人知识库命令（install.sh 自动添加）
ima() {
    local _KB_DIR="$SCRIPT_DIR"
    if [ ! -d "\$_KB_DIR/.venv" ]; then
        echo "虚拟环境不存在，请运行: cd \$_KB_DIR && ./install.sh"
        return 1
    fi
    (
        cd "\$_KB_DIR" || return 1
        source .venv/bin/activate 2>/dev/null
        if [ \$# -eq 0 ]; then
            python run.py chat
        else
            python run.py "\$@"
        fi
    )
}
$marker_end
EOF
    return 0
}

configured=false
shell_name=$(basename "$SHELL" 2>/dev/null || echo "zsh")

case "$shell_name" in
    zsh)
        if _add_ima_command "$HOME/.zshrc"; then
            _done "已添加到 ~/.zshrc"
            configured=true
        else
            _skip "ima 命令已配置"
            configured=true
        fi ;;
    bash)
        if _add_ima_command "$HOME/.bashrc"; then
            _done "已添加到 ~/.bashrc"
            configured=true
        else
            _skip "ima 命令已配置"
            configured=true
        fi ;;
    *)
        _warn "未识别的 shell: $shell_name"
        _info "请手动将 ima 命令添加到你的 shell 配置"
        _info "参考: cat install.sh | grep 'ima()'";;
esac

if [ "$configured" = "true" ]; then
    _info "新开终端后生效，或运行: source ~/.${shell_name}rc"
fi

# ============================================================
# [6/6] 验证
# ============================================================
_step_pass "验证安装"

_spin_start "检查 ima CLI..."
if python run.py --help &>/dev/null; then
    _spin_stop; _done "ima CLI 可用"
else
    _spin_stop; _fail "ima CLI 启动失败"
fi

# ============================================================
# 完成
# ============================================================
echo ""
echo -e "${CYAN}${BOLD}  ═══════════════════════════════════════════════${NC}"
echo -e "${CYAN}${BOLD}        ✅  IMA 安装完成！${NC}"
echo -e "${CYAN}${BOLD}  ═══════════════════════════════════════════════${NC}"
echo ""

# 检查还有哪些需要用户操作
need_action=false

# 检查 Key
if grep -q "sk-在这里填入你的key" .env 2>/dev/null; then
    echo -e "  ${YELLOW}⚠  还需要配置 API Key（编辑 .env 文件）${NC}"
    need_action=true
fi

# 检查 tesseract
if [ "$OCR_ARG" = "true" ] && ! command -v tesseract &>/dev/null; then
    echo -e "  ${YELLOW}⚠  OCR 未就绪（brew install tesseract tesseract-lang）${NC}"
    need_action=true
fi

if [ "$need_action" = "false" ]; then
    echo -e "  ${GREEN}✓  一切就绪！新开终端后即可使用${NC}"
fi

echo ""
echo -e "  ${BOLD}常用命令：${NC}"
echo -e "    ${CYAN}ima${NC}                       进入交互式 REPL"
echo -e "    ${CYAN}ima ingest <文件/目录>${NC}     入库文档"
echo -e "    ${CYAN}ima search <关键词>${NC}       BM25 搜索"
echo -e "    ${CYAN}ima web${NC}                   启动 Web 后台"
echo -e "    ${CYAN}ima --help${NC}                查看所有命令"
echo ""
echo -e "  ${DIM}重新安装/更新: 再次运行 ./install.sh${NC}"
echo ""
