"""Regression checks for Radar indexing, location filtering and last-good news batches."""
import builtins
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from mutagen.id3 import TPE1
from mutagen.wave import WAVE
from PySide6.QtWidgets import QApplication

from organizador import biblioteca, pipeline as pl, radar, tags
from organizador.radar_ui import RadarPage


def check_radar_review(tmp, make):
    root = Path(tmp) / "radar-review"
    both = make(str(root / "multi.wav"), 1, "Helena Hauff", "Live")
    media = WAVE(both)
    media.tags.setall("TPE1", [TPE1(encoding=3, text=["Helena Hauff", "DJ Stingray"])])
    media.save()
    duo = make(str(root / "duo.wav"), 1, "Artist One & Artist Two", "Set")
    partial = make(str(root / "untitled.wav"), 1, "Ana Solar")
    opts = pl.Options(root=str(root), online=False)
    tracks = biblioteca.catalogue(opts, threading.Event(), background_index=True)[0]
    assert tracks[both].artists == ("Helena Hauff", "DJ Stingray")
    index = radar.artist_index(tracks.values())
    for name, path in (("helena hauff", both), ("dj stingray", both), ("artist one", duo),
                       ("artist two", duo), ("artist one artist two", duo), ("ana solar", partial)):
        assert index[name] == {path}, name

    app = QApplication.instance() or QApplication([])
    rss = b"<rss><channel><item><title>DJ Stingray set</title><link>https://example.test/set</link></item></channel></rss>"
    with patch.object(radar, "cached_news", return_value={}):
        page = RadarPage(lambda: opts)
    page.tracks, page.index = tracks, index
    page.news_ready(({"DJ Mag": {"articles": radar.parse_feed(rss, "DJ Mag"), "updated": 1}}, []))
    page.mine.setChecked(True)
    assert page.matches[0][1] == [both] and page.local.isEnabled()
    credits = page.table.item(0, 3).text()
    assert "DJ Stingray" in credits and "Helena Hauff" in credits
    page.close()

    # Hold the real audio file open inside a background scan. A foreground preview and
    # rename must both succeed, and the old index entry must be discarded afterwards.
    acquired, resume = threading.Event(), threading.Event()

    @contextmanager
    def hold_first_open(path, *args, **kwargs):
        with builtins.open(path, *args, **kwargs) as file:
            if str(path) == partial and not acquired.is_set():
                acquired.set()
                assert resume.wait(15)
            yield file

    with patch.object(tags, "open", create=True, side_effect=hold_first_open), ThreadPoolExecutor(1) as pool:
        cached = {path: track for path, track in tracks.items() if path != partial}
        future = pool.submit(biblioteca.catalogue, opts, threading.Event(), previous=cached, background_index=True)
        try:
            assert acquired.wait(10)
            pl.Organizer(opts).preview()
            with pl.library_lock(str(root)):
                os.rename(partial, root / "renamed.wav")
                os.rename(duo, root / "renamed-duo.wav")
        finally:
            resume.set()
        current = future.result()[0]
        assert partial not in current and duo not in current and current[both] is cached[both]

    assert radar.in_portugal("dj set in oporto")
    assert radar.in_portugal("dj set in oporto", "porto")
    assert radar.in_portugal("dj set in porto", "oporto")
    assert not radar.in_portugal("dj set in porto alegre brazil")
    assert not radar.in_portugal("dj set in porto alegre brazil", "porto")
    assert radar.in_portugal("tour from porto alegre to porto", "porto")
    assert radar.in_portugal("festival in lisbon", "lisboa")
    assert radar.in_portugal("festival in sintra", "sintra")
    rss = b"<rss><channel><item><title>Set in Oporto</title><link>https://example.test/porto</link></item></channel></rss>"
    news = radar.parse_feed(rss, "DJ Mag")
    assert "portugal" in news[0]["groups"]
    empty = radar.parse_feed(b"<rss><channel><item><title>Missing link</title></item></channel></rss>", "DJ Mag")

    with patch.object(radar, "CACHE", str(root / "news.json")), patch.dict(radar.FEEDS, {"DJ Mag": ""}, clear=True):
        with patch.object(radar, "fetch_feed", return_value=news):
            first, errors = radar.refresh_news()
        assert not errors
        with patch.object(radar, "fetch_feed", return_value=empty):
            second, errors = radar.refresh_news()
        assert errors == ["DJ Mag"] and second == first == radar.cached_news()
