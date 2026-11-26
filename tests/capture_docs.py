"""Regenerate README screenshots from real widgets and illustrative, offline data.

No music files, user settings, network service or installer are accessed. Run from
the repository root: ``python tests/capture_docs.py [output-directory]``.
"""

import atexit
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "windows"
os.environ["QT_SCALE_FACTOR"] = "1"
profile = tempfile.TemporaryDirectory(prefix="groovewizard-docs-")
atexit.register(profile.cleanup)
os.environ["APPDATA"] = profile.name
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from organizador import biblioteca, config, radar
from organizador.ajuda import InfoDialog, TermsDialog, help_html
from organizador import gui
from organizador.gui import Window
from organizador.dj_ui import ReviewDialog, SetDialog, TrackHistoryDialog
from organizador.i18n import set_lang, t
from organizador.janelas import HistoryDialog, PlanDialog
from organizador.pipeline import DuplicateTrack, HistoryEntry, LibrarySnapshot, Options
from organizador.theme import QSS


OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "docs").resolve()
OUT.mkdir(parents=True, exist_ok=True)
ROOT = r"D:\musica"  # display text only; never read or written


def screenshot(widget, filename):
    widget.setAttribute(Qt.WA_DontShowOnScreen)
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
for tab, filename in ((1, "11-opcoes.png"), (2, "12-fontes-online.png"), (3, "13-ferramentas.png"),
                      (4, "14-biblioteca-dj.png")):
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
next_patch = gui.__version__.rsplit(".", 1)
example_version = f"{next_patch[0]}.{int(next_patch[1]) + 1}"
w._show_update({"version": example_version, "installer": "https://example.invalid/setup.exe",
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


def demo_track(relative, artist, title, genre, bpm, seconds, mib, problems=()):
    return biblioteca.Track(str(Path(ROOT, relative)), artist, title, genre, bpm, seconds,
                            (mib * 1048576, 1), problems, artist, title, genre)


opts = Options(root=ROOT)
kept = demo_track(r"House\Nora Vale - Maré Alta (Extended Mix).flac",
                  "Nora Vale", "Maré Alta (Extended Mix)", "House", 124, 382, 42)
incoming = demo_track(r"_entrada\Pack de sexta\03 - Maré Alta (Extended).flac",
                      kept.artist, kept.title, kept.genre, kept.bpm, kept.duration, 42)
club = demo_track(r"House\Eco Modular - Linha de Água (Club Mix).mp3",
                  "Eco Modular", "Linha de Água (Club Mix)", "House", 126, 348, 14)
radio = demo_track(r"_entrada\Linha de Água (Radio Edit).mp3",
                   "Eco Modular", "Linha de Água (Radio Edit)", "House", 126, 189, 8)
tracks = [incoming, kept, radio, club,
          demo_track(r"_entrada\Lia Norte - Azul.wav", "Lia Norte", "Azul", "", 122, 315, 51,
                     ("report_no_genre",)),
          demo_track(r"_entrada\07 Demo.mp3", "", "07 Demo", "", None, 254, 10,
                     ("report_no_artist_title", "report_no_genre")),
          demo_track(r"_entrada\Ficheiro incompleto.mp3", "", "Ficheiro incompleto", "", None, 0, 0,
                     ("report_unreadable",)),
          demo_track(r"House\Lia Norte - Farol.flac", "Lia Norte", "Farol", "House", 123, 297, 32),
          demo_track(r"House\Nora Vale - Cais 7.flac", "Nora Vale", "Cais 7", "House", 125, 336, 37)]
catalogue = {track.path: track for track in tracks}
duplicates = {incoming.path: kept.path, radio.path: club.path}
details = {t.path: DuplicateTrack(version, t.duration, checksum, True) for t, version, checksum in (
    (incoming, "Extended Mix", b"a"), (kept, "Extended Mix", b"a"),
    (radio, "Radio Edit", b"b"), (club, "Club Mix", b"c"))}
playlists = {"xml": "colecao-de-exemplo.xml", "tracks": {
    biblioteca.playlist_path(incoming.path): [],
    biblioteca.playlist_path(kept.path): ["Warm-up", "Sexta", "Sunset"]}}

dialog = ReviewDialog(opts, (catalogue, duplicates, details, LibrarySnapshot(frozenset())))
dialog.table.setCurrentCell(0, 1)
dialog.table.setColumnWidth(0, 330)
dialog.resize(1100, 380)
screenshot(dialog, "15-por-rever.png")

with patch("organizador.janelas.saved_map", return_value=playlists):
    dialog = PlanDialog([("dup", path, keeper) for path, keeper in duplicates.items()], ROOT,
                        details=details, quarantine_only=True)
dialog.table.setCurrentCell(0, 1)
dialog.resize(1100, 470)
screenshot(dialog, "16-comparar-repetidas.png")

run = "20261125-191500-100-1"
quarantine = str(Path(ROOT, "_quarentena", run, Path(incoming.path).relative_to(ROOT)))
before = str(Path(ROOT, "_entrada", "Pack de sexta", "03 - Demo.flac"))
events = [
    HistoryEntry(run, 2, incoming.path, quarantine, "quarentena", "done", True),
    HistoryEntry(run, 1, before, incoming.path, "rename", "done", False),
    HistoryEntry("20261121-183000-1-1", 0, kept.path, kept.path, "tags", "done", False),
]
dialog = TrackHistoryDialog(opts, events)
dialog.search.setText("Maré Alta")
dialog.table.setCurrentCell(0, 1)
dialog.table.setColumnWidth(1, 180)
dialog.resize(1180, 370)
screenshot(dialog, "17-historico-musica.png")

with patch.object(biblioteca, "saved_map", return_value=playlists):
    dialog = SetDialog(opts, tracks)
dialog.genre.setCurrentText("House")
dialog.min_bpm.setValue(122)
dialog.max_bpm.setValue(126)
for selected in (tracks[7], kept, club):
    dialog.table.item(tracks.index(selected), 0).setCheckState(Qt.Checked)
dialog.table.setCurrentCell(tracks.index(kept), 1)
dialog.resize(1040, 445)
screenshot(dialog, "18-preparar-set.png")

w = window()
source = "Exemplo"
updated = datetime(2026, 11, 25, 19, 15).timestamp()
headlines = [
    "Nora Vale apresenta o EP Maré Alta no Porto",
    "Eco Modular partilha um novo set gravado ao pôr do sol",
    "Lia Norte reúne três remisturas de Farol",
    "Workshop em Lisboa explora a mistura harmónica",
    "Como preparar playlists para um set de abertura",
]
articles = [{"title": title, "text": radar.words(title), "source": source, "date": int(updated - i * 3600),
             "url": f"https://example.invalid/noticias/{i}", "groups": []} for i, title in enumerate(headlines)]
w.radar.library_key = ROOT, tuple()
w.radar.index_ready((w.radar.library_key, w.radar.generation, catalogue, radar.artist_index(tracks)))
w.radar.news_ready(({source: {"updated": updated, "articles": articles}}, []))
with patch.object(w.radar, "refresh", return_value=None):
    w.tabs.setCurrentWidget(w.radar)
    screenshot(w, "19-radar-dj.png")
print(f"Saved screenshots to {OUT}")
