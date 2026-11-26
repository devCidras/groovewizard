"""Feature scenarios using the same temporary library and WAV fixtures as test_pipeline."""
import os
import shutil
import threading
from pathlib import Path
from unittest.mock import patch
from xml.etree.ElementTree import Element, SubElement, ElementTree

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog

from organizador import biblioteca as lib, pipeline as pl, radar
from organizador.dj_ui import ReviewDialog, SetDialog, TrackHistoryDialog, perform
from organizador.janelas import PlanDialog
from organizador.radar_ui import RadarPage
from organizador.tags import read_info


def check_catalogue_and_export_regressions(tmp, make):
    root = Path(tmp) / "catalogue and USB"
    marker = make(str(root / "_Intro Tool.wav"), artist="Nina Kraviz")
    only_title = make(str(root / "02.wav"), title="Sunrise")
    long_name = "x" * 251 + ".wav"
    long_path = make(str(root / long_name))
    broken = root / "Broken.mp3"
    broken.touch()
    make(str(root / "_private" / "private.wav"))
    external = Path(make(str(Path(tmp) / "other library" / "Other.wav")))
    alias, nested = Path(tmp) / "music alias", root / "outside"
    if os.name == "nt":
        from _winapi import CreateJunction
        CreateJunction(str(root), str(alias))
        CreateJunction(str(external.parent), str(nested))
    else:
        alias.symlink_to(root, target_is_directory=True)
        nested.symlink_to(external.parent, target_is_directory=True)
    opts = pl.Options(root=str(alias))
    cancel = threading.Event()
    tracks = lib.catalogue(opts, cancel)[0]
    by_name = {Path(track.path).name: track for track in tracks.values()}
    assert set(by_name) == {Path(marker).name, Path(only_title).name, long_name, broken.name}
    assert by_name["_Intro Tool.wav"].artist == "Nina Kraviz" and by_name["02.wav"].title == "Sunrise"
    assert not lib.library_file(pl.Organizer(opts), str(alias / "outside" / external.name))

    xml = Element("DJ_PLAYLISTS")
    collection = SubElement(xml, "COLLECTION")
    playlist = SubElement(SubElement(xml, "PLAYLISTS"), "NODE", Type="1", Name="Sunset", KeyType="1")
    for path in (marker, only_title):
        uri = (alias / Path(path).name).as_uri()
        SubElement(collection, "TRACK", Location=uri)
        SubElement(playlist, "TRACK", Key=uri)
    file = Path(tmp) / "locations-only.xml"
    ElementTree(xml).write(file, encoding="utf-8")
    saved = lib.import_playlists(str(alias), file)
    assert saved["tracks"] == {lib.playlist_path(str(alias / Path(p).name)): ["Sunset"] for p in (marker, only_title)}

    app = QApplication.instance() or QApplication([])
    bad = by_name["Broken.mp3"]
    dialog = SetDialog(opts, [bad])
    assert not dialog.table.item(0, 0).flags() & Qt.ItemIsUserCheckable and not dialog.send.isEnabled()
    dialog.close()
    target = Path(tmp) / "USB regressions"
    target.mkdir()
    try:
        lib.export_set(opts, [by_name[long_name], bad], target, cancel)
    except ValueError as e:
        assert bad.path.endswith(broken.name) and broken.name in str(e)
    else:
        raise AssertionError("Included a known unreadable file")
    assert not list(target.iterdir())
    result = Path(lib.export_set(opts, [by_name[long_name]], target, cancel))
    name = result.read_text(encoding="utf-8").splitlines()[1]
    assert name.startswith("001 - ") and name.endswith(".wav") and len(name) == 255
    assert (result.parent / name).read_bytes() == Path(long_path).read_bytes()
    # A stale catalogue with the same size and mtime must not publish a corrupt copy.
    old = Path(long_path).stat()
    Path(long_path).write_bytes(bytes(old.st_size))
    os.utime(long_path, ns=(old.st_atime_ns, old.st_mtime_ns))
    try:
        lib.export_set(opts, [by_name[long_name]], target, cancel, "Broken set")
    except ValueError as e:
        assert long_name in str(e)
    else:
        raise AssertionError("Published an unreadable copy from a stale catalogue")
    assert list(target.iterdir()) == [result.parent]


