"""Desktop tools for reviewing a music library, restoring tracks and exporting sets."""
import os
import threading
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout)

from . import biblioteca as lib, pipeline as pl
from .i18n import t
from .janelas import PlanDialog, TrackPlayer, _dialog, run_date


class Job(QThread):
    def __init__(self, fn):
        super().__init__()
        self.fn, self.cancel = fn, threading.Event()
        self.value = self.error = None

    def run(self):
        try:
            self.value = self.fn(self.cancel)
        except pl.Cancelled:
            pass
        except Exception as e:
            self.error = str(e)


class Working(QDialog):
    def reject(self):
        if self.cancellable:
            self.job.cancel.set()
            self.button.setEnabled(False)


def perform(parent, title, fn, *, cancellable=True):
    """Run disk and XML work away from the GUI. A cancelled copy finishes cleanup before the dialog closes."""
    dialog = Working(parent)
    dialog.cancellable = cancellable
    dialog.setWindowTitle(title)
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel(title + "…"))
    dialog.job = Job(fn)
    dialog.button = QPushButton(t("btn.cancel"))
    dialog.button.clicked.connect(dialog.reject)
    layout.addWidget(dialog.button)
    dialog.button.setVisible(cancellable)
    dialog.job.finished.connect(dialog.accept)
    QTimer.singleShot(0, dialog.job.start)
    dialog.exec()
    dialog.job.wait()
    value, error = dialog.job.value, dialog.job.error
    dialog.deleteLater()
    if error:
        QMessageBox.warning(parent, title, error)
    return value


def import_xml_dialog(parent, root):
    filename, _ = QFileDialog.getOpenFileName(parent, t("dj.import_xml"), "", "rekordbox XML (*.xml)")
    if filename:
        return perform(parent, t("dj.import_xml"), lambda c: lib.import_playlists(root, filename, c))


def button(row, key, fn):
    b = QPushButton(t(key), cursor=Qt.PointingHandCursor, autoDefault=False)
    b.clicked.connect(fn)
    row.addWidget(b)
    return b


def table(headers, stretch):
    view = QTableWidget(0, len(headers))
    view.setHorizontalHeaderLabels([t(k) for k in headers])
    view.setEditTriggers(QAbstractItemView.NoEditTriggers)
    view.setSelectionBehavior(QAbstractItemView.SelectRows)
    view.setSelectionMode(QAbstractItemView.SingleSelection)
    view.verticalHeader().hide()
    view.horizontalHeader().setSectionResizeMode(stretch, QHeaderView.Stretch)
    return view


def cell(view, row, col, value):
    item = QTableWidgetItem(str(value))
    item.setToolTip(str(value))
    view.setItem(row, col, item)
    return item


def duration(seconds):
    m, s = divmod(round(seconds), 60)
    return f"{m // 60}:{m % 60:02}:{s:02}" if m >= 60 else f"{m}:{s:02}"


def search_filter(view, records, query):
    terms = query.casefold().split()
    first = -1
    for i, text in enumerate(records):
        visible = all(term in text.casefold() for term in terms)
        view.setRowHidden(i, not visible)
        if visible and first == -1:
            first = i
    if view.currentRow() < 0 or view.isRowHidden(view.currentRow()):
        view.setCurrentCell(first, 0)


