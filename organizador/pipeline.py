"""The organizer: extract packs, sort by genre, drop duplicates, look up missing genres, tidy tags.

Every change is logged before it happens so the last run can be undone: moves, tag edits (original tags are
saved) and removals. Removed files go to a quarantine folder inside the library (same drive, instant), kept
30 days, then sent to the Recycle Bin. Nothing is ever deleted outright.
"""
import csv
import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
import zipfile
from contextlib import contextmanager
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from send2trash import send2trash

from . import bpm as bpm_mod
from .online import Lookup
from .i18n import t
from .regras import FAMILY_OF, FOLDER_NAMES, NO_GENRE, OTHER
from .tags import (LIST_SEP, LOSSLESS, SPAM, clean_sites, fix_tags, genre_from_folder, is_audio, normalize_genre,
                   raw_genre, read_info, restore, search_terms, snapshot, track_key)

APP_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Cratekeeper")
_OLD_DIR = os.path.join(os.path.dirname(APP_DIR), "OrganizadorMusica")  # name before v0.2
if os.path.isdir(_OLD_DIR) and not os.path.exists(APP_DIR):
    try:
        os.rename(_OLD_DIR, APP_DIR)
    except OSError:
        pass
ARCHIVES = {".zip", ".rar", ".7z"}
# what packs bring besides music; anything else left in _entrada is kept for the user to check
JUNK_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".txt", ".nfo", ".url", ".htm", ".html", ".m3u", ".m3u8",
            ".sfv", ".md5", ".cue", ".log", ".pdf", ".db", ".ini", ".ds_store"}
SKIP_DIRS = {"downloading", "incomplete"}  # transfers still in progress (Soulseek / Nicotine+)
INBOX = "_entrada"  # where packs are extracted before sorting
QUARANTINE = "_quarentena"  # removed files, one subfolder per run
QUARANTINE_DAYS = 30
# extraction guards (zip bombs, full disks)
MAX_MEMBERS = 100_000
MAX_RATIO = 200
FREE_MARGIN = 1 << 30  # keep 1 GB free
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


class Cancelled(Exception):
    pass


def data_dir_for(root):
    """Caches and logs live in %APPDATA%, not in the music folder (which may be shared on Soulseek)."""
    canon = os.path.normcase(os.path.realpath(root))  # d:\ == D:\
    tag = hashlib.sha1(canon.encode("utf-8")).hexdigest()[:12]
    safe = re.sub(r"[^\w.-]+", "_", os.path.basename(canon.rstrip("\\/")) or "raiz")[:40]
    d = os.path.join(APP_DIR, "bibliotecas", f"{safe}-{tag}")
    os.makedirs(os.path.join(d, "execucoes"), exist_ok=True)
    return d


class Busy(Exception):
    pass


@contextmanager
def library_lock(root):
    """One run per library at a time (two windows, or the app twice, would move the same files)."""
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


def too_broad(root):
    """A drive root, the user profile or a system folder would sweep up every audio file on the PC."""
    r = os.path.normcase(os.path.realpath(root)).rstrip("\\/")
    home = os.path.normcase(os.path.expanduser("~"))
    blocked = {home, os.path.dirname(home)}
    for var in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData", "APPDATA", "LOCALAPPDATA"):
        if os.environ.get(var):
            blocked.add(os.path.normcase(os.environ[var]).rstrip("\\/"))
    return os.path.dirname(r) == r or len(r) <= 3 or r in blocked


def _find_7zip():
    for p in SEVEN_ZIP:
        if os.path.isfile(p) or shutil.which(p):
            return p
    return None


