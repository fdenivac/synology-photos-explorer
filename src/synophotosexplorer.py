#!python
"""
Explorer for Synology Photos

Based on https://github.com/adesfontaines/pyqtexplorer

"""
import sys
import logging
import os
import ctypes
import weakref
import winreg
from pathlib import PurePosixPath
from threading import Event

from PyQt6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QTableWidget,
    QTableWidgetItem,
    QLineEdit,
    QSplitter,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QToolButton,
    QMenu,
    QDockWidget,
    QFrame,
    QFileDialog,
    QComboBox,
)
from PyQt6.QtGui import (
    QIcon,
    QCursor,
    QAction,
    QImage,
    QPixmap,
    QColorSpace,
)
from PyQt6.QtCore import (
    Qt,
    QModelIndex,
    QItemSelectionModel,
    QItemSelection,
    QItemSelectionRange,
    QSettings,
    QTimer,
)

from diskcache.core import args_to_key as get_cache_key
from cache import thumbcache, download_thread_pool, THUMB_CALLABLE_NAME, control_thread_pool

from qt_json_view.model import JsonModel
from qt_json_view.view import JsonView

from synophotosmodel import (
    SynoModel,
    SynoNode,
    NodeType,
    SpaceType,
)

from synology_photos_api.photos import DatePhoto
from photos_api import synofoto

from internalconfig import (
    USE_LOG_WIDGET,
    USE_THREAD_CHILDS,
    USE_COMBO_VIEW,
    INITIAL_PATH,
    APP_NAME,
    CACHE_PIXMAP,
    VERSION,
    TAB_MAIN_EXPLORER,
    TAB_PERSONAL_TAGS,
    TAB_SHARED_TAGS,
)
from pyqt_slideshow.slideshow import SlideShow
from cacheddownload import download_thumbnail
from loggerwidget import LoggerWidget
from synotabwidget import SynoTabWidget
from photosview import PhotosIconView, PhotosDetailsView
from synotreeview import SynoTreeView
from imagewidget import ImageWidget
from uidialogs import LoginDialog, AboutDialog, FailedConnectDialog


# search combo value
WHERE_TAG_PERSONAL = "Tag Personal"
WHERE_TAG_SHARED = "Tag Shared"
WHERE_KEYWORD_PERSONAL = "Keyword Personal"
WHERE_KEYWORD_SHARED = "Keyword Shared"

# widget order in main splitter
WIDGET_TREE_EXPLORER = 0
WIDGET_LIST_EXPLORER = 1
WIDGET_SLIDESHOW = 2


# set logger in stdout
log = logging.getLogger("main")
log.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.INFO)
handler.setFormatter(
    logging.Formatter(
        "%(name)s - %(asctime)s.%(msecs)d - %(levelname)s - %(message)s",
        datefmt="%H:%M:%S",
    )
)
log.addHandler(handler)
log.info("Logger in place")


class History:
    """
    manage history navigation
    """

    def __init__(self, maxhist):
        self.max = maxhist
        self.histback = []
        self.histforward = []

    def append(self, value):
        """new entry"""
        if self.histback and value == self.histback[-1]:
            return
        self.histback.append(value)
        if len(self.histback) > self.max:
            self.histback.pop(0)

    def back(self):
        """previous url"""
        if not self.histback or len(self.histback) == 1:
            return None
        value = self.histback.pop(-1)
        self.histforward.append(value)
        return self.histback[-1]

    def forward(self):
        """next url"""
        if not self.histforward:
            return None
        value = self.histforward.pop(-1)
        self.histback.append(value)
        return value


def fatalConnect():
    """call by timer on init when connect to synology fails"""

    def getMainWindow():
        for widget in QApplication.instance().topLevelWidgets():
            if isinstance(widget, QMainWindow):
                return widget
        return None

    parent = getMainWindow()
    ret = FailedConnectDialog(synofoto.exception, parent).exec()
    if not ret:
        QApplication.quit()


