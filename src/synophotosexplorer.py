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
    QLineEdit,
    QSplitter,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QToolButton,
    QMenu,
    QWidget,
    QDockWidget,
    QFrame,
    QFileDialog,
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
    QSettings,
    QTimer,
)

from diskcache.core import args_to_key as get_cache_key
from cache import cache, download_thread_pool, THUMB_CALLABLE_NAME, control_thread_pool

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

from internalconfig import USE_LOG_WIDGET, USE_THREAD_CHILDS, INITIAL_PATH, APP_NAME, CACHE_PIXMAP, VERSION
from cacheddownload import download_thumbnail
from loggerwidget import LoggerWidget
from photosview import PhotosIconView, PhotosDetailsView
from synotreeview import SynoTreeView
from imagewidget import ImageWidget
from uidialogs import LoginDialog, AboutDialog, FailedConnectDialog




# set logger in stdout
log = logging.getLogger()
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


class History:
    """
    manage history navigation
    """

    def __init__(self, max):
        self.max = max
        self.histback = []
        self.histforward = []

    def append(self, value):
        if self.histback and value == self.histback[-1]:
            return
        self.histback.append(value)
        if len(self.histback) > self.max:
            self.histback.pop(0)

    def back(self):
        if not self.histback or len(self.histback) == 1:
            return None
        value = self.histback.pop(-1)
        self.histforward.append(value)
        return self.histback[-1]

    def forward(self):
        if not self.histforward:
            return None
        value = self.histforward.pop(-1)
        self.histback.append(value)
        return value


def fatalConnect(quit=False):
    def getMainWindow():
        app = QApplication.instance()
        for widget in app.topLevelWidgets():
            if isinstance(widget, QMainWindow):
                return widget
        return None

    parent = getMainWindow()
    ret = FailedConnectDialog(synofoto.exception, parent).exec()
    if not ret:
        QApplication.quit()


