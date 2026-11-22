"""Window: pick the music folder, paste API keys, choose steps, Organize / Preview / Undo with per-step progress."""
import os
import sys
import threading
import traceback

from PySide6.QtCore import QObject, QPropertyAnimation, QRectF, QSize, Qt, QThread, Signal, Property
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (QAbstractButton, QApplication, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
                               QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from . import __version__, config, termos
from .i18n import LANGS, lang, report_label, set_lang, system_lang, t
from .pipeline import Cancelled, Options, Organizer, too_broad, undo_last
from .theme import C, QSS

# (Options field, pipeline step ids shown on that row). "_organize" always runs.
STEPS = [("extract", ["extract"]), ("_organize", ["organize"]), ("dedupe", ["dedupe_scan", "dedupe_remove"]),
         ("online", ["online"]), ("bpm_folders", ["bpm"]), ("write_tags", ["tags"])]
EXTRA_OPTIONS = ["clean_sites", "families", "musicbrainz", "delete_archives"]
ICON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recursos", "cratekeeper.png")


def opt_key(field):
    return "opt." + field.lstrip("_")


class Toggle(QAbstractButton):
    """Switch; keyboard accessible (Space toggles), visible focus ring."""

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(160)
        self.toggled.connect(self._animate)

    def sizeHint(self):
        return QSize(44, 24)

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
        off, on = QColor(C["muted"]), QColor(C["accent"])
        mix = lambda a, b: int(a + (b - a) * self._pos)
        track = QColor(mix(off.red(), on.red()), mix(off.green(), on.green()), mix(off.blue(), on.blue()))
        if not self.isEnabled():
            track.setAlpha(90)
        p.setPen(QColor(C["secondary_hover"]) if self.hasFocus() else Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 6
        x = r.left() + 3 + (r.width() - d - 6) * self._pos
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QRectF(x, r.top() + 3, d, d))


def card(title=None, subtitle=None):
    f = QFrame(objectName="card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(20, 18, 20, 18)
    lay.setSpacing(12)
    if title:
        lay.addWidget(QLabel(title, objectName="cardTitle"))
    if subtitle:
        lay.addWidget(QLabel(subtitle, objectName="hint", wordWrap=True, openExternalLinks=True))
    return f, lay


class StepRow(QWidget):
    """Status dot + title + live counter."""
    COLORS = {"waiting": C["muted"], "running": C["secondary_hover"], "done": C["accent"], "off": "#3A3A55",
              "error": C["danger"]}

    def __init__(self, title):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 4)
        self.dot = QLabel(fixedSize=QSize(12, 12))
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
        self.dot.setStyleSheet(f"background:{self.COLORS[state]}; border-radius:6px;")
        self.title.setStyleSheet(f"color:{C['fg'] if state != 'off' else '#5B6478'};"
                                 f"font-weight:{600 if state == 'running' else 400};")
        self.state.setText(text if text is not None else t("state." + state))


class Worker(QObject):
    progress = Signal(str, int, int, str)
    finished = Signal(str, object, object)  # kind, report, errors
    failed = Signal(str)

    def __init__(self, kind, opts, keys, cancel):
        super().__init__()
        self.kind, self.opts, self.keys, self.cancel = kind, opts, keys, cancel

    def run(self):
        emit = lambda step, i, n, msg="": self.progress.emit(step, i, n, msg)
        try:
            if self.kind == "undo":
                rep, errs = undo_last(self.opts.root, emit, self.cancel)
            else:
                org = Organizer(self.opts, self.keys, emit, self.cancel)
                rep, errs = (org.preview(), []) if self.kind == "preview" else org.run()
            self.finished.emit(self.kind, rep, errs)
        except Cancelled:
            self.failed.emit(t("msg.cancelled"))
        except Exception:
            self.failed.emit(traceback.format_exc())


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(t("app.title"))
        self.resize(1080, 760)
        self.setMinimumSize(900, 620)
        self.thread = None
        self.build()
        QShortcut(QKeySequence("F1"), self, self.show_help)

    def build(self):
        opts, keys = config.load()
        self.folder_lang = opts.folder_lang
        root = QWidget(objectName="root")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(20)

        # header
        head = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(QPixmap(ICON).scaled(52, 52, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        head.addWidget(logo, 0, Qt.AlignTop)
        head.addSpacing(10)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(QLabel(t("app.title"), objectName="title"))
        titles.addWidget(QLabel(t("app.subtitle"), objectName="subtitle"))
        head.addLayout(titles, 1)
        for label, tip, fn in (("btn.help", "btn.help_tip", self.show_help), ("terms.menu", "terms.title", self.show_terms),
                               ("btn.about", "btn.about_tip", self.show_about)):
            b = QPushButton(t(label), objectName="ghost", cursor=Qt.PointingHandCursor, toolTip=t(tip))
            b.clicked.connect(fn)
            head.addWidget(b, 0, Qt.AlignTop)
        self.lang_combo = QComboBox(toolTip=t("lang.tip"))
        self.lang_combo.setAccessibleName(t("lang.tip"))
        for code, name in LANGS.items():
            self.lang_combo.addItem(name, code)
        self.lang_combo.setCurrentIndex(list(LANGS).index(lang()))
        self.lang_combo.currentIndexChanged.connect(self.change_lang)
        head.addWidget(self.lang_combo, 0, Qt.AlignTop)
        head.addWidget(QLabel(f"v{__version__}", objectName="badge"), 0, Qt.AlignTop)
        outer.addLayout(head)

        cols = QHBoxLayout()
        cols.setSpacing(20)
        outer.addLayout(cols, 1)

        # ---- left: settings (scrollable) ----
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 6, 0)
        ll.setSpacing(16)

        c, lay = card(t("card.library"), t("card.library_hint"))
        row = QHBoxLayout()
        self.folder = QLineEdit(opts.root, placeholderText=t("folder.placeholder"))
        self.folder.setAccessibleName(t("folder.dialog"))
        pick = QPushButton(t("folder.pick"), cursor=Qt.PointingHandCursor)
        pick.clicked.connect(self.pick_folder)
        row.addWidget(self.folder, 1)
        row.addWidget(pick)
        lay.addLayout(row)
        ll.addWidget(c)

        link = '<a style="color:{c}" href="{h}">{x}</a>'
        c, lay = card(t("card.online"), t("card.online_hint",
                      discogs=link.format(c=C["accent"], h="https://www.discogs.com/settings/developers", x=t("link.discogs")),
                      lastfm=link.format(c=C["accent"], h="https://www.last.fm/api/account/create", x=t("link.lastfm"))))
        self.discogs = self._secret(lay, "Discogs token", keys.get("discogs_token", ""))
        self.lastfm = self._secret(lay, "Last.fm API key", keys.get("lastfm_api_key", ""))
        ll.addWidget(c)

        c, lay = card(t("card.steps"))
        self.toggles = {}
        for field, _ in STEPS:
            if not field.startswith("_"):
                self.toggles[field] = self._option(lay, field, getattr(opts, field))
        lay.addWidget(QLabel(t("card.more"), objectName="cardTitle"))
        for field in EXTRA_OPTIONS:
            self.toggles[field] = self._option(lay, field, getattr(opts, field))
        ll.addWidget(c)
        ll.addStretch()

        scroll = QScrollArea(widgetResizable=True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # content follows the column width
        left.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        scroll.setWidget(left)
        scroll.setMinimumWidth(440)
        cols.addWidget(scroll, 5)

        # ---- right: actions + progress ----
        right = QVBoxLayout()
        right.setSpacing(16)
        c, lay = card()
        btns = QHBoxLayout()
        self.btn_run = QPushButton(t("btn.run"), objectName="primary", cursor=Qt.PointingHandCursor)
        self.btn_preview = QPushButton(t("btn.preview"), cursor=Qt.PointingHandCursor, toolTip=t("btn.preview_tip"))
        self.btn_cancel = QPushButton(t("btn.cancel"), objectName="danger", cursor=Qt.PointingHandCursor, enabled=False)
        self.btn_undo = QPushButton(t("btn.undo"), objectName="ghost", cursor=Qt.PointingHandCursor, toolTip=t("btn.undo_tip"))
        self.btn_run.clicked.connect(lambda: self.start("run"))
        self.btn_preview.clicked.connect(lambda: self.start("preview"))
        self.btn_cancel.clicked.connect(self.do_cancel)
        self.btn_undo.clicked.connect(self.undo)
        for b in (self.btn_run, self.btn_preview, self.btn_cancel):
            btns.addWidget(b)
        btns.addStretch()
        btns.addWidget(self.btn_undo)
        lay.addLayout(btns)
        self.bar = QProgressBar(textVisible=False)
        self.status = QLabel(t("status.ready"), objectName="hint")
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.bar)
        lay.addWidget(self.status)
        right.addWidget(c)

        c, lay = card(t("card.progress"))
        self.rows, self.step_rows = {}, []
        for field, ids in STEPS:
            r = StepRow(t(opt_key(field)))
            lay.addWidget(r)
            self.step_rows.append((field, r))
            for i in ids:
                self.rows[i] = r
        right.addWidget(c)

        c, lay = card(t("card.summary"))
        self.stats_grid = QGridLayout()
        self.stats_grid.setHorizontalSpacing(24)
        lay.addLayout(self.stats_grid)
        self.log = QPlainTextEdit(readOnly=True, placeholderText=t("log.placeholder"))
        self.log.setMinimumHeight(140)
        lay.addWidget(self.log, 1)
        right.addWidget(c, 1)
        cols.addLayout(right, 6)

        self.setCentralWidget(root)
        self.setWindowTitle(t("app.title"))

    # ---------- building blocks ----------

    def _secret(self, lay, label, value):
        lay.addWidget(QLabel(label, objectName="stepDesc"))
        row = QHBoxLayout()
        e = QLineEdit(value, echoMode=QLineEdit.Password)
        e.setAccessibleName(label)
        show = QPushButton(t("btn.show"), objectName="ghost", cursor=Qt.PointingHandCursor, checkable=True)
        show.toggled.connect(lambda on: (e.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password),
                                         show.setText(t("btn.hide") if on else t("btn.show"))))
        row.addWidget(e, 1)
        row.addWidget(show)
        lay.addLayout(row)
        return e

    def _option(self, lay, field, checked):
        row = QHBoxLayout()
        text = QVBoxLayout()
        text.setSpacing(1)
        title = QLabel(t(opt_key(field)))
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

    def current(self):
        opts = Options(root=self.folder.text().strip(), folder_lang=self.folder_lang,
                       **{f: tg.isChecked() for f, tg in self.toggles.items()})
        keys = {"discogs_token": self.discogs.text().strip(), "lastfm_api_key": self.lastfm.text().strip()}
        config.save(opts, keys)
        return opts, keys

    def busy(self, on):
        for w in (self.btn_preview, self.btn_run, self.btn_undo, self.folder, self.lang_combo, *self.toggles.values()):
            w.setEnabled(not on)
        self.btn_cancel.setEnabled(on)

    def reset_rows(self, opts, kind):
        for field, r in self.step_rows:
            if kind == "preview":
                on = field in ("_organize", "extract", "dedupe")
            elif kind == "undo":
                on = False
            elif field == "write_tags":
                on = opts.write_tags or opts.clean_sites
            else:
                on = field.startswith("_") or getattr(opts, field)
            r.set("waiting" if on else "off")

    def start(self, kind, opts=None, keys=None):
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
        self.reset_rows(opts, kind)
        self.current_row = None
        self.clear_stats()
        self.cancel = threading.Event()
        self.thread = QThread()
        self.worker = Worker(kind, opts, keys, self.cancel)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.failed.connect(self.on_failed)
        for sig in (self.worker.finished, self.worker.failed):
            sig.connect(self.thread.quit)
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
                self.thread.finished.connect(self.close)
            return
        event.accept()

    def undo(self):
        opts, keys = self.current()
        if QMessageBox.question(self, t("btn.undo"), t("msg.undo_confirm")) == QMessageBox.Yes:
            self.start("undo", opts, keys)

    def do_cancel(self):
        self.cancel.set()
        self.btn_cancel.setEnabled(False)
        self.status.setText(t("status.cancelling"))

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

    def on_finished(self, kind, rep, errs):
        self.busy(False)
        self.bar.setMaximum(1)
        self.bar.setValue(1)
        for _, r in self.step_rows:
            if r.current != "off":
                r.set("done")
        self.status.setText(t("status.preview_done") if kind == "preview" else t("status.done"))
        self.show_stats(rep)
        for k, v in sorted(rep.items(), key=lambda kv: -kv[1]):
            self.log.appendPlainText(f"{v:>7}  {report_label(k)}")
        if errs:
            self.log.appendPlainText(t("log.warnings", n=len(errs)))
            for e in errs[:100]:
                self.log.appendPlainText(f"   {e}")
        if kind == "run":
            self.log.appendPlainText(t("log.rekordbox"))

    def on_failed(self, msg):
        self.busy(False)
        if self.current_row is not None:
            self.current_row.set("error")
        self.status.setText(t("status.stopped"))
        self.log.appendPlainText(msg)

    def clear_stats(self):
        while self.stats_grid.count():
            self.stats_grid.takeAt(0).widget().deleteLater()

    def show_stats(self, rep):
        def total(*ids):
            return sum(v for k, v in rep.items() if k.partition("|")[0] in ids)
        stats = [("stat.tracks", rep.get("tracks")), ("stat.moved", total("moved", "to_move", "undo_returned")),
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
            self.stats_grid.addWidget(w, 0, col)
            col += 1


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
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS)
    app.setWindowIcon(QIcon(ICON))
    if not first_run():
        sys.exit(0)
    w = Window()
    w.show()
    sys.exit(app.exec())
