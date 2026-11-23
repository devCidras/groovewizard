"""The organizer: extract packs, sort by genre, drop duplicates, look up missing genres, tidy tags.

Every change is logged before it happens so the last run can be undone: extractions, moves, tag edits
(original tags are saved) and removals. Removed files go to a quarantine folder inside the library (same
drive, instant), kept 30 days, then sent to the Recycle Bin. Nothing is ever deleted outright.
"""
import csv
import ctypes
import errno
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
import zipfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass

from send2trash import send2trash

from . import bpm as bpm_mod
from .i18n import t
from .online import Lookup
from .regras import FAMILY_OF, FOLDER_NAMES, NO_GENRE, OTHER
from .tags import (JUNK_TAG_SPAM, LIST_SEP, LOSSLESS, clean_sites, fix_tags, genre_from_folder, is_audio,
                   normalize_genre, raw_genre, read_info, restore, search_terms, snapshot, track_key, version_label)

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
QUARANTINE_MARK = ".quarentena-da-app"  # written by the app; a _quarentena without it is not ours
RUN_DIR = re.compile(r"^\d{8}-\d{6}-\d+-\d+$")  # run_id format
KEEP_LOGS = 30
# extraction guards (zip bombs, full disks), per run
MAX_MEMBERS = 100_000
MAX_ARCHIVES = 500
MAX_RATIO = 200
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


class Cancelled(Exception):
    pass


class Busy(Exception):
    pass


def data_dir_for(root):
    """Caches and logs live in %APPDATA%, not in the music folder (which may be shared on Soulseek)."""
    canon = os.path.normcase(os.path.realpath(root))  # d:\ == D:\
    tag = hashlib.sha1(canon.encode("utf-8")).hexdigest()[:12]
    safe = re.sub(r"[^\w.-]+", "_", os.path.basename(canon.rstrip("\\/")) or "raiz")[:40]
    d = os.path.join(APP_DIR, "bibliotecas", f"{safe}-{tag}")
    os.makedirs(os.path.join(d, "execucoes"), exist_ok=True)
    return d


