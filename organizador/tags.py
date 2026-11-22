"""Reading and writing tags (mutagen), plus the name parsing used by dedupe and online lookup."""
import base64
import os
import pickle
import re
import unicodedata

import mutagen
from mutagen.id3 import TCON

from .regras import ALIAS, FOLDER_RULES

AUDIO = {".mp3", ".flac", ".aiff", ".aif", ".wav", ".m4a"}
LOSSLESS = {".flac", ".wav", ".aiff", ".aif"}
ID3_EXT = {".mp3", ".aiff", ".aif", ".wav"}
GENRE_KEYS = ("TCON", "genre", "GENRE", "\xa9gen")

SPAM = re.compile(r"https?:|www\.|\.com\b|\.net\b|\.org\b", re.I)
LIST_SEP = re.compile(r"[;,|]")
VERSION = re.compile(r"[\(\[]\s*(extended|original|radio|club)?\s*(mix|edit|version|extended)\s*[\)\]]", re.I)
# strict mode: only Original/Extended are the same arrangement; Radio Edit / Club Mix stay separate tracks
VERSION_STRICT = re.compile(r"[\(\[]\s*(extended|original)\s*(mix|version)?\s*[\)\]]", re.I)
JUNK = re.compile(r"[\(\[]?\s*(www\.\S+|\S+\.(com|org|net))\s*[\)\]]?|\[whoplaymusic\]|\(\d{4}\)|\(\d+\)$", re.I)
LEADING_NUM = re.compile(r"^\s*(\[[^\]]*\]\s*)?(\d+[A-Za-z]?\s*[-.]\s*)*(\d+[\s.]+)?")  # "01. ", "1A - 145 - ", "[9A, 130] "


def is_audio(name):
    return os.path.splitext(name)[1].lower() in AUDIO


def _open(path):
    try:
        return mutagen.File(path)
    except Exception:
        return None


def raw_genre(path):
    """Genre text exactly as stored (what rekordbox shows), '' if none."""
    f = _open(path)
    if not f or not f.tags:
        return ""
    for k in GENRE_KEYS:
        try:
            if k in f.tags:
                v = f.tags[k]
                v = v.text if hasattr(v, "text") else v
                return " | ".join(str(x) for x in v)
        except Exception:
            pass
    return ""


def normalize_genre(raw):
    """'house; tech house' -> 'House'; site spam / generic -> None. Result is a folder name."""
    if not raw or not raw.strip():
        return None
    first = LIST_SEP.split(raw)[0].strip()
    if SPAM.search(first):
        return None
    first = re.sub(r"^\(\d+\)", "", first).strip()  # ID3v1 "(13)Pop"
    first = first.replace("/", "-").replace("\\", "-")  # Beatport "Techno (Peak Time / Driving)"
    first = re.sub(r'[<>:"?*]', "", first)
    first = re.sub(r"\s+", " ", first).strip(" .").title()
    return ALIAS.get(first, first) or None


def genre_of(path):
    return normalize_genre(raw_genre(path))


def genre_from_folder(path, pack=None):
    """Genre from the folder (or extracted pack) name, for untagged files."""
    for name in filter(None, (os.path.basename(os.path.dirname(path)), pack)):
        for pat, g in FOLDER_RULES:
            if re.search(pat, name, re.I):
                return g
    return None


def write_genre(path, genre):
    """Genre = one value. genre '' removes the tag."""
    fix_tags(path, genre=genre)


def _set_genre(f, ext, genre):
    if ext in ID3_EXT:
        if f.tags is None:
            if not genre:
                return
            f.add_tags()
        f.tags.delall("TCON")
        if genre:
            f.tags.add(TCON(encoding=3, text=[genre]))
    else:
        key = "genre" if ext == ".flac" else "\xa9gen"
        if f.tags is None:
            if not genre:
                return
            f.add_tags()
        if genre:
            f.tags[key] = [genre]
        elif key in f.tags:
            del f.tags[key]


