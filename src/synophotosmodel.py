"""
Item Model for Synology Photos

Code based on :
    https://gist.github.com/nbassler/342fc56c42df27239fa5276b79fca8e6
    based on :
        http://trevorius.com/scrapbook/uncategorized/pyqt-custom-abstractitemmodel/



"""

from __future__ import annotations
from typing import Any
import os
from enum import Enum
from pathlib import PurePosixPath
import logging

from PyQt6 import QtCore, QtWidgets, QtGui
from PyQt6.QtWidgets import (
    QApplication,
    QStyle,
)
from PyQt6.QtCore import (
    Qt,
    QAbstractItemModel,
    QModelIndex,
    QSortFilterProxyModel,
    QSize,
    QRect,
    pyqtSignal,
    QObject,
    QVariant,
    QMimeData,
)
from PyQt6.QtGui import (
    QStandardItem,
    QFont,
    QPixmap,
    QImage,
    QColorSpace,
    QColorConstants,
)

from dotenv import load_dotenv

# Maybe in the future Photos will be merged in official synology_api package :
#   from synology_api.photos import Photos, DatePhoto
#   from synology_api.exceptions import PhotosError
from synology_photos_api.photos import DatePhoto

from internalconfig import CACHE_PIXMAP, PHOTOS_CHUNK
from photos_api import synofoto
from utils import smart_unit

from cacheddownload import download_thumbnail


# take environment variables (addr, port ,user, password, ...) from .env file
load_dotenv()

# set logger in stdout
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)


ROOT_NAME = "/"

UNKNOWN_COUNT = -1


class SynoSygnal(QObject):
    """specific signals emitted from model"""

    directoryLoaded = pyqtSignal(str)
    countUpdated = pyqtSignal(str)
    elementsAdded = pyqtSignal(str)


signal = SynoSygnal()


class SpaceType(Enum):
    """Space Types"""

    ROOT = 1
    PERSONAL = 2
    SHARED = 3
    ALBUM = 4
    SEARCH = 5


space_names = {
    SpaceType.ROOT: ROOT_NAME,
    SpaceType.PERSONAL: "Personal",
    SpaceType.SHARED: "Shared",
    SpaceType.ALBUM: "Album",
    SpaceType.SEARCH: "Search",
}


class NodeType(Enum):
    """Node Types"""

    ROOT = 0
    FOLDER = 1
    FILE = 2
    SPACE = 3
    SEARCH = 4


nodetype_names = {
    NodeType.ROOT: "Root",
    NodeType.FOLDER: "Folder",
    NodeType.FILE: "Photo",
    NodeType.SPACE: "Space",
    NodeType.SEARCH: "Search",
}


