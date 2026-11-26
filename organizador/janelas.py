"""Dialogs: the review list after Preview (untick tracks to leave them alone) and the run history for Undo."""
import os
import time

from PySide6.QtCore import QObject, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from .capas import preview, same
from .i18n import t
from .pipeline import compatible_versions
from .biblioteca import PLAYLIST_FILE, playlist_description, saved_map
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


class TrackPlayer(QObject):
    def __init__(self, dialog, status):
        super().__init__(dialog)
        self.status = status
        self.player = None
        dialog.finished.connect(self.stop)

    def play(self, path):
        from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer
        self.stop()
        self.status.show()
        if QMediaDevices.defaultAudioOutput().isNull():
            self.status.setText(t("plan.no_audio_device"))
            return
        if self.player is None:
            self.player = QMediaPlayer(self)
            self.output = QAudioOutput(self)
            self.player.setAudioOutput(self.output)
            self.player.errorOccurred.connect(lambda _, msg: self.status.setText(t("plan.audio_error", msg=msg)))
            self.player.mediaStatusChanged.connect(lambda state: self.status.hide()
                                                   if state == QMediaPlayer.EndOfMedia else None)
        self.status.setText(t("plan.playing", name=os.path.basename(path)))
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.play()

    def stop(self):
        if self.player is not None:
            self.player.stop()
            self.player.setSource(QUrl())
        self.status.hide()


