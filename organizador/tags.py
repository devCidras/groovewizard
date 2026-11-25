"""Reading and writing tags (mutagen), plus the name parsing used by dedupe and online lookup."""
import base64
import copy
import os
import pickle
import re
import unicodedata

import mutagen
from mutagen.aiff import AIFF, AIFFFile, error as AIFFError
from mutagen.flac import FLAC
from mutagen.id3 import TCON
from mutagen.id3._file import find_id3v1
from mutagen.id3._util import BitPaddedInt
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.wave import WAVE

from .regras import ALIAS, FOLDER_RULES

AUDIO = {".mp3", ".flac", ".aiff", ".aif", ".wav", ".m4a"}
LOSSLESS = {".flac", ".wav", ".aiff", ".aif"}
ID3_EXT = {".mp3", ".aiff", ".aif", ".wav"}
GENRE_KEYS = ("TCON", "genre", "GENRE", "\xa9gen")
_MEDIA_EXT = {AIFF: ".aiff", FLAC: ".flac", MP3: ".mp3", MP4: ".m4a", WAVE: ".wav"}
_ID3_FRAME_ID = re.compile(rb"[A-Z0-9]{4}")

SPAM = re.compile(r"https?:|www\.|\.com\b|\.net\b|\.org\b", re.I)
JUNK_TAG_SPAM = SPAM  # a genre tag that is a site
LIST_SEP = re.compile(r"[;,|]")
VERSION = re.compile(r"[\(\[]\s*(extended|original|radio|club)?\s*(mix|edit|version|extended)\s*[\)\]]", re.I)
# strict mode: only Original/Extended are the same arrangement; Radio Edit / Club Mix stay separate tracks
VERSION_STRICT = re.compile(r"[\(\[]\s*(extended|original)\s*(mix|version)?\s*[\)\]]", re.I)
JUNK = re.compile(r"[\(\[]?\s*(www\.\S+|\S+\.(com|org|net)\b)\s*[\)\]]?|\[whoplaymusic\]", re.I)
# "01. ", "1A - 145 - ", "[9A, 130] ", "01 " ; never "2-Step", "50.Cent" or "808_State".
_NUMBER_PREFIX = r"(?:\d{1,3}[A-Za-z]?(?:\s+-\s+|[._)]\s+)|0\d\s+)"
LEADING_NUM = re.compile(r"^\s*(\[[^\]]*\]\s*)?(?:" + _NUMBER_PREFIX + r")*")


def is_audio(name):
    return os.path.splitext(name)[1].lower() in AUDIO


class _AIFFTagReader:
    """Give Mutagen a corrected ID3 header for this read, with no change to the file."""

    def __init__(self, file, tag_offset, size):
        self.file = file
        self.tag_offset = tag_offset
        self.tag_size = BitPaddedInt.to_str(size, width=4)

    def __getattr__(self, name):
        return getattr(self.file, name)

    def read(self, size=-1):
        offset = self.file.tell()
        data = self.file.read(size)
        # Mutagen's ID3Header reads the ten-byte header at the start of the tag.
        if offset == self.tag_offset and len(data) == 10:
            return data[:6] + self.tag_size
        return data


def _id3_frames_fit(file, remaining, version):
    while remaining:
        header = file.read(min(10, remaining))
        remaining -= len(header)
        if header.startswith(b"\0"):
            return not header.strip(b"\0") and not file.read(remaining).strip(b"\0")
        if len(header) != 10 or not _ID3_FRAME_ID.fullmatch(header[:4]):
            return False
        if version == 4 and not BitPaddedInt.has_valid_padding(header[4:8]):
            return False
        size = BitPaddedInt(header[4:8]) if version == 4 else int.from_bytes(header[4:8], "big")
        if not 0 < size <= remaining:
            return False
        file.seek(size, os.SEEK_CUR)
        remaining -= size
    return True


