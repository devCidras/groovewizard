"""Window: pick the music folder, paste API keys, choose steps, Organize / Preview / Undo with per-step progress."""
import os
import sys
import threading
import traceback
from collections import Counter
from dataclasses import asdict, replace

from PySide6.QtCore import QObject, QPointF, QPropertyAnimation, QRectF, Qt, QThread, QTimer, Signal, Property
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (QApplication, QBoxLayout, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow, QMenu,
                               QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
                               QStackedWidget, QTabWidget, QVBoxLayout, QWidget)

from . import __version__, config, termos
from .capas import SiteCovers
from .i18n import LANGS, lang, report_label, set_lang, system_lang, t
from .pipeline import (APP_DIR, MARKED_COVERS, Busy, Cancelled, Options, Organizer, library_lock, library_report, list_runs,
                       has_completed_full_run, protectable, purge_quarantine, too_broad, undo_until)
from .theme import C, QSS, RecordSleeve

# (Options field, pipeline step ids shown on that row). "_organize" always runs.
STEPS = [("extract", ["extract"]), ("_organize", ["organize"]), ("dedupe", ["dedupe_scan", "dedupe_remove"]),
         ("online", ["online"]), ("bpm_folders", ["bpm"]), ("write_tags", ["tags"]), ("covers", ["covers"])]
EXTRA_OPTIONS = ["only_new", "merge_versions", "clean_sites", "families", "rename_packs", "site_names",
                 "site_covers", "musicbrainz", "delete_archives"]
OLD_SCOPE = ("organize_all", "dedupe_all", "online_all", "bpm_all", "write_tags_all",
             "clean_sites_all", "covers_all", "site_covers_all")
ICON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recursos", "groovewizard-icone.png")  # symbol without tile: reads bigger
LOGO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recursos", "groovewizard-simbolo.png")  # no tile: sits on the dark header


def opt_key(field):
    return "opt." + field.lstrip("_")


class Toggle(QCheckBox):
    """Switch; keyboard accessible (Space toggles), visible focus ring."""

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setChecked(checked)
        self.setFixedSize(36, 22)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(160)
        self.toggled.connect(self._animate)

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def _animate(self, on):
        self._anim.stop()
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def _get_pos(self):
        return self._pos

    def _set_pos(self, v):
        self._pos = v
        self.update()

    knob = Property(float, _get_pos, _set_pos)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(1, 1, self.width() - 2, self.height() - 2)
        off, on = QColor(C["switch_off"]), QColor(C["accent"])
        mix = lambda a, b: int(a + (b - a) * self._pos)
        track = QColor(mix(off.red(), on.red()), mix(off.green(), on.green()), mix(off.blue(), on.blue()))
        if not self.isEnabled():
            track.setAlpha(90)
        p.setPen(QPen(QColor(C["fg"]), 2) if self.hasFocus() else Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 6
        x = r.left() + 3 + (r.width() - d - 6) * self._pos
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(C["on_accent"] if self.isChecked() else C["fg"]))
        p.drawEllipse(QRectF(x, r.top() + 3, d, d))


def card(title=None, subtitle=None):
    f = QFrame(objectName="card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(20, 18, 20, 18)
    lay.setSpacing(12)
    if title:
        lay.addWidget(QLabel(title, objectName="cardTitle", wordWrap=True))
    if subtitle:
        lay.addWidget(QLabel(subtitle, objectName="hint", wordWrap=True, openExternalLinks=True))
    return f, lay


def tab_page(tabs, title):
    page = QWidget()
    lay = QVBoxLayout(page)
    lay.setContentsMargins(0, 12, 4, 2)
    lay.setSpacing(10)
    scroll = QScrollArea(widgetResizable=True, frameShape=QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setWidget(page)
    tabs.addTab(scroll, t(title))
    return lay


class StatusIcon(QWidget):
    """Step state: grey ring (waiting), spinning arc (running), green check (done), red cross (error)."""
    SIZE = 18

    def __init__(self):
        super().__init__()
        self.setFixedSize(self.SIZE, self.SIZE)
        self.state, self.angle = "waiting", 0
        self.timer = QTimer(self, interval=16)  # ~60 fps while running, stopped otherwise
        self.timer.timeout.connect(self._spin)

    def _spin(self):
        self.angle = (self.angle - 8) % 360
        self.update()

    def set(self, state):
        self.state = state
        if state == "running":
            self.timer.start()
        else:
            self.timer.stop()
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(2, 2, self.SIZE - 4, self.SIZE - 4)
        if self.state in ("waiting", "off", "cancelled"):
            p.setPen(QPen(QColor(C["border"] if self.state == "off" else C["switch_off"]), 2))
            p.drawEllipse(r)
        elif self.state == "running":
            p.setPen(QPen(QColor(C["muted"]), 2))
            p.drawEllipse(r)
            pen = QPen(QColor(C["accent"]), 2.5)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawArc(r, self.angle * 16, 100 * 16)  # a 100 degree arc going round
        else:
            done = self.state == "done"
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(C["accent"] if done else C["danger"]))
            p.drawEllipse(r)
            pen = QPen(QColor(C["on_accent"] if done else "#FFFFFF"), 2)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            c = self.SIZE / 2
            if done:  # check mark
                p.drawLine(QPointF(c - 4, c), QPointF(c - 1, c + 3))
                p.drawLine(QPointF(c - 1, c + 3), QPointF(c + 4, c - 3))
            else:  # cross
                p.drawLine(QPointF(c - 3, c - 3), QPointF(c + 3, c + 3))
                p.drawLine(QPointF(c + 3, c - 3), QPointF(c - 3, c + 3))


class StepRow(QWidget):
    """Status icon + title + live counter."""

    def __init__(self, title):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 4)
        self.dot = StatusIcon()
        self.title = QLabel(title)
        self.state = QLabel(objectName="hint")
        self.current = "waiting"
        lay.addWidget(self.dot)
        lay.addSpacing(8)
        lay.addWidget(self.title, 1)
        lay.addWidget(self.state)
        self.set("waiting")

    def set(self, state, text=None):
        self.current = state
        self.dot.set(state)
        self.title.setStyleSheet(f"color:{C['fg'] if state != 'off' else C['fg_muted']};"
                                 f"font-weight:{600 if state == 'running' else 400};")
        self.state.setText(text if text is not None else t("state." + state))


