"""
TreeView demo application for Synology Photos (DSM 7)
"""

from __future__ import annotations
import os
import sys
import logging

from PyQt6.QtWidgets import QApplication, QTreeView, QMessageBox

from dotenv import load_dotenv

from cache import control_thread_pool

from synophotosmodel import SynoModel
from photos_api import synofoto


# take environment variables (addr, port ,user, password, ...) from .env file
load_dotenv()


# set logger in stdout
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter("%(message)s")
handler.setFormatter(formatter)
log.addHandler(handler)


class SynoTreeView(QTreeView):
    def __init__(self):
        """Init Custom model"""
        QTreeView.__init__(self)
        self.setWindowTitle("Synology Photos Tree")
        self.setGeometry(0, 0, 500, 600)
        self.setModel(SynoModel(dirs_only=False))
        self.setHeaderHidden(True)
        self.hideColumn(2)
        self.hideColumn(1)
        self.show()

    def mousePressEvent(self, event) -> None:
        """click on tree : update node count if needed"""
        view_pos = self.viewport().mapFromGlobal(event.globalPosition())
        index = self.indexAt(view_pos.toPoint())
        if index.isValid():
            node = index.internalPointer()
            if node.isUnknownRowCount():
                index.model().updateRowCount(index)
                log.info(f"update rows count before collapse/expand({node.childCount()}) for {node._data[0]}")
        return super().mousePressEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)

    address = os.environ.get("SYNO_ADDR")
    port = os.environ.get("SYNO_PORT")
    username = os.environ.get("SYNO_USER")
    password = os.environ.get("SYNO_PASSWORD")
    secure = os.environ.get("SYNO_SECURE")
    certverif = os.environ.get("SYNO_CERTVERIF")
    otpcode = os.environ.get("SYNO_OPTCODE")

    synofoto.login(address, port, username, password, secure, certverif, 7, False, otpcode)

    status = "Connected" if synofoto.is_connected() else "Failed to connect"
    log.info(f"{status} to Synology Photos ({os.environ.get('SYNO_ADDR')})")

    open_app = True
    if not synofoto.is_connected():
        ret = QMessageBox.critical(
            None,
            "Synology Photos Error",
            f"{status} to Synology Photos ({os.environ.get('SYNO_ADDR')})\n\n" "A fake empty model will be used.",
            QMessageBox.StandardButton.Abort | QMessageBox.StandardButton.Ok,
        )
        if ret == QMessageBox.StandardButton.Abort:
            open_app = False

    if open_app:
        # launch application
        mytree = SynoTreeView()
        app.exec()

    # exit from download thread (created on init, not used here)
    control_thread_pool.exit_loop()