def _load_aiff(file, filename):
    try:
        return AIFF(file, filename=filename)
    except AIFFError:
        # Some exports advertise more ID3 padding than fits in the enclosing AIFF chunk.
        file.seek(0)
        aiff = AIFFFile(file)
        if "ID3" not in aiff:
            raise
        chunk = aiff["ID3"]
        if chunk.offset + chunk.size > min(file.seek(0, os.SEEK_END), aiff.root.size):
            raise
        file.seek(chunk.data_offset)
        header = file.read(10)
        if (len(header) != 10 or header[:3] != b"ID3" or header[3] not in (3, 4)
                or header[4:6] != b"\0\0" or not BitPaddedInt.has_valid_padding(header[6:])):
            raise
        available = chunk.data_size - len(header)
        if not 0 <= available < BitPaddedInt(header[6:]) or not _id3_frames_fit(file, available, header[3]):
            raise
        file.seek(0)
        return AIFF(_AIFFTagReader(file, chunk.data_offset, available), filename=filename)


def _load(path):
    filename = os.fspath(path)
    with open(filename, "rb") as file:
        header = file.read(12)
        file.seek(0)
        if header.startswith(b"fLaC"):
            return FLAC(file, filename=filename)
        if header[4:8] == b"ftyp":
            return MP4(file, filename=filename)
        if header[:4] == b"FORM" and header[8:12] in (b"AIFF", b"AIFC"):
            return _load_aiff(file, filename)
        if header[:4] == b"RIFF" and header[8:12] == b"WAVE":
            return WAVE(file, filename=filename)
        return mutagen.File(file, options=_MEDIA_EXT, filename=filename)


def _open(path):
    try:
        return _load(path)
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
    first = re.sub(r'[<>:"?*\x00-\x1f]', "", first)
    first = re.sub(r"\s+", " ", first).strip(" .").title()
    if first.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                          *(f"LPT{i}" for i in range(1, 10))}:
        first += "_"
    g = ALIAS.get(first, first) or None
    return None if g and g.startswith(("_", ".")) else g  # "_quarentena" etc. are the app's own folders


def genre_of(path):
    return normalize_genre(raw_genre(path))


def genre_from_folder(path, pack=None):
    """Genre from the folder (or extracted pack) name, for untagged files."""
    for name in filter(None, (os.path.basename(os.path.dirname(path)), pack)):
        if name == pack:  # downloaded pack names commonly use scene separators
            name = re.sub(r"[_-]+", " ", name)
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
                b = float(str(v).replace(",", ".").split()[0])
                if 50 <= b <= 250:
                    return b
        except (TypeError, ValueError, KeyError, IndexError):
            continue  # a bad value here: try the next key
    return None


def duration(path):
    f = _open(path)
    return f.info.length if f is not None and f.info else 0.0


# ---------- names: artist / title ----------

def norm(s):
    s = unicodedata.normalize("NFKC", s).casefold()
    s = "".join(c if c.isalnum() or c == "_" or unicodedata.category(c).startswith("M") else " " for c in s)
    return re.sub(r"[\s_]+", " ", s).strip()  # combining marks can change the word in many languages


_ARTIST = {"id3": "TPE1", "vorbis": "artist", "mp4": "\xa9ART"}
_TITLE = {"id3": "TIT2", "vorbis": "title", "mp4": "\xa9nam"}


def _first(tags, key):
    try:
        v = tags.get(key)
    except Exception:
        return ""
    if v is None:
        return ""
    v = v.text if hasattr(v, "text") else v
    return str(v[0]) if v else ""


# ---------- cover art ----------

def _has_cover(f):
    if getattr(f, "pictures", None):  # FLAC
        return True
    tags = f.tags
    if not tags:
        return False
    try:
        return any(str(k).startswith(("APIC", "PIC")) for k in tags.keys()) or bool(tags.get("covr"))
    except Exception:
        return False


MAX_COVER_SIDE = 3000  # px: bigger is a broken or absurd image, never written into a track


def image_type(data):
    """'image/jpeg' / 'image/png' when the bytes are a complete image of sane size, else None (anything else is never
    written into a track)."""
    import struct
    if data[:3] == b"\xff\xd8\xff" and data.rstrip(b"\x00")[-2:] == b"\xff\xd9":  # starts and ends like a JPEG
        i = 2
        while i + 9 < len(data):  # find the frame header (SOFn) for its size
            if data[i] != 0xFF:
                return None
            marker, length = data[i + 1], struct.unpack(">H", data[i + 2:i + 4])[0]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return "image/jpeg" if 0 < w <= MAX_COVER_SIDE and 0 < h <= MAX_COVER_SIDE else None
            i += 2 + length
        return None
    if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR" and data[-8:-4] == b"IEND":
        w, h = struct.unpack(">II", data[16:24])
        return "image/png" if 0 < w <= MAX_COVER_SIDE and 0 < h <= MAX_COVER_SIDE else None
    return None


def cover_digest(data):
    """Short id of an image: Undo takes out only the cover the app put in, never one added later."""
    import hashlib
    return hashlib.sha1(data).hexdigest()[:16]


def pictures(path):
    """Every embedded image's bytes ([] when none or unreadable)."""
    f = _open(path)
    if f is None:
        return []
    out = [p.data for p in getattr(f, "pictures", None) or []]
    for k in f.tags.keys() if f.tags else ():
        if str(k).startswith("APIC"):
            out.append(f.tags[k].data)
        elif k == "covr":
            out += [bytes(c) for c in f.tags[k]]
    return out


def _record_data(record):
    return base64.b64decode(record["data"]) if isinstance(record, dict) else record


def _record_identity(record):
    if not isinstance(record, dict):
        return ("legacy", cover_digest(record))
    return tuple((k, str(record.get(k, ""))) for k in sorted(record) if k not in ("ordinal", "position"))


def picture_records(path):
    """Embedded images with the metadata needed for an exact site-cover Undo."""
    f = _open(path)
    if f is None:
        return []
    out = []
    for p in getattr(f, "pictures", None) or []:  # FLAC
        out.append({"kind": "flac", "data": base64.b64encode(p.data).decode("ascii"), "type": p.type,
                    "mime": p.mime, "desc": p.desc, "width": p.width, "height": p.height,
                    "depth": p.depth, "colors": p.colors})
    for k in f.tags.keys() if f.tags else ():
        if str(k).startswith(("APIC", "PIC")):
            p = f.tags[k]
            out.append({"kind": "id3", "data": base64.b64encode(p.data).decode("ascii"),
                        "encoding": int(p.encoding), "mime": p.mime, "type": int(p.type), "desc": p.desc})
        elif k == "covr":
            for p in f.tags[k]:
                out.append({"kind": "mp4", "data": base64.b64encode(bytes(p)).decode("ascii"),
                            "imageformat": int(getattr(p, "imageformat", 0))})
    seen = {}
    for position, rec in enumerate(out):
        rec["position"] = position
        ident = _record_identity(rec)
        seen[ident] = seen.get(ident, 0) + 1
        rec["ordinal"] = seen[ident]
    return out


def put_back_cover(path, data):
    """Undo of taking a site's cover out, preserving its stored type, description and order."""
    from mutagen.flac import Picture
    from mutagen.id3 import APIC
    from mutagen.mp4 import MP4Cover
    record = data if isinstance(data, dict) else None
    data = _record_data(data)
    png = data[:8] == b"\x89PNG\r\n\x1a\n"
    mime = ("image/png" if png else "image/gif" if data[:4] == b"GIF8"
            else "image/webp" if data[8:12] == b"WEBP" else "image/jpeg")
    f = _load(path)
    if f is None:
        raise ValueError("formato nao reconhecido")
    ext = _MEDIA_EXT[type(f)]
    version = f.tags.version[1] if ext in ID3_EXT and f.tags is not None and hasattr(f.tags, "version") else None
    if ext == ".flac":
        pic = Picture()
        pic.type = record.get("type", 3) if record else 3
        pic.mime = record.get("mime", mime) if record else mime
        pic.desc = record.get("desc", "") if record else ""
        pic.width = record.get("width", 0) if record else 0
        pic.height = record.get("height", 0) if record else 0
        pic.depth = record.get("depth", 0) if record else 0
        pic.colors = record.get("colors", 0) if record else 0
        pic.data = data
        if record:
            keep = list(f.pictures)
            keep.insert(min(int(record.get("position", len(keep))), len(keep)), pic)
            f.clear_pictures()
            for item in keep:
                f.add_picture(item)
        else:
            f.add_picture(pic)
    else:
        if f.tags is None:
            f.add_tags()
        if ext == ".m4a":
            fmt = record.get("imageformat") if record else (MP4Cover.FORMAT_PNG if png else MP4Cover.FORMAT_JPEG)
            covers = list(f.tags.get("covr") or [])
            covers.insert(min(int(record.get("position", len(covers))), len(covers)) if record else len(covers),
                          MP4Cover(data, imageformat=fmt))
            f.tags["covr"] = covers
        else:  # own description: ID3 keeps one image per description
            pic = APIC(encoding=record.get("encoding", 3) if record else 3,
                       mime=record.get("mime", mime) if record else mime,
                       type=record.get("type", 3) if record else 3,
                       desc=record.get("desc", cover_digest(data)) if record else cover_digest(data), data=data)
            if record:
                covers = list(f.tags.getall("APIC"))
                covers.insert(min(int(record.get("position", len(covers))), len(covers)), pic)
                f.tags.delall("APIC")
                for item in covers:
                    f.tags.add(item)
            else:
                f.tags.add(pic)
    _save_cover(f, ext, version)


