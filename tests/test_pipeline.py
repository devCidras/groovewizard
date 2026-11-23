"""End-to-end check on a temporary library of tiny WAV files. Run: python -m pytest tests  (or python tests/test_pipeline.py)"""
import os
import shutil
import sys
import tempfile
import wave
import zipfile

TMP = tempfile.mkdtemp(prefix="organizador-teste-")
os.environ["APPDATA"] = os.path.join(TMP, "appdata")  # keep caches/logs out of the real profile
os.environ["LOCALAPPDATA"] = os.path.join(TMP, "localappdata")  # %TEMP% lives under it; libraries there are refused
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
    assert pl.too_broad(os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Media"))  # inside a system folder
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

    broken = os.path.join(root, "Techno", "Techno", "broken.mp3")  # unreadable tags inside a genre folder
    os.makedirs(os.path.dirname(broken))
    open(broken, "wb").write(b"not really audio")

    opts = pl.Options(root=root, online=False, bpm_folders=True)
    org = pl.Organizer(opts)
    assert org.preview()["archives_pending"] == 1
    assert not os.path.exists(os.path.join(root, pl.QUARANTINE)) and os.path.exists(os.path.join(root, "solta")), "preview changed files"
    rep, errs = org.run()
    assert os.path.exists(broken), "unreadable file must stay where it is"
    errs = [e for e in errs if "broken.mp3" not in e]
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

    assert os.path.isdir(os.path.join(root, pl.QUARANTINE))  # the duplicate is kept there, not deleted

    rep, errs = pl.undo_last(root)  # the second run changed nothing, so this undoes the first
    assert not errs, errs
    assert rep["undo_returned"] >= 1 and rep["undo_from_quarantine"] >= 1 and rep["undo_tags"] >= 1, rep
    assert os.path.exists(os.path.join(root, "solta", "A - Groove (Original Mix).wav"))  # duplicate is back
    b = os.path.join(root, "B - Spam.wav")
    assert raw_genre(b) == "https://djsoundtop.com" and "djsoundtop" in str(WAVE(b).tags.get("TALB"))  # tags restored
    assert genre_of(os.path.join(root, "C - Afro.wav")) == "House"
    # only the undone pack extraction may remain in quarantine (put aside whole); nothing else
    left = [os.path.relpath(os.path.join(dp, f), root) for dp, _, fs in os.walk(os.path.join(root, pl.QUARANTINE))
            for f in fs if f != pl.QUARANTINE_MARK]
    assert left and all("_extracoes_desfeitas" in f for f in left), left
    assert rep["undo_extract"] >= 1 and not os.path.exists(os.path.join(root, pl.INBOX))  # extraction put aside
    assert pl.Organizer(opts).preview()["archives_pending"] == 1  # the pack would be extracted again
    assert pl.undo_last(root)[0]["undo_nothing"] == 1


def test_rename_packs():
    root = os.path.join(TMP, "ren")
    loose = make(os.path.join(root, "solta", "x_minha.wav"), 1, "A", "Mine", "Tech House")  # already in the library
    taken = make(os.path.join(root, "House", "Tech House", "C - Taken.wav"), 3, "Z", "Other", "Tech House")
    src = os.path.join(TMP, "renpack")
    files = [make(os.path.join(src, "01-fisher-losing_it_(extended_mix)-tr.wav"), 1, "Fisher", "Losing It", "Tech House"),
             make(os.path.join(src, "02 - sem tags.wav"), 1, None, None, "Tech House"),
             make(os.path.join(src, "03-c-taken.wav"), 1, "C", "Taken", "Tech House"),  # name already used there
             make(os.path.join(src, "04 - x.wav"), 1, "AC/DC", "What? Now", "Tech House")]
    with zipfile.ZipFile(os.path.join(root, "pack.zip"), "w") as z:
        for f in files:
            z.write(f, os.path.basename(f))
    make(os.path.join(root, pl.INBOX, "solta nova.wav"), 1, "Bob", "New One (Club Mix)", "Tech House")  # loose, not a pack
    opts = pl.Options(root=root, online=False, bpm_folders=False, dedupe=False, rename_packs=True)
    rep, errs = pl.Organizer(opts).run()
    assert not errs, errs
    th = os.path.join(root, "House", "Tech House")
    names = sorted(os.listdir(th))
    assert "Fisher - Losing It (Extended Mix).wav" in names, names
    assert "AC DC - What Now.wav" in names, names
    assert "Bob - New One (Club Mix).wav" in names, names
    assert "02 - sem tags.wav" in names and "03-c-taken.wav" in names, names  # unsure / taken: original name
    assert "x_minha.wav" in names, "a track already in the library is never renamed"
    assert rep["renamed"] == 3, rep
    assert os.path.exists(taken)
    rep, errs = pl.undo_last(root)
    assert not errs, errs
    assert os.path.exists(loose) and not os.path.exists(os.path.join(th, "Fisher - Losing It (Extended Mix).wav"))
    # default: off
    assert pl.Options().rename_packs is False

    # the Extended only said so in its old name: renaming must not make it lose against the Original
    root = os.path.join(TMP, "ren2")
    make(os.path.join(root, "House", "Tech House", "A - Track (Original Mix).wav"), 2, "A", "Track", "Tech House")
    make(os.path.join(root, pl.INBOX, "a-track-extended_mix.wav"), 2, "A", "Track", "Tech House")
    make(os.path.join(root, pl.INBOX, "b-song-extended.wav"), 1, "B", "Song", "Tech House")  # no way to carry it
    org = pl.Organizer(pl.Options(root=root, online=False, bpm_folders=False, rename_packs=True))
    assert org.preview()["rename_pending"] == 1
    rep, errs = org.run()
    assert not errs, errs
    names = sorted(os.listdir(os.path.join(root, "House", "Tech House")))
    assert names == ["A - Track (Extended Mix).wav", "b-song-extended.wav"], names
    # preview and run agree when the new name is taken
    root = os.path.join(TMP, "ren3")
    make(os.path.join(root, "House", "Tech House", "fisher - losing it.wav"), 3, "X", "Y", "Tech House")
    make(os.path.join(root, pl.INBOX, "01.wav"), 1, "Fisher", "Losing It", "Tech House")
    org = pl.Organizer(pl.Options(root=root, online=False, bpm_folders=False, dedupe=False, rename_packs=True))
    assert "rename_pending" not in org.preview()
    assert org.run()[0]["renamed"] == 0
    # two new tracks wanting the same name: preview counts one, like the run
    root = os.path.join(TMP, "ren4")
    make(os.path.join(root, pl.INBOX, "x1.wav"), 1, "Q", "Same", "Tech House")
    make(os.path.join(root, pl.INBOX, "x2.mp3".replace(".mp3", ".wav")), 3, "Q", "Same", "Tech House")
    org = pl.Organizer(pl.Options(root=root, online=False, bpm_folders=False, dedupe=False, rename_packs=True))
    assert org.preview()["rename_pending"] == 1
    assert org.run()[0]["renamed"] == 1


def test_new_tracks_outside_inbox():
    root = os.path.join(TMP, "inv")
    th = os.path.join(root, "House", "Tech House")
    old = make(os.path.join(th, "old one.wav"), 2, "Old", "One", "Tech House")
    make(os.path.join(root, "antes.wav"), 3, "Pre", "Existing", "Tech House")  # there before the 1st run
    opts = pl.Options(root=root, online=False, bpm_folders=False, dedupe=False, write_tags=False, clean_sites=False,
                      rename_packs=True)
    asked = []
    yes = lambda items: asked.append(items) or True

    def cancel(items):
        raise pl.Cancelled()

    pl.Organizer(opts, ask_rename=yes).run()
    assert not asked, "first run: nothing outside _entrada counts as new"
    assert os.path.exists(os.path.join(th, "antes.wav"))

    make(os.path.join(root, "nova.wav"), 1, "Fisher", "Losing It (Extended Mix)", "Tech House")  # new, loose in root
    make(os.path.join(th, "ja no sitio.wav"), 4, "Bob", "Placed", "Tech House")  # new, already in the right folder
    os.rename(old, os.path.join(root, "movida a mao.wav"))  # known track moved by hand: same size, not new
    assert pl.Organizer(opts).preview()["rename_ask"] == 2

    try:  # stopped while the question is open: the new tracks stay new
        pl.Organizer(opts, ask_rename=cancel).run()
        raise AssertionError("expected Cancelled")
    except pl.Cancelled:
        pass
    assert pl.Organizer(opts).preview()["rename_ask"] == 2
    pl.undo_last(root)  # undoing never makes known tracks new (antes.wav goes back to the root)
    assert os.path.exists(os.path.join(root, "antes.wav"))
    assert pl.Organizer(opts).preview()["rename_ask"] == 2

    rep, errs = pl.Organizer(opts, ask_rename=yes).run()
    assert not errs, errs
    assert len(asked) == 1 and len(asked[0]) == 2, asked
    assert sorted(os.listdir(th)) == ["Bob - Placed.wav", "Fisher - Losing It (Extended Mix).wav", "antes.wav",
                                      "movida a mao.wav"], os.listdir(th)
    assert rep["renamed"] == 2, rep
    assert not pl.Organizer(opts).preview().get("rename_ask"), "renamed tracks are known now"
    rep, errs = pl.undo_last(root)
    assert not errs and os.path.exists(os.path.join(root, "nova.wav")) and os.path.exists(os.path.join(th, "ja no sitio.wav"))

    # same new name wanted by a track in _entrada and one outside: one plan, preview = run
    make(os.path.join(root, pl.INBOX, "a.wav"), 6, "Zed", "Same", "Tech House")
    make(os.path.join(root, "b.wav"), 7, "Zed", "Same", "Tech House")
    prev = pl.Organizer(opts).preview()
    assert prev["rename_pending"] == 1 and not prev.get("rename_ask"), prev
    rep, _ = pl.Organizer(opts, ask_rename=yes).run()
    assert rep["renamed"] == 1 and os.path.exists(os.path.join(th, "Zed - Same.wav")) and os.path.exists(os.path.join(th, "b.wav"))

    # a track that arrives while a run is going is not taken as known
    late = os.path.join(root, "chegou tarde.wav")
    org = pl.Organizer(opts, ask_rename=yes)
    org.step_bpm = lambda: make(late, 8, "Late", "Comer", "Tech House")  # runs after organize
    org.opts.bpm_folders = True
    org.run()
    org.opts.bpm_folders = False
    assert pl.Organizer(opts).preview()["rename_ask"] == 1

    make(os.path.join(root, "outra.wav"), 5, "Ann", "Other", "Tech House")
    rep, errs = pl.Organizer(opts, ask_rename=lambda items: False).run()  # "No": kept, and never asked again
    assert not errs and not rep["renamed"] and os.path.exists(os.path.join(th, "outra.wav")), (rep, errs)
    assert not pl.Organizer(opts).preview().get("rename_ask")


def test_quarantine_ownership():
    root = os.path.join(TMP, "qown")
    user_q = os.path.join(root, pl.QUARANTINE)
    make(os.path.join(user_q, "minha faixa.wav"), 1, "X", "Mine")  # a user folder that happens to have this name
    os.utime(user_q, (0, 0))
    assert pl.purge_quarantine(root, 0) == 0 and os.path.exists(os.path.join(user_q, "minha faixa.wav"))
    # made by a version before the mark: only run folders, each with its log in our data dir -> adopted
    root = os.path.join(TMP, "qold")
    run = "20261123-020440-17508-320412300"
    make(os.path.join(root, pl.QUARANTINE, run, "pack.wav"), 1, "X", "Y")
    logs = os.path.join(pl.data_dir_for(root), "execucoes")
    os.makedirs(logs, exist_ok=True)
    assert not pl._owns_quarantine(root)  # no log yet: could be the user's
    open(os.path.join(logs, run + ".csv"), "w").close()
    assert not pl._owns_quarantine(root)  # a log alone proves nothing: it must show a move into that folder
    import csv
    with open(os.path.join(logs, run + ".csv"), "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerow(["quarentena", os.path.join(root, "pack.wav"),
                                 os.path.join(root, pl.QUARANTINE, run, "pack.wav")])
    os.makedirs(os.path.join(root, pl.QUARANTINE, "minhas coisas"))
    assert not pl._owns_quarantine(root)  # something that is not a run folder: the user's
    os.rmdir(os.path.join(root, pl.QUARANTINE, "minhas coisas"))
    assert pl._owns_quarantine(root) and os.path.exists(os.path.join(root, pl.QUARANTINE, pl.QUARANTINE_MARK))
    from organizador.tags import normalize_genre
    assert normalize_genre("_quarentena") is None and normalize_genre("_Entrada") is None


