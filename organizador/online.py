"""Genre lookup online: Discogs (styles per track), Last.fm and MusicBrainz (tags per artist). Cached in JSON."""
import http.client
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import __version__
from .regras import ONLINE_RULES
from .tags import norm

UA = f"GrooveWizard/{__version__} (+https://github.com/devCidras/groovewizard)"


def check_key(service, key, timeout=15):
    """-> ("ok", detail) | ("invalid", "") | ("offline", error). One small request, nothing is cached."""
    key = (key or "").strip()
    if not key:
        return "invalid", ""
    if service == "discogs":
        req = urllib.request.Request("https://api.discogs.com/oauth/identity",
                                     headers={"User-Agent": UA, "Authorization": f"Discogs token={key}"})
    else:
        q = urllib.parse.urlencode({"method": "artist.getinfo", "artist": "Daft Punk", "api_key": key, "format": "json"})
        req = urllib.request.Request("https://ws.audioscrobbler.com/2.0/?" + q, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):  # Discogs: bad token; Last.fm answers 403 for an invalid key
            return "invalid", ""
        if service == "discogs" or e.code >= 429:
            return "offline", f"HTTP {e.code}"  # busy / server error: we don't know if the key is good
        try:
            data = json.load(e)  # Last.fm explains a bad key in the body
        except Exception:
            return "offline", f"HTTP {e.code}"
    except (OSError, http.client.HTTPException, ValueError) as e:
        return "offline", str(getattr(e, "reason", e))
    if not isinstance(data, dict):
        return "offline", "unexpected response"
    if service == "lastfm" and data.get("error"):
        detail = data.get("message", "")
        return ("invalid", "") if data["error"] in (10, 26) else ("offline", detail if isinstance(detail, str) else "")
    username = data.get("username", "")
    return "ok", username if service == "discogs" and isinstance(username, str) else ""


def folder_for(tag):
    """Online tag -> (folder, priority) or (None, None). 'electronic' is too generic to mean anything."""
    import re
    if not isinstance(tag, str):
        return None, None
    n = tag.lower()
    if "electronic" in n:
        return None, None
    for i, (k, g) in enumerate(ONLINE_RULES):
        pat = r"(?<!\w)" + r"[\s_-]+".join(re.escape(x) for x in k.split()) + r"(?!\w)"
        if re.search(pat, n):
            return g, i
    return None, None


def pick(tag_counts):
    """[(tag, count)] -> (count, priority, folder, tag) of the best mapped tag, or None."""
    best = None
    for row in tag_counts if isinstance(tag_counts, list) else []:
        if not isinstance(row, (list, tuple)) or len(row) != 2:
            continue
        name, cnt = row
        if not isinstance(name, str) or not isinstance(cnt, (int, float)):
            continue
        g, prio = folder_for(name)
        if g and (best is None or (cnt, -prio) > (best[0], -best[1])):
            best = (cnt, prio, g, name)
    return best


class Cached:
    """JSON cache + minimum interval between requests + retry on 429/5xx."""

    def __init__(self, path, interval, cancel=None):
        self.path, self.interval, self.last = path, interval, 0.0
        self.cancel = cancel or threading.Event()
        try:
            with open(path, encoding="utf-8") as fh:
                self.cache = json.load(fh)
        except (OSError, ValueError):  # missing or damaged: start empty
            self.cache = {}
        if not isinstance(self.cache, dict):
            self.cache = {}
        self.disabled = False
        self.problem = ""

    def fetch(self, url, headers):
        if self.disabled:
            return None
        last_error = "offline"
        for wait in (0, 2, 10):
            delay = max(wait, self.interval - (time.time() - self.last))
            if self.cancel.wait(delay):
                return None
            self.last = time.time()
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
                    data = json.load(r)
                if not isinstance(data, dict):
                    self.disabled, self.problem = True, "unexpected JSON"
                    return None
                if data.get("error"):  # Deezer quota / Last.fm bad key, with a 200
                    return None
                return data
            except urllib.error.HTTPError as e:
                last_error = f"HTTP {e.code}"
                if e.code == 404:
                    return {}  # really nothing there
                if e.code not in (408, 429, 500, 502, 503, 504):
                    self.disabled, self.problem = True, last_error
                    return None  # bad key or request: not cached as 'no result', asked again next time
            except (OSError, http.client.HTTPException, ValueError) as e:  # dropped connection, bad data, timeout
                last_error = str(getattr(e, "reason", e)) or type(e).__name__
        self.disabled, self.problem = True, last_error
        return None  # failed: not cached, retried next run

    def save(self):
        """Best effort: a cache that can't be written (disk full) only means asking again next time."""
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.cache, fh, ensure_ascii=False)
            os.replace(tmp, self.path)
        except OSError:
            pass