class App(QMainWindow):
    """main application"""

    def __init__(self, parent=None):
        super(App, self).__init__(parent=parent)

        # Navigation history
        self.history = History(100)

        # thumbnails management
        self.eventCancelThumb = Event()
        self.futureDownloadChilds = None

        # mainExplorer creation deferred in ChangeView
        self.mainExplorer = None

        # settings access
        self.settings = QSettings("fdenivac", "SynoPhotosExplorer")

        # Synology Photos login (status check after init UI ...)
        self.synoPhotosLogin()

        # App init
        self.initUI()

        # restore window position
        self.restoreGeometry(self.settings.value("mainwinpos", bytes("", "utf-8")))
        self.restoreGeometry(self.settings.value("mainwinpos", bytes("", "utf-8")))
        self.restoreState(self.settings.value("mainwinstate", bytes("", "utf-8")))
        self.explorerSplitter.restoreState(self.settings.value("explorersplittersizes", bytes("", "utf-8")))
        if self.settings.value("slideshowfloating") == "true":
            self.onDetachSlideshow()
            self.slideshow.restoreGeometry(self.settings.value("slideshowpos", bytes("", "utf-8")))
            if self.slideshow.isFullScreen():
                self.toggleSlideshowFullScreen()
        hidden = self.settings.value("explorersplitterhide", ["true", "true", "true"])
        self.sideExplorer.setHidden(hidden[0] == "true")
        self.mainExplorer.setHidden(hidden[1] == "true")
        self.slideshow.setHidden(hidden[2] == "true")
        self.restoreDockWidget(self.json_dock)
        self.actionJsonView.setChecked(not self.json_dock.isHidden())
        self.restoreDockWidget(self.thumbnail_dock)
        self.actionThumbView.setChecked(not self.thumbnail_dock.isHidden())
        self.actionShowTreeExpl.setChecked(not self.explorerSplitter.widget(WIDGET_TREE_EXPLORER).isHidden())
        self.actionShowListExpl.setChecked(not self.explorerSplitter.widget(WIDGET_LIST_EXPLORER).isHidden())
        self.actionShowSlideshow.setChecked(self.slideshow.isHidden())
        if USE_LOG_WIDGET:
            self.restoreDockWidget(self.log_dock)
            self.actionLogView.setChecked(not self.log_dock.isHidden())

        self.statusBar().showMessage(f"Welcome to {APP_NAME} version {VERSION}")
        self.updateToolbar()
        self.show()

        # display fatal error if Synology API failed to connect
        if not synofoto.is_connected():
            QTimer.singleShot(1, fatalConnect)

    def synoPhotosLogin(
        self,
        address=None,
        port=None,
        username=None,
        password=None,
        secure=None,
        certverif=None,
        debug=None,
        otpcode=None,
    ):
        """
        Synology Photos Login
        """
        address = os.environ.get("SYNO_ADDR") if address is None else address
        port = os.environ.get("SYNO_PORT") if port is None else port
        username = os.environ.get("SYNO_USER") if username is None else username
        password = os.environ.get("SYNO_PASSWORD") if password is None else password
        secure = os.environ.get("SYNO_SECURE") if secure is None else secure
        certverif = os.environ.get("SYNO_CERTVERIF") if certverif is None else certverif
        otpcode = os.environ.get("SYNO_OPTCODE") if otpcode is None else otpcode
        synofoto.login(address, port, username, password, secure, certverif, 7, debug, otpcode)
        log.info(f"connected = {synofoto.is_connected()} to Synology Photos ({os.environ.get('SYNO_ADDR')})")
        return synofoto.is_connected()

    def initUI(self):
        """init User Interface"""
        # Side explorer with dirs only
        self.sideExplorer = SynoTreeView()
        self.sideExplorer.setModel(SynoModel(dirs_only=True, search=True))
        self.sideExplorer.hideColumn(3)
        self.sideExplorer.hideColumn(2)
        self.sideExplorer.hideColumn(1)
        self.sideExplorer.header().hide()
        self.sideExplorer.selectionModel().currentRowChanged.connect(self.onCurrentRowChangedInSideExpl)

        self.sideExplorer.setFrameStyle(QFrame.Shape.NoFrame)
        self.sideExplorer.uniformRowHeights = True
        # set context menu for side explorer
        self.sideDownloadToAction = QAction("Download folder To ...", self)
        self.sideDownloadToAction.setStatusTip("Download folder to destination")
        self.sideDownloadToAction.triggered.connect(self.onSideDownloadTo)
        self.sideDownloadAction = QAction("Download folder", self)
        self.sideDownloadAction.setStatusTip("Download folder to 'Download' folder")
        self.sideDownloadAction.triggered.connect(self.onSideDownload)
        self.sideExplorer.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.sideExplorer.customContextMenuRequested.connect(self.sideContextItemMenu)

        self.mainModel = SynoModel(
            dirs_only=False,
            additional=["thumbnail", "exif", "resolution"],
            search=True,
        )

        self.currentExplorerView = self.settings.value("viewtype", "Details")

        # Top menus
        self.createTopMenu()
        self.createActionBar()

        # photos view/slideshow
        self.slideshow = None
        self.createSlideshowWidget(False)
        self.parentSlideshow = None
        self.modeFullscreen = False

        # Main explorer
        self.changeView(self.currentExplorerView)

        # Set layout and views
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        explorerLayout = QHBoxLayout()
        explorerLayout.setContentsMargins(0, 0, 0, 0)

        # create splitter for tree explorer + list explorer + slideshow
        self.explorerSplitter = QSplitter(Qt.Orientation.Horizontal)
        # WARNING: do not change order unless change WIDGET_TREE_EXPLORER; WIDGET_LIST_EXPLORER, WIDGET_SLIDESHOW
        self.explorerSplitter.addWidget(self.sideExplorer)
        self.explorerSplitter.addWidget(self.mainExplorer)
        self.explorerSplitter.addWidget(self.slideshow)
        self.explorerSplitter.setStretchFactor(1, 2)
        self.explorerSplitter.setSizes([400, 800, 200])
        explorerLayout.addWidget(self.explorerSplitter)

        # create tab, add main explorer
        self.tab_widget = SynoTabWidget()
        self.tab_widget.addTab(self.explorerSplitter, TAB_MAIN_EXPLORER)
        layout.addWidget(self.tab_widget)

        # Main widget
        widget = QWidget()
        widget.setLayout(layout)
        self.setCentralWidget(widget)
        self.setGeometry(200, 200, 1200, 800)

        # Application icon
        self.setWindowIcon(QIcon("./src/ico/icon_photos.png"))
        if sys.platform == "win32":
            # show correct icon in taskbar
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("fdenivac")

        # Dock json widget
        self.json_dock = QDockWidget("JSON Details")
        self.json_dock.setObjectName("json_dock")
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.json_dock)
        self.json_view = JsonView()
        self.json_dock.setWidget(self.json_view)

        # Dock image widget
        self.thumbnail_dock = QDockWidget("Photo Thumbnail")
        self.thumbnail_dock.setObjectName("thumbnail_dock")
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.thumbnail_dock)
        self.thumbnailWidget = ImageWidget(self)
        self.thumbnail_dock.setWidget(self.thumbnailWidget)
        self.thumbnailWidget.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # logging windows
        if USE_LOG_WIDGET:
            self.log_dock = QDockWidget("Log window")
            self.log_dock.setObjectName("logs_dock")
            self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.log_dock)
            self.logTextBox = LoggerWidget(self)
            logging.getLogger().addHandler(self.logTextBox)
            logging.getLogger().setLevel(logging.INFO)
            self.log_view = self.logTextBox
            self.log_dock.setWidget(self.logTextBox)

        # restore pinned search
        self.settings.beginGroup("pinnedSearch")
        keys = self.settings.childKeys()
        for key in keys:
            parts = self.settings.value(key).split("/")
            section, shared, searchText = parts[2:]
            shared = shared.lower() == "shared"
            self.mainExplorer.model().createSearch(section, searchText, shared)
            self.sideExplorer.model().createSearch(section, searchText, shared)
        self.settings.endGroup()

        # set initial path
        self.currentDir = ""
        currentDir = self.settings.value("initialpath", INITIAL_PATH)
        self.sideExplorer.model().setRootPath(currentDir)
        self.sideExplorer.expandAbsolutePath(currentDir)
        self.navigate(self.mainExplorer.model().setRootPath(currentDir))
        # self.setMainExplorerIndex("first")

        log.info("END InitUI")

    def createTopMenu(self):
        """create initial menus"""
        # Add menus
        menuBar = self.menuBar()

        fileMenu = menuBar.addMenu("&File")
        editMenu = menuBar.addMenu("&Edit")
        # aboutToShow signal used for update menu
        editMenu.aboutToShow.connect(self.updateEditMenu)
        viewMenu = menuBar.addMenu("&View")
        viewMenu.aboutToShow.connect(self.updateEditMenu)
        slideshowMenu = menuBar.addMenu("&Slideshow")
        slideshowMenu.aboutToShow.connect(self.updateSlideshowMenu)
        helpMenu = menuBar.addMenu("&Help")

        # File
        action = QAction("&Synology login ...", self)
        action.triggered.connect(self.loginDialog)
        fileMenu.addAction(action)

        fileMenu.addSeparator()

        action = QAction("&Quit", self)
        action.triggered.connect(self.quitApp)
        action.setShortcut("Ctrl+Q")
        fileMenu.addAction(action)

        # Edit
        action = QAction("&Select All", self)
        action.setStatusTip("Select All")
        action.setShortcut("Ctrl+A")
        action.triggered.connect(self.selectAll)
        editMenu.addAction(action)

        action = QAction("&Unselect All", self)
        action.setStatusTip("Unselect All")
        action.setShortcut("Ctrl+D")
        action.triggered.connect(self.unselectAll)
        editMenu.addAction(action)

        editMenu.addSeparator()

        self.actionDownloadTo = QAction("Download To ...", self)
        self.actionDownloadTo.setStatusTip("Download selected elements to folder")
        self.actionDownloadTo.triggered.connect(self.onDownloadTo)
        editMenu.addAction(self.actionDownloadTo)

        self.actionDownload = QAction("Download", self)
        self.actionDownload.setStatusTip("Download selected elements to 'Download' folder")
        self.actionDownload.triggered.connect(self.onDownload)
        editMenu.addAction(self.actionDownload)

        # View
        self.actionIconsView = QAction("&Thumbnails", self)
        self.actionIconsView.setStatusTip("Thumbnail list view")
        self.actionIconsView.setCheckable(True)
        self.actionIconsView.triggered.connect(lambda setview, view="Icons": self.changeView(view))
        viewMenu.addAction(self.actionIconsView)

        self.actionDetailsView = QAction("&Details", self)
        self.actionDetailsView.setStatusTip("Details view")
        self.actionDetailsView.setCheckable(True)
        self.actionDetailsView.triggered.connect(lambda setview, view="Details": self.changeView(view))
        viewMenu.addAction(self.actionDetailsView)

        viewMenu.addSeparator()

        self.actionTagsPersonal = QAction(TAB_PERSONAL_TAGS, self)
        self.actionTagsPersonal.setStatusTip("Open tab for Personal Tags")
        self.actionTagsPersonal.setCheckable(True)
        self.actionTagsPersonal.triggered.connect(lambda setview, tab=TAB_PERSONAL_TAGS,: self.onShowTagsList(tab))
        viewMenu.addAction(self.actionTagsPersonal)

        self.actionTagsShared = QAction(TAB_SHARED_TAGS, self)
        self.actionTagsShared.setStatusTip("Open tab for Shared Tags")
        self.actionTagsShared.setCheckable(True)
        self.actionTagsShared.triggered.connect(lambda setview, tab=TAB_SHARED_TAGS: self.onShowTagsList(tab))
        viewMenu.addAction(self.actionTagsShared)

        viewMenu.addSeparator().setText("Dock Views")

        self.actionJsonView = QAction("&JSON view", self)
        self.actionJsonView.setStatusTip("Show JSON view")
        self.actionJsonView.setShortcut("Ctrl+J")
        self.actionJsonView.setCheckable(True)
        self.actionJsonView.triggered.connect(self.showJsonView)
        viewMenu.addAction(self.actionJsonView)

        self.actionThumbView = QAction("&Thumbnail view", self)
        self.actionThumbView.setStatusTip("Show Thumbnail view")
        self.actionThumbView.setShortcut("Ctrl+T")
        self.actionThumbView.setCheckable(True)
        self.actionThumbView.triggered.connect(self.showThumbView)
        viewMenu.addAction(self.actionThumbView)

        if USE_LOG_WIDGET:
            self.actionLogView = QAction("&Log view", self)
            self.actionLogView.setStatusTip("Show Log view")
            self.actionLogView.setCheckable(True)
            self.actionLogView.triggered.connect(self.showLogView)
            viewMenu.addAction(self.actionLogView)

        viewMenu.addSeparator()

        # hide/display component in explorer splitter

        # tree explorer
        self.actionShowTreeExpl = QAction("Show/hide Tree Explorer", self)
        self.actionShowTreeExpl.setStatusTip("Show/hide Tree Explorer")
        self.actionShowTreeExpl.setCheckable(True)
        self.actionShowTreeExpl.triggered.connect(self.showHideTree)
        viewMenu.addAction(self.actionShowTreeExpl)
        # list/table explorer
        self.actionShowListExpl = QAction("Show/hide List Explorer", self)
        self.actionShowListExpl.setStatusTip("Show/hide List Explorer")
        self.actionShowListExpl.setCheckable(True)
        self.actionShowListExpl.triggered.connect(self.showHideList)
        viewMenu.addAction(self.actionShowListExpl)
        # slideshow
        self.actionShowSlideshow = QAction("Show/hide slideshow window", self)
        self.actionShowSlideshow.setStatusTip("Show/hide slideshow window")
        self.actionShowSlideshow.setCheckable(True)
        self.actionShowSlideshow.triggered.connect(self.showHideSlide)
        viewMenu.addAction(self.actionShowSlideshow)

        # Slideshow Menu

        # start slide show from first photo
        self.actionStartSlideshow = QAction("Start slideshow (from first photo)", self)
        self.actionStartSlideshow.setStatusTip("Start slideshow of current folder")
        self.actionStartSlideshow.triggered.connect(self.onStartSlideshow)
        slideshowMenu.addAction(self.actionStartSlideshow)

        # continue slide show
        self.actionContinueSlideShow = QAction("Start slideshow from current photo", self)
        self.actionContinueSlideShow.setStatusTip("Continue slideshow of current folder")
        self.actionContinueSlideShow.triggered.connect(self.onContinueSlideshow)
        slideshowMenu.addAction(self.actionContinueSlideShow)

        # pause slide show
        self.actionPauseSlideshow = QAction("Pause slideshow", self)
        self.actionPauseSlideshow.setStatusTip("Pause slideshow of current folder")
        self.actionPauseSlideshow.triggered.connect(self.onPauseSlideshow)
        slideshowMenu.addAction(self.actionPauseSlideshow)

        slideshowMenu.addSeparator()

        # fullscreen toggle
        self.actionSlideshowFullscreen = QAction("Fullscreen", self)
        self.actionSlideshowFullscreen.setStatusTip("Full Screen Toggle")
        self.actionSlideshowFullscreen.setShortcut("Ctrl+F")
        self.actionSlideshowFullscreen.triggered.connect(self.toggleSlideshowFullScreen)
        slideshowMenu.addAction(self.actionSlideshowFullscreen)

        slideshowMenu.addSeparator()

        # detach slideshow window from splitter
        self.actionFloatSlideshow = QAction("Slideshow as float window", self)
        self.actionFloatSlideshow.setStatusTip("Detach slideshow window from explorer splitter")
        self.actionFloatSlideshow.triggered.connect(self.onDetachSlideshow)
        slideshowMenu.addAction(self.actionFloatSlideshow)

        # attach slideshow window in splitter
        self.actionSlideshowSplitter = QAction("Slideshow in explorer", self)
        self.actionSlideshowSplitter.setStatusTip("Attach slideshow window in explorer splitter")
        self.actionSlideshowSplitter.triggered.connect(self.onAttachSlideshow)
        slideshowMenu.addAction(self.actionSlideshowSplitter)

        # About
        action = QAction("&About", self)
        action.setStatusTip("About")
        action.triggered.connect(self.about)
        helpMenu.addAction(action)

    def createActionBar(self):
        """initial action bar"""
        self.toolbar = self.addToolBar("actionToolBar")
        self.toolbar.setObjectName("action_toolbar")
        self.toolbar.setMovable(False)
        self.toolbar.setFloatable(False)

        # navigation icons
        button = QToolButton()
        button.setIcon(QIcon("./src/ico/arrow-180.png"))
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setStatusTip("Navigate Previous address")
        button.clicked.connect(self.navigateBack)
        self.toolbar.addWidget(button)

        button = QToolButton()
        button.setIcon(QIcon("./src/ico/arrow.png"))
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setStatusTip("Navigate Next address")
        button.clicked.connect(self.navigateForward)
        self.toolbar.addWidget(button)

        button = QToolButton()
        button.setIcon(QIcon("./src/ico/arrow-090.png"))
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setStatusTip("Navigate Up address")
        button.clicked.connect(self.navigateUp)
        self.toolbar.addWidget(button)

        # splitter for address bar, search, combo search space
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.addressBar = QLineEdit()
        self.addressBar.setMaxLength(255)
        self.addressBar.returnPressed.connect(self.navigateAddress)
        splitter.addWidget(self.addressBar)

        # search section
        self.searchField = QLineEdit()
        self.searchField.setPlaceholderText("Search")
        self.searchField.returnPressed.connect(self.onSearch)
        splitter.addWidget(self.searchField)

        self.searchWhere = QComboBox()
        self.searchWhere.addItem(WHERE_TAG_PERSONAL)
        self.searchWhere.addItem(WHERE_TAG_SHARED)
        self.searchWhere.addItem(WHERE_KEYWORD_PERSONAL)
        self.searchWhere.addItem(WHERE_KEYWORD_SHARED)
        self.searchWhere.setEditable(False)
        splitter.addWidget(self.searchWhere)

        splitter.setStretchFactor(10, 1)
        splitter.setSizes([500, 200, 100])

        self.toolbar.addWidget(splitter)

        # splitter icons
        self.btTreeExplorer = QToolButton()
        self.btTreeExplorer.setIcon(QIcon("./src/ico/pane1.png"))
        self.btTreeExplorer.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.btTreeExplorer.setStatusTip("Hide/Show main explorer folder Tree")
        self.btTreeExplorer.setCheckable(True)
        self.btTreeExplorer.clicked.connect(self.showHideTree)
        self.toolbar.addWidget(self.btTreeExplorer)

        self.btListExplorer = QToolButton()
        self.btListExplorer.setIcon(QIcon("./src/ico/pane2.png"))
        self.btListExplorer.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.btListExplorer.setStatusTip("Hide/Show main explorer photos List")
        self.btListExplorer.setCheckable(True)
        self.btListExplorer.clicked.connect(self.showHideList)
        self.toolbar.addWidget(self.btListExplorer)

        self.btSlideshow = QToolButton()
        self.btSlideshow.setIcon(QIcon("./src/ico/pane3.png"))
        self.btSlideshow.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.btSlideshow.setStatusTip("Hide/Show main explorer Slideshow")
        self.btSlideshow.setCheckable(True)
        self.btSlideshow.clicked.connect(self.showHideSlide)
        self.toolbar.addWidget(self.btSlideshow)

        # mainExplorer mode icons
        if USE_COMBO_VIEW:
            # mainExplorer view mode
            self.comboView = QComboBox()
            self.comboView.setEditable(False)
            self.comboView.addItem(QIcon("./src/ico/windetails.png"), "List", "Details")
            self.comboView.addItem(QIcon("./src/ico/winicons.png"), "Thumb", "Icons")
            self.comboView.setStatusTip("Change view mode for Main Explorer")
            self.setComboViewMode(self.currentExplorerView)
            self.comboView.currentIndexChanged.connect(self.onChangeView)
            self.toolbar.addWidget(self.comboView)
        else:
            self.btViewIcons = QToolButton()
            self.btViewIcons.setIcon(QIcon("./src/ico/winicons.png"))
            self.btViewIcons.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            self.btViewIcons.setCheckable(True)
            self.btViewIcons.clicked.connect(lambda setview, view="Icons": self.changeView(view))
            self.btViewIcons.setStatusTip("Main Explorer Thumbnails mode")
            self.toolbar.addWidget(self.btViewIcons)

            self.btViewDetails = QToolButton()
            self.btViewDetails.setIcon(QIcon("./src/ico/windetails.png"))
            self.btViewDetails.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            self.btViewDetails.setCheckable(True)
            self.btViewDetails.clicked.connect(lambda setview, view="Details": self.changeView(view))
            self.btViewDetails.setStatusTip("Main explorer Details mode")
            self.toolbar.addWidget(self.btViewDetails)

        self.toolbar.setStyleSheet("QToolBar { border: 0px }")

    def createSlideshowWidget(self, startTimer: bool):
        """create slideshow window"""
        if self.slideshow is not None:
            self.slideshow.signal.previous.disconnect()
            self.slideshow.signal.next.disconnect()
        self.slideshow = SlideShow()
        self.slideshow.setWindowTitle("Synology Photos Slideshow")
        self.slideshow.setWindowIcon(QIcon("./src/ico/icon_photos.png"))
        self.slideshow.setTimerEnabled(False)
        self.slideshow.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.slideshow.customContextMenuRequested.connect(self.slideshowContextItemMenu)
        self.slideshow.signal.previous.connect(self.onPrevSlide)
        self.slideshow.signal.next.connect(self.onNextSlide)
        if startTimer:
            self.slideshow.setTimerEnabled(True)
        self.slideshow.show()

    def setComboViewMode(self, mode):
        """set mode"""
        for index in range(0, self.comboView.count()):
            if self.comboView.itemData(index) == mode:
                self.comboView.setCurrentIndex(index)

    def onChangeView(self):
        """change selection in comboView"""
        view = self.comboView.currentData()
        self.changeView(view)

    def changeView(self, view):
        """change view mode in mainExplorer : new PhotosIconView or PhotosDetailsView"""
        if (
            view == "Icons"
            and isinstance(self.mainExplorer, PhotosIconView)
            or view == "Details"
            and isinstance(self.mainExplorer, PhotosDetailsView)
        ):
            self.updateToolbar()
            return

        # save current index and selection
        needResel = self.mainExplorer is not None
        if needResel:
            sortColumn = self.mainExplorer.model().sortColumn()
            sortOrder = self.mainExplorer.model().sortOrder()
            index = self.mainExplorer.selectionModel().currentIndex()
            # currentPath = ""
            if not index.isValid():
                needResel = False
            else:
                currentPath = self.mainExplorer.model().absoluteFilePath(index)
                currentSelection = []
                for index in self.mainExplorer.selectionModel().selection().indexes():
                    if index.column() != 0:
                        continue
                    currentSelection.append(self.mainExplorer.model().absoluteFilePath(index))

        self.currentExplorerView = view
        if view == "Icons":
            self.actionIconsView.setChecked(True)
            self.actionDetailsView.setChecked(False)
            self.mainExplorer = PhotosIconView(self.mainModel)

        elif view == "Details":
            self.actionDetailsView.setChecked(True)
            self.mainExplorer = PhotosDetailsView(self.mainModel)
            self.mainExplorer.horizontalHeader().sectionClicked.connect(self.onSortColumn)

        else:
            assert False

        # Common settings
        self.mainExplorer.doubleClicked.connect(self.onDoubleClick)
        self.mainExplorer.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.mainExplorer.customContextMenuRequested.connect(self.contextItemMenu)
        self.mainExplorer.selectionModel().currentRowChanged.connect(self.onCurrentRowChanged)
        self.mainExplorer.selectionModel().selectionChanged.connect(self.onSelectionChanged)
        if hasattr(self, "explorerSplitter"):
            self.explorerSplitter.replaceWidget(1, self.mainExplorer)
            self.mainExplorer.setRootIndex(self.mainExplorer.model().setRootPath(self.currentDir))

        # restore current index and selection
        if needResel:
            if sortColumn >= 0:
                self.mainExplorer.model().sort(sortColumn, sortOrder)
            index = self.mainExplorer.model().pathIndex(currentPath)
            self.mainExplorer.setCurrentIndex(index)
            self.mainExplorer.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)
            selection = QItemSelection()
            for path in currentSelection:
                index = self.mainExplorer.model().pathIndex(path)
                selection.append(QItemSelectionRange(index))
            self.mainExplorer.selectionModel().select(
                selection, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
            )

        # update toolbar
        self.updateToolbar()

    def closeEvent(self, event):
        """close app"""
        # save geometry on close
        self.settings.setValue("mainwinpos", self.saveGeometry())
        self.settings.setValue("mainwinstate", self.saveState())
        # save various parameter
        self.settings.setValue("initialpath", self.currentDir)
        self.settings.setValue("viewtype", self.currentExplorerView)
        self.settings.setValue("explorersplittersizes", self.explorerSplitter.saveState())
        self.settings.setValue(
            "explorersplitterhide",
            [self.sideExplorer.isHidden(), self.mainExplorer.isHidden(), self.slideshow.isHidden()],
        )
        self.settings.setValue("slideshowpos", self.slideshow.saveGeometry())
        self.settings.setValue("slideshowfloating", not isinstance(self.parentSlideshow, QSplitter))

        self.slideshow.close()

        # stop control thread pool
        control_thread_pool.exit_loop()

        # stop threading
        download_thread_pool.shutdown(wait=True, cancel_futures=True)

        # remove weakref of Handler logTextBox, just for avoid message as :
        #   """
        #   Exception ignored in atexit callback: <function shutdown at 0x000002186E60F740>
        #   Traceback (most recent call last):
        #       File "....\Python311\Lib\logging\__init__.py", line 2193, in shutdown
        #       h.close()
        #   RuntimeError: wrapped C/C++ object of type LoggerWidget has been deleted
        #   """"
        if USE_LOG_WIDGET:
            wr = weakref.ref(self.logTextBox)
            logging._removeHandlerRef(wr)

        super(App, self).closeEvent(event)

    def quitApp(self):
        """action quit application"""
        self.close()

    def updateEditMenu(self):
        """update edit menu"""
        hasSelection = self.mainExplorer.selectionModel().hasSelection()
        self.actionDownloadTo.setEnabled(hasSelection)
        self.actionDownload.setEnabled(hasSelection)
        self.actionTagsPersonal.setChecked(self.tab_widget.isTabExists(TAB_PERSONAL_TAGS))
        self.actionTagsShared.setChecked(self.tab_widget.isTabExists(TAB_SHARED_TAGS))

    def updateSlideshowMenu(self):
        """update slideshow menu"""
        name = "Exit Fullscreen" if self.slideshow.isFullScreen() else "Fullscreen"
        self.actionSlideshowFullscreen.setText(name)
        self.actionFloatSlideshow.setEnabled(isinstance(self.slideshow.parent(), QSplitter))
        self.actionSlideshowSplitter.setEnabled(not isinstance(self.slideshow.parent(), QSplitter))
        self.actionPauseSlideshow.setEnabled(self.slideshow.isTimerActive())
        self.actionContinueSlideShow.setEnabled(not self.slideshow.isTimerActive())

    def updateToolbar(self):
        """update icons in toobar"""
        self.btTreeExplorer.setChecked(not self.sideExplorer.isHidden())
        self.btListExplorer.setChecked(not self.mainExplorer.isHidden())
        self.btSlideshow.setChecked(self.slideshow.isVisible())
        if USE_COMBO_VIEW:
            self.setComboViewMode(self.currentExplorerView)
        else:
            self.btViewIcons.setChecked(isinstance(self.mainExplorer, PhotosIconView))
            self.btViewDetails.setChecked(isinstance(self.mainExplorer, PhotosDetailsView))

    def contextItemMenu(self, position):
        """create context menu main explorer"""
        menu = QMenu()
        self.updateEditMenu()
        menu.addAction(self.actionDownloadTo)
        menu.addAction(self.actionDownload)
        menu.exec(QCursor.pos())

    def sideContextItemMenu(self, position):
        """create context menu side explorer"""
        menu = QMenu()
        menu.addAction(self.sideDownloadToAction)
        menu.addAction(self.sideDownloadAction)
        index = self.sideExplorer.indexAt(position)
        node: SynoNode = index.internalPointer()
        if node.node_type == NodeType.SEARCH:
            menu.addSeparator()
            # remove
            action = QAction("Remove search", self)
            action.setStatusTip("Remove search(s)")
            action.triggered.connect(lambda val, node=node: self.onRemoveTag(index))
            menu.addAction(action)
            # pin
            action = QAction("Pin search", self)
            action.setStatusTip("Pin search permanently in space")
            action.triggered.connect(lambda val, node=node: self.onPinSearch(index))
            action.setEnabled(not self.isPinnedSearch(index))
            menu.addAction(action)
            # unpin
            action = QAction("Unpin search", self)
            action.setStatusTip("Remove pinned search")
            action.triggered.connect(lambda val, node=node: self.onUnpinSearch(index))
            action.setEnabled(self.isPinnedSearch(index))
            menu.addAction(action)
        menu.exec(QCursor.pos())

    def slideshowContextItemMenu(self):
        """context menu for slideshow"""
        self.updateSlideshowMenu()
        menu = QMenu()
        menu.addAction(self.actionStartSlideshow)
        menu.addAction(self.actionContinueSlideShow)
        menu.addAction(self.actionPauseSlideshow)
        menu.addSeparator()
        menu.addAction(self.actionSlideshowFullscreen)
        menu.addSeparator()
        menu.addAction(self.actionFloatSlideshow)
        menu.addAction(self.actionSlideshowSplitter)
        # show context menu
        menu.exec(QCursor.pos())

    def toggleSlideshowFullScreen(self):
        """slideshow widget in fullscreen

        Fullscreen seems impossible when slideshow is in splitter !
        Workaround : delete from splitter, recreate as floating window, and go fullscreen
                     restore position on exit fullscreen
        """
        slideshowActive = self.slideshow.isTimerActive()
        if self.slideshow.isFullScreen():
            if isinstance(self.parentSlideshow, QSplitter):
                self.slideshow.setTimerEnabled(False)
                self.slideshow.close()
                self.createSlideshowWidget(slideshowActive)
                self.explorerSplitter.addWidget(self.slideshow)
            else:
                self.slideshow.showNormal()
            self.modeFullscreen = False
        else:
            self.parentSlideshow = self.slideshow.parent()
            if isinstance(self.parentSlideshow, QSplitter):
                # remove from splitter
                self.slideshow.setTimerEnabled(False)
                widget = self.explorerSplitter.widget(WIDGET_SLIDESHOW)
                widget.deleteLater()
                # recreate, show current
                self.createSlideshowWidget(slideshowActive)
                self.setMainExplorerIndex("current")
            self.slideshow.showFullScreen()
            self.modeFullscreen = True
        self.setMainExplorerIndex("current")
        self.updateToolbar()

    def setMainExplorerIndex(self, location):
        """Set index : change

        with location in ["first", "prev", "next", "current"]
        """
        curIndex = self.mainExplorer.currentIndex()
        if isinstance(curIndex.model(), SynoModel):
            curIndex = self.mainExplorer.model().mapFromSource(curIndex)
        if not curIndex.isValid():
            assert False
        curNode = curIndex.model().nodePointer(curIndex)
        log.info(f"setMainExplorerIndex({location}) node: {curNode.dataColumn(0)}")
        if location == "first":
            index = curIndex.model().index(0, 0, curIndex.parent())
        elif location == "prev":
            index = curIndex.model().index(
                (curIndex.row() - 1) % curIndex.model().rowCount(curIndex.parent()), 0, curIndex.parent()
            )
        elif location == "next":
            index = curIndex.model().index(
                (curIndex.row() + 1) % curIndex.model().rowCount(curIndex.parent()), 0, curIndex.parent()
            )
        elif location == "current":
            # need change row for generate signal
            self.setMainExplorerIndex("first")
            index = curIndex
        else:
            assert False
        if not index.isValid():
            assert False
        curNode = index.model().nodePointer(index)
        log.info(f"setMainExplorerIndex({location}) new node: {curNode.dataColumn(0)}")
        self.mainExplorer.setCurrentIndex(index)

    def onSortColumn(self, logicalIndex: int):
        """sort column for explorer mode details"""
        selected = self.mainExplorer.selectionModel().selectedIndexes()
        if selected:
            self.mainExplorer.scrollTo(selected[0], QAbstractItemView.ScrollHint.EnsureVisible)

    def onDetachSlideshow(self):
        """detach/attach slideshow from explorer splitter"""
        self.createSlideshowWidget(self.slideshow.isTimerActive())
        widget = self.explorerSplitter.widget(WIDGET_SLIDESHOW)
        widget.deleteLater()
        self.setMainExplorerIndex("current")

    def onAttachSlideshow(self):
        """detach/attach slideshow from explorer splitter"""
        prevSlideshow = self.slideshow
        self.createSlideshowWidget(self.slideshow.isTimerActive())
        prevSlideshow.deleteLater()
        self.explorerSplitter.addWidget(self.slideshow)
        self.setMainExplorerIndex("current")

    def onStartSlideshow(self):
        """ "Start slideshow of current folder"""
        self.slideshow.setHidden(False)
        self.updateToolbar()
        self.setMainExplorerIndex("first")
        self.slideshow.setTimerEnabled(True)

    def onContinueSlideshow(self):
        """ "Start slideshow of current folder"""
        self.slideshow.setHidden(False)
        self.updateToolbar()
        self.setMainExplorerIndex("current")
        self.slideshow.setTimerEnabled(True)

    def onPauseSlideshow(self):
        """ "Start slideshow of current folder"""
        self.slideshow.setTimerEnabled(False)

    def onPrevSlide(self):
        """click button prev in slideshow"""
        self.setMainExplorerIndex("prev")

    def onNextSlide(self):
        """click button next in slideshow"""
        log.info("onNextSlide")
        self.setMainExplorerIndex("next")

    def tabTagContextItemMenu(self, position, widget, shared):
        """create context menu for tab Tag"""
        item: QTableWidgetItem = widget.itemAt(position)
        parent = widget.parent()
        parent = parent.parent()
        if item.column() != 0:
            return
        tagName = item.text()
        menu = QMenu()
        action = QAction("Search Tag", self)
        action.setStatusTip(f'Search Tag "{tagName}"')
        action.triggered.connect(
            lambda vv, section="tag", tag=tagName, shared=shared: self.Search(section, tag, shared)
        )
        menu.addAction(action)
        menu.exec(QCursor.pos())

    def loginDialog(self):
        """login dialog : create new model, reset views"""
        dialog = LoginDialog(self)
        if not dialog.exec():
            return
        connected = self.synoPhotosLogin(
            dialog.address.text(),
            dialog.port.text(),
            dialog.username.text(),
            dialog.password.text(),
            dialog.secure.isChecked(),
            dialog.certverif.isChecked(),
            dialog.debug.isChecked(),
            dialog.otpcode.text(),
        )
        if not connected:
            ret = FailedConnectDialog(synofoto.exception, self).exec()
            if not ret:
                QApplication.quit()
        # set new models using new synophoto
        self.mainModel = SynoModel(dirs_only=False)
        self.mainExplorer.setModel(self.mainModel)

        self.sideModel = SynoModel(dirs_only=True)
        self.sideExplorer.setModel(self.sideModel)

        # reset widgets
        self.json_view.setModel(JsonModel(data={}))
        self.thumbnailWidget.setImage(QPixmap())

        # set to root path
        self.currentDir = "/"
        self.mainModel.setRootPath(self.currentDir)
        self.sideExplorer.model().setRootPath(self.currentDir)
        self.sideExplorer.expandAbsolutePath(self.currentDir)
        self.navigate(self.mainModel.setRootPath(self.currentDir))

        # TODO : may be something wrong : signals lost after setmodel !?
        #  as workaround (but enough ?) :
        self.sideExplorer.selectionModel().currentRowChanged.connect(self.onCurrentRowChangedInSideExpl)
        self.changeView(self.currentExplorerView)

    def about(self):
        """dialog about app"""
        AboutDialog(self).exec()

    def showJsonView(self, event):
        """show dock JSON view"""
        self.json_dock.setHidden(not event)

    def showThumbView(self, event):
        """show dock thumbnail view"""
        self.thumbnail_dock.setHidden(not event)

    def showLogView(self, event):
        """show dock log view"""
        self.log_dock.setHidden(not event)

    def showHideTree(self, event):
        """show/hide tree explorer"""
        self.sideExplorer.setHidden(not event)

    def showHideList(self, event):
        """show/hide list explorer"""
        self.mainExplorer.setHidden(not event)

    def showHideSlide(self, event):
        """show/hide slide show"""
        self.slideshow.setHidden(not event)
        if event and self.modeFullscreen:
            self.slideshow.showFullScreen()

    def selectAll(self):
        """select all in main explorer"""
        self.mainExplorer.selectAll()

    def unselectAll(self):
        """unselect all in main explorer"""
        self.mainExplorer.selectionModel().clearSelection()

    def navigate(self, index):
        """navigate - index (always folder) from mainExplorer"""
        nodeIndex = index.model().nodeIndex(index)
        node = nodeIndex.internalPointer()
        currentDir = self.mainModel.absoluteFilePath(nodeIndex)
        if currentDir == self.currentDir:
            return
        self.currentDir = currentDir

        log.info(f"navigate inode {node.inode} {node.dataColumn(0)} -> {self.currentDir}")
        # navigate in folder => stop current slide show
        self.slideshow.setTimerEnabled(False)

        self.mainModel.setRootPath(self.currentDir)
        # need to have real count
        self.mainModel.updateIfUnknownRowCount(nodeIndex)
        self.mainExplorer.setRootIndex(index)
        # scroll to first item, but no set index
        child = node.child(0)
        if child:
            indexChild = self.mainModel.createIndex(child.row(), 0, child)
            self.mainExplorer.selectionModel().setCurrentIndex(indexChild, QItemSelectionModel.SelectionFlag.Clear)
            self.mainExplorer.scrollTo(indexChild)
        self.setWindowTitle(f"Synology Photos Explorer - {self.currentDir}")
        self.addressBar.setText(self.currentDir)
        # set json, invalidate thumbnail widget
        self.json_view.setModel(JsonModel(data=formatJson(node.rawData())))
        self.thumbnailWidget.setImage(QPixmap())
        self.slideshow.setPhoto(QPixmap())
        # download child thumbnails
        self.download_childs_thumbnail(node)
        self.history.append(self.currentDir)

    def navigateUp(self):
        """navigate parent folder"""
        self.currentDir = os.path.dirname(self.currentDir)
        self.navigate(self.mainModel.setRootPath(self.currentDir))

    def navigateForward(self):
        """navigate next folder in history"""
        log.info("navigateForward")
        path = self.history.forward()
        if path:
            index = self.sideExplorer.model().pathIndex(path)
            self.sideExplorer.setCurrentIndex(index)

    def navigateBack(self):
        """navigate previous folder in history"""
        log.info("navigateBack")
        path = self.history.back()
        if path:
            index = self.sideExplorer.model().pathIndex(path)
            self.sideExplorer.setCurrentIndex(index)

    def navigateAddress(self):
        """enter in address bar => navigate
        Warning : case sensitive
        """
        path = self.addressBar.text()
        index = self.sideExplorer.model().pathIndex(path)
        newPath = self.sideExplorer.model().absoluteFilePath(index)
        if PurePosixPath(path) != PurePosixPath(newPath):
            log.info("Invalid address")
            self.addressBar.selectAll()
            self.statusBar().showMessage("Error: Invalid address")
            return
        self.navigate(self.mainModel.pathIndex(path))

    def updateStatus(self, element: QModelIndex | str = None):
        """update status bar from path or QModelIndex"""
        # log.info("updateStatus")
        index = element if isinstance(element, QModelIndex) else self.mainModel.pathIndex(element)
        index = index.model().nodeIndex(index)
        self.mainModel.updateIfUnknownRowCount(index)
        status = ""
        node: SynoNode = index.internalPointer()
        if node.node_type in [NodeType.SPACE, NodeType.FOLDER, NodeType.SEARCH]:
            status = f"{node.foldersNumber()} folders,  {node.photosNumber()} photos"
        elif node.node_type == NodeType.FILE:
            parent = node.parent()
            if parent.node_type == NodeType.FOLDER:
                status = f"{parent.foldersNumber()} folders,  {parent.photosNumber()} photos - {node.dataColumn(0)}: {node.dataColumn(1)}, {node.dataColumn(2)}"
        else:
            return
        selectedCount = len(
            [index for index in self.mainExplorer.selectionModel().selectedIndexes() if index.column() == 0]
        )
        if selectedCount > 0:
            status += f" ({selectedCount} elements selected)"
        self.statusBar().showMessage(status)

    def onDoubleClick(self, index):
        """signal doubleClick in mainExplorer for open folder"""
        node = index.model().nodePointer(index)
        if node.isDir():
            self.navigate(index)
            self.download_childs_thumbnail(node)

    def onCurrentRowChangedInSideExpl(self, index: QModelIndex):
        """signal selection changed (a folder) in side explorer"""
        log.info("on current row changed from left side")
        path = index.model().absoluteFilePath(index)
        self.updateStatus(path)
        log.info(f"change row side : {path}")
        self.navigate(self.mainExplorer.model().pathIndex(path))

    def onSelectionChanged(self, selected: QItemSelection, deselected: QItemSelection):
        """signal selection changed in mainExplorer"""
        log.info(f"onSelectionChanged selected:{selected.count()}, deselect:{deselected.count()}")
        index = self.mainExplorer.selectionModel().currentIndex()
        if not index.isValid():
            log.info("invalid selection currentIndex %s", index.model())
            return
        self.updateStatus(self.mainExplorer.selectionModel().currentIndex())

    def onCurrentRowChanged(self, index: QModelIndex):
        """selection changed in main explorer"""
        log.info("onCurrentRowChanged")
        if not index.isValid():
            return
        node: SynoNode = index.model().nodePointer(index)
        data = node.rawData()
        # set json data
        self.json_view.setModel(JsonModel(data=formatJson(data)))
        # set thumbnail
        if node.node_type == NodeType.FOLDER:
            pass
        elif node.node_type == NodeType.FILE and node._raw_data["type"] == "photo":
            shared = node.isShared()
            # use cached function :
            raw_image = download_thumbnail(
                node.inode,
                node.rawData()["additional"]["thumbnail"]["cache_key"],
                shared,
                node.passphrase(),
            )
            if not raw_image:
                return
            if CACHE_PIXMAP:
                image = QPixmap()
                image.loadFromData(raw_image)
                self.thumbnailWidget.setImage(image)
            else:
                pixmap = QPixmap()
                image = QImage()
                image.loadFromData(raw_image)
                colorspace = image.colorSpace()
                if not colorspace.description().startswith("sRGB"):
                    log.debug(f"convert colorspace {colorspace.description()}")
                    srgbColorSpace = QColorSpace(QColorSpace.NamedColorSpace.SRgb)
                    image.convertToColorSpace(srgbColorSpace)
                pixmap.convertFromImage(image)
                self.thumbnailWidget.setImage(pixmap)
            # show image in slideshow
            self.slideshow.setPhoto(node)
            log.debug(f"cache stats: {thumbcache.stats()}")
        else:
            pixmap = QPixmap()
            self.thumbnailWidget.setImage(pixmap)
            self.slideshow.setPhoto(pixmap)

    def Search(self, section, searchText, shared):
        """Search photos"""
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        # search in 2 models
        index = self.mainExplorer.model().search(section, searchText, shared)
        self.sideExplorer.model().search(section, searchText, shared)
        self.navigate(index)
        # expand and select path in sideExplorer
        self.sideExplorer.setCurrentIndex(self.sideExplorer.expandAbsolutePath(self.currentDir))
        QApplication.restoreOverrideCursor()
        # search appears in main explorer : show it
        self.tab_widget.setCurrentTab(TAB_MAIN_EXPLORER)
        self.updateStatus(self.currentDir)

    def onSearch(self):
        """Enter in search bar"""
        searchText = self.searchField.text()
        where = self.searchWhere.currentText()
        if where in [WHERE_TAG_PERSONAL, WHERE_TAG_SHARED]:
            team = where == WHERE_TAG_SHARED
            self.Search("tag", searchText, team)
        elif where in [WHERE_KEYWORD_PERSONAL, WHERE_KEYWORD_SHARED]:
            team = where == WHERE_KEYWORD_SHARED
            self.Search("keyword", searchText, team)

    def onPinSearch(self, index):
        """pin search"""
        path = index.internalPointer().absoluteFilePath()
        # get a "place" in registry
        place = 1
        while True:
            if self.settings.value(f"pinnedSearch/{place}", None) is None:
                break
            place += 1
        self.settings.setValue(f"pinnedSearch/{place}", path)

    def onUnpinSearch(self, index: QModelIndex) -> None:
        """unpin search"""
        path = index.internalPointer().absoluteFilePath()
        # search in registry
        self.settings.beginGroup("pinnedSearch")
        keys = self.settings.childKeys()
        for key in keys:
            regPath = self.settings.value(key)
            if path == regPath:
                self.settings.remove(key)
                break
        self.settings.endGroup()

    def isPinnedSearch(self, index: QModelIndex) -> bool:
        """return True if search is pinned"""
        path = index.internalPointer().absoluteFilePath()
        # search in registry
        self.settings.beginGroup("pinnedSearch")
        keys = self.settings.childKeys()
        for key in keys:
            if path == self.settings.value(key):
                self.settings.endGroup()
                return True
        self.settings.endGroup()
        return False

    def onShowTagsList(self, tabname: str):
        """open tab tags list"""
        tab = self.tab_widget.setCurrentTab(tabname)
        if tab is not None:
            # already open
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        team = tabname == TAB_SHARED_TAGS
        tags = synofoto.api.general_tags(team=team)
        widget = QTableWidget(len(tags), 3)
        widget.setHorizontalHeaderLabels(["Name", "id", "Count"])
        for row, tag in enumerate(tags):
            item = QTableWidgetItem(tag["name"])
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            widget.setItem(row, 0, item)
            # use IntIntSortTableItem for sort column of type Int
            item = IntSortTableItem(str(tag["id"]))
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            widget.setItem(row, 1, item)
            item = IntSortTableItem(str(tag["item_count"]))
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            widget.setItem(row, 2, item)
        widget.setSortingEnabled(True)
        widget.sortItems(0, Qt.SortOrder.AscendingOrder)
        self.tab_widget.addTab(widget, tabname)
        QApplication.restoreOverrideCursor()
        # self.updateStatus(f"activate {TAB_SHARED_TAGS}")
        widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        widget.customContextMenuRequested.connect(
            lambda pos, child=widget, shared=team: self.tabTagContextItemMenu(pos, child, shared)
        )

    def onRemoveTag(self, index: QModelIndex):
        """remove Tag(s) from models"""
        # remove node from 2 models : sideExplorer and mainExplorer
        path = index.internalPointer().absoluteFilePath()
        index = self.sideExplorer.model().pathIndex(path)
        index.model().removeNode(index)
        index = self.mainExplorer.model().pathIndex(path)
        index.model().removeNode(index)

    def onDownload(self):
        """download photos in `download` folder"""
        self.downloadSelected(self.mainExplorer.selectionModel().selectedIndexes(), get_download_path())

    def onDownloadTo(self):
        """download photos in folder to choose"""
        dlg = QFileDialog()
        folder = dlg.getExistingDirectory(self, "Select directory to download")
        if not folder:
            return
        self.downloadSelected(self.mainExplorer.selectionModel().selectedIndexes(), folder)

    def sideSelectedToMainIndexes(self):
        """return selected folder of sideExplorer in mainEplorer indexes"""
        sideIndexes = [index for index in self.sideExplorer.selectionModel().selectedIndexes() if index.column() == 0]
        return [
            self.mainExplorer.model().pathIndex(self.sideExplorer.model().absoluteFilePath(index))
            for index in sideIndexes
        ]

    def onSideDownload(self):
        """download photos in `download` folder"""
        self.downloadSelected(self.sideSelectedToMainIndexes(), get_download_path())

    def onSideDownloadTo(self):
        """download photos in folder to choose"""
        dlg = QFileDialog()
        folder = dlg.getExistingDirectory(self, "Select directory to download")
        if not folder:
            return
        self.downloadSelected(self.sideSelectedToMainIndexes(), folder)

    def downloadSelected(self, indexes, path):
        """download photos in folder"""

        def photo_download(node: SynoNode, destination: str):
            shared = node.space == SpaceType.SHARED if not node.space == SpaceType.ALBUM else None
            try:
                raw_image = synofoto.api.photo_download(node.inode, shared)
            except Exception as _e:
                log.error(f"Failed download {node.dataColumn(0)}")
                return
            name = str(os.path.join(destination, node.dataColumn(0)))
            with open(name, "wb") as file:
                file.write(raw_image)

        for index in indexes:
            if index.column() > 0:
                continue
            node: SynoNode = index.model().nodePointer(index)
            if node.node_type == NodeType.FILE:
                log.info(f"Download photo inode {node.inode} {node.dataColumn(0)}")
                photo_download(node, path)
            elif node.node_type in [NodeType.FOLDER, NodeType.SEARCH]:
                log.info(f"Download photos folder inode {node.inode} {node.dataColumn(0)}")
                dest = os.path.join(path, node.dataColumn(0))
                os.makedirs(dest, exist_ok=True)
                for ichild in range(0, node.childCount()):
                    child = node.child(ichild)
                    log.info(f"Download photo {child.dataColumn(0)} ({child.inode})")
                    photo_download(child, dest)
            log.info("Download end")

    def download_childs_thumbnail(self, node: SynoNode):
        """start a thread download thumbnails for all childs of the node"""
        log.info("download_childs_thumbnail start")
        if node.isUnknownRowCount():
            return
        if USE_THREAD_CHILDS:
            control_thread_pool.cancel_futures()
            if self.futureDownloadChilds:
                self.eventCancelThumb.set()
                self.futureDownloadChilds.result()
            self.eventCancelThumb.clear()
            node.child(0)  # ensure that all child nodes created
            self.futureDownloadChilds = download_thread_pool.submit(self._thread_download_childs_thumbnail, node)
        else:
            for iChild in range(0, node.childCount()):
                child = node.child(iChild)
                if child.isFile():
                    self.get_thumbnail_cached(child)
        log.info("download_childs_thumbnail end")

    def _thread_download_childs_thumbnail(self, node: SynoNode):
        """to be execute in thread (see download_childs_thumbnail)"""

        def get_thumbnail_cached(node: SynoNode):
            inode = node.inode
            shared = node.isShared()
            if not "additional" in node.rawData():
                log.warning("No additionnal datas")
                return None
            syno_key = node.rawData()["additional"]["thumbnail"]["cache_key"]
            key = get_cache_key(
                (THUMB_CALLABLE_NAME,),
                (
                    node.inode,
                    node.rawData()["additional"]["thumbnail"]["cache_key"],
                    shared,
                    node.passphrase(),
                ),
                {},
                False,
                (),
            )
            if key in thumbcache:
                # nothing to do
                return
            future = download_thread_pool.submit(download_thumbnail, inode, syno_key, shared, passphrase)
            # add to future pool
            control_thread_pool.add_future(future)

        # thread begin
        log.info(f"thread childs download start for inode {node.inode}")
        for iChild in range(0, node.childCount()):
            if self.eventCancelThumb.wait(0.001):
                log.info("thread childs download CANCELLED")
                return
            child = node.child(iChild)
            if child is None:
                log.error("child is None")
                continue
            if child.isFile():
                get_thumbnail_cached(child)
        log.info("thread childs download end")

    def get_thumbnail_cached(self, node: SynoNode):
        """add thumbnail for download by thread pool"""
        inode = node.inode
        shared = node.isShared()
        if not "additional" in node.rawData():
            log.error("no additional fields")
            return None
        syno_key = node.rawData()["additional"]["thumbnail"]["cache_key"]
        key = get_cache_key(
            (THUMB_CALLABLE_NAME,),
            (
                node.inode,
                node.rawData()["additional"]["thumbnail"]["cache_key"],
                shared,
                node.passphrase(),
            ),
            {},
            False,
            (),
        )
        if key in thumbcache:
            # nothing to do
            return
        future = download_thread_pool.submit(download_thumbnail, inode, syno_key, shared, node.passphrase())
        # add to future pool
        control_thread_pool.add_future(future)

        return future


