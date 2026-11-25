"""Regenerate README screenshots from real widgets and illustrative, offline data.

No music files, user settings, network service or installer are accessed. Run from
the repository root: ``python tests/capture_docs.py [output-directory]``.
"""

import atexit
import os
import sys
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "windows"
os.environ["QT_SCALE_FACTOR"] = "1"
profile = tempfile.TemporaryDirectory(prefix="groovewizard-docs-")
atexit.register(profile.cleanup)
os.environ["APPDATA"] = profile.name
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from organizador import config
from organizador.ajuda import InfoDialog, TermsDialog, help_html
from organizador import gui
from organizador.gui import Window
from organizador.i18n import set_lang, t
from organizador.janelas import HistoryDialog, PlanDialog
from organizador.pipeline import Options
from organizador.theme import QSS


OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "docs").resolve()
OUT.mkdir(parents=True, exist_ok=True)
ROOT = r"D:\musica"  # display text only; never read or written


def screenshot(widget, filename):
    widget.show()
    app.processEvents()
    image = widget.grab()
    if not image.save(str(OUT / filename)):
        raise OSError(f"could not save {filename}")
    widget.close()


def window(language="pt"):
    set_lang(language)
    w = Window()
    w.resize(1100, 760)
    return w


def running(w):
    w.busy(True)
    w.rows["extract"].set("done")
    w.rows["organize"].set("done")
    w.rows["dedupe_scan"].set("running", "812 / 1 340")
    w.rows["covers"].set("off")
    w.bar.setMaximum(1340)
    w.bar.setValue(812)
    w.status.setText("Tech House / Fisher - Losing It (Extended Mix).mp3")
    w.log.setPlainText("5 packs extraídos para _entrada\n1340 faixas encontradas")


def finished(w):
    for _, row in w.step_rows:
        row.set("off" if row is w.rows["covers"] else "done")
    w.bar.setMaximum(1)
    w.bar.setValue(1)
    w.status.setText(t("status.done"))
    w.show_stats({"tracks": 1340, "moved": 982, "dups_trashed": 431,
                  "online": 167, "genre_tag_fixed": 1830})
    w.log.setPlainText("5 packs extraídos\n1340 faixas encontradas\n982 faixas movidas\n431 repetidas na quarentena")


app = QApplication([])
app.setStyleSheet(QSS)
config.load = lambda: (Options(root=ROOT, protected=[ROOT + r"\Os Meus Edits"]), {})
gui.has_completed_full_run = lambda _root: True  # screenshot text only: never probe D:\musica

screenshot(window(), "1-principal.png")
for tab, filename in ((1, "11-opcoes.png"), (2, "12-fontes-online.png"), (3, "13-ferramentas.png")):
    w = window()
    w.tabs.setCurrentIndex(tab)
    screenshot(w, filename)
w = window()
running(w)
screenshot(w, "2-a-organizar.png")
w = window()
finished(w)
screenshot(w, "3-resumo.png")

set_lang("pt")
help_dialog = InfoDialog(t("btn.help"), help_html())
help_dialog.resize(720, 760)
screenshot(help_dialog, "4-ajuda.png")

set_lang("en")
terms = TermsDialog()
screenshot(terms, "5-termos-en.png")

w = window()
w._show_update({"version": "1.9.0", "installer": "https://example.invalid/setup.exe",
                "sha256": "0" * 64, "page": "https://example.invalid"})
screenshot(w, "6-atualizacao.png")
screenshot(window("en"), "7-english.png")

set_lang("pt")
track = ROOT + r"\_entrada\Beatport Top 100 Tech House\01 fisher-losing_it-ext.mp3"
plan = [
    ("move", track, ROOT + r"\House\Tech House\Fisher - Losing It (Extended Mix).mp3"),
    ("tags", track, "Tech House"),
    ("move", ROOT + r"\_entrada\Melodic Selection\Anyma - Eternity.mp3",
     ROOT + r"\Melodic & Indie\Melodic House & Techno\Anyma - Eternity.mp3"),
    ("move", ROOT + r"\solta\Amelie Lens - Feel It.wav",
     ROOT + r"\Techno\Techno (Peak Time - Driving)\Amelie Lens - Feel It.wav"),
    ("dup", ROOT + r"\solta\Amelie Lens - Feel It (Radio Edit).mp3",
     ROOT + r"\solta\Amelie Lens - Feel It.wav"),
    ("site_name", ROOT + r"\House\Tech House\John Summit - Where You Are (Extended).mp3",
     "John Summit - Where You Are (Extended Mix).mp3"),
    ("rename_ask", ROOT + r"\Chris Lake - Turn Off The Lights.mp3",
     "Chris Lake, Alexis Roberts - Turn Off The Lights (Extended Mix).mp3"),
    ("tags", ROOT + r"\House\House\Dom Dolla - Girl$.flac", "House"),
]
dialog = PlanDialog(plan, ROOT)
dialog.resize(1100, 560)
dialog.table.item(4, 0).setCheckState(Qt.Unchecked)
screenshot(dialog, "8-lista.png")

runs = [
    ("20261124-210500-1-1", {"mover": 1340, "quarentena": 431, "tags": 1830, "extraido": 5}),
    ("20261121-183000-1-1", {"mover": 212, "tags": 198}),
    ("20261118-221500-1-1", {"mover": 87, "quarentena": 12, "extraido": 2}),
]
screenshot(HistoryDialog(runs), "9-desfazer.png")
w = window()
w.scope_options["covers_all"] = True  # illustrate selecting only missing covers for old tracks
dialog, _ = w._old_scope_dialog()
screenshot(dialog, "10-antigas.png")
w.close()
print(f"Saved screenshots to {OUT}")
