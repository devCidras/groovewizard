"""End-to-end check on a temporary library of tiny WAV files. Run: python -m pytest tests  (or python tests/test_pipeline.py)"""
import os
import shutil
import sys
import tempfile
import wave
import zipfile

_FIXED_TMP = os.environ.get("GROOVEWIZARD_TEST_TMP")
TMP = os.path.abspath(_FIXED_TMP) if _FIXED_TMP else tempfile.mkdtemp(prefix="organizador-teste-")
os.makedirs(TMP, exist_ok=True)
if _FIXED_TMP:  # managed sandboxes may only allow descendants of a directory that already existed
    for _name in os.listdir(TMP):
        if _name == ".gitkeep":
            continue
        _p = os.path.join(TMP, _name)
        shutil.rmtree(_p, ignore_errors=True) if os.path.isdir(_p) else os.remove(_p)
os.environ["APPDATA"] = os.path.join(TMP, "appdata")  # keep caches/logs out of the real profile
os.environ["LOCALAPPDATA"] = os.path.join(TMP, "localappdata")  # %TEMP% lives under it; libraries there are refused
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mutagen.id3 import TALB, TCON, TIT2, TPE1  # noqa: E402
from mutagen.wave import WAVE  # noqa: E402

import organizador.pipeline as pl  # noqa: E402
from organizador.tags import genre_of, normalize_genre, raw_genre, strip_sites, title_key  # noqa: E402

trashed = []
pl.send2trash = lambda p: (trashed.append(p), shutil.rmtree(p) if os.path.isdir(p) else os.remove(p))


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
    assert strip_sites("Dance - Kiss.Me") == "Dance - Kiss.Me"
    assert strip_sites("Rock - www.site.ru - Extended") == "Rock - Extended"
    assert strip_sites("https://electronicfresh.com") == ""
    assert strip_sites("Iglesias, Sharing-DB.club") == "Iglesias"  # site last in a list of artists: no comma left
    assert strip_sites(" Groove ") == " Groove " and strip_sites("A, B") == "A, B"  # no site: untouched
    assert strip_sites("Various Artists, Toolroom.Club") == "Various Artists, Toolroom.Club"
    assert strip_sites("Artist, Love.me") == "Artist, Love.me" and strip_sites("A, djsoundtop.com") == "A"
    for real in ("Love.me (Extended Mix)", "Back.to Life", "Toolroom Records", "Original Mix", "Kiss.Me", "Toolroom.Club"):
        assert strip_sites(real) == real, real
    assert title_key("Go Back feat. Julia (Extended Mix)") != title_key("Go Back (Original Mix)")
    assert title_key("Go Back (Extended Mix)") == title_key("Go Back (Original Mix)")
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
    # unsure / taken: only an unambiguous number followed by whitespace comes off; "03-c" may be an artist
    assert "sem tags.wav" in names and "03-c-taken.wav" in names, names
    assert "x_minha.wav" in names, "a track already in the library is never renamed"
    assert rep["renamed"] == 4, rep  # 3 Artist - Title + one that only lost an unambiguous track number
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
    yes = lambda items, kind="new": asked.append(items) or True

    def cancel(items, kind="new"):
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
    rep, errs = pl.Organizer(opts, ask_rename=lambda items, kind="new": False).run()  # "No": kept, and never asked again
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
    # lengths no other test file has: the inventory must know them by path, not by a size match
    edit = make(os.path.join(mine, "A - Song (Original Mix).wav"), 7, "A", "Song (Original Mix)", "Tech House")
    spam = make(os.path.join(mine, "B - X.wav"), 8, "B", "X", "https://site.com")
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

    # unticking the copy that stays: the other copy still goes (the list said so), the unticked one is never removed
    keep = make(os.path.join(root, "K - Song (Extended Mix).wav"), 3, "K", "Song (Extended Mix)", "Tech House")
    dup = make(os.path.join(root, "solta", "K - Song (Original Mix).wav"), 1, "K", "Song (Original Mix)", "Tech House")
    org = pl.Organizer(opts)
    org.preview()
    assert ("dup", dup, keep) in org.plan
    snap = org.snapshot
    assert pl.Organizer(opts).library_snapshot() == snap  # nothing changed: the list holds
    make(os.path.join(root, "novo.wav"), 1, "N", "Novo", "Techno")
    assert pl.Organizer(opts).library_snapshot() != snap  # a new download: the list no longer holds
    try:
        pl.Organizer(opts).run(expect=snap)
        raise AssertionError("ran on a stale list")
    except ValueError:
        pass
    os.remove(os.path.join(root, "novo.wav"))
    rep, errs = pl.Organizer(opts, skip=[keep, untick]).run()
    assert rep["dups_trashed"] == 1 and not os.path.exists(dup) and os.path.exists(keep)

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
    # protected tracks are known: unprotected later, 'Only new tracks' still leaves them alone
    opts.protected, opts.only_new = [], True
    rep, errs = pl.Organizer(opts).run()
    assert os.path.exists(edit) and os.path.exists(spam), "unprotected old tracks were treated as new"


def test_only_new():
    root = os.path.join(TMP, "novas")
    old = make(os.path.join(root, "solta", "A - Old.wav"), 1, "A", "Old", "Techno")
    opts = pl.Options(root=root, online=False, bpm_folders=False, dedupe=True, only_new=True)
    org = pl.Organizer(opts)
    assert org.preview()["only_new_first"] == 1

    def stop(*a):
        raise pl.Cancelled()
    org = pl.Organizer(opts, progress=stop)  # first organize cancelled straight away: nothing sorted yet
    try:
        org.run()
    except pl.Cancelled:
        pass
    assert os.path.exists(old) and pl.Organizer(opts).only_new_first  # still sorts everything next time
    rep, _ = pl.Organizer(opts).run()  # first organize of this library: everything is sorted, and the user is told
    assert rep["only_new_first"] == 1 and not os.path.exists(old)
    old = os.path.join(root, "Techno", "Techno", "A - Old.wav")
    assert os.path.exists(old) and "only_new_first" not in pl.Organizer(opts).run()[0]  # from now on: only new
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


