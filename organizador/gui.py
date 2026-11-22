"""Window: pick the music folder, paste API keys, choose options, Organize / Preview / Undo with progress."""
import os
import sys
import threading
import traceback

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (QApplication, QCheckBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
                               QVBoxLayout, QWidget)

from . import __version__, config
from .pipeline import Cancelled, Organizer, undo_last

OPTIONS = [  # (Options field, label, tooltip)
    ("extract", "Extrair .zip / .rar / .7z", "Packs descarregados sao extraidos e as faixas arrumadas. O .rar e .7z precisam do 7-Zip."),
    ("delete_archives", "Enviar os compactados para a Reciclagem depois de extrair", ""),
    ("dedupe", "Remover repetidas (fica a Extended / a mais longa)", "As outras vao para a Reciclagem."),
    ("online", "Procurar online o genero das faixas sem genero", "Discogs e Last.fm (precisam de chave gratis)."),
    ("musicbrainz", "Usar tambem o MusicBrainz (lento: 1 pedido por segundo)", ""),
    ("write_tags", "Gravar o genero na tag de cada faixa", "Para o rekordbox / Serato mostrarem o genero certo."),
    ("clean_sites", "Tirar nomes de sites das tags (album, titulo, comentario...)", "Ex.: 'djsoundtop.com' no Album."),
    ("bpm_folders", "Separar 'Sem Genero' e 'Outros' por BPM", "Usa o BPM da tag; mede o audio se o librosa estiver instalado."),
    ("families", "Agrupar em pastas-mae (House, Techno, ...)", "House/Tech House, Techno/Hard Techno, ..."),
]


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
            self.failed.emit("Cancelado. O que ja foi feito fica feito e pode ser desfeito.")
        except Exception:
            self.failed.emit(traceback.format_exc())


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Organizador de Musica {__version__}")
        self.resize(760, 680)
        opts, keys = config.load()

        self.folder = QLineEdit(opts.root)
        pick = QPushButton("Escolher...")
        pick.clicked.connect(self.pick_folder)
        row = QHBoxLayout()
        row.addWidget(self.folder)
        row.addWidget(pick)

        self.discogs = QLineEdit(keys.get("discogs_token", ""))
        self.lastfm = QLineEdit(keys.get("lastfm_api_key", ""))
        for w in (self.discogs, self.lastfm):
            w.setEchoMode(QLineEdit.Password)
        keys_box = QGroupBox("Chaves de API (gratis, ficam so neste PC)")
        form = QFormLayout(keys_box)
        form.addRow("Discogs token:", self.discogs)
        form.addRow("Last.fm API key:", self.lastfm)
        form.addRow(QLabel('<a href="https://www.discogs.com/settings/developers">Criar token Discogs</a> · '
                           '<a href="https://www.last.fm/api/account/create">Criar chave Last.fm</a>',
                           openExternalLinks=True))

        opt_box = QGroupBox("O que fazer")
        ol = QVBoxLayout(opt_box)
        self.checks = {}
        for field, label, tip in OPTIONS:
            cb = QCheckBox(label, checked=getattr(opts, field))
            cb.setToolTip(tip)
            self.checks[field] = cb
            ol.addWidget(cb)

        self.btn_preview = QPushButton("Pre-visualizar")
        self.btn_run = QPushButton("Organizar")
        self.btn_run.setStyleSheet("font-weight: bold; padding: 6px 18px;")
        self.btn_cancel = QPushButton("Cancelar", enabled=False)
        self.btn_undo = QPushButton("Desfazer ultima")
        self.btn_preview.clicked.connect(lambda: self.start("preview"))
        self.btn_run.clicked.connect(lambda: self.start("run"))
        self.btn_undo.clicked.connect(self.undo)
        self.btn_cancel.clicked.connect(self.do_cancel)
        buttons = QHBoxLayout()
        for b in (self.btn_preview, self.btn_run, self.btn_cancel):
            buttons.addWidget(b)
        buttons.addStretch()
        buttons.addWidget(self.btn_undo)

        self.bar = QProgressBar()
        self.status = QLabel("Pronto.")
        self.log = QPlainTextEdit(readOnly=True)

        lay = QVBoxLayout()
        lay.addWidget(QLabel("Pasta das musicas:"))
        lay.addLayout(row)
        lay.addWidget(keys_box)
        lay.addWidget(opt_box)
        lay.addLayout(buttons)
        lay.addWidget(self.bar)
        lay.addWidget(self.status)
        lay.addWidget(self.log, 1)
        central = QWidget()
        central.setLayout(lay)
        self.setCentralWidget(central)
        self.thread = None

    def pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Pasta das musicas", self.folder.text())
        if d:
            self.folder.setText(os.path.normpath(d))

    def current(self):
        from .pipeline import Options
        opts = Options(root=self.folder.text().strip(), **{f: cb.isChecked() for f, cb in self.checks.items()})
        keys = {"discogs_token": self.discogs.text().strip(), "lastfm_api_key": self.lastfm.text().strip()}
        config.save(opts, keys)
        return opts, keys

    def busy(self, on):
        for b in (self.btn_preview, self.btn_run, self.btn_undo):
            b.setEnabled(not on)
        self.btn_cancel.setEnabled(on)

    def start(self, kind, opts=None, keys=None):
        if opts is None:
            opts, keys = self.current()
        if not os.path.isdir(opts.root):
            QMessageBox.warning(self, "Pasta", "Escolhe a pasta das musicas.")
            return
        if kind == "run" and QMessageBox.question(
                self, "Organizar", f"Vai mover e renomear ficheiros em:\n{opts.root}\n\n"
                "Fecha o rekordbox / Serato antes. No fim faz 'Relocate' nele.\nContinuar?") != QMessageBox.Yes:
            return
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
        self.log.appendPlainText(f"--- {dict(preview='Pre-visualizar', run='Organizar', undo='Desfazer')[kind]}: {opts.root}")
        self.thread.start()

    def undo(self):
        opts, keys = self.current()
        if QMessageBox.question(self, "Desfazer", "Devolver os ficheiros movidos na ultima vez?") == QMessageBox.Yes:
            self.start("undo", opts, keys)

    def do_cancel(self):
        self.cancel.set()
        self.status.setText("A cancelar...")

    def on_progress(self, step, i, n, msg):
        self.bar.setMaximum(max(n, 1))
        self.bar.setValue(i)
        self.status.setText(f"{step}: {i}/{n}  {msg}")

    def on_finished(self, kind, rep, errs):
        self.busy(False)
        self.bar.setValue(self.bar.maximum())
        self.status.setText("Pre-visualizacao pronta (nada foi alterado)." if kind == "preview" else "Feito.")
        for k, v in sorted(rep.items(), key=lambda kv: -kv[1]):
            self.log.appendPlainText(f"  {v:>6}  {k}")
        if errs:
            self.log.appendPlainText(f"  Avisos/erros ({len(errs)}):")
            for e in errs[:50]:
                self.log.appendPlainText(f"    {e}")
        if kind == "run":
            self.log.appendPlainText("  No rekordbox: Ficheiro > Gerir faixas inexistentes > Auto Relocate; depois Recarregar tag.")

    def on_failed(self, msg):
        self.busy(False)
        self.status.setText("Parado.")
        self.log.appendPlainText(msg)


def main():
    app = QApplication(sys.argv)
    w = Window()
    w.show()
    sys.exit(app.exec())