def _write_json(path, obj):
    """Atomic: a crash leaves the old file, never half a file."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _read_json(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
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


def _find_7zip():
    for p in SEVEN_ZIP:
        if os.path.isfile(p) or shutil.which(p):
            return p
    return None


def _hide(path):
    try:
        ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x2)  # FILE_ATTRIBUTE_HIDDEN
    except Exception:
        pass


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
        self.overrides = _read_json(self._overrides_path, {})  # track id -> genre found online
        self._extracted_bytes = self._extracted_members = self._extracted_archives = 0

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

    def _in_inbox(self, p):
        return os.path.normcase(p).startswith(os.path.normcase(os.path.join(self.root, INBOX)) + os.sep)

    def move(self, src, dst_dir):
        """Never overwrites and never deletes a file it did not create itself."""
        os.makedirs(dst_dir, exist_ok=True)
        base, ext = os.path.splitext(os.path.join(dst_dir, os.path.basename(src)))
        dst, i = base + ext, 1
        while os.path.exists(dst):
            dst, i = f"{base} ({i}){ext}", i + 1
        self._write_log("mover", src, dst)  # before the move: a crash right after still leaves a record
        tmp = None
        try:
            try:
                os.rename(src, dst)  # same drive; on Windows it fails instead of overwriting
            except OSError as e:
                if getattr(e, "winerror", None) != 17 and e.errno != errno.EXDEV:  # 17: not the same drive
                    raise
                tmp = f"{dst}.ck-{self.run_id}.part"  # our own name: safe to remove if the copy fails
                shutil.copy2(src, tmp)
                os.rename(tmp, dst)
                tmp = None
                os.remove(src)
        except OSError as e:
            self._write_log("falhou", src, dst)
            if tmp and os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            self.errors.append(f"{src}: {e}")
            return None
        return dst

    def trash(self, path):
        """Into this run's quarantine folder (Undo brings it back). Same drive: a rename, no copy."""
        rel = os.path.relpath(path, self.root)
        dst = os.path.join(self.qdir, rel)
        # (raises if a user folder called _quarentena already exists: stops before touching anything)
        qroot = os.path.join(self.root, QUARANTINE)
        if not os.path.isdir(qroot):
            os.makedirs(qroot, exist_ok=True)
            _hide(qroot)  # not shown in Explorer / shares that skip hidden folders
            open(os.path.join(qroot, QUARANTINE_MARK), "w").close()
        elif not os.path.exists(os.path.join(qroot, QUARANTINE_MARK)):
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
        self._write_log("tags", p, snapshot(p))
        before = read_info(p)["duration"]
        tmp = f"{p}.ck-{self.run_id}{os.path.splitext(p)[1]}"  # same extension: mutagen picks the format by it
        shutil.copy2(p, tmp)
        try:
            changed = fix_tags(tmp, genre=genre, clean=clean)
            check = read_info(tmp)
            # length unknown before (some AIFF without tags report 0) only needs to be readable after
            if check["unreadable"] or not check["duration"] or (before and abs(check["duration"] - before) > 0.5):
                raise RuntimeError(t("err.tag_check"))
            os.replace(tmp, p)
            return changed
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    def audio_files(self, base=None):
        base = base or self.root
        for dp, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIRS and not (dp == self.root and d.startswith("_") and d != INBOX)]
            for n in files:
                if is_audio(n) and ".ck-" not in n:  # our own temporary copies (left only by a crash)
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

    def override_key(self, p, info):
        """Online genres are remembered per track (artist + title + length), not per file name."""
        return f"{track_key(p, False, info) or os.path.basename(p).lower()}|{round(info['duration'])}"

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

    # ---------- archives ----------

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
            rel = os.path.normcase(os.path.relpath(p, self.root))
            return f"{rel}|{st.st_size}|{st.st_mtime_ns}"
        except OSError:  # vanished (e.g. moved by the download client)
            return None

    def _done_archives(self):
        return set(_read_json(os.path.join(self.data, "extraidos.json"), []))

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
            out, k = os.path.join(parent, stem), 2
            while os.path.exists(out):
                out, k = os.path.join(parent, f"{stem} ({k})"), k + 1
            aid = self._archive_id(a)
            try:
                self._extracted_archives += 1
                if self._extracted_archives > MAX_ARCHIVES:
                    raise RuntimeError(t("err.archive_many", n=self._extracted_archives))
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
        if listing.returncode != 0 or not sizes:  # can't see inside: don't extract blind
            raise RuntimeError(t("err.archive_list"))
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

    # ---------- genre ----------

    def plan_genre(self, path, info=None):
        info = info or read_info(path)
        rel = os.path.relpath(path, self.root).split(os.sep)
        pack = rel[1] if rel[0] == INBOX and len(rel) > 2 else None
        g = self.overrides.get(self.override_key(path, info))
        if g == NO_GENRE:  # taken out of a guessed genre on purpose
            return NO_GENRE
        return normalize_genre(info["genre"]) or g or genre_from_folder(path, pack) or NO_GENRE

    def step_organize(self):
        files = list(self.audio_files())
        infos = self._read_all(files, "organize")
        for i, p in enumerate(files, 1):
            self._tick("organize", i, len(files), os.path.basename(p))
            if infos[p]["unreadable"] and not self._in_inbox(p):
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
        groups = defaultdict(list)
        for p, info in infos.items():
            if info["unreadable"]:
                continue  # damaged tags: its length is unknown (0), it would always lose
            key = track_key(p, self.opts.merge_versions, info)
            if key:
                groups[key].append((p, info["duration"]))
        out = []
        for v in groups.values():
            if len(v) > 1:
                ranked = sorted(v, key=lambda x: self._score(x[0], x[1], infos[x[0]]["title"]), reverse=True)
                out += self._losers(ranked, infos)
        return out

    def step_dedupe(self):
        infos = self._read_all(list(self.audio_files()), "dedupe_scan")
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
        files = list(self.audio_files(base)) if os.path.isdir(base) else []
        try:
            for i, p in enumerate(files, 1):
                self._tick("online", i, len(files), os.path.basename(p))
                info = read_info(p)
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
                if self.opts.write_tags:
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

    # ---------- BPM ----------

    def _loose_unsorted(self):
        files = []
        for top in (NO_GENRE, OTHER):
            d = self.target_dir(top)
            if os.path.isdir(d):
                files += [os.path.join(d, n) for n in os.listdir(d) if is_audio(n)]  # only loose ones
        return files

    def step_bpm(self):
        files = self._loose_unsorted()
        ex = ThreadPoolExecutor(4)
        try:
            for done, (p, b) in enumerate(zip(files, ex.map(bpm_mod.bpm_of, files)), 1):
                self._tick("bpm", done, len(files), os.path.basename(p))
                if self.move(p, os.path.join(os.path.dirname(p), bpm_mod.bucket(b, self.names))):
                    self.report["bpm_sorted"] += 1
        finally:
            ex.shutdown(wait=True, cancel_futures=True)  # on cancel: don't measure the rest

    # ---------- tags ----------

    def step_tags(self):
        files = list(self.audio_files())
        for i, p in enumerate(files, 1):
            self._tick("tags", i, len(files), os.path.basename(p))
            try:
                info = read_info(p)
                if info["unreadable"]:
                    continue  # damaged tags: never write into them
                genre, key = self._genre_decision(p, info["genre"]) if self.opts.write_tags else (None, None)
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

    def run(self):
        with library_lock(self.root):
            _purge_quarantine(self.root, QUARANTINE_DAYS)  # here, not in __init__: Preview must not change anything
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
        """What a run would do with the files as they are now, without touching anything.
        Not included: tracks still inside packs, online results, site cleaning in tags (see log.preview_limits)."""
        with library_lock(self.root):
            return self._preview()

    def _preview(self):
        rep = Counter()
        if self.opts.extract:
            rep["archives_pending"] = len(self.pending_archives())
        files = list(self.audio_files())
        infos = self._read_all(files, "preview")
        for p, info in infos.items():
            if info["unreadable"] and not self._in_inbox(p):
                rep["unreadable"] += 1
                continue
            g = self.plan_genre(p, info)
            if not self.in_place(p, g):
                rep[f"to_move|{self.label(g)}"] += 1
            elif self.opts.write_tags and self._genre_decision(p, info["genre"])[0] is not None:
                rep["tags_pending"] += 1
        rep["tracks"] = len(files)
        if self.opts.dedupe:
            rep["dups_pending"] = len(self.find_duplicates(infos))
        if self.opts.bpm_folders:
            rep["bpm_pending"] = len(self._loose_unsorted())
        if self.opts.online and os.path.isdir(self.target_dir(NO_GENRE)):
            rep["online_pending"] = sum(1 for _ in self.audio_files(self.target_dir(NO_GENRE)))
        inbox = os.path.join(self.root, INBOX)
        if os.path.isdir(inbox):
            rep["junk_pending"] = sum(1 for _, _, fs in os.walk(inbox) for n in fs
                                      if os.path.splitext(n)[1].lower() in JUNK_EXT)
        return Counter({k: v for k, v in rep.items() if v or k == "tracks"})