class Organizer:
    def __init__(self, opts, keys=None, progress=None, cancel=None):
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
        self.run_id = time.strftime("%Y%m%d-%H%M%S") + f"-{os.getpid()}-{time.time_ns() % 10**9}"
        self.qdir = os.path.join(self.root, QUARANTINE, self.run_id)
        self._overrides_path = os.path.join(self.data, "generos_corrigidos.json")
        try:
            with open(self._overrides_path, encoding="utf-8") as fh:
                self.overrides = json.load(fh)  # file name -> genre found online
        except (FileNotFoundError, json.JSONDecodeError):
            self.overrides = {}

    # ---------- helpers ----------

    def _tick(self, step, i, n, msg=""):
        if self.cancel.is_set():
            raise Cancelled()
        self.progress(step, i, n, msg)

    def _write_log(self, *row):
        if self._log is None:
            path = os.path.join(self.data, "execucoes", self.run_id + ".csv")
            self._log = open(path, "x", newline="", encoding="utf-8")
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

    def move(self, src, dst_dir):
        os.makedirs(dst_dir, exist_ok=True)
        base, ext = os.path.splitext(os.path.join(dst_dir, os.path.basename(src)))
        dst, i = base + ext, 1
        while os.path.exists(dst):
            dst, i = f"{base} ({i}){ext}", i + 1
        self._write_log("mover", src, dst)  # before the move: a crash right after still leaves a record
        try:
            shutil.move(src, dst)  # rename on the same drive; copy + delete across drives
        except OSError as e:
            self._write_log("falhou", src, dst)
            if os.path.exists(src) and os.path.exists(dst):
                try:
                    os.remove(dst)  # half-copied file from a failed cross-drive move
                except OSError:
                    pass
            self.errors.append(f"{src}: {e}")
            return None
        return dst

    def trash(self, path):
        """Into this run's quarantine folder (Undo brings it back). Same drive: a rename, no copy."""
        rel = os.path.relpath(path, self.root)
        dst_dir = os.path.dirname(os.path.join(self.qdir, rel))
        if not os.path.isdir(os.path.join(self.root, QUARANTINE)):
            os.makedirs(os.path.join(self.root, QUARANTINE), exist_ok=True)
            _hide(os.path.join(self.root, QUARANTINE))  # not shown in Explorer / shares that skip hidden
        os.makedirs(dst_dir, exist_ok=True)
        dst = os.path.join(dst_dir, os.path.basename(path))
        self._write_log("quarentena", path, dst)
        try:
            os.replace(path, dst)
        except OSError as e:
            self._write_log("falhou", path, dst)
            self.errors.append(f"{path}: {e}")
            return False
        return True

    def _edit_tags(self, p, genre=None, clean=False):
        """Original tags go to the run log first, then one save. -> (genre_changed, site_fields_changed)."""
        self._write_log("tags", p, snapshot(p))
        return fix_tags(p, genre=genre, clean=clean)

    def audio_files(self, base=None):
        base = base or self.root
        for dp, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIRS and not (dp == self.root and d.startswith("_") and d != INBOX)]
            for n in files:
                if is_audio(n):
                    yield os.path.join(dp, n)

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

    def _save_overrides(self):
        tmp = self._overrides_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.overrides, fh, ensure_ascii=False, indent=0)
        os.replace(tmp, self._overrides_path)

    def remove_empty_dirs(self):
        found = []
        for dp, dirs, _ in os.walk(self.root):
            # never touch transfers in progress or the root-level "_" folders
            dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIRS and not (dp == self.root and d.startswith("_") and d != INBOX)]
            if dp != self.root:
                found.append(dp)
        for dp in reversed(found):  # deepest first
            try:
                if not os.listdir(dp):
                    os.rmdir(dp)
            except OSError:
                pass

    # ---------- steps ----------

    def pending_archives(self):
        done = self._done_archives()
        out = []
        for dp, dirs, files in os.walk(self.root):
            dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIRS and not (dp == self.root and d == QUARANTINE)]  # _entrada included: packs inside packs
            for n in files:
                p = os.path.join(dp, n)
                aid = self._archive_id(p) if os.path.splitext(n)[1].lower() in ARCHIVES else None
                if aid and aid not in done:
                    out.append(p)
        return sorted(out)

    def _archive_id(self, p):
        try:
            st = os.stat(p)
            return f"{os.path.basename(p)}|{st.st_size}|{int(st.st_mtime)}"
        except OSError:  # vanished (e.g. moved by the download client)
            return None

    def _done_archives(self):
        try:
            with open(os.path.join(self.data, "extraidos.json"), encoding="utf-8") as fh:
                return set(json.load(fh))
        except (FileNotFoundError, json.JSONDecodeError):
            return set()

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
        for i, a in enumerate(archives, 1):
            self._tick("extract", i, len(archives), os.path.basename(a))
            stem = os.path.splitext(os.path.basename(a))[0].strip(" .")
            inbox = os.path.join(self.root, INBOX)
            # an archive inside a pack is extracted next to it, so the pack name still gives the genre
            inside = os.path.normcase(a).startswith(os.path.normcase(inbox) + os.sep)
            out, k = os.path.join(os.path.dirname(a) if inside else inbox, stem), 2
            while os.path.exists(out):
                out, k = os.path.join(os.path.dirname(a) if inside else inbox, f"{stem} ({k})"), k + 1
            try:
                if a.lower().endswith(".zip"):
                    self._unzip(a, out)
                elif seven:
                    self._un7z(seven, a, out)
                else:
                    raise RuntimeError(t("err.need_7zip"))
            except Cancelled:
                shutil.rmtree(out, ignore_errors=True)  # our own fresh folder: half an extraction is useless
                raise
            except Exception as e:
                shutil.rmtree(out, ignore_errors=True)
                self.errors.append(f"{os.path.basename(a)}: {e}")
                continue
            done.add(self._archive_id(a) or a)
            with open(os.path.join(self.data, "extraidos.json"), "w", encoding="utf-8") as fh:
                json.dump(sorted(done), fh, ensure_ascii=False)
            self.report["archives_extracted"] += 1
            if self.opts.delete_archives and self.trash(a):
                self.report["archives_trashed"] += 1

    def _check_archive(self, total, count, packed):
        if count > MAX_MEMBERS:
            raise RuntimeError(t("err.archive_many", n=count))
        if packed and total > 2 * (1 << 30) and total / packed > MAX_RATIO:
            raise RuntimeError(t("err.archive_bomb"))
        if total > shutil.disk_usage(self.root).free - FREE_MARGIN:
            raise RuntimeError(t("err.no_space", gb=round(total / (1 << 30), 1)))

    def _unzip(self, a, out):
        with zipfile.ZipFile(a) as z:
            infos = z.infolist()
            self._check_archive(sum(i.file_size for i in infos), len(infos), sum(i.compress_size for i in infos))
            for info in infos:
                if self.cancel.is_set():
                    raise Cancelled()
                z.extract(info, out)  # drops absolute paths and '..'

    def _un7z(self, seven, a, out):
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        listing = subprocess.run([seven, "l", "-slt", "-ba", a], capture_output=True, text=True, errors="replace",
                                 creationflags=flags)
        sizes = [int(m) for m in re.findall(r"^Size = (\d+)$", listing.stdout, re.M)]
        packed = sum(int(m) for m in re.findall(r"^Packed Size = (\d+)$", listing.stdout, re.M))
        self._check_archive(sum(sizes), len(sizes), packed)
        proc = subprocess.Popen([seven, "x", a, f"-o{out}", "-aos", "-y", "-bso0", "-bsp0", "-snl-"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=flags)
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

    def plan_genre(self, path, info=None):
        name = os.path.basename(path)
        rel = os.path.relpath(path, self.root).split(os.sep)
        pack = rel[1] if rel[0] == INBOX and len(rel) > 2 else None
        g = self.overrides.get(name)
        if g == NO_GENRE:  # taken out of a guessed genre on purpose
            return NO_GENRE
        # tag first: overrides are keyed by file name, which another track may share
        tag = normalize_genre((info or read_info(path))["genre"])
        return tag or g or genre_from_folder(path, pack) or NO_GENRE

    def step_organize(self):
        files = list(self.audio_files())
        infos = self._read_all(files, "organize")
        for i, p in enumerate(files, 1):
            self._tick("organize", i, len(files), os.path.basename(p))
            if infos[p]["unreadable"] and not p.startswith(os.path.join(self.root, INBOX)):
                # damaged tags: we can't tell its genre, so it stays where it is (it may have been placed by hand)
                self.report["unreadable"] += 1
                self.errors.append(t("err.unreadable", path=p))
                continue
            g = self.plan_genre(p, infos[p])
            if not self.in_place(p, g) and self.move(p, self.target_dir(g)):
                self.report[f"moved|{self.label(g)}"] += 1
        inbox = os.path.join(self.root, INBOX)
        if os.path.isdir(inbox):
            done = self._done_archives()
            for dp, _, fs in os.walk(inbox):  # covers, .nfo, .url... and inner archives already extracted
                for n in fs:
                    p = os.path.join(dp, n)
                    ext = os.path.splitext(n)[1].lower()
                    if (ext in JUNK_EXT or (ext in ARCHIVES and self._archive_id(p) in done)) and self.trash(p):
                        self.report["junk_trashed"] += 1
        self.remove_empty_dirs()

    @staticmethod
    def _score(path, dur):
        # DJ preference: Extended Mix, then longest, then lossless, then bigger file
        ext = bool(re.search(r"extended", os.path.basename(path), re.I))
        try:
            size = os.path.getsize(path)
        except OSError:  # vanished during the run
            size = -1
        return ext, round(dur), os.path.splitext(path)[1].lower() in LOSSLESS, size

    def step_dedupe(self):
        files = list(self.audio_files())
        groups = defaultdict(list)
        for p, info in self._read_all(files, "dedupe_scan").items():
            key = track_key(p, self.opts.merge_versions, info)
            if key:
                groups[key].append((p, info["duration"]))
        dups = [sorted(v, key=lambda x: self._score(*x), reverse=True) for v in groups.values() if len(v) > 1]
        losers = [p for v in dups for p, _ in v[1:] if os.path.exists(p)]
        for i, p in enumerate(losers, 1):
            self._tick("dedupe_remove", i, len(losers), os.path.basename(p))
            if self.trash(p):
                self.report["dups_trashed"] += 1

    def step_online(self):
        look = Lookup(self.data, self.keys.get("discogs_token", ""), self.keys.get("lastfm_api_key", ""),
                      self.opts.musicbrainz, self.cancel)
        if not look.available:
            self.errors.append(t("err.online_skipped"))
            return
        base = self.target_dir(NO_GENRE)
        files = [p for p in self.audio_files(base) if self.overrides.get(os.path.basename(p)) != NO_GENRE] \
            if os.path.isdir(base) else []
        try:
            for i, p in enumerate(files, 1):
                self._tick("online", i, len(files), os.path.basename(p))
                terms = search_terms(p)
                g, src = look.genre(*terms) if terms else (None, None)
                if g:
                    self.overrides[os.path.basename(p)] = g
                    dst = self.move(p, self.target_dir(g))
                    if dst:
                        self._write_log("genero", dst, g, src)
                        self.report[f"online|{g}"] += 1
                        if self.opts.write_tags:
                            try:
                                self._edit_tags(dst, genre=g)  # the tag survives renames, the override may not
                            except Exception as e:
                                self.errors.append(f"{os.path.basename(dst)}: {e}")
                if i % 25 == 0:
                    look.save()
                    self._save_overrides()
        finally:
            look.save()
            self._save_overrides()

    def step_bpm(self):
        files = []
        for top in (NO_GENRE, OTHER):
            d = self.target_dir(top)
            if os.path.isdir(d):
                files += [os.path.join(d, n) for n in os.listdir(d) if is_audio(n)]  # only loose ones
        ex = ThreadPoolExecutor(4)
        try:
            for done, (p, b) in enumerate(zip(files, ex.map(bpm_mod.bpm_of, files)), 1):
                self._tick("bpm", done, len(files), os.path.basename(p))
                if self.move(p, os.path.join(os.path.dirname(p), bpm_mod.bucket(b, self.names))):
                    self.report["bpm_sorted"] += 1
        finally:
            ex.shutdown(wait=True, cancel_futures=True)  # on cancel: don't measure the rest

    def step_tags(self):
        files = list(self.audio_files())
        for i, p in enumerate(files, 1):
            self._tick("tags", i, len(files), os.path.basename(p))
            try:
                if read_info(p)["unreadable"]:
                    continue  # damaged tags: never write into them
                genre, key = self._genre_decision(p) if self.opts.write_tags else (None, None)
                clean = bool(self.opts.clean_sites and clean_sites(p, write=False))
                if genre is None and not clean:
                    continue
                g, s = self._edit_tags(p, genre=genre, clean=clean)
                if g:
                    self.report[key] += 1
                if s:
                    self.report["sites_cleaned"] += 1
            except Exception as e:
                self.errors.append(f"{os.path.basename(p)}: {e}")

    def _genre_decision(self, p):
        """-> (new genre or None to leave it, report key)."""
        raw = raw_genre(p)
        top = os.path.relpath(p, self.root).split(os.sep)[0]
        if top in (self.names[NO_GENRE], self.names[OTHER]):
            if SPAM.search(raw):
                return "", "genre_spam_cleared"
            if top == self.names[OTHER] and LIST_SEP.search(raw):
                return LIST_SEP.split(raw)[0].strip(), "genre_tag_fixed"
            return None, None
        here = os.path.basename(os.path.dirname(p))
        if not self.in_place(p, here):
            return None, None  # not inside a genre folder
        # keep a more specific tag that maps to this folder (e.g. "Afro House" inside House)
        if normalize_genre(raw) != here or LIST_SEP.search(raw) or SPAM.search(raw):
            return here, "genre_tag_fixed"
        return None, None

    # ---------- run ----------

    def run(self):
        with library_lock(self.root):
            purge_quarantine(self.root, QUARANTINE_DAYS)  # here, not in __init__: Preview must not change anything
            prune_logs(self.data)
            return self._run()

    def _run(self):
        steps = [(self.opts.extract, self.step_extract), (True, self.step_organize), (self.opts.dedupe, self.step_dedupe),
                 (self.opts.online, self.step_online), (self.opts.bpm_folders, self.step_bpm),
                 (self.opts.write_tags or self.opts.clean_sites, self.step_tags)]
        try:
            for on, fn in steps:
                if on:
                    fn()
            self.remove_empty_dirs()
        finally:
            if self._log:
                self._log.close()
        return self.report, self.errors

    def preview(self):
        """What a run would do, without touching anything."""
        with library_lock(self.root):
            return self._preview()

    def _preview(self):
        rep = Counter()
        rep["archives_pending"] = len(self.pending_archives())
        files = list(self.audio_files())
        groups = Counter()
        for p, info in self._read_all(files, "preview").items():
            if info["unreadable"] and not p.startswith(os.path.join(self.root, INBOX)):
                rep["unreadable"] += 1
                continue
            g = self.plan_genre(p, info)
            if not self.in_place(p, g):
                rep[f"to_move|{self.label(g)}"] += 1
            if self.opts.dedupe:
                k = track_key(p, self.opts.merge_versions, info)
                if k:
                    groups[k] += 1
        rep["tracks"] = len(files)
        if self.opts.dedupe:
            rep["dups_pending"] = sum(c - 1 for c in groups.values() if c > 1)
        return rep


def _hide(path):
    try:
        ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x2)  # FILE_ATTRIBUTE_HIDDEN
    except Exception:
        pass


