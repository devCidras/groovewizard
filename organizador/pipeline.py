"""The organizer: extract packs, sort by genre, drop duplicates, look up missing genres, tidy tags.

Every move is logged so the last run can be undone. Deleted files go to the Recycle Bin, never straight away.
"""
import csv
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
from dataclasses import dataclass

from send2trash import send2trash

from . import bpm as bpm_mod
from .online import Lookup
from .i18n import t
from .regras import FAMILY_OF, FOLDER_NAMES, NO_GENRE, OTHER
from .tags import (LIST_SEP, LOSSLESS, SPAM, clean_sites, duration, genre_from_folder, genre_of, is_audio,
                   normalize_genre, raw_genre, search_terms, track_key, write_genre)

APP_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Cratekeeper")
_OLD_DIR = os.path.join(os.path.dirname(APP_DIR), "OrganizadorMusica")  # name before v0.2
if os.path.isdir(_OLD_DIR) and not os.path.exists(APP_DIR):
    try:
        os.rename(_OLD_DIR, APP_DIR)
    except OSError:
        pass
ARCHIVES = {".zip", ".rar", ".7z"}
SKIP_DIRS = {"downloading", "incomplete"}  # transfers still in progress (Soulseek / Nicotine+)
INBOX = "_entrada"  # where packs are extracted before sorting
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


class Cancelled(Exception):
    pass