def test_lock():
    root = os.path.join(TMP, "lock")
    os.makedirs(root)
    with pl.library_lock(root):
        try:
            with pl.library_lock(root):
                raise AssertionError("second lock should fail")
        except pl.Busy:
            pass
    with pl.library_lock(root):  # free again
        pass


def test_duplicate_rules():
    root = os.path.join(TMP, "dups")
    good = make(os.path.join(root, "A - Song (Original Mix).wav"), 1, "A", "Song (Original Mix)", "House")
    broken = os.path.join(root, "A - Song (Original Mix).mp3")
    open(broken, "wb").write(b"damaged")  # unreadable: never chosen as the copy to remove
    long_ = make(os.path.join(root, "B - Other (Original Mix).wav"), 1, "B", "Other (Original Mix)")
    short = make(os.path.join(root, "B - Other (Original Mix) (1).wav"), 20, "B", "Other (Original Mix)")
    ext = make(os.path.join(root, "C - Tune (Extended Mix).wav"), 3, "C", "Tune (Extended Mix)")
    radio = make(os.path.join(root, "C - Tune (Radio Edit).wav"), 1, "C", "Tune (Radio Edit)")
    remix = make(os.path.join(root, "C - Tune (Bob Remix).wav"), 1, "C", "Tune")  # generic tag title, remix in name
    org = pl.Organizer(pl.Options(root=root))
    from organizador.tags import read_info
    losers = org.find_duplicates({p: read_info(p) for p in (good, broken, long_, short, ext, radio, remix)})
    assert broken not in losers and good not in losers
    assert long_ not in losers and short not in losers  # same version, 1 s vs 20 s: different recordings
    assert losers == [radio], losers  # radio edit goes, extended stays, the remix is another track