def tag_bpm(path):
    f = _open(path)
    t = f.tags if f else None
    if not t:
        return None
    for k in ("TBPM", "bpm", "BPM", "tmpo"):
        try:
            if k in t:
                v = t[k]
                v = v.text[0] if hasattr(v, "text") else v[0]
                b = float(v)
                return b if 50 <= b <= 250 else None
        except (TypeError, ValueError, KeyError, IndexError):
            return None
    return None


def duration(path):
    f = _open(path)
    return f.info.length if f and f.info else 0.0


# ---------- names: artist / title ----------

def norm(s):
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).casefold()
    return re.sub(r"[\W_]+", " ", s).strip()  # accents dropped, other scripts kept


def artist_title(path):
    """(artist, title) from tags, else from 'Artist - Title' file name; None if neither."""
    a = t = ""
    try:
        f = mutagen.File(path, easy=True)
        if f and f.tags:
            a = (f.tags.get("artist") or [""])[0]
            t = (f.tags.get("title") or [""])[0]
    except Exception:
        pass
    if not (a and t):
        stem = LEADING_NUM.sub("", JUNK.sub("", os.path.splitext(os.path.basename(path))[0]))
        if " - " not in stem:
            return None
        a, t = stem.split(" - ", 1)
    return (a.strip(), t.strip()) if a.strip() and t.strip() else None


def artists_key(a):
    a = re.sub(r"\b(feat|ft|featuring)\b\.?", ",", a, flags=re.I)
    parts = re.split(r",|&|;|/|\bx\b|\band\b|\bvs\b\.?", a, flags=re.I)
    return " + ".join(sorted({norm(p) for p in parts if norm(p)}))


def title_key(t, merge_versions=True):
    t = JUNK.sub("", t)
    # drop "feat. X" but stop before "(... Remix)" so the remix name survives
    t = re.sub(r"[\(\[]\s*(feat|ft)\b[^\)\]]*[\)\]]|\s(feat|ft)\.?\s[^\(\[]*", " ", t, flags=re.I)
    rx = VERSION if merge_versions else VERSION_STRICT
    while rx.search(t):
        t = rx.sub("", t)
    return norm(t)


def track_key(path, merge_versions=True):
    """Same song = same artists (any order, feat ignored) + same title (mix name ignored)."""
    at = artist_title(path)
    if not at:
        return None
    a, t = artists_key(at[0]), title_key(at[1], merge_versions)
    return f"{a} | {t}" if a and t else None


def search_terms(path):
    """(main artist, clean title) for online search."""
    at = artist_title(path)
    if not at:
        return None
    a, t = at
    a = next((p.strip() for p in re.split(r",|&|\bfeat\b|\bft\b|\bx\b", a, flags=re.I) if p.strip()), a.strip())
    t = VERSION.sub("", JUNK.sub("", t))
    t = re.sub(r"[\(\[]\s*(feat|ft)\b[^\)\]]*[\)\]]", "", t, flags=re.I).strip()
    return (a, t) if a and t else None


# ---------- download-site spam in text tags ----------

_DOMAIN = r"(?:https?://)?(?:www\.)?[\w-]+(?:\.[\w-]+)*\.(?:com|net|org|ru|info|to|cc|me|io|pl|club)\b/?\S*?"
# spam = the whole field is a domain, a bracketed domain, a " - domain" suffix, or anything with www./http
_WHOLE = re.compile(r"\s*[\[(]?\s*(?:(?:https?://|www\.)\S+|[\w-]+(?:\.[\w-]+)*\.(?:com|net|org|ru|info)\b/?\S*?)\s*[\])]?\s*", re.I)
_PIECES = re.compile(r"\s*[\[(]\s*" + _DOMAIN + r"\s*[\])]"
                     r"|\s*[-|–—]\s*" + _DOMAIN + r"\s*$"
                     r"|\s*(?:https?://|www\.)\S+", re.I)