class Worker(QObject):
    progress = Signal(str, int, int, str)
    finished = Signal(str, object, object)  # kind, report, errors
    failed = Signal(str, bool)  # message, operation actually cancelled
    ask = Signal(object, object, str)  # worker, [(path, new name)], "new"/"sites" -> answered via worker.answer()

    def __init__(self, kind, opts, keys, cancel, extra=None):
        super().__init__()
        self.kind, self.opts, self.keys, self.cancel = kind, opts, keys, cancel
        self.extra = extra or {}  # undo: {"until": run_id}; run: {"skip": [paths unticked in the review list]}
        self.repeated = []
        self.dup_details = {}
        self.plan, self.snapshot, self.report_path = [], None, None  # results the window reads after a preview / report
        self._answer, self._answered = False, threading.Event()

    def answer(self, yes):
        self._answer = yes
        self._answered.set()

    def ask_rename(self, items, kind="new"):
        """Runs in the worker thread: waits for the user's answer in the window (Cancel also stops waiting)."""
        self._answered.clear()
        self.ask.emit(self, items, kind)
        while not self._answered.wait(0.2):
            if self.cancel.is_set():
                raise Cancelled()
        if self.cancel.is_set():  # Cancel inside the question: stop, don't take it as "No"
            raise Cancelled()
        return self._answer

    def run(self):
        emit = lambda step, i, n, msg="": self.progress.emit(step, i, n, msg)
        try:
            if self.kind == "undo":
                rep, errs = undo_until(self.opts.root, self.extra["until"], emit, self.cancel, self.opts.protected,
                                       self.extra.get("newest"))
            elif self.kind == "purge":
                rep, errs = {"purged": purge_quarantine(self.opts.root)}, []  # takes the library lock
            elif self.kind == "covers_scan":
                org = Organizer(self.opts, self.keys, emit, self.cancel)
                with library_lock(self.opts.root):  # no run changing files while it reads them
                    self.repeated = org.repeated_covers()
                rep, errs = Counter(), []
            elif self.kind == "report":
                org = Organizer(self.opts, self.keys, emit, self.cancel)
                path = os.path.join(org.data, f"relatorio-{org.run_id}.csv")  # unique: never overwrites an older one
                with library_lock(self.opts.root):  # no run moving files while it reads them
                    rep, errs = library_report(org, path), []
                self.report_path = path
            else:
                org = Organizer(self.opts, self.keys, emit, self.cancel, ask_rename=self.ask_rename,
                                skip=self.extra.get("skip"), reviewed_duplicates=self.extra.get("reviewed_duplicates"),
                                keeper_choices=self.extra.get("keeper_choices"))
                rep, errs = (org.preview(), []) if self.kind == "preview" else org.run(
                    self.extra.get("snapshot"), duplicates_only=self.kind == "duplicates")
                self.plan, self.snapshot, self.dup_details = org.plan, org.snapshot, org.dup_details
            self.finished.emit(self.kind, rep, errs)
        except Cancelled:
            message = {"run": "msg.cancelled", "undo": "msg.undo_cancelled"}.get(self.kind, "status.cancelled")
            self.failed.emit(t(message), True)
        except (Busy, ValueError) as e:  # expected: another window running, bad folder
            self.failed.emit(str(e), False)
        except Exception:
            self.failed.emit(log_crash(traceback.format_exc()), False)