def set_cover(path, data):
    """Front cover into the file's tags (MP3/WAV/AIFF: ID3 APIC, FLAC: picture block, M4A: covr)."""
    from mutagen.flac import Picture
    from mutagen.id3 import APIC
    from mutagen.mp4 import MP4Cover
    mime = image_type(data)
    if not mime:
        raise ValueError("not a JPEG/PNG image")
    f = _load(path)
    if f is None:
        raise ValueError("formato nao reconhecido")
    if _has_cover(f):
        raise ValueError("already has cover art")  # an existing cover is never replaced
    ext = _MEDIA_EXT[type(f)]
    version = f.tags.version[1] if ext in ID3_EXT and f.tags is not None and hasattr(f.tags, "version") else None
    if ext == ".flac":
        pic = Picture()
        pic.type, pic.mime, pic.desc, pic.data = 3, mime, "Cover", data
        f.add_picture(pic)
    else:
        if f.tags is None:
            f.add_tags()
        if ext == ".m4a":
            fmt = MP4Cover.FORMAT_PNG if mime == "image/png" else MP4Cover.FORMAT_JPEG
            f.tags["covr"] = [MP4Cover(data, imageformat=fmt)]
        else:
            f.tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=data))
    _save_cover(f, ext, version)


def remove_cover(path, digest):
    """Undo of set_cover: takes out only the picture with this digest (the one the app added). Returns True if found."""
    f = _load(path)
    if f is None:
        raise ValueError("formato nao reconhecido")
    ext = _MEDIA_EXT[type(f)]
    version = f.tags.version[1] if ext in ID3_EXT and f.tags is not None and hasattr(f.tags, "version") else None
    found = False
    if getattr(f, "pictures", None):  # FLAC
        keep = [p for p in f.pictures if cover_digest(p.data) != digest]
        if len(keep) != len(f.pictures):
            found = True
            f.clear_pictures()
            for p in keep:
                f.add_picture(p)
    if f.tags:
        for k in list(f.tags.keys()):
            if str(k).startswith(("APIC", "PIC")) and cover_digest(f.tags[k].data) == digest:
                del f.tags[k]
                found = True
            elif k == "covr":
                keep = [c for c in f.tags["covr"] if cover_digest(bytes(c)) != digest]
                if len(keep) != len(f.tags["covr"]):
                    found = True
                    if keep:
                        f.tags["covr"] = keep
                    else:
                        del f.tags["covr"]
    if found:
        _save_cover(f, ext, version)
    return found


