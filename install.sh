#!/usr/bin/env bash
# ============================================================
# IMA 个人知识库 · 一键安装脚本
# ============================================================
# 用法：
#   ./install.sh           # 标准安装
#   ./install.sh --ocr     # 同时装 OCR 支持（扫描 PDF / 图片识别）
#   ./install.sh --vector  # 同时装向量检索依赖（chromadb + sentence-transformers）
#   ./install.sh --dev     # 同时装开发工具
#   ./install.sh --no-venv # 不创建虚拟环境
#
# 流程：
#   1. 检查 Python 版本（>= 3.9）
#   2. 创建 .venv 虚拟环境
#   3. 安装 Python 依赖（pandas/openpyxl 等已自动装）
#   4. 配置 .env（如果没有，会提示填 API Key）
#   5. 配置 ima 全局命令（zsh / bash）
#   6. 验证安装
# ============================================================

set -e  # 任何命令失败立即退出

# ---- 颜色 ----
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'  # No Color

# ---- 参数解析 ----
INSTALL_OCR=false
INSTALL_DEV=false
INSTALL_VECTOR=false
SKIP_VENV=false

for arg in "$@"; do
    case $arg in
        --ocr) INSTALL_OCR=true ;;
        --vector) INSTALL_VECTOR=true ;;
        --dev)  INSTALL_DEV=true ;;
        --no-venv) SKIP_VENV=true ;;
        --help|-h)
            echo "用法: ./install.sh [--ocr] [--vector] [--dev] [--no-venv]"
            echo ""
            echo "选项:"
            echo "  --ocr      同时安装 OCR 支持（pytesseract，需 brew install tesseract）"
            echo "  --vector   同时安装向量检索依赖（chromadb + sentence-transformers）"
            echo "  --dev      同时安装开发工具（pytest 等）"
            echo "  --no-venv  不创建虚拟环境，直接用当前 Python"
            echo "  --help     显示此帮助"
            exit 0
            ;;
        *)
            echo -e "${RED}未知参数: $arg${NC}（用 --help 查看选项）"
            exit 1
            ;;
    esac
done

# ---- 定位项目目录 ----
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo -e "${CYAN}${BOLD}"
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║       📚  IMA 个人知识库 · 安装脚本  v4.0                    ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"
echo "项目目录: $SCRIPT_DIR"
echo ""

# ============================================================
# 1. 检查 Python 版本
# ============================================================
echo -e "${BOLD}[1/6] 检查 Python 环境...${NC}"

if ! command -v python3 &> /dev/null; then
    echo -e "${RED}✗ 未找到 python3，请先安装 Python 3.10+${NC}"
    echo "  macOS: brew install python@3.11"
    exit 1
fi

PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_OK=$(python3 -c 'import sys; print(1 if sys.version_info >= (3, 9) else 0)')

if [ "$PY_OK" != "1" ]; then
    echo -e "${RED}✗ Python 版本过低: $PY_VERSION（需要 3.9+）${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Python $PY_VERSION${NC}"

# ============================================================
# 2. 创建虚拟环境
# ============================================================
if [ "$SKIP_VENV" = "false" ]; then
    echo ""
    echo -e "${BOLD}[2/6] 创建虚拟环境...${NC}"
    if [ -d ".venv" ]; then
        echo -e "${YELLOW}  .venv 已存在，跳过创建${NC}"
    else
        python3 -m venv .venv
        echo -e "${GREEN}✓ 创建 .venv${NC}"
    fi
    # 激活
    source .venv/bin/activate
    echo -e "${GREEN}✓ 已激活虚拟环境${NC}"
else
    echo ""
    echo -e "${BOLD}[2/6] 跳过虚拟环境（--no-venv）${NC}"
fi

# ============================================================
# 3. 安装 Python 依赖
# ============================================================
echo ""
echo -e "${BOLD}[3/6] 安装 Python 依赖...${NC}"

# 升级 pip
python -m pip install --upgrade pip --quiet

# 标准依赖
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt --quiet
    echo -e "${GREEN}✓ 已安装 requirements.txt${NC}"
fi

# 用 pip install -e . 注册 ima 命令入口
pip install -e . --quiet
echo -e "${GREEN}✓ 已注册 ima 命令入口${NC}"