class Window(QMainWindow):
    _key_result = Signal(str, int, str, str)  # service, request number, result, detail
    _update_found = Signal(object)  # dict from atualizacoes.check(), or None
    _update_progress = Signal(int)
    _update_ready = Signal(str)  # downloaded installer path, or "" on failure

    def __init__(self):
        super().__init__()
        self.setWindowTitle(t("app.title"))
        self.resize(1100, 760)
        self.setMinimumSize(760, 520)
        self.thread = None
        self.worker = None
        self.cancel = threading.Event()
        self.current_row = None
        self._updating = False
        self._plan, self._plan_opts, self._plan_snapshot = [], None, None
        self._dup_details = {}
        self._last_rep = {}
        self._key_ui = {}
        self._next_key_check = 0
        self._key_controls = []
        self._key_result.connect(self._show_key_result)  # once: results come back to the UI thread
        self._update_info = None
        self._status_key = "status.ready"
        self._update_found.connect(self._show_update)
        self._update_progress.connect(lambda pct: self.upd_btn.setText(t("upd.downloading", pct=pct)))
        self._update_ready.connect(self._run_installer)
        self.build()
        QShortcut(QKeySequence("F1"), self, self.show_help)

    def build(self):
        show_update = self._update_info is not None and not self.banner.isHidden()
        old_log = self.log.toPlainText() if hasattr(self, "log") else ""
        old_states = [r.current for _, r in self.step_rows] if old_log else []
        tab = self.tabs.currentIndex() if hasattr(self, "tabs") else 0
        shutdown = self.shutdown_toggle.isChecked() if hasattr(self, "shutdown_toggle") else False
        self._key_controls = []
        opts, keys = config.load()
        self._saved_options = asdict(opts)
        self._saved_keys = {key: keys.get(key, "") for key in ("discogs_token", "lastfm_api_key")}
        self._checking = {}
        self._columns = []
        self.folder_lang = opts.folder_lang
        root = QWidget(objectName="root")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(24, 16, 24, 16)
        outer.setSpacing(12)

        head = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(QPixmap(LOGO).scaled(36, 36, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        head.addWidget(logo)
        head.addWidget(QLabel(t("app.title"), objectName="title"))
        head.addWidget(QLabel(f"v{__version__}", objectName="badge"), 0, Qt.AlignVCenter)
        head.addStretch()
        help_btn = QPushButton(t("btn.help"), cursor=Qt.PointingHandCursor)
        menu = QMenu(help_btn)
        menu.addAction(t("btn.help_tip"), self.show_help)
        menu.addAction(t("terms.menu"), self.show_terms)
        menu.addAction(t("btn.about"), self.show_about)
        help_btn.setMenu(menu)
        head.addWidget(help_btn)
        self.lang_combo = QComboBox(toolTip=t("lang.tip"))
        self.lang_combo.setAccessibleName(t("lang.tip"))
        for code, name in LANGS.items():
            self.lang_combo.addItem(name, code)
        self.lang_combo.setCurrentIndex(list(LANGS).index(lang()))
        self.lang_combo.currentIndexChanged.connect(self.change_lang)
        head.addWidget(self.lang_combo)
        outer.addLayout(head)

        self.banner = QFrame(objectName="banner")
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(16, 10, 12, 10)
        self.upd_label = QLabel()
        self.upd_btn = QPushButton(t("upd.install"), objectName="primary", cursor=Qt.PointingHandCursor)
        self.upd_btn.clicked.connect(self._start_update)
        later = QPushButton(t("upd.later"), objectName="ghost", cursor=Qt.PointingHandCursor)
        later.clicked.connect(self.banner.hide)
        bl.addWidget(self.upd_label, 1)
        bl.addWidget(later)
        bl.addWidget(self.upd_btn)
        self.banner.hide()
        outer.addWidget(self.banner)
        if show_update:  # preserve a dismissed banner when rebuilding in another language
            self._show_update(self._update_info)

        outer.addWidget(self._library_card(opts, shutdown))
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)
        self._activity_page()
        self._options_page(opts, shutdown)
        self._sources_page(keys)
        self._tools_page(opts)
        self._dj_page()
        from .radar_ui import RadarPage
        self.radar = RadarPage(lambda: self.current()[0], self.tabs)
        self.tabs.addTab(self.radar, "Radar DJ")
        self.folder.textChanged.connect(self.radar.invalidate_library)
        self.protected.model().rowsInserted.connect(self.radar.invalidate_library)
        self.protected.model().rowsRemoved.connect(self.radar.invalidate_library)
        self.tabs.currentChanged.connect(self._refresh_overview)
        self._refresh_overview(0)
        self.tabs.setCurrentIndex(tab)
        self.folder.textChanged.connect(self._update_new_only_availability)
        self._update_new_only_availability()
        self.setCentralWidget(root)
        self._fit_columns()
        self.setWindowTitle(t("app.title"))
        if old_log:
            self.log.setPlainText(old_log)
            for (_, row), state in zip(self.step_rows, old_states):
                row.set(state)
            self.status.setText(t(self._status_key))
            if self._status_key in ("status.done", "status.preview_done"):
                self.bar.setRange(0, 1)
                self.bar.setValue(1)
        self._update_plan_button()
        if self._last_rep:
            self.show_stats(self._last_rep)

    def _library_card(self, opts, shutdown):
        hero = QFrame(objectName="library")
        layout = QHBoxLayout(hero)
        layout.setContentsMargins(22, 14, 16, 14)
        form = QVBoxLayout()
        form.setSpacing(8)
        title = QLabel(t("folder.dialog"), objectName="libraryTitle")
        form.addWidget(title)
        row = QHBoxLayout()
        self.folder = QLineEdit(opts.root, placeholderText=t("folder.placeholder"))
        self.folder.setAccessibleName(t("folder.dialog"))
        pick = self.pick_btn = QPushButton(t("folder.pick"), cursor=Qt.PointingHandCursor)
        pick.clicked.connect(self.pick_folder)
        row.addWidget(self.folder, 1)
        row.addWidget(pick)
        title.setBuddy(self.folder)
        form.addLayout(row)
        form.addWidget(QLabel(t("library.hint"), objectName="hint", wordWrap=True))
        actions = QHBoxLayout()
        self.btn_preview = QPushButton(t("btn.preview"), objectName="primary", cursor=Qt.PointingHandCursor,
                                       toolTip=t("btn.preview_tip"))
        self.btn_preview.clicked.connect(lambda: self.start("preview"))
        self.btn_run = QPushButton(t("btn.run"), cursor=Qt.PointingHandCursor)
        self.btn_run.clicked.connect(self.organize)
        self.btn_plan = QPushButton(objectName="review", cursor=Qt.PointingHandCursor, toolTip=t("btn.plan_tip"))
        self.btn_plan.clicked.connect(self.show_plan)
        self.btn_plan.hide()
        self.btn_cancel = QPushButton(t("btn.cancel"), objectName="danger", cursor=Qt.PointingHandCursor)
        self.btn_cancel.clicked.connect(self.do_cancel)
        self.btn_cancel.hide()
        for button in (self.btn_preview, self.btn_plan, self.btn_run, self.btn_cancel):
            actions.addWidget(button)
        actions.addStretch()
        self.shutdown_note = QLabel(t("shut.toggle"), objectName="armed")
        self.shutdown_note.setVisible(shutdown)
        actions.addWidget(self.shutdown_note)
        form.addLayout(actions)
        layout.addLayout(form, 1)
        self.sleeve = RecordSleeve()
        layout.addWidget(self.sleeve)
        return hero

    def _page_columns(self, page):
        columns = QHBoxLayout()
        columns.setSpacing(14)
        page.addLayout(columns, 1)
        self._columns.append(columns)
        return columns

    def _fit_columns(self):
        available = self.width() - 76  # outer margins, page padding and vertical scrollbar
        self.sleeve.setVisible(available >= 820)
        for columns in self._columns:
            needed = sum(columns.itemAt(i).minimumSize().width() for i in range(columns.count()))
            direction = QBoxLayout.LeftToRight if needed + columns.spacing() <= available else QBoxLayout.TopToBottom
            columns.setDirection(direction)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "sleeve"):
            self._fit_columns()

    def _activity_page(self):
        page = tab_page(self.tabs, "tab.activity")
        columns = self._page_columns(page)
        progress, lay = card(t("card.progress"))
        columns.addWidget(progress, 1)
        self.status = QLabel(t("status.ready"), objectName="hint", wordWrap=True)
        self.status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.status)
        self.bar = QProgressBar(textVisible=False, value=0)
        lay.addWidget(self.bar)
        self.rows, self.step_rows = {}, []
        for field, ids in STEPS:
            r = StepRow(t(opt_key(field)))
            lay.addWidget(r)
            self.step_rows.append((field, r))
            for i in ids:
                self.rows[i] = r
        lay.addStretch()
        self.results = QStackedWidget()
        columns.addWidget(self.results, 1)
        overview, lay = card(t("overview.title"))
        self.results.addWidget(overview)
        self.step_count = QLabel(objectName="overviewValue")
        self.protected_count = QLabel(objectName="overviewValue")
        self.source_names = QLabel(objectName="overviewValue")
        for key, value in (("overview.steps", self.step_count), ("protect.title", self.protected_count),
                           ("overview.sources", self.source_names)):
            row = QHBoxLayout()
            row.addWidget(QLabel(t(key)), 1)
            row.addWidget(value)
            lay.addLayout(row)
        review = QPushButton(t("overview.edit"), cursor=Qt.PointingHandCursor)
        review.clicked.connect(lambda: self.tabs.setCurrentIndex(1))
        lay.addWidget(review, 0, Qt.AlignLeft)
        lay.addStretch()

        summary, lay = card(t("card.summary"))
        self.results.addWidget(summary)
        self.stats_grid = QGridLayout()
        lay.addLayout(self.stats_grid)
        self.log = QPlainTextEdit(readOnly=True, placeholderText=t("log.placeholder"))
        self.log.setAccessibleName(t("card.summary"))
        self.log.setMinimumHeight(90)
        lay.addWidget(self.log, 1)
        self.log.textChanged.connect(lambda: self.results.setCurrentIndex(int(not self.log.document().isEmpty())))

    def _refresh_overview(self, index):
        if index != 0:
            return
        selected = {field: toggle.isChecked() for field, toggle in self.toggles.items()}
        optional = [field for field, _ in STEPS if not field.startswith("_")]
        self.step_count.setText(f"{sum(selected[field] for field in optional)} / {len(optional)}")
        if self.log.document().isEmpty() and self.thread is None:
            self.reset_rows(Options(**selected), "run")
        self.protected_count.setText(str(self.protected.count()))
        sources = [name for name, edit in (("Discogs", self.discogs), ("Last.fm", self.lastfm)) if edit.text().strip()]
        self.source_names.setText(", ".join(sources) or t("overview.none"))

    def _options_page(self, opts, shutdown):
        page = tab_page(self.tabs, "tab.options")
        columns = self._page_columns(page)
        basic, lay = card(t("card.steps"))
        columns.addWidget(basic, 1)
        self.toggles = {}
        self.scope_options = {field: getattr(opts, field) for field in OLD_SCOPE}
        for field, _ in STEPS:
            if not field.startswith("_"):
                self.toggles[field] = self._option(lay, field, getattr(opts, field))
        self.shutdown_toggle = Toggle(shutdown)
        self.shutdown_toggle.setAccessibleName(t("shut.toggle"))
        self.shutdown_toggle.setToolTip(t("shut.tip"))
        self.shutdown_toggle.toggled.connect(self.shutdown_note.setVisible)
        self.shutdown_toggle.toggled.connect(self._shutdown_armed)
        row = QHBoxLayout()
        label = QLabel(t("shut.toggle"), toolTip=t("shut.tip"))
        label.setBuddy(self.shutdown_toggle)
        row.addWidget(label, 1)
        row.addWidget(self.shutdown_toggle)
        lay.addLayout(row)
        lay.addStretch()
        extra, lay = card(t("card.more"))
        columns.addWidget(extra, 1)
        for field in EXTRA_OPTIONS:
            self.toggles[field] = self._option(lay, field, getattr(opts, field))
            if field == "only_new":
                self.new_only_hint = QLabel(t("scope.first_run"), objectName="hint", wordWrap=True)
                lay.addWidget(self.new_only_hint)
                self.btn_old_scope = QPushButton(cursor=Qt.PointingHandCursor)
                self._update_old_scope_button()
                self.btn_old_scope.clicked.connect(self.edit_old_scope)
                lay.addWidget(self.btn_old_scope, 0, Qt.AlignLeft)
            if field == "site_covers":
                self.btn_covers = QPushButton(t("btn.covers"), objectName="ghost", cursor=Qt.PointingHandCursor,
                                              toolTip=t("btn.covers_tip"))
                self.btn_covers.clicked.connect(lambda: self.start("covers_scan"))
                lay.addWidget(self.btn_covers, 0, Qt.AlignLeft)
        lay.addStretch()
        page.addStretch()

    def _sources_page(self, keys):
        page = tab_page(self.tabs, "card.online")
        link = '<a style="color:{c}" href="{h}">{x}</a>'
        c, lay = card(t("card.online"), t("card.online_hint",
                      discogs=link.format(c=C["accent"], h="https://www.discogs.com/settings/developers", x=t("link.discogs")),
                      lastfm=link.format(c=C["accent"], h="https://www.last.fm/api/account/create", x=t("link.lastfm"))))
        self.discogs = self._secret(lay, "Discogs token", keys.get("discogs_token", ""), "discogs")
        self.lastfm = self._secret(lay, "Last.fm API key", keys.get("lastfm_api_key", ""), "lastfm")
        page.addWidget(c)
        page.addStretch()

    def _tools_page(self, opts):
        page = tab_page(self.tabs, "tab.tools")
        columns = self._page_columns(page)
        protected, lay = card(t("protect.title"), t("protect.hint"))
        columns.addWidget(protected, 1)
        self.protected = QListWidget()
        self.protected.setAccessibleName(t("protect.title"))
        self.protected.addItems(opts.protected)
        self.protected.setMaximumHeight(96)
        lay.addWidget(self.protected)
        row = QHBoxLayout()
        row.addStretch()
        self.protect_add = QPushButton(t("protect.add"), objectName="ghost", cursor=Qt.PointingHandCursor)
        self.protect_del = QPushButton(t("protect.remove"), objectName="ghost", cursor=Qt.PointingHandCursor)
        self.protect_add.clicked.connect(self.add_protected)
        self.protect_del.clicked.connect(lambda: [self.protected.takeItem(self.protected.row(i))
                                                  for i in self.protected.selectedItems()])
        row.addWidget(self.protect_del)
        row.addWidget(self.protect_add)
        lay.addLayout(row)
        lay.addStretch()
        tools, lay = card(t("tools.library"))
        columns.addWidget(tools, 1)
        self.btn_report = QPushButton(t("btn.report"), toolTip=t("btn.report_tip"))
        self.btn_report.clicked.connect(lambda: self.start("report"))
        self.btn_undo = QPushButton(t("btn.history"), toolTip=t("btn.history_tip"))
        self.btn_undo.clicked.connect(self.undo)
        self.btn_quarantine = QPushButton(t("btn.quarantine"), toolTip=t("btn.quarantine_tip"))
        self.btn_quarantine.clicked.connect(self.open_quarantine)
        self.btn_purge = QPushButton(t("btn.purge"), objectName="danger", toolTip=t("btn.purge_tip"))
        self.btn_purge.clicked.connect(self.purge)
        for button in (self.btn_report, self.btn_undo, self.btn_quarantine, self.btn_purge):
            button.setCursor(Qt.PointingHandCursor)
            lay.addWidget(button)
        lay.addStretch()
        page.addStretch()

    def _dj_page(self):
        page = tab_page(self.tabs, "dj.library")
        columns = self._page_columns(page)
        review, left = card(t("dj.review"), t("dj.review_hint"))
        sets, right = card(t("dj.set"), t("dj.set_hint"))
        columns.addWidget(review, 1)
        columns.addWidget(sets, 1)
        self.dj_buttons = []
        for key, layout in (("dj.review", left), ("dj.import_xml", left), ("dj.history", left), ("dj.set", right)):
            action = QPushButton(t(key), cursor=Qt.PointingHandCursor)
            action.clicked.connect(lambda _, k=key: self.open_dj_tool(k))
            layout.addWidget(action)
            self.dj_buttons.append(action)
        left.addStretch()
        right.addStretch()
        page.addStretch()

    def open_dj_tool(self, key):
        from . import biblioteca
        from .dj_ui import ReviewDialog, SetDialog, TrackHistoryDialog, import_xml_dialog, perform
        from .pipeline import track_history
        opts, _ = self.current()
        if not os.path.isdir(opts.root) or too_broad(opts.root):
            QMessageBox.information(self, t("card.library"), t("msg.pick_folder"))
            return
        if key == "dj.import_xml":
            result = import_xml_dialog(self, opts.root)
            if result is not None:
                n = sum(bool(names) for names in result["tracks"].values())
                QMessageBox.information(self, t(key), t("dj.xml_loaded", name=result["xml"], n=n))
            return
        if key == "dj.history":
            entries = perform(self, t(key), lambda _: track_history(opts))
            if entries is None:
                return
            dialog = TrackHistoryDialog(opts, entries, self)
        else:
            review = key == "dj.review"
            opts = replace(opts, dedupe=True) if review else opts
            catalog = perform(self, t(key), lambda c: biblioteca.catalogue(opts, c, duplicates=review))
            if catalog is None:
                return
            dialog = ReviewDialog(opts, catalog, self) if review else SetDialog(opts, catalog[0].values(), self)
        dialog.exec()
        dialog.deleteLater()
        if key in ("dj.review", "dj.history"):
            self.radar.invalidate_library()

    # ---------- building blocks ----------

    def _secret(self, lay, label, value, service):
        lay.addWidget(QLabel(label, objectName="stepDesc"))
        row = QHBoxLayout()
        e = QLineEdit(value, echoMode=QLineEdit.Password)
        e.setAccessibleName(label)
        show = QPushButton(t("btn.show"), objectName="ghost", cursor=Qt.PointingHandCursor, checkable=True)
        show.toggled.connect(lambda on: (e.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password),
                                         show.setText(t("btn.hide") if on else t("btn.show"))))
        check = QPushButton(t("btn.check"), objectName="ghost", cursor=Qt.PointingHandCursor, toolTip=t("btn.check_tip"))
        clear = QPushButton(t("btn.clear_key"), objectName="ghost", cursor=Qt.PointingHandCursor)
        self._key_controls.extend((show, clear))
        status = QLabel(objectName="hint")
        self._key_ui[service] = (check, status)
        check.clicked.connect(lambda: self.check_key(service, e))
        def clear_key():
            name = "discogs_token" if service == "discogs" else "lastfm_api_key"
            if config.clear_key(name):
                self._saved_keys[name] = ""
                e.clear()

        def invalidate():
            self._checking.pop(service, None)
            check.setEnabled(e.isEnabled())
            status.clear()

        clear.clicked.connect(clear_key)
        e.textChanged.connect(invalidate)
        row.addWidget(e, 1)
        row.addWidget(show)
        row.addWidget(clear)
        row.addWidget(check)
        lay.addLayout(row)
        lay.addWidget(status)
        return e

    # ---------- updates ----------

    def look_for_update(self):
        from . import atualizacoes
        threading.Thread(target=lambda: self._update_found.emit(atualizacoes.check()), daemon=True).start()

    def _show_update(self, info):
        if not info:
            return
        self._update_info = info
        self.upd_label.setText(t("upd.available", v=info["version"]))
        self.upd_btn.setEnabled(True)
        self.upd_btn.setText(t("upd.install") if info.get("installer") and info.get("sha256") else t("upd.open_page"))
        self.banner.show()

    def _start_update(self):
        info = self._update_info
        if not (info.get("installer") and info.get("sha256")):  # nothing to verify it with: let the user download it
            QDesktopServices.openUrl(info["page"])
            return
        if self.thread and self.thread.isRunning():
            QMessageBox.information(self, t("app.title"), t("upd.busy"))
            return
        self._updating = True
        self.busy(True)  # no Organize/Preview/Undo while the update downloads
        self.btn_cancel.setEnabled(False)
        from . import atualizacoes
        self.upd_btn.setEnabled(False)

        def work():
            try:
                path = atualizacoes.download(info["installer"], info["sha256"],
                                             lambda d, tot: self._update_progress.emit(int(d * 100 / tot) if tot else 0))
            except Exception:
                path = ""
            self._update_ready.emit(path)

        threading.Thread(target=work, daemon=True).start()

    def _run_installer(self, path):
        self._updating = False
        self.busy(False)
        if not path:
            self.upd_btn.setEnabled(True)
            self.upd_btn.setText(t("upd.install"))
            QMessageBox.warning(self, t("app.title"), t("upd.failed"))
            QDesktopServices.openUrl(self._update_info["page"])
            return
        if self.thread and self.thread.isRunning():  # cannot happen (buttons were off), but never quit mid-run
            QMessageBox.information(self, t("app.title"), t("upd.busy"))
            return
        self.current()  # keep settings
        os.startfile(path)  # the installer replaces this version; the app closes so its files are free
        QApplication.quit()

    def check_key(self, service, edit):
        """Asks the service in the background; the window never freezes on a slow network."""
        from .online import check_key
        button, status = self._key_ui[service]
        button.setEnabled(False)
        status.setStyleSheet("")
        status.setText(t("key.checking"))
        key = edit.text()
        self._next_key_check += 1
        request = self._next_key_check
        self._checking[service] = request
        threading.Thread(target=lambda: self._key_result.emit(service, request, *check_key(service, key)), daemon=True).start()

    def _show_key_result(self, service, request, result, detail):
        if self._checking.get(service) != request:
            return
        del self._checking[service]
        button, status = self._key_ui[service]
        field = self.discogs if service == "discogs" else self.lastfm
        button.setEnabled(field.isEnabled())
        color = {"ok": C["accent"], "invalid": C["danger"]}.get(result, C["warn"])
        status.setStyleSheet(f"color:{color};")
        status.setText(t("key." + result, detail=detail).strip())
        if result == "ok":
            self.current()  # save the key that works

    def _option(self, lay, field, checked):
        row = QHBoxLayout()
        text = QVBoxLayout()
        text.setSpacing(1)
        title = QLabel(t(opt_key(field)), wordWrap=True)
        text.addWidget(title)
        text.addWidget(QLabel(t(opt_key(field) + "_d"), objectName="stepDesc", wordWrap=True))
        tg = Toggle(checked)
        tg.setAccessibleName(title.text())
        title.setBuddy(tg)
        row.addLayout(text, 1)
        row.addWidget(tg, 0, Qt.AlignVCenter)
        lay.addLayout(row)
        return tg

    # ---------- actions ----------

    def change_lang(self):
        if self.thread and self.thread.isRunning():
            return
        self.current()  # keep what was typed
        set_lang(self.lang_combo.currentData())
        config.put("idioma", lang())
        self.build()

    def show_help(self):
        from .ajuda import InfoDialog, help_html
        InfoDialog(t("btn.help"), help_html(), self).exec()

    def show_about(self):
        from .ajuda import InfoDialog, about_html
        InfoDialog(t("btn.about"), about_html(), self, (540, 540)).exec()

    def show_terms(self):
        from .ajuda import TermsView
        TermsView(self).exec()

    def pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, t("folder.dialog"), self.folder.text())
        if d:
            self.folder.setText(os.path.normpath(d))

    def add_protected(self):
        root = self.folder.text().strip()
        d = QFileDialog.getExistingDirectory(self, t("protect.dialog"), root)
        if not d:
            return
        d = os.path.normpath(d)
        if not root or not protectable(root, [d]):  # outside the library, the library itself, _entrada / _quarentena
            QMessageBox.warning(self, t("protect.title"), t("protect.outside", root=root))
            return
        if os.path.normcase(d) not in {os.path.normcase(self.protected.item(i).text()) for i in range(self.protected.count())}:
            self.protected.addItem(d)

    def _update_old_scope_button(self):
        self.btn_old_scope.setText(t("scope.button", n=sum(self.scope_options.values())))
        self.btn_old_scope.setAccessibleName(self.btn_old_scope.text())

    def _update_new_only_availability(self):
        available = has_completed_full_run(self.folder.text().strip())
        self.toggles["only_new"].setEnabled(available and not (self.thread and self.thread.isRunning()))
        self.new_only_hint.setVisible(not available)

    def _old_scope_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(t("scope.title"))
        dialog.setMinimumWidth(480)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(t("scope.hint"), objectName="hint", wordWrap=True))
        boxes = {}
        for field in OLD_SCOPE:
            boxes[field] = QCheckBox(t("scope." + field))
            boxes[field].setChecked(self.scope_options[field])
            layout.addWidget(boxes[field])
        layout.addWidget(QLabel(t("scope.warning"), objectName="hint", wordWrap=True))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        return dialog, boxes

    def edit_old_scope(self):
        dialog, boxes = self._old_scope_dialog()
        if dialog.exec() == QDialog.Accepted:
            self.scope_options = {field: box.isChecked() for field, box in boxes.items()}
            self._update_old_scope_button()
            self.current()

    def current(self):
        opts = Options(root=self.folder.text().strip(), folder_lang=self.folder_lang,
                       protected=[self.protected.item(i).text() for i in range(self.protected.count())],
                        **{f: tg.isChecked() for f, tg in self.toggles.items()}, **self.scope_options)
        keys = {"discogs_token": self.discogs.text().strip(), "lastfm_api_key": self.lastfm.text().strip()}
        values = asdict(opts)
        changed_opts = {name: value for name, value in values.items() if value != self._saved_options[name]}
        changed_keys = {name: value for name, value in keys.items() if value != self._saved_keys[name]}
        if changed_opts or changed_keys:
            # Two open windows can edit different settings. Merge only edits made in this window.
            stored_opts, stored_keys = config.load()
            if config.save(replace(stored_opts, **changed_opts), stored_keys | changed_keys):
                self._saved_options, self._saved_keys = values, keys
        return opts, keys

    def busy(self, on):
        for w in (self.btn_preview, self.btn_run, self.btn_undo, self.btn_purge, self.btn_quarantine, self.btn_report, self.btn_plan,
                  self.btn_covers, self.btn_old_scope, self.protected, self.protect_add, self.protect_del, self.folder, self.pick_btn, self.discogs, self.lastfm,
                  self.lang_combo, *self.dj_buttons, *self._key_controls, *self.toggles.values()):
            w.setEnabled(not on)
        for service, (check, _) in self._key_ui.items():
            check.setEnabled(not on and service not in self._checking)
        self.btn_cancel.setEnabled(on)
        self.btn_cancel.setVisible(on)
        if on:
            self.tabs.setCurrentIndex(0)
        if not on:
            self._update_new_only_availability()

    def reset_rows(self, opts, kind):
        for field, r in self.step_rows:
            if kind == "preview":
                on = field == "_organize" or (field in ("extract", "dedupe") and getattr(opts, field))
            elif kind == "duplicates":
                on = field == "dedupe"
            elif kind in ("undo", "purge", "report", "covers_scan"):
                on = False
            elif field == "write_tags":
                on = opts.write_tags or opts.clean_sites
            elif field == "covers":
                on = opts.covers or opts.site_covers
            else:
                on = field.startswith("_") or getattr(opts, field)
            r.set("waiting" if on else "off")

    def start(self, kind, opts=None, keys=None, extra=None):
        if getattr(self, "_updating", False):
            return  # an update is downloading; the app will close for the installer
        if opts is None:
            opts, keys = self.current()
        if not os.path.isdir(opts.root):
            QMessageBox.warning(self, t("card.library"), t("msg.pick_folder"))
            self.folder.setFocus()
            return
        if too_broad(opts.root):
            QMessageBox.warning(self, t("card.library"), t("err.too_broad", root=opts.root))
            self.folder.setFocus()
            return
        if kind == "run" and QMessageBox.question(self, t("btn.run"), t("msg.run_confirm", root=opts.root)) != QMessageBox.Yes:
            return
        if kind == "duplicates":
            count = len(extra["reviewed_duplicates"])
            if not count or QMessageBox.question(self, t("plan.quarantine_only"),
                                                  t("plan.quarantine_confirm", n=count)) != QMessageBox.Yes:
                return
        risky_old = (opts.organize_all or (opts.dedupe and opts.dedupe_all)
                     or (opts.online and opts.online_all) or (opts.bpm_folders and opts.bpm_all)
                     or (opts.site_covers and opts.site_covers_all))
        if kind == "run" and opts.only_new and risky_old and QMessageBox.question(
                self, t("scope.title"), t("msg.old_scope_confirm")) != QMessageBox.Yes:
            return
        self.reset_rows(opts, kind)
        self.current_row = None
        self.bar.setMaximum(1)
        self.bar.setValue(0)
        self.clear_stats()
        self._last_rep = {}
        self._clear_plan()
        self.cancel = threading.Event()
        self.thread = QThread()
        self.worker = Worker(kind, opts, keys, self.cancel, extra)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.failed.connect(self.on_failed)
        self.worker.ask.connect(self.ask_rename)
        for sig in (self.worker.finished, self.worker.failed):
            sig.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self._thread_done)
        self.busy(True)
        self.log.appendPlainText(f"— {t('log.kind.' + kind)}: {opts.root}")
        self.status.setText(t("status.starting"))
        self.thread.start()

    def closeEvent(self, event):
        """Never kill the worker mid-file (a half-written tag corrupts the track): cancel, then close."""
        if self.thread and self.thread.isRunning():
            event.ignore()
            if QMessageBox.question(self, t("app.title"), t("msg.close_running")) == QMessageBox.Yes:
                self.do_cancel()
                if self.thread and self.thread.isRunning():
                    self.thread.finished.connect(self.close)
                else:
                    QTimer.singleShot(0, self.close)
            return
        self.current()
        event.accept()

    def open_quarantine(self):
        """The quarantine is a hidden folder: opened here so nobody has to turn on hidden items in Explorer."""
        from .pipeline import QUARANTINE
        root = self.folder.text().strip()
        q = os.path.join(root, QUARANTINE)
        if root and os.path.isdir(q) and any(n != ".quarentena-da-app" for n in os.listdir(q)):
            os.startfile(q)
        else:
            QMessageBox.information(self, t("btn.quarantine"), t("msg.quarantine_empty"))

    def purge(self):
        opts, keys = self.current()
        if QMessageBox.question(self, t("btn.purge"), t("msg.purge_confirm")) == QMessageBox.Yes:
            self.start("purge", opts, keys)

    def undo(self):
        from .janelas import HistoryDialog, run_date
        opts, keys = self.current()
        if not os.path.isdir(opts.root):
            QMessageBox.warning(self, t("card.library"), t("msg.pick_folder"))
            return
        runs = list_runs(opts.root)
        d = HistoryDialog(runs, self)
        if d.exec() != HistoryDialog.Accepted or d.chosen() < 0:
            return
        i = d.chosen()
        run_id = runs[i][0]
        if QMessageBox.question(self, t("history.title"), t("history.confirm", n=i + 1, date=run_date(run_id))) == QMessageBox.Yes:
            self.start("undo", opts, keys, {"until": run_id, "newest": runs[0][0]})

    def _update_plan_button(self):
        if self._plan:
            tracks = len({p for _, p, _ in self._plan})
            label = "btn.plan_duplicates" if all(kind == "dup" for kind, _, _ in self._plan) else "btn.plan"
            self.btn_plan.setText(t(label, n=f"{tracks:,}".replace(",", " ")))
        self.btn_plan.setVisible(bool(self._plan))

    def _clear_plan(self):
        self._plan, self._plan_opts, self._plan_snapshot = [], None, None
        self._dup_details = {}
        self.btn_plan.hide()

    def organize(self):
        if any(kind == "dup" for kind, _, _ in self._plan):
            self.show_plan()
        else:
            self.start("run")

    def show_plan(self):
        from .janelas import PlanDialog
        opts, keys = self.current()
        if asdict(opts) != self._plan_opts:  # folder or options changed since the Preview: the list is not for these
            self._clear_plan()
            QMessageBox.information(self, t("plan.title"), t("plan.stale"))
            return
        d = PlanDialog(self._plan, opts.root, self, details=self._dup_details)
        result = d.exec()
        d.deleteLater()
        if result != PlanDialog.Accepted:
            return
        try:
            same = Organizer(opts).library_snapshot() == self._plan_snapshot
        except (OSError, ValueError):
            same = False
        if not same:  # tracks or packs added, moved, renamed or changed since the Preview: the list no longer holds
            self._clear_plan()
            QMessageBox.information(self, t("plan.title"), t("plan.stale"))
            return
        self.start("duplicates" if d.quarantine_only else "run", opts, keys,
                   {"skip": [] if d.quarantine_only else d.skipped(), "snapshot": self._plan_snapshot,
                    "reviewed_duplicates": d.reviewed_duplicates(), "keeper_choices": d.keeper_choices})

    def do_cancel(self):
        self.cancel.set()
        self.btn_cancel.setEnabled(False)
        self.status.setText(t("status.cancelling"))

    def ask_rename(self, worker, items, kind="new"):
        """New tracks outside _entrada: renaming one that is already in rekordbox/Serato would make it lose it.
        The box is modal, so it carries its own Cancel (the main Cancel button can't be clicked meanwhile)."""
        if self.cancel.is_set():
            worker.answer(False)
            return
        # sites: tracks you already had (maybe in rekordbox); new_sites: new tracks, only the site comes out
        prefix = {"sites": "sites", "new_sites": "newsites"}.get(kind, "rename")
        box = QMessageBox(QMessageBox.Question, t(prefix + ".title"), t(prefix + ".ask", n=len(items)),
                          QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel, self)
        box.setDefaultButton(QMessageBox.No)
        box.setDetailedText("\n".join(f"{os.path.basename(p)}  →  {name}" for p, name in items))
        choice = box.exec()
        if choice == QMessageBox.Cancel:
            self.do_cancel()
        worker.answer(choice == QMessageBox.Yes)

    def on_progress(self, step, i, n, msg):
        self.bar.setMaximum(max(n, 1))
        self.bar.setValue(i)
        self.status.setText(msg or t("step." + step))
        row = self.rows.get(step)
        if row:
            if self.current_row is not None and self.current_row is not row:
                self.current_row.set("done")
            self.current_row = row
            row.set("running", f"{i:,} / {n:,}".replace(",", " "))

    # ---------- shut down when done ----------

    def _shutdown_armed(self, on):
        if on and QMessageBox.question(self, t("shut.toggle"), t("shut.confirm")) != QMessageBox.Yes:
            self.shutdown_toggle.setChecked(False)

    def _maybe_shutdown(self, kind, errs=()):
        """After an Organize run that finished (never after an error or a cancel): 60 s to change your mind."""
        if kind != "run" or errs or not self.shutdown_toggle.isChecked():
            return
        self.shutdown_toggle.setChecked(False)
        shutdown_pc(60)
        box = QMessageBox(QMessageBox.Warning, t("shut.toggle"), t("shut.countdown", s=60), parent=self)
        cancel = box.addButton(t("shut.cancel"), QMessageBox.RejectRole)
        self._shutdown_left = 60

        def tick():
            self._shutdown_left -= 1
            box.setText(t("shut.countdown", s=max(self._shutdown_left, 0)))

        timer = QTimer(box, interval=1000)
        timer.timeout.connect(tick)
        timer.start()
        box.exec()
        timer.stop()
        if box.clickedButton() is cancel:
            cancel_shutdown()
            self.log.appendPlainText(t("shut.cancelled"))

    def _thread_done(self):
        thread = self.thread
        self.thread = self.worker = None  # the worker deletes itself when its thread ends (connected in start)
        thread.deleteLater()
        self.busy(False)

    def on_finished(self, kind, rep, errs):
        if kind in ("run", "duplicates", "undo"):
            self.radar.invalidate_library()
        QTimer.singleShot(0, lambda: self._maybe_shutdown(kind, tuple(errs)))  # after the results are on screen
        self._last_rep = rep
        self.bar.setMaximum(1)
        self.bar.setValue(1)
        for _, r in self.step_rows:
            if r.current != "off":
                r.set("done")
        self._status_key = "status.preview_done" if kind == "preview" else "status.done"
        self.status.setText(t(self._status_key))
        self.show_stats(rep)
        for k, v in sorted(rep.items(), key=lambda kv: -kv[1]):
            if k != "only_new_first":  # a note, not a count
                self.log.appendPlainText(f"{v:>7}  {report_label(k)}")
        if rep.get("only_new_first"):
            self.log.appendPlainText(t("log.only_new_first"))
        if errs:
            self.log.appendPlainText(t("log.warnings", n=len(errs)))
            for e in errs[:100]:
                self.log.appendPlainText(f"   {e}")
        if kind == "run":
            self.log.appendPlainText(t("log.rekordbox"))
        if kind == "preview":
            self.log.appendPlainText(t("log.preview_limits"))
            self._plan, self._plan_snapshot = self.worker.plan, self.worker.snapshot
            self._dup_details = self.worker.dup_details
            self._plan_opts = asdict(self.worker.opts)
            self._update_plan_button()
        if kind == "covers_scan":
            found = self.worker.repeated
            QTimer.singleShot(0, lambda: self._covers_ready(found))
        if kind == "report" and self.worker.report_path:
            path = self.worker.report_path
            QTimer.singleShot(0, lambda: self._report_ready(path))  # after the counts are on screen

    def _covers_ready(self, found):
        from .janelas import CoversDialog
        site = SiteCovers(MARKED_COVERS)
        if not found and not site.marked:
            QMessageBox.information(self, t("covers.title"), t("covers.empty"))
            return
        d = CoversDialog(found, site.marked, self)
        if d.exec() == CoversDialog.Accepted:
            site.save_marked(d.marked())

    def _report_ready(self, path):
        box = QMessageBox(QMessageBox.Information, t("btn.report"), t("report.done", path=path), QMessageBox.Close, self)
        open_btn = box.addButton(t("report.open"), QMessageBox.AcceptRole)
        box.exec()
        if box.clickedButton() is open_btn:
            os.startfile(path)

    def on_failed(self, msg, cancelled):
        if self.current_row is not None:
            self.current_row.set("cancelled" if cancelled else "error")
        self._status_key = "status.cancelled" if cancelled else "status.stopped"
        self.status.setText(t(self._status_key))
        self.log.appendPlainText(msg)

    def clear_stats(self):
        while self.stats_grid.count():
            self.stats_grid.takeAt(0).widget().deleteLater()

    def show_stats(self, rep):
        def total(*ids):
            return sum(v for k, v in rep.items() if k.partition("|")[0] in ids)
        stats = [("stat.tracks", rep.get("tracks")), ("stat.moved", total("moved", "to_move", "undo_returned", "undo_from_quarantine")),
                 ("stat.dups", total("dups_trashed", "dups_pending")), ("stat.online", total("online")),
                 ("stat.tags", total("genre_tag_fixed", "genre_spam_cleared", "sites_cleaned"))]
        col = 0
        for label, v in stats:
            if not v:
                continue
            box = QVBoxLayout()
            box.addWidget(QLabel(f"{v:,}".replace(",", " "), objectName="statValue"))
            box.addWidget(QLabel(t(label), objectName="statLabel"))
            w = QWidget()
            w.setLayout(box)
            self.stats_grid.addWidget(w, col // 3, col % 3)
            col += 1


def log_crash(text):
    """Appends a traceback to %APPDATA%\\GrooveWizard\\erros.log; returns the text for the window."""
    import datetime
    path = os.path.join(APP_DIR, "erros.log")
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"\n=== {datetime.datetime.now():%Y-%m-%d %H:%M:%S} v{__version__}\n{text}")
    except OSError:
        pass
    return text + "\n" + t("err.crash", path=path)


