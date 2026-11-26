"""Radar DJ tab: public headlines, with matching performed against local music tags."""
import os
import threading
import time
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget)

from . import biblioteca, config, radar
from .dj_ui import SetDialog, button, cell, table
from .i18n import t
from .pipeline import too_broad


class RadarPage(QWidget):
    downloaded = Signal(object)
    indexed = Signal(object)

    def __init__(self, get_opts, parent=None):
        super().__init__(parent)
        self.get_opts = get_opts
        self.cache = radar.cached_news()
        self.failed = []
        self.downloading = False
        self.indexing = False
        self.library_key = None
        self.generation = 0
        self.tracks, self.index = {}, {}
        self.last_attempt = self.last_index = 0
        self.index_error = ""
        self.matches = []
        layout = QVBoxLayout(self)
        filters = QHBoxLayout()
        self.category = QComboBox()
        for key in ("all", "music", "portugal", "tech"):
            self.category.addItem(t("dj.cat."+key), key)
        filters.addWidget(self.category)
        self.city = QLineEdit(placeholderText=t("dj.city"))
        filters.addWidget(self.city)
        self.mine = QCheckBox(t("dj.my_artists"))
        filters.addWidget(self.mine)
        self.refresh_btn = button(filters, "dj.refresh", lambda: self.refresh(True))
        layout.addLayout(filters)
        follows = QHBoxLayout()
        self.follow = QLineEdit(config.get("radar_follow", ""), placeholderText=t("dj.follow"))
        follows.addWidget(self.follow)
        self.follow_only = QCheckBox(t("dj.follow_only"))
        follows.addWidget(self.follow_only)
        layout.addLayout(follows)
        self.table = table(["dj.date", "dj.source", "dj.news", "dj.artist"], 2)
        self.table.setColumnWidth(0, 145)
        layout.addWidget(self.table)
        self.headline = QLabel(wordWrap=True, textFormat=Qt.PlainText)
        layout.addWidget(self.headline)
        row = QHBoxLayout()
        self.open = button(row, "dj.open_news", self.open_article)
        self.local = button(row, "dj.my_tracks", self.open_tracks)
        row.addStretch()
        layout.addLayout(row)
        self.status = QLabel(wordWrap=True, objectName="hint", textFormat=Qt.PlainText)
        layout.addWidget(self.status)
        self.downloaded.connect(self.news_ready)
        self.indexed.connect(self.index_ready)
        self.table.currentCellChanged.connect(self.selected)
        self.table.itemDoubleClicked.connect(self.open_article)
        for signal in (self.category.currentIndexChanged, self.city.textChanged, self.mine.toggled,
                       self.follow.textChanged, self.follow_only.toggled):
            signal.connect(self.render)
        self.follow.editingFinished.connect(lambda: config.put("radar_follow", self.follow.text()))
        self.timer = QTimer(self, interval=radar.INTERVAL * 1000)
        self.timer.timeout.connect(lambda: self.refresh(True))
        self.render()

    def showEvent(self, event):
        super().showEvent(event)
        if not self.timer.isActive():
            self.timer.start()
        QTimer.singleShot(0, self.refresh)

    def invalidate_library(self, *_):
        self.generation += 1
        self.library_key = None
        self.tracks, self.index = {}, {}
        self.last_index = 0
        if self.isVisible():
            self.render()
            QTimer.singleShot(0, self.refresh)

    def background(self, callback, signal):
        def run():
            try:
                value = callback()
            except Exception as e:
                value = e
            try:
                signal.emit(value)
            except RuntimeError:
                pass  # closed window or a language change rebuilt this tab
        threading.Thread(target=run, daemon=True).start()

    def refresh(self, force=False):
        now = time.monotonic()
        if not self.downloading and (force or not self.last_attempt or now - self.last_attempt >= radar.INTERVAL - 2):
            self.downloading = True
            self.last_attempt = now
            if self.timer.isActive():
                self.timer.start()
            self.refresh_btn.setEnabled(False)
            self.background(radar.refresh_news, self.downloaded)
        opts = self.get_opts()
        key = (opts.root, tuple(opts.protected))
        if key != self.library_key:
            self.tracks, self.index = {}, {}
            self.library_key, self.last_index, self.index_error = key, 0, ""
        if (not self.indexing and os.path.isdir(opts.root) and not too_broad(opts.root)
                and (force or not self.last_index or now - self.last_index >= radar.INTERVAL - 2)):
            previous = self.tracks
            self.indexing = True
            self.last_index = now
            generation = self.generation
            def lookup():
                tracks = biblioteca.catalogue(opts, threading.Event(), previous=previous, background_index=True)[0]
                return key, generation, tracks, radar.artist_index(tracks.values())
            self.background(lookup, self.indexed)
        self.render()

    def news_ready(self, value):
        self.downloading = False
        self.refresh_btn.setEnabled(True)
        if isinstance(value, Exception):
            self.failed = [str(value)]
        else:
            self.cache, self.failed = value
        self.render()

    def index_ready(self, result):
        self.indexing = False
        if isinstance(result, Exception):
            self.index_error = str(result)
        elif result[:2] == (self.library_key, self.generation):
            _, _, self.tracks, self.index = result
            self.index_error = ""
        else:
            self.last_index = 0
            self.refresh()
        self.render()

    def render(self):
        current = self.table.currentRow()
        url = self.matches[current][0]["url"] if 0 <= current < len(self.matches) else ""
        by_url = {}
        for batch in self.cache.values():
            for a in batch["articles"]:
                by_url[a["url"]] = a
        follows = {radar.words(v) for v in self.follow.text().split(",") if v.strip()}
        category = self.category.currentData()
        city = radar.words(self.city.text())
        self.city.setVisible(category == "portugal")
        lengths = {len(k.split()) for k in self.index}
        follow_lengths = {len(k.split()) for k in follows}
        self.matches = []
        for a in sorted(by_url.values(), key=lambda v: v["date"], reverse=True):
            if category == "portugal":
                if not radar.in_portugal(a["text"], city):
                    continue
            elif category != "all" and category not in a["groups"]:
                continue
            names = radar.mentions(a["text"], self.index, lengths)
            if self.mine.isChecked() and not names:
                continue
            if self.follow_only.isChecked() and not radar.mentions(a["text"], follows, follow_lengths):
                continue
            paths = sorted({p for name in names for p in self.index[name]})
            self.matches.append((a, paths))
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.matches))
        selected = 0
        for i, (a, paths) in enumerate(self.matches):
            if a["url"] == url:
                selected = i
            date = datetime.fromtimestamp(a["date"]).strftime("%d/%m/%Y %H:%M") if a["date"] else "—"
            artists = ", ".join(sorted({artist for p in paths
                                        for artist in (self.tracks[p].artists or (self.tracks[p].artist,))}))
            for col, v in enumerate((date, a["source"], a["title"], artists)):
                cell(self.table, i, col, v)
        self.table.blockSignals(False)
        self.table.setCurrentCell(selected if self.matches else -1, 2)
        self.selected()
        info = []
        if self.downloading:
            info.append(t("dj.fetching"))
        if self.cache:
            latest = max(v["updated"] for v in self.cache.values())
            info.append(t("dj.updated", date=datetime.fromtimestamp(latest).strftime("%d/%m %H:%M")))
        if self.failed:
            info.append(t("dj.feed_failed", sources=", ".join(self.failed)))
        if self.indexing:
            info.append(t("dj.indexing"))
        if self.index_error:
            info.append(self.index_error)
        self.status.setText(" · ".join(info))

    def selected(self, *_):
        i = self.table.currentRow()
        entry = self.matches[i] if 0 <= i < len(self.matches) else None
        self.headline.setText(entry[0]["title"] if entry else t("dj.no_news"))
        self.open.setEnabled(bool(entry))
        self.local.setEnabled(bool(entry and entry[1]))

    def open_article(self, *_):
        i = self.table.currentRow()
        if i >= 0:
            QDesktopServices.openUrl(QUrl(self.matches[i][0]["url"]))

    def open_tracks(self):
        opts = self.get_opts()
        if (opts.root, tuple(opts.protected)) != self.library_key:
            self.refresh(True)
            return
        i = self.table.currentRow()
        if i >= 0:
            dialog = SetDialog(opts, [self.tracks[p] for p in self.matches[i][1]], self)
            dialog.exec()
            dialog.deleteLater()
