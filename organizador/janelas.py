"""Dialogs: the review list after Preview (untick tracks to leave them alone) and the run history for Undo."""
import os
import time

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from .capas import preview, same
from .i18n import t
from .theme import C


def _dialog(d, title, size):
    d.setWindowTitle(title)
    d.resize(*size)
    d.setStyleSheet(f"QDialog {{ background: {C['card']}; }}")
    lay = QVBoxLayout(d)
    lay.setContentsMargins(24, 20, 24, 20)
    lay.setSpacing(12)
    return lay


def _button(text, kind=None):
    return QPushButton(text, objectName=kind or "", cursor=Qt.PointingHandCursor)


class PlanDialog(QDialog):
    """Preview rows (kind, path, detail). exec() == Accepted: organize now, leaving self.skipped() alone."""

    def __init__(self, plan, root, parent=None):
        super().__init__(parent)
        lay = _dialog(self, t("plan.title"), (1100, 680))
        lay.addWidget(QLabel(t("plan.hint"), objectName="hint", wordWrap=True))
        self.search = QLineEdit(placeholderText=t("plan.search"))
        self.search.setAccessibleName(t("plan.search"))
        lay.addWidget(self.search)

        rel = lambda p: os.path.relpath(p, root) if p and os.path.isabs(p) else p
        self.table = QTableWidget(len(plan), 3)
        self.table.setHorizontalHeaderLabels([t("plan.col_action"), t("plan.col_track"), t("plan.col_to")])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setWordWrap(False)
        self.paths = []
        self.table.setUpdatesEnabled(False)
        for i, (kind, path, detail) in enumerate(plan):
            action = QTableWidgetItem(t("plan.kind." + kind))
            action.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
            action.setCheckState(Qt.Checked)
            track = QTableWidgetItem(rel(path))
            track.setToolTip(path)
            result = t("plan.keeps", x=rel(detail)) if kind == "dup" else rel(detail)
            to = QTableWidgetItem(result)
            to.setToolTip(result)
            for col, item in enumerate((action, track, to)):
                self.table.setItem(i, col, item)
            self.paths.append(path)
        self.table.setUpdatesEnabled(True)
        head = self.table.horizontalHeader()
        self.table.resizeColumnToContents(0)
        self.table.setColumnWidth(0, self.table.columnWidth(0) + 32)  # the tick box is not counted in the text width
        head.setSectionResizeMode(0, QHeaderView.Interactive)
        head.setSectionResizeMode(1, QHeaderView.Stretch)
        head.setSectionResizeMode(2, QHeaderView.Stretch)
        lay.addWidget(self.table, 1)

        self.count = QLabel(objectName="hint")
        row = QHBoxLayout()
        all_, none = _button(t("plan.all"), "ghost"), _button(t("plan.none"), "ghost")
        all_.clicked.connect(lambda: self._tick_visible(Qt.Checked))
        none.clicked.connect(lambda: self._tick_visible(Qt.Unchecked))
        close, run = _button(t("btn.close")), _button(t("plan.run"), "primary")
        close.clicked.connect(self.reject)
        run.clicked.connect(self.accept)
        run.setEnabled(bool(plan))
        self.run_btn = run
        for w in (all_, none, self.count):
            row.addWidget(w)
        row.addStretch()
        row.addWidget(close)
        row.addWidget(run)
        lay.addLayout(row)

        self._timer = QTimer(self, singleShot=True, interval=200)  # filter after typing stops: 16k rows
        self._timer.timeout.connect(self._filter)
        self.search.textChanged.connect(lambda _: self._timer.start())
        self.rows_of = {}  # path -> its rows (a track can have several actions): ticked/unticked together
        for i, p in enumerate(self.paths):
            self.rows_of.setdefault(p, []).append(i)
        self.table.itemChanged.connect(self._changed)
        self._update_count()

    def _changed(self, item):
        if item.column() != 0:
            return
        self.table.blockSignals(True)
        for i in self.rows_of[self.paths[item.row()]]:
            self.table.item(i, 0).setCheckState(item.checkState())
        self.table.blockSignals(False)
        self._update_count()

    def _filter(self):
        words = self.search.text().casefold().split()
        for i in range(self.table.rowCount()):
            text = " ".join(self.table.item(i, c).text() for c in range(3)).casefold()
            self.table.setRowHidden(i, not all(w in text for w in words))

    def _tick_visible(self, state):
        self.table.blockSignals(True)
        for i in range(self.table.rowCount()):
            if not self.table.isRowHidden(i):
                for j in self.rows_of[self.paths[i]]:  # the track's other rows too, even if filtered out
                    self.table.item(j, 0).setCheckState(state)
        self.table.blockSignals(False)
        self._update_count()

    def _update_count(self):
        """Counted in tracks, not rows."""
        off = set(self.skipped())
        on = len(self.rows_of) - len(off)
        self.count.setText(t("plan.count", on=on, n=len(self.rows_of)))
        if hasattr(self, "run_btn"):
            self.run_btn.setEnabled(on > 0)

    def skipped(self):
        """Files with any row unticked: left exactly as they are in the run."""
        return sorted({self.paths[i] for i in range(self.table.rowCount())
                       if self.table.item(i, 0).checkState() != Qt.Checked})


