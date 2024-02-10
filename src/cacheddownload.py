"""
    Thumbnails download cached function
"""

from cache import cache, THUMB_CALLABLE_NAME
from PyQt6.QtGui import (
    QImage,
    QPixmap,
    QColorSpace,
)
from PyQt6.QtCore import (
    QByteArray,
    QBuffer,
    QIODeviceBase,
)
from internalconfig import CACHE_PIXMAP


@cache.memoize(name=THUMB_CALLABLE_NAME, tag="thumb")
def download_thumbnail(inode, cache_key, shared):
    """get thumbnail using cache"""
    from photos_api import synofoto

    if CACHE_PIXMAP:
        raw_image = synofoto.api.thumbnail_download(inode, "sm", cache_key, shared)
        pixmap = QPixmap()
        image = QImage()
        image.loadFromData(raw_image)
        colorspace = image.colorSpace()
        if not colorspace.description().startswith("sRGB"):
            srgbColorSpace = QColorSpace(QColorSpace.NamedColorSpace.SRgb)
            image.convertToColorSpace(srgbColorSpace)
        pixmap.convertFromImage(image)
        # convert to bytes
        array = QByteArray()
        buffer = QBuffer(array)
        buffer.open(QIODeviceBase.OpenModeFlag.WriteOnly)
        pixmap.save(buffer, "PNG")
        return array.data()
    return synofoto.api.thumbnail_download(inode, "sm", cache_key, shared)
