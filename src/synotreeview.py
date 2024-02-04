#!python
"""
SynoTreeView

    to use with SynoModel

"""
import logging

from PyQt6.QtWidgets import QTreeView
from PyQt6.QtCore import QModelIndex


log = logging.getLogger(__name__)


class SynoTreeView(QTreeView):
    """Synology Photos TreeView"""

    def __init__(self):
        """Init Custom model"""
        QTreeView.__init__(self)

    def mousePressEvent(self, event) -> None:
        """click on tree : update node count if needed"""
        view_pos = self.viewport().mapFromGlobal(event.globalPosition())
        index = self.indexAt(view_pos.toPoint())
        if index.isValid():
            node = index.internalPointer()
            if node.isUnknownRowCount():
                index.model().updateRowCount(index)
        return super().mousePressEvent(event)

    def expandAbsolutePath(self, path: str) -> QModelIndex:
        """expand absolute path"""
        indexes = self.model().pathIndexes(path)
        index = None
        for index in indexes:
            index.model().updateRowCount(index)
            self.expand(index)
        return index