class SynoNode(QStandardItem):
    """
    Synology Photo Item
    """

    def __init__(
        self,
        space: SpaceType,
        data: Any = None,
        node_type: NodeType = NodeType.ROOT,
        parent: Any = None,
        model: SynoModel = None,
    ):
        QStandardItem.__init__(self)
        self.space = space
        self.node_type = node_type
        self._raw_data = {}
        # INFO : workaround because QStandardItem.model() return always None
        self._model = model

        if self.node_type in [NodeType.ROOT, NodeType.SPACE]:
            self._data = [data]
            self.inode = None if self.node_type == NodeType.ROOT else 0
            self.nb_folders = 0
            if self.space not in [SpaceType.ROOT, SpaceType.SEARCH]:
                self.nb_folders = UNKNOWN_COUNT

        elif self.node_type == NodeType.FOLDER:
            self._raw_data = data
            folder_name = PurePosixPath(self._raw_data["name"]).parts[-1]
            self._data = [folder_name]
            self.inode = self._raw_data["id"]
            self.nb_folders = UNKNOWN_COUNT  # means unknown at this moment

        elif self.node_type == NodeType.FILE:
            # photo json
            self._raw_data = data
            self._data = [
                self._raw_data["filename"],
                DatePhoto(self._raw_data["time"]).to_string("%Y/%m/%d %H:%M:%S"),
                smart_unit(self._raw_data["filesize"], "B"),
            ]
            if "exif" in self._model.additional:
                self._data.extend(
                    [
                        self._raw_data["additional"]["exif"]["aperture"],
                        self._raw_data["additional"]["exif"]["camera"],
                        self._raw_data["additional"]["exif"]["exposure_time"],
                        self._raw_data["additional"]["exif"]["focal_length"],
                        self._raw_data["additional"]["exif"]["iso"],
                        self._raw_data["additional"]["exif"]["lens"],
                    ]
                )
            if "resolution" in self._model.additional:
                self._data.extend(
                    [
                        f'{self._raw_data["additional"]["resolution"]["width"]} x {self._raw_data["additional"]["resolution"]["height"]}',
                    ]
                )
            self.inode = self._raw_data["id"]
            self.nb_folders = 0

        elif self.node_type == NodeType.SEARCH:
            # specific for search space
            self._data = [data]
            self.inode = None
            self.nb_folders = UNKNOWN_COUNT
        else:
            assert False

        self._children = []
        self._parent = parent
        if self._parent:
            self.dirs_only = self._parent.dirs_only
        else:
            self.dirs_only = False
        self.nb_photos = 0

    def __hash__(self):
        return self.inode

    def __eq__(self, other):
        """equality test"""
        return self.inode == other.inode and self._data == other._data and self.space == other.space

    def isDir(self) -> bool:
        """return True if node is folder"""
        return self.node_type in [NodeType.SPACE, NodeType.FOLDER, NodeType.SEARCH]

    def isFile(self) -> bool:
        """return True if node is file"""
        return self.node_type == NodeType.FILE

    def isUnknownRowCount(self) -> bool:
        """return True if node child count is unknown"""
        return self.nb_folders == UNKNOWN_COUNT

    def updateIfUnknownRowCount(self) -> bool:
        """Update node child count if unknown. Return True if updated"""
        if self.nb_folders == UNKNOWN_COUNT:
            return self.updateRowCount()
        return False

    def updateRowCount(self) -> bool:
        """
        Update row count : sub folders + photos

        For performance reason, row count is unknown when item created,
        and must be updated (this function) when a row is clicked

        Return True if updated
        """
        if self.nb_folders != UNKNOWN_COUNT:
            return False
        if self.space == SpaceType.ALBUM:
            if self.node_type == NodeType.SPACE:
                log.warning("updateRowCount count_albums()")
                self.nb_folders = synofoto.api.count_albums(category="normal_share_with_me")
                self._children = [None] * (self.nb_folders)
            elif self.node_type == NodeType.FOLDER:
                self.nb_folders = 0
                if not self.dirs_only:
                    if "item_count" not in self._raw_data:
                        log.warning(f"updateRowCount count_photos_in_album({self.inode})")
                        self.nb_photos = synofoto.api.count_photos_in_album(self.inode)
                    else:
                        self.nb_photos = self._raw_data["item_count"]
                    self._children = [None] * (self.nb_photos)

        elif self.space == SpaceType.SEARCH:
            section, search, team = self.searchContext
            if not self.dirs_only:
                if section == "tag":
                    log.warning(f"count_photos_with_tag({search}, {team})")
                    self.nb_photos = synofoto.api.count_photos_with_tag(search, team=team)
                elif section == "keyword":
                    log.warning(f"count_photos_with_keyword({search}, {team})")
                    self.nb_photos = synofoto.api.count_photos_with_keyword(search, team=team)
                else:
                    assert False
                self._children = [None] * self.nb_photos
            self.nb_folders = 0

        else:
            team = self.space == SpaceType.SHARED
            if self.node_type == NodeType.SPACE:
                # get inode for root folder
                self.inode = synofoto.api.get_folder(team=team)["id"]

            if self.node_type in [NodeType.SPACE, NodeType.FOLDER]:
                log.warning(f"updateRowCount count_folders({self.inode}, {team})")
                self.nb_folders = synofoto.api.count_folders(self.inode, team=team)
                if self.dirs_only:
                    self.nb_photos = 0
                else:
                    log.warning(f"updateRowCount count_photos_in_folder({self.inode}, {team})")
                    self.nb_photos = synofoto.api.count_photos_in_folder(self.inode, team=team)
                self._children = [None] * (self.nb_folders + self.nb_photos)

            elif self.node_type == NodeType.FILE:
                self.nb_folders = self.nb_photos = 0
        signal.countUpdated.emit(str(self.inode))
        return True

    def _createChildNodes(self) -> None:
        """create children nodes for NodeType.FILE"""
        self.updateRowCount()
        if self.space in [SpaceType.PERSONAL, SpaceType.SHARED]:
            log.info(f"list_folders({self.inode}, {self.space == SpaceType.SHARED})")
            elements = synofoto.api.list_folders(
                self.inode,
                self.space == SpaceType.SHARED,
                sort_by="filename",
            )
            log.info(f"photos_in_folder({self.inode}, {self.space == SpaceType.SHARED})")
            if not self.dirs_only:
                left = self.nb_photos
                while left:
                    partial_elements = synofoto.api.photos_in_folder(
                        self.inode,
                        self.space == SpaceType.SHARED,
                        offset=self.nb_photos - left,
                        limit=min(PHOTOS_CHUNK, left),
                        additional=self._model.additional,
                        sort_by="takentime",
                    )
                    left -= len(partial_elements)
                    if left:
                        log.warning(f"{left} photos left")
                    elements.extend(partial_elements)

        elif self.space == SpaceType.SEARCH:
            section, search, team = self.searchContext
            if self.dirs_only:
                return
            if section == "tag":
                log.warning(f"photos_with_tag({search}, {team})")
                left = self.nb_photos
                elements = []
                while left:
                    partial_elements = synofoto.api.photos_with_tag(
                        search,
                        team=team,
                        offset=self.nb_photos - left,
                        limit=min(PHOTOS_CHUNK, left),
                        additional=self._model.additional,
                        sort_by="takentime",
                    )
                    left -= len(partial_elements)
                    if left:
                        log.warning(f"{left} photos left")
                    elements.extend(partial_elements)
            elif section == "keyword":
                log.warning(f"photos_with_keyword({search}, {team})")
                left = self.nb_photos
                elements = []
                while left:
                    partial_elements = synofoto.api.photos_with_keyword(
                        search,
                        team=team,
                        offset=self.nb_photos - left,
                        limit=min(PHOTOS_CHUNK, left),
                        additional=self._model.additional,
                        sort_by="takentime",
                    )
                    left -= len(partial_elements)
                    if left:
                        log.warning(f"{left} photos left")
                    elements.extend(partial_elements)

        elif self.space == SpaceType.ALBUM:
            if self.node_type == NodeType.SPACE:
                log.info("list_albums()")
                elements = synofoto.api.list_albums(sort_by="album_name", category="normal_share_with_me")
            else:
                if not self.dirs_only:
                    log.info(f"photos_in_album({self.inode})")
                    elements = []
                    left = self.nb_photos
                    while left:
                        partial_elements = synofoto.api.photos_in_album(
                            (
                                self.inode
                                if "passphrase" not in self._raw_data or not self._raw_data["passphrase"]
                                else self._raw_data["passphrase"]
                            ),
                            offset=self.nb_photos - left,
                            limit=min(PHOTOS_CHUNK, left),
                            additional=self._model.additional,
                            sort_by="takentime",
                            # passphrase=self._raw_data["passphrase"],
                        )
                        left -= len(partial_elements)
                        if left:
                            log.warning(f"{left} photos left")
                        elements.extend(partial_elements)
        else:
            assert False

        for row, element in enumerate(elements):
            if row < self.nb_folders:
                album = element
                node = SynoNode(self.space, album, NodeType.FOLDER, self, self._model)
            elif row < self.nb_folders + self.nb_photos:
                photo = element
                node = SynoNode(self.space, photo, NodeType.FILE, self, self._model)
            else:
                assert False
            if row >= len(self._children):
                assert False
            self._children[row] = node

    def findChild(self, name: str) -> SynoNode:
        """return child node 'name' in column 0"""
        for node in self._children:
            if node._data[0] == name:
                return node

    def removeChild(self, nodeToRemove: SynoNode) -> bool:
        """remove specific child"""
        for node in self._children:
            if node == nodeToRemove:
                if nodeToRemove.node_type == NodeType.FILE:
                    self.nb_photos -= 1
                else:
                    self.nb_folders -= 1
                self._children.remove(nodeToRemove)
                del nodeToRemove
                return True
        return False

    def dataColumn(self, column: int = 0) -> Any:
        """Get data. Column is an offset in data"""
        if column >= 0 and column < len(self._data):
            return self._data[column]

    def hasChildren(self, parent: QModelIndex = QModelIndex()) -> bool:
        """returns true if parent has any children; otherwise returns false."""
        # log.info(f"{self._data[0]} hasChildren")
        return self.childCount() > 0

    def childCount(self) -> int:
        """Get child count (folders+photos)

        Return 1 if child count is unknow at this moment
        """
        if self.nb_folders == UNKNOWN_COUNT:
            # real count unknow at this moment, but return 1 for allows displaying expand/collapse indicator
            return 1
        return self.nb_folders + self.nb_photos

    def child(self, row: int) -> None:
        """return child node"""
        # log.info(f"child({row} -> {self._data}) nb_folders:{self.nb_folders}")
        self.updateRowCount()
        if row >= 0 and row < self.childCount():
            if self.node_type != NodeType.ROOT and (not self._children or self._children[row] is None):
                QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
                self._createChildNodes()
                QApplication.restoreOverrideCursor()
            return self._children[row]

    def parent(self) -> SynoNode:
        """return node parent"""
        return self._parent

    def row(self) -> int:
        """return node row"""
        if self._parent is None:
            return 0
        # (Warning list.index use __eq__)
        return self._parent._children.index(self)

    def addChild(self, child: SynoNode) -> None:
        """add child to node"""
        child._parent = self
        child.dirs_only = self.dirs_only
        self._children.append(child)

    def absoluteFilePath(self) -> str:
        """build full path"""
        parts = []
        node = self
        while True:
            parts.append(node._data[0])
            if node._parent is None:
                break
            node = node._parent

        parts.reverse()
        return str(PurePosixPath("").joinpath(*parts))

    def rawData(self):
        """get raw data : the json"""
        return self._raw_data

    def isShared(self) -> bool | None:
        """return True if node is in Shared Space, False in Personal Space, None for Album Space"""
        if self.space == SpaceType.ALBUM:
            # album can have photos in personal or shared space, no way to know
            shared = None
        elif self.space == SpaceType.SEARCH:
            shared = self.parent().parent().dataColumn(0) == "Shared"
        else:
            shared = self.space == SpaceType.SHARED
        return shared

    def passphrase(self):
        """return passphrase for node in album shared (whith me)"""
        if self.space != SpaceType.ALBUM:
            return None
        return self.parent()._raw_data["passphrase"]

    def photosNumber(self) -> int:
        """return photos number for node"""
        return self.nb_photos

    def foldersNumber(self) -> int:
        """return folders number for node"""
        return self.nb_folders

    def __str__(self):
        return f"{space_names[self.space]}, {nodetype_names[self.node_type]}, inode={self.inode} folders={self.nb_folders}, photos={self.nb_photos} : {self._data}"