def _excepthook(kind, value, tb):
    msg = log_crash("".join(traceback.format_exception(kind, value, tb)))
    try:
        QMessageBox.critical(None, t("app.title"), msg[-1500:])
    except Exception:
        pass


def shutdown_pc(seconds):
    """Windows shuts down in `seconds`, forcing other apps closed (/f) so nothing blocks it overnight."""
    import subprocess
    subprocess.run(["shutdown", "/s", "/f", "/t", str(seconds), "/c", t("shut.windows_msg")],
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def cancel_shutdown():
    import subprocess
    subprocess.run(["shutdown", "/a"], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def first_run():
    """Language + Terms. Returns False if the user refused. Also fixes the folder-name language on first use."""
    set_lang(config.get("idioma") or system_lang())
    if config.get("termos_aceites") == termos.VERSION:
        return True
    from .ajuda import TermsDialog
    if TermsDialog().exec() != TermsDialog.Accepted:
        return False
    config.put("idioma", lang())
    config.put("termos_aceites", termos.VERSION)
    opts, keys = config.load()
    if not config.get("opcoes"):  # brand-new install: folder names follow the chosen language
        opts.folder_lang = lang()
        config.save(opts, keys)
    return True


def main():
    sys.excepthook = _excepthook  # errors outside the worker (UI code) are logged, not silent
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS)
    app.setWindowIcon(QIcon(ICON))
    if not first_run():
        sys.exit(0)
    w = Window()
    w.show()
    w.look_for_update()  # always: the user wants to be told about every new version
    sys.exit(app.exec())