# ---------- quarantine / logs ----------

def purge_quarantine(root, older_than_days=None):
    """Quarantined runs -> Recycle Bin. Takes the library lock (never while an Undo is running)."""
    with library_lock(root):
        return _purge_quarantine(root, older_than_days)


def _purge_quarantine(root, older_than_days=None):
    qroot = os.path.join(root, QUARANTINE)
    if not os.path.isdir(qroot):
        return 0
    if not os.path.exists(os.path.join(qroot, QUARANTINE_MARK)):
        return 0  # not created by this app: never touch it
    limit = time.time() - older_than_days * 86400 if older_than_days is not None else None
    n = 0
    for d in os.listdir(qroot):
        p = os.path.join(qroot, d)
        if not (RUN_DIR.match(d) and os.path.isdir(p)):
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
    logs = sorted(f for f in os.listdir(d) if f.endswith(".csv"))
    for f in logs[:-KEEP_LOGS]:
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
        if check["unreadable"] or (before and check["duration"] and abs(check["duration"] - before) > 0.5):
            raise RuntimeError(t("err.tag_check"))
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _move_back(src, dst, errors, retry):
    """dst -> src; True when moved. retry[0] = True when trying again later could succeed."""
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
    """Undoes the last run: tags back to the originals, removed files out of quarantine, moves reversed,
    extracted packs put aside."""
    with library_lock(root):
        return _undo_last(root, progress, cancel)