def read_info(path):
    """Everything the organizer needs from one file, with a single open: genre text, artist, title, duration."""
    f = _open(path)
    info = {"genre": "", "artist": "", "title": "", "duration": 0.0, "bitrate": 0, "cover": False,
            "format": "", "unreadable": f is None}
    if f is None:
        return info
    ext = info["format"] = _MEDIA_EXT[type(f)]
    info["duration"] = f.info.length if f.info else 0.0
    info["bitrate"] = getattr(f.info, "bitrate", 0) or 0  # bits/s; 0 when the format doesn't say
    info["cover"] = _has_cover(f)
    if not f.tags:
        return info
    kind = "id3" if ext in ID3_EXT else "mp4" if ext == ".m4a" else "vorbis"
    info["artist"], info["title"] = _first(f.tags, _ARTIST[kind]), _first(f.tags, _TITLE[kind])
    for k in GENRE_KEYS:
        try:
            if k in f.tags:
                v = f.tags[k]
                v = v.text if hasattr(v, "text") else v
                info["genre"] = " | ".join(str(x) for x in v)
                break
        except Exception:
            pass
    return info


def artist_title(path, info=None):
    """(artist, title) from tags, else from 'Artist - Title' file name; None if neither."""
    info = info or read_info(path)
    a, t = info["artist"], info["title"]
    if not (a and t):
        stem = LEADING_NUM.sub("", JUNK.sub("", os.path.splitext(os.path.basename(path))[0]))
        if " - " not in stem:
            return None
        a, t = stem.split(" - ", 1)
    return (a.strip(), t.strip()) if a.strip() and t.strip() else None


def artists_key(a):
    a = a.strip()
    # "ft." is a join only after an artist name; it can also start a real name (Ft. Lauderdale).
    a = re.sub(r"\b(feat|ft|featuring)\b\.?",
               lambda m: m.group(0) if not a[:m.start()].strip() else ",", a, flags=re.I)
    parts = re.split(r",|&|;|/|\s+x\s+|\s+(?:and|vs)\.?\s+", a, flags=re.I)  # joins only between names
    keys = {norm(p) for p in parts if norm(p)}
    return " + ".join(sorted(keys)) or unicodedata.normalize("NFKC", a).casefold().strip()


def title_key(t, merge_versions=True):
    t = JUNK.sub("", t)
    # A featured singer can identify a different recording, so keep the name in the key.
    t = re.sub(r"[\(\[]\s*(?:feat|ft)\.?\s*([^\)\]]*)[\)\]]|\s(?:feat|ft)\.?\s+([^\(\[]*)",
               lambda m: " feat " + (m.group(1) or m.group(2) or ""), t, flags=re.I)
    rx = VERSION if merge_versions else VERSION_STRICT
    while rx.search(t):
        t = rx.sub("", t)
    if merge_versions:
        t = re.sub(r"\s*[-–—]\s*(?:extended|original|club|radio)\s+(?:mix|edit|version)\s*$", "", t, flags=re.I)
    else:
        t = re.sub(r"\s*[-–—]\s*(?:extended|original)\s+(?:mix|version)\s*$", "", t, flags=re.I)
    return norm(t)


_REMIX = re.compile(r"[\(\[]([^\)\]]*\b(?:remix|rework|bootleg|vip|dub|refix|flip|edit|mix)\b[^\)\]]*)[\)\]]", re.I)


def _name_title(path):
    stem = LEADING_NUM.sub("", JUNK.sub("", os.path.splitext(os.path.basename(path))[0]))
    return stem.split(" - ", 1)[1] if " - " in stem else ""


