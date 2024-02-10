"""
    Dialogs based on UI files
"""

import os
from PyQt6.QtWidgets import (
    QDialog,
)
from PyQt6.QtGui import QTextDocument
from PyQt6.uic import loadUi
from internalconfig import APP_NAME, VERSION


class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        loadUi(
            os.path.join(os.path.realpath(os.path.dirname(__file__)), "ui/login.ui"),
            self,
        )


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        def replace(placeholder, newString):
            cursor = doc.find(placeholder, 0, QTextDocument.FindFlag.FindWholeWords)
            if not cursor.isNull():
                cursor.insertText(newString)

        super().__init__(parent)
        loadUi(
            os.path.join(os.path.realpath(os.path.dirname(__file__)), "ui/about.ui"),
            self,
        )
        doc = self.textEdit.document()
        replace("<APPNAME>", APP_NAME)
        replace("<VERSION>", VERSION)


class FailedConnectDialog(QDialog):
    def __init__(self, details, parent=None):
        super().__init__(parent)
        loadUi(
            os.path.join(os.path.realpath(os.path.dirname(__file__)), "ui/connectfailed.ui"),
            self,
        )
        self.errorDetails.setText(details)
