"""配置中心：统一管理所有配置项。

从 .env 文件加载配置，提供全局访问。
"""
from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass, field

from dotenv import load_dotenv

# 加载 .env 文件（如果存在）
load_dotenv()

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.resolve()


def _get_env(key: str, default: str = "") -> str:
    """读取环境变量，去掉首尾空白。"""
    return os.getenv(key, default).strip()


@dataclass
class Settings:
    """全局配置。"""

    # ---- LLM (Agnes AI) ----
    agnes_api_key: str = field(default_factory=lambda: _get_env("AGNES_API_KEY"))
    agnes_base_url: str = field(
        default_factory=lambda: _get_env("AGNES_BASE_URL", "https://apihub.agnes-ai.com/v1")
    )
    llm_model: str = field(default_factory=lambda: os.environ.get("LLM_MODEL_OVERRIDE") or _get_env("LLM_MODEL", "agnes-2.0-flash"))

    # ---- 图像生成 (Agnes Image) ----
    image_model: str = field(default_factory=lambda: _get_env("IMAGE_MODEL", "agnes-image-2.1-flash"))
    image_size: str = field(default_factory=lambda: _get_env("IMAGE_SIZE", "1024x1024"))
    image_response_format: str = field(default_factory=lambda: _get_env("IMAGE_RESPONSE_FORMAT", "url"))

    # ---- 存储 ----
    storage_path: Path = field(
        default_factory=lambda: PROJECT_ROOT / _get_env("STORAGE_PATH", "./storage")
    )

    # ---- 分块 ----
    chunk_size: int = field(default_factory=lambda: int(_get_env("CHUNK_SIZE", "512")))
    chunk_overlap: int = field(default_factory=lambda: int(_get_env("CHUNK_OVERLAP", "64")))

    # ---- RAG ----
    rag_top_k: int = field(default_factory=lambda: int(_get_env("RAG_TOP_K", "6")))
    llm_max_tokens: int = field(default_factory=lambda: int(_get_env("LLM_MAX_TOKENS", "1024")))

    # ---- Parent-Document 上下文扩展 ----
    # 检索时用小 chunk 匹配，返回时附加前后各 N 个相邻 chunk 作为上下文
    # 0 表示关闭，1 表示前后各 1 个（共 3 个 chunk 的上下文）
    parent_window: int = field(default_factory=lambda: int(_get_env("PARENT_WINDOW", "1")))

    # ---- Context 压缩 ----
    # 每个 chunk content 传给 LLM 时的最大字符数，超过时保留首尾各一半
    # 0 表示不压缩（适用于 parent_window 扩展后 content 较长的场景）
    context_max_chars: int = field(default_factory=lambda: int(_get_env("CONTEXT_MAX_CHARS", "800")))

    # ---- 对话记忆 ----
    # 进入 LLM prompt 的最近消息条数（1 轮 = user + assistant 2 条）
    # 8 轮 = 16 条是 token 与上下文的平衡点
    history_window: int = field(default_factory=lambda: int(_get_env("HISTORY_WINDOW", "16")))
    # 触发摘要压缩的阈值（history 超过此值就压缩早期对话）
    # 建议 = history_window * 1.5（窗口 16 → 阈值 24）
    history_compress_threshold: int = field(default_factory=lambda: int(_get_env("HISTORY_COMPRESS_THRESHOLD", "24")))
    # 摘要最大字符数（控制 token 成本）
    summary_max_chars: int = field(default_factory=lambda: int(_get_env("SUMMARY_MAX_CHARS", "500")))
    # 是否启用历史感知检索（用 summary 扩展 query 提升多轮对话召回率）
    history_aware_retrieval: bool = field(default_factory=lambda: _get_env("HISTORY_AWARE_RETRIEVAL", "1") == "1")

    # ---- Reranker ----
    # 重排序器类型：cross_encoder（专用模型，推荐）/ llm（LLM prompt 打分）/ none
    reranker_type: str = field(default_factory=lambda: _get_env("RERANKER_TYPE", "cross_encoder"))
    # Cross-Encoder 模型名称（BAAI/bge-reranker-v2-m3 中英多语言，1.1B 参数）
    reranker_model: str = field(default_factory=lambda: _get_env("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3"))
    # 重排序候选数（top_n）：最终返回给 LLM 的资料条数
    reranker_top_n: int = field(default_factory=lambda: int(_get_env("RERANKER_TOP_N", "5")))

    @property
    def uploads_dir(self) -> Path:
        """原文件存储目录。"""
        return self.storage_path / "uploads"

    @property
    def chroma_dir(self) -> Path:
        """ChromaDB 持久化目录，由 VectorIndex 使用。"""
        return self.storage_path / "chroma"

    @property
    def memory_path(self) -> Path:
        """记忆数据文件路径。"""
        return self.storage_path / "memory.json"

    @property
    def db_path(self) -> Path:
        """元数据 SQLite 文件路径。"""
        return self.storage_path / "metadata.db"

    @property
    def cache_dir(self) -> Path:
        """解析缓存目录。"""
        return self.storage_path / "cache"

    @property
    def bm25_index_path(self) -> Path:
        """BM25 索引文件路径。"""
        return self.storage_path / "bm25_index.pkl"

    @property
    def images_dir(self) -> Path:
        """生成的图片存储目录。"""
        return self.storage_path / "images"

    def ensure_dirs(self) -> None:
        """创建所有必要的存储目录。"""
        for d in (self.storage_path, self.uploads_dir, self.chroma_dir, self.cache_dir, self.images_dir):
            d.mkdir(parents=True, exist_ok=True)

    def has_llm(self) -> bool:
        """是否配置了 LLM Key。"""
        return bool(self.agnes_api_key and not self.agnes_api_key.startswith("sk-xxx"))

    def is_configured(self) -> bool:
        """检查是否已完成首次配置（.env 存在且 AGNES_API_KEY 非占位值）。"""
        env_path = PROJECT_ROOT / ".env"
        if not env_path.exists():
            return False
        key = os.environ.get("AGNES_API_KEY", "")
        # 占位值检查：空、"sk-xxx"、"your-api-key" 等
        if not key or key in ("sk-xxx", "your-api-key", "YOUR_API_KEY"):
            return False
        return True


# 全局配置单例
settings = Settings()