class Discogs(Cached):
    def __init__(self, data_dir, token, cancel=None):
        super().__init__(os.path.join(data_dir, "cache_discogs.json"), 1.05, cancel)  # 60 req/min with token
        self.h = {"User-Agent": UA, "Authorization": f"Discogs token={token}"}

    def tags(self, artist, title):
        k = f"{artist} | {title}".lower()
        if k in self.cache and not isinstance(self.cache[k], list):
            self.cache.pop(k)
        if k not in self.cache:
            q = urllib.parse.urlencode({"type": "release", "artist": artist, "track": title, "per_page": 10})
            r = self.fetch("https://api.discogs.com/database/search?" + q, self.h)
            if r is None:
                return []
            c = {}
            results = r.get("results", [])
            for rel in results if isinstance(results, list) else []:
                if not isinstance(rel, dict):
                    continue
                styles = rel.get("style", [])
                for s in styles if isinstance(styles, list) else []:
                    if isinstance(s, str):
                        c[s] = c.get(s, 0) + 1
            self.cache[k] = sorted(c.items(), key=lambda kv: -kv[1])
        return [x for x in self.cache[k] if isinstance(x, (list, tuple)) and len(x) == 2
                and isinstance(x[0], str) and isinstance(x[1], (int, float))]


    def cover(self, artist, title):
        """URL of a cover for this track, '' if none: a release named after the track (its single) first, else any
        release it is on. Cached, like the genre search."""
        k = f"cover | {artist} | {title}".lower()
        if k in self.cache and not isinstance(self.cache[k], str):
            self.cache.pop(k)
        if k not in self.cache:
            q = urllib.parse.urlencode({"type": "release", "artist": artist, "track": title, "per_page": 10})
            r = self.fetch("https://api.discogs.com/database/search?" + q, self.h)
            if r is None:
                return None  # failed: not cached, tried again next run
            nt = norm(title)
            # 'Artist - Release': only releases by this artist (a Various Artists compilation cover is not the track's)
            results = r.get("results", [])
            ok = [x for x in results if isinstance(x, dict) and isinstance(x.get("title"), str)
                  and " - " in x.get("title", "")
                  and _same_artist(artist, x["title"].split(" - ", 1)[0])]
            ok.sort(key=lambda x: nt not in norm(x.get("title", "")))  # its own single first (stable)
            self.cache[k] = next((x["cover_image"] for x in ok if isinstance(x.get("cover_image"), str)
                                  and x["cover_image"] and "spacer.gif" not in x["cover_image"]), "")
        return self.cache[k]

    def image(self, url, folder):
        """The image's bytes (kept in `folder`, so tracks of the same release download it once), or None."""
        import hashlib
        import re
        if not re.match(r"^https://[\w.-]+\.(discogs\.com|dzcdn\.net|deezer\.com)/", url or ""):
            return None  # only the services' own image servers
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, hashlib.sha1(url.encode()).hexdigest()[:20])
        from .tags import image_type
        try:
            with open(path, "rb") as fh:
                data = fh.read()
            if image_type(data):  # checked again: a damaged cache file is fetched anew
                return data
        except OSError:
            pass
        if self.cancel.wait(max(0.0, self.interval - (time.time() - self.last))):
            return None
        self.last = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30) as r:
                chunks, total = [], 0
                while True:
                    if self.cancel.is_set():
                        return None
                    chunk = r.read(min(1 << 16, 5 * 1024 * 1024 + 1 - total))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    total += len(chunk)
                    if total > 5 * 1024 * 1024:
                        return None
                data = b"".join(chunks)
        except (OSError, http.client.HTTPException, ValueError):
            return None
        if len(data) > 5 * 1024 * 1024 or not image_type(data):  # only real JPEG/PNG, never huge files
            return None
        tmp = path + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
        return data


