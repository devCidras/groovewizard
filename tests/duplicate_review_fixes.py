"""Regression checks for decisions carried from the DJ review box to the organizer."""
import os
import shutil
import threading
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QDialog

from organizador import biblioteca as lib, pipeline as pl
from organizador.dj_ui import ReviewDialog
from organizador.janelas import PlanDialog


def check_duplicate_review_fixes(tmp, make):
    app = QApplication.instance() or QApplication([])
    owner = QDialog()
    cancel = threading.Event()
    root = Path(tmp) / "held-duplicates"
    keep = make(str(root / "House" / "Kept.wav"), 4, "Band", "Title", "House")
    inbox = root / "_entrada"
    inbox.mkdir()
    a = shutil.copyfile(keep, str(inbox / "A.wav"))
    b = shutil.copyfile(keep, str(inbox / "B.wav"))
    opts = pl.Options(root=str(root), families=False, extract=False, write_tags=False, clean_sites=False,
                      online=False, bpm_folders=False)
    old_preview = pl.Organizer(opts)
    old_preview.preview()
    catalog = lib.catalogue(opts, cancel, duplicates=True)
    queue = ReviewDialog(opts, catalog, owner)
    row = next(i for i, issue in enumerate(queue.issues) if issue[0].path == b and issue[1] == "dup")
    queue.table.setCurrentCell(row, 1)
    queue.defer()
    row = next(i for i, issue in enumerate(queue.issues) if issue[0].path == a and issue[1] == "dup")
    queue.table.setCurrentCell(row, 1)
    shown = []
    def close_comparison(dialog):
        shown.extend(dialog.paths)
        assert not dialog.swap.isEnabled()  # this keeper also belongs to the deferred pair
        return QDialog.Rejected
    with patch.object(PlanDialog, "exec", close_comparison):
        queue.compare()
    assert shown == [a]
    assert queue.next_btn.isEnabled() == any(
        not queue.table.isRowHidden(i) and issue[0].path != a
        for i, issue in enumerate(queue.issues) if i > row)
    if queue.next_btn.isEnabled():
        with patch.object(queue.audio, "play") as player:
            queue.next_track()
        assert player.call_count == 1 and player.call_args.args[0] != a
    queue.later.setChecked(True)
    assert not queue.next_btn.isEnabled() and not queue.compare_btn.isEnabled()
    queue.close()
    queue.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    preview = pl.Organizer(opts)
    assert preview.preview()["dups_pending"] == 1 and preview.dup_best == {a: keep}
    # Even a review made before the decision cannot apply it afterwards.
    report, errors = pl.Organizer(opts, reviewed_duplicates={b: keep}).run(old_preview.snapshot, duplicates_only=True)
    assert not errors and not report["dups_trashed"] and os.path.isfile(b)
    report, errors = pl.Organizer(opts).run()
    assert not errors and report["dups_trashed"] == 1
    moved = str(root / "House" / "B.wav")
    assert os.path.isfile(moved) and os.path.isfile(keep)
    # Files moved by the organizer are still deferred on a later invocation.
    assert not pl.Organizer(opts).preview()["dups_pending"]
    write_json = pl._write_json
    transient_errors = []
    def write_with_busy_preference(path, value):
        if Path(path).name == pl.DEFERRED_FILE and not transient_errors:
            transient_errors.append(path)
            raise PermissionError("settings temporarily busy")
        return write_json(path, value)
    with patch.object(pl, "_write_json", side_effect=write_with_busy_preference):
        _, undo_errors = pl.undo_last(str(root))
    assert len(undo_errors) == len(transient_errors) == 1 and os.path.isfile(b)
    preview = pl.Organizer(opts)
    assert preview.preview()["dups_pending"] == 1 and preview.dup_best == {a: keep}
    report, errors = pl.Organizer(opts).run()
    assert not errors and report["dups_trashed"] == 1 and os.path.isfile(moved)
    queue = ReviewDialog(opts, lib.catalogue(opts, cancel, duplicates=True), owner)
    queue.later.setChecked(True)
    assert queue.current()[0].path == moved and queue.current()[1] == "dup"
    queue.defer()
    queue.close()
    owner.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert pl.Organizer(opts).preview()["dups_pending"] == 1

    # Change one PCM sample after Preview, keeping the same tags, path, size and modified time.
    for source in ("loser", "keeper"):
        for mode in ("inbox", "preview"):
            root = Path(tmp) / ("same-stat-" + source + "-" + mode)
            keep = make(str(root / "House" / "Original.wav"), 6, "Band", "Tune", "House")
            (root / "_entrada").mkdir()
            other = shutil.copyfile(keep, str(root / "_entrada" / "Copy.wav"))
            opts.root = str(root)
            if mode == "inbox":
                _, pairs, _, snapshot = lib.catalogue(opts, cancel, duplicates=True)
            else:
                org = pl.Organizer(opts)
                org.preview()
                pairs, snapshot = org.dup_best, org.snapshot
            assert pairs == {other: keep}
            changed = other if source == "loser" else keep
            st = os.stat(changed)
            with open(changed, "r+b") as f:
                f.seek(4096)
                f.write(b"\x01")
            os.utime(changed, ns=(st.st_atime_ns, st.st_mtime_ns))
            report, errors = pl.Organizer(opts, reviewed_duplicates=pairs).run(snapshot, duplicates_only=(mode == "inbox"))
            assert errors and not report["dups_trashed"] and report["dups_review"] == 1
            assert len(list(pl.Organizer(opts).audio_files())) == 2