def test_update_versions():
    from organizador import atualizacoes as a
    assert a.newer("v1.0.10", "1.0.9") and a.newer("2.0.0", "1.9.9")
    assert not a.newer("v1.0.7", "1.0.7") and not a.newer("1.0.6", "1.0.7") and not a.newer("", "1.0.7")
    for url, sha in (("https://evil.example.com/x.exe", "0" * 64), ("https://github.com/x/setup.exe", None)):
        try:
            a.download(url, sha)
            raise AssertionError("must refuse: not GitHub, or nothing to verify against")
        except ValueError:
            pass


def test_versions_option():
    assert title_key("Song (Radio Edit)") == title_key("Song (Extended Mix)")
    assert title_key("Song (Radio Edit)", False) != title_key("Song (Extended Mix)", False)
    assert title_key("Song (Original Mix)", False) == title_key("Song (Extended Mix)", False)


def test_protected_and_skip():
    root = os.path.join(TMP, "prot")
    mine = os.path.join(root, "Os Meus Edits")
    edit = make(os.path.join(mine, "A - Song (Original Mix).wav"), 1, "A", "Song (Original Mix)", "Tech House")
    spam = make(os.path.join(mine, "B - X.wav"), 1, "B", "X", "https://site.com")
    make(os.path.join(root, "A - Song (Extended Mix).wav"), 2, "A", "Song (Extended Mix)", "Tech House")
    untick = make(os.path.join(root, "C - Y.wav"), 1, "C", "Y", "Techno")
    opts = pl.Options(root=root, online=False, bpm_folders=False,
                      protected=[mine, root, r"C:\fora", os.path.join(root, pl.INBOX, "x"), os.path.join(root, pl.QUARANTINE)])
    org = pl.Organizer(opts, skip=[untick])
    assert org._protected == {os.path.normcase(mine)}  # the library, outside it, _entrada and _quarentena are ignored
    org.preview()
    assert not any(p in (edit, spam, untick) for _, p, _ in org.plan), org.plan
    rep, errs = pl.Organizer(opts, skip=[untick]).run()
    assert not errs, errs
    assert os.path.exists(edit) and os.path.exists(spam) and raw_genre(spam) == "https://site.com"  # not touched
    assert os.path.exists(untick)  # unticked in the list: stays where it is
    assert os.path.exists(os.path.join(root, "House", "Tech House", "A - Song (Extended Mix).wav"))
    assert "dups_trashed" not in rep  # the protected copy is not compared, never removed

    # a protected target folder: nothing is moved into it
    techno = os.path.join(root, "Techno")
    os.makedirs(techno, exist_ok=True)
    new = make(os.path.join(root, "D - Z.wav"), 1, "D", "Z", "Techno")
    opts.protected = [mine, techno]
    assert pl.Organizer(opts).preview()["protected_target"] == 2  # D - Z and the unticked C - Y
    rep, errs = pl.Organizer(opts).run()
    assert os.path.exists(new) and any("D - Z.wav" in e for e in errs)
    # Undo leaves protected folders alone and keeps the run pending
    house = os.path.join(root, "House")
    runs = pl.list_runs(root)
    rep, errs = pl.undo_until(root, runs[-1][0], protected=[house])
    assert any(pl.t("err.undo_stuck") == e for e in errs)
    assert os.path.exists(os.path.join(house, "Tech House", "A - Song (Extended Mix).wav"))
    a = pl.Organizer(opts).run_id
    assert a < pl.Organizer(opts).run_id  # run ids sort in time order


