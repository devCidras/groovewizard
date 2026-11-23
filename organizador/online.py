"""Genre lookup online: Discogs (styles per track), Last.fm and MusicBrainz (tags per artist). Cached in JSON."""
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
        try:
            data = json.load(e)
        except Exception:
            return "offline", f"HTTP {e.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return "offline", str(getattr(e, "reason", e))
    if service == "lastfm" and data.get("error"):
        return ("invalid", "") if data["error"] in (10, 26) else ("offline", data.get("message", ""))
    return "ok", data.get("username", "") if service == "discogs" else ""


def folder_for(tag):
    """Online tag -> (folder, priority) or (None, None). 'electronic' is too generic to mean anything."""
    n = tag.lower()
    if "electronic" in n:
        return None, None
    for i, (k, g) in enumerate(ONLINE_RULES):
        if k in n:
            return g, i
    return None, None


def pick(tag_counts):
    """[(tag, count)] -> (count, priority, folder, tag) of the best mapped tag, or None."""
    best = None
    for name, cnt in tag_counts:
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
        except (FileNotFoundError, json.JSONDecodeError):
            self.cache = {}

    def fetch(self, url, headers):
        for wait in (0, 5, 20, 60):
            delay = max(wait, self.interval - (time.time() - self.last))
            if self.cancel.wait(delay):
                return None
            self.last = time.time()
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
                    return json.load(r)
            except urllib.error.HTTPError as e:
                if e.code not in (429, 500, 502, 503):
                    return {}
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
                pass
        return None  # failed: not cached, retried next run

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.cache, fh, ensure_ascii=False)
        os.replace(tmp, self.path)


class Discogs(Cached):
    def __init__(self, data_dir, token, cancel=None):
        super().__init__(os.path.join(data_dir, "cache_discogs.json"), 1.05, cancel)  # 60 req/min with token
        self.h = {"User-Agent": UA, "Authorization": f"Discogs token={token}"}

    def tags(self, artist, title):
        k = f"{artist} | {title}".lower()
        if k not in self.cache:
            q = urllib.parse.urlencode({"type": "release", "artist": artist, "track": title, "per_page": 10})
            r = self.fetch("https://api.discogs.com/database/search?" + q, self.h)
            if r is None:
                return []
            c = {}
            for rel in r.get("results", []):
                for s in rel.get("style", []):
                    c[s] = c.get(s, 0) + 1
            self.cache[k] = sorted(c.items(), key=lambda kv: -kv[1])
        return self.cache[k]


class LastFM(Cached):
    def __init__(self, data_dir, key, cancel=None):
        super().__init__(os.path.join(data_dir, "cache_lastfm.json"), 0.25, cancel)
        self.key = key

    def tags(self, artist):
        k = artist.lower()
        if k not in self.cache:
            q = urllib.parse.urlencode({"method": "artist.gettoptags", "artist": artist, "api_key": self.key,
                                        "format": "json", "autocorrect": 1})
            r = self.fetch("https://ws.audioscrobbler.com/2.0/?" + q, {"User-Agent": UA})
            if r is None:
                return []
            self.cache[k] = [(t["name"], int(t.get("count", 0))) for t in r.get("toptags", {}).get("tag", [])[:15]]
        return self.cache[k]


class MusicBrainz(Cached):
    """No key needed, but 1 request/second: slow for big libraries."""

    def __init__(self, data_dir, cancel=None):
        super().__init__(os.path.join(data_dir, "cache_musicbrainz.json"), 1.1, cancel)
        self.h = {"User-Agent": UA, "Accept": "application/json"}

    def tags(self, artist):
        k = norm(artist)
        if k not in self.cache:
            r = self.fetch("https://musicbrainz.org/ws/2/artist/?fmt=json&limit=5&query="
                           + urllib.parse.quote(f'artist:"{artist}"'), self.h)
            if r is None:
                return []
            hit = next((a for a in r.get("artists", []) if norm(a["name"]) == k and a.get("score", 0) >= 90), None)
            out = []
            if hit:
                full = self.fetch(f"https://musicbrainz.org/ws/2/artist/{hit['id']}?fmt=json&inc=genres+tags", self.h)
                if full is None:
                    return []
                seen = {}
                for x in full.get("genres", []) + full.get("tags", []):
                    seen[x["name"]] = max(seen.get(x["name"], 0), x.get("count", 0))
                out = sorted(seen.items(), key=lambda kv: -kv[1])
            self.cache[k] = out
        return self.cache[k]


class Lookup:
    """genre(artist, title) -> (folder, source) or (None, None). Discogs per track wins; else best artist tag."""

    def __init__(self, data_dir, discogs_token="", lastfm_key="", musicbrainz=False, cancel=None):
        self.sources = []
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
