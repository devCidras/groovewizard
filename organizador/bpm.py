"""Tempo for tracks without a genre: tag BPM, else measured from the audio."""
from .regras import BPM_LIMITS, FOLDER_NAMES
from .tags import tag_bpm

SECONDS, HOP, WIN = 90, 256, 1024  # the middle of the track, where the beat is
MIN_BEAT = .15  # measured: 380 tagged club tracks give at least 0.2, an acapella 0.08


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


def _onsets(path):
    """(strength of the new sounds over time, values per second)."""
    import numpy as np  # here: only loaded when a track has to be measured
    import soundfile
    with soundfile.SoundFile(path) as f:
        rate, n = f.samplerate, min(f.frames, SECONDS * f.samplerate)
        f.seek((f.frames - n) // 2)
        # mono block by block: 90 s of a 192 kHz or multichannel file never in memory at once
        y = np.concatenate([b.mean(axis=1) for b in f.blocks(1 << 16, frames=n, dtype="float32", always_2d=True)])
    frames = np.lib.stride_tricks.sliding_window_view(y, WIN)[::HOP]
    window, last, out = np.hanning(WIN).astype("float32"), None, []
    for i in range(0, len(frames), 1024):  # in blocks: never the whole spectrogram in memory
        s = np.log1p(100 * np.abs(np.fft.rfft(frames[i:i + 1024] * window)).astype("float32"))
        if last is not None:
            s = np.vstack([last, s])
        out.append(np.maximum(np.diff(s, axis=0), 0).sum(axis=1))
        last = s[-1:]
    return np.concatenate(out), rate / HOP


def measure(path):
    """BPM to 0.1, or None: no clear beat, or a format that can't be decoded (M4A).

    The right tempo repeats at 1, 2, 4... 64 beats; the long ones give the precision (127 and 128 are 0.2 s apart
    after 64 beats), the beat itself and a light preference for ~127 settle 4/3 confusions (124 heard as 165).
    Checked on 800 tracks with a BPM tag: 96% within 0.6, and several of the others have a wrong tag."""
    try:
        import numpy as np
        o, per_second = _onsets(path)
        o = o - o.mean()
        n = len(o)
        spectrum = np.fft.rfft(o, 2 * n)
        ac = np.fft.irfft(spectrum * np.conj(spectrum))[:n] / np.arange(n, 0, -1)
        if not ac[0] > 0:  # silence (or NaN samples)
            return None
        bpms = np.arange(90, 180, .05)
        score, total = np.zeros(len(bpms)), 0
        for beats, weight in ((1, 2), (2, 1), (4, 1), (8, 1), (16, 1), (32, 1), (64, 1)):
            lag = 60 / bpms * beats * per_second
            if lag[0] < n * .8:
                score += weight * np.interp(lag, np.arange(n), ac / ac[0])
                total += weight
            elif beats <= 8:  # too short (under 7 s) to tell
                return None
        score /= total
        best = int((score * np.exp(-.5 * (np.log2(bpms / 127) / .7) ** 2)).argmax())
        return round(float(bpms[best]), 1) if score[best] >= MIN_BEAT else None
    except Exception:
        return None


def bpm_of(path):
    b = tag_bpm(path)
    return fold(b) if b else measure(path)