def test_site_names():
    from organizador.tags import site_free_name
    assert site_free_name("A - B (Extended Mix) - www.djsoundtop.com.MP3") == "A - B (Extended Mix).mp3"
    assert site_free_name("Carla - Red Ambition-www.groovytunes.org.wav") == "Carla - Red Ambition.wav"
    assert site_free_name("DAMEN - Games (Original Mix) [4DJsonline.com] .aiff") == "DAMEN - Games (Original Mix).aiff"
    assert site_free_name("Love.me (Extended Mix).wav") is None and site_free_name("www.site.com.wav") is None
    from organizador.tags import clean_file_name as cfn
    assert cfn("05. Kaufmann (DE) - In Control.mp3", "Kaufmann (DE)") == "Kaufmann (DE) - In Control.mp3"
    assert cfn("01. A - B - www.djsoundtop.com.mp3", "A") == "A - B.mp3"
    assert cfn("02 - 6 Sense - X.wav", "6 Sense") == "6 Sense - X.wav"
    for keep, art in (("3.14 (AR) - Peter.mp3", "3.14 (AR)"), ("808 State - Cubik.mp3", "808 State"),
                      ("6 Sense - X.wav", "6 Sense"), ("1-2-3 Go.mp3", ""), ("936 - Pasion.mp3", "936")):
        assert cfn(keep, art) is None, keep  # the number belongs to the artist / isn't a track number
    assert cfn("[Live] 01 - A - B.mp3", "A") == "[Live] A - B.mp3"  # only the number comes off
    assert cfn("01 - Баста - Песня.mp3", "Баста") == "Баста - Песня.mp3"  # any script
    assert cfn("www.site.com - 05. A - B.mp3", "A") == "A - B.mp3"
    # a track you already had, put back in _entrada by hand: asked about like any old track, not renamed silently
    root = os.path.join(TMP, "entrada_antiga")
    import random
    old = make(os.path.join(root, "Techno", "Techno", "07. Z - Old.wav"), 2, "Z", "Old", "Techno")
    with open(old, "r+b") as fh:
        fh.seek(4000)
        fh.write(random.Random(9).randbytes(20000))
    o = pl.Options(root=root, online=False, bpm_folders=False, dedupe=False)
    pl.Organizer(o).run()
    pl.Organizer(o).run()  # fingerprints recorded
    back = os.path.join(root, pl.INBOX, "07. Z - Old.wav")
    os.makedirs(os.path.dirname(back))
    os.rename(old, back)
    asked2 = []
    pl.Organizer(o, ask_rename=lambda items, kind="new": asked2.append(kind) or False).run()
    assert os.path.exists(os.path.join(root, "Techno", "Techno", "07. Z - Old.wav")) and asked2 == []
    assert site_free_name("Artist - Love.me.wav") is None and site_free_name("Artist  -  Title.wav") is None
    assert site_free_name("Clouds - Mutate On-Site-www.groovytunes.org.mp3") == "Clouds - Mutate On-Site.mp3"
    assert site_free_name("A - Title-www.site.com (Extended Mix).mp3") == "A - Title (Extended Mix).mp3"
    assert site_free_name("Artist-www.site.com-Extended-Mix.mp3") == "Artist-Extended-Mix.mp3"  # the mix stays
    assert strip_sites("DUMBO-www.groovytunes.org") == "DUMBO"  # tag: a glued site never takes the title with it
    # 'Artist - Title' taken: the original name without the site is used instead
    root = os.path.join(TMP, "sites2")
    make(os.path.join(root, "Techno", "Techno", "Z - Taken.wav"), 2, "Q", "Other", "Techno")
    make(os.path.join(root, pl.INBOX, "z_taken - www.djsoundtop.com.wav"), 1, "Z", "Taken", "Techno")
    pl.Organizer(pl.Options(root=root, online=False, bpm_folders=False, dedupe=False, rename_packs=True)).run()
    assert sorted(os.listdir(os.path.join(root, "Techno", "Techno"))) == ["Z - Taken.wav", "z_taken.wav"]

    root = os.path.join(TMP, "sites")
    old = make(os.path.join(root, "Techno", "Techno", "A - Old (Original Mix) - www.djsoundtop.com.wav"), 1, "A", "Old", "Techno")
    opts = pl.Options(root=root, online=False, bpm_folders=False, dedupe=False)  # clean_sites on by default
    asked = []
    ask = lambda items, kind="new": (asked.append((kind, len(items))), True)[1]
    pl.Organizer(opts, ask_rename=ask).run()  # first run: the old track is known and keeps its name
    assert os.path.exists(old) and asked == []
    make(os.path.join(root, pl.INBOX, "pack", "B - New (Extended Mix) [4DJsonline.com].wav"), 1, "B", "New", "Techno")
    make(os.path.join(root, "C - Loose - www.electronicfresh.com.wav"), 3, "C", "Loose", "Techno")
    rep, errs = pl.Organizer(opts, ask_rename=ask).run()
    assert not errs, errs
    here = os.path.join(root, "Techno", "Techno")
    assert os.path.exists(os.path.join(here, "B - New (Extended Mix).wav"))  # _entrada: no question
    assert os.path.exists(os.path.join(here, "C - Loose.wav")) and asked == [("new_sites", 1)]  # new outside: asked
    assert os.path.exists(old)  # option for existing tracks is off

    opts.site_names = True
    org = pl.Organizer(opts)
    org.preview()
    assert ("site_name", old, "A - Old (Original Mix).wav") in org.plan
    rep, _ = pl.Organizer(opts, ask_rename=lambda items, kind="new": False).run()  # "No": stays
    assert os.path.exists(old)
    rep, errs = pl.Organizer(opts, ask_rename=ask).run()
    assert rep["site_names"] == 1 and asked[-1] == ("sites", 1)
    assert os.path.exists(os.path.join(here, "A - Old (Original Mix).wav")) and not os.path.exists(old)
    pl.undo_last(root)
    assert os.path.exists(old)  # Undo puts the old name back


def test_same_size_new_track():
    """A new track with exactly the size of a known one is new if its music differs; a known one moved by hand isn't."""
    import random

    def music(path, seed, artist, title):
        make(path, 2, artist, title, "Techno")
        with open(path, "r+b") as fh:  # same length and tags, different audio in the middle
            fh.seek(4000)
            fh.write(random.Random(seed).randbytes(20000))
        return path

    root = os.path.join(TMP, "fps")
    a = music(os.path.join(root, "Techno", "Techno", "A - One.wav"), 1, "A", "One")
    opts = pl.Options(root=root, online=False, bpm_folders=False, dedupe=False, only_new=True)
    pl.Organizer(opts).run()  # first run: list of known tracks with fingerprints
    pl.Organizer(opts).run()
    moved = os.path.join(root, "pasta", "A - One.wav")
    os.makedirs(os.path.dirname(moved))
    os.rename(a, moved)  # moved by hand: same music -> still known
    b = music(os.path.join(root, "B - Two.wav"), 2, "B", "Two")  # same size, other music -> new
    assert os.path.getsize(b) == os.path.getsize(moved)
    org = pl.Organizer(opts)
    assert not org.is_new(moved) and org.is_new(b)
    pl.Organizer(opts).run()
    assert os.path.exists(moved) and os.path.exists(os.path.join(root, "Techno", "Techno", "B - Two.wav"))
    # an inventory from before fingerprints: a known size alone still counts as known (safe side)
    inv = pl._read_json(org._inventory_path, {})
    pl._write_json(org._inventory_path, {"paths": [], "sizes": inv["sizes"]})
    assert not pl.Organizer(opts).is_new(moved)
    # migrating such an inventory: a known track that is away during the first 1.5 run (same size as one that is
    # here) must still be known when it comes back somewhere else
    away = os.path.join(TMP, "fora.wav")
    os.rename(moved, away)
    c = music(os.path.join(root, "C - Three.wav"), 3, "C", "Thr")  # same size, present during the migration run
    assert os.path.getsize(c) == os.path.getsize(away)
    pl._write_json(org._inventory_path, {"paths": [org._rel(c)], "sizes": inv["sizes"]})
    opts.only_new = False
    pl.Organizer(opts).run()  # migration: fingerprints written
    back = os.path.join(root, "outra", "A - One.wav")
    os.makedirs(os.path.dirname(back))
    os.rename(away, back)
    assert not pl.Organizer(opts).is_new(back), "a known track became new after the migration"


