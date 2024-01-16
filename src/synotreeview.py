"""
SynoTreeView

    to use with SynoModel

"""
import logging

from PyQt6.QtWidgets import QTreeView

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
                node.updateRowCount()
                log.info(f"collapse/expand({node.childCount()}) for {node._data[0]}")
                if node.childCount() == 0:
                    # workaround for removing expand/collapse indicator
                    self.collapse(index.parent())
                    self.expand(index.parent())
        return super().mousePressEvent(event)

    def expandAbsolutePath(self, path):
        """expand absolute path"""
        indexes = self.model().pathIndexes(path)
        for index in indexes:
            index.internalPointer().updateRowCount()
            self.expand(index)
