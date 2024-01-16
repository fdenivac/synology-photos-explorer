"""
    ImageWidget resizable to parent size
"""
from PyQt6.QtWidgets import QLabel
from PyQt6.QtGui import QPixmap, QResizeEvent
from PyQt6.QtCore import Qt


class ImageWidget(QLabel):
    def __init__(self, parent, img: QPixmap = None):
        super().__init__(parent)
        if img is None:
            img = QPixmap()
        self.img = img
        self.setImage(img)
        self.setStyleSheet("background-color: black;")
        self.setMinimumSize(50, 50)

    def setImage(self, img):
        self.img = QPixmap(img)
        if self.img.isNull():
            self.setPixmap(self.img)
            return
        dim = min(self.parent().width(), self.parent().height())
        self.setPixmap(self.img.scaled(dim, dim, Qt.AspectRatioMode.KeepAspectRatio))

    def resizeEvent(self, event: QResizeEvent):
        if self.img.isNull():
            return
        dim = min(self.parent().width(), self.parent().height())
        self.setPixmap(self.img.scaled(dim, dim, Qt.AspectRatioMode.KeepAspectRatio))