class IntSortTableItem(QTableWidgetItem):
    """
    IntSortTableItem : allow column sort for int value.

    Use with QTableWidget
    """

    def __lt__(self, other):
        try:
            return int(self.text()) < int(other.text())
        except ValueError:
            return super(IntSortTableItem, self).__lt__(other)


def formatJson(data):
    """try to replace timestamp with date"""
    data = dict(data)

    def replace(key, div=1):
        if key in data:
            data[key] = DatePhoto.from_timestamp(data[key] // div).to_string()

    for key in ["time", "create_time", "end_time", "start_time"]:
        replace(key)
    for key in ["indexed_time"]:
        replace(key, 1000)
    return data


def get_download_path():
    """return standard download folder"""
    if os.name == "nt":
        sub_key = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
        downloads_guid = "{374DE290-123F-4565-9164-39C4925E467B}"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub_key) as key:
            location = winreg.QueryValueEx(key, downloads_guid)[0]
        return location
    else:
        return os.path.join(os.path.expanduser("~"), "downloads")


if __name__ == "__main__":
    if "-V" in sys.argv or "--version" in sys.argv:
        print(f"{APP_NAME} - Version {VERSION}")
        # exit threads (launched globally)
        control_thread_pool.exit_loop()
        download_thread_pool.shutdown(wait=True, cancel_futures=True)
        sys.exit()

    app = QApplication(sys.argv)
    myApp = App()
    sys.exit(app.exec())
