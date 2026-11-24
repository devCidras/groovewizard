"""Tempo for tracks without a genre: tag BPM, else measured from the audio (needs the optional librosa)."""
from .regras import BPM_LIMITS, FOLDER_NAMES
from .tags import tag_bpm

try:
    import librosa  # optional: pip install librosa
except Exception:  # not installed, or broken native deps
    librosa = None


def fold(bpm):
    """Beat trackers return half/double tempo; club music sits between 90 and 180."""
    import math
    if not bpm or not math.isfinite(bpm) or bpm <= 0:
        return None  # unknown (NaN / infinite / negative would loop or fail)
    while bpm and bpm < 90:
        bpm *= 2
    while bpm and bpm > 180:
        bpm /= 2
    return bpm


def bucket(bpm, names=FOLDER_NAMES["pt"]):
    import math
    if not bpm or not math.isfinite(bpm):
        return names["bpm_unknown"]
    return names["bpm"][next(i for i, top in enumerate(BPM_LIMITS) if bpm < top)]


def measure(path):
    if librosa is None:
        return None
    try:
        dur = librosa.get_duration(path=path)
        y, sr = librosa.load(path, sr=22050, mono=True, offset=max(0, dur / 2 - 30), duration=60)
        # beat_track crashes (access violation) on Python 3.14; autocorrelation tempo does not use that code
        onset = librosa.onset.onset_strength(y=y, sr=sr, hop_length=256)
        return fold(float(librosa.feature.tempo(onset_envelope=onset, sr=sr, hop_length=256, start_bpm=125)[0]))
    except Exception:
        return None


def bpm_of(path):
    b = tag_bpm(path)
    return fold(b) if b else measure(path)