def test_covers():
    """Tracks without cover art get one (Discogs faked: no network in tests); existing covers stay; Undo removes it."""
    import struct
    import zlib
    from organizador.tags import read_info, set_cover

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b""))
    asked = []
    from organizador.online import _same_artist
    for ours, theirs, same in (("Fisher", "FISHER", True), ("Fisher", "Fisher Price", False), ("B", "A Featuring B", True),
                               ("Marten Hørger", "Marten Hørger & James Carter", True), ("Ampa", "FTampa", False)):
        assert _same_artist(ours, theirs) == same, (ours, theirs)

    class FakeDiscogs:
        def __init__(self, data, token, cancel=None):
            pass

        def cover(self, artist, title):
            asked.append((artist, title))
            return "https://img/x.png"

        def image(self, url, folder):
            return png

        def save(self):
            pass

    class FakeDeezer(FakeDiscogs):
        def __init__(self, data, cancel=None):
            pass

        def cover(self, artist, title):
            asked.append(("deezer", artist, title))
            return ""  # not found there: Discogs is tried next

    real = pl.Discogs, pl.Deezer
    pl.Discogs, pl.Deezer = FakeDiscogs, FakeDeezer
    try:
        root = os.path.join(TMP, "capas")
        bare = make(os.path.join(root, "Techno", "Techno", "A - Bare.wav"), 1, "A", "Bare", "Techno")
        has = make(os.path.join(root, "Techno", "Techno", "B - Has.wav"), 2, "B", "Has", "Techno")
        set_cover(has, png)
        opts = pl.Options(root=root, online=False, bpm_folders=False, covers=True)
        assert pl.Organizer(opts).preview()["covers_pending"] == 1
        rep, errs = pl.Organizer(opts, keys={"discogs_token": "x"}).run()
        assert not errs and rep["covers_added"] == 1, (rep, errs)
        assert asked == [("deezer", "A", "Bare"), ("A", "Bare")], asked  # only the track without a cover; Deezer first
        assert read_info(bare)["cover"] and read_info(has)["cover"]
        rep, errs = pl.undo_last(root)
        assert not errs and rep["undo_covers"] == 1 and not read_info(bare)["cover"] and read_info(has)["cover"]
        rep, errs = pl.Organizer(opts).run()  # no Discogs key, Deezer finds nothing: no cover, no error
        assert not errs and "covers_added" not in rep and not read_info(bare)["cover"]
        # the user replaced our cover after the run: Undo leaves theirs alone
        pl.Organizer(opts, keys={"discogs_token": "x"}).run()
        from organizador.tags import remove_cover, cover_digest
        assert remove_cover(bare, cover_digest(png))
        mine = png[:-12] + b"\x00\x00\x00\x00tEXt" + png[-12:]  # another (still valid) image
        set_cover(bare, mine)
        rep, errs = pl.undo_last(root)
        assert not errs and read_info(bare)["cover"], "Undo took out a cover the user added"
        from organizador.tags import image_type
        assert image_type(png) and not image_type(png[:-12]) and not image_type(b"\xff\xd8\xff\xe0" + b"x" * 50)
    finally:
        pl.Discogs, pl.Deezer = real


def test_covers_all_with_only_new():
    """The cover override reaches old bare tracks, without widening any other step."""
    import struct
    import zlib
    from organizador.tags import read_info, set_cover

    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff))

    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b""))
    root = os.path.join(TMP, "capas-todas")
    techno = os.path.join(root, "Techno")
    old = make(os.path.join(techno, "Old.wav"), 1, "A", "Old", "Techno")
    missing = make(os.path.join(techno, "Missing.wav"), 2, "B", "Missing", "Techno")
    has = make(os.path.join(techno, "Has.wav"), 3, "C", "Has", "Techno")
    protected_dir = os.path.join(root, "Protegida")
    protected = make(os.path.join(protected_dir, "Private.wav"), 4, "D", "Private", "Techno")
    set_cover(has, png)
    base = pl.Options(root=root, extract=False, dedupe=False, online=False, bpm_folders=False,
                      write_tags=False, clean_sites=False, covers=False, families=False,
                      protected=[protected_dir])
    rep, errs = pl.Organizer(base).run()  # build the inventory with a completed full run
    assert not errs, (rep, errs)
    moved_old = os.path.join(root, "Deslocada", "Old.wav")
    os.makedirs(os.path.dirname(moved_old))
    os.rename(old, moved_old)  # still known by content; Only new must not re-sort it
    new = make(os.path.join(root, "Solta", "New.wav"), 5, "E", "New", "Techno")
    base.only_new = base.covers = True
    org = pl.Organizer(base)
    assert not org.is_new(moved_old) and org.is_new(new)
    assert org.preview()["covers_pending"] == 1  # old behaviour remains the default
    base.covers_all = True
    org = pl.Organizer(base)
    assert org.preview()["covers_pending"] == 3
    assert {p for kind, p, _ in org.plan if kind == "cover"} == {moved_old, missing, new}
    assert not any(kind == "move" and p == moved_old for kind, p, _ in org.plan)

    asked = []

    class FakeDeezer:
        def __init__(self, *args):
            pass

        def cover(self, artist, title):
            asked.append(title)
            return "" if title == "Missing" else "https://example.invalid/cover.png"

        def image(self, url, folder):
            return png

        def save(self):
            pass

    real = pl.Deezer
    pl.Deezer = FakeDeezer
    try:
        rep, errs = pl.Organizer(base).run()
    finally:
        pl.Deezer = real
    new_place = os.path.join(techno, "New.wav")
    assert not errs and rep["covers_added"] == 2, (rep, errs)
    assert set(asked) == {"Old", "Missing", "New"}, asked
    assert os.path.exists(moved_old) and not os.path.exists(new) and os.path.exists(new_place)
    assert read_info(moved_old)["cover"] and read_info(new_place)["cover"]
    assert not read_info(missing)["cover"] and read_info(has)["cover"]
    assert not read_info(protected)["cover"]


