"""
Explorer for Synology Photos

Based on https://github.com/adesfontaines/pyqtexplorer

"""
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QTableView,
    QHeaderView,
    QListView,
    QFrame,
    QAbstractScrollArea,
)
from PyQt6.QtGui import (
    QFontMetrics,
)
from PyQt6.QtCore import (
    Qt,
    QSize,
    QItemSelectionModel,
)


class PhotosIconView(QListView):
    """
    main explorer in icon mode
    """

    def __init__(self, model):
        super(PhotosIconView, self).__init__()
        self.curModel = model
        self.setModel(self.curModel)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setWordWrap(True)
        grid_size = 250
        cell_size = 240
        thumb_size = QSize(
            cell_size, cell_size - int(QFontMetrics(self.font()).height() * 5)
        )

        self.setGridSize(QSize(grid_size, grid_size))
        self.curModel.setThumbnailSize(thumb_size)
        self.setUniformItemSizes(True)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setAttribute(Qt.WidgetAttribute.WA_StyleSheet, True)
        self.setStyleSheet("color: #b0b0b0; background-color: #101010;")

        self.setDragEnabled(True)
        self.setAcceptDrops(False)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)

        self.curModel.useThumbnail(True)

        selectionModel = QItemSelectionModel(self.curModel)
        self.setSelectionModel(selectionModel)


class PhotosDetailsView(QTableView):
    """
    main explorer in details mode
    """

    def __init__(self, model):
        super(PhotosDetailsView, self).__init__()

        model.useThumbnail(False)
        self.setModel(model)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

        self.verticalHeader().hide()
        self.setShowGrid(False)
        self.horizontalHeader().setSectionsMovable(True)
        self.horizontalHeader().setHighlightSections(True)
        self.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)
        self.horizontalHeader().resizeSection(0, 200)
        self.horizontalHeader().resizeSection(1, 350)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

        self.setFrameStyle(QFrame.Shape.NoFrame)
        self.setSortingEnabled(True)
        self.setEditTriggers(QAbstractItemView.EditTrigger.EditKeyPressed)