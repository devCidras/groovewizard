"""Window: pick the music folder, paste API keys, choose steps, Organize / Preview / Undo with per-step progress."""
import os
import sys
import threading
import traceback

from PySide6.QtCore import QObject, QPropertyAnimation, QRectF, QSize, Qt, QThread, Signal, Property
from PySide6.QtGui import QColor, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (QAbstractButton, QApplication, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
                               QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from . import __version__, config
from .pipeline import Cancelled, Options, Organizer, undo_last
from .theme import C, QSS

# (Options field, title, description, pipeline step names it covers)
STEPS = [
    ("extract", "Extrair packs", "Descompacta .zip, .rar e .7z (os .rar/.7z precisam do 7-Zip).", ["Extrair"]),
    ("_organize", "Arrumar por género", "Pela tag Genre; sem tag, pelo nome do pack.", ["Organizar por genero"]),
    ("dedupe", "Remover repetidas", "Fica a Extended, senão a mais longa. As outras vão para a Reciclagem.",
     ["Procurar repetidas", "Remover repetidas"]),
    ("online", "Procurar género online", "Discogs e Last.fm para as faixas sem género.", ["Procurar genero online"]),
    ("bpm_folders", "Separar por BPM", "'Sem Genero' e 'Outros' em pastas de BPM 122-128, 128-135...", ["Separar por BPM"]),
    ("write_tags", "Gravar género na tag", "O rekordbox / Serato passam a mostrar o género certo.", ["Corrigir tags"]),
]
EXTRA_OPTIONS = [
    ("clean_sites", "Limpar sites das tags", "Tira 'djsoundtop.com' e afins do Álbum, Título, Comentário..."),
    ("families", "Agrupar em pastas-mãe", "House / Tech House, Techno / Hard Techno, Melodic & Indie..."),
    ("musicbrainz", "Usar também o MusicBrainz", "Sem chave, mas lento (1 pedido por segundo)."),
    ("delete_archives", "Enviar compactados para a Reciclagem", "Depois de extraídos com sucesso."),
]


class Toggle(QAbstractButton):
    """iOS-style switch; keyboard accessible (Space toggles), visible focus ring."""

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
        track = QColor(off.red() + (on.red() - off.red()) * self._pos, off.green() + (on.green() - off.green()) * self._pos,
                       off.blue() + (on.blue() - off.blue()) * self._pos)
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
        s = QLabel(subtitle, objectName="hint", wordWrap=True, openExternalLinks=True)
        lay.addWidget(s)
    return f, lay


class StepRow(QWidget):
    """Status dot + title + live counter."""
    COLORS = {"espera": C["muted"], "a correr": C["secondary_hover"], "feito": C["accent"], "desligado": "#3A3A55",
              "erro": C["danger"]}

    def __init__(self, title):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 4)
        self.dot = QLabel(fixedSize=QSize(12, 12))
        self.title = QLabel(title)
        self.state = QLabel(objectName="hint")
        lay.addWidget(self.dot)
        lay.addSpacing(8)
        lay.addWidget(self.title, 1)
        lay.addWidget(self.state)
        self.set("espera")

    def set(self, state, text=None):
        self.dot.setStyleSheet(f"background:{self.COLORS[state]}; border-radius:6px;")
        self.title.setStyleSheet(f"color:{C['fg'] if state != 'desligado' else '#5B6478'};"
                                 f"font-weight:{600 if state == 'a correr' else 400};")
        self.state.setText(text if text is not None else ("" if state == "espera" else state))


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
                rep, errs = undo_last(self.opts.root, emit)
            else:
                org = Organizer(self.opts, self.keys, emit, self.cancel)
                rep, errs = (org.preview(), []) if self.kind == "preview" else org.run()
            self.finished.emit(self.kind, rep, errs)
        except Cancelled:
            self.failed.emit("Cancelado. O que já foi feito fica feito e pode ser desfeito.")
        except Exception:
            self.failed.emit(traceback.format_exc())


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Organizador de Música")
        self.resize(1080, 760)
        self.setMinimumSize(900, 620)
        opts, keys = config.load()
        self.thread = None

        root = QWidget(objectName="root")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(20)

        # header
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(QLabel("Organizador de Música", objectName="title"))
        titles.addWidget(QLabel("Arruma a tua biblioteca por género, sem repetidas, com as tags limpas.", objectName="subtitle"))
        head.addLayout(titles, 1)
        for label, tip, fn in (("Ajuda", "Como usar (F1)", self.show_help), ("Sobre", "Quem fez, versão, licença", self.show_about)):
            b = QPushButton(label, objectName="ghost", cursor=Qt.PointingHandCursor, toolTip=tip)
            b.clicked.connect(fn)
            head.addWidget(b, 0, Qt.AlignTop)
        head.addWidget(QLabel(f"v{__version__}", objectName="badge"), 0, Qt.AlignTop)
        QShortcut(QKeySequence("F1"), self, self.show_help)
        outer.addLayout(head)

        cols = QHBoxLayout()
        cols.setSpacing(20)
        outer.addLayout(cols, 1)

        # ---- left: settings (scrollable) ----
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 6, 0)
        ll.setSpacing(16)

        c, lay = card("Biblioteca", "A pasta onde estão as tuas músicas. Fecha o rekordbox / Serato antes de organizar.")
        row = QHBoxLayout()
        self.folder = QLineEdit(opts.root, placeholderText=r"ex.: D:\musica")
        self.folder.setAccessibleName("Pasta das músicas")
        pick = QPushButton("Escolher…", cursor=Qt.PointingHandCursor)
        pick.clicked.connect(self.pick_folder)
        row.addWidget(self.folder, 1)
        row.addWidget(pick)
        lay.addLayout(row)
        ll.addWidget(c)

        c, lay = card("Fontes online", 'Chaves grátis, guardadas só neste PC. '
                      '<a style="color:#22C55E" href="https://www.discogs.com/settings/developers">Criar token Discogs</a> · '
                      '<a style="color:#22C55E" href="https://www.last.fm/api/account/create">Criar chave Last.fm</a>')
        self.discogs = self._secret(lay, "Discogs token", keys.get("discogs_token", ""))
        self.lastfm = self._secret(lay, "Last.fm API key", keys.get("lastfm_api_key", ""))
        ll.addWidget(c)

        c, lay = card("Passos")
        self.toggles = {}
        for field, title, desc, _ in STEPS:
            if field.startswith("_"):
                continue  # sorting by genre always runs
            self.toggles[field] = self._option(lay, title, desc, getattr(opts, field))
        lay.addWidget(QLabel("Mais opções", objectName="cardTitle"))
        for field, title, desc in EXTRA_OPTIONS:
            self.toggles[field] = self._option(lay, title, desc, getattr(opts, field))
        ll.addWidget(c)
        ll.addStretch()

        scroll = QScrollArea(widgetResizable=True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # content follows the column width
        left.setMinimumWidth(0)
        left.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        scroll.setWidget(left)
        scroll.setMinimumWidth(440)
        cols.addWidget(scroll, 5)

        # ---- right: actions + progress ----
        right = QVBoxLayout()
        right.setSpacing(16)
        c, lay = card()
        btns = QHBoxLayout()
        self.btn_run = QPushButton("Organizar", objectName="primary", cursor=Qt.PointingHandCursor)
        self.btn_preview = QPushButton("Pré-visualizar", cursor=Qt.PointingHandCursor)
        self.btn_preview.setToolTip("Mostra o que ia mudar, sem mexer em nada.")
        self.btn_cancel = QPushButton("Cancelar", objectName="danger", cursor=Qt.PointingHandCursor, enabled=False)
        self.btn_undo = QPushButton("Desfazer última", objectName="ghost", cursor=Qt.PointingHandCursor)
        self.btn_undo.setToolTip("Devolve os ficheiros movidos na última vez.")
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
        self.status = QLabel("Pronto.", objectName="hint")
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.bar)
        lay.addWidget(self.status)
        right.addWidget(c)

        c, lay = card("Progresso")
        self.rows = {}
        for field, title, _, names in STEPS:
            r = StepRow(title)
            lay.addWidget(r)
            for n in names:
                self.rows[n] = (field, r)
        self.step_rows = [(f, r) for f, r in dict((f, r) for f, r in self.rows.values()).items()]
        right.addWidget(c)

        c, lay = card("Resumo")
        self.stats_grid = QGridLayout()
        self.stats_grid.setHorizontalSpacing(24)
        lay.addLayout(self.stats_grid)
        self.log = QPlainTextEdit(readOnly=True, placeholderText="Os detalhes de cada execução aparecem aqui.")
        self.log.setMinimumHeight(140)
        lay.addWidget(self.log, 1)
        right.addWidget(c, 1)
        cols.addLayout(right, 6)

        self.setCentralWidget(root)
        self.reset_rows()

    # ---------- building blocks ----------

    def _secret(self, lay, label, value):
        lay.addWidget(QLabel(label, objectName="stepDesc"))
        row = QHBoxLayout()
        e = QLineEdit(value, echoMode=QLineEdit.Password)
        e.setAccessibleName(label)
        show = QPushButton("Mostrar", objectName="ghost", cursor=Qt.PointingHandCursor, checkable=True)
        show.toggled.connect(lambda on: (e.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password),
                                         show.setText("Esconder" if on else "Mostrar")))
        row.addWidget(e, 1)
        row.addWidget(show)
        lay.addLayout(row)
        return e

    def _option(self, lay, title, desc, checked):
        row = QHBoxLayout()
        text = QVBoxLayout()
        text.setSpacing(1)
        t = QLabel(title)
        d = QLabel(desc, objectName="stepDesc", wordWrap=True)
        text.addWidget(t)
        text.addWidget(d)
        tg = Toggle(checked)
        tg.setAccessibleName(title)
        t.setBuddy(tg)
        row.addLayout(text, 1)
        row.addWidget(tg, 0, Qt.AlignVCenter)
        lay.addLayout(row)
        return tg

    # ---------- actions ----------

    def show_help(self):
        from .ajuda import HELP, InfoDialog
        InfoDialog("Ajuda — Organizador de Música", HELP, self).exec()

    def show_about(self):
        from .ajuda import ABOUT, InfoDialog
        InfoDialog("Sobre", ABOUT, self, (540, 540)).exec()

    def pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Pasta das músicas", self.folder.text())
        if d:
            self.folder.setText(os.path.normpath(d))

    def current(self):
        opts = Options(root=self.folder.text().strip(), **{f: t.isChecked() for f, t in self.toggles.items()})
        keys = {"discogs_token": self.discogs.text().strip(), "lastfm_api_key": self.lastfm.text().strip()}
        config.save(opts, keys)
        return opts, keys

    def busy(self, on):
        for w in (self.btn_preview, self.btn_run, self.btn_undo, self.folder, *self.toggles.values()):
            w.setEnabled(not on)
        self.btn_cancel.setEnabled(on)

    def reset_rows(self, opts=None, kind="run"):
        for field, r in self.step_rows:
            enabled = field.startswith("_") or (opts is None or getattr(opts, field, True))
            if field == "write_tags" and opts is not None:
                enabled = opts.write_tags or opts.clean_sites
            if kind == "preview":
                enabled = field in ("_organize", "extract", "dedupe")
            r.set("espera" if enabled else "desligado")

    def start(self, kind, opts=None, keys=None):
        if opts is None:
            opts, keys = self.current()
        if not os.path.isdir(opts.root):
            QMessageBox.warning(self, "Biblioteca", "Escolhe a pasta das músicas.")
            self.folder.setFocus()
            return
        if kind == "run" and QMessageBox.question(
                self, "Organizar", f"Vai mover e renomear ficheiros em:\n{opts.root}\n\n"
                "O rekordbox / Serato tem de estar fechado. No fim faz 'Relocate' nele.\n\nContinuar?") != QMessageBox.Yes:
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
        label = {"preview": "Pré-visualizar", "run": "Organizar", "undo": "Desfazer"}[kind]
        self.log.appendPlainText(f"— {label}: {opts.root}")
        self.status.setText("A começar…")
        self.thread.start()

    def undo(self):
        opts, keys = self.current()
        if QMessageBox.question(self, "Desfazer", "Devolver os ficheiros movidos na última vez?\n"
                                "O que foi para a Reciclagem restaura-se pelo Windows.") == QMessageBox.Yes:
            self.start("undo", opts, keys)

    def do_cancel(self):
        self.cancel.set()
        self.btn_cancel.setEnabled(False)
        self.status.setText("A cancelar… (termina o ficheiro atual)")

    def on_progress(self, step, i, n, msg):
        self.bar.setMaximum(max(n, 1))
        self.bar.setValue(i)
        self.status.setText(f"{msg}" if msg else step)
        hit = self.rows.get(step)
        if hit:
            row = hit[1]
            if self.current_row is not None and self.current_row is not row:
                self.current_row.set("feito")
            self.current_row = row
            row.set("a correr", f"{i:,} / {n:,}".replace(",", " "))

    def on_finished(self, kind, rep, errs):
        self.busy(False)
        self.bar.setMaximum(1)
        self.bar.setValue(1)
        for _, r in self.step_rows:
            if r.state.text() not in ("desligado",):
                r.set("feito")
        self.status.setText("Pré-visualização pronta — nada foi alterado." if kind == "preview" else "Feito.")
        self.show_stats(rep)
        for k, v in sorted(rep.items(), key=lambda kv: -kv[1]):
            self.log.appendPlainText(f"{v:>7}  {k}")
        if errs:
            self.log.appendPlainText(f"Avisos ({len(errs)}):")
            for e in errs[:100]:
                self.log.appendPlainText(f"   {e}")
        if kind == "run":
            self.log.appendPlainText("No rekordbox: Ficheiro › Gerir faixas inexistentes › Auto Relocate; depois Recarregar tag.")

    def on_failed(self, msg):
        self.busy(False)
        if self.current_row is not None:
            self.current_row.set("erro", "parado")
        self.status.setText("Parado.")
        self.log.appendPlainText(msg)

    def clear_stats(self):
        while self.stats_grid.count():
            self.stats_grid.takeAt(0).widget().deleteLater()

    def show_stats(self, rep):
        def total(*words):
            return sum(v for k, v in rep.items() if any(w in k for w in words))
        stats = [("faixas", rep.get("faixas")), ("movidas", total("movidas", "a mover")),
                 ("repetidas", total("repetidas")), ("géneros online", total("online")),
                 ("tags corrigidas", total("tag", "sites"))]
        col = 0
        for label, v in stats:
            if not v:
                continue
            box = QVBoxLayout()
            val = QLabel(f"{v:,}".replace(",", " "), objectName="statValue")
            box.addWidget(val)
            box.addWidget(QLabel(label, objectName="statLabel"))
            w = QWidget()
            w.setLayout(box)
            self.stats_grid.addWidget(w, 0, col)
            col += 1


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS)
    w = Window()
    w.show()
    sys.exit(app.exec())