def test_old_step_scopes():
    """Old-track opt-ins are independent: a tag repair must not also move or dedupe old files."""
    from organizador.tags import read_info

    root = os.path.join(TMP, "old-step-tags")
    here = os.path.join(root, "Techno")
    genre = make(os.path.join(here, "Genre.wav"), 1, "A", "Genre", "Techno")
    site = make(os.path.join(here, "Site.wav"), 2, "B", "Site", "Techno")
    opts = pl.Options(root=root, extract=False, dedupe=False, online=False, bpm_folders=False,
                      write_tags=False, clean_sites=False, families=False)
    assert not pl.has_completed_full_run(root)
    assert not pl.Organizer(opts).run()[1]
    assert pl.has_completed_full_run(root)
    f = WAVE(genre)
    f.tags.setall("TCON", [TCON(encoding=3, text=["House"])])
    f.save()
    f = WAVE(site)
    f.tags.add(TALB(encoding=3, text=["www.djsoundtop.com"]))
    f.save()
    opts.only_new = opts.write_tags = opts.clean_sites = True
    assert not pl.Organizer(opts).run()[1]
    assert raw_genre(genre) == "House" and "djsoundtop.com" in str(WAVE(site).tags)
    opts.write_tags_all = True
    org = pl.Organizer(opts)
    org.preview()
    assert ("tags", genre, "Techno") in org.plan and not any(k == "move" for k, _, _ in org.plan)
    assert not pl.Organizer(opts).run()[1]
    assert raw_genre(genre) == "Techno" and "djsoundtop.com" in str(WAVE(site).tags)
    opts.write_tags_all, opts.clean_sites_all = False, True
    assert not pl.Organizer(opts).run()[1]
    assert "djsoundtop.com" not in str(WAVE(site).tags) and os.path.exists(genre)

    root = os.path.join(TMP, "old-step-organize")
    old = make(os.path.join(root, "Techno", "Old - www.djsoundtop.com.wav"), 1, "C", "Old", "Techno")
    opts = pl.Options(root=root, extract=False, dedupe=False, online=False, bpm_folders=False,
                      write_tags=False, clean_sites=False, families=False)
    assert not pl.Organizer(opts).run()[1]
    displaced = os.path.join(root, "Loose", os.path.basename(old))
    os.makedirs(os.path.dirname(displaced))
    os.rename(old, displaced)
    opts.only_new = opts.site_names = True
    org = pl.Organizer(opts)
    assert not org.is_new(displaced)
    org.preview()
    assert any(k == "site_name" and p == displaced for k, p, _ in org.plan)
    assert not any(k == "move" and p == displaced for k, p, _ in org.plan)
    assert not pl.Organizer(opts, ask_rename=lambda items, kind="new": True).run()[1]
    renamed = os.path.join(root, "Loose", "Old.wav")
    assert os.path.exists(renamed) and not os.path.exists(old)
    opts.site_names, opts.organize_all = False, True
    org = pl.Organizer(opts)
    org.preview()
    assert any(k == "move" and p == renamed for k, p, _ in org.plan)
    assert not pl.Organizer(opts).run()[1]
    assert os.path.exists(os.path.join(root, "Techno", "Old.wav"))

    root = os.path.join(TMP, "old-step-dedupe")
    original = make(os.path.join(root, "House", "D - Tune (Original Mix).wav"), 1, "D", "Tune (Original Mix)", "House")
    extended = make(os.path.join(root, "House", "D - Tune (Extended Mix).wav"), 2, "D", "Tune (Extended Mix)", "House")
    opts = pl.Options(root=root, extract=False, dedupe=False, online=False, bpm_folders=False,
                      write_tags=False, clean_sites=False, families=False)
    assert not pl.Organizer(opts).run()[1]
    opts.only_new = opts.dedupe = True
    assert pl.Organizer(opts).preview()["dups_pending"] == 0
    opts.dedupe_all = True
    assert pl.Organizer(opts).preview()["dups_pending"] == 1
    assert not pl.Organizer(opts).run()[1]
    assert not os.path.exists(original) and os.path.exists(extended)

    root = os.path.join(TMP, "old-step-online")
    old = make(os.path.join(root, "Sem Genero", "E - Unknown.wav"), 1, "E", "Unknown")
    opts = pl.Options(root=root, extract=False, dedupe=False, online=False, bpm_folders=False,
                      write_tags=False, clean_sites=False, families=False)
    assert not pl.Organizer(opts).run()[1]
    opts.only_new = opts.online = opts.write_tags = True
    assert pl.Organizer(opts).preview()["online_pending"] == 0
    opts.online_all = True
    assert pl.Organizer(opts).preview()["online_pending"] == 1

    class FakeLookup:
        available = True
        problems = []

        def __init__(self, *args):
            pass

        def genre(self, artist, title):
            return "Techno", "test"

        def save(self):
            pass

    real = pl.Lookup
    pl.Lookup = FakeLookup
    try:
        assert not pl.Organizer(opts).run()[1]
    finally:
        pl.Lookup = real
    online_moved = os.path.join(root, "Techno", "E - Unknown.wav")
    assert not os.path.exists(old) and os.path.exists(online_moved)
    assert not raw_genre(online_moved), "online_all alone must not also write an old track's genre tag"
    opts.online = False
    opts.write_tags_all = True
    assert not pl.Organizer(opts).run()[1]
    assert raw_genre(online_moved) == "Techno"

    root = os.path.join(TMP, "old-step-bpm")
    old = make(os.path.join(root, "Sem Genero", "F - Beat.wav"), 1, "F", "Beat")
    opts = pl.Options(root=root, extract=False, dedupe=False, online=False, bpm_folders=False,
                      write_tags=False, clean_sites=False, families=False)
    assert not pl.Organizer(opts).run()[1]
    opts.only_new = opts.bpm_folders = True
    assert pl.Organizer(opts).preview()["bpm_pending"] == 0
    opts.bpm_all = True
    assert pl.Organizer(opts).preview()["bpm_pending"] == 1
    real = pl.bpm_mod.bpm_of
    pl.bpm_mod.bpm_of = lambda p: 125
    try:
        assert not pl.Organizer(opts).run()[1]
    finally:
        pl.bpm_mod.bpm_of = real
    assert not os.path.exists(old) and os.path.exists(os.path.join(root, "Sem Genero", "BPM 122-128", "F - Beat.wav"))