def data_dir_for(root):
    """Caches and logs live in %APPDATA%, not in the music folder (which may be shared on Soulseek)."""
    safe = re.sub(r"[^\w.-]+", "_", os.path.abspath(root)).strip("_")
    d = os.path.join(APP_DIR, "bibliotecas", safe)
    os.makedirs(os.path.join(d, "execucoes"), exist_ok=True)
    return d


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
        self.keys = keys or {}
        self.progress = progress or (lambda step, i, n, msg="": None)
        self.cancel = cancel or threading.Event()
        self.data = data_dir_for(self.root)
        self.names = FOLDER_NAMES.get(opts.folder_lang, FOLDER_NAMES["pt"])
        self.report = Counter()
        self.errors = []
        self._log = None
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
            path = os.path.join(self.data, "execucoes", time.strftime("%Y%m%d-%H%M%S") + ".csv")
            self._log = open(path, "a", newline="", encoding="utf-8")
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
        try:
            shutil.move(src, dst)  # rename on the same drive
        except OSError as e:
            self.errors.append(f"{src}: {e}")
            return None
        self._write_log("mover", src, dst)
        return dst

    def trash(self, path):
        try:
            send2trash(path)
        except Exception as e:
            self.errors.append(f"{path}: {e}")
            return False
        self._write_log("reciclagem", path, "")
        return True

    def audio_files(self, base=None):
        base = base or self.root
        for dp, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIRS and not (dp == self.root and d.startswith("_") and d != INBOX)]
            for n in files:
                if is_audio(n):
                    yield os.path.join(dp, n)

    def _save_overrides(self):
        tmp = self._overrides_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.overrides, fh, ensure_ascii=False, indent=0)
        os.replace(tmp, self._overrides_path)

    def remove_empty_dirs(self):
        for dp, dirs, files in os.walk(self.root, topdown=False):
            if dp == self.root or os.path.basename(dp).lower() in SKIP_DIRS:
                continue
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
            dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIRS and d != INBOX]
            for n in files:
                p = os.path.join(dp, n)
                if os.path.splitext(n)[1].lower() in ARCHIVES and self._archive_id(p) not in done:
                    out.append(p)
        return sorted(out)

    def _archive_id(self, p):
        return f"{os.path.basename(p)}|{os.path.getsize(p)}"

    def _done_archives(self):
        try:
            with open(os.path.join(self.data, "extraidos.json"), encoding="utf-8") as fh:
                return set(json.load(fh))
        except (FileNotFoundError, json.JSONDecodeError):
            return set()

    def step_extract(self):
        archives = self.pending_archives()
        done = self._done_archives()
        seven = _find_7zip()
        for i, a in enumerate(archives, 1):
            self._tick("extract", i, len(archives), os.path.basename(a))
            out = os.path.join(self.root, INBOX, os.path.splitext(os.path.basename(a))[0].strip(" ."))
            try:
                if a.lower().endswith(".zip"):
                    with zipfile.ZipFile(a) as z:
                        z.extractall(out)  # extractall drops absolute paths and '..'
                elif seven:
                    r = subprocess.run([seven, "x", a, f"-o{out}", "-aos", "-y", "-bso0", "-bsp0"],
                                       capture_output=True, text=True, errors="replace",
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    if r.returncode != 0:
                        raise RuntimeError(r.stderr.strip()[:200] or f"7-Zip erro {r.returncode}")
                else:
                    raise RuntimeError(t("err.need_7zip"))
            except Exception as e:
                self.errors.append(f"{os.path.basename(a)}: {e}")
                continue
            done.add(self._archive_id(a))
            with open(os.path.join(self.data, "extraidos.json"), "w", encoding="utf-8") as fh:
                json.dump(sorted(done), fh, ensure_ascii=False)
            self.report["archives_extracted"] += 1
            if self.opts.delete_archives and self.trash(a):
                self.report["archives_trashed"] += 1

    def plan_genre(self, path):
        name = os.path.basename(path)
        rel = os.path.relpath(path, self.root).split(os.sep)
        pack = rel[1] if rel[0] == INBOX and len(rel) > 2 else None
        g = self.overrides.get(name)
        return g or genre_of(path) or genre_from_folder(path, pack) or NO_GENRE

    def step_organize(self):
        files = list(self.audio_files())
        for i, p in enumerate(files, 1):
            self._tick("organize", i, len(files), os.path.basename(p))
            g = self.plan_genre(p)
            if not self.in_place(p, g) and self.move(p, self.target_dir(g)):
                self.report[f"moved|{self.label(g)}"] += 1
        inbox = os.path.join(self.root, INBOX)
        if os.path.isdir(inbox) and not any(True for _ in self.audio_files(inbox)):
            for dp, _, fs in os.walk(inbox):  # covers, .nfo, .url... from the packs
                for n in fs:
                    if self.trash(os.path.join(dp, n)):
                        self.report["junk_trashed"] += 1
        self.remove_empty_dirs()

    @staticmethod
    def _score(path, dur):
        # DJ preference: Extended Mix, then longest, then lossless, then bigger file
        ext = bool(re.search(r"extended", os.path.basename(path), re.I))
        return ext, round(dur), os.path.splitext(path)[1].lower() in LOSSLESS, os.path.getsize(path)

    def step_dedupe(self):
        files = list(self.audio_files())
        groups = defaultdict(list)
        with ThreadPoolExecutor(8) as ex:
            for i, (p, key, dur) in enumerate(ex.map(lambda p: (p, track_key(p), duration(p)), files), 1):
                if i % 50 == 0 or i == len(files):
                    self._tick("dedupe_scan", i, len(files))
                if key:
                    groups[key].append((p, dur))
        dups = [sorted(v, key=lambda x: self._score(*x), reverse=True) for v in groups.values() if len(v) > 1]
        losers = [p for v in dups for p, _ in v[1:]]
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
                    if self.move(p, self.target_dir(g)):
                        self._write_log("genero", p, f"{g} ({src})")
                        self.report[f"online|{g}"] += 1
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
                if self.opts.write_tags:
                    self._fix_genre_tag(p)
                if self.opts.clean_sites and clean_sites(p):
                    self.report["sites_cleaned"] += 1
            except Exception as e:
                self.errors.append(f"{os.path.basename(p)}: {e}")

    def _fix_genre_tag(self, p):
        raw = raw_genre(p)
        top = os.path.relpath(p, self.root).split(os.sep)[0]
        if top in (self.names[NO_GENRE], self.names[OTHER]):
            if SPAM.search(raw):
                write_genre(p, "")
                self.report["genre_spam_cleared"] += 1
            elif top == self.names[OTHER] and LIST_SEP.search(raw):
                write_genre(p, LIST_SEP.split(raw)[0].strip())
                self.report["genre_tag_fixed"] += 1
            return
        here = os.path.basename(os.path.dirname(p))
        if not self.in_place(p, here):
            return  # not inside a genre folder
        # keep a more specific tag that maps to this folder (e.g. "Afro House" inside House)
        if normalize_genre(raw) != here or LIST_SEP.search(raw) or SPAM.search(raw):
            write_genre(p, here)
            self.report["genre_tag_fixed"] += 1

    # ---------- run ----------

    def run(self):
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
        rep = Counter()
        rep["archives_pending"] = len(self.pending_archives())
        files = list(self.audio_files())
        groups = Counter()
        for i, p in enumerate(files, 1):
            self._tick("preview", i, len(files), os.path.basename(p))
            g = self.plan_genre(p)
            if not self.in_place(p, g):
                rep[f"to_move|{self.label(g)}"] += 1
            if self.opts.dedupe:
                k = track_key(p)
                if k:
                    groups[k] += 1
        rep["tracks"] = len(files)
        if self.opts.dedupe:
            rep["dups_pending"] = sum(c - 1 for c in groups.values() if c > 1)
        return rep


def undo_last(root, progress=None):
    """Moves files of the last run back. Files sent to the Recycle Bin stay there (restore them from Windows)."""
    progress = progress or (lambda *a: None)
    runs_dir = os.path.join(data_dir_for(root), "execucoes")
    runs = sorted(f for f in os.listdir(runs_dir) if f.endswith(".csv") and not f.endswith(".desfeito.csv"))
    if not runs:
        return Counter({"undo_nothing": 1}), []
    path = os.path.join(runs_dir, runs[-1])
    with open(path, encoding="utf-8") as fh:
        rows = [r for r in csv.reader(fh) if r]
    rep, errors = Counter(), []
    moves = [r for r in rows if r[0] == "mover"]
    for i, (_, src, dst) in enumerate(reversed(moves), 1):
        progress("undo", i, len(moves), os.path.basename(src))
        if os.path.exists(dst) and not os.path.exists(src):
            try:
                os.makedirs(os.path.dirname(src), exist_ok=True)
                shutil.move(dst, src)
                rep["undo_returned"] += 1
            except OSError as e:
                errors.append(f"{dst}: {e}")
    rep["undo_in_trash"] = sum(1 for r in rows if r[0] == "reciclagem")
    os.replace(path, path[:-4] + ".desfeito.csv")
    return rep, errors
