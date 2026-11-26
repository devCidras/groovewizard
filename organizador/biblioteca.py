"""Library review, rekordbox playlist references and portable set exports."""
import os
import ntpath
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from . import pipeline as pl
from .i18n import t
from .tags import artist_title, normalize_genre, is_audio, read_info

PLAYLIST_FILE = "rekordbox_playlists.json"
DEFERRED_FILE = pl.DEFERRED_FILE


def stamp(path):
    st = os.stat(path)
    return st.st_size, st.st_mtime_ns


def library_file(org, path):
    if not pl._direct_library_path(org.root, path, org.resolved_root):
        return False
    parts = Path(os.path.relpath(path, org.root)).parts
    if len(parts) > 1 and parts[0].startswith("_") and parts[0].lower() != pl.INBOX:
        return False
    return not org.left_alone(path) and is_audio(path)


@dataclass(frozen=True)
class Track:
    path: str
    artist: str
    title: str
    genre: str
    bpm: float | None
    duration: float
    stamp: tuple
    problems: tuple
    raw_artist: str
    raw_title: str
    raw_genre: str
    artists: tuple = ()

    @property
    def exportable(self):
        return self.stamp[0] > 0 and "report_unreadable" not in self.problems


def catalogue(opts, cancel, duplicates=False, previous=None, *, background_index=False):
    """Interactive reviews use an exclusive snapshot. The Radar only reads and discards moved/changed tracks."""
    org = pl.Organizer(opts, cancel=cancel)
    if background_index and duplicates:
        raise ValueError("Duplicate review requires a locked snapshot")
    with nullcontext() if background_index else pl.library_lock(org.root):
        files = [p for p in org.audio_files() if library_file(org, p)]
        snapshot = org.library_snapshot()
        stamps = {v[0]: v[1:] for v in snapshot.files if len(v) == 3}
        tracks = {p: previous[p] for p in files if previous and not duplicates and p in previous
                  and previous[p].stamp == stamps.get(os.path.normcase(p))}
        infos = org._read_all([p for p in files if p not in tracks], "report")
        for path, info in infos.items():
            if cancel.is_set():
                raise pl.Cancelled()
            identity = stamps.get(os.path.normcase(path))
            if not identity:
                continue
            problems = pl.track_problems(info)
            inferred_artist, inferred_title = artist_title(path, info) or ("", Path(path).stem)
            artist = info["artist"].strip() or inferred_artist
            title = info["title"].strip() or inferred_title
            genre = info["genre"] if normalize_genre(info["genre"]) else org.plan_genre(path, info)
            bpm = info["bpm"]
            if not bpm and org._bpm_cache:
                bpm = org._cached_bpm(path)[1]
            tracks[path] = Track(path, artist, title, genre, bpm, info["duration"], identity, tuple(problems),
                                 info["artist"], info["title"], info["genre"], info["artists"])
        if background_index:
            for path, track in list(tracks.items()):
                try:
                    if stamp(path) == track.stamp:
                        continue
                except OSError:
                    pass  # disappeared while a foreground operation was running
                del tracks[path]
        if duplicates:
            org._fresh = org._new_tracks()
            org._load_deferred()
            org.find_duplicates(infos, include_deferred=True)
            org.snapshot = snapshot
            org._duplicate_details(infos, review=True)
            snapshot = org.snapshot
    return tracks, org.dup_best, org.dup_details, snapshot


def edit_metadata(opts, track, artist, title, genre):
    org = pl.Organizer(opts)
    with pl.library_lock(org.root):
        if not library_file(org, track.path) or stamp(track.path) != track.stamp:
            raise ValueError(t("plan.stale"))
        credits = {k: v for k, v, old in (("artist", artist, track.raw_artist), ("title", title, track.raw_title))
                   if v != old}
        try:
            if credits or genre != track.raw_genre:
                org._edit_tags(track.path, genre=genre if genre != track.raw_genre else None, credits=credits)
        finally:
            if org._log:
                org._log.close()


def saved_map(root, filename):
    if filename == DEFERRED_FILE:
        return pl.read_deferred(root)
    value = pl._read_json(os.path.join(pl.data_dir_for(root, create=False), filename), {})
    return value if isinstance(value, dict) else {}


def defer_issue(root, key, signature, defer):
    with pl.library_lock(root):
        items = saved_map(root, DEFERRED_FILE)
        if defer:
            items[key] = signature
        else:
            items.pop(key, None)
        pl._write_json(os.path.join(pl.data_dir_for(root), DEFERRED_FILE), items)


def playlist_path(value):
    """Match by full location only. A second copy with the same basename is a different track."""
    if not value:
        return ""
    if value.lower().startswith("file:"):
        uri = urlsplit(value)
        value = unquote(uri.path)
        if uri.netloc and uri.netloc.lower() != "localhost":
            value = "//" + uri.netloc + value
        elif re.match(r"^/[A-Za-z]:", value):
            value = value[1:]
    return ntpath.normcase(ntpath.normpath(value)) if ntpath.isabs(value) else ""