def _undo_last(root, progress, cancel):
    progress = progress or (lambda *a: None)
    data = data_dir_for(root)
    runs_dir = os.path.join(data, "execucoes")
    runs = sorted(f for f in os.listdir(runs_dir) if f.endswith(".csv") and not f.endswith(".desfeito.csv"))
    if not runs:
        return Counter({"undo_nothing": 1}), []
    path = os.path.join(runs_dir, runs[-1])
    run_id = runs[-1][:-4]
    with open(path, encoding="utf-8") as fh:
        rows = [r for r in csv.reader(fh) if r]
    done_path = path + ".feito"  # entries already undone by an earlier (partial) attempt
    try:
        with open(done_path, encoding="utf-8") as fh:
            done = {int(x) for x in fh.read().split()}
    except FileNotFoundError:
        done = set()
    rep, errors, retry = Counter(), [], [False]
    failed = {(r[1], r[2]) for r in rows if r[0] == "falhou" and len(r) > 2}
    kinds = ("tags", "quarentena", "mover", "extraido", "genero")
    todo = [(i, r) for i, r in enumerate(rows) if r[0] in kinds and len(r) > 2 and (r[1], r[2]) not in failed
            and i not in done]
    overrides_path = os.path.join(data, "generos_corrigidos.json")
    overrides = _read_json(overrides_path, {})
    extracted = set(_read_json(os.path.join(data, "extraidos.json"), []))
    with open(done_path, "a", encoding="utf-8") as done_fh:
        for n, (i, r) in enumerate(reversed(todo), 1):  # newest first: replays the chain backwards
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            kind, a, b = r[:3]
            progress("undo", n, len(todo), os.path.basename(a))
            ok = False
            if kind == "tags":
                if not os.path.exists(a):
                    errors.append(t("err.undo_missing", path=a))
                else:
                    try:
                        _safe_restore(a, b, run_id)
                        rep["undo_tags"] += 1
                        ok = True
                    except Exception as e:  # e.g. file open in another program: try again later
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
                    dst = os.path.join(root, QUARANTINE, run_id, "_extracoes_desfeitas", os.path.basename(b))
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    try:
                        os.rename(b, dst)
                    except OSError as e:
                        errors.append(f"{b}: {e}")
                        retry[0] = True
                        continue
                extracted.discard(a)
                rep["undo_extract"] += 1
                ok = True
            else:
                ok = _move_back(a, b, errors, retry)
                if ok:
                    rep["undo_from_quarantine" if kind == "quarentena" else "undo_returned"] += 1
            if ok:
                done_fh.write(f"{i}\n")
                done_fh.flush()
    _write_json(overrides_path, overrides)
    _write_json(os.path.join(data, "extraidos.json"), sorted(extracted))
    legacy = sum(1 for r in rows if r[0] == "reciclagem")  # runs before the quarantine existed
    if legacy:
        rep["undo_in_trash"] = legacy
    if not retry[0]:  # pending only when retrying can help (conflict, file in use); missing files never come back
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