_ID3_TEXT = {"TALB", "TIT2", "TPE1", "TPE2", "TPUB", "COMM", "TCOP", "TENC", "TXXX"}
_ID3_URL = {"WXXX", "WOAS", "WOAF", "WPUB", "WCOM", "WORS"}
_OTHER_TEXT = {"album", "title", "artist", "albumartist", "label", "organization", "comment", "description",
               "copyright", "encodedby", "encoder", "\xa9alb", "\xa9nam", "\xa9ART", "aART", "\xa9cmt", "cprt", "\xa9too"}


def strip_sites(text):
    """'Rockin (Extended Mix) - www.site.com' -> 'Rockin (Extended Mix)'; 'site.com' -> ''; 'Love.me' stays."""
    if _WHOLE.fullmatch(text):
        return ""
    out = _PIECES.sub("", text).strip(" -|–—:")
    return out if re.search(r"\w", out) else ""


def _has_site(text):
    return strip_sites(text) != text


def clean_sites(path, write=True):
    """Removes download-site names from album/title/comment/... Returns number of fields changed."""
    if write:
        return fix_tags(path, clean=True)[1]
    f = mutagen.File(path)
    return _clean(f, path, False) if f and f.tags else 0


def _clean(f, path, write):
    changed = 0
    for key in list(f.tags.keys()):
        if os.path.splitext(path)[1].lower() in ID3_EXT:
            fid = key[:4]
            if fid in _ID3_URL:
                changed += 1
                if write:
                    del f.tags[key]
                continue
            frame = f.tags[key]
            if fid not in _ID3_TEXT or not hasattr(frame, "text"):
                continue
            old = [str(x) for x in frame.text]
        else:
            if (key.lower() if isinstance(key, str) else key) not in _OTHER_TEXT and key not in _OTHER_TEXT:
                continue
            old = [str(x) for x in f.tags[key]]
        if not any(_has_site(x) for x in old):
            continue
        new = [c for c in (strip_sites(x) for x in old) if c]
        changed += 1
        if not write:
            continue
        if not new:
            del f.tags[key]
        elif os.path.splitext(path)[1].lower() in ID3_EXT:
            f.tags[key].text = new
        else:
            f.tags[key] = new
    return changed


def fix_tags(path, genre=None, clean=False):
    """genre: None = leave, '' = remove, text = set. One save for both edits. -> (genre_changed, site_fields_changed)."""
    f = mutagen.File(path)
    if f is None:
        raise ValueError("formato nao reconhecido")
    ext = os.path.splitext(path)[1].lower()
    g = 0
    if genre is not None and not (f.tags is None and not genre):
        _set_genre(f, ext, genre)
        g = 1
    s = _clean(f, path, True) if clean and f.tags else 0
    if g or s:
        f.save()
    return g, s


# ---------- backup / restore of the text tags (for Undo) ----------

_PICTURES = ("APIC", "covr", "metadata_block_picture", "PIC")


def _text_keys(f):
    return [k for k in f.tags.keys() if not str(k).startswith(_PICTURES)] if f.tags is not None else []


def snapshot(path):
    """Text tags (no cover art) as a compact string, to put the file back as it was."""
    f = mutagen.File(path)
    if f is None:
        return ""
    id3 = os.path.splitext(path)[1].lower() in ID3_EXT
    data = None if f.tags is None else {k: (f.tags.getall(k) if id3 else list(f.tags[k])) for k in _text_keys(f)}
    return base64.b64encode(pickle.dumps((id3, data), protocol=4)).decode("ascii")


def restore(path, snap):
    """Undo of fix_tags: text tags back to the snapshot. Only reads snapshots this app wrote itself."""
    if not snap:
        return
    id3, data = pickle.loads(base64.b64decode(snap))  # our own run log in %APPDATA%, never external input
    f = mutagen.File(path)
    if f is None:
        raise ValueError("formato nao reconhecido")
    if f.tags is None:
        if not data:
            return
        f.add_tags()
    for k in _text_keys(f):
        if not data or k not in data:
            if id3:
                f.tags.delall(k)
            else:
                del f.tags[k]
    for k, v in (data or {}).items():
        if id3:
            f.tags.setall(k, v)
        else:
            f.tags[k] = v
    f.save()