class SetDialog(QDialog):
    def __init__(self, opts, tracks, parent=None):
        super().__init__(parent)
        self.opts, self.tracks = opts, list(tracks)
        self.playlists = lib.saved_map(opts.root, lib.PLAYLIST_FILE)
        self.selected = {}  # insertion order = running order on the USB
        layout = _dialog(self, t("dj.set"), (1040, 650))
        filters = QHBoxLayout()
        self.search = QLineEdit(placeholderText=t("dj.search"))
        filters.addWidget(self.search, 1)
        self.genre = QComboBox()
        self.genre.addItem(t("dj.all_genres"), "")
        for genre in sorted({tr.genre for tr in self.tracks if tr.genre}, key=str.casefold):
            self.genre.addItem(genre, genre)
        filters.addWidget(self.genre)
        self.min_bpm, self.max_bpm = QSpinBox(), QSpinBox()
        for spin, label in ((self.min_bpm, "dj.min"), (self.max_bpm, "dj.max")):
            filters.addWidget(QLabel(t(label)))
            spin.setRange(0, 999)
            spin.setSpecialValueText("—")
            filters.addWidget(spin)
        layout.addLayout(filters)
        self.table = table(["dj.order", "plan.col_track", "dj.artist", "dj.genre", "dj.bpm", "dj.length"], 1)
        self.table.setRowCount(len(self.tracks))
        for i, tr in enumerate(self.tracks):
            check = cell(self.table, i, 0, "")
            if tr.exportable:
                check.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
                check.setCheckState(Qt.Unchecked)
            else:
                check.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                check.setText(t("dj.unreadable"))
                check.setToolTip(t("dj.unreadable_export", name=Path(tr.path).name))
            cell(self.table, i, 1, tr.title).setToolTip(tr.path)
            for col, value in enumerate((tr.artist, tr.genre, f"{tr.bpm:g}" if tr.bpm else "—", duration(tr.duration)), 2):
                cell(self.table, i, col, value)
        self.table.setColumnWidth(0, 65)
        self.table.setColumnWidth(2, 165)
        layout.addWidget(self.table)
        self.total = QLabel()
        layout.addWidget(self.total)
        self.location = QLabel(wordWrap=True, textFormat=Qt.PlainText, textInteractionFlags=Qt.TextSelectableByMouse)
        layout.addWidget(self.location)
        self.status = QLabel(wordWrap=True, textFormat=Qt.PlainText)
        layout.addWidget(self.status)
        self.audio = TrackPlayer(self, self.status)
        self.status.hide()
        actions = QHBoxLayout()
        button(actions, "dj.play", self.play)
        button(actions, "plan.stop", self.audio.stop)
        button(actions, "dj.measure", self.measure)
        actions.addStretch()
        self.send = button(actions, "dj.export", self.export)
        button(actions, "btn.close", self.reject)
        layout.addLayout(actions)
        self.table.itemChanged.connect(self.ticked)
        self.table.currentCellChanged.connect(self.track_changed)
        for signal in (self.search.textChanged, self.genre.currentIndexChanged, self.min_bpm.valueChanged,
                       self.max_bpm.valueChanged):
            signal.connect(self.filter)
        self.update_total()

    def track_changed(self, *_):
        self.audio.stop()
        i = self.table.currentRow()
        text = ""
        if i >= 0 and not self.table.isRowHidden(i):
            text = self.tracks[i].path
            if self.playlists:
                text += "\n" + lib.playlist_description(self.playlists, text)
        self.location.setText(text)

    def filter(self):
        terms = self.search.text().casefold().split()
        low, high, genre = self.min_bpm.value(), self.max_bpm.value(), self.genre.currentData()
        for i, tr in enumerate(self.tracks):
            text = (tr.path + " " + tr.artist + " " + tr.title).casefold()
            match = (not genre or tr.genre == genre) and all(v in text for v in terms)
            if low or high:
                match = match and tr.bpm is not None and low <= tr.bpm <= (high or 999)
            self.table.setRowHidden(i, not match)
        i = self.table.currentRow()
        if i < 0 or self.table.isRowHidden(i):
            self.table.setCurrentCell(next((r for r in range(len(self.tracks)) if not self.table.isRowHidden(r)), -1), 1)
            self.track_changed()

    def ticked(self, item):
        if item.column() != 0 or not self.tracks[item.row()].exportable:
            return
        i = item.row()
        if item.checkState() == Qt.Checked:
            self.selected[i] = True
        else:
            self.selected.pop(i, None)
        self.table.blockSignals(True)
        item.setText("")
        for n, row in enumerate(self.selected, 1):
            self.table.item(row, 0).setText(str(n))
        self.table.blockSignals(False)
        self.update_total()

    def update_total(self):
        tracks = [self.tracks[i] for i in self.selected]
        self.total.setText(t("dj.total", n=len(tracks), time=duration(sum(tr.duration for tr in tracks)),
                             mb=f"{sum(tr.stamp[0] for tr in tracks)/1048576:.1f}"))
        self.send.setEnabled(bool(tracks))

    def play(self):
        i = self.table.currentRow()
        if i >= 0 and not self.table.isRowHidden(i):
            self.audio.play(self.tracks[i].path)

    def measure(self):
        paths = [tr for tr in self.tracks if tr.bpm is None and "report_unreadable" not in tr.problems]
        def measure_missing(cancel):
            org = pl.Organizer(self.opts, cancel=cancel)
            result = {}
            with pl.library_lock(org.root):
                for tr in paths:
                    if cancel.is_set():
                        raise pl.Cancelled()
                    if lib.library_file(org, tr.path) and lib.stamp(tr.path) == tr.stamp:
                        result[tr.path] = org._measure_bpm(tr.path)
                pl._write_json(org._bpm_cache_path, {"version": pl.BPM_CACHE_VERSION, "items": org._bpm_cache})
            return result
        result = perform(self, t("dj.measure"), measure_missing)
        if result is not None:
            for i, tr in enumerate(self.tracks):
                if result.get(tr.path):
                    self.tracks[i] = replace(tr, bpm=result[tr.path])
                    self.table.item(i, 4).setText(f"{result[tr.path]:g}")
            self.filter()
            self.status.setText(t("dj.measured", n=sum(bool(value) for value in result.values())))
            self.status.show()

    def export(self):
        dest = QFileDialog.getExistingDirectory(self, t("dj.pick_usb"))
        if not dest:
            return
        name, ok = QInputDialog.getText(self, t("dj.export"), t("dj.set_name"), text="DJ Set")
        if ok:
            tracks = [self.tracks[i] for i in self.selected]
            path = perform(self, t("dj.export"), lambda cancel: lib.export_set(self.opts, tracks, dest, cancel, name))
            if path:
                QMessageBox.information(self, t("dj.export"), t("dj.export_done", path=path))


