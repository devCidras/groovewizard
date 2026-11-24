"""Covers that are not the track's: ads of download sites and generic store art (Beatport charts...).

Each is known by a 32x32 RGB thumbnail, so another size or JPEG quality still matches. Measured on 5 351 real covers:
other sizes / qualities of an image differ by at most 1.9 on average and 21 at the worst point; the real cover closest
to a listed one by 4.3 on average, and none by less than 75 at the worst point (a different small text gives 110+)."""
import base64
import json
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

SIDE = 32
MAX_MEAN, MAX_POINT = 2.5, 40
MIN_ARTISTS = 5  # the same cover on this many artists is offered in 'Repeated covers' (compilations are there too)
SHIPPED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recursos", "capas_sites.json")


def fingerprint(data):
    """bytes of the SIDE x SIDE RGB thumbnail, or None when it isn't an image."""
    im = QImage.fromData(data)
    if im.isNull():
        return None
    im = im.scaled(SIDE, SIDE, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).convertToFormat(QImage.Format_RGB888)
    raw, step = bytes(im.constBits()), im.bytesPerLine()
    return b"".join(raw[y * step:y * step + SIDE * 3] for y in range(SIDE))


def same(a, b):
    total, limit = 0, MAX_MEAN * len(a)
    for x, y in zip(a, b):
        d = abs(x - y)
        total += d
        if d > MAX_POINT or total > limit:
            return False
    return True


def _load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            prints = [base64.b64decode(x) for x in json.load(fh)]
        return [p for p in prints if len(p) == SIDE * SIDE * 3]
    except (OSError, ValueError, TypeError):
        return []


class SiteCovers:
    """is_site(image bytes): shipped list + the ones the user ticked in 'Repeated covers' (kept in `marked_path`)."""

    def __init__(self, marked_path):
        self.path = marked_path
        self.shipped, self.marked = _load(SHIPPED), _load(marked_path)
        self._seen = {}  # image digest -> bool: each different image is decoded once

    def is_site(self, data):
        from .tags import cover_digest
        k = cover_digest(data)
        if k not in self._seen:
            f = fingerprint(data)
            self._seen[k] = bool(f) and any(same(f, x) for x in self.shipped + self.marked)
        return self._seen[k]

    def save_marked(self, prints):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump([base64.b64encode(p).decode() for p in prints], fh)
        os.replace(tmp, self.path)


def preview(fp):
    """The fingerprint as an image (for covers marked before that aren't in this library now)."""
    return QImage(fp, SIDE, SIDE, SIDE * 3, QImage.Format_RGB888).copy()


def repeated(covers, site):
    """covers: iterable of (image bytes, artist). -> [(fingerprint, small QImage, tracks, artists)] of images used by
    many artists and not in the shipped list, most artists first: the user tells ads from compilations.
    Images are dropped as they are read: only artists, counts and (from the 2nd artist on) a small preview are kept."""
    from .tags import cover_digest
    by_image = {}  # digest -> [tracks, artists, fingerprint, preview]
    for data, artist in covers:
        e = by_image.setdefault(cover_digest(data), [0, set(), None, None])
        e[0] += 1
        e[1].add(artist.casefold())
        if len(e[1]) == 2 and e[2] is None:
            e[2] = fingerprint(data) or b""
            if e[2]:
                e[3] = QImage.fromData(data).scaled(140, 140, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    groups = []
    for n, artists, f, small in sorted(by_image.values(), key=lambda e: -len(e[1])):
        if not f or any(same(f, x) for x in site.shipped):
            continue
        g = next((g for g in groups if same(f, g[0])), None)
        if g:
            g[2] += n
            g[3] |= artists
        else:
            groups.append([f, small, n, set(artists)])
    return sorted(((f, im, n, len(a)) for f, im, n, a in groups if len(a) >= MIN_ARTISTS), key=lambda g: -g[3])