def check_dj_tools(tmp, make):
    root = Path(tmp) / "DJ tools"
    a = make(str(root / "House" / "Café.wav"), 3, "Ana Solar", "Luz", "House")
    b = str(root / "_entrada" / "Café.wav")
    Path(b).parent.mkdir()
    shutil.copyfile(a, b)
    missing = make(str(root / "Loose" / "Artist - Untagged.wav"))
    broken = root / "Damaged.mp3"
    broken.write_bytes(b"broken")
    opts = pl.Options(root=str(root), families=False)
    cancel = threading.Event()
    catalog = lib.catalogue(opts, cancel, duplicates=True)
    tracks, pairs, details, snapshot = catalog
    assert pairs == {b: a} and details[b].identical(details[a])
    assert "report_no_genre" in tracks[missing].problems and "report_unreadable" in tracks[str(broken)].problems

    xml = Element("DJ_PLAYLISTS")
    coll = SubElement(xml, "COLLECTION")
    for k, p in (("1", a), ("2", b)):
        SubElement(coll, "TRACK", TrackID=k, Location=Path(p).as_uri().replace("file:///", "file://localhost/"))
    playlists = SubElement(SubElement(xml, "PLAYLISTS"), "NODE", Name="ROOT", Type="0")
    folder = SubElement(playlists, "NODE", Name="Noite", Type="0")
    p1 = SubElement(folder, "NODE", Name="Warm-up", Type="1", KeyType="0")
    SubElement(p1, "TRACK", Key="1")
    p2 = SubElement(playlists, "NODE", Name="Sunset", Type="1", KeyType="1")
    SubElement(p2, "TRACK", Key=Path(a).as_uri())
    filename = root.parent / "rekordbox.xml"
    ElementTree(xml).write(filename, encoding="utf-8", xml_declaration=True)
    saved = lib.import_playlists(str(root), filename)
    assert saved["tracks"][lib.playlist_path(a)] == ["Noite / Warm-up", "Sunset"]
    assert saved["tracks"][lib.playlist_path(b)] == []
    assert lib.playlist_description(saved, b) != lib.playlist_description(saved, missing)
    assert lib.saved_map(str(root), lib.PLAYLIST_FILE) == saved

    app = QApplication.instance() or QApplication([])
    plan = PlanDialog([("dup", b, a)], str(root), details=details)
    assert "Sunset" in plan.pair.text() and "(2)" in plan.pair.text() and "(0)" in plan.pair.text()
    queue = ReviewDialog(opts, catalog)
    row = next(i for i, issue in enumerate(queue.issues) if issue[0].path == missing)
    queue.table.setCurrentCell(row, 1)
    queue.defer()
    assert queue.table.isRowHidden(row)
    queue.later.setChecked(True)
    assert not queue.table.isRowHidden(row)
    queue.defer()
    assert queue.table.isRowHidden(row)
    assert perform(queue, "check", lambda _: 123) == 123
    queue.close()
    lib.edit_metadata(opts, tracks[missing], "Artista", "Faixa", "Techno")
    edited = read_info(missing)
    assert (edited["artist"], edited["title"], edited["genre"]) == ("Artista", "Faixa", "Techno")
    assert not pl.undo_last(str(root))[1] and read_info(missing)["genre"] == ""

    usb = Path(tmp) / "USB fixture"
    usb.mkdir()
    d = SetDialog(opts, [tracks[a], tracks[b]])
    d.table.item(1, 0).setCheckState(Qt.Checked)
    d.table.item(0, 0).setCheckState(Qt.Checked)
    d.search.setText("no match")
    assert d.table.isRowHidden(0) and list(d.selected) == [1, 0]
    copied = Path(lib.export_set(opts, [d.tracks[i] for i in d.selected], usb, cancel, "Weekend"))
    names = copied.read_text(encoding="utf-8").splitlines()
    assert names == ["#EXTM3U", "001 - Café.wav", "002 - Café.wav"]
    for name in names[1:]:
        assert (copied.parent / name).read_bytes() == Path(a).read_bytes()
    try:
        lib.export_set(opts, [tracks[a]], usb, cancel, "Weekend")
        assert False, "overwrote an existing export"
    except FileExistsError:
        pass
    stop = threading.Event()
    stop.set()
    try:
        lib.export_set(opts, [tracks[a]], usb, stop, "Cancelled")
        assert False
    except pl.Cancelled:
        pass
    assert list(usb.iterdir()) == [copied.parent]
    class StopDuringCopy:
        def is_set(self):
            return any(path.stat().st_size > 0 for path in usb.glob(".groovewizard-*/*.wav"))
    try:
        lib.export_set(opts, [tracks[a], tracks[b]], usb, StopDuringCopy(), "Interrupted")
        assert False, "published a partial set"
    except pl.Cancelled:
        pass
    assert list(usb.iterdir()) == [copied.parent]
    d.close()

    org = pl.Organizer(opts)
    with pl.library_lock(str(root)):
        try:
            assert org.trash(b) and org.trash(missing)
        finally:
            org._log.close()
    entries = pl.track_history(opts)
    event = next(e for e in entries if e.source == b and e.restorable)
    history = TrackHistoryDialog(opts, entries)
    history.search.setText("Café")
    assert history.restore.isEnabled()
    Path(b).write_bytes(b"occupied")
    try:
        pl.restore_track(opts, event)
        assert False, "overwrote a new file"
    except ValueError:
        pass
    assert Path(b).read_bytes() == b"occupied"
    Path(b).unlink()
    assert pl.restore_track(opts, event) == b and not Path(missing).exists()
    assert next(e for e in pl.track_history(opts) if e.run == event.run and e.row == event.row).status == "undone"
    rep, errors = pl.undo_last(str(root))
    assert not errors and rep["undo_from_quarantine"] == 1 and Path(missing).is_file()
    history.close()
    plan.close()

    sample = b"<rss><channel><item><title>Ana Solar releases Porto DJ set</title><link>https://example.org/news</link><pubDate>Thu, 26 Nov 2026 13:00:00 GMT</pubDate></item></channel></rss>"
    news = radar.parse_feed(sample, "DJ Mag")
    assert news[0]["date"] and set(news[0]["groups"]) == {"portugal", "music"}
    index = radar.artist_index(tracks.values())
    assert radar.mentions(news[0]["text"], index, {1, 2, 3}) == {"ana solar"}
    assert radar.mentions("ana solaris", index, {2}) == set()
    with patch.object(radar, "CACHE", str(root.parent / "news.json")), patch.object(
            radar, "fetch_feed", side_effect=lambda source: [dict(n, source=source) for n in news]):
        first, errors = radar.refresh_news()
        assert not errors and len(first) == len(radar.FEEDS)
        with patch.object(radar, "fetch_feed", side_effect=OSError("offline")):
            again, errors = radar.refresh_news()
        assert first == again and len(errors) == len(radar.FEEDS)
        page = RadarPage(lambda: opts)
        # Run the actual refresh and index callbacks synchronously, against the fixture library.
        with patch.object(page, "background", side_effect=lambda fn, signal: signal.emit(fn())):
            page.refresh(True)
        assert page.table.rowCount() == 1 and page.local.isEnabled() and not page.index_error
        page.mine.setChecked(True)
        page.category.setCurrentIndex(page.category.findData("portugal"))
        page.city.setText("Porto")
        assert page.table.rowCount() == 1
        assert set(page.matches[0][1]) == {a, b}
        page.city.setText("Lisboa")
        assert page.table.rowCount() == 0 and not page.open.isEnabled()
        page.close()
