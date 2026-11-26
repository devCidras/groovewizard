"""Search, selective quarantine recovery and isolation between separate archive imports."""
import csv
import os
import zipfile
from pathlib import Path
from unittest.mock import patch

from organizador import pipeline as pl


def check_history_fixes(tmp):
    base = Path(tmp) / "history-regressions"
    base.mkdir()

    def library(name):
        path = base / name
        path.mkdir()
        return path, pl.Options(root=str(path))

    def quarantine(opts, path):
        org = pl.Organizer(opts)
        assert org.trash(str(path))
        org._log.close()
        return org

    for legacy in (False, True):
        root, opts = library("legacy-extract" if legacy else "extract")
        pack = root / pl.INBOX / "Weekend"
        pack.mkdir(parents=True)
        original = pack / "First.wav"
        original.write_bytes(b"old pack")
        quarantine(opts, original)
        pack.rmdir()
        with zipfile.ZipFile(root / "Weekend.zip", "w") as archive:
            archive.writestr("Second.wav", b"new pack")
            archive.writestr("notes.txt", b"notes")
        org = pl.Organizer(opts)
        org.step_extract()
        assert org.move(str(pack / "Second.wav"), str(root / "House"))
        org._log.close()
        if legacy:
            path = Path(org.data, "execucoes", org.run_id + ".csv")
            rows = pl._read_log_rows(path)
            rows[0] = rows[0][:3]
            with path.open("w", newline="", encoding="utf-8") as out:
                csv.writer(out).writerows(rows)
        event = next(e for e in pl.track_history(opts) if e.restorable)
        pl.restore_track(opts, event)
        assert original.read_bytes() == b"old pack"
        rep, errors = pl.undo_last(str(root))
        assert not errors and rep["undo_extract"] == 1, errors
        assert original.read_bytes() == b"old pack"
        reclaimed = root / pl.QUARANTINE / org.run_id / "_extracoes_desfeitas" / "Weekend"
        assert (reclaimed / "Second.wav").read_bytes() == b"new pack"
        # For a legacy log only files demonstrably returned by this run belong to it.
        assert ((pack if legacy else reclaimed) / "notes.txt").is_file()

    root, opts = library("retention")
    originals = [root / (str(n) + ".wav") for n in range(3)]
    logs = []
    for p in originals:
        p.write_bytes(p.name.encode())
        logs.append(quarantine(opts, p))
    with patch.object(pl, "KEEP_LOGS", 1):
        pl.prune_logs(logs[0].data)
    assert [run for run, _ in pl.list_runs(str(root))] == [logs[-1].run_id]
    history = pl.track_history(opts)
    assert len([e for e in history if e.restorable]) == 3
    pl.restore_track(opts, next(e for e in history if e.source == str(originals[0])))
    assert originals[0].is_file()
    # Simulate a log already discarded by the previous version. Undone extraction leftovers
    # belong in quarantine, even when their enclosing run no longer has a CSV.
    log = Path(logs[1].data, "execucoes", logs[1].run_id + ".csv")
    log.unlink()
    excluded = Path(logs[1].qdir, "_extracoes_desfeitas", "pack", "wrong.wav")
    excluded.parent.mkdir(parents=True)
    excluded.write_bytes(b"leftovers")
    history = pl.track_history(opts)
    assert all(e.destination != str(excluded) for e in history)
    assert [run for run, _ in pl.list_runs(str(root))] == [logs[-1].run_id]
    pl.restore_track(opts, next(e for e in history if e.source == str(originals[1])))
    pl.restore_track(opts, next(e for e in history if e.source == str(originals[2])))
    assert all(p.read_bytes() == p.name.encode() for p in originals)
    assert not pl.list_runs(str(root))

    root, opts = library("interrupted")
    a, b = root / "first.wav", root / "second.wav"
    a.write_bytes(b"A")
    b.write_bytes(b"B")
    org = quarantine(opts, a)
    quarantine(opts, b)
    event = next(e for e in pl.track_history(opts) if e.source == str(a))
    log = Path(org.data, "execucoes", org.run_id + ".csv")
    pl._write_json(str(log) + ".restore.json", [event.row, event.source, event.destination,
                                               pl._file_identity(event.destination)])
    os.rename(event.destination, root / "renamed-after-restore.wav")
    history = pl.track_history(opts)
    assert next(e for e in history if e.source == str(a)).status == "unavailable"
    pl.restore_track(opts, next(e for e in history if e.source == str(b)))
    assert b.read_bytes() == b"B"

    root, opts = library("rename-search")
    org = pl.Organizer(opts)
    a = root / "XX01.wav"
    a.write_bytes(b"original music")
    dst = org.move(str(a), str(root / "House"), "DJ Lina - Aurora.wav")
    assert dst
    org._log.close()
    org = pl.Organizer(opts)
    final = org.move(dst, str(root / "House" / "120"))
    assert final and org.trash(final)
    org._log.close()
    # The original source path can legitimately be re-used by a different file.
    a.write_bytes(b"a later import")
    quarantine(opts, a)
    history = pl.track_history(opts)
    event = next(e for e in history if e.restorable and e.source == final)
    assert "XX01.wav" in event.aliases and "DJ Lina - Aurora.wav" in event.aliases
    other = next(e for e in history if e.restorable and e.source == str(a))
    assert "DJ Lina - Aurora.wav" not in other.aliases

    if os.name == "nt":
        import _winapi
        alias = base / "history-alias"
        _winapi.CreateJunction(str(root), str(alias))
        try:
            linked_opts = pl.Options(root=str(alias))
            entry = next(e for e in pl.track_history(linked_opts) if e.source == str(a) and e.restorable)
            pl.restore_track(linked_opts, entry)
            assert a.read_bytes() == b"a later import"
        finally:
            alias.rmdir()

    root, opts = library("checkpoint-before-close")
    x, y = root / "older.wav", root / "selected.wav"
    x.write_bytes(b"x")
    y.write_bytes(b"y")
    old = quarantine(opts, x)
    new = quarantine(opts, y)
    e = next(e for e in pl.track_history(opts) if e.source == str(y))
    log = Path(new.data, "execucoes", new.run_id + ".csv")
    pl._write_json(str(log) + ".restore.json", [e.row, e.source, e.destination, pl._file_identity(e.destination)])
    os.rename(e.destination, e.source)
    rep, errors = pl.undo_until(str(root), new.run_id)
    assert not errors and not rep and y.read_bytes() == b"y" and not x.exists()
    assert [run for run, _ in pl.list_runs(str(root))] == [old.run_id]
