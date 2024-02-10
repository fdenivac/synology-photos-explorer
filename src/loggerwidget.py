"""
Logging widget

    Usage 
        ...
        self.logTextBox = LoggerWidget(self)
        logging.getLogger().addHandler(self.logTextBox)
        logging.getLogger().setLevel(logging.DEBUG)
        ...
"""

import logging
from PyQt6.QtCore import (
    QObject,
    pyqtSignal,
)
from PyQt6.QtWidgets import (
    QPlainTextEdit,
)


class LoggerWidget(QPlainTextEdit, logging.Handler):
    """Logger widget

    WARNING !! : RecursionError occurs when logging from some SynoModel override functions
    """

    class Sygnal(QObject):
        appendText = pyqtSignal(str)

    signal = Sygnal()

    def __init__(self, parent):
        super(LoggerWidget, self).__init__(parent)
        self.setReadOnly(True)
        self.signal.appendText.connect(self.appendPlainText)

        self.setFormatter(
            logging.Formatter(
                "%(name)s - %(asctime)s.%(msecs)d - %(levelname)s - %(message)s",
                datefmt="%H:%M:%S",
            )
        )

    def emit(self, record):
        msg = self.format(record)
        self.signal.appendText.emit(msg)