class SynoModel(QAbstractItemModel):
    """
    Synology Photos Item Model
    """

    def __init__(
        self,
        dirs_only: bool = False,
        additional: list[str] = None,
        thumbnail: bool = False,
        search=False,
    ) -> None:
        """Init Syno model"""
        QAbstractItemModel.__init__(self)
        self.dirs_only = dirs_only
        self.thumbnail = thumbnail
        if thumbnail:
            additional.append("thumbnail")
        if additional is None:
            additional = []
        self.additional = list(set(additional))
        self._root = SynoNode(
            space=SpaceType.ROOT,
            node_type=NodeType.ROOT,
            data=space_names[SpaceType.ROOT],
            model=self,
        )
        self.search_mode = search
        self._root.dirs_only = dirs_only

        # default header names
        self.headerNames = ["Name", "Date", "Size"]
        if "exif" in self.additional:
            self.headerNames.extend(["Aperture", "Camera", "ExposureTime", "Focal", "ISO", "Lens"])
        if "resolution" in self.additional:
            self.headerNames.extend(["Resolution"])

        self.icons = {
            NodeType.SPACE: QtWidgets.QApplication.instance()
            .style()
            .standardIcon(QStyle.StandardPixmap.SP_DirHomeIcon),
            NodeType.FOLDER: QtGui.QIcon("./src/ico/application-sidebar.png"),
            NodeType.FILE: QtWidgets.QApplication.instance().style().standardIcon(QStyle.StandardPixmap.SP_FileIcon),
            NodeType.SEARCH: QtGui.QIcon("./src/ico/application-sidebar.png"),
        }
        self.thumbnail_size = QSize(200, 150)

        spaces = [SpaceType.PERSONAL, SpaceType.ALBUM, SpaceType.SHARED]
        if self.search_mode:
            spaces.append(SpaceType.SEARCH)
        for space in spaces:
            node = SynoNode(
                space=space,
                node_type=NodeType.SPACE,
                data=space_names[space],
                model=self,
            )
            self._root.addChild(node)
            self._root.nb_folders += 1

    def rowCount(self, index: QModelIndex) -> int:
        """override QAbstractItemModel.rowCount"""
        if index.isValid():
            return index.internalPointer().childCount()
        return self._root.childCount()

    def addChild(self, node, _parent):
        """add child to node"""
        if not _parent or not _parent.isValid():
            parent = self._root
        else:
            parent = _parent.internalPointer()
        parent.addChild(node)

    def pathToNode(self, path: str) -> SynoNode | None:
        """return node from path"""
        node = self._root
        path = PurePosixPath(path)
        for part in path.parts[1:]:
            node = self._find_in_childs(node, part)
            if node is None:
                log.warning(f"pathToNode({path}) : part not found")
                return None
        return node

    def pathIndex(self, path: str) -> QModelIndex:
        """return index from path"""
        path = PurePosixPath(path)
        node = self.pathToNode(path)
        if node is None:
            node = self._root
        return self.createIndex(node.row(), 0, node)

    def index(self, row: int, column: int, _parent=QModelIndex()) -> QModelIndex:
        """override QAbstractItemModel.index"""
        parent = self._root if not _parent.isValid() else _parent.internalPointer()
        if not QAbstractItemModel.hasIndex(self, row, column, _parent):
            return QtCore.QModelIndex()
        child = parent.child(row)
        if child:
            return self.createIndex(row, column, child)
        return QtCore.QModelIndex()

    def parent(self, index: QModelIndex) -> QModelIndex:
        """override QAbstractItemModel.parent"""
        if index.isValid():
            p = index.internalPointer().parent()
            if p:
                return self.createIndex(p.row(), 0, p)
        return QtCore.QModelIndex()

    def columnCount(self, index: QModelIndex) -> int:
        """override QAbstractItemModel.columnCount"""
        return len(self.headerNames)

    def flags(self, index: QModelIndex) -> Any:
        """overrride QAbstractItemModel.flags"""
        if not index.isValid():
            return super().flags(index)
        node = index.internalPointer()
        if node.node_type in [NodeType.ROOT, NodeType.SPACE]:
            return super().flags(index)
        # accept drag
        defaultFlags = super().flags(index)
        return Qt.ItemFlag.ItemIsDragEnabled | defaultFlags

    def data(self, index: QModelIndex, role) -> Any:
        """override QAbstractItemModel.data"""
        if not index.isValid():
            return None
        node = index.internalPointer()
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return node.dataColumn(index.column())
        elif role == QtCore.Qt.ItemDataRole.DecorationRole:
            if index.column() == 0:
                if self.thumbnail:
                    if node.node_type in [
                        NodeType.SPACE,
                        NodeType.ROOT,
                        NodeType.FOLDER,
                        NodeType.SEARCH,
                    ]:
                        image = QPixmap(os.path.abspath("./src/ico/icons8-folder-200.png"))
                        return image.scaled(
                            self.thumbnail_size.width(),
                            self.thumbnail_size.height(),
                            Qt.AspectRatioMode.KeepAspectRatio,
                        )
                    shared = node.isShared()
                    passphrase = node.passphrase()
                    syno_key = node._raw_data["additional"]["thumbnail"]["cache_key"]
                    if CACHE_PIXMAP:
                        image = QPixmap()
                        image.loadFromData(download_thumbnail(node.inode, syno_key, shared, passphrase))
                        return image.scaled(
                            self.thumbnail_size.width(),
                            self.thumbnail_size.height(),
                            Qt.AspectRatioMode.KeepAspectRatio,
                        )
                    else:
                        log.debug(f"model need thumb {node.inode}")
                        raw_image = download_thumbnail(node.inode, syno_key, shared, passphrase)
                        if not raw_image:
                            return QVariant()
                        pixmap = QPixmap()
                        image = QImage()
                        image.loadFromData(raw_image)
                        colorspace = image.colorSpace()
                        if not colorspace.description().startswith("sRGB"):
                            srgbColorSpace = QColorSpace(QColorSpace.NamedColorSpace.SRgb)
                            image.convertToColorSpace(srgbColorSpace)
                        pixmap.convertFromImage(image)
                        # Because we want uses setUniformItemSizes(True) in views (for performance) :
                        # insert thumbnail in black square
                        pixmap = pixmap.scaled(
                            self.thumbnail_size.width(),
                            self.thumbnail_size.height(),
                            Qt.AspectRatioMode.KeepAspectRatio,
                        )
                        pixmap_paint = QPixmap(self.thumbnail_size.width(), self.thumbnail_size.height())
                        pixmap_paint.fill(QColorConstants.Black)
                        painter = QtGui.QPainter(pixmap_paint)
                        rect = QRect(0, 0, pixmap.width(), pixmap.height())
                        rect.translate(
                            (self.thumbnail_size.width() - pixmap.width()) // 2,
                            (self.thumbnail_size.height() - pixmap.height()) // 2,
                        )
                        painter.drawPixmap(rect, pixmap)
                        return pixmap_paint

                if node.node_type in self.icons:
                    return self.icons[node.node_type]

        elif role == QtCore.Qt.ItemDataRole.TextAlignmentRole:
            if self.thumbnail:
                return QtCore.Qt.AlignmentFlag.AlignHCenter | QtCore.Qt.AlignmentFlag.AlignBottom
            if node.dataColumn(index.column()) == "Size":
                return QtCore.Qt.AlignmentFlag.AlignRight
            else:
                return QtCore.Qt.AlignmentFlag.AlignLeft

        return QVariant()

    def headerData(
        self,
        column: int,
        orientation: QtCore.Qt.Orientation,
        role: QtCore.Qt.ItemDataRole,
    ) -> Any:
        """override QAbstractItemModel.headerData"""
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            if orientation == QtCore.Qt.Orientation.Horizontal:
                return QtCore.QVariant(self.headerNames[column])
        elif role == QtCore.Qt.ItemDataRole.FontRole:
            return QFont("Times", 10, QFont.Weight.Bold, False)
        elif role == QtCore.Qt.ItemDataRole.TextAlignmentRole:
            return QtCore.Qt.AlignmentFlag.AlignLeft
        else:
            return QVariant()

    def mimeTypes(self):
        """overrride QAbstractItemModel.mimeTypes"""
        # TODO
        return ["text/uri-list", "text/x-uri"]

    def mimeData(self, indexes):
        """overrride QAbstractItemModel.mimeData"""
        mimeData = QMimeData()
        # TODO
        return mimeData

    def absoluteFilePath(self, index: QModelIndex) -> str:
        """return absolute path for index"""
        if not index.isValid():
            return QModelIndex()
        return index.internalPointer().absoluteFilePath()

    def _find_in_childs(self, node: SynoNode, part: str):
        """(internal) find part foldername in nodes child"""
        node.updateIfUnknownRowCount()
        for row in range(0, node.childCount()):
            child = node.child(row)
            if child._data[0] == part:
                return child
        return None

    def setRootPath(self, rootPath: str) -> QModelIndex:
        """change root path, return index"""
        index = self.pathIndex(rootPath)
        signal.directoryLoaded.emit(rootPath)
        return index

    def updateRowCount(self, index: QModelIndex) -> None:
        """force update of row count (childs) for index"""
        if not index.isValid():
            return
        node: SynoNode = index.internalPointer()
        count = node.childCount()
        if node.updateRowCount():
            newCount = node.childCount()
            log.info(f"updateRowCount {count} -> {newCount}")
            if newCount == 0:
                self.rowsRemoved.emit(index.parent(), 0, 0)
            else:
                self.rowsInserted.emit(index.parent(), 0, 0)

    def pathIndexes(self, path: str) -> list:
        """expand absolute path"""
        indexes = []
        path = PurePosixPath(path)
        node = self._root
        for part in path.parts[1:]:
            node = self._find_in_childs(node, part)
            if node is None:
                log.warning(f"pathIndexes({path}) : part not found")
                return []
            indexes.append(self.createIndex(node.row(), 0, node))
        return indexes

    def updateIfUnknownRowCount(self, index: QModelIndex) -> None:
        """update node child count if unknown"""
        if not index.isValid():
            return
        index.internalPointer().updateIfUnknownRowCount()

    def useThumbnail(self, thumbnail: bool = False) -> None:
        """use thumbnail as icon"""
        self.thumbnail = thumbnail

    def setThumbnailSize(self, size: QSize) -> None:
        """update node child count if unknown"""
        self.thumbnail_size = size

    def nodePointer(self, index: QModelIndex) -> SynoNode:
        """get node pointer"""
        return index.internalPointer()

    def nodeIndex(self, index: QModelIndex) -> QModelIndex:
        """get node index"""
        return index

    def _getOrCreateSearchChild(self, nodeParent: SynoNode, name: str):
        """get or create child in search space"""
        node = nodeParent.findChild(name)
        if node is None:
            log.info(f"beginInsertRows to {nodeParent._data[0]}, pos:{nodeParent.childCount()}")
            indexParent = self.createIndex(nodeParent.row(), 0, nodeParent)
            self.beginInsertRows(indexParent, nodeParent.childCount(), nodeParent.childCount())
            node = SynoNode(nodeParent.space, name, NodeType.SEARCH, nodeParent, nodeParent._model)
            nodeParent.addChild(node)
            if nodeParent.nb_folders == -1:
                nodeParent.nb_folders = 0
            nodeParent.nb_folders += 1
            self.endInsertRows()
        return node

    def search(self, section: str, search: str, team: bool) -> QModelIndex:
        """search tag or keyword: create path, populate nodes"""
        index = self.createSearch(section, search, team)
        node = index.internalPointer()
        # update count and populates photos
        node._createChildNodes()
        return index

    def createSearch(self, section: str, search: str, team: bool) -> QModelIndex:
        """create search node"""
        node = self.pathToNode("/Search")
        if node is None:
            log.error("No Search Space")
            return QModelIndex()
        if section.lower() not in ["tag", "keyword"]:
            log.error(f"Section {section} unsupported")
            return QModelIndex()
        if section.lower() == "tag":
            node = self._getOrCreateSearchChild(node, "Tag")
        elif section.lower() == "keyword":
            node = self._getOrCreateSearchChild(node, "Keyword")
        teamName = "Shared" if team else "Personal"
        node = self._getOrCreateSearchChild(node, teamName)
        node = self._getOrCreateSearchChild(node, search)
        node.searchContext = [section.lower(), search, team]
        return self.createIndex(node.row(), 0, node)

    def removeNode(self, index: QModelIndex) -> None:
        """remove node and children"""
        node: SynoNode = index.internalPointer()
        self.beginRemoveRows(index.parent(), node.row(), node.row())
        log.info(f"Remove node(s) {node.dataColumn(0)}")
        node.parent().removeChild(node)
        self.endRemoveRows()


