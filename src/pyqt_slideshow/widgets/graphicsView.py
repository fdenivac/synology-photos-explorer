from PyQt6.QtCore import Qt, QPropertyAnimation, QObject
from PyQt6.QtGui import QPixmap, QImage, QColor, QColorSpace, QBrush, QRadialGradient, QAction
from PyQt6.QtWidgets import QGraphicsScene, QGraphicsView, QGraphicsOpacityEffect, QGraphicsProxyWidget, QFrame


from synophotosmodel import (
    # SynoModel,
    SynoNode,
    NodeType,
    SpaceType,
)

from photos_api import synofoto
from cacheddownload import download_photo


class SingleImageGraphicsView(QGraphicsView):
    def __init__(self):
        super().__init__()
        self.__aspectRatioMode = Qt.AspectRatioMode.KeepAspectRatio
        self.__gradient_enabled = False
        self.__initVal()

    def __initVal(self):
        self._scene = QGraphicsScene()
        self._p = QPixmap()
        self._item = ""

    def setImage(self, image: QPixmap | SynoNode):
        """set image pixmap"""
        if isinstance(image, SynoNode):
            node = image
            pixmap = QPixmap()
            image = QImage()
            raw_image = download_photo(node.inode, node.isShared(), node.passphrase())
            image.loadFromData(raw_image)
            colorspace = image.colorSpace()
            if not colorspace.description().startswith("sRGB"):
                srgbColorSpace = QColorSpace(QColorSpace.NamedColorSpace.SRgb)
                image.convertToColorSpace(srgbColorSpace)
            pixmap.convertFromImage(image)
            image = pixmap

        self._p = image
        self._scene = QGraphicsScene()
        self._item = self._scene.addPixmap(self._p)

        self.setScene(self._scene)
        self.fitInView(self._item, self.__aspectRatioMode)

    def setAspectRatioMode(self, mode):
        self.__aspectRatioMode = mode

    def setGradientEnabled(self, f: bool):
        self.__gradient_enabled = f

    def __setGradient(self):
        center_point = self.mapToScene(self.rect().center())
        gradient = QRadialGradient(center_point, (self.height() + self.width()) // 2)
        gradient.setColorAt(0, QColor(255, 255, 255, 0))
        gradient.setColorAt(1, QColor(0, 0, 0, 255))
        brush = QBrush(gradient)
        self.setForegroundBrush(brush)

    def resizeEvent(self, e):
        if self._item:
            self.fitInView(self.sceneRect(), self.__aspectRatioMode)
            if self.__gradient_enabled:
                self.__setGradient()
        return super().resizeEvent(e)