# 可选：OCR
if [ "$INSTALL_OCR" = "true" ]; then
    echo ""
    echo -e "${BOLD}安装 OCR 支持...${NC}"
    pip install "pytesseract>=0.3.10" --quiet
    echo -e "${GREEN}✓ pytesseract 已安装${NC}"
    if ! command -v tesseract &> /dev/null; then
        echo -e "${YELLOW}  ⚠ 未检测到系统 tesseract，请手动安装:${NC}"
        echo -e "  ${CYAN}brew install tesseract tesseract-lang${NC}"
    else
        echo -e "${GREEN}✓ tesseract 已就绪${NC}"
    fi
fi

# 可选：向量检索依赖
if [ "$INSTALL_VECTOR" = "true" ]; then
    echo ""
    echo -e "${BOLD}安装向量检索依赖（chromadb + sentence-transformers）...${NC}"
    pip install chromadb sentence-transformers --quiet
    echo -e "${GREEN}✓ 向量检索依赖已安装${NC}"
else
    echo -e "${YELLOW}ℹ 未安装向量依赖（用 --vector 启用）。将降级为纯 BM25。${NC}"
fi

# 可选：开发工具
if [ "$INSTALL_DEV" = "true" ]; then
    echo ""
    echo -e "${BOLD}安装开发工具...${NC}"
    pip install pytest build --quiet
    echo -e "${GREEN}✓ 开发工具已安装${NC}"
fi

# ============================================================
# 4. 配置 .env
# ============================================================
echo ""
echo -e "${BOLD}[4/6] 配置 .env...${NC}"

if [ -f ".env" ]; then
    echo -e "${YELLOW}  .env 已存在，跳过${NC}"
else
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo -e "${GREEN}✓ 从 .env.example 复制了 .env${NC}"
        echo -e "${YELLOW}  ⚠ 请编辑 .env 填入真实的 AGNES_API_KEY${NC}"
    else
        # 兜底：直接写一个
        cat > .env <<'EOF'
# IMA 个人知识库配置

# LLM API（Agnes AI）
AGNES_API_KEY=sk-在这里填入你的key
AGNES_BASE_URL=https://apihub.agnes-ai.com/v1
LLM_MODEL=agnes-2.0-flash

# 存储路径
STORAGE_PATH=./storage

# 分块参数
CHUNK_SIZE=512
CHUNK_OVERLAP=64
EOF
        echo -e "${GREEN}✓ 已生成 .env${NC}"
        echo -e "${YELLOW}  ⚠ 请编辑 .env 填入真实的 AGNES_API_KEY${NC}"
    fi
fi

# ============================================================
# 5. 配置 ima 全局命令（zsh）
# ============================================================
echo ""
echo -e "${BOLD}[5/6] 配置 ima 全局命令...${NC}"

# 判断当前 shell
SHELL_NAME=$(basename "$SHELL")

if [ "$SHELL_NAME" = "zsh" ]; then
    ZSHRC="$HOME/.zshrc"
    MARKER="# >>> IMA 个人知识库 >>>"
    MARKER_END="# <<< IMA 个人知识库 <<<"

    # 检查是否已经配置过
    if grep -q "$MARKER" "$ZSHRC" 2>/dev/null; then
        echo -e "${YELLOW}  ima 命令已配置过，跳过${NC}"
    else
        # 追加 zsh function 到 ~/.zshrc
        cat >> "$ZSHRC" <<EOF