class App(QMainWindow):
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
        self.restoreDockWidget(self.json_dock)
        self.jsonViewAction.setChecked(not self.json_dock.isHidden())
        self.restoreDockWidget(self.thumbnail_dock)
        self.thumbViewAction.setChecked(not self.thumbnail_dock.isHidden())
        if USE_LOG_WIDGET:
            self.restoreDockWidget(self.log_dock)
            self.logViewAction.setChecked(not self.log_dock.isHidden())

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
        synofoto.login(
            address, port, username, password, secure, certverif, 7, debug, otpcode
        )
        log.info(
            f"connected = {synofoto.is_connected()} to Synology Photos ({os.environ.get('SYNO_ADDR')})"
        )
        return synofoto.is_connected()

    def initUI(self):
        """init User Interface"""
        # Side explorer with dirs only
        self.sideExplorer = SynoTreeView()
        self.sideExplorer.setModel(SynoModel(dirs_only=True))
        self.sideExplorer.hideColumn(3)
        self.sideExplorer.hideColumn(2)
        self.sideExplorer.hideColumn(1)
        self.sideExplorer.header().hide()
        self.sideExplorer.selectionModel().currentRowChanged.connect(
            self.onCurrentRowChangedInSideExpl
        )

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

        # model for explorer
        self.mainModel = SynoModel(dirs_only=False, additionnal=["thumbnail", "exif", "resolution"])

        # Top menus
        self.createTopMenu()
        self.createActionBar()

        # Main explorer
        self.currentExplorerView = self.settings.value("viewtype", "Details")
        self.changeView(self.currentExplorerView)

        # Set layout and views
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        explorerLayout = QHBoxLayout()
        explorerLayout.setContentsMargins(0, 0, 0, 0)

        layout.addLayout(explorerLayout)

        self.explorerSplitter = QSplitter(Qt.Orientation.Horizontal)
        self.explorerSplitter.addWidget(self.sideExplorer)
        self.explorerSplitter.addWidget(self.mainExplorer)

        self.explorerSplitter.setStretchFactor(1, 2)
        self.explorerSplitter.setSizes([400, 800])
        explorerLayout.addWidget(self.explorerSplitter)

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

        # initial path
        self.currentDir = self.settings.value("initialpath", INITIAL_PATH)
        self.sideExplorer.model().setRootPath(self.currentDir)
        self.sideExplorer.expandAbsolutePath(self.currentDir)
        self.navigate(self.mainExplorer.model().setRootPath(self.currentDir))
        self.show()
        log.info("END InitUI")

    def createTopMenu(self):
        # Add menus
        menuBar = self.menuBar()

        fileMenu = menuBar.addMenu("&File")
        self.editMenu = menuBar.addMenu("&Edit")
        # aboutToShow signal used for update menu
        self.editMenu.aboutToShow.connect(self.updateEditMenu)
        viewMenu = menuBar.addMenu("&View")
        helpMenu = menuBar.addMenu("&Help")

        # File
        loginAction = QAction("&Synology login ...", self)
        loginAction.triggered.connect(self.loginDialog)
        fileMenu.addAction(loginAction)

        fileMenu.addSeparator()

        exitAction = QAction("&Quit", self)
        exitAction.triggered.connect(self.quitApp)
        exitAction.setShortcut("Ctrl+Q")
        fileMenu.addAction(exitAction)

        # Edit
        selectAllAction = QAction("&Select All", self)
        selectAllAction.setStatusTip("Select All")
        selectAllAction.setShortcut("Ctrl+A")
        selectAllAction.triggered.connect(self.selectAll)
        self.editMenu.addAction(selectAllAction)

        unselectAllAction = QAction("&Unselect All", self)
        unselectAllAction.setStatusTip("Unselect All")
        unselectAllAction.setShortcut("Ctrl+D")
        unselectAllAction.triggered.connect(self.unselectAll)
        self.editMenu.addAction(unselectAllAction)

        self.editMenu.addSeparator()

        self.downloadToAction = QAction("Download To ...", self)
        self.downloadToAction.setStatusTip("Download selected elements to folder")
        self.downloadToAction.triggered.connect(self.onDownloadTo)
        self.editMenu.addAction(self.downloadToAction)

        self.downloadAction = QAction("Download", self)
        self.downloadAction.setStatusTip("Download selected elements to 'Download' folder")
        self.downloadAction.triggered.connect(self.onDownload)
        self.editMenu.addAction(self.downloadAction)

        # View
        self.iconsViewAction = QAction("&Thumbnails", self)
        self.iconsViewAction.setStatusTip("Thumbnail list view")
        self.iconsViewAction.setCheckable(True)
        self.iconsViewAction.triggered.connect(
            lambda setview, view="Icons": self.changeView(view)
        )
        viewMenu.addAction(self.iconsViewAction)

        self.detailViewAction = QAction("&Details", self)
        self.detailViewAction.setStatusTip("Details view")
        self.detailViewAction.setCheckable(True)
        self.detailViewAction.triggered.connect(
            lambda setview, view="Details": self.changeView(view)
        )
        viewMenu.addAction(self.detailViewAction)

        viewMenu.addSeparator()

        self.jsonViewAction = QAction("&JSON view", self)
        self.jsonViewAction.setStatusTip("Show JSON view")
        self.jsonViewAction.setShortcut("Ctrl+J")
        self.jsonViewAction.setCheckable(True)
        self.jsonViewAction.triggered.connect(self.showJsonView)
        viewMenu.addAction(self.jsonViewAction)

        self.thumbViewAction = QAction("&Thumbnail view", self)
        self.thumbViewAction.setStatusTip("Show Thumbnail view")
        self.thumbViewAction.setShortcut("Ctrl+T")
        self.thumbViewAction.setCheckable(True)
        self.thumbViewAction.triggered.connect(self.showThumbView)
        viewMenu.addAction(self.thumbViewAction)

        if USE_LOG_WIDGET:
            self.logViewAction = QAction("&Log view", self)
            self.logViewAction.setStatusTip("Show Log view")
            self.logViewAction.setCheckable(True)
            self.logViewAction.triggered.connect(self.showLogView)
            viewMenu.addAction(self.logViewAction)

        # About
        aboutAction = QAction("&About", self)
        aboutAction.setStatusTip("About")
        aboutAction.triggered.connect(self.about)
        helpMenu.addAction(aboutAction)

    def createActionBar(self):
        self.toolbar = self.addToolBar("actionToolBar")
        self.toolbar.setObjectName("action_toolbar")
        self.toolbar.setMovable(False)
        self.toolbar.setFloatable(False)

        self._navigateBackButton = QToolButton()
        self._navigateBackButton.setIcon(QIcon("./src/ico/arrow-180.png"))
        self._navigateBackButton.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonIconOnly
        )
        self._navigateBackButton.clicked.connect(self.navigateBack)

        self._navigateForwardButton = QToolButton()
        self._navigateForwardButton.setIcon(QIcon("./src/ico/arrow.png"))
        self._navigateForwardButton.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonIconOnly
        )
        self._navigateForwardButton.clicked.connect(self.navigateForward)

        self._navigateUpButton = QToolButton()
        self._navigateUpButton.setIcon(QIcon("./src/ico/arrow-090.png"))
        self._navigateUpButton.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._navigateUpButton.clicked.connect(self.navigateUp)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.addressBar = QLineEdit()
        self.addressBar.setMaxLength(255)
        self.addressBar.returnPressed.connect(self.navigateAddress)
        splitter.addWidget(self.addressBar)

        self.searchField = QLineEdit()
        self.searchField.setPlaceholderText("Search")
        splitter.addWidget(self.searchField)

        splitter.setStretchFactor(10, 1)
        splitter.setSizes([500, 200])

        self.toolbar.addWidget(self._navigateBackButton)
        self.toolbar.addWidget(self._navigateForwardButton)
        self.toolbar.addWidget(self._navigateUpButton)
        self.toolbar.addWidget(splitter)
        self.toolbar.setStyleSheet("QToolBar { border: 0px }")

    def changeView(self, view):
        self.currentExplorerView = view
        if view == "Icons":
            self.iconsViewAction.setChecked(True)
            self.detailViewAction.setChecked(False)
            self.mainExplorer = PhotosIconView(self.mainModel)

        elif view == "Details":
            self.iconsViewAction.setChecked(False)
            self.detailViewAction.setChecked(True)
            self.mainExplorer = PhotosDetailsView(self.mainModel)

        # Common settings
        self.mainExplorer.doubleClicked.connect(self.onDoubleClick)

        self.mainExplorer.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.mainExplorer.customContextMenuRequested.connect(self.contextItemMenu)

        selectionModel = QItemSelectionModel(self.mainExplorer.model())
        self.mainExplorer.setSelectionModel(selectionModel)
        self.mainExplorer.selectionModel().currentRowChanged.connect(
            self.onCurrentRowChanged
        )
        self.mainExplorer.selectionModel().selectionChanged.connect(
            self.onSelectionChanged
        )
        if hasattr(self, "explorerSplitter"):
            self.explorerSplitter.replaceWidget(1, self.mainExplorer)
            self.mainExplorer.setRootIndex(self.mainExplorer.model().setRootPath(self.currentDir))

    def closeEvent(self, event):
        """close app"""
        # save geometry on close
        self.settings.setValue("mainwinpos", self.saveGeometry())
        self.settings.setValue("mainwinstate", self.saveState())
        # save various parameter
        self.settings.setValue("initialpath", self.currentDir)
        self.settings.setValue("viewtype", self.currentExplorerView)

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
        self.close()


    def updateEditMenu(self):
        """ update edit menu """
        hasSelection = self.mainExplorer.selectionModel().hasSelection()
        self.downloadToAction.setEnabled(hasSelection)
        self.downloadAction.setEnabled(hasSelection)


    def contextItemMenu(self, position):
        """ create context menu main explorer"""
        menu = QMenu()
        self.updateEditMenu()
        menu.addAction(self.downloadToAction)
        menu.addAction(self.downloadAction)
        menu.exec(QCursor.pos())

    def sideContextItemMenu(self, position):
        """ create context menu side explorer """
        menu = QMenu()
        menu.addAction(self.sideDownloadToAction)
        menu.addAction(self.sideDownloadAction)
        menu.exec(QCursor.pos())

    def loginDialog(self):
        """ login dialog : create new model, reset views """
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

        # TODO : seems something wrong : signals lost after setmodel !?
        #  as workaround (but enough ?) :
        self.sideExplorer.selectionModel().currentRowChanged.connect(
            self.onCurrentRowChangedInSideExpl
        )
        self.changeView(self.currentExplorerView)

    def about(self, event):
        AboutDialog(self).exec()

    def showJsonView(self, event):
        self.json_dock.setHidden(not event)

    def showThumbView(self, event):
        self.thumbnail_dock.setHidden(not event)

    def showLogView(self, event):
        self.log_dock.setHidden(not event)

    def selectAll(self, event):
        self.mainExplorer.selectAll()

    def unselectAll(self):
        self.mainExplorer.selectionModel().clearSelection()

    def navigate(self, index):
        """ navigate - index must be SynoSortFilterProxyModel"""
        nodeIndex = index.model().nodeIndex(index)
        node = nodeIndex.internalPointer()
        log.info(f"navigate inode {node.inode} {node.dataColumn(0)}")
        self.currentDir = self.mainModel.absoluteFilePath(nodeIndex)
        self.mainModel.setRootPath(self.currentDir)
        # need to have real count
        self.mainModel.updateIfUnknownRowCount(nodeIndex)

        self.mainExplorer.setRootIndex(index)
        # scroll to first item
        child = node.child(0)
        if child:
            indexChild = self.mainModel.createIndex(child.row(), 0, child)
            self.mainExplorer.selectionModel().setCurrentIndex(
                indexChild, QItemSelectionModel.SelectionFlag.Clear
            )
            self.mainExplorer.scrollTo(indexChild)
        self.setWindowTitle(f"Synology Photos Explorer - {self.currentDir}")
        self.addressBar.setText(self.currentDir)
        # invalid widget thumbnail and json
        self.json_view.setModel(JsonModel(data=formatJson(node.rawData())))
        self.thumbnailWidget.setImage(QPixmap())
        # download child thumbnails
        self.download_childs_thumbnail(node)
        self.history.append(self.currentDir)


    def navigateUp(self, event):
        self.currentDir = os.path.dirname(self.currentDir)
        self.navigate(self.mainModel.setRootPath(self.currentDir))

    def navigateForward(self, event):
        log.info("navigateForward")
        path = self.history.forward()
        if path:
            index = self.sideExplorer.model().pathIndex(path)
            self.sideExplorer.setCurrentIndex(index)

    def navigateBack(self, event):
        log.info("navigateBack")
        path = self.history.back()
        if path:
            index = self.sideExplorer.model().pathIndex(path)
            self.sideExplorer.setCurrentIndex(index)

    def navigateAddress(self):
        """Enter in address bar -> navigate
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
        self.navigate(self.sideExplorer.model().pathIndex(path))

    def updateStatus(self, element=None):
        """update status bar from path or QModelIndex"""
        log.info("updateStatus")
        if element is None:
            index = self.mainExplorer.selectionModel().currentIndex()
        else:
            index = (
                element
                if isinstance(element, QModelIndex)
                else self.mainModel.pathIndex(element)
            )
        index = index.model().nodeIndex(index)
        self.mainModel.updateIfUnknownRowCount(index)
        status = ""
        node: SynoNode = index.internalPointer()
        if node.node_type == NodeType.FOLDER:
            status = f"{node.foldersNumber()} folders,  {node.photosNumber()} photos"
        elif node.node_type == NodeType.FILE:
            parent = node.parent()
            if parent.node_type == NodeType.FOLDER:
                status = (
                    f"{parent.foldersNumber()} folders,  {parent.photosNumber()} photos"
                )
        else:
            return
        selectedCount = len(
            [
                index
                for index in self.mainExplorer.selectionModel().selectedIndexes()
                if index.column() == 0
            ]
        )
        if selectedCount > 0:
            status += f" ({selectedCount} elements selected)"
        self.statusBar().showMessage(status)

    def onDoubleClick(self, index):
        """DoubleClick in mainExplorer for open folder"""
        node = index.model().nodePointer(index)
        if node.isDir():
            self.navigate(index)
            self.download_childs_thumbnail(node)

    def onCurrentRowChangedInSideExpl(self, index: QModelIndex):
        """selection changed (a folder) in side explorer"""
        log.info("on current row changed from left side")
        path = self.sideExplorer.model().absoluteFilePath(index)
        self.updateStatus(path)
        self.navigate(self.mainExplorer.model().pathIndex(path))

    def onSelectionChanged(self, selected: QItemSelection, unselected: QItemSelection):
        self.updateStatus()

    def onCurrentRowChanged(self, index: QModelIndex):
        """selection changed in main explorer"""
        node: SynoNode = index.model().nodePointer(index)
        data = node.rawData()
        # set json data
        self.json_view.setModel(JsonModel(data=formatJson(data)))
        # set thumbnail
        if node.node_type == NodeType.FOLDER:
            pass
        elif node.node_type == NodeType.FILE:
            if node.space == SpaceType.ALBUM:
                # album can have photos in personal or shared space, no way to know
                shared = None
            else:
                shared = node.space == SpaceType.SHARED
            # use cached function :
            raw_image = download_thumbnail(
                node.inode,
                node._raw_data["additional"]["thumbnail"]["cache_key"],
                shared,
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
            log.debug(f"cache stats: {cache.stats()}")


    def onDownload(self, event):
        """download photos in `download` folder"""
        self.downloadSelected(self.mainExplorer.selectionModel().selectedIndexes(), get_download_path())

    def onDownloadTo(self, event):
        """download photos in folder to choose """
        dlg = QFileDialog()
        folder = dlg.getExistingDirectory(self, "Select directory to download")
        if not folder:
            return
        self.downloadSelected(self.mainExplorer.selectionModel().selectedIndexes(), folder)


    def sideSelectedToMainIndexes(self):
        """ return selected folder of sideExplorer in mainEplorer indexes """
        sideIndexes = [
                index
                for index in self.sideExplorer.selectionModel().selectedIndexes()
                if index.column() == 0
            ]
        return [
                self.mainExplorer.model().pathIndex(self.sideExplorer.model().absoluteFilePath(index)) 
                for index in sideIndexes
            ]
    
    def onSideDownload(self, event):
        """download photos in `download` folder"""
        self.downloadSelected(self.sideSelectedToMainIndexes(), get_download_path())

    def onSideDownloadTo(self, event):
        """download photos in folder to choose """
        dlg = QFileDialog()
        folder = dlg.getExistingDirectory(self, "Select directory to download")
        if not folder:
            return
        self.downloadSelected(self.sideSelectedToMainIndexes(), folder)


    def downloadSelected(self, indexes, path):
        """download photos in folder"""

        def photo_download(node: SynoNode, destination: str):
            shared = (
                node.space == SpaceType.SHARED
                if not node.space == SpaceType.ALBUM
                else None
            )
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
            elif node.node_type == NodeType.FOLDER:
                log.info(
                    f"Download photos folder inode {node.inode} {node.dataColumn(0)}"
                )
                dest = os.path.join(path, node.dataColumn(0))
                os.makedirs(dest, exist_ok=True)
                for ichild in range(0, node.childCount()):
                    child = node.child(ichild)
                    log.info(
                        f"Download photo {child.dataColumn(0)} ({child.inode})"
                    )
                    photo_download(child, dest)
            log.info(f"Download end")


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
            self.futureDownloadChilds = download_thread_pool.submit(
                self._thread_download_childs_thumbnail, node
            )
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
            if node.space == SpaceType.ALBUM:
                # album can have photos in personal or shared space, no way to know
                shared = None
            else:
                shared = node.space == SpaceType.SHARED
            if not "additional" in node._raw_data:
                log.warning("No additionnal datas")
                return None
            syno_key = node._raw_data["additional"]["thumbnail"]["cache_key"]
            key = get_cache_key(
                (THUMB_CALLABLE_NAME,),
                (
                    node.inode,
                    node._raw_data["additional"]["thumbnail"]["cache_key"],
                    shared,
                ),
                {},
                False,
                (),
            )
            if key in cache:
                # nothing to do
                return
            future = download_thread_pool.submit(
                download_thumbnail, inode, syno_key, shared
            )
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
        inode = node.inode
        if node.space == SpaceType.ALBUM:
            # album can have photos in personal or shared space, no way to know
            shared = None
        else:
            shared = node.space == SpaceType.SHARED
        if not "additional" in node._raw_data:
            log.error("no additional fields")
            return None
        syno_key = node._raw_data["additional"]["thumbnail"]["cache_key"]
        key = get_cache_key(
            (THUMB_CALLABLE_NAME,),
            (
                node.inode,
                node._raw_data["additional"]["thumbnail"]["cache_key"],
                shared,
            ),
            {},
            False,
            (),
        )
        if key in cache:
            # nothing to do
            return
        future = download_thread_pool.submit(
            download_thumbnail, inode, syno_key, shared
        )
        # add to future pool
        control_thread_pool.add_future(future)

        return future


def formatJson(data):
    """try to replace dates"""
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