_BAD_NAME_LEN = 120  # characters; the full path is checked again before the move
_BARE_VERSION = re.compile(r"\b(?:extended|original|club|radio|dub|instrumental|vocal)\s+(?:mix|edit|version)\b", re.I)
_BAD_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def pack_file_name(path, info):
    """'Artist - Title (Extended Mix).ext' from the tags, for tracks that came out of a pack; None when unsure.
    The version comes from the title tag, else from the current file name; none is invented. If the old name says
    'extended' and the new one would not, the file keeps its name (dedupe prefers Extended by name)."""
    a, t = strip_sites(info.get("artist") or "").strip(), strip_sites(info.get("title") or "").strip()
    if not (a and t):
        return None
    if not _REMIX.search(t):  # 'Groove' in the tag, 'Groove (Extended Mix)' in the file name
        old = os.path.splitext(os.path.basename(path))[0].replace("_", " ")
        if " - " in old:
            old = old.split(" - ", 1)[1]
        else:  # scene name: 01-fisher-losing_it-extended_mix
            tagged_artist = re.sub(r"\s+", r"\\s+", re.escape(a).replace(r"\ ", " "))
            old = re.sub(r"^\s*" + _NUMBER_PREFIX, "", old)
            old = re.sub(r"^" + tagged_artist + r"\s*[-–—]\s*", "", old, flags=re.I)
        found = _REMIX.findall(old) or [m.group(0) for m in _BARE_VERSION.finditer(old)]
        if found:
            v = found[-1].strip()
            t = f"{t} ({v.title() if v == v.lower() else v})"  # scene names are all lower case
    name = _BAD_NAME.sub(" ", f"{a} - {t}")
    name = re.sub(r"\s+", " ", name).strip(" .")[:_BAD_NAME_LEN].strip(" .")
    if not re.search(r"\w", name):
        return None
    if re.search(r"extended", os.path.basename(path), re.I) and not re.search(r"extended", name, re.I):
        return None
    return name + os.path.splitext(path)[1].lower()


# in file names only unmistakable sites: 'www.' / 'http' anywhere, or a .com/.net/.org/.ru/.info domain in brackets
# (stricter than strip_sites for tags: a title like 'Love.me' must never lose words from the name)
_FILE_SITE = re.compile(r"\s*[\[(]\s*(?:www\.)?[\w-]+(?:\.[\w-]+)*\.(?:com|net|org|ru|info)\s*[\])]"
                        r"|\s*[-|–—]?\s*" + r"(?:https?://\S+|www\.[\w-]+(?:\.[\w-]+)*\.[a-z]{2,24}\b(?:/\S*)?)", re.I)
# (with the '-' that glued it on; www.* stops at its top-level domain: 'www.site.com-Extended-Mix' keeps the mix)


# a track number at the start of a file name: '05. ', '01 - ', '01-', '01_', '03) ', '[9A] 05 - ', or '01 ' with a 0.
# '3.14 (AR)', '1-2-3' or '808 State' are not track numbers ('.'/'-' right before a digit, or no separator)
_TRACK_NUM = re.compile(r"^(\s*\[[^\]]*\]\s*)?(?:" + _NUMBER_PREFIX + r")(?=\D)")


def _plain(s):
    """Letters and digits only, no accents, any script ('Баста' stays 'баста')."""
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).casefold()
    return re.sub(r"[\W_]+", "", s)


def clean_file_name(path, artist=""):
    """Same name without the download site and the track number: '05. Artist - Title - www.djsoundtop.com.mp3' ->
    'Artist - Title.mp3'. Nothing is added or guessed. The number stays when the name starts with the artist from the
    tags (the number is part of the artist: '808 State', '6 Sense'). None when nothing would change."""
    stem, ext = os.path.splitext(os.path.basename(path))
    cut = _FILE_SITE.sub("", stem)
    if cut != stem:
        cut = cut.lstrip(" -|–—:")  # 'www.site.com - 05. Artist': the site's separator goes with it
    m = _TRACK_NUM.match(cut)
    if m and not (artist and _plain(artist) and _plain(cut[len(m.group(1) or ""):]).startswith(_plain(artist))):
        cut = (m.group(1) or "") + cut[m.end():]  # only the number: a '[Live] ' or '[9A] ' before it stays
    if cut == stem:  # nothing to take out: never touch the name (not even its spacing)
        return None
    new = re.sub(r"\s+", " ", cut).strip(" .-_|–—:")
    return new + ext.lower() if re.search(r"\w", new) else None


def site_free_name(path):
    """Kept for callers that only want the site out (and the number, see clean_file_name)."""
    return clean_file_name(path)


def version_label(path, info=None):
    """'extended mix', 'radio edit', 'x remix'... from the title (tag, else file name); '' when none."""
    at = artist_title(path, info)
    found = _REMIX.findall(at[1]) if at else []
    return norm(found[-1]) if found else ""