$MARKER
# IMA 个人知识库命令（install.sh 自动添加）
ima() {
    local KB_DIR="$SCRIPT_DIR"
    if [ ! -d "\$KB_DIR" ]; then
        echo "❌ 知识库目录不存在: \$KB_DIR"
        return 1
    fi
    if [ ! -f "\$KB_DIR/.venv/bin/activate" ]; then
        echo "❌ 虚拟环境不存在，请先在 \$KB_DIR 运行 ./install.sh"
        return 1
    fi
    (
        cd "\$KB_DIR" || return 1
        source .venv/bin/activate
        if [ \$# -eq 0 ]; then
            python run.py chat
        else
            python run.py "\$@"
        fi
    )
}
$MARKER_END
EOF
        echo -e "${GREEN}✓ 已把 ima 命令添加到 ~/.zshrc${NC}"
        echo -e "${YELLOW}  新开终端自动生效，或运行: source ~/.zshrc${NC}"
    fi

elif [ "$SHELL_NAME" = "bash" ]; then
    BASHRC="$HOME/.bashrc"
    MARKER="# >>> IMA 个人知识库 >>>"
    MARKER_END="# <<< IMA 个人知识库 <<<"

    if grep -q "$MARKER" "$BASHRC" 2>/dev/null; then
        echo -e "${YELLOW}  ima 命令已配置过，跳过${NC}"
    else
        cat >> "$BASHRC" <<EOF

$MARKER
ima() {
    local KB_DIR="$SCRIPT_DIR"
    if [ ! -d "\$KB_DIR" ]; then
        echo "❌ 知识库目录不存在: \$KB_DIR"
        return 1
    fi
    if [ ! -f "\$KB_DIR/.venv/bin/activate" ]; then
        echo "❌ 虚拟环境不存在，请先在 \$KB_DIR 运行 ./install.sh"
        return 1
    fi
    (
        cd "\$KB_DIR" || return 1
        source .venv/bin/activate
        if [ \$# -eq 0 ]; then
            python run.py chat
        else
            python run.py "\$@"
        fi
    )
}
$MARKER_END
EOF
        echo -e "${GREEN}✓ 已把 ima 命令添加到 ~/.bashrc${NC}"
        echo -e "${YELLOW}  新开终端自动生效，或运行: source ~/.bashrc${NC}"
    fi

else
    echo -e "${YELLOW}  ⚠ 未识别的 shell: $SHELL_NAME${NC}"
    echo -e "  请手动把 ima-command.zsh 内容加到你的 shell 配置文件"
fi

# ============================================================
# 6. 验证安装
# ============================================================
echo ""
echo -e "${BOLD}[6/6] 验证安装...${NC}"

# 测试 ima --help
if python run.py --help &> /dev/null; then
    echo -e "${GREEN}✓ ima CLI 可用${NC}"
else
    echo -e "${RED}✗ ima CLI 启动失败${NC}"
    echo "  请检查依赖是否装全"
    exit 1
fi

# 测试 stats
if python run.py stats &> /dev/null; then
    echo -e "${GREEN}✓ stats 命令可用${NC}"
else
    echo -e "${YELLOW}  ⚠ stats 命令异常（可能 .env 未配置）${NC}"
fi

# ============================================================
# 完成
# ============================================================
echo ""
echo -e "${CYAN}${BOLD}"
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                                                              ║"
echo "║       ✅  IMA 安装完成！                                      ║"
echo "║                                                              ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# 检查 .env 是否需要配置
ENV_NEED_CONFIG=false
if [ -f ".env" ]; then
    if grep -q "sk-在这里填入你的key" .env 2>/dev/null; then
        ENV_NEED_CONFIG=true
    fi
fi

if [ "$ENV_NEED_CONFIG" = "true" ]; then
    echo -e "${YELLOW}${BOLD}⚠ 重要：还需要配置 API Key${NC}"
    echo ""
    echo -e "  1. ${BOLD}编辑 .env 填入 AGNES_API_KEY${NC}"
    echo -e "     ${CYAN}vim .env${NC}"
    echo -e "     ${DIM}（或用任意编辑器打开 .env 文件）${NC}"
    echo -e "     把 ${BOLD}AGNES_API_KEY=sk-在这里填入你的key${NC} 改成真实的 key"
    echo ""
    echo -e "  2. ${BOLD}新开一个终端窗口${NC}（让 ima 命令生效）"
    echo ""
else
    echo -e "${GREEN}${BOLD}✓ .env 已配置${NC}"
    echo ""
    echo -e "  ${BOLD}新开一个终端窗口${NC}（让 ima 命令生效）"
    echo ""
fi

echo -e "${BOLD}开始使用：${NC}"
echo ""
echo -e "  ${CYAN}ima${NC}                      # 进入交互式 REPL（推荐）"
echo -e "  ${CYAN}ima --help${NC}               # 查看所有命令"
echo -e "  ${CYAN}ima stats${NC}                # 知识库统计"
echo -e "  ${CYAN}ima ingest 路径${NC}          # 入库文件（PDF/Word/Excel/...）"
echo -e "  ${CYAN}ima analyze 文件.xlsx${NC}     # 数据表分析（自动统计+AI 解读）"
echo -e "  ${CYAN}ima search 关键词${NC}        # BM25 搜索"
echo -e "  ${CYAN}ima ask \"问题\"${NC}          # AI 问答"
echo -e "  ${CYAN}ima graph build${NC}          # 构建知识图谱"
echo ""
echo -e "${BOLD}文档：${NC}阅读 HANDOFF.md 了解项目全貌"
echo ""
echo -e "${DIM}重新安装或更新：再次运行 ./install.sh 即可${NC}"
echo ""
