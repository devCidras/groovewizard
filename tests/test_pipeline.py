"""End-to-end check on a temporary library of tiny WAV files. Run: python -m pytest tests  (or python tests/test_pipeline.py)"""
import os
import shutil
import sys
import tempfile
import wave
import zipfile

TMP = tempfile.mkdtemp(prefix="organizador-teste-")
os.environ["APPDATA"] = os.path.join(TMP, "appdata")  # keep caches/logs out of the real profile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mutagen.id3 import TALB, TCON, TIT2, TPE1  # noqa: E402
from mutagen.wave import WAVE  # noqa: E402

import organizador.pipeline as pl  # noqa: E402
from organizador.tags import genre_of, normalize_genre, raw_genre, strip_sites, title_key  # noqa: E402

trashed = []
pl.send2trash = lambda p: (trashed.append(p), os.remove(p))  # no real Recycle Bin in tests
pl.bpm_mod.librosa = None  # silence has no tempo; result must not depend on librosa being installed


def make(path, seconds=1, artist=None, title=None, genre=None, album=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(8000)
        w.writeframes(b"\0\0" * 8000 * seconds)
    f = WAVE(path)
    f.add_tags()
    for frame, v in ((TPE1, artist), (TIT2, title), (TCON, genre), (TALB, album)):
        if v:
            f.tags.add(frame(encoding=3, text=[v]))
    f.save()
    return path


def test_rules():
    assert normalize_genre("Afro House") == "House"
    assert normalize_genre("Techno (Peak Time / Driving)") == "Techno (Peak Time - Driving)"
    assert normalize_genre("https://electronicfresh.com") is None
    assert normalize_genre("Electronic") is None
    assert normalize_genre("Tech House, Deep House") == "Tech House"
    assert strip_sites("Rockin' (Extended Mix) - www.djsoundtop.com") == "Rockin' (Extended Mix)"
    assert strip_sites("djsoundtop.com") == ""
    assert strip_sites("Crazy (Extended Mix) [4DJsonline.com]") == "Crazy (Extended Mix)"
    assert strip_sites("https://electronicfresh.com") == ""
    for real in ("Love.me (Extended Mix)", "Back.to Life", "Toolroom Records", "Original Mix", "Kiss.Me", "Toolroom.Club"):
        assert strip_sites(real) == real, real
    assert title_key("Go Back feat. Julia (Extended Mix)") == title_key("Go Back (Original Mix)")
    assert title_key("Ocean (Marlon Hoffstadt Remix)") != title_key("Ocean")


def test_guards():
    assert pl.too_broad("C:\\") and pl.too_broad(os.path.expanduser("~"))
    assert not pl.too_broad(os.path.join(TMP, "musica"))
    assert pl.data_dir_for("C:\\DJ Sets") != pl.data_dir_for("C:\\DJ_Sets")
    from organizador.tags import artists_key
    assert artists_key("Кино") and artists_key("Кино") != artists_key("Ария")


def test_full_run_and_undo():
    root = os.path.join(TMP, "musica")
    make(os.path.join(root, "solta", "A - Groove (Original Mix).wav"), 1, "A", "Groove (Original Mix)", "Tech House, Deep House")
    make(os.path.join(root, "solta", "A - Groove (Extended Mix).wav"), 2, "A", "Groove (Extended Mix)", "Tech House")
    make(os.path.join(root, "B - Spam.wav"), 1, "B", "Spam", "https://djsoundtop.com", album="djsoundtop.com")
    make(os.path.join(root, "C - Afro.wav"), 1, "C", "Afro", "Afro House")
    pack = make(os.path.join(TMP, "pack", "D - Dark.wav"), 1, "D", "Dark")  # untagged, genre from pack name
    inner = os.path.join(TMP, "pack", "CD2.zip")
    with zipfile.ZipFile(inner, "w") as z:  # pack inside a pack
        z.write(make(os.path.join(TMP, "pack", "E - Deep.wav"), 1, "E", "Deep"), "E - Deep.wav")
    with zipfile.ZipFile(os.path.join(root, "Best New Hard Techno Nov.zip"), "w") as z:
        z.write(pack, "D - Dark.wav")
        z.write(inner, "CD2.zip")
        z.writestr("cover.txt", "x")
        z.writestr("bonus.ogg", "not handled")  # unknown format: must not be thrown away

    opts = pl.Options(root=root, online=False, bpm_folders=True)
    org = pl.Organizer(opts)
    assert org.preview()["archives_pending"] == 1
    rep, errs = org.run()
    assert not errs, errs

    house = os.path.join(root, "House")
    kept = os.path.join(house, "Tech House", "A - Groove (Extended Mix).wav")
    assert os.path.exists(kept)
    assert not os.path.exists(os.path.join(house, "Tech House", "A - Groove (Original Mix).wav"))  # duplicate gone
    assert raw_genre(kept) == "Tech House"
    afro = os.path.join(house, "House", "C - Afro.wav")
    assert raw_genre(afro) == "Afro House"  # specific tag kept, it belongs to this folder
    assert os.path.exists(os.path.join(root, "Techno", "Hard Techno", "D - Dark.wav"))
    assert os.path.exists(os.path.join(root, "Techno", "Hard Techno", "E - Deep.wav"))  # from the inner zip
    assert any(p.endswith("bonus.ogg") for p in map(str, __import__("pathlib").Path(root).rglob("*"))), "ogg kept"
    spam = os.path.join(root, "Sem Genero", "BPM desconhecido", "B - Spam.wav")
    assert os.path.exists(spam) and raw_genre(spam) == "" and "djsoundtop" not in str(WAVE(spam).tags.get("TALB"))
    assert not os.path.exists(os.path.join(root, "solta"))

    rep2, _ = pl.Organizer(opts).run()  # second run: nothing to move
    assert not any(k.startswith("moved") for k in rep2), rep2

    rep, errs = pl.undo_last(root)
    assert rep["undo_returned"] >= 1, rep
    rep, errs = pl.undo_last(root)  # undoes the first run (the second moved nothing so it has no log)
    assert os.path.exists(os.path.join(root, "B - Spam.wav"))
    assert genre_of(os.path.join(root, "C - Afro.wav")) == "House"


if __name__ == "__main__":
    try:
        test_rules()
        test_guards()
        test_full_run_and_undo()
        print("ok")
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
