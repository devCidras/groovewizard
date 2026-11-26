"""Public RSS headlines and local artist matching. Requests only go to these feed URLs."""
import datetime as dt
import html
import http.client
import os
import re
import tempfile
import time
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
import json
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

from .online import UA
from .pipeline import APP_DIR, _read_json

FEEDS = {"Mixmag": "https://mixmag.net/rss.xml", "DJ Mag": "https://djmag.com/rss.xml",
         "Rádio Oxigénio": "https://www.oxigenio.fm/feed/", "Digital DJ Tips": "https://www.digitaldjtips.com/feed/"}
INTERVAL = 15 * 60
CACHE = os.path.join(APP_DIR, "radar.json")
PORTUGAL = {"portugal", "lisboa", "lisbon", "porto", "braga", "algarve", "coimbra", "portugues",
            "portuguesa", "portuguese", "faro", "madeira", "acores", "aveiro", "guimaraes", "caparica", "leiria",
            "evora", "viseu", "setubal", "braganca", "santarem", "portalegre", "funchal"}
CITY_ALIASES = {"oporto": "porto", "lisbon": "lisboa"}


def words(text):
    plain = unicodedata.normalize("NFKD", text.casefold())
    return " ".join(re.findall(r"[^\W_]+", "".join(c for c in plain if not unicodedata.combining(c))))


def plain_text(text):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text or "")).split())


def in_portugal(text, city=""):
    """Match normalized news text and city names, including English names from international feeds."""
    location = re.sub(r"\bporto alegre\b", " ", text)
    tokens = [CITY_ALIASES.get(word, word) for word in location.split()]
    if city:
        city = CITY_ALIASES.get(city, city)
        return f" {city} " in f" {' '.join(tokens)} "
    return not PORTUGAL.isdisjoint(tokens)


def parse_feed(data, source):
    root = ET.fromstring(data)
    if root.find("channel") is None:
        raise ValueError("RSS")
    articles = []
    for item in root.findall("channel/item")[:100]:
        title = plain_text(item.findtext("title"))
        url = (item.findtext("link") or "").strip()
        parts = urlsplit(url)
        if not title or parts.scheme not in ("http", "https") or not parts.hostname:
            continue
        date = item.findtext("pubDate") or item.findtext("{http://purl.org/dc/elements/1.1/}date") or ""
        try:
            published = parsedate_to_datetime(date)
        except (ValueError, TypeError, OverflowError):
            try:
                published = dt.datetime.fromisoformat(date)
            except ValueError:
                published = None
        timestamp = 0
        if published:
            if published.tzinfo is None:
                published = published.replace(tzinfo=dt.timezone.utc)
            seconds = (published - dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)).total_seconds()
            if 0 < seconds < 4102444800:
                timestamp = int(seconds)
        summary = plain_text(item.findtext("description"))[:1000]
        keywords = " ".join(c.text or "" for c in item.findall("category"))
        text = words(" ".join((title, summary, keywords)))
        tokens = set(text.split())
        groups = []
        if in_portugal(text):
            groups.append("portugal")
        if source == "Digital DJ Tips" or tokens.intersection({
                "firmware", "rekordbox", "serato", "traktor", "cdj", "controller", "controlador", "mixer",
                "headphones", "software", "hardware", "equipment", "tech", "synth", "alphatheta"}):
            groups.append("tech")
        if tokens.intersection({"album", "ep", "remix", "remixes", "set", "sets", "mix", "mixtape", "release",
                                "releases", "single", "lancamento", "lanca", "disco", "tracks", "faixa"}):
            groups.append("music")
        articles.append(dict(title=title, url=url, source=source, date=timestamp, text=text, groups=groups))
    return articles


def fetch_feed(source):
    req = urllib.request.Request(FEEDS[source], headers={"User-Agent": UA, "Accept": "application/rss+xml, application/xml"})
    with urllib.request.urlopen(req, timeout=10) as response:
        data = response.read(5_000_001)
    if len(data) > 5_000_000:
        raise ValueError("RSS size")
    return parse_feed(data, source)


def cached_news():
    cache = _read_json(CACHE, {})
    clean = {}
    for source, batch in cache.items() if isinstance(cache, dict) else ():
        if (source not in FEEDS or not isinstance(batch, dict) or not isinstance(batch.get("updated"), (int, float))
                or not 0 < batch["updated"] < 4102444800 or not isinstance(batch.get("articles"), list)):
            continue
        articles = [a for a in batch["articles"] if isinstance(a, dict) and a.get("source") == source
                    and all(isinstance(a.get(k), str) for k in ("url", "title", "text"))
                    and a["url"].startswith(("https://", "http://")) and isinstance(a.get("groups"), list)
                    and isinstance(a.get("date"), int) and 0 <= a["date"] < 4102444800]
        clean[source] = {"updated": batch["updated"], "articles": articles}
    return clean


def refresh_news():
    cache, failed = cached_news(), []
    with ThreadPoolExecutor(max_workers=len(FEEDS)) as pool:
        futures = {s: pool.submit(fetch_feed, s) for s in FEEDS}
        for source, future in futures.items():
            try:
                articles = future.result()
                if articles:
                    cache[source] = {"updated": time.time(), "articles": articles}
                else:
                    failed.append(source)
            except (OSError, ValueError, ET.ParseError, EOFError, http.client.HTTPException, OverflowError):
                failed.append(source)
    if len(failed) < len(FEEDS):
        os.makedirs(APP_DIR, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", dir=APP_DIR, encoding="utf-8", delete=False) as f:
            tmp = f.name
            try:
                json.dump(cache, f, ensure_ascii=False)
            except BaseException:
                f.close()
                os.unlink(tmp)
                raise
        try:
            os.replace(tmp, CACHE)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    return cache, failed


def artist_index(tracks):
    index = {}
    for track in tracks:
        for credit in track.artists or (track.artist,):
            parts = re.split(r"\s+(?:feat\.?|ft\.?|featuring|b2b|x|vs\.?|&|/)\s+|[;,]", credit, flags=re.I)
            for name in {credit, *parts}:
                key = words(name)
                if key:
                    index.setdefault(key, set()).add(track.path)
    return index


def mentions(text, names, lengths):
    """Look up headline phrases in the local index, independent of the size of the music collection."""
    tokens = text.split()
    return {phrase for length in lengths for i in range(len(tokens) - length + 1)
            if (phrase := " ".join(tokens[i:i + length])) in names}