def test_site_covers():
    """A site's ad comes out (the real cover is put in when found), real covers stay, Undo puts the ad back."""
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QColor, QImage, QPainter
    from organizador import capas
    from mutagen.id3 import APIC
    from organizador.tags import cover_digest, picture_records, pictures, put_back_cover, set_cover

    def image(color, box, side=300, fmt="JPG"):
        im = QImage(side, side, QImage.Format_RGB888)
        im.fill(QColor(color))
        p = QPainter(im)
        x, y, w, h = (int(v * side) for v in box)
        p.fillRect(x, y, w, h, QColor("white"))
        p.end()
        b = QBuffer()
        b.open(QIODevice.WriteOnly)
        assert im.save(b, fmt)
        return bytes(b.data())

    ad, ad_small = image("black", (.2, .4, .6, .2)), image("black", (.2, .4, .6, .2), 90, "PNG")  # same ad, other file
    logo = image("black", (.4, .1, .2, .6))  # a real label cover, also white on black
    found = image("red", (.1, .1, .3, .3))
    text = image("black", (.2, .4, .55, .2))  # same background, slightly different text: not the same cover
    f = capas.fingerprint(ad)
    assert capas.same(f, capas.fingerprint(ad_small)) and not capas.same(f, capas.fingerprint(logo))
    assert not capas.same(f, capas.fingerprint(text))
    assert capas.fingerprint(b"not an image") is None
    shipped = capas.SiteCovers("none").shipped
    assert len(shipped) >= 30
    root = os.path.join(TMP, "capas-sites")
    here = os.path.join(root, "Techno", "Techno")
    a, b, c, d, e = (make(os.path.join(here, n + " - Song.wav"), i + 1, n, "Song", "Techno") for i, n in enumerate("ABCDE"))
    for p, pic in ((a, ad), (b, ad_small), (c, logo), (d, ad), (e, ad)):
        set_cover(p, pic)
    fa = WAVE(a)
    fa.tags.delall("APIC")
    fa.tags.add(APIC(encoding=1, mime="image/jpeg", type=4, desc="Original back cover", data=ad))
    fa.save(v2_version=3)
    put_back_cover(d, logo)  # D: the ad and a real cover
    answer = {"A": "u", "B": "", "E": None}  # found / nothing there / no internet

    class Fake:
        def __init__(self, *a):
            pass

        def cover(self, artist, title):
            return answer[artist]  # KeyError (an error in the report) if C or D were looked up

        def image(self, url, folder):
            return ad_small  # Deezer answers with the ad itself: Discogs is still asked

        def save(self):
            pass

    class FakeDiscogs(Fake):
        def image(self, url, folder):
            return found

    real = pl.Deezer, pl.Discogs
    pl.Deezer, pl.Discogs = Fake, FakeDiscogs
    try:
        capas.SiteCovers(pl.MARKED_COVERS).save_marked([f])
        opts = pl.Options(root=root, online=False, bpm_folders=False, dedupe=False, site_covers=True)
        org = pl.Organizer(opts)
        assert org.preview()["site_covers_pending"] == 4
        assert {p for k, p, _ in org.plan if k == "site_cover"} == {a, b, d, e}
        before = {p: picture_records(p) for p in (a, b, c, d, e)}
        rep, errs = pl.Organizer(opts, keys={"discogs_token": "x"}).run()
        assert not errs and (rep["site_covers_out"], rep["covers_added"], rep["site_covers_later"]) == (3, 1, 1), (rep, errs)
        assert [pictures(p) for p in (a, b, c, d, e)] == [[found], [], [logo], [logo], [ad]]
        rep, errs = pl.undo_last(root)
        assert not errs and rep["undo_site_covers"] == 3, (rep, errs)
        after_records = {p: picture_records(p) for p in before}
        assert after_records == before, [(p, before[p], after_records[p]) for p in before if before[p] != after_records[p]]
        assert WAVE(a).tags.version[1] == 3
        # unticked in the list: left alone
        pl.Organizer(opts, skip=[a, b, d]).run()
        assert pictures(a) == [ad]
        opts.only_new = True
        assert pl.Organizer(opts).preview()["site_covers_pending"] == 0
        opts.site_covers_all = True
        assert pl.Organizer(opts).preview()["site_covers_pending"] == 4
        rep, errs = pl.Organizer(opts, keys={"discogs_token": "x"}).run()
        assert not errs and rep["site_covers_out"] == 3, (rep, errs)
        assert [pictures(p) for p in (a, b, c, d, e)] == [[found], [], [logo], [logo], [ad]]
        many = [(ad, str(i)) for i in range(6)] + [(ad_small, "x"), (logo, "y")]
        groups = capas.repeated(many, capas.SiteCovers("none"))
        assert len(groups) == 1 and groups[0][2] == 6 and groups[0][3] == 6, groups
    finally:
        pl.Deezer, pl.Discogs = real
        os.remove(pl.MARKED_COVERS)
    # a timeout / bad request is 'could not ask', only 404 is 'nothing there'
    import urllib.error
    import urllib.request
    from organizador import online
    real_open, code = urllib.request.urlopen, [0]

    def fail(*a, **k):
        raise urllib.error.HTTPError("u", code[0], "", {}, None)
    urllib.request.urlopen = fail
    try:
        for code[0], answer in ((400, None), (403, None), (404, "")):
            dz = online.Deezer(os.path.join(TMP, f"http-{code[0]}"))
            os.makedirs(dz.path.rsplit(os.sep, 1)[0], exist_ok=True)
            assert dz.cover("A", f"T{code[0]}") == answer, code
    finally:
        urllib.request.urlopen = real_open