class ReviewDialog(QDialog):
    def __init__(self, opts, catalog, parent=None):
        super().__init__(parent)
        self.opts = opts
        layout = _dialog(self, t("dj.review"), (1000, 630))
        filters = QHBoxLayout()
        self.search = QLineEdit(placeholderText=t("dj.search"))
        self.later = QCheckBox(t("dj.show_deferred"))
        filters.addWidget(self.search, 1)
        filters.addWidget(self.later)
        layout.addLayout(filters)
        self.table = table(["dj.issue", "plan.col_track", "dj.artist", "dj.folder"], 1)
        self.table.setColumnWidth(0, 230)
        self.table.setColumnWidth(3, 220)
        layout.addWidget(self.table)
        self.detail = QLabel(wordWrap=True, textFormat=Qt.PlainText, textInteractionFlags=Qt.TextSelectableByMouse)
        layout.addWidget(self.detail)
        self.status = QLabel(wordWrap=True, textFormat=Qt.PlainText)
        self.audio = TrackPlayer(self, self.status)
        self.status.hide()
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        self.play_btn = button(actions, "dj.play", self.play)
        button(actions, "plan.stop", self.audio.stop)
        self.next_btn = button(actions, "dj.next", self.next_track)
        self.edit_btn = button(actions, "dj.edit", self.edit)
        self.compare_btn = button(actions, "dj.compare", self.compare)
        self.defer_btn = button(actions, "dj.defer", self.defer)
        actions.addStretch()
        button(actions, "btn.close", self.reject)
        layout.addLayout(actions)
        self.table.currentCellChanged.connect(self.changed)
        self.search.textChanged.connect(self.filter)
        self.later.toggled.connect(self.filter)
        self.load(catalog)

    def load(self, catalog):
        self.tracks, self.dups, self.details, self.snapshot = catalog
        saved = lib.saved_map(self.opts.root, lib.DEFERRED_FILE)
        self.issues = []
        for path, tr in self.tracks.items():
            for kind, reason in (("dup", t("plan.possible")) , ("tags", ", ".join(t("rep."+k) for k in tr.problems))):
                if (kind == "dup" and path not in self.dups) or not reason:
                    continue
                key = kind + "|" + os.path.normcase(path)
                signature = list(tr.stamp)
                if kind == "dup":
                    keep = self.dups[path]
                    signature += [keep, *self.tracks[keep].stamp]
                    if self.details[path].identical(self.details[keep]):
                        reason = t("plan.exact")
                recorded = saved.get(key)
                if kind == "dup" and isinstance(recorded, list) and len(recorded) == 5 and isinstance(recorded[2], str):
                    deferred = (recorded[:2] == signature[:2] and recorded[3:] == signature[3:]
                                and os.path.normcase(recorded[2]) == os.path.normcase(keep))
                else:
                    deferred = recorded == signature
                self.issues.append((tr, kind, reason, key, signature, deferred))
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.issues))
        for i, (tr, _, reason, *_) in enumerate(self.issues):
            for col, value in enumerate((reason, Path(tr.path).name, tr.artist, os.path.dirname(tr.path))):
                cell(self.table, i, col, value)
        self.table.blockSignals(False)
        self.filter()

    def filter(self):
        terms = self.search.text().casefold().split()
        first = -1
        for i, (tr, _, reason, _, _, deferred) in enumerate(self.issues):
            text = (tr.path + " " + tr.artist + " " + tr.title + " " + reason).casefold()
            show = deferred == self.later.isChecked() and all(term in text for term in terms)
            self.table.setRowHidden(i, not show)
            if show and first < 0:
                first = i
        row = self.table.currentRow()
        if row < 0 or self.table.isRowHidden(row):
            self.table.setCurrentCell(first, 1)
        self.changed()

    def current(self):
        i = self.table.currentRow()
        return self.issues[i] if 0 <= i < len(self.issues) and not self.table.isRowHidden(i) else None

    def changed(self, *_):
        self.audio.stop()
        entry = self.current()
        self.detail.setText(entry[0].path if entry else t("dj.queue_empty"))
        for b in (self.play_btn, self.defer_btn):
            b.setEnabled(bool(entry))
        self.next_btn.setEnabled(self._next_row() is not None)
        self.edit_btn.setEnabled(bool(entry and "report_unreadable" not in entry[0].problems))
        self.compare_btn.setEnabled(bool(entry and entry[1] == "dup" and not entry[5]))
        self.defer_btn.setText(t("dj.resume" if self.later.isChecked() else "dj.defer"))

    def play(self):
        if self.current():
            self.audio.play(self.current()[0].path)

    def _next_row(self):
        entry = self.current()
        if entry:
            return next((i for i in range(self.table.currentRow() + 1, len(self.issues))
                         if not self.table.isRowHidden(i) and self.issues[i][0].path != entry[0].path), None)

    def next_track(self):
        i = self._next_row()
        if i is not None:
            self.table.setCurrentCell(i, 1)
            self.play()

    def defer(self):
        track, kind, _, key, signature, deferred = self.current()
        try:
            lib.defer_issue(self.opts.root, key, signature, not deferred)
        except (OSError, pl.Busy) as e:
            QMessageBox.warning(self, t("dj.review"), str(e))
            return
        if kind == "dup" and deferred:
            self.reload()  # resuming the pair can change the preferred copy for the group
            return
        if kind == "dup":
            for path in (track.path, self.dups[track.path]):
                self.details[path] = replace(self.details[path], removable=False)
        self.load((self.tracks, self.dups, self.details, self.snapshot))

    def reload(self):
        catalog = perform(self, t("dj.review"), lambda c: lib.catalogue(self.opts, c, duplicates=True))
        if catalog is not None:
            self.load(catalog)
        else:
            self.reject()

    def edit(self):
        self.audio.stop()
        tr = self.current()[0]
        d = QDialog(self)
        d.setWindowTitle(t("dj.edit"))
        form = QFormLayout(d)
        form.addRow(QLabel(Path(tr.path).name, textFormat=Qt.PlainText))
        fields = [QLineEdit(v) for v in (tr.raw_artist, tr.raw_title, tr.raw_genre)]
        for key, field in zip(("dj.artist", "dj.title", "dj.genre"), fields):
            form.addRow(t(key), field)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(d.accept)
        buttons.rejected.connect(d.reject)
        form.addRow(buttons)
        if d.exec() == QDialog.Accepted:
            values = [f.text().strip() for f in fields]
            perform(self, t("dj.edit"), lambda _: lib.edit_metadata(self.opts, tr, *values), cancellable=False)
            self.reload()

    def compare(self):
        self.audio.stop()
        path = self.current()[0].path
        keep = self.dups[path]
        rows = [("dup", track.path, keep) for track, kind, _, _, _, deferred in self.issues
                if kind == "dup" and not deferred and self.dups[track.path] == keep]
        if not any(p == path for _, p, _ in rows):
            return
        d = PlanDialog(rows, self.opts.root, self, details=self.details, quarantine_only=True)
        d.table.setCurrentCell(d.paths.index(path), 1)
        result = d.exec()
        d.deleteLater()
        if result != QDialog.Accepted:
            return
        reviewed, choices = d.reviewed_duplicates(), d.keeper_choices
        if not reviewed or QMessageBox.question(self, t("dj.compare"), t("plan.quarantine_confirm", n=len(reviewed))) != QMessageBox.Yes:
            return
        def apply(cancel):
            org = pl.Organizer(self.opts, cancel=cancel, reviewed_duplicates=reviewed, keeper_choices=choices)
            return org.run(self.snapshot, duplicates_only=True)
        result = perform(self, t("dj.compare"), apply)
        if result is not None:
            report, errors = result
            QMessageBox.information(self, t("dj.compare"), t("dj.quarantined", n=report["dups_trashed"]) + "\n" + "\n".join(errors))
        self.reload()