def test_only_new():
    root = os.path.join(TMP, "novas")
    old = make(os.path.join(root, "solta", "A - Old.wav"), 1, "A", "Old", "Techno")
    opts = pl.Options(root=root, online=False, bpm_folders=False, dedupe=True, only_new=True)
    pl.Organizer(opts).run()  # first run: no list of known tracks yet, so only _entrada counts
    assert os.path.exists(old)
    new = make(os.path.join(root, "B - New.wav"), 3, "B", "New", "Techno")
    dup_old = make(os.path.join(root, "solta", "C - Same (Original Mix).wav"), 2, "C", "Same (Original Mix)", "House")
    org = pl.Organizer(opts)
    org.known[0].add(org._rel(dup_old))  # pretend it was there before
    org.known[1].add(os.path.getsize(dup_old))
    pl._write_json(org._inventory_path, {"paths": sorted(org.known[0]), "sizes": sorted(org.known[1])})
    make(os.path.join(root, pl.INBOX, "C - Same (Extended Mix).wav"), 4, "C", "Same (Extended Mix)", "House")
    rep, errs = pl.Organizer(opts).run()
    assert not errs, errs
    assert os.path.exists(old) and os.path.exists(dup_old)  # old tracks: not moved, not removed as duplicates
    assert os.path.exists(os.path.join(root, "Techno", "Techno", "B - New.wav"))
    assert os.path.exists(os.path.join(root, "House", "House", "C - Same (Extended Mix).wav"))
    assert not os.path.exists(new)


