import logging

from PyQt6.QtCore import Qt, QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QWidget, QGridLayout, QHBoxLayout

# from pyqt_slideshow.widgets.aniButton import AniRadioButton
from pyqt_slideshow.widgets.graphicsView import SingleImageGraphicsView
from pyqt_slideshow.widgets.svgButton import SvgButton


log = logging.getLogger(__name__)
log.setLevel(logging.INFO)


class SlideShow(QWidget):
    """
    Widget slideshow
        - passive component :
            send signal on click next/previous, timer
    """

    class __Sygnal(QObject):
        previous = pyqtSignal()
        next = pyqtSignal(bool)

    signal = __Sygnal()

    def __init__(self, parent=None, flags=Qt.WindowType.Window | Qt.WindowType.WindowCloseButtonHint):
        """init forcing Window Type (seems mandatory for set full screen mode)"""
        super().__init__(parent, flags)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        self.setStyleSheet("QWidget {background: transparent; border: 0px; }")
        self.__interval = 6000
        self.__initUi()

    def __initUi(self):
        self.__view = SingleImageGraphicsView()
        self.__view.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        # self.__view.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatioByExpanding)
        self.__view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.__view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.__view.setStyleSheet("QGraphicsView { background: black; border: 0px; }")
        self.__view.installEventFilter(self)

        self.__btnWidget = QWidget()

        self.__prevBtn = SvgButton(self)
        self.__prevBtn.setIcon("ico/left.svg")
        self.__prevBtn.setFixedSize(30, 50)
        self.__prevBtn.clicked.connect(self.__prev)
        self.__prevBtn.setEnabled(True)

        self.__nextBtn = SvgButton(self)
        self.__nextBtn.setIcon("ico/right.svg")
        self.__nextBtn.setFixedSize(30, 50)
        self.__nextBtn.clicked.connect(self.__nextClicked)
        self.__nextBtn.setEnabled(True)

        lay = QHBoxLayout()
        lay.addWidget(self.__prevBtn, alignment=Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(self.__nextBtn, alignment=Qt.AlignmentFlag.AlignRight)

        self.__navWidget = QWidget()
        self.__navWidget.setLayout(lay)

        lay = QGridLayout()
        lay.addWidget(self.__view, 0, 0, 3, 1)
        lay.addWidget(self.__navWidget, 0, 0, 3, 1)
        lay.addWidget(self.__btnWidget, 2, 0, 1, 1, Qt.AlignmentFlag.AlignCenter)
        self.setLayout(lay)

        self.__timer = QTimer(self)
        self.__timer.setInterval(self.__interval)
        self.__timer.timeout.connect(self.__nextByTimer)
        self.__timer.stop()

    def toggleFullScreen(self):
        """
        Toogle full screen

        (Seems impossible without error when widget in QSplitter)
        """
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def __prev(self):
        """click button previous"""
        self.signal.previous.emit()

    def __nextByTimer(self):
        """next by timer"""
        log.info(f"Timer signal")
        self.signal.next.emit(False)

    def __nextClicked(self):
        """click button next"""
        self.signal.next.emit(True)

    def setInterval(self, milliseconds: int):
        """change timer value"""
        self.__interval = milliseconds
        self.__timer.setInterval(milliseconds)

    def setPhoto(self, photo):
        """set photo

        photo is SynoNode or QPixmap
        """
        self.__view.setImage(photo)

    def setNavigationButtonVisible(self, f: bool):
        self.__navWidget.setVisible(f)

    def setBottomButtonVisible(self, f: bool):
        self.__btnWidget.setVisible(f)

    def setTimerEnabled(self, f: bool):
        """start/stop timer"""
        if f:
            self.__timer.start()
        else:
            self.__timer.stop()

    def isTimerActive(self):
        """return True if Slideshow running"""
        return self.__timer.isActive()

    def setGradientEnabled(self, f: bool):
        self.__view.setGradientEnabled(f)

    # get the btn widget
    # to set the spacing (currently)
    # here's how to do it:
    # self.__btnWidget.layout().setSpacing(5)
    def getBtnWidget(self):
        return self.__btnWidget

    # get the prev button
    # to set the prev nav button's size by user
    def getPrevBtn(self):
        return self.__prevBtn

    # get the next button
    # to set the next nav button's size by user
    def getNextBtn(self):
        return self.__nextBtn