def _same_artist(ours, theirs):
    """Same name ('Fisher' = 'FISHER'), or one of the names of a collaboration ('Marten Hørger & James Carter',
    'A, B', 'A feat. B', 'A x B'). Never part of a name: 'Fisher' is not 'Fisher Price'."""
    import re
    joins = r"\s*(?:,|&|\+|\b(?:featuring|feat|ft|vs|x|and|with)\b\.?)\s*"  # whole words only: 'FTampa' stays
    split = lambda s: {norm(x) for x in re.split(joins, s, flags=re.I)}
    a = norm(ours)
    return bool(a) and (a == norm(theirs) or a in split(theirs) or norm(theirs) in split(ours))


def _base_title(t):
    """The song without anything in brackets: 'Losing It (Extended Mix)' -> 'losing it'."""
    import re
    return norm(re.sub(r"[\(\[][^\)\]]*[\)\]]?", " ", t))


class Deezer(Cached):
    """Cover art without a key (good for new electronic releases). 500x500: enough for rekordbox, small in the file."""

    def __init__(self, data_dir, cancel=None):
        super().__init__(os.path.join(data_dir, "cache_deezer.json"), 0.15, cancel)  # limit: 50 requests / 5 s
        self.h = {"User-Agent": UA}

    def cover(self, artist, title):
        """URL of the cover of the release this track is on, '' if no result matches artist and title."""
        k = f"{artist} | {title}".lower()
        if k in self.cache and not isinstance(self.cache[k], str):
            self.cache.pop(k)
        if k not in self.cache:
            base = _base_title(title)  # 'That Acid (X Extended Remix)' is listed as 'That Acid (X Remix)'
            r = self.fetch("https://api.deezer.com/search?" + urllib.parse.urlencode({"q": f"{artist} {base}", "limit": 15}),
                           self.h)
            if r is None:
                return None  # failed: not cached, tried again next run
            words = set(norm(title).split())
            rows = r.get("data", [])
            hits = [x for x in rows if isinstance(x, dict) and isinstance(x.get("artist"), dict)
                    and isinstance(x.get("title"), str)
                    and _same_artist(artist, x["artist"].get("name", ""))
                    and base and _base_title(x["title"]) == base] if isinstance(rows, list) else []
            # same song: the version whose title shares most words with ours (the remix, not the original)
            hit = max(hits, key=lambda x: len(words & set(norm(x.get("title", "")).split())), default=None)
            self.cache[k] = (hit or {}).get("album", {}).get("cover_big", "") or ""
        return self.cache[k]

    image = Discogs.image  # same download + disk cache