def purge_quarantine(root, older_than_days=None):
    """Quarantined runs -> Recycle Bin (all of them, or only older ones). Returns how many runs."""
    qroot = os.path.join(root, QUARANTINE)
    if not os.path.isdir(qroot):
        return 0
    limit = time.time() - older_than_days * 86400 if older_than_days is not None else None
    n = 0
    for d in os.listdir(qroot):
        p = os.path.join(qroot, d)
        try:
            if limit is None or os.path.getmtime(p) < limit:
                send2trash(p)
                n += 1
        except OSError:
            pass
    try:
        if not os.listdir(qroot):
            os.rmdir(qroot)
    except OSError:
        pass
    return n


KEEP_LOGS = 30


def prune_logs(data_dir):
    d = os.path.join(data_dir, "execucoes")
    logs = sorted(f for f in os.listdir(d) if f.endswith(".csv"))
    for f in logs[:-KEEP_LOGS]:
        try:
            os.remove(os.path.join(d, f))
        except OSError:
            pass


def _remove_empty(top):
    for dp, _, _ in sorted(os.walk(top), key=lambda w: -len(w[0])):
        try:
            os.rmdir(dp)  # only succeeds when empty
        except OSError:
            pass


def _move_back(src, dst, errors, retry):
    """dst -> src; True when moved. retry: set to True when trying again later could succeed."""
    if not os.path.exists(dst):
        errors.append(t("err.undo_missing", path=dst))
        return False
    if os.path.exists(src):
        errors.append(t("err.undo_conflict", path=src))
        retry[0] = True
        return False
    try:
        os.makedirs(os.path.dirname(src), exist_ok=True)
        shutil.move(dst, src)
        return True
    except OSError as e:
        errors.append(f"{dst}: {e}")
        retry[0] = True  # e.g. file open in rekordbox
        return False


