"""
Tab Widget for Synology Explore

"""
import logging

from PyQt6.QtWidgets import (
    QTabWidget,
    QWidget,
    QVBoxLayout,
)
from internalconfig import TAB_MAIN_EXPLORER

log = logging.getLogger(__name__)


class SynoTabWidget(QWidget):
    """Manage Tab"""

    def __init__(self, parent=None):
        super(SynoTabWidget, self).__init__(parent=parent)
        self.layout = QVBoxLayout(self)

        # Initialize tab screen
        self.tabs = QTabWidget()

        # Add tabs to widget
        self.layout.addWidget(self.tabs)
        self.setLayout(self.layout)

        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.onCloseTab)

    def addTab(self, widget: QWidget, title: str) -> None:
        """add new Tab and activate it"""
        self.tabs.addTab(widget, title)
        self.tabs.setCurrentWidget(widget)

    def isTabExists(self, title: str) -> bool:
        """return True if a tab title exists"""
        index = self.tabIndex(title)
        return index is not None

    def tabIndex(self, title: str) -> int | None:
        """return index of tab with title"""
        for itab in range(0, self.tabs.count()):
            if self.tabs.tabText(itab) == title:
                return itab
        return None

    def setCurrentTab(self, title: str) -> int | None:
        """activate tab by title"""
        iTab = self.tabIndex(title)
        if iTab is None:
            return None
        self.tabs.setCurrentIndex(iTab)
        return iTab

    def onCloseTab(self, index: int) -> None:
        """close tab (except Main Explorer)"""
        if self.tabs.tabText(index) == TAB_MAIN_EXPLORER:
            log.warning("Close of Main Explorer refused")
            return
        widget = self.tabs.widget(index)
        widget.deleteLater()
        self.tabs.removeTab(index)