class LastFM(Cached):
    def __init__(self, data_dir, key, cancel=None):
        super().__init__(os.path.join(data_dir, "cache_lastfm.json"), 0.25, cancel)
        self.key = key

    def tags(self, artist):
        k = artist.lower()
        if k in self.cache and not isinstance(self.cache[k], list):
            self.cache.pop(k)
        if k not in self.cache:
            q = urllib.parse.urlencode({"method": "artist.gettoptags", "artist": artist, "api_key": self.key,
                                        "format": "json", "autocorrect": 1})
            r = self.fetch("https://ws.audioscrobbler.com/2.0/?" + q, {"User-Agent": UA})
            if r is None:
                return []
            top = r.get("toptags", {})
            rows = top.get("tag", []) if isinstance(top, dict) else []
            out = []
            for tag in rows[:15] if isinstance(rows, list) else []:
                try:
                    if isinstance(tag, dict) and isinstance(tag.get("name"), str):
                        out.append((tag["name"], int(tag.get("count", 0))))
                except (TypeError, ValueError):
                    continue
            self.cache[k] = out
        return [x for x in self.cache[k] if isinstance(x, (list, tuple)) and len(x) == 2]


class MusicBrainz(Cached):
    """No key needed, but 1 request/second: slow for big libraries."""

    def __init__(self, data_dir, cancel=None):
        super().__init__(os.path.join(data_dir, "cache_musicbrainz.json"), 1.1, cancel)
        self.h = {"User-Agent": UA, "Accept": "application/json"}

    def tags(self, artist):
        k = norm(artist)
        if k in self.cache and not isinstance(self.cache[k], list):
            self.cache.pop(k)
        if k not in self.cache:
            r = self.fetch("https://musicbrainz.org/ws/2/artist/?fmt=json&limit=5&query="
                           + urllib.parse.quote(f'artist:"{artist}"'), self.h)
            if r is None:
                return []
            artists = r.get("artists", [])
            hit = next((a for a in artists if isinstance(a, dict) and isinstance(a.get("name"), str)
                        and norm(a["name"]) == k and isinstance(a.get("score", 0), (int, float))
                        and a.get("score", 0) >= 90 and isinstance(a.get("id"), str)), None) if isinstance(artists, list) else None
            out = []
            if hit:
                full = self.fetch(f"https://musicbrainz.org/ws/2/artist/{hit['id']}?fmt=json&inc=genres+tags", self.h)
                if full is None:
                    return []
                seen = {}
                genres, tags = full.get("genres", []), full.get("tags", [])
                rows = (genres if isinstance(genres, list) else []) + (tags if isinstance(tags, list) else [])
                for x in rows:
                    if isinstance(x, dict) and isinstance(x.get("name"), str):
                        count = x.get("count", 0) if isinstance(x.get("count", 0), (int, float)) else 0
                        seen[x["name"]] = max(seen.get(x["name"], 0), count)
                out = sorted(seen.items(), key=lambda kv: -kv[1])
            self.cache[k] = out
        return [x for x in self.cache[k] if isinstance(x, (list, tuple)) and len(x) == 2]


class Lookup:
    """genre(artist, title) -> (folder, source) or (None, None). Discogs per track wins; else best artist tag."""

    def __init__(self, data_dir, discogs_token="", lastfm_key="", musicbrainz=False, cancel=None):
        self.dg = Discogs(data_dir, discogs_token, cancel) if discogs_token else None
        self.lf = LastFM(data_dir, lastfm_key, cancel) if lastfm_key else None
        self.mb = MusicBrainz(data_dir, cancel) if musicbrainz else None

    @property
    def available(self):
        return bool(self.dg or self.lf or self.mb)

    def genre(self, artist, title):
        if self.dg:
            d = pick(self.dg.tags(artist, title))
            if d:
                return d[2], f"Discogs: {d[3]}"
        found = []
        if self.lf:
            found += [(b, "Last.fm") for b in [pick(self.lf.tags(artist))] if b]
        if self.mb:
            found += [(b, "MusicBrainz") for b in [pick(self.mb.tags(artist))] if b]
        if not found:
            return None, None
        (cnt, prio, g, tag), src = max(found, key=lambda x: (x[0][0], -x[0][1]))
        return g, f"{src}: {tag}"

    def save(self):
        for s in (self.dg, self.lf, self.mb):
            if s:
                s.save()

    @property
    def problems(self):
        return [s.problem for s in (self.dg, self.lf, self.mb) if s and s.problem]