def undo_last(root, progress=None, cancel=None):
    """Undoes the last run: tags back to the originals, removed files out of quarantine, moves reversed."""
    with library_lock(root):
        return _undo_last(root, progress, cancel)


def _undo_last(root, progress, cancel):
    progress = progress or (lambda *a: None)
    runs_dir = os.path.join(data_dir_for(root), "execucoes")
    runs = sorted(f for f in os.listdir(runs_dir) if f.endswith(".csv") and not f.endswith(".desfeito.csv"))
    if not runs:
        return Counter({"undo_nothing": 1}), []
    path = os.path.join(runs_dir, runs[-1])
    with open(path, encoding="utf-8") as fh:
        rows = [r for r in csv.reader(fh) if r]
    rep, errors, retry = Counter(), [], [False]
    failed = {(r[1], r[2]) for r in rows if r[0] == "falhou" and len(r) > 2}
    todo = [r for r in rows if r[0] in ("tags", "quarentena", "mover") and len(r) > 2 and (r[1], r[2]) not in failed]
    for i, (kind, a, b) in enumerate(reversed([r[:3] for r in todo]), 1):  # newest first: replays the chain
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        progress("undo", i, len(todo), os.path.basename(a))
        if kind == "tags":
            if os.path.exists(a):
                try:
                    restore(a, b)
                    rep["undo_tags"] += 1
                except Exception as e:
                    errors.append(f"{a}: {e}")
        elif _move_back(a, b, errors, retry):
            rep["undo_from_quarantine" if kind == "quarentena" else "undo_returned"] += 1
    found = [os.path.basename(r[1]) for r in rows if r[0] == "genero" and len(r) > 1]
    if found:  # otherwise the next run would move them out again
        opath = os.path.join(data_dir_for(root), "generos_corrigidos.json")
        try:
            with open(opath, encoding="utf-8") as fh:
                ov = json.load(fh)
            for n in found:
                ov.pop(n, None)
            with open(opath, "w", encoding="utf-8") as fh:
                json.dump(ov, fh, ensure_ascii=False)
        except (OSError, json.JSONDecodeError):
            pass
    legacy = sum(1 for r in rows if r[0] == "reciclagem")  # runs before the quarantine existed
    if legacy:
        rep["undo_in_trash"] = legacy
    if not retry[0]:  # pending only when retrying can help (conflict, file in use); missing files never come back
        os.replace(path, path[:-4] + ".desfeito.csv")
        _remove_empty(os.path.join(root, QUARANTINE))  # this run's now-empty quarantine folders
    return rep, errors