def run_date(run_id):
    try:
        return time.strftime("%d/%m/%Y %H:%M", time.strptime(run_id[:15], "%Y%m%d-%H%M%S"))
    except ValueError:
        return run_id


def run_summary(kinds):
    parts = [t("hist." + k, n=kinds[k]) for k in ("mover", "quarentena", "tags", "capa", "capa_fora", "extraido") if kinds.get(k)]
    return ", ".join(parts) or t("hist.nothing")


class HistoryDialog(QDialog):
    """Runs newest first; exec() == Accepted: undo back to self.chosen() (index in the list, 0 = newest)."""

    def __init__(self, runs, parent=None):
        super().__init__(parent)
        lay = _dialog(self, t("history.title"), (640, 460))
        lay.addWidget(QLabel(t("history.hint"), objectName="hint", wordWrap=True))
        self.list = QListWidget()
        self.list.setAccessibleName(t("history.title"))
        for run_id, kinds in runs:
            QListWidgetItem(f"{run_date(run_id)}  —  {run_summary(kinds)}", self.list)
        if not runs:
            QListWidgetItem(t("history.empty"), self.list).setFlags(Qt.NoItemFlags)
        else:
            self.list.setCurrentRow(0)
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.addStretch()
        close, undo = _button(t("btn.close")), _button(t("history.undo"), "primary")
        close.clicked.connect(self.reject)
        undo.clicked.connect(self.accept)
        undo.setEnabled(bool(runs))
        self.list.itemDoubleClicked.connect(lambda _: runs and self.accept())
        row.addWidget(close)
        row.addWidget(undo)
        lay.addLayout(row)

    def chosen(self):
        return self.list.currentRow()


class CoversDialog(QDialog):
    """Covers used by many artists; ticked = not a real cover. exec() == Accepted: marked() is the new list."""

    def __init__(self, found, marked, parent=None):
        super().__init__(parent)
        lay = _dialog(self, t("covers.title"), (1000, 700))
        lay.addWidget(QLabel(t("covers.hint"), objectName="hint", wordWrap=True))
        self.list = QListWidget()
        self.list.setAccessibleName(t("covers.title"))
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setIconSize(QSize(140, 140))
        self.list.setGridSize(QSize(170, 200))
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setMovement(QListWidget.Static)
        self.found = list(found)
        # marked before and no longer repeated here: shown too, so it can be unticked
        self.found += [(m, preview(m), 0, 0) for m in marked if not any(same(f, m) for f, *_ in found)]
        for f, small, n, artists in self.found:
            pm = QPixmap.fromImage(small).scaled(140, 140, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            it = QListWidgetItem(QIcon(pm), t("covers.item", n=n, artists=artists) if n else t("covers.marked"), self.list)
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if any(same(f, m) for m in marked) else Qt.Unchecked)
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.addStretch()
        close, save = _button(t("btn.close")), _button(t("covers.save"), "primary")
        close.clicked.connect(self.reject)
        save.clicked.connect(self.accept)
        row.addWidget(close)
        row.addWidget(save)
        lay.addLayout(row)

    def marked(self):
        return [f for i, (f, *_) in enumerate(self.found) if self.list.item(i).checkState() == Qt.Checked]