def track_key(path, merge_versions=True, info=None):
    """Same song = same artists (any order, feat ignored) + same title (mix name ignored)."""
    at = artist_title(path, info)
    if not at:
        return None
    a, t = artists_key(at[0]), title_key(at[1], merge_versions)
    # a generic tag title ('Track') must not hide the remix written in the file name ('Track (X Remix)')
    rx = VERSION if merge_versions else VERSION_STRICT
    for token in _REMIX.findall(_name_title(path)):
        nt = norm(token)
        if nt and nt not in norm(at[1]) and not rx.fullmatch(f"({token})"):
            t = f"{t} {nt}"
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
                     # last of a list of artists: 'Iglesias, Sharing-DB.club' -> 'Iglesias'; only unmistakable sites
                     # (.com/.net/.org/.ru/.info, or a hyphen in the name): 'Artist, Toolroom.Club' / 'Love.me' stay
                     r"|\s*,\s*(?:(?:https?://)?(?:www\.)?[\w-]+(?:\.[\w-]+)*\.(?:com|net|org|ru|info)"
                     r"|(?:www\.)?[\w]+-[\w-]+\.[a-z]{2,10})/?\s*$"
                     r"|\s*[-|–—]\s*(?:(?:https?://|www\.)\S+|[\w-]+(?:\.[\w-]+)*\.(?:com|net|org|ru|info)\b/?\S*)\s*$"
                     r"|\s*(?:https?://|www\.)\S+", re.I)
_ID3_TEXT = {"TALB", "TIT2", "TPE1", "TPE2", "TPUB", "COMM", "TCOP", "TENC", "TXXX"}
_ID3_URL = {"WXXX", "WOAS", "WOAF", "WPUB", "WCOM", "WORS"}
_URL_SPAM = re.compile(r"(?:djsoundtop|4djsonline|sharing-db|whoplaymusic|electronicfresh|groovytunes)", re.I)
_OTHER_TEXT = {"album", "title", "artist", "albumartist", "label", "organization", "comment", "description",
               "copyright", "encodedby", "encoder", "\xa9alb", "\xa9nam", "\xa9ART", "aART", "\xa9cmt", "cprt", "\xa9too"}


def strip_sites(text):
    """'Rockin (Extended Mix) - www.site.com' -> 'Rockin (Extended Mix)'; 'site.com' -> ''; 'Love.me' stays.
    A site glued on with a hyphen ('DUMBO-www.site.org') is split off first, so the words before it are kept."""
    text = re.sub(r"(?<=\S)-(?=(?:https?://|www\.))", " - ", text, flags=re.I)
    if _WHOLE.fullmatch(text):
        return ""
    out = _PIECES.sub("", text)
    if out == text:
        return text  # no site: untouched, whatever it looks like ('!!!' is a band)
    out = re.sub(r"\s*[-|–—]\s*[-|–—]\s*", " - ", out)
    out = out.strip(" -|–—:,")  # a site came out: no dangling separator or comma left behind ('Iglesias,')
    return out if re.search(r"\w", out) else ""


def _has_site(text):
    return strip_sites(text) != text


def clean_sites(path, write=True):
    """Removes download-site names from album/title/comment/... Returns number of fields changed."""
    if write:
        return fix_tags(path, clean=True)[1]
    f = _load(path)
    return _clean(f, _MEDIA_EXT[type(f)], False) if f and f.tags else 0


def _clean(f, ext, write):
    id3 = ext in ID3_EXT
    changed = 0
    for key in list(f.tags.keys()):
        if id3:
            fid = key[:4]
            if fid in _ID3_URL:
                frame = f.tags[key]
                value = " ".join(str(getattr(frame, x, "")) for x in ("url", "desc"))
                if _URL_SPAM.search(value):
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
        elif id3:
            f.tags[key].text = new
        else:
            f.tags[key] = new
    return changed


def _id3v1(path):
    """Copy the MP3 trailer verbatim, including values shadowed by ID3v2."""
    with open(path, "rb") as fh:
        _, offset = find_id3v1(fh)
        if not offset:
            return b""
        fh.seek(offset, os.SEEK_END)
        return fh.read()