def test_bpm():
    from organizador import bpm

    def clicks(path, tempo, seconds=48):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        beat = round(44100 * 60 / tempo)
        with wave.open(path, "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(44100)
            w.writeframes((b"\xff\x3f\x01\xc0" * 300 + bytes(beat * 2 - 1200)) * (seconds * 44100 // beat))
        return path

    root = os.path.join(TMP, "bpm")
    for tempo in (98, 122, 127, 128, 174):
        got = bpm.measure(clicks(os.path.join(TMP, "bpm-src", f"{tempo}.wav"), tempo))
        assert got and abs(got - tempo) <= .1, (tempo, got)
    assert bpm.measure(make(os.path.join(TMP, "bpm-src", "mudo.wav"), 30)) is None  # silence
    assert bpm.measure(clicks(os.path.join(TMP, "bpm-src", "curta.wav"), 125, 5)) is None  # too short to tell
    bad = os.path.join(TMP, "bpm-src", "bad.mp3")
    open(bad, "wb").write(b"not really audio")
    assert bpm.measure(bad) is None
    # tracks left in 'unknown' by older versions are measured now; what still has no beat stays there
    unknown = os.path.join(root, "Sem Genero", "BPM desconhecido")
    old = clicks(os.path.join(unknown, "A - Old.wav"), 127)
    mute = make(os.path.join(unknown, "B - Mute.wav"), 9)
    out = clicks(os.path.join(root, "Outros", "BPM desconhecido", "C - Out.wav"), 130)
    rep, errs = pl.Organizer(pl.Options(root=root, online=False, bpm_folders=True, dedupe=False)).run()
    assert not errs and rep["bpm_sorted"] == 2, (rep, errs)
    moved = os.path.join(root, "Sem Genero", "BPM 122-128", "A - Old.wav")
    assert not os.path.exists(old) and os.path.exists(moved)
    assert not os.path.exists(out), os.listdir(root)
    assert os.path.exists(mute)
    real_measure, calls = bpm.measure, []
    bpm.measure = lambda p: calls.append(p) or real_measure(p)
    try:
        again = pl.Organizer(pl.Options(root=root, online=False, bpm_folders=True, dedupe=False))
        assert again.preview().get("bpm_pending", 0) == 0
        again.run()
        assert not calls, "a permanently unknown track was measured again"
    finally:
        bpm.measure = real_measure
    rep, errs = pl.undo_last(root)
    assert not errs and os.path.exists(old) and os.path.exists(out), errs


def test_review_fixes():
    from organizador import bpm
    from organizador.tags import artist_title, artists_key, clean_sites
    assert strip_sites("!!!") == "!!!" and strip_sites("...") == "..."  # no site: never emptied
    root = os.path.join(TMP, "revisao")
    band = make(os.path.join(root, "Techno", "Techno", "x.wav"), 1, "!!!", "...", "Techno")
    assert clean_sites(band, write=False) == 0
    bare = {"artist": "", "title": ""}
    assert artist_title("808 State - Pacific.wav", bare) == ("808 State", "Pacific")
    assert artist_title("01. Fisher - Losing It.wav", bare) == ("Fisher", "Losing It")
    assert artists_key("Mr. X") != artists_key("Mr") and artists_key("A x B") == artists_key("B, A")
    assert artists_key("Ft. Lauderdale") != artists_key("Lauderdale")
    assert bpm.fold(float("nan")) is None and bpm.fold(float("inf")) is None
    # half a pack left by a crash is never sorted; a '_' root folder is left alone; a pack dropped in _entrada stays
    make(os.path.join(root, pl.INBOX, "P" + pl.STAGING, "half.wav"), 2, "H", "Half", "House")
    make(os.path.join(root, "_Backup", "mine.wav"), 3, "M", "Mine", "House")
    src = make(os.path.join(TMP, "revisao-src", "t.wav"), 4, "T", "Track", "House")
    for d in (os.path.join(root, "_Backup"), os.path.join(root, pl.INBOX)):
        with zipfile.ZipFile(os.path.join(d, "pack.zip"), "w") as z:
            z.write(src, "t.wav")
    rep, errs = pl.Organizer(pl.Options(root=root, online=False, bpm_folders=False, dedupe=False)).run()
    assert not errs and rep["archives_extracted"] == 1, (rep, errs)
    assert os.path.exists(os.path.join(root, "House", "House", "t.wav"))
    assert not os.path.exists(os.path.join(root, "House", "House", "half.wav"))
    assert os.path.exists(os.path.join(root, "_Backup", "mine.wav")) and os.path.exists(os.path.join(root, "_Backup", "pack.zip"))
    assert os.path.exists(os.path.join(root, pl.INBOX, "pack.zip"))


def test_unticked_on_first_run_stay_known():
    root = os.path.join(TMP, "untick1")
    old = make(os.path.join(root, "Misc", "A - One.wav"), 9, "A", "One", "House")  # unique length: known by path only
    opts = pl.Options(root=root, online=False, bpm_folders=False)
    pl.Organizer(opts, skip=[old]).run()  # first run ever, the old track unticked
    assert os.path.exists(old)
    opts.only_new = True
    pl.Organizer(opts).run()
    assert os.path.exists(old), "an old track unticked on the first run became 'new' and was moved"


def test_audit_names_config_and_online():
    import builtins
    import io
    import json
    from unittest.mock import patch
    from mutagen.id3 import WXXX
    from organizador import config, online
    from organizador.tags import (artist_title, clean_file_name, clean_sites, genre_from_folder, norm, pack_file_name,
                                  read_info, snapshot)

    assert title_key("Ready (feat. Ramona)") != title_key("Ready (feat. Sam)")
    assert title_key("Anthem (1995)") != title_key("Anthem (2003)")
    assert title_key("Lost - Extended Mix") == title_key("Lost (Extended Mix)")
    assert norm("Ma") != norm("Mà") and norm("ไม่") != norm("ไม้")
    assert artist_title("Artist - Oh.Organic.wav", {"artist": "", "title": ""}) == ("Artist", "Oh.Organic")
    for name in ("2-Step - Sample.mp3", "50.Cent - Candy Shop.mp3", "808_State - Pacific.mp3"):
        assert clean_file_name(name) is None, name
    assert clean_file_name("01. Artist - Track.mp3") == "Artist - Track.mp3"
    assert online.folder_for("Lighthouse Family") == (None, None)
    assert online.folder_for("Breakdance") == (None, None)
    assert online.folder_for("Nu-Disco")[0] == "Nu Disco - Disco"
    assert online.folder_for("Techno House")[0] == "Techno House"
    assert genre_from_folder(r"X:\_entrada\Deep_House_Vol1\a.wav", "Deep_House_Vol1") == "Deep House"
    assert pack_file_name("Dave (Edit Master) - Tune.wav", {"artist": "Dave", "title": "Tune"}) == "Dave - Tune.wav"

    tagged = make(os.path.join(TMP, "url-tags", "A.wav"), 2, "A", "T", "House")
    f = WAVE(tagged)
    f.tags.add(WXXX(encoding=3, desc="publisher", url="https://label.example/release"))
    f.tags.add(WXXX(encoding=3, desc="djsoundtop", url="https://djsoundtop.com/x"))
    f.save(v2_version=3)
    clean_sites(tagged)
    f = WAVE(tagged)
    assert f.tags.version[1] == 3
    urls = [x.url for x in f.tags.getall("WXXX")]
    assert urls == ["https://label.example/release"], urls
    assert snapshot(tagged)

    old_path = config.PATH
    config.PATH = os.path.join(TMP, "cfg", "config.json")
    os.makedirs(os.path.dirname(config.PATH), exist_ok=True)
    with open(config.PATH, "w", encoding="utf-8") as fh:
        json.dump({"opcoes": {"root": 5, "dedupe": "false", "protected": ["ok", 2]},
                   "chaves": {"discogs_token": 5, "lastfm_api_key": "x"}}, fh)
    opts, keys = config.load()
    assert opts.root == "" and opts.dedupe is True and opts.protected == ["ok"] and keys == {"lastfm_api_key": "x"}
    with patch.object(builtins, "open", side_effect=OSError("busy")):
        assert config._read() is None
    assert os.path.exists(config.PATH) and not os.path.exists(config.PATH + ".estragado")
    with open(config.PATH, "w", encoding="utf-8") as fh:
        json.dump({"chaves": {"discogs_token": "dpapi:AAAA"}}, fh)
    assert config.load()[1]["discogs_token"] == ""
    assert config.clear_key("discogs_token") and "discogs_token" not in config._read()["chaves"]
    config.PATH = old_path

    class Response(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *args): return False
    source = online.Cached(os.path.join(TMP, "odd-cache.json"), 0, cancel=type("C", (), {"wait": lambda self, n: False})())
    with patch.object(online.urllib.request, "urlopen", return_value=Response(b"[]")):
        assert source.fetch("https://example.invalid", {}) is None and source.disabled
    calls = []
    source = online.Cached(os.path.join(TMP, "offline-cache.json"), 0, cancel=type("C", (), {"wait": lambda self, n: False})())
    def offline(*args, **kwargs):
        calls.append(1)
        raise OSError("offline")
    with patch.object(online.urllib.request, "urlopen", side_effect=offline):
        assert source.fetch("https://example.invalid", {}) is None
        assert source.fetch("https://example.invalid", {}) is None
    assert len(calls) == 3, "an offline source was retried for every track"


def test_audit_pipeline_and_undo():
    import stat
    from unittest.mock import patch
    from organizador.tags import read_info

    # A destination that is a regular file is a per-track warning, not a run crash.
    root = os.path.join(TMP, "dest-conflict")
    os.makedirs(root)
    open(os.path.join(root, "House"), "wb").write(b"mine")
    src = make(os.path.join(root, "A.wav"), 2, "A", "T", "Tech House")
    rep, errs = pl.Organizer(pl.Options(root=root, online=False, bpm_folders=False, dedupe=False)).run()
    assert errs and os.path.exists(src)

    # Cancellation does not start the expensive full inventory rebuild.
    root = os.path.join(TMP, "cancel-inventory")
    make(os.path.join(root, "A.wav"), 1)
    cancel = __import__("threading").Event()
    cancel.set()
    org = pl.Organizer(pl.Options(root=root, online=False), cancel=cancel)
    try:
        org.run()
        raise AssertionError("cancel was ignored")
    except pl.Cancelled:
        pass
    assert not os.path.exists(org._inventory_path)

    # A failed cross-drive source deletion rolls back the completed copy (no duplicate is left behind).
    root = os.path.join(TMP, "cross-drive")
    src = make(os.path.join(root, "src", "A.wav"), 1)
    dst_dir = os.path.join(root, "dst")
    org = pl.Organizer(pl.Options(root=root, online=False))
    real_rename, real_remove = pl.os.rename, pl.os.remove
    rename_calls = [0]
    def cross_rename(a, b):
        rename_calls[0] += 1
        if rename_calls[0] == 1:
            raise OSError(__import__("errno").EXDEV, "cross drive")
        return real_rename(a, b)
    def locked_remove(path):
        if path == src:
            raise PermissionError("locked")
        return real_remove(path)
    with patch.object(pl.os, "rename", side_effect=cross_rename), patch.object(pl.os, "remove", side_effect=locked_remove):
        assert org.move(src, dst_dir) is None
    assert os.path.exists(src) and not os.path.exists(os.path.join(dst_dir, "A.wav"))
    org._log.close()
    assert pl.list_runs(root)[0][1].get("mover", 0) == 0

    # A read-only destination may reject the edit, but no full .ck- copy is left behind.
    root = os.path.join(TMP, "readonly")
    ro = make(os.path.join(root, "House", "House", "A.wav"), 2, "A", "T", "House", "djsoundtop.com")
    os.chmod(ro, stat.S_IREAD)
    try:
        pl.Organizer(pl.Options(root=root, online=False, bpm_folders=False, dedupe=False)).run()
        assert not [n for n in os.listdir(os.path.dirname(ro)) if ".ck-" in n]
    finally:
        os.chmod(ro, stat.S_IWRITE)

    # Windows accepts an unpaired UTF-16 surrogate in a file name; logging it must not abort the run.
    root = os.path.join(TMP, "surrogate")
    odd = make(os.path.join(root, "House", "House", "bad\ud800.wav"), 1, "A", "T", "House", "djsoundtop.com")
    rep, errs = pl.Organizer(pl.Options(root=root, online=False, bpm_folders=False, dedupe=False)).run()
    assert rep["sites_cleaned"] == 1 and os.path.exists(odd), errs

    # Case-insensitive member collisions reject the pack instead of silently losing one track.
    root = os.path.join(TMP, "zip-collision")
    os.makedirs(root)
    sample = make(os.path.join(TMP, "zip-src", "x.wav"), 1)
    pack = os.path.join(root, "pack.zip")
    with zipfile.ZipFile(pack, "w") as z:
        z.write(sample, "Song.wav")
        z.write(sample, "song.wav")
    rep, errs = pl.Organizer(pl.Options(root=root, online=False, bpm_folders=False, dedupe=False)).run()
    assert errs and os.path.exists(pack) and rep["archives_extracted"] == 0

    # A directory disguised with an audio extension and a legitimate '.ck-' name are handled correctly.
    root = os.path.join(TMP, "loose")
    os.makedirs(os.path.join(root, "Sem Genero", "crate.mp3", "inside"))
    legit = make(os.path.join(root, "Sem Genero", "Artist - Track.ck-edit.wav"), 1)
    org = pl.Organizer(pl.Options(root=root, online=False, bpm_folders=True, dedupe=False))
    assert legit in list(org.audio_files()) and os.path.join(root, "Sem Genero", "crate.mp3") not in org._loose_unsorted()

    # A temporarily missing result keeps Undo pending and can be retried.
    root = os.path.join(TMP, "undo-missing")
    original = make(os.path.join(root, "loose", "A.wav"), 2, "A", "T", "Techno")
    pl.Organizer(pl.Options(root=root, online=False, bpm_folders=False, dedupe=False)).run()
    moved = next(p for p in pl.Organizer(pl.Options(root=root)).audio_files() if os.path.basename(p) == "A.wav")
    away = moved + ".away"
    os.rename(moved, away)
    _, errs = pl.undo_last(root)
    assert errs and pl.list_runs(root)
    os.rename(away, moved)
    _, errs = pl.undo_last(root)
    assert not errs and os.path.exists(original)

    # Later user tag edits are never overwritten by Undo.
    root = os.path.join(TMP, "undo-tags")
    track = make(os.path.join(root, "House", "House", "A.wav"), 2, "A", "Before", "House", "djsoundtop.com")
    pl.Organizer(pl.Options(root=root, online=False, bpm_folders=False, dedupe=False)).run()
    f = WAVE(track)
    f.tags.delall("TIT2")
    f.tags.add(TIT2(encoding=3, text=["User edit"]))
    f.save()
    _, errs = pl.undo_last(root)
    assert errs and read_info(track)["title"] == "User edit" and pl.list_runs(root)

    # A truncated final UTF-8 row leaves all complete rows readable.
    log = os.path.join(TMP, "truncated.csv")
    with open(log, "wb") as fh:
        fh.write('mover,"a","b"\nquarentena,"ç'.encode("utf-8")[:-1])
    assert pl._read_log_rows(log) == [["mover", "a", "b"]]


def test_audit_7z_update_and_dialogs():
    import hashlib
    import io
    from unittest.mock import patch
    from PySide6.QtWidgets import QApplication, QPushButton
    from organizador import atualizacoes, gui
    from organizador.janelas import HistoryDialog, PlanDialog

    class Listed:
        returncode, stdout = 0, "Size = 10\nPacked Size = 5\n"
    class Proc:
        returncode = 0
        def communicate(self, timeout=None): return (b"", b"")
    seen = {}
    def fake_run(*args, **kwargs):
        seen["run"] = kwargs
        return Listed()
    def fake_popen(*args, **kwargs):
        seen["popen"] = kwargs
        return Proc()
    with patch.object(pl.subprocess, "run", side_effect=fake_run), \
         patch.object(pl.subprocess, "Popen", side_effect=fake_popen):
        org = object.__new__(pl.Organizer)
        org.cancel = type("C", (), {"is_set": lambda self: False})()
        org._extracted_members = org._extracted_bytes = 0
        org.root = TMP
        org._un7z("7z.exe", "x.7z", "out")
    assert seen["run"]["stdin"] is pl.subprocess.DEVNULL and seen["popen"]["stdin"] is pl.subprocess.DEVNULL
    org._extracted_members = org._extracted_bytes = 0
    try:
        org._check_archive(int(1.9 * (1 << 30)), 1, 1024)
        raise AssertionError("a sub-2GB compression bomb was accepted")
    except RuntimeError:
        pass

    payload = b"installer"
    class Download(io.BytesIO):
        headers = {"Content-Length": str(len(payload))}
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def geturl(self): return "https://github.com/x/setup.exe"
    with patch.object(atualizacoes.urllib.request, "urlopen", return_value=Download(payload)):
        try:
            atualizacoes.download("https://github.com/x/setup.exe", "0" * 64)
            raise AssertionError("wrong installer hash accepted")
        except ValueError:
            pass
    class JsonList(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *args): return False
    with patch.object(atualizacoes.urllib.request, "urlopen", return_value=JsonList(b"[]")):
        assert atualizacoes.check() is None

    app = QApplication.instance() or QApplication([])
    plan = PlanDialog([("move", "C:\\x.wav", "C:\\y.wav")], "C:\\")
    assert plan.run_btn.isDefault()
    history = HistoryDialog([("20260101-000000-x", {"mover": 1})])
    undo = next(b for b in history.findChildren(QPushButton) if b.text() == pl.t("history.undo"))
    assert undo.isDefault()
    called = []
    fake = type("W", (), {"shutdown_toggle": type("T", (), {"isChecked": lambda self: True})()})()
    with patch.object(gui, "shutdown_pc", side_effect=lambda n: called.append(n)):
        gui.Window._maybe_shutdown(fake, "run", ["error"])
    assert not called
    window = gui.Window()
    window._plan = [("move", os.path.join(TMP, "a.wav"), os.path.join(TMP, "b.wav"))]
    window.log.setPlainText("kept log")
    window.build()  # same rebuild used by a language change
    assert not window.btn_plan.isHidden() and window.log.toPlainText() == "kept log"
    fresh_root = os.path.join(TMP, "gui-first-run")
    make(os.path.join(fresh_root, "Techno", "Fresh.wav"), 1, "A", "Fresh", "Techno")
    window.folder.setText(fresh_root)
    assert not window.toggles["only_new"].isEnabled()
    assert not pl.Organizer(pl.Options(root=fresh_root, extract=False, dedupe=False, online=False,
                                       bpm_folders=False, write_tags=False, clean_sites=False,
                                       families=False)).run()[1]
    window._update_new_only_availability()
    assert window.toggles["only_new"].isEnabled()
    window.toggles["only_new"].setChecked(True)
    window.scope_options["write_tags_all"] = True
    assert window.current()[0].write_tags_all
    window.folder.setText(os.path.join(TMP, "gui-other-library"))
    assert not window.toggles["only_new"].isEnabled() and window.toggles["only_new"].isChecked()
    window.folder.setText(fresh_root)
    assert window.toggles["only_new"].isEnabled() and window.toggles["only_new"].isChecked()
    plan.close(), history.close(), window.close()


def test_deep_audit_regressions():
    from unittest.mock import patch
    from organizador.tags import duration, read_info, restore, snapshot

    # Untagged audio still has a duration; same-name recordings of 2 and 30 seconds are not duplicates.
    root = os.path.join(TMP, "untagged-durations")
    paths = []
    for folder, seconds in (("Sem Genero", 2), (os.path.join("Sem Genero", "BPM desconhecido"), 30)):
        p = os.path.join(root, folder, "A - Track.wav")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with wave.open(p, "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(8000)
            w.writeframes(bytes(16000 * seconds))
        assert duration(p) == read_info(p)["duration"] == seconds
        paths.append(p)
    rep, errs = pl.Organizer(pl.Options(root=root, online=False, bpm_folders=False,
                                       write_tags=False, clean_sites=False)).run()
    assert not errs and rep["dups_trashed"] == 0 and all(os.path.exists(p) for p in paths), (rep, errs)

    # Undo must reject a copy that remains readable but has lost all of its audio.
    p = make(os.path.join(TMP, "undo-duration", "A.wav"), 2, "A", "T", "House")
    def broken_restore(temp, _):
        with wave.open(temp, "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(8000)
            w.writeframes(b"")
    with patch.object(pl, "restore", side_effect=broken_restore):
        try:
            pl._safe_restore(p, snapshot(p), "audit")
            raise AssertionError("Undo accepted a zero-length replacement")
        except RuntimeError:
            pass
    assert read_info(p)["duration"] == 2

    # A user's similarly named folder is never treated as an interrupted extraction.
    root = os.path.join(TMP, "staging-owned")
    stage = os.path.join(root, pl.INBOX, "personal.gw-parte")
    os.makedirs(stage)
    sentinel = os.path.join(stage, "keep.txt")
    with open(sentinel, "w") as fh:
        fh.write("mine")
    with zipfile.ZipFile(os.path.join(root, pl.INBOX, "pack.zip"), "w") as z:
        z.writestr("inside.txt", "pack")
    org = pl.Organizer(pl.Options(root=root, online=False))
    org.step_extract()
    assert not org.errors and os.path.exists(sentinel)

    # A quarantine redirected through a junction cannot move files outside the library.
    root = os.path.join(TMP, "quarantine-junction")
    qroot = os.path.join(root, pl.QUARANTINE)
    os.makedirs(qroot)
    open(os.path.join(qroot, pl.QUARANTINE_MARK), "w").close()
    source = make(os.path.join(root, "A.wav"))
    org = pl.Organizer(pl.Options(root=root, online=False))
    with patch.object(pl.os.path, "isjunction", side_effect=lambda path: os.path.normcase(path) == os.path.normcase(qroot),
                      create=True):
        try:
            org.trash(source)
            raise AssertionError("a redirected quarantine was accepted")
        except RuntimeError:
            pass
    assert os.path.exists(source)

    # Completed logs must not displace the last pending Undo log from the retention window.
    data = os.path.join(TMP, "prune-pending")
    runs = os.path.join(data, "execucoes")
    os.makedirs(runs)
    for name in ("1.csv", "2.desfeito.csv", "3.desfeito.csv"):
        open(os.path.join(runs, name), "w").close()
    with patch.object(pl, "KEEP_LOGS", 2), patch.object(pl, "_log_time_key", side_effect=lambda d, f: int(f[0])):
        pl.prune_logs(data)
    assert os.path.exists(os.path.join(runs, "1.csv"))

    # If later tag edits prevent Undo, its earlier move must wait too; a retry can then succeed.
    root = os.path.join(TMP, "undo-edited-moved")
    source = make(os.path.join(root, "loose", "A.wav"), 2, "A", "Before", "Tech House", "djsoundtop.com")
    rep, errs = pl.Organizer(pl.Options(root=root, online=False, bpm_folders=False, dedupe=False)).run()
    assert not errs, errs
    moved = next(p for p in pl.Organizer(pl.Options(root=root)).audio_files() if os.path.basename(p) == "A.wav")
    after = snapshot(moved)
    f = WAVE(moved)
    f.tags.delall("TIT2")
    f.tags.add(TIT2(encoding=3, text=["User edit"]))
    f.save(v2_version=3)
    _, errors = pl.undo_last(root)
    assert errors and os.path.exists(moved) and not os.path.exists(source) and pl.list_runs(root), errors
    _, errors = pl.undo_last(root)
    assert errors and os.path.exists(moved) and not any("não encontrado" in e for e in errors), errors
    restore(moved, after)
    _, errors = pl.undo_last(root)
    assert not errors and os.path.exists(source) and not pl.list_runs(root), errors


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
        test_site_names()
        test_unticked_on_first_run_stay_known()
        test_same_size_new_track()
        test_covers()
        test_covers_all_with_only_new()
        test_old_step_scopes()
        test_review_fixes()
        test_site_covers()
        test_bpm()
        test_audit_names_config_and_online()
        test_audit_pipeline_and_undo()
        test_audit_7z_update_and_dialogs()
        test_deep_audit_regressions()
        print("ok")
    finally:
        if os.environ.get("GROOVEWIZARD_TEST_TMP"):
            for name in os.listdir(TMP):
                if name == ".gitkeep":
                    continue
                p = os.path.join(TMP, name)
                shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else os.remove(p)
        else:
            shutil.rmtree(TMP, ignore_errors=True)
