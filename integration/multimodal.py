"""
integration/multimodal.py — 多模态数据处理工具

提供图像编码和 OpenAI Vision API 兼容的消息格式构建。
"""
from __future__ import annotations

import base64
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def encode_image(file_path: str | Path) -> str:
    """
    读取本地图片文件，返回 data URI 格式的 Base64 编码字符串。

    Args:
        file_path: 图片文件路径

    Returns:
        "data:image/png;base64,..." 格式的字符串
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"图片文件不存在: {path}")

    suffix = path.suffix.lower().lstrip(".")
    mime_map = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "webp": "image/webp",
        "bmp": "image/bmp",
    }
    mime_type = mime_map.get(suffix, "image/png")

    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")

    return f"data:{mime_type};base64,{b64}"


def build_multimodal_content(
    text: str,
    images: list[str],
) -> list[dict]:
    """
    构建 OpenAI Vision API 兼容的多模态 content 结构。

    Args:
        text: 文本内容
        images: Base64 编码的图片列表（data URI 或纯 base64 字符串）

    Returns:
        [{"type": "text", "text": "..."}, {"type": "image_url", "image_url": {"url": "..."}}]
    """
    content: list[dict] = [{"type": "text", "text": text}]

    for img in images:
        # 如果不是 data URI 格式，补全前缀
        if not img.startswith("data:"):
            img = f"data:image/png;base64,{img}"

        content.append({
            "type": "image_url",
            "image_url": {"url": img},
        })

    return content
