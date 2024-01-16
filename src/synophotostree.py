"""
TreeView for Synology Photos

Code based on :
    https://gist.github.com/nbassler/342fc56c42df27239fa5276b79fca8e6
    based on :
        http://trevorius.com/scrapbook/uncategorized/pyqt-custom-abstractitemmodel/


"""

from __future__ import annotations
from typing import Any
import sys
from enum import Enum
import logging
from PyQt6 import QtCore, QtWidgets, QtGui
from PyQt6.QtWidgets import (
    QTreeView,
)

from synophotosmodel import SynoModel


# set logger in stdout
log = logging.getLogger(__name__)
log.setLevel(logging.WARNING)
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter("%(message)s")
handler.setFormatter(formatter)
log.addHandler(handler)


class SynoTreeView(QTreeView):
    def __init__(self):
        """Init Custom model"""
        QTreeView.__init__(self)
        self.setModel(SynoModel(dirs_only=False))
        # TODO if setHeaderHidden is False, so mousePressEvent position is wrong
        self.setHeaderHidden(False)
        self.hideColumn(3)
        self.hideColumn(2)
        self.hideColumn(1)

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


class SynoTree:
    """ """

    def __init__(self):
        self.tw = SynoTreeView()
        self.tw.setWindowTitle("Synology Photos Tree")
        self.tw.setGeometry(0, 0, 500, 600)


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    mytree = SynoTree()
    mytree.tw.show()
    sys.exit(app.exec())