def import_playlists(root, filename, cancel=None):
    tree = ET.parse(filename).getroot()
    collection, lists = tree.find("COLLECTION"), tree.find("PLAYLISTS")
    if tree.tag != "DJ_PLAYLISTS" or collection is None or lists is None:
        raise ValueError(t("dj.bad_xml"))
    locations = {}
    known_paths = set()
    for entry in collection.iterfind("TRACK"):
        path = playlist_path(entry.get("Location"))
        if path:
            known_paths.add(path)
            if entry.get("TrackID"):
                locations[entry.get("TrackID")] = path
    memberships = defaultdict(set)
    def visit(node, folders):
        if cancel is not None and cancel.is_set():
            raise pl.Cancelled()
        name = node.get("Name") or "?"
        route = folders + [name]
        if node.get("Type") == "1":
            for track in node.findall("TRACK"):
                key = track.get("Key", "")
                path = playlist_path(key) if node.get("KeyType") == "1" else locations.get(key)
                if path and path in known_paths:
                    memberships[path].add(" / ".join(route))
        else:
            for child in node.findall("NODE"):
                visit(child, route)
    for node in lists.findall("NODE"):
        if node.get("Name") == "ROOT" and node.get("Type") == "0":
            for child in node.findall("NODE"):
                visit(child, [])
        else:
            visit(node, [])
    result = {"xml": os.path.basename(filename), "tracks": {p: sorted(memberships.get(p, ())) for p in known_paths if p}}
    with pl.library_lock(root):
        if cancel is not None and cancel.is_set():
            raise pl.Cancelled()
        pl._write_json(os.path.join(pl.data_dir_for(root), PLAYLIST_FILE), result)
    return result


def playlist_description(playlists, path):
    names = playlists.get("tracks", {}).get(playlist_path(path))
    if names is None:
        return t("dj.path_not_in_xml")
    return t("dj.memberships", n=len(names), names=", ".join(names)).rstrip()


def _set_filename(number, path):
    """Keep the running order and extension, even when the original fills a filename."""
    original = Path(path)
    prefix = f"{number:03d} - "
    suffix = original.suffix
    encoding, limit = ("utf-16-le", 510) if os.name == "nt" else (sys.getfilesystemencoding(), 255)
    budget = limit - len((prefix + suffix).encode(encoding))
    stem = original.stem.encode(encoding)[:budget].decode(encoding, errors="ignore")
    return prefix + stem + suffix


def export_set(opts, selection, target, cancel, name="DJ Set"):
    """Publish an entirely new folder on the destination volume only after the last copy succeeds."""
    tracks = list(selection)
    org = pl.Organizer(opts, cancel=cancel)
    target = Path(target).resolve(strict=True)
    if not tracks or not target.is_dir() or pl._inside(pl._norm(target), pl._norm(org.root)):
        raise ValueError(t("dj.export_target"))
    name = name.strip()
    if (not name or re.search(r'[<>:"/\\|?*\x00-\x1f]', name) or name.endswith((".", " "))
            or name in (".", "..") or re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)", name, re.I)):
        raise ValueError(t("dj.bad_name"))
    destination = target / name
    if os.path.lexists(destination):
        raise FileExistsError(t("dj.set_exists"))
    with pl.library_lock(org.root):
        for track in tracks:
            if not track.exportable:
                raise ValueError(t("dj.unreadable_export", name=Path(track.path).name))
        if sum(track.stamp[0] for track in tracks) > shutil.disk_usage(target).free:
            raise ValueError(t("dj.space"))
        # A private staging folder also prevents an incomplete playlist appearing after unplugging a drive.
        stage = Path(tempfile.mkdtemp(prefix=".groovewizard-", dir=target))
        try:
            entries = ["#EXTM3U"]
            for i, track in enumerate(tracks, 1):
                if cancel.is_set():
                    raise pl.Cancelled()
                if not library_file(org, track.path) or stamp(track.path) != track.stamp:
                    raise ValueError(t("plan.stale"))
                filename = _set_filename(i, track.path)
                with open(track.path, "rb") as src, (stage / filename).open("xb") as dst:
                    while block := src.read(1024 * 1024):
                        if cancel.is_set():
                            raise pl.Cancelled()
                        dst.write(block)
                if stamp(track.path) != track.stamp or (stage / filename).stat().st_size != track.stamp[0]:
                    raise ValueError(t("plan.stale"))
                if read_info(stage / filename)["unreadable"]:
                    raise ValueError(t("dj.unreadable_export", name=Path(track.path).name))
                entries.append(filename)
            (stage / "Set.m3u8").write_text("\n".join(entries) + "\n", encoding="utf-8")
            if cancel.is_set():
                raise pl.Cancelled()
            if os.path.lexists(destination):
                raise FileExistsError(t("dj.set_exists"))
            os.rename(stage, destination)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
    return str(destination / "Set.m3u8")
