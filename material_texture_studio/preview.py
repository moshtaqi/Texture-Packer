from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image
from PyQt6.QtGui import QImage, QPixmap


def make_thumbnail(path: Path | str, size: int = 72) -> QPixmap | None:
    try:
        with Image.open(path) as image:
            image.thumbnail((size, size), Image.Resampling.LANCZOS)
            image = image.convert("RGBA")
            arr = np.asarray(image)
            height, width, _ = arr.shape
            q_image = QImage(
                arr.data,
                width,
                height,
                4 * width,
                QImage.Format.Format_RGBA8888,
            ).copy()
            return QPixmap.fromImage(q_image)
    except Exception:
        return None
