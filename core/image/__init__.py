"""图像生成子模块：封装 Agnes Image 2.1 Flash API。

提供：
- text_to_image: 文生图
- doc_to_image: 基于文档内容生图（增强 prompt）
- daily_card: 生成每日知识卡片
"""
from core.image.generator import ImageGenerator, ImageError

__all__ = ["ImageGenerator", "ImageError"]