class TrackHistoryDialog(QDialog):
    def __init__(self, opts, entries, parent=None):
        super().__init__(parent)
        self.opts = opts
        layout = _dialog(self, t("dj.history"), (1100, 620))
        self.search = QLineEdit(placeholderText=t("dj.history_search"))
        layout.addWidget(self.search)
        self.table = table(["dj.date", "dj.why", "dj.from", "dj.to", "dj.status"], 3)
        self.table.setColumnWidth(0, 145)
        self.table.setColumnWidth(1, 145)
        self.table.setColumnWidth(2, 300)
        layout.addWidget(self.table)
        self.detail = QLabel(wordWrap=True, textFormat=Qt.PlainText, textInteractionFlags=Qt.TextSelectableByMouse)
        layout.addWidget(self.detail)
        row = QHBoxLayout()
        self.restore = button(row, "dj.restore", self.restore_one)
        row.addStretch()
        button(row, "btn.close", self.reject)
        layout.addLayout(row)
        self.search.textChanged.connect(self.filter)
        self.table.currentCellChanged.connect(self.changed)
        self.load(entries)

    def load(self, entries):
        self.entries = entries
        self.texts = []
        self.table.blockSignals(True)
        self.table.setRowCount(len(entries))
        for i, e in enumerate(entries):
            values = (run_date(e.run), t("dj.reason."+e.reason), e.source, e.destination, t("dj.state."+e.status))
            self.texts.append(" ".join((*values, *e.aliases)))
            for col, value in enumerate(values):
                shown = value
                if col in (2, 3):
                    try:
                        shown = os.path.relpath(value, self.opts.root)
                    except ValueError:
                        pass  # a prior run used a different drive alias for the same library
                item = cell(self.table, i, col, shown)
                item.setToolTip(value)
        self.table.blockSignals(False)
        self.filter()

    def filter(self):
        search_filter(self.table, self.texts, self.search.text())
        self.changed()

    def changed(self, *_):
        i = self.table.currentRow()
        e = self.entries[i] if 0 <= i < len(self.entries) and not self.table.isRowHidden(i) else None
        self.detail.setText(f"{e.source}\n→ {e.destination}" if e else t("dj.no_history"))
        self.restore.setEnabled(bool(e and e.restorable))

    def restore_one(self):
        e = self.entries[self.table.currentRow()]
        if QMessageBox.question(self, t("dj.restore"), t("dj.restore_confirm", path=e.source)) == QMessageBox.Yes:
            perform(self, t("dj.restore"), lambda _: pl.restore_track(self.opts, e), cancellable=False)
            entries = perform(self, t("dj.history"), lambda _: pl.track_history(self.opts))
            if entries is not None:
                self.load(entries)