def test_undo_history_and_report():
    root = os.path.join(TMP, "hist")
    a = make(os.path.join(root, "A - One.wav"), 1, "A", "One", "Techno")
    opts = pl.Options(root=root, online=False, bpm_folders=False)
    pl.Organizer(opts).run()
    b = make(os.path.join(root, "B - Two.wav"), 1, "B", "Two", "House")
    pl.Organizer(opts).run()
    runs = pl.list_runs(root)
    assert len(runs) == 2 and runs[0][1]["mover"] == 1
    rep, errs = pl.undo_until(root, runs[1][0])  # the older one: both are undone, newest first
    assert not errs, errs
    assert os.path.exists(a) and os.path.exists(b) and pl.list_runs(root) == []
    assert pl.undo_until(root, runs[1][0]) == (pl.Counter(), [])  # nothing left: does nothing
    pl.Organizer(opts).run()
    assert pl.undo_until(root, pl.list_runs(root)[0][0], newest_seen="outra") == (pl.Counter(), [pl.t("err.undo_changed")])
    pl.undo_until(root, pl.list_runs(root)[0][0])
    # preview: a track that is moved and gets its genre tag fixed shows both; a second preview does not double the list
    multi = make(os.path.join(root, "M - Multi.wav"), 1, "M", "Multi", "Tech House, Deep House")
    org = pl.Organizer(opts)
    org.preview()
    assert ("tags", multi, "Tech House") in org.plan and any(k == "move" and p == multi for k, p, _ in org.plan)
    n = len(org.plan)
    org.preview()
    assert len(org.plan) == n
    os.remove(multi)

    make(os.path.join(root, "Sem Tags.wav"), 1)
    short = make(os.path.join(root, "C - Short.wav"), 1, "C", "Short", "Techno")
    out = os.path.join(TMP, "relatorio.csv")
    rep = pl.library_report(pl.Organizer(opts), out)
    assert rep["tracks"] == 4 and rep["report_no_artist_title"] == 1 and rep["report_no_genre"] == 1
    text = open(out, encoding="utf-8-sig").read()
    assert "Sem Tags.wav" in text and os.path.exists(short)  # read only
    assert any(short in line and pl.t("rep.report_short") in line for line in text.splitlines())  # 1 s long


if __name__ == "__main__":
    try:
        test_rules()
        test_guards()
        test_versions_option()
        test_update_versions()
        test_duplicate_rules()
        test_lock()
        test_quarantine_ownership()
        test_full_run_and_undo()
        test_rename_packs()
        test_new_tracks_outside_inbox()
        test_protected_and_skip()
        test_only_new()
        test_undo_history_and_report()
        print("ok")
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
