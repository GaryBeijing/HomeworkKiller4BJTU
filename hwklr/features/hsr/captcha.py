# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-10-31 20:45
# 文件名: captcha.py
# 主要用途: 使用 Pillow 对滑块拼图验证码做模板匹配并求出缺口横向偏移。
# 文件版本: 1.0.0
"""滑块验证码拼图匹配。

与原版纯 Python 逐像素扫描相比，这里把像素差值计算交给 Pillow 的 C 实现
（``ImageChops.difference`` + ``ImageStat``），并只统计拼图块不透明像素，
在保持匹配结果一致的前提下显著降低耗时。
"""
from __future__ import annotations

import base64
import io
from typing import Final, NamedTuple

from PIL import Image, ImageChops, ImageStat

__version__ = "1.0.0"
__all__ = ["CaptchaOffset", "solve_offset"]

# alpha 通道大于该阈值才视为拼图块的有效像素（与原版一致）。
_ALPHA_THRESHOLD: Final[int] = 8


class CaptchaOffset(NamedTuple):
    """拼图匹配结果。"""

    x: int
    y: int
    score: float


def _decode_image(raw_base64: str, mode: str) -> Image.Image:
    """将 Base64 字符串解码为指定模式的图片。

    Args:
        raw_base64: 图片的 Base64 文本。
        mode: 目标 Pillow 模式，如 ``"RGB"``、``"RGBA"``。

    Returns:
        解码后的图片对象。

    Raises:
        ValueError: 数据无法解析为图片时抛出。
    """
    try:
        raw_bytes: bytes = base64.b64decode(raw_base64)
        image: Image.Image = Image.open(io.BytesIO(raw_bytes))
        return image.convert(mode)
    except Exception as exc:  # Pillow 的异常类型较多，统一转为可读错误。
        raise ValueError("验证码图片解析失败: %s" % exc) from exc


def solve_offset(original_base64: str, piece_base64: str) -> CaptchaOffset:
    """计算拼图块在背景图中的最佳匹配位置。

    Args:
        original_base64: 背景图 Base64。
        piece_base64: 拼图块 Base64（带 alpha 通道）。

    Returns:
        最佳匹配的左边缘 x、上边缘 y 与平均像素差分数。

    Raises:
        ValueError: 图片为空、拼图块无有效像素或尺寸异常时抛出。
    """
    original: Image.Image = _decode_image(original_base64, "RGB")
    piece: Image.Image = _decode_image(piece_base64, "RGBA")

    # 步骤 1：裁掉拼图块四周透明区域，只保留有效内容。
    alpha_channel: Image.Image = piece.getchannel("A")
    bbox: tuple[int, int, int, int] | None = alpha_channel.getbbox()
    if bbox is None:
        raise ValueError("验证码拼图块为空")
    patch: Image.Image = piece.crop(bbox)
    patch_width, patch_height = patch.size
    if patch_width <= 0 or patch_height <= 0:
        raise ValueError("验证码拼图块尺寸异常")

    # 步骤 2：构造二值掩码并统计有效像素数量。
    patch_alpha: Image.Image = patch.getchannel("A")
    mask: Image.Image = patch_alpha.point(
        lambda value: 255 if value > _ALPHA_THRESHOLD else 0
    )
    valid_pixels: int = sum(mask.histogram()[1:])
    if valid_pixels == 0:
        raise ValueError("验证码拼图块无有效像素")

    background_width, background_height = original.size
    patch_rgb: Image.Image = patch.convert("RGB")

    # 步骤 3：确定纵向搜索范围。
    # 若拼图块图片与背景等高，说明拼图块已处于正确纵向位置，只需横向搜索。
    if piece.size[1] == background_height:
        y_positions: range | list[int] = [bbox[1]]
    else:
        y_positions = range(0, background_height - patch_height + 1)

    best_score: float = float("inf")
    best_x: int = 0
    best_y: int = bbox[1] if piece.size[1] == background_height else 0

    # 步骤 4：逐位置计算带掩码的平均像素绝对差，取最小值。
    for y_position in y_positions:
        for x_position in range(0, background_width - patch_width + 1):
            region: Image.Image = original.crop(
                (x_position, y_position, x_position + patch_width, y_position + patch_height)
            )
            difference: Image.Image = ImageChops.difference(region, patch_rgb)
            statistics: ImageStat.Stat = ImageStat.Stat(difference, mask)
            # sum 为 RGB 三通道差值之和；除以有效像素数得到平均差分。
            score: float = sum(statistics.sum) / valid_pixels
            if score < best_score:
                best_score = score
                best_x = x_position
                best_y = y_position

    return CaptchaOffset(x=best_x, y=best_y, score=best_score)
