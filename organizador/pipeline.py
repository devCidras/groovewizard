"""The organizer: extract packs, sort by genre, drop duplicates, look up missing genres, tidy tags.

Every change is logged before it happens so the last run can be undone: extractions, moves, tag edits
(original tags are saved) and removals. Removed files go to a quarantine folder inside the library (same
drive, instant), kept 30 days, then sent to the Recycle Bin. Nothing is ever deleted outright.
"""
import base64
import csv
import ctypes
import errno
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import threading
import time
import zipfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field

from send2trash import send2trash

from . import bpm as bpm_mod
from .i18n import t
from .capas import SiteCovers, repeated
from .online import Deezer, Discogs, Lookup
from .regras import FAMILY_OF, FOLDER_NAMES, NO_GENRE, OTHER
from .tags import (JUNK_TAG_SPAM, LIST_SEP, LOSSLESS, clean_sites, fix_tags, genre_from_folder, is_audio,
                   normalize_genre, pack_file_name, raw_genre, read_info, remove_cover, restore, search_terms, clean_file_name,
                   set_cover, snapshot, snapshot_matches, track_key, version_label, cover_digest, pictures,
                   picture_records, put_back_cover)

APP_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "GrooveWizard")
for _old in ("Cratekeeper", "OrganizadorMusica"):  # names before v1.2 / v0.2
    _old = os.path.join(os.path.dirname(APP_DIR), _old)
    if os.path.isdir(_old) and not os.path.exists(APP_DIR):
        try:
            os.rename(_old, APP_DIR)
        except OSError:
            APP_DIR = _old  # in use (old version still open): keep using it, moved on a later start
ARCHIVES = {".zip", ".rar", ".7z"}
# what packs bring besides music; anything else left in _entrada is kept for the user to check
JUNK_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".txt", ".nfo", ".url", ".htm", ".html", ".m3u", ".m3u8",
            ".sfv", ".md5", ".cue", ".log", ".pdf", ".db", ".ini", ".ds_store"}
SKIP_DIRS = {"downloading", "incomplete"}  # transfers still in progress (Soulseek / Nicotine+)
INBOX = "_entrada"  # where packs are extracted before sorting
QUARANTINE = "_quarentena"  # removed files, one subfolder per run
QUARANTINE_DAYS = 30
REMOVED_COVERS = "capas_tiradas"  # in the library's data folder: site covers taken out (few, shared by many tracks), for Undo
MARKED_COVERS = os.path.join(APP_DIR, "capas_marcadas.json")  # covers the user said are not real ones
INVENTORY = "faixas_conhecidas.json"  # tracks the app has seen: anything else is new (see Organizer.is_new)
BPM_CACHE = "bpm_medidos.json"
BPM_CACHE_VERSION = 1
QUARANTINE_MARK = ".quarentena-da-app"  # written by the app; a _quarentena without it is not ours
RUN_DIR = re.compile(r"^\d{8}-\d{6}-\d+-\d+$")  # run_id format
TEMP_COPY = re.compile(r"\.ck-(?:undo-)?\d{8}-\d{6}-\d+-\d+(?:\.[^.]+)?$", re.I)
KEEP_LOGS = 30
# extraction guards (zip bombs, full disks), per run
MAX_MEMBERS = 100_000
MAX_ARCHIVES = 500
MAX_RATIO = 200
RATIO_MIN_BYTES = 200 * 1024 * 1024
MAX_RUN_EXTRACTED = 100 * (1 << 30)
FREE_MARGIN = 1 << 30  # keep 1 GB free
SAME_VERSION_TOLERANCE = 15  # s: same artist/title/version but this much longer/shorter = a different recording
csv.field_size_limit(1 << 30)  # tag snapshots are long
SEVEN_ZIP = [r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe", "7z"]


@dataclass
class Options:
    root: str = ""
    extract: bool = True
    delete_archives: bool = False
    dedupe: bool = True
    online: bool = True
    musicbrainz: bool = False
    write_tags: bool = True
    clean_sites: bool = True
    bpm_folders: bool = True
    families: bool = True
    folder_lang: str = "pt"  # language of Sem Genero / Outros / BPM folder names, fixed on first use
    merge_versions: bool = True  # Radio Edit / Club Mix count as the same song as the Extended Mix
    rename_packs: bool = False  # new tracks (packs / _entrada) get 'Artist - Title (Mix)' names; never tracks elsewhere
    covers: bool = False  # tracks without cover art get one (Deezer, then Discogs with its key)
    site_covers: bool = False  # covers that are a site's ad or generic store art are taken out and the real one looked up
    site_names: bool = False  # tracks you already had lose the download site from their file name (asked first)
    only_new: bool = False  # only _entrada and tracks never seen before; the rest of the library is left as it is
    organize_all: bool = False  # per-step overrides of only_new; ineffective when the corresponding step is off
    dedupe_all: bool = False
    online_all: bool = False
    bpm_all: bool = False
    write_tags_all: bool = False
    clean_sites_all: bool = False
    covers_all: bool = False
    site_covers_all: bool = False
    protected: list = field(default_factory=list)  # folders (absolute paths) the app never reads, moves or edits


class Cancelled(Exception):
    pass


class Busy(Exception):
    pass


def data_dir_for(root, create=True):
    """Caches and logs live in %APPDATA%, not in the music folder (which may be shared on Soulseek)."""
    canon = os.path.normcase(os.path.realpath(root))  # d:\ == D:\
    tag = hashlib.sha1(canon.encode("utf-8")).hexdigest()[:12]
    safe = re.sub(r"[^\w.-]+", "_", os.path.basename(canon.rstrip("\\/")) or "raiz")[:40]
    d = os.path.join(APP_DIR, "bibliotecas", f"{safe}-{tag}")
    if create:
        os.makedirs(os.path.join(d, "execucoes"), exist_ok=True)
    return d


def has_completed_full_run(root):
    """Read-only eligibility check for the Only new tracks control."""
    if not root or not os.path.isdir(root):
        return False
    inv = _read_json(os.path.join(data_dir_for(root, create=False), INVENTORY), None)
    return isinstance(inv, dict) and bool(inv.get("full_done", True))


def _write_json(path, obj):
    """Atomic: a crash leaves the old file, never half a file."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", errors="surrogatepass") as fh:
        json.dump(obj, fh, ensure_ascii=False)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _read_json(path, default):
    try:
        with open(path, encoding="utf-8", errors="surrogatepass") as fh:
            return json.load(fh)
    except (OSError, ValueError):  # missing/busy/bad JSON or bad bytes: cache/state can be rebuilt
        return default


@contextmanager
def library_lock(root):
    """One operation per library at a time (two windows, or the app twice, would move the same files)."""
    path = os.path.join(data_dir_for(root), "em_uso.lock")
    fh = open(path, "a+")
    try:
        try:
            import msvcrt
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        except ImportError:  # not Windows
            import fcntl
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        raise Busy(t("err.busy"))
    try:
        yield
    finally:
        fh.close()  # releases the lock


def _norm(p):
    return os.path.normcase(os.path.realpath(p)).rstrip("\\/")


def _inside(path, parent):
    try:
        return os.path.commonpath([path, parent]) == parent
    except ValueError:  # different drives
        return False


def too_broad(root):
    """Drive roots, the user profile itself and anything inside system/program folders are refused."""
    r = _norm(root)
    home = _norm(os.path.expanduser("~"))
    if os.path.dirname(r) == r or len(r) <= 3 or r in (home, os.path.dirname(home)):
        return True
    for var in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "ProgramData", "APPDATA",
                "LOCALAPPDATA"):
        if os.environ.get(var) and _inside(r, _norm(os.environ[var])):
            return True
    return False


_last_run_ns = 0  # last run id time handed out in this process


def _content_fp(path, size):
    """'size:hash' of 32 KB from the middle of the file: the music, not the tags at its ends."""
    with open(path, "rb") as fh:
        fh.seek(max(0, size // 2 - 16384))
        return f"{size}:{hashlib.sha1(fh.read(32768)).hexdigest()[:20]}"


STAGING = ".gw-parte"  # a pack being unpacked: renamed to its real name only once it is complete


def _descend(dp, d, root):
    """Folders the app walks into: not a junction / symlink (it could lead outside the library), not a pack still
    being unpacked, and at the library's top level no '_' folder except _entrada."""
    p = os.path.join(dp, d)
    if os.path.islink(p) or getattr(os.path, "isjunction", lambda _: False)(p) or d.endswith(STAGING):
        return False
    if dp == root and d.startswith("_") and os.path.normcase(d) != os.path.normcase(INBOX):
        return False
    return d.lower() not in SKIP_DIRS


def _batched(ex, fn, files, size=64):
    """(file, fn(file)) in parallel, a few at a time: results with images in them never pile up in memory."""
    for i in range(0, len(files), size):
        yield from zip(files[i:i + size], ex.map(fn, files[i:i + size]))


def protectable(root, dirs):
    """The protected folders that count (normcase): inside the library, not the library itself and not the app's own
    _entrada / _quarentena (it must be able to extract, quarantine, undo and empty them)."""
    here = os.path.normcase(os.path.abspath(root))
    own = [os.path.join(here, os.path.normcase(n)) for n in (INBOX, QUARANTINE)]
    out = set()
    for d in dirs or []:
        d = os.path.normcase(os.path.abspath(d)) if d else ""
        if d and d != here and _inside(d, here) and not any(d == o or _inside(d, o) for o in own):
            out.add(d)
    return out


def _find_7zip():
    for p in SEVEN_ZIP:
        if os.path.isfile(p):
            return p
        found = shutil.which(p)
        if found:
            return found
    return None


def _remove_temp(path):
    """Best-effort removal of a copy2() temporary, including copies of read-only tracks."""
    if not path or not os.path.exists(path):
        return
    try:
        os.chmod(path, os.stat(path).st_mode | stat.S_IWRITE)
        os.remove(path)
    except OSError:
        pass


def _hide(path):
    try:
        ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x2)  # FILE_ATTRIBUTE_HIDDEN
    except Exception:
        pass