def _save(f, ext, v2_version=None, *, id3v1=None):
    options = {"v2_version": v2_version} if ext in ID3_EXT and v2_version in (3, 4) else {}
    if id3v1 is None:
        f.save(**options)
        return
    with open(f.filename, "r+b") as fh:
        f.save(fh, v1=0, **options)
        fh.seek(0, os.SEEK_END)
        fh.write(id3v1)


def _save_cover(f, ext, v2_version):
    # ID3v1 has no artwork. Mutagen normally regenerates it from ID3v2 on a save.
    _save(f, ext, v2_version, id3v1=_id3v1(f.filename) if ext == ".mp3" else None)


def fix_tags(path, genre=None, clean=False):
    """genre: None = leave, '' = remove, text = set. One save for both edits. -> (genre_changed, site_fields_changed)."""
    f = _load(path)
    if f is None:
        raise ValueError("formato nao reconhecido")
    ext = _MEDIA_EXT[type(f)]
    version = f.tags.version[1] if ext in ID3_EXT and f.tags is not None and hasattr(f.tags, "version") else None
    g = 0
    if genre is not None and not (f.tags is None and not genre):
        _set_genre(f, ext, genre)
        g = 1
    s = _clean(f, ext, True) if clean and f.tags else 0
    if g or s:
        _save(f, ext, version)
    return g, s


# ---------- backup / restore of the text tags (for Undo) ----------

_PICTURES = ("APIC", "covr", "metadata_block_picture", "PIC")


def _text_keys(f):
    return [k for k in f.tags.keys() if not str(k).startswith(_PICTURES)] if f.tags is not None else []


def _snapshot_data(path):
    f = _load(path)
    if f is None:
        return None
    ext = _MEDIA_EXT[type(f)]
    id3 = ext in ID3_EXT
    keys = sorted(_text_keys(f)) if ext == ".flac" else _text_keys(f)
    data = None if f.tags is None else {k: (copy.deepcopy(f.tags.getall(k)) if id3 else copy.deepcopy(f.tags[k]))
                                       for k in keys}
    version = f.tags.version[1] if id3 and f.tags is not None and hasattr(f.tags, "version") else None
    fields = (id3, data, version)
    return (*fields, _id3v1(path)) if ext == ".mp3" else fields


def _pack_snapshot(data):
    return base64.b64encode(pickle.dumps(data, protocol=4)).decode("ascii") if data is not None else ""


def _unpack_snapshot(snap):
    return pickle.loads(base64.b64decode(snap))  # our own run log in %APPDATA%, never external input


def snapshot(path):
    """Text tags (no cover art) as a compact string, to put the file back as it was."""
    return _pack_snapshot(_snapshot_data(path))


def snapshot_matches(path, snap):
    """Compare with the fields recorded by this run, including older logs without an ID3v1 trailer."""
    current = _snapshot_data(path)
    if current is None or not snap:
        return current is None and not snap
    if any(_pack_snapshot(current[:size]) == snap for size in range(len(current), 1, -1)):
        return True
    if current[0] or current[1] is None:
        return False
    # Older FLAC snapshots followed the Vorbis comment dictionary's process-dependent key order.
    try:
        id3, recorded, *metadata = _unpack_snapshot(snap)
    except (EOFError, TypeError, ValueError, pickle.UnpicklingError):
        return False
    actual = current[1]
    return (not id3 and isinstance(recorded, dict) and tuple(metadata) == current[2:2 + len(metadata)]
            and recorded.keys() == actual.keys()
            and all(_pack_snapshot(recorded[k]) == _pack_snapshot(actual[k]) for k in actual))


def restore(path, snap):
    """Undo of fix_tags: text tags back to the snapshot. Only reads snapshots this app wrote itself."""
    if not snap:
        return
    id3, data, *metadata = _unpack_snapshot(snap)
    version = metadata[0] if metadata else None
    f = _load(path)
    if f is None:
        raise ValueError("formato nao reconhecido")
    ext = _MEDIA_EXT[type(f)]
    id3v1 = (metadata[1] if len(metadata) > 1 else _id3v1(path)) if ext == ".mp3" else None
    if f.tags is None:
        if not data and not id3v1:
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
    _save(f, ext, version, id3v1=id3v1)
