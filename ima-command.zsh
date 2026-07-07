# ===== IMA 个人知识库 命令配置 =====
# 把这段加到 ~/.zshrc 末尾即可使用 ima 命令
# 用法：
#   ima            进入交互式 CLI 对话
#   ima web        启动 Web 界面（http://localhost:8501）
#   ima search "词" BM25 搜索
#   ima ask "问题"  单次 RAG 问答
#   ima stats       知识库统计
#   ima ingest 路径 入库文件/目录
#   ima --help      查看所有命令
ima() {
    local KB_DIR="/Users/4u/Desktop/项目/拱墅区/2025身后事（殡葬）项目/34-知识库"
    if [ ! -d "$KB_DIR" ]; then
        echo "❌ 知识库目录不存在: $KB_DIR"
        return 1
    fi
    if [ ! -f "$KB_DIR/.venv/bin/activate" ]; then
        echo "❌ 虚拟环境不存在，请先在 $KB_DIR 运行:"
        echo "   python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
        return 1
    fi
    (
        cd "$KB_DIR" || return 1
        source .venv/bin/activate
        if [ $# -eq 0 ]; then
            python run.py chat
        else
            python run.py "$@"
        fi
    )
}