class PlanDialog(QDialog):
    """Preview rows (kind, path, detail). exec() == Accepted: organize now, leaving self.skipped() alone."""

    def __init__(self, plan, root, parent=None, *, details=None, quarantine_only=False):
        super().__init__(parent)
        self.details = details or {}
        self.root = root
        self.playlists = saved_map(root, PLAYLIST_FILE) if any(row[0] == "dup" for row in plan) else {}
        self.quarantine_only = quarantine_only
        self.keeper_choices = {}
        self._duplicate_rows = {i: detail for i, (kind, _, detail) in enumerate(plan) if kind == "dup"}
        self._original_keepers = self._duplicate_rows.copy()
        self._all_duplicates = bool(plan) and len(self._duplicate_rows) == len(plan)
        lay = _dialog(self, t("plan.title"), (1100, 680))
        lay.addWidget(QLabel(t("plan.dup_hint" if self._all_duplicates else "plan.hint"), objectName="hint", wordWrap=True))
        self.search = QLineEdit(placeholderText=t("plan.search"))
        self.search.setAccessibleName(t("plan.search"))
        filters = QHBoxLayout()
        filters.addWidget(self.search, 1)
        if self._duplicate_rows:
            xml = _button(t("dj.import_xml"))
            xml.setAutoDefault(False)
            xml.clicked.connect(self._import_xml)
            filters.addWidget(xml)
        self.only_duplicates = None
        if self._duplicate_rows and not self._all_duplicates:
            self.only_duplicates = QCheckBox(t("plan.only_duplicates"))
            self.only_duplicates.toggled.connect(self._filter)
            filters.addWidget(self.only_duplicates)
        lay.addLayout(filters)

        rel = lambda p: os.path.relpath(p, root) if p and os.path.isabs(p) else p
        self.table = QTableWidget(len(plan), 3)
        self._set_headers(self._all_duplicates)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setWordWrap(False)
        self.paths = []
        self.rows_of = {}  # ordinary actions stay linked per track; duplicate approval is independent
        self.table.setUpdatesEnabled(False)
        for i, (kind, path, detail) in enumerate(plan):
            action = QTableWidgetItem(t("plan.kind." + kind))
            action.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
            action.setCheckState(Qt.Checked)
            track = QTableWidgetItem(os.path.basename(path) if kind == "dup" else rel(path))
            track.setToolTip(path)
            result = os.path.basename(detail) if kind == "dup" else rel(detail)
            if kind == "dup" and not self._all_duplicates:
                result = t("plan.keeps", x=result)
            to = QTableWidgetItem(result)
            to.setToolTip(detail if kind == "dup" else result)
            for col, item in enumerate((action, track, to)):
                self.table.setItem(i, col, item)
            self.paths.append(path)
            if kind == "dup":
                self._set_pair(i, path, detail)
            else:
                self.rows_of.setdefault(path, []).append(i)
        self.table.setUpdatesEnabled(True)
        head = self.table.horizontalHeader()
        self.table.resizeColumnToContents(0)
        self.table.setColumnWidth(0, self.table.columnWidth(0) + 32)  # the tick box is not counted in the text width
        head.setSectionResizeMode(0, QHeaderView.Interactive)
        head.setSectionResizeMode(1, QHeaderView.Stretch)
        head.setSectionResizeMode(2, QHeaderView.Stretch)
        lay.addWidget(self.table, 1)

        self.pair = QLabel(objectName="hint", wordWrap=True, textFormat=Qt.PlainText,
                           textInteractionFlags=Qt.TextSelectableByMouse)
        self.pair.hide()
        lay.addWidget(self.pair)
        controls = QHBoxLayout()
        self.play_remove = _button(t("plan.play_quarantine"))
        self.play_keep = _button(t("plan.play_keep"))
        self.stop = _button(t("plan.stop"))
        self.swap = _button(t("plan.swap"))
        for button in (self.play_remove, self.play_keep, self.stop, self.swap):
            button.setAutoDefault(False)
            controls.addWidget(button)
            button.hide()
        controls.addStretch()
        lay.addLayout(controls)
        self.play_remove.clicked.connect(lambda: self._play(self.paths[self.table.currentRow()]))
        self.play_keep.clicked.connect(lambda: self._play(self._duplicate_rows[self.table.currentRow()]))
        self.stop.clicked.connect(self._stop_audio)
        self.swap.clicked.connect(self._swap_keeper)
        self.audio_status = QLabel(objectName="hint", wordWrap=True, textFormat=Qt.PlainText)
        self.audio_status.hide()
        lay.addWidget(self.audio_status)
        self.audio = TrackPlayer(self, self.audio_status)
        self.table.currentCellChanged.connect(lambda row, *_: self._show_pair(row))
        if self._all_duplicates:
            self.table.setCurrentCell(0, 1)

        self.count = QLabel(objectName="hint")
        row = QHBoxLayout()
        all_, none = _button(t("plan.all"), "ghost"), _button(t("plan.none"), "ghost")
        all_.setAutoDefault(False)
        none.setAutoDefault(False)
        all_.clicked.connect(lambda: self._tick_visible(Qt.Checked))
        none.clicked.connect(lambda: self._tick_visible(Qt.Unchecked))
        close, run = _button(t("btn.close")), _button(t("plan.run"), "primary")
        close.setAutoDefault(False)
        run.setDefault(not self._all_duplicates)
        close.clicked.connect(self.reject)
        run.clicked.connect(self.accept)
        run.setEnabled(bool(plan))
        self.run_btn = run
        for w in (all_, none, self.count):
            row.addWidget(w)
        row.addStretch()
        row.addWidget(close)
        row.addWidget(run)
        run.setVisible(not quarantine_only)
        self.quarantine_btn = _button(t("plan.quarantine_only"), "primary")
        self.quarantine_btn.clicked.connect(self._accept_duplicates)
        self.quarantine_btn.setVisible(bool(self._duplicate_rows))
        self.quarantine_btn.setDefault(self._all_duplicates)
        row.addWidget(self.quarantine_btn)
        lay.addLayout(row)

        self._timer = QTimer(self, singleShot=True, interval=200)  # filter after typing stops: 16k rows
        self._timer.timeout.connect(self._filter)
        self.search.textChanged.connect(lambda _: self._timer.start())
        self.table.itemChanged.connect(self._changed)
        self._update_count()

    def _changed(self, item):
        if item.column() != 0:
            return
        self.table.blockSignals(True)
        if item.row() not in self._duplicate_rows:
            for i in self.rows_of[self.paths[item.row()]]:
                self.table.item(i, 0).setCheckState(item.checkState())
        self.table.blockSignals(False)
        self._update_count()

    def _set_headers(self, duplicates):
        self.table.setHorizontalHeaderLabels([t("plan.col_action"),
                                              t("plan.col_quarantine" if duplicates else "plan.col_track"),
                                              t("plan.col_keep" if duplicates else "plan.col_to")])

    def _set_pair(self, row, path, keep):
        self.paths[row], self._duplicate_rows[row] = path, keep
        left, right = self.details.get(path), self.details.get(keep)
        exact = bool(left and right and left.identical(right))
        eligible = not (left and right) or (left.removable and compatible_versions(
            left.version, left.duration, right.version, right.duration))
        action = self.table.item(row, 0)
        action.setText(t("plan.exact" if exact else "plan.possible") if eligible else t("plan.incompatible"))
        action.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | (Qt.ItemIsUserCheckable if eligible else Qt.NoItemFlags))
        action.setCheckState(Qt.Checked if exact and eligible else Qt.Unchecked)
        for col, filename in ((1, path), (2, keep)):
            item = self.table.item(row, col)
            name = os.path.basename(filename)
            item.setText(t("plan.keeps", x=name) if col == 2 and not self._all_duplicates else name)
            item.setToolTip(filename)

    def _swap_keeper(self):
        row = self.table.currentRow()
        original = self._original_keepers[row]
        chosen, previous = self.paths[row], self._duplicate_rows[row]
        self.keeper_choices[original] = chosen
        selected = self.table.item(row, 0).checkState()
        self.table.blockSignals(True)
        for i, group in self._original_keepers.items():
            if group == original:
                self._set_pair(i, previous if i == row else self.paths[i], chosen)
                action = self.table.item(i, 0)
                action.setCheckState(selected if i == row and action.flags() & Qt.ItemIsUserCheckable else Qt.Unchecked)
        self.table.blockSignals(False)
        self._show_pair(row)
        self._filter()
        self._update_count()

    def _show_pair(self, row):
        self._stop_audio()
        visible = row in self._duplicate_rows
        for w in (self.pair, self.play_remove, self.play_keep, self.stop, self.swap):
            w.setVisible(visible)
        if not visible:
            return
        path, keep = self.paths[row], self._duplicate_rows[row]
        left, right = self.details.get(path), self.details.get(keep)
        reason = t("plan.reason_exact") if left and right and left.identical(right) else t("plan.reason_tags")
        if not self.table.item(row, 0).flags() & Qt.ItemIsUserCheckable:
            reason = t("plan.reason_incompatible")

        def describe(p, track):
            if not track:
                return p
            minutes, seconds = divmod(round(track.duration), 60)
            duration = f"{minutes}:{seconds:02}" if track.duration else t("plan.unknown_duration")
            description = " · ".join(filter(None, (track.version, duration, p)))
            if self.playlists:
                description += "\n    " + playlist_description(self.playlists, p)
            return description

        self.pair.setText(reason + "\n" + t("plan.dup_paths", quarantine=describe(path, left), keep=describe(keep, right)))
        self.swap.setEnabled(bool(right and right.removable))
        self.swap.setToolTip(t("plan.swap_hint" if self.swap.isEnabled() else "plan.swap_scope"))

    def _import_xml(self):
        from .dj_ui import import_xml_dialog
        result = import_xml_dialog(self, self.root)
        if result is not None:
            self.playlists = result
            self._show_pair(self.table.currentRow())

    @property
    def player(self):
        return self.audio.player

    def _play(self, path):
        self.audio.play(path)

    def _stop_audio(self):
        self.audio.stop()

    def _accept_duplicates(self):
        self.quarantine_only = True
        self.accept()

    def reviewed_duplicates(self):
        return {self.paths[i]: keep for i, keep in self._duplicate_rows.items()
                if self.table.item(i, 0).checkState() == Qt.Checked}

    def _filter(self):
        duplicates = self.only_duplicates is not None and self.only_duplicates.isChecked()
        self._set_headers(self._all_duplicates or duplicates)
        words = self.search.text().casefold().split()
        for i in range(self.table.rowCount()):
            is_duplicate = i in self._duplicate_rows
            text = " ".join(self.table.item(i, c).text() for c in range(3))
            if is_duplicate:
                text += " " + self.paths[i] + " " + self._duplicate_rows[i]
            text = text.casefold()
            self.table.setRowHidden(i, (duplicates and not is_duplicate) or not all(w in text for w in words))
        row = self.table.currentRow()
        if row < 0 or self.table.isRowHidden(row):
            first_visible = next((i for i in range(self.table.rowCount()) if not self.table.isRowHidden(i)), -1)
            self.table.setCurrentCell(first_visible, 1)
            self._show_pair(first_visible)

    def _tick_visible(self, state):
        self.table.blockSignals(True)
        for i in range(self.table.rowCount()):
            if not self.table.isRowHidden(i):
                rows = [i] if i in self._duplicate_rows else self.rows_of[self.paths[i]]
                for j in rows:
                    item = self.table.item(j, 0)
                    if item.flags() & Qt.ItemIsUserCheckable:
                        item.setCheckState(state)
        self.table.blockSignals(False)
        self._update_count()

    def _update_count(self):
        """Counted in tracks, not rows."""
        checked = {path for i, path in enumerate(self.paths) if self.table.item(i, 0).checkState() == Qt.Checked}
        self.count.setText(t("plan.count", on=len(checked), n=len(set(self.paths))))
        self.run_btn.setEnabled(bool(checked))
        self.quarantine_btn.setEnabled(bool(self.reviewed_duplicates()))

    def skipped(self):
        """Tracks to skip in ordinary steps. Duplicate approvals are carried separately."""
        selected = set(self.reviewed_duplicates())
        for path, rows in self.rows_of.items():
            if self.table.item(rows[0], 0).checkState() == Qt.Checked:
                selected.add(path)
            else:
                selected.discard(path)
        return sorted(set(self.paths) - selected)


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
        close.setAutoDefault(False)
        undo.setDefault(True)
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