class SynoSortFilterProxyModel(QSortFilterProxyModel):
    """
    Implements QSortFilterProxyModel for sorting views
    """

    def __init__(self, parent=None):
        super(SynoSortFilterProxyModel, self).__init__(parent=parent)

    def setRootPath(self, rootPath: str) -> QModelIndex:
        """change root path, return index"""
        return self.mapFromSource(self.sourceModel().setRootPath(rootPath))

    def pathIndex(self, path: str) -> QModelIndex:
        """return index from path"""
        return self.mapFromSource(self.sourceModel().pathIndex(path))

    def absoluteFilePath(self, index: QModelIndex) -> str:
        """return index from path"""
        if isinstance(index.model(), SynoSortFilterProxyModel):
            index = index.model().mapToSource(index)
        return self.sourceModel().absoluteFilePath(index)

    def search(self, section: str, search: str, team: bool) -> QModelIndex:
        """search for tag or keyword"""
        return self.mapFromSource(self.sourceModel().search(section, search, team))

    def createSearch(self, section: str, search: str, team: bool) -> QModelIndex:
        """create search node (without populates)"""
        return self.mapFromSource(self.sourceModel().createSearch(section, search, team))

    def removeNode(self, index: QModelIndex) -> None:
        """remove node from model"""
        self.sourceModel().removeNode(index.model().mapToSource(index))

    def nodePointer(self, index: QModelIndex) -> SynoNode:
        """get SynoNode from index"""
        if isinstance(index.model(), SynoSortFilterProxyModel):
            return index.model().mapToSource(index).internalPointer()
        return index.internalPointer()

    def nodeIndex(self, index: QModelIndex) -> QModelIndex:
        """get SynoNode index from index"""
        if isinstance(index.model(), SynoSortFilterProxyModel):
            return index.model().mapToSource(index)
        return index

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        """override QSortFilterProxyModel.lessThan"""
        column = left.column()
        # TODO : for future : change column index to headername
        if column in [2, 3, 5, 6, 7, 9]:
            leftNode: SynoNode = left.model().nodePointer(left)
            if leftNode.node_type != NodeType.FILE:
                return False
            leftData = leftNode.dataColumn(column)
            if not leftData:
                return False
            rightNode: SynoNode = right.model().nodePointer(right)
            rightData = rightNode.dataColumn(column)
            if not rightData:
                return True
            if column == 2:  # Size
                return leftNode.rawData()["filesize"] < rightNode.rawData()["filesize"]
            if column == 3:  # Aperture
                return float(leftData[1:]) < float(rightData[1:])
            if column == 5:  # Exposure
                try:
                    val = leftData[:-2].split("/")
                    lv = float(val[0]) if len(val) == 1 else int(val[0]) / int(val[1])
                    val = rightData[:-2].split("/")
                    rv = float(val[0]) if len(val) == 1 else int(val[0]) / int(val[1])
                    return lv < rv
                except ValueError:
                    return False
            if column == 6:  # Focal
                return float(leftData[:-3]) < float(rightData[:-3])
            if column == 7:  # ISO
                return float(leftData) < float(rightData)
            if column == 9:  # ISO
                lw, lh = leftData.split(" x ")
                rw, rh = rightData.split(" x ")
                return int(lw) * int(lh) < int(rw) * int(rh)

        return super().lessThan(left, right)