def _move_file(src, dst):
    """On Windows rename fails if dst is occupied, including when publishing a cross-volume copy."""
    try:
        os.rename(src, dst)
        return
    except OSError as e:
        if getattr(e, "winerror", None) != 17 and e.errno != errno.EXDEV:
            raise

    with tempfile.NamedTemporaryFile(dir=os.path.dirname(dst), suffix=".part", delete=False) as staging:
        tmp = staging.name
    try:
        shutil.copy2(src, tmp)
        copy_stat = os.stat(tmp)
        os.rename(tmp, dst)
        tmp = None
        try:
            os.remove(src)
        except OSError:
            try:
                current = os.stat(dst)
                if (os.path.samestat(copy_stat, current) and copy_stat.st_size == current.st_size
                        and copy_stat.st_mtime_ns == current.st_mtime_ns):
                    _remove_temp(dst)
            except OSError:
                pass  # the published copy moved or became inaccessible
            raise
    finally:
        _remove_temp(tmp)


class Organizer:
    def __init__(self, opts, keys=None, progress=None, cancel=None, ask_rename=None, skip=None):
        self.opts = opts
        self.root = os.path.abspath(opts.root)
        if not os.path.isdir(self.root):
            raise ValueError(t("err.no_folder", root=self.root))
        if too_broad(self.root):
            raise ValueError(t("err.too_broad", root=self.root))
        self.keys = keys or {}
        self.progress = progress or (lambda step, i, n, msg="": None)
        self.cancel = cancel or threading.Event()
        self.data = data_dir_for(self.root)
        self.names = FOLDER_NAMES.get(opts.folder_lang, FOLDER_NAMES["pt"])
        self.report = Counter()
        self.errors = []
        self._log = None
        # sorts by name in time order (Undo relies on it): fixed-width nanoseconds before the pid
        global _last_run_ns
        now = _last_run_ns = max(time.time_ns(), _last_run_ns + 1)  # Windows clock ticks are coarse: never repeat
        self.run_id = time.strftime("%Y%m%d-%H%M%S", time.localtime(now // 10**9)) + f"-{now % 10**9:09d}-{os.getpid()}"
        self.qdir = os.path.join(self.root, QUARANTINE, self.run_id)
        self._overrides_path = os.path.join(self.data, "generos_corrigidos.json")
        overrides = _read_json(self._overrides_path, {})  # track id -> genre found online
        self.overrides = overrides if isinstance(overrides, dict) else {}
        self._extracted_bytes = self._extracted_members = self._extracted_archives = 0
        # new tracks outside _entrada are renamed only if this says yes: ask_rename([(path, new name), ...]) -> bool
        self.ask_rename = ask_rename
        self._inventory_path = os.path.join(self.data, INVENTORY)
        self._bpm_cache_path = os.path.join(self.data, BPM_CACHE)
        bpm_cache = _read_json(self._bpm_cache_path, {})
        self._bpm_cache = bpm_cache.get("items", {}) if isinstance(bpm_cache, dict) and (
            bpm_cache.get("version") == BPM_CACHE_VERSION and isinstance(bpm_cache.get("items"), dict)) else {}
        inv = _read_json(self._inventory_path, None)  # tracks seen in earlier runs; None before the first run
        self.known = None if not isinstance(inv, dict) else (set(inv.get("paths", [])), set(inv.get("sizes", [])))
        inv = inv if isinstance(inv, dict) else {}
        # content fingerprints (1.5.0+): a never-seen path with a known size is known only if its content matches.
        # Sizes recorded before fingerprints existed ('legacy') still count as known on their own (safe side).
        self._has_fps = "fps" in inv
        self._fps = set(inv.get("fps", []))
        self._legacy_sizes = set(inv.get("legacy_sizes", []))
        self._fp_cache = inv.get("cache", {}) if isinstance(inv.get("cache"), dict) else {}  # rel -> [size, mtime, fp]
        # a full organize reached its end at least once (lists from before 1.5.3 came from full organizes)
        self._full_done = self.known is not None and bool(inv.get("full_done", True))
        self._finished = False
        self._pending = set()  # never-seen tracks not settled yet (no answer, or the rename failed): stay new
        self._start = []
        self._settled = []
        self._start_paths = set()  # normcase paths of the tracks there when the run began
        self._moved_from = {}  # normcase dst -> src, for tracks this run moved
        # left alone: protected folders inside the library (the library itself can't be one) and files the user
        # unticked in the preview list
        self._protected = protectable(self.root, opts.protected)
        self._skip = {os.path.normcase(p) for p in (skip or [])}
        self._skip_paths = list(skip or [])
        self._fresh = set()  # only_new: tracks this run works on besides _entrada (followed when moved)
        # 'Only new tracks' needs one full organize that reached its end (first time, or the first one was cancelled):
        # until then the whole library is sorted
        self.only_new = opts.only_new and self._full_done
        self.only_new_first = opts.only_new and not self.only_new  # reported, so the user knows why it took longer
        self.plan = []  # filled by preview(): (kind, path, detail) rows for the review list
        self.snapshot = None  # filled by preview(): library_snapshot() the list was made from
        self.dup_best = {}  # duplicate -> the copy that stays

    # ---------- helpers ----------

    def _tick(self, step, i, n, msg=""):
        if self.cancel.is_set():
            raise Cancelled()
        self.progress(step, i, n, msg)

    def _write_log(self, *row):
        if self._log is None:
            path = os.path.join(self.data, "execucoes", self.run_id + ".csv")
            self._log = open(path, "x", newline="", encoding="utf-8", errors="surrogatepass")
            self._logw = csv.writer(self._log)
        self._logw.writerow(row)
        self._log.flush()

    def target_dir(self, genre):
        if genre in (NO_GENRE, OTHER):
            return os.path.join(self.root, self.names[genre])
        fam = FAMILY_OF.get(genre) if self.opts.families else None
        return os.path.join(self.root, fam, genre) if fam else os.path.join(self.root, genre)

    def label(self, genre):
        return self.names.get(genre, genre)

    def in_place(self, path, genre):
        target = os.path.normcase(self.target_dir(genre))
        here = os.path.normcase(os.path.dirname(path))
        if genre in (NO_GENRE, OTHER):  # may sit in a BPM subfolder
            return here == target or here.startswith(target + os.sep)
        return here == target

    @staticmethod
    def name_usable(src, dst_dir, name):
        """A new name is used only when it is free in the target folder (any case) and the path stays short enough
        for Windows without long-path support (the ' (1)' suffix move() may add included)."""
        if not name or os.path.normcase(name) == os.path.normcase(os.path.basename(src)):
            return False
        full = os.path.join(dst_dir, name)
        u16 = lambda s: len(s.encode("utf-16-le")) // 2  # Windows limits count UTF-16 units (emoji = 2)
        return not os.path.exists(full) and u16(full) + 4 < 255 and u16(name) < 250

    def _rel(self, p):
        return os.path.normcase(os.path.relpath(p, self.root))

    def is_new(self, p):
        """Never seen by the app: path unknown and no known file of the same size (moved/renamed by hand = known).
        Before the first run nothing outside _entrada counts as new: we can't tell what rekordbox already has."""
        if self.known is None or self._in_inbox(p):
            return False
        paths, sizes = self.known
        if self._rel(p) in paths:
            return False
        try:
            size = os.path.getsize(p)
            if size not in sizes:
                return True
            if not self._has_fps or size in self._legacy_sizes:
                return False  # size known from before fingerprints were kept: can't tell, so known (safe side)
            return self._fingerprint(p) not in self._fps  # same size, different music: a new track
        except OSError:
            return False

    def _known_content(self, p):
        """Music the app has seen before (same fingerprint), wherever the file is now. A matching fingerprint is enough;
        a size known only from before fingerprints is not (a pack track is never held back by an old size alone)."""
        if self.known is None or not self._has_fps:
            return False
        try:
            return os.path.getsize(p) in self.known[1] and self._fingerprint(p) in self._fps
        except OSError:
            return False

    def _fingerprint(self, p):
        """'size:hash' of 32 KB from the middle of the file (the music, not the tags at its ends). Cached by path,
        size and modified time: only new or changed files are read."""
        st = os.stat(p)
        rel = self._rel(p)
        c = self._fp_cache.get(rel)
        if isinstance(c, list) and len(c) == 3 and c[0] == st.st_size and c[1] == st.st_mtime_ns:
            return c[2]
        fp = _content_fp(p, st.st_size)
        self._fp_cache[rel] = [st.st_size, st.st_mtime_ns, fp]
        return fp

    def _wanted_names(self, p, info, known):
        """New names for one track, best first. New tracks: 'Artist - Title (Mix)' (option), then the same name
        without the download site and track number (when names are cleaned), used if the first is taken. Known
        tracks: only the site and number come out, and only with site_names."""
        if known:
            return [clean_file_name(p, info["artist"])] if self.opts.site_names else []
        return [n for n in (pack_file_name(p, info) if self.opts.rename_packs else None,
                            clean_file_name(p, info["artist"]) if self.opts.clean_sites else None) if n]

    def rename_plan(self, files, infos):
        """(names for _entrada tracks, names for never-seen tracks elsewhere, site-free names for tracks you already
        had): one plan, so two tracks never count on the same new name and Preview says what Organize will do.
        _entrada is renamed without asking; the other two groups are asked about (rekordbox may have them)."""
        inbox, outside, sites, planned = {}, {}, {}, set()
        if not (self.opts.rename_packs or self.opts.clean_sites or self.opts.site_names):
            return inbox, outside, sites
        for p in sorted(files, key=lambda p: not self._in_inbox(p)):  # _entrada first: renamed without asking
            info = infos[p]
            if info["unreadable"]:
                continue
            if self._in_inbox(p):
                # a track you already had, put in _entrada by hand: rekordbox may have it, so it's asked about
                group = sites if self._known_content(p) else inbox
            elif self.is_new(p):
                group = outside
            else:
                group = sites
            names = [n for n in self._wanted_names(p, info, group is sites) if n]
            if not names:
                continue
            g = self.plan_genre(p, info)
            # With Only new on, the separate old-name option must not silently reorganize old tracks.
            rename_only = group is sites and self.only_new and not self.opts.organize_all
            dst_dir = os.path.dirname(p) if rename_only or self.in_place(p, g) else self.target_dir(g)
            for name in names:  # the first one that is free
                key = os.path.normcase(os.path.join(dst_dir, name))
                if self.name_usable(p, dst_dir, name) and key not in planned:
                    planned.add(key)
                    group[p] = name
                    break
        return inbox, outside, sites

    def _settle(self, p):
        """A never-seen track is dealt with (renamed, or the user said No): known, even if dedupe removes it later."""
        self._pending.discard(os.path.normcase(p))
        try:
            self._settled.append((self._rel(p), os.path.getsize(p)))
        except OSError:
            pass

    def _track_moves(self, src, dst):
        """Keeps where each track that was new at the start went, so the inventory follows it."""
        k = os.path.normcase(src)
        self._moved_from[os.path.normcase(dst)] = k
        if self.only_new and (k in self._fresh or self._in_inbox(src)):
            self._fresh.add(os.path.normcase(dst))
        if k in self._pending:
            self._pending.discard(k)
            self._pending.add(os.path.normcase(dst))

    def _origin(self, p):
        k = os.path.normcase(p)
        seen = set()
        while k in self._moved_from and k not in seen:
            seen.add(k)
            k = self._moved_from[k]
        return k

    def _identities(self, end=False):
        """(relative path, size) of every track not waiting to be renamed.
        A known path, or a known size whose content fingerprint matches (see is_new), counts as known.
        shortcut: sizes recorded before 1.5.0 have no fingerprint and still count as known on their own; this can only
        miss a new track (never asked about), never rename a known one."""
        out = []
        inbox = os.path.normcase(os.path.join(self.root, INBOX)) + os.sep
        for p in self.audio_files():
            if os.path.normcase(p) in self._pending:
                continue
            if end:
                o = self._origin(p)
                # arrived while this run was going: still new, asked next time.
                # shortcut: a new file put at a path the run just emptied passes as known (safe side: not asked)
                if o not in self._start_paths and not o.startswith(inbox) and (self.known is None or self.is_new(p)):
                    continue
            try:
                out.append((self._rel(p), os.path.getsize(p)))
            except OSError:
                pass
        return out

    def _protected_identities(self):
        """Tracks in protected folders are the user's, not new: known, so removing the protection later never makes
        'Only new tracks' or the rename question treat them as new."""
        out = []
        for d in self._protected:
            for dp, _, fs in os.walk(d):
                for n in fs:
                    if is_audio(n):
                        p = os.path.join(dp, n)
                        try:
                            out.append((self._rel(p), os.path.getsize(p)))
                        except OSError:
                            pass
        return out

    def _unticked_identities(self):
        """Tracks unticked in the review list that were not new (old ones, or any outside _entrada before the first
        run): known, like the rest of the library. Unticked new tracks stay new and are dealt with next time."""
        out = []
        for p in self._skip_paths:
            if os.path.isfile(p) and is_audio(p) and not self._in_inbox(p) and not self.is_new(p):
                try:
                    out.append((self._rel(p), os.path.getsize(p)))
                except OSError:
                    pass
        return out

    def save_inventory(self):
        """Runs at the end of every run, finished or not. The list only grows: every track in the library becomes
        known, except never-seen ones still waiting for an answer or whose rename failed (asked again next time).
        Growing only means Undo, cancel or a half-done Undo can never make an old track look new."""
        paths, sizes = self.known if self.known is not None else (set(), set())
        # first save with fingerprints: every size known so far stays 'legacy' (known on its own) for good, because a
        # known track that is not here right now (or shares a size with one that is) has no fingerprint to compare
        legacy = set(self._legacy_sizes) | (set(sizes) if self.known is not None and not self._has_fps else set())
        paths, sizes = set(paths), set(sizes)
        fps, cache = set(self._fps), {}
        ids = (self._start + self._settled + self._identities(end=True) + self._protected_identities()
               + self._unticked_identities())
        for i, (rel, size) in enumerate(ids, 1):
            paths.add(rel)
            sizes.add(size)
            if i % 200 == 0:
                self.progress("inventory", i, len(ids), "")  # first 1.5 run reads every track once: show it
            p = os.path.join(self.root, rel)
            if not os.path.exists(p):
                q = os.path.join(self.qdir, rel)  # removed by this run: its copy waits in quarantine
                try:
                    if os.path.getsize(q) == size:
                        fps.add(_content_fp(q, size))  # restored somewhere else later: still known
                except OSError:
                    pass  # moved during the run: its new place is in ids too
                continue
            try:
                if os.path.getsize(p) != size:  # changed during the run (tags, cover): its new size is in ids too
                    continue
                fps.add(self._fingerprint(p))
                cache[rel] = self._fp_cache[rel]
            except (OSError, KeyError):
                legacy.add(size)  # here but no fingerprint: its size alone must keep counting as known
        full_done = self._full_done or (self._finished and not self.only_new)
        _write_json(self._inventory_path, {"paths": sorted(paths), "sizes": sorted(sizes), "fps": sorted(fps),
                                           "legacy_sizes": sorted(legacy), "cache": cache, "full_done": full_done})

    def _in_inbox(self, p):
        return os.path.normcase(p).startswith(os.path.normcase(os.path.join(self.root, INBOX)) + os.sep)

    def left_alone(self, p, *, include_unticked=False):
        """Inside a protected folder, or unticked in the preview list: never read, moved, renamed or edited."""
        k = os.path.normcase(p)
        return ((not include_unticked and k in self._skip) or k in self._protected
                or any(k.startswith(d + os.sep) for d in self._protected))

    def _in_scope(self, p):
        """'Only new tracks': _entrada and the tracks never seen before (where they went during this run)."""
        return not self.only_new or self._in_inbox(p) or os.path.normcase(p) in self._fresh

    def _step_scope(self, p, all_tracks=False):
        return all_tracks or self._in_scope(p)

    def _walk(self, base=None):
        """os.walk of the library without protected folders, transfers in progress and the root-level '_' folders
        (except _entrada)."""
        base = base or self.root
        for dp, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if _descend(dp, d, self.root) and not self.left_alone(os.path.join(dp, d))]
            yield dp, dirs, files

    def move(self, src, dst_dir, name=None):
        """Never overwrites and never deletes a file it did not create itself. `name`: new file name, used only
        when free (taken: the file keeps its own name, so nothing gets a ' (1)' just for the rename)."""
        if self.left_alone(dst_dir):  # never into a protected folder: the track stays where it is
            self.errors.append(t("err.protected_target", path=src))
            return None
        try:
            os.makedirs(dst_dir, exist_ok=True)
            if not self.name_usable(src, dst_dir, name):
                name = None
            base, ext = os.path.splitext(os.path.join(dst_dir, name or os.path.basename(src)))
            dst, i = base + ext, 1
            while os.path.exists(dst):
                dst, i = f"{base} ({i}){ext}", i + 1
            self._write_log("mover", src, dst)  # before the move: a crash right after still leaves a record
            _move_file(src, dst)
        except OSError as e:
            if "dst" in locals():
                self._write_log("falhou", src, dst)
            self.errors.append(f"{src}: {e}")
            return None
        self._track_moves(src, dst)  # only after it really moved
        return dst

    def trash(self, path):
        """Into this run's quarantine folder (Undo brings it back). Same drive: a rename, no copy."""
        rel = os.path.relpath(path, self.root)
        dst = os.path.join(self.qdir, rel)
        # (raises if a user folder called _quarentena already exists: stops before touching anything)
        qroot = os.path.join(self.root, QUARANTINE)
        if self.left_alone(qroot):
            self.errors.append(t("err.protected_target", path=path))
            return False
        if not os.path.isdir(qroot):
            os.makedirs(qroot, exist_ok=True)
            _hide(qroot)  # not shown in Explorer / shares that skip hidden folders
            open(os.path.join(qroot, QUARANTINE_MARK), "w").close()
        elif not _owns_quarantine(self.root):
            raise RuntimeError(t("err.quarantine_taken", path=qroot))  # a user folder with that name: never use it
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        self._write_log("quarentena", path, dst)
        try:
            os.rename(path, dst)
        except OSError as e:
            self._write_log("falhou", path, dst)
            self.errors.append(f"{path}: {e}")
            return False
        return True

    def _edit_tags(self, p, genre=None, clean=False):
        """Original tags go to the run log first; the edit is made on a copy that must reopen with the same
        length before it replaces the original, so a failed save can never damage the track."""
        snap = snapshot(p)
        self._fp_cache.pop(self._rel(p), None)  # content changes: never reuse its old fingerprint (coarse mtimes)
        before = read_info(p)["duration"]
        tmp = f"{p}.ck-{self.run_id}{os.path.splitext(p)[1]}"  # same extension: mutagen picks the format by it
        try:
            shutil.copy2(p, tmp)
            changed = fix_tags(tmp, genre=genre, clean=clean)
            check = read_info(tmp)
            # length unknown before (some AIFF without tags report 0) only needs to be readable after
            if check["unreadable"] or not check["duration"] or (before and abs(check["duration"] - before) > 0.5):
                raise RuntimeError(t("err.tag_check"))
            self._write_log("tags", p, snap, snapshot(tmp))
            os.replace(tmp, p)
            return changed
        except BaseException:
            if self._log is not None:
                self._write_log("falhou", p, snap)  # not changed: Undo skips this entry
            raise
        finally:
            _remove_temp(tmp)

    def audio_files(self, base=None, *, include_unticked=False):
        for dp, _, files in self._walk(base):
            for n in files:
                p = os.path.join(dp, n)
                if is_audio(n) and not TEMP_COPY.search(n) and not self.left_alone(p, include_unticked=include_unticked):
                    yield p

    def _read_all(self, files, step):
        """{path: info} read in parallel, cancellable."""
        out = {}
        ex = ThreadPoolExecutor(8)
        try:
            for i, (p, info) in enumerate(zip(files, ex.map(read_info, files)), 1):
                if i % 50 == 0 or i == len(files):
                    self._tick(step, i, len(files), os.path.basename(p))
                out[p] = info
        finally:
            ex.shutdown(wait=True, cancel_futures=True)
        return out

    def override_key(self, p, info):
        """Online genres are remembered per track (artist + title + length), not per file name."""
        return f"{track_key(p, False, info) or os.path.basename(p).lower()}|{round(info['duration'])}"

    def remove_empty_dirs(self):
        found = []
        for dp, _, _ in self._walk():  # never protected folders, transfers in progress or root-level "_" folders
            if dp != self.root:
                found.append(dp)
        for dp in reversed(found):  # deepest first
            try:
                if not os.listdir(dp):
                    os.rmdir(dp)
            except OSError:
                pass

    # ---------- archives ----------

    def pending_archives(self):
        done = self._done_archives()
        out = []
        for dp, dirs, files in os.walk(self.root):
            # _entrada included (packs inside packs); _quarentena, _Backup, junctions excluded
            dirs[:] = [d for d in dirs if _descend(dp, d, self.root) and not self.left_alone(os.path.join(dp, d))]
            for n in files:
                p = os.path.join(dp, n)
                if self.left_alone(p):
                    continue
                aid = self._archive_id(p) if os.path.splitext(n)[1].lower() in ARCHIVES else None
                if aid and aid not in done:
                    out.append(p)
        return sorted(out)

    def _archive_id(self, p):
        try:
            st = os.stat(p)
            rel = os.path.normcase(os.path.relpath(p, self.root))
            return f"{rel}|{st.st_size}|{st.st_mtime_ns}"
        except OSError:  # vanished (e.g. moved by the download client)
            return None

    def _done_archives(self):
        value = _read_json(os.path.join(self.data, "extraidos.json"), [])
        return set(value) if isinstance(value, list) else set()

    def step_extract(self):
        seven = _find_7zip()
        tried = set()
        while True:  # again for archives found inside the packs just extracted (CD1.zip, CD2.zip...)
            archives = [a for a in self.pending_archives() if a not in tried]
            if not archives:
                return
            tried.update(archives)
            self._extract(archives, seven)

    def _extract(self, archives, seven):
        done = self._done_archives()
        inbox = os.path.join(self.root, INBOX)
        for i, a in enumerate(archives, 1):
            self._tick("extract", i, len(archives), os.path.basename(a))
            stem = os.path.splitext(os.path.basename(a))[0].strip(" .")
            # an archive inside a pack is extracted next to it, so the pack name still gives the genre
            parent = os.path.dirname(a) if self._in_inbox(a) else inbox
            if self.left_alone(parent):  # _entrada protected: nowhere to extract to
                self.errors.append(t("err.protected_target", path=a))
                continue
            out, k = os.path.join(parent, stem), 2
            while os.path.lexists(out) or os.path.lexists(out + STAGING):
                out, k = os.path.join(parent, f"{stem} ({k})"), k + 1
            aid = self._archive_id(a)
            part = out + STAGING  # older interrupted folders are left alone, not assumed to belong to this app
            part_created = False
            try:
                self._extracted_archives += 1
                if self._extracted_archives > MAX_ARCHIVES:
                    raise RuntimeError(t("err.archive_many", n=self._extracted_archives))
                os.makedirs(parent, exist_ok=True)
                os.mkdir(part)  # only this run's newly created folder may be removed on failure
                part_created = True
                if a.lower().endswith(".zip"):
                    self._unzip(a, part)
                elif seven:
                    self._un7z(seven, a, part)
                else:
                    raise RuntimeError(t("err.need_7zip"))
                os.rename(part, out)
            except Cancelled:
                if part_created:
                    shutil.rmtree(part, ignore_errors=True)
                raise
            except Exception as e:
                if part_created:
                    shutil.rmtree(part, ignore_errors=True)
                self.errors.append(f"{os.path.basename(a)}: {e}")
                continue
            self._write_log("extraido", aid or a, out)
            done.add(aid or a)
            _write_json(os.path.join(self.data, "extraidos.json"), sorted(done))
            self.report["archives_extracted"] += 1
            if self.opts.delete_archives and self.trash(a):
                self.report["archives_trashed"] += 1

    def _check_archive(self, total, count, packed):
        self._extracted_members += count
        self._extracted_bytes += total
        if self._extracted_members > MAX_MEMBERS:
            raise RuntimeError(t("err.archive_many", n=self._extracted_members))
        if packed and total > RATIO_MIN_BYTES and total / packed > MAX_RATIO:
            raise RuntimeError(t("err.archive_bomb"))
        if self._extracted_bytes > MAX_RUN_EXTRACTED:
            raise RuntimeError(t("err.archive_run_size"))
        if total > shutil.disk_usage(self.root).free - FREE_MARGIN:
            raise RuntimeError(t("err.no_space", gb=round(total / (1 << 30), 1)))

    def _unzip(self, a, out):
        with zipfile.ZipFile(a) as z:
            infos = z.infolist()
            self._check_archive(sum(i.file_size for i in infos), len(infos), sum(i.compress_size for i in infos))
            names = [os.path.normcase(os.path.normpath(i.filename.replace("/", os.sep))) for i in infos]
            if len(names) != len(set(names)):
                raise RuntimeError(t("err.archive_names"))
            for info in infos:
                if self.cancel.is_set():
                    raise Cancelled()
                z.extract(info, out)  # drops absolute paths and '..'

    def _un7z(self, seven, a, out):
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        listing = subprocess.run([seven, "l", "-slt", "-ba", a], capture_output=True, text=True, errors="replace",
                                 stdin=subprocess.DEVNULL, creationflags=flags)
        sizes = [int(m) for m in re.findall(r"^Size = (\d+)$", listing.stdout, re.M)]
        if listing.returncode != 0 or not sizes:  # can't see inside: don't extract blind
            raise RuntimeError(t("err.archive_list"))
        packed = sum(int(m) for m in re.findall(r"^Packed Size = (\d+)$", listing.stdout, re.M))
        self._check_archive(sum(sizes), len(sizes), packed)
        proc = subprocess.Popen([seven, "x", a, f"-o{out}", "-aos", "-y", "-bso0", "-bsp0", "-snl-"],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                creationflags=flags)
        while True:
            try:
                err = proc.communicate(timeout=0.5)[1]
                break
            except subprocess.TimeoutExpired:
                if self.cancel.is_set():
                    proc.kill()
                    proc.communicate()
                    raise Cancelled()
        if proc.returncode != 0:
            raise RuntimeError(err.decode(errors="replace").strip()[:200] or f"7-Zip erro {proc.returncode}")

    # ---------- genre ----------

    def plan_genre(self, path, info=None):
        info = info or read_info(path)
        rel = os.path.relpath(path, self.root).split(os.sep)
        pack = rel[1] if os.path.normcase(rel[0]) == os.path.normcase(INBOX) and len(rel) > 2 else None
        g = self.overrides.get(self.override_key(path, info))
        if g == NO_GENRE:  # taken out of a guessed genre on purpose
            return NO_GENRE
        return normalize_genre(info["genre"]) or g or genre_from_folder(path, pack) or NO_GENRE

    def step_organize(self):
        files = [p for p in self.audio_files() if self._step_scope(p, self.opts.organize_all)
                 or self.opts.site_names]
        infos = self._read_all(files, "organize")
        inbox_names, outside, sites = self.rename_plan(files, infos)
        self._pending -= {os.path.normcase(p) for p in files if p not in outside}  # nothing to ask about them
        # without 'Artist - Title' names only the site comes out: the question must say so
        kind = "new_sites" if all(n == clean_file_name(p, infos[p]["artist"]) for p, n in outside.items()) else "new"
        if outside and not (self.ask_rename and self.ask_rename(sorted(outside.items()), kind)):
            for p in outside:  # "No": known from now on, never asked again
                self._settle(p)
            outside = {}
        # tracks you already had: the site comes out of the name only after a yes (asked every run while it's on)
        if sites and not (self.ask_rename and self.ask_rename(sorted(sites.items()), "sites")):
            sites = {}
        names = {**inbox_names, **outside, **sites}
        for i, p in enumerate(files, 1):
            self._tick("organize", i, len(files), os.path.basename(p))
            if not self._step_scope(p, self.opts.organize_all):
                name = sites.get(p)  # explicit old-name option only; never move it to another folder
                if name and self.move(p, os.path.dirname(p), name):
                    self.report["site_names"] += 1
                continue
            if infos[p]["unreadable"] and not self._in_inbox(p):
                # damaged tags: we can't tell its genre, so it stays where it is (it may have been placed by hand)
                self.report["unreadable"] += 1
                self.errors.append(t("err.unreadable", path=p))
                continue
            g = self.plan_genre(p, infos[p])
            name = names.get(p)
            if self.in_place(p, g):
                dst = self.move(p, os.path.dirname(p), name) if name else None  # right folder: only the new name
            else:
                dst = self.move(p, self.target_dir(g), name)
                if dst:
                    self.report[f"moved|{self.label(g)}"] += 1
            if dst and name and os.path.basename(dst) == name:
                self.report["site_names" if p in sites else "renamed"] += 1
                self._settle(dst)  # done: known from now on
        inbox = os.path.join(self.root, INBOX)
        if os.path.isdir(inbox):
            done = self._done_archives()
            for dp, _, fs in self._walk(inbox):  # covers, .nfo, .url... and inner archives already extracted
                for n in fs:
                    p = os.path.join(dp, n)
                    ext = os.path.splitext(n)[1].lower()
                    if self.left_alone(p):
                        continue
                    leftover_pack = (ext in ARCHIVES and self._archive_id(p) in done
                                     and (os.path.normcase(dp) != os.path.normcase(inbox) or self.opts.delete_archives))
                    if (ext in JUNK_EXT or leftover_pack) and self.trash(p):
                        self.report["junk_trashed"] += 1
        self.remove_empty_dirs()

    # ---------- duplicates ----------

    @staticmethod
    def _score(path, dur, title=""):
        # DJ preference: Extended Mix (file name or title tag), then longest, then lossless, then bigger file
        ext = bool(re.search(r"extended", os.path.basename(path) + " " + (title or ""), re.I))
        try:
            size = os.path.getsize(path)
        except OSError:  # vanished during the run
            size = -1
        return ext, round(dur), os.path.splitext(path)[1].lower() in LOSSLESS, size

    def _losers(self, group, infos):
        """Sorted best first. The same version (e.g. two 'Original Mix') with clearly different lengths is
        a different recording, not a copy: it stays."""
        best, rest = group[0], group[1:]
        out = []
        for p, dur in rest:
            same_version = version_label(p, infos[p]) == version_label(best[0], infos[best[0]])
            if same_version and dur and best[1] and abs(dur - best[1]) > SAME_VERSION_TOLERANCE:
                continue
            out.append(p)
        return out

    def find_duplicates(self, infos):
        """Copies to remove (best kept: see _score). 'Only new tracks': only new copies are removed.
        Also fills self.dup_best (copy removed -> copy kept) for the review list."""
        groups = defaultdict(list)
        for p, info in infos.items():
            if info["unreadable"]:
                continue  # damaged tags: its length is unknown (0), it would always lose
            key = track_key(p, self.opts.merge_versions, info)
            if key:
                groups[key].append((p, info["duration"]))
        out = []
        for v in groups.values():
            if len(v) > 1 and any(self._step_scope(p, self.opts.dedupe_all) for p, _ in v):
                ranked = sorted(v, key=lambda x: self._score(x[0], x[1], infos[x[0]]["title"]), reverse=True)
                # only new: an old copy is never removed (the rest of the library is left as it is), even if the
                # new one is better; a full run sorts that out
                losers = [p for p in self._losers(ranked, infos)
                          if self._step_scope(p, self.opts.dedupe_all) and not self.left_alone(p)]
                self.dup_best.update((p, ranked[0][0]) for p in losers)
                out += losers
        return out

    def step_dedupe(self):
        # unticked tracks still count as copies (the list promised 'X goes, Y stays' even if Y was unticked),
        # they are just never the one removed (find_duplicates skips left_alone)
        kept = [p for p in self._skip_paths if os.path.isfile(p) and is_audio(p)]
        infos = self._read_all(list(self.audio_files()) + kept, "dedupe_scan")
        losers = [p for p in self.find_duplicates(infos) if os.path.exists(p)]
        for i, p in enumerate(losers, 1):
            self._tick("dedupe_remove", i, len(losers), os.path.basename(p))
            if self.trash(p):
                self.report["dups_trashed"] += 1

    # ---------- online ----------

    def step_online(self):
        look = Lookup(self.data, self.keys.get("discogs_token", ""), self.keys.get("lastfm_api_key", ""),
                      self.opts.musicbrainz, self.cancel)
        if not look.available:
            self.errors.append(t("err.online_skipped"))
            return
        base = self.target_dir(NO_GENRE)
        files = [p for p in self.audio_files(base) if self._step_scope(p, self.opts.online_all)] if os.path.isdir(base) else []
        try:
            for i, p in enumerate(files, 1):
                self._tick("online", i, len(files), os.path.basename(p))
                info = read_info(p)
                write_genre = self.opts.write_tags and self._step_scope(p, self.opts.write_tags_all)
                okey = self.override_key(p, info)
                if info["unreadable"] or self.overrides.get(okey) == NO_GENRE:
                    continue
                terms = search_terms(p)
                g, src = look.genre(*terms) if terms else (None, None)
                if not g:
                    continue
                dst = self.move(p, self.target_dir(g))
                if not dst:
                    continue
                self._write_log("genero", dst, g, src, okey, self.overrides.get(okey, ""))
                self.overrides[okey] = g
                self.report[f"online|{g}"] += 1
                if write_genre:
                    try:
                        self._edit_tags(dst, genre=g)  # the tag is what other apps (rekordbox) read
                    except Exception as e:
                        self.errors.append(f"{os.path.basename(dst)}: {e}")
                if i % 25 == 0:
                    look.save()
                    _write_json(self._overrides_path, self.overrides)
        finally:
            look.save()
            _write_json(self._overrides_path, self.overrides)
            for problem in look.problems:
                msg = t("err.online_source", error=problem)
                if msg not in self.errors:
                    self.errors.append(msg)

    # ---------- BPM ----------

    def _loose_unsorted(self):
        files = []
        for top in (NO_GENRE, OTHER):
            d = self.target_dir(top)
            for d in (d, os.path.join(d, self.names["bpm_unknown"])):  # loose ones, and those nobody could measure yet
                if os.path.isdir(d) and not self.left_alone(d):
                    for n in os.listdir(d):
                        p = os.path.join(d, n)
                        if (is_audio(n) and os.path.isfile(p) and not os.path.islink(p)
                                and not getattr(os.path, "isjunction", lambda _: False)(p) and not TEMP_COPY.search(n)):
                            hit, value = self._cached_bpm(p)
                            if os.path.basename(d) != self.names["bpm_unknown"] or not hit or value:
                                files.append(p)
        return [p for p in files if self._step_scope(p, self.opts.bpm_all) and not self.left_alone(p)]

    def _cached_bpm(self, p):
        try:
            st = os.stat(p)
            key = f"{st.st_mtime_ns}:{_content_fp(p, st.st_size)}"
            if key in self._bpm_cache:
                return True, self._bpm_cache[key]
        except OSError:
            pass
        return False, None

    def _measure_bpm(self, p):
        hit, value = self._cached_bpm(p)
        if not hit:
            value = bpm_mod.bpm_of(p)
            try:
                st = os.stat(p)
                self._bpm_cache[f"{st.st_mtime_ns}:{_content_fp(p, st.st_size)}"] = value
            except OSError:
                pass
        return value

    def step_bpm(self):
        files = self._loose_unsorted()
        ex = ThreadPoolExecutor(4)
        try:
            for done, (p, b) in enumerate(zip(files, ex.map(self._measure_bpm, files)), 1):
                self._tick("bpm", done, len(files), os.path.basename(p))
                here = os.path.dirname(p)
                unknown = os.path.basename(here) == self.names["bpm_unknown"]
                if unknown and not b:
                    continue  # still unknown
                if self.move(p, os.path.join(os.path.dirname(here) if unknown else here, bpm_mod.bucket(b, self.names))):
                    self.report["bpm_sorted"] += 1
        finally:
            ex.shutdown(wait=True, cancel_futures=True)  # on cancel: don't measure the rest
            try:
                _write_json(self._bpm_cache_path, {"version": BPM_CACHE_VERSION, "items": self._bpm_cache})
            except OSError as e:
                self.errors.append(f"{self._bpm_cache_path}: {e}")

    # ---------- tags ----------

    def site_cover_map(self, files, infos):
        """{track: ids of its images that are a site's ad or generic store art} (the images themselves are not kept)."""
        site = SiteCovers(MARKED_COVERS)
        files = [p for p in files if not infos[p]["unreadable"] and infos[p]["cover"]]
        out = {}
        ex = ThreadPoolExecutor(8)
        try:
            for i, (p, pics) in enumerate(_batched(ex, pictures, files), 1):
                if i % 50 == 0 or i == len(files):
                    self._tick("covers", i, len(files), os.path.basename(p))
                bad = [cover_digest(d) for d in pics if site.is_site(d)]
                if bad:
                    out[p] = bad
        finally:
            ex.shutdown(wait=True, cancel_futures=True)
        return out

    def step_covers(self):
        """Tracks without cover art get the cover of a release they are on: Deezer first (no key), then Discogs (with
        its key). Only a result whose artist and title match is used. A real cover is never replaced; a site's ad
        comes out (with site_covers) and stays out even when no real cover is found."""
        token = self.keys.get("discogs_token", "")
        sources = [Deezer(self.data, self.cancel)] + ([Discogs(self.data, token, self.cancel)] if token else [])
        files = [p for p in self.audio_files() if self._in_scope(p)
                 or (self.opts.covers and self.opts.covers_all)
                 or (self.opts.site_covers and self.opts.site_covers_all)]
        infos = self._read_all(files, "covers")
        bad = self.site_cover_map([p for p in files if self._step_scope(p, self.opts.site_covers_all)], infos) if self.opts.site_covers else {}
        todo = [p for p in files if p in bad
                or (self.opts.covers and self._step_scope(p, self.opts.covers_all)
                    and not infos[p]["unreadable"] and not infos[p]["cover"])]
        site = SiteCovers(MARKED_COVERS)
        try:
            for i, p in enumerate(todo, 1):
                self._tick("covers", i, len(todo), os.path.basename(p))
                drop = bad.get(p, [])
                try:
                    data, asked = None, True
                    if not drop or all(cover_digest(d) in drop for d in pictures(p)):  # no real cover left
                        data, asked = self._find_cover(p, sources, site)
                    if drop and not asked:
                        self.report["site_covers_later"] += 1  # no answer from the internet: next time
                        continue
                    if (drop or data) and self._change_cover(p, drop, data):
                        self.report["site_covers_out"] += bool(drop)
                        self.report["covers_added"] += bool(data)
                except Cancelled:
                    raise
                except Exception as e:
                    self.errors.append(f"{os.path.basename(p)}: {e}")
                if i % 25 == 0:
                    for src in sources:
                        src.save()
        finally:
            for src in sources:
                src.save()
                if getattr(src, "problem", ""):
                    msg = t("err.online_source", error=src.problem)
                    if msg not in self.errors:
                        self.errors.append(msg)
        self.report = +self.report  # no zero lines in the summary

    def _find_cover(self, p, sources, site):
        """(image or None, True when every source answered). Generic art from a source doesn't count as an answer."""
        terms = search_terms(p)
        asked = True
        for src in sources if terms else []:
            url = src.cover(*terms)
            data = src.image(url, os.path.join(self.data, "capas")) if url else None
            if data and not site.is_site(data):
                return data, True
            if url is None or (url and not data):  # couldn't ask, or the image didn't come
                asked = False
        if self.cancel.is_set():
            raise Cancelled()
        return None, asked

    def _change_cover(self, p, drop, data):
        """Takes the images with the `drop` ids out and puts `data` in (only if no other cover is left), on a verified copy; logged
        first, with the removed images kept, so Undo puts everything back. False when there was nothing to change."""
        tmp = f"{p}.ck-{self.run_id}{os.path.splitext(p)[1]}"
        rows = []
        try:
            shutil.copy2(p, tmp)
            before = read_info(tmp)["duration"]
            records = picture_records(tmp)
            gone = [r for r in records if cover_digest(base64.b64decode(r["data"])) in drop]
            for digest in set(drop):
                remove_cover(tmp, digest)
            left = len(pictures(tmp))
            data = None if left else data
            if not gone and not data:
                return False
            for record in reversed(gone):  # Undo reverses rows: covers are reinserted in their original order
                packed = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                key = hashlib.sha1(packed).hexdigest()[:20] + ".json"
                keep = os.path.join(self.data, REMOVED_COVERS, key)
                if not os.path.exists(keep):
                    os.makedirs(os.path.dirname(keep), exist_ok=True)
                    with open(keep + ".tmp", "wb") as fh:
                        fh.write(packed)
                    os.replace(keep + ".tmp", keep)
                rows.append(("capa_fora", p, key))
            if data:
                rows.append(("capa", p, cover_digest(data)))
            for r in rows:
                self._write_log(*r)
            self._fp_cache.pop(self._rel(p), None)
            if data:
                set_cover(tmp, data)
            check = read_info(tmp)
            if check["unreadable"] or check["cover"] != bool(left or data) or (
                    before and abs(check["duration"] - before) > 0.5):
                raise RuntimeError(t("err.tag_check"))
            os.replace(tmp, p)
            return True
        except BaseException:
            for _, a, b in rows:
                self._write_log("falhou", a, b)  # not changed: Undo skips these entries
            raise
        finally:
            _remove_temp(tmp)

    def repeated_covers(self):
        """For 'Repeated covers': read-only look at every embedded image."""
        files = list(self.audio_files())

        def one(p):
            pics = pictures(p)
            return [(d, read_info(p)["artist"]) for d in pics] if pics else []

        def covers():
            ex = ThreadPoolExecutor(8)
            try:
                for i, (p, found) in enumerate(_batched(ex, one, files), 1):
                    if i % 50 == 0 or i == len(files):
                        self._tick("covers_scan", i, len(files), os.path.basename(p))
                    yield from found
            finally:
                ex.shutdown(wait=True, cancel_futures=True)
        return repeated(covers(), SiteCovers(MARKED_COVERS))

    def step_tags(self):
        files = [p for p in self.audio_files() if self._in_scope(p)
                 or (self.opts.write_tags and self.opts.write_tags_all)
                 or (self.opts.clean_sites and self.opts.clean_sites_all)]
        for i, p in enumerate(files, 1):
            self._tick("tags", i, len(files), os.path.basename(p))
            try:
                info = read_info(p)
                if info["unreadable"]:
                    continue  # damaged tags: never write into them
                genre, key = (self._genre_decision(p, info["genre"])
                              if self.opts.write_tags and self._step_scope(p, self.opts.write_tags_all)
                              else (None, None))
                clean = bool(self.opts.clean_sites and self._step_scope(p, self.opts.clean_sites_all)
                             and clean_sites(p, write=False))
                if genre is None and not clean:
                    continue
                g, s = self._edit_tags(p, genre=genre, clean=clean)
                if g:
                    self.report[key] += 1
                if s:
                    self.report["sites_cleaned"] += 1
            except Exception as e:
                self.errors.append(f"{os.path.basename(p)}: {e}")

    def _genre_decision(self, p, raw=None):
        """-> (new genre or None to leave it, report key)."""
        raw = raw_genre(p) if raw is None else raw
        top = os.path.relpath(p, self.root).split(os.sep)[0]
        if top in (self.names[NO_GENRE], self.names[OTHER]):
            if JUNK_TAG_SPAM.search(raw):
                return "", "genre_spam_cleared"
            if top == self.names[OTHER] and LIST_SEP.search(raw):
                return LIST_SEP.split(raw)[0].strip(), "genre_tag_fixed"
            return None, None
        here = os.path.basename(os.path.dirname(p))
        if not self.in_place(p, here):
            return None, None  # not inside a genre folder
        # keep a more specific tag that maps to this folder (e.g. "Afro House" inside House)
        if normalize_genre(raw) != here or LIST_SEP.search(raw) or JUNK_TAG_SPAM.search(raw):
            return here, "genre_tag_fixed"
        return None, None

    # ---------- run / preview ----------

    def run(self, expect=None):
        """expect: library_snapshot() of the Preview whose list the user reviewed; checked under the lock, so a track
        arriving after the review is never organized on the strength of a list it was not on."""
        with library_lock(self.root):
            if expect is not None and self.library_snapshot() != expect:
                raise ValueError(t("plan.stale"))
            _purge_quarantine(self.root, QUARANTINE_DAYS)  # here, not in __init__: Preview must not change anything
            prune_logs(self.data)
            return self._run()

    def _run(self):
        steps = [(self.opts.extract, self.step_extract), (True, self.step_organize), (self.opts.dedupe, self.step_dedupe),
                 (self.opts.online, self.step_online), (self.opts.bpm_folders, self.step_bpm),
                 (self.opts.write_tags or self.opts.clean_sites, self.step_tags), (self.opts.covers or self.opts.site_covers, self.step_covers)]
        renames = self.opts.rename_packs or self.opts.clean_sites
        if renames and self.known is not None:  # never-seen at the start: stay new if we stop before the question
            self._pending = {os.path.normcase(p) for p in self.audio_files() if self.is_new(p)}
        self._fresh = self._new_tracks()
        if self.only_new_first:
            self.report["only_new_first"] = 1
        self._start = self._identities()  # where/what every track was before this run: Undo puts them back there
        self._start_paths = {os.path.normcase(p) for p in self.audio_files()}
        try:
            for on, fn in steps:
                if on:
                    fn()
            self.remove_empty_dirs()
            self._finished = True  # not cancelled, no crash
        finally:
            try:
                if not (self.cancel.is_set() and not self._finished):
                    self.save_inventory()
            except OSError as e:
                self.errors.append(f"{self._inventory_path}: {e}")
            finally:
                if self._log:
                    self._log.close()
        return self.report, self.errors

    def preview(self):
        """What a run would do with the files as they are now, without touching anything.
        Not included: tracks still inside packs, online results, site cleaning in tags (see log.preview_limits)."""
        with library_lock(self.root):
            return self._preview()

    def library_snapshot(self, files=None):
        """Tracks and packs as they are now (path, size, modified): the review list only holds while this is unchanged
        (a download finishing after the Preview would otherwise be organized without ever being on the list)."""
        out = {("only_new", self.only_new)}  # another window finishing a first organize changes what Organize does
        tracks = self.audio_files(include_unticked=True) if files is None else files
        for p in list(tracks) + self.pending_archives():
            try:
                st = os.stat(p)
                out.add((os.path.normcase(p), st.st_size, st.st_mtime_ns))
            except OSError:
                pass
        return frozenset(out)

    def _new_tracks(self):
        """'Only new tracks': the never-seen tracks outside _entrada (before the first run: none)."""
        return {os.path.normcase(p) for p in self.audio_files() if self.is_new(p)} if self.only_new else set()

    def _preview(self):
        """Counts for the summary, and self.plan: one row per track that will change, for the review list
        ("move": new path, "rename_ask": new name if you say yes, "dup": the copy that stays, "tags": new genre)."""
        rep = Counter()
        self.plan, self.dup_best = [], {}  # a second preview() on the same object starts clean
        if self.opts.extract:
            rep["archives_pending"] = len(self.pending_archives())
        self._fresh = self._new_tracks()
        files = list(self.audio_files())
        self.snapshot = self.library_snapshot(None if self._skip else files)
        infos = self._read_all(files, "preview")  # all of them: duplicates are looked for in the whole library
        inbox_names, outside, sites = self.rename_plan(
            [p for p in files if self._step_scope(p, self.opts.organize_all) or self.opts.site_names], infos)
        for p, info in infos.items():
            dst = p
            if self._step_scope(p, self.opts.organize_all):
                if info["unreadable"] and not self._in_inbox(p):
                    rep["unreadable"] += 1
                    continue
                g = self.plan_genre(p, info)
                name = inbox_names.get(p)
                if not self.in_place(p, g) and self.left_alone(self.target_dir(g)):
                    rep["protected_target"] += 1  # Organize leaves it where it is
                elif not self.in_place(p, g):
                    rep[f"to_move|{self.label(g)}"] += 1
                    if name:
                        rep["rename_pending"] += 1
                    dst = os.path.join(self.target_dir(g), name or os.path.basename(p))
                    self.plan.append(("move", p, dst))
                elif name:
                    rep["rename_pending"] += 1
                    dst = os.path.join(os.path.dirname(p), name)
                    self.plan.append(("move", p, dst))
            elif p in sites:
                dst = os.path.join(os.path.dirname(p), sites[p])
            # the tag step runs after the move, on the new place (decided from the path and the tag text only)
            new_genre = (self._genre_decision(dst, info["genre"])[0]
                         if self.opts.write_tags and self._step_scope(p, self.opts.write_tags_all)
                         and not info["unreadable"] else None)
            if new_genre is not None:
                rep["tags_pending"] += 1
                self.plan.append(("tags", p, new_genre))
            if p in outside:
                self.plan.append(("rename_ask", p, outside[p]))
            if p in sites:
                self.plan.append(("site_name", p, sites[p]))
        rep["tracks"] = len(files)
        if self.only_new_first:
            rep["only_new_first"] = 1
        # counted from the list: tracks headed for a protected folder were left out above (Organize leaves them)
        rep["site_names_ask"] = sum(1 for k, _, _ in self.plan if k == "site_name")
        rep["rename_ask"] = sum(1 for k, _, _ in self.plan if k == "rename_ask")
        if self.opts.dedupe:
            dups = self.find_duplicates(infos)
            rep["dups_pending"] = len(dups)
            self.plan += [("dup", p, self.dup_best[p]) for p in dups]
        if self.opts.bpm_folders:
            rep["bpm_pending"] = len(self._loose_unsorted())
        if self.opts.covers:
            bare = [p for p, i in infos.items() if self._step_scope(p, self.opts.covers_all)
                    and not i["unreadable"] and not i["cover"]]
            rep["covers_pending"] = len(bare)
            self.plan += [("cover", p, t("plan.cover_detail")) for p in bare]
        if self.opts.site_covers:
            bad = self.site_cover_map([p for p in files if self._step_scope(p, self.opts.site_covers_all)], infos)
            rep["site_covers_pending"] = len(bad)
            self.plan += [("site_cover", p, t("plan.cover_detail")) for p in bad]
        if self.opts.online and os.path.isdir(self.target_dir(NO_GENRE)):
            rep["online_pending"] = sum(1 for p in self.audio_files(self.target_dir(NO_GENRE))
                                        if self._step_scope(p, self.opts.online_all))
        inbox = os.path.join(self.root, INBOX)
        if os.path.isdir(inbox):
            rep["junk_pending"] = sum(1 for dp, _, fs in self._walk(inbox) for n in fs  # same filters as the run
                                      if os.path.splitext(n)[1].lower() in JUNK_EXT
                                      and not self.left_alone(os.path.join(dp, n)))
        return Counter({k: v for k, v in rep.items() if v or k == "tracks"})


# ---------- quarantine / logs ----------

def purge_quarantine(root, older_than_days=None):
    """Quarantined runs -> Recycle Bin. Takes the library lock (never while an Undo is running)."""
    with library_lock(root):
        return _purge_quarantine(root, older_than_days)


def _owns_quarantine(root):
    """The app's mark is there, or the folder was made by a version before the mark existed (< 1.2.0): it then holds
    only run folders, and our own run log shows the app moving files into one of them. Such a folder gets the mark
    now; anything else is the user's.
    shortcut: one proven run is enough (older logs may be pruned), the other folders only need the run-id name."""
    qroot = os.path.join(root, QUARANTINE)
    if os.path.islink(qroot) or getattr(os.path, "isjunction", lambda _: False)(qroot):
        return False  # never follow a redirected quarantine outside the chosen library
    mark = os.path.join(qroot, QUARANTINE_MARK)
    if os.path.exists(mark):
        return True
    logs = os.path.join(data_dir_for(root), "execucoes")
    try:
        entries = os.listdir(qroot)
        if not entries or not all(RUN_DIR.match(d) and os.path.isdir(os.path.join(qroot, d)) for d in entries):
            return False
        if not any(_log_quarantined_into(logs, d, os.path.join(qroot, d)) for d in entries):
            return False
        open(mark, "w").close()
    except OSError:
        return False
    return True


def _log_quarantined_into(logs, run_id, run_dir):
    """True when that run's log has a 'quarentena' row whose destination is inside run_dir."""
    inside = os.path.normcase(run_dir) + os.sep
    for name in (run_id + ".csv", run_id + ".desfeito.csv"):
        try:
            if any(r and r[0] == "quarentena" and len(r) > 2 and os.path.normcase(r[2]).startswith(inside)
                   for r in _read_log_rows(os.path.join(logs, name))):
                return True
        except (OSError, csv.Error):
            continue
    return False


def _purge_quarantine(root, older_than_days=None):
    qroot = os.path.join(root, QUARANTINE)
    if not os.path.isdir(qroot):
        return 0
    if not _owns_quarantine(root):
        return 0  # not created by this app: never touch it
    limit = time.time() - older_than_days * 86400 if older_than_days is not None else None
    n = 0
    for d in os.listdir(qroot):
        p = os.path.join(qroot, d)
        if not (RUN_DIR.match(d) and os.path.isdir(p)) or os.path.islink(p) or getattr(os.path, "isjunction", lambda _: False)(p):
            continue  # only the per-run folders the app made
        try:
            if limit is None or os.path.getmtime(p) < limit:
                send2trash(p)
                n += 1
        except OSError:
            pass
    try:
        if os.listdir(qroot) == [QUARANTINE_MARK]:
            os.remove(os.path.join(qroot, QUARANTINE_MARK))
            os.rmdir(qroot)
    except OSError:
        pass
    return n


def prune_logs(data_dir):
    d = os.path.join(data_dir, "execucoes")
    logs = [f for f in os.listdir(d) if f.endswith(".csv")]
    for group in ((f for f in logs if not f.endswith(".desfeito.csv")),
                  (f for f in logs if f.endswith(".desfeito.csv"))):
        for f in sorted(group, key=lambda f: _log_time_key(d, f))[:-KEEP_LOGS]:
            for extra in ("", ".feito"):
                try:
                    os.remove(os.path.join(d, f + extra))
                except OSError:
                    pass


def _remove_empty(top):
    for dp, _, _ in sorted(os.walk(top), key=lambda w: -len(w[0])):
        try:
            os.rmdir(dp)  # only succeeds when empty
        except OSError:
            pass


# ---------- undo ----------

def _safe_restore(path, snap, run_id):
    """Undo of tags on a copy that must reopen with the same length before it replaces the original."""
    before = read_info(path)["duration"]
    tmp = f"{path}.ck-undo-{run_id}{os.path.splitext(path)[1]}"
    shutil.copy2(path, tmp)
    try:
        restore(tmp, snap)
        check = read_info(tmp)
        # length 0 is allowed here: an AIFF put back to "no tags" reports 0 again, as it did before the run
        if check["unreadable"] or (before and abs(check["duration"] - before) > 0.5):
            raise RuntimeError(t("err.tag_check"))
        os.replace(tmp, path)
    finally:
        _remove_temp(tmp)


def _safe_uncover(path, digest, run_id):
    """Undo of a cover the app added (only that image: one the user added later stays), on a copy that must still play
    before it replaces the track."""
    before = read_info(path)["duration"]
    tmp = f"{path}.ck-undo-{run_id}{os.path.splitext(path)[1]}"
    shutil.copy2(path, tmp)
    try:
        if not remove_cover(tmp, digest):
            return False  # not there any more (replaced by hand): nothing of ours to take out
        check = read_info(tmp)
        if check["unreadable"] or (before and abs(check["duration"] - before) > 0.5):
            raise RuntimeError(t("err.tag_check"))
        os.replace(tmp, path)
        return True
    finally:
        _remove_temp(tmp)


def _safe_put_back(path, image, run_id):
    """Undo of a site cover taken out, on a copy that must still play before it replaces the track."""
    if isinstance(image, dict):
        target = {k: v for k, v in image.items() if k not in ("ordinal", "position")}
        have = sum({k: v for k, v in r.items() if k not in ("ordinal", "position")} == target
                   for r in picture_records(path))
        if have >= int(image.get("ordinal", 1)):
            return
    elif any(cover_digest(d) == cover_digest(image) for d in pictures(path)):
        return
    before = read_info(path)["duration"]
    tmp = f"{path}.ck-undo-{run_id}{os.path.splitext(path)[1]}"
    shutil.copy2(path, tmp)
    try:
        put_back_cover(tmp, image)
        check = read_info(tmp)
        if check["unreadable"] or (before and abs(check["duration"] - before) > 0.5):
            raise RuntimeError(t("err.tag_check"))
        os.replace(tmp, path)
    finally:
        _remove_temp(tmp)


def _move_back(src, dst, errors, retry):
    """dst -> src; True when moved. retry[0] = True when trying again later could succeed."""
    if not os.path.exists(dst):
        errors.append(t("err.undo_missing", path=dst))
        retry[0] = True
        return False
    if os.path.exists(src):
        errors.append(t("err.undo_conflict", path=src))
        retry[0] = True
        return False
    try:
        os.makedirs(os.path.dirname(src), exist_ok=True)
        _move_file(dst, src)
        return True
    except OSError as e:
        errors.append(f"{dst}: {e}")
        retry[0] = True  # e.g. file open in rekordbox
        return False


def _log_time_key(runs_dir, f):
    try:
        st = os.stat(os.path.join(runs_dir, f))
        # creation time: st_birthtime (Python 3.12+); st_ctime is creation time on older Windows Pythons only
        return getattr(st, "st_birthtime_ns", None) or st.st_ctime_ns, f
    except OSError:
        return 0, f


def _pending_logs(runs_dir):
    """Run logs not undone yet, oldest first. By creation time, not by name: run ids carry the local time, which
    jumps back an hour when summer time ends (the name breaks ties)."""
    return sorted((f for f in os.listdir(runs_dir) if f.endswith(".csv") and not f.endswith(".desfeito.csv")),
                  key=lambda f: _log_time_key(runs_dir, f))


def _read_log_rows(path):
    """Complete CSV rows from a log; a power-cut-truncated final UTF-8 character does not hide earlier work."""
    with open(path, "rb") as fh:
        raw = fh.read()
    try:
        text = raw.decode("utf-8", "surrogatepass")
    except UnicodeDecodeError as e:
        end = raw.rfind(b"\n", 0, e.start) + 1
        text = raw[:end].decode("utf-8", "surrogatepass") if end else ""
    return [r for r in csv.reader(text.splitlines()) if r]


def list_runs(root):
    """Runs that can still be undone, newest first: [(run_id, Counter of what each did)]."""
    d = os.path.join(data_dir_for(root), "execucoes")
    out = []
    for f in reversed(_pending_logs(d)):
        kinds = Counter()
        try:
            rows = _read_log_rows(os.path.join(d, f))
            failed = {(r[1], r[2]) for r in rows if r[0] == "falhou" and len(r) > 2}
            for r in rows:
                if r[0] != "falhou" and len(r) > 2 and (r[1], r[2]) not in failed:
                    kinds[r[0]] += 1
        except OSError:
            continue
        out.append((f[:-4], kinds))
    return out


def undo_until(root, run_id, progress=None, cancel=None, protected=(), newest_seen=None):
    """Undoes the runs from the newest back to run_id (included), one at a time: an older run can only be undone
    after the newer ones, or a file moved twice would go back to the wrong place. Stops at the first run that
    could not be fully undone (it stays the newest, so trying again continues from there).
    newest_seen: the newest run the user saw when choosing; if another one finished since, nothing is undone."""
    with library_lock(root):
        rep, errors = Counter(), []
        runs = list_runs(root)
        if newest_seen and runs and runs[0][0] != newest_seen:
            return rep, [t("err.undo_changed")]
        while True:
            pending = [r for r, _ in list_runs(root)]
            if run_id not in pending:
                return rep, errors
            newest = pending[0]
            r, e = _undo_last(root, progress, cancel, protected)
            rep.update(r)
            errors += e
            if newest in [x for x, _ in list_runs(root)]:  # still there: something must be retried first
                errors.append(t("err.undo_stuck"))
                return rep, errors


def library_report(organizer, csv_path):
    """Read-only look at the whole library: counts per problem and a CSV list (problem; file) at csv_path.
    Problems: damaged tags, no artist or title tag, no genre tag, MP3 under 320 kbps, shorter than 1 minute."""
    files = list(organizer.audio_files())
    infos = organizer._read_all(files, "report")
    rep, rows = Counter({"tracks": len(files)}), []
    for p, info in infos.items():
        problems = []
        if info["unreadable"]:
            problems.append("report_unreadable")
        else:
            if not (info["artist"] and info["title"]):
                problems.append("report_no_artist_title")
            if not info["genre"]:
                problems.append("report_no_genre")
            if p.lower().endswith(".mp3") and 0 < info.get("bitrate", 0) < 320000:
                problems.append("report_low_bitrate")
            if 0 < info["duration"] < 60:
                problems.append("report_short")
        for k in problems:
            rep[k] += 1
            rows.append((t("rep." + k), p))
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as fh:  # BOM: Excel opens accents right
        w = csv.writer(fh, delimiter=";")
        w.writerow((t("report.col_problem"), t("report.col_file")))
        w.writerows(sorted(rows))
    return rep


def undo_last(root, progress=None, cancel=None):
    """Undoes the last run: tags back to the originals, removed files out of quarantine, moves reversed,
    extracted packs put aside."""
    with library_lock(root):
        return _undo_last(root, progress, cancel)


def _undo_last(root, progress, cancel, protected=()):
    """protected: folders the user protected since that run. Their entries are not undone; the run stays pending
    (it can be undone once the folder is no longer protected)."""
    shielded = protectable(root, protected)
    inside = lambda p: any(os.path.normcase(os.path.abspath(p)) == d or os.path.normcase(os.path.abspath(p)).startswith(d + os.sep)
                           for d in shielded)
    progress = progress or (lambda *a: None)
    data = data_dir_for(root)
    runs_dir = os.path.join(data, "execucoes")
    runs = _pending_logs(runs_dir)
    if not runs:
        return Counter({"undo_nothing": 1}), []
    path = os.path.join(runs_dir, runs[-1])
    run_id = runs[-1][:-4]
    rows = _read_log_rows(path)
    done_path = path + ".feito"  # entries already undone by an earlier (partial) attempt
    try:
        with open(done_path, encoding="utf-8") as fh:
            done = {int(x) for x in fh.read().split()}
    except FileNotFoundError:
        done = set()
    rep, errors, retry = Counter(), [], [False]
    blocked_paths = set()
    failed = {(r[1], r[2]) for r in rows if r[0] == "falhou" and len(r) > 2}
    kinds = ("tags", "quarentena", "mover", "extraido", "genero", "capa", "capa_fora")
    todo = [(i, r) for i, r in enumerate(rows) if r[0] in kinds and len(r) > 2 and (r[1], r[2]) not in failed
            and i not in done]
    overrides_path = os.path.join(data, "generos_corrigidos.json")
    overrides = _read_json(overrides_path, {})
    overrides = overrides if isinstance(overrides, dict) else {}
    extracted_value = _read_json(os.path.join(data, "extraidos.json"), [])
    extracted = set(extracted_value) if isinstance(extracted_value, list) else set()
    try:  # cancelled halfway: the entries already undone are kept on disk too
        with open(done_path, "a", encoding="utf-8") as done_fh:
            for n, (i, r) in enumerate(reversed(todo), 1):  # newest first: replays the chain backwards
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                kind, a, b = r[:3]
                progress("undo", n, len(todo), os.path.basename(a))
                paths = (a, b) if kind in ("mover", "quarentena", "extraido") else (a,)
                touched = {os.path.normcase(p) for p in paths if os.path.isabs(p)}
                # A failed later action leaves this track at a different path, or another file in its place.
                # Keep that chain and any enclosing extraction pending while undoing unrelated tracks.
                if (blocked_paths.intersection(touched) or
                        (kind == "extraido" and any(p.startswith(os.path.normcase(b) + os.sep) for p in blocked_paths))):
                    blocked_paths.update(touched)
                    continue
                if any(inside(p) for p in touched):
                    errors.append(t("err.undo_protected", path=a))
                    retry[0] = True  # stays pending: undone later, when the folder is no longer protected
                    blocked_paths.update(touched)
                    continue
                ok = False
                if kind == "tags":
                    if not os.path.exists(a):
                        errors.append(t("err.undo_missing", path=a))
                        retry[0] = True
                    elif len(r) > 3 and not snapshot_matches(a, r[3]):
                        errors.append(t("err.undo_tags_changed", path=a))
                        retry[0] = True
                    else:
                        try:
                            _safe_restore(a, b, run_id)
                            rep["undo_tags"] += 1
                            ok = True
                        except Exception as e:  # e.g. file open in another program: try again later
                            errors.append(f"{a}: {e}")
                            retry[0] = True
                elif kind == "capa":  # the track had no cover before this run
                    if not os.path.exists(a):
                        errors.append(t("err.undo_missing", path=a))
                        retry[0] = True
                    else:
                        try:
                            if _safe_uncover(a, b, run_id):
                                rep["undo_covers"] += 1
                            ok = True
                        except Exception as e:
                            errors.append(f"{a}: {e}")
                            retry[0] = True
                elif kind == "capa_fora":  # a site's cover taken out: put back
                    if not os.path.exists(a):
                        errors.append(t("err.undo_missing", path=a))
                        retry[0] = True
                    else:
                        try:
                            with open(os.path.join(data, REMOVED_COVERS, b), "rb") as fh:
                                stored = fh.read()
                            image = json.loads(stored.decode("utf-8")) if b.endswith(".json") else stored
                            _safe_put_back(a, image, run_id)
                            rep["undo_site_covers"] += 1
                            ok = True
                        except Exception as e:
                            errors.append(f"{a}: {e}")
                            retry[0] = True
                elif kind == "genero":
                    okey, prev = (r[4], r[5]) if len(r) > 5 else (None, "")
                    if okey:
                        if prev:
                            overrides[okey] = prev
                        else:
                            overrides.pop(okey, None)
                    ok = True
                elif kind == "extraido":
                    if os.path.isdir(b):  # what is left of the extraction (the tracks were moved back into it)
                        base = os.path.join(root, QUARANTINE, run_id, "_extracoes_desfeitas", os.path.basename(b))
                        dst, k = base, 2
                        while os.path.exists(dst):  # two packs both called CD1.zip
                            dst, k = f"{base} ({k})", k + 1
                        os.makedirs(os.path.dirname(dst), exist_ok=True)
                        try:
                            os.rename(b, dst)
                        except OSError as e:
                            errors.append(f"{b}: {e}")
                            retry[0] = True
                            blocked_paths.update(touched)
                            continue
                    extracted.discard(a)
                    rep["undo_extract"] += 1
                    ok = True
                else:
                    ok = _move_back(a, b, errors, retry)
                    if ok:
                        rep["undo_from_quarantine" if kind == "quarentena" else "undo_returned"] += 1
                if not ok:
                    blocked_paths.update(touched)
                else:
                    if kind == "genero":
                        _write_json(overrides_path, overrides)  # saved before the entry counts as done
                    elif kind == "extraido":
                        _write_json(os.path.join(data, "extraidos.json"), sorted(extracted))
                    done_fh.write(f"{i}\n")
                    done_fh.flush()
    finally:
        _write_json(overrides_path, overrides)
        _write_json(os.path.join(data, "extraidos.json"), sorted(extracted))
    legacy = sum(1 for r in rows if r[0] == "reciclagem")  # runs before the quarantine existed
    if legacy:
        rep["undo_in_trash"] = legacy
    if not retry[0]:  # conflicts, missing files and files in use keep the run pending for another attempt
        os.replace(path, path[:-4] + ".desfeito.csv")
        try:
            os.remove(done_path)
        except OSError:
            pass
        qroot = os.path.join(root, QUARANTINE)
        _remove_empty(qroot)
        if os.path.isdir(qroot) and os.listdir(qroot) == [QUARANTINE_MARK]:
            os.remove(os.path.join(qroot, QUARANTINE_MARK))
            os.rmdir(qroot)
        _remove_empty(os.path.join(root, INBOX))
    return rep, errors
