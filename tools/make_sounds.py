"""Synthesise the game's sound effects (no third-party assets needed).

Writes WAV files with the standard library, then converts them to OGG with
ffmpeg (OGG is the format browsers handle best in the pygbag web build).

    python tools/make_sounds.py
"""

import math
import os
import random
import shutil
import struct
import subprocess
import wave

RATE = 22050
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "sounds")


def tone(freq_fn, dur, wave_fn="sine", vol=0.5, attack=0.005, release=0.08):
    n = int(RATE * dur)
    out, phase = [], 0.0
    for i in range(n):
        t = i / RATE
        phase += 2 * math.pi * freq_fn(t / dur) / RATE
        if wave_fn == "sine":
            s = math.sin(phase)
        elif wave_fn == "square":
            s = 1.0 if math.sin(phase) >= 0 else -1.0
            s *= 0.5
        elif wave_fn == "tri":
            s = 2 / math.pi * math.asin(math.sin(phase))
        else:  # noise
            s = random.uniform(-1, 1)
        env = min(1.0, t / attack) if attack else 1.0
        env *= min(1.0, (dur - t) / release) if release else 1.0
        out.append(s * env * vol)
    return out


def concat(*parts):
    out = []
    for p in parts:
        out.extend(p)
    return out


def mixdown(*parts):
    n = max(len(p) for p in parts)
    return [sum(p[i] for p in parts if i < len(p)) for i in range(n)]


def write(name, samples):
    os.makedirs(OUT, exist_ok=True)
    wav_path = os.path.join(OUT, name + ".wav")
    with wave.open(wav_path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, s)) * 30000)) for s in samples))
    if shutil.which("ffmpeg"):
        ogg_path = os.path.join(OUT, name + ".ogg")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", wav_path,
                        "-ac", "2", "-c:a", "vorbis", "-strict", "-2", ogg_path], check=True)
        os.remove(wav_path)


def main():
    random.seed(4)
    write("orb", concat(tone(lambda p: 880 + 440 * p, 0.06, "tri", 0.5, release=0.02),
                        tone(lambda p: 1320 + 300 * p, 0.10, "tri", 0.45)))
    write("powerup", concat(*[tone(lambda p, f=f: f, 0.07, "square", 0.35, release=0.03)
                              for f in (523, 659, 784, 1046)]))
    write("close", mixdown(tone(lambda p: 300 + 900 * p, 0.25, "noise", 0.25, release=0.2),
                           tone(lambda p: 400 + 800 * p, 0.25, "sine", 0.35, release=0.2)))
    write("death", mixdown(tone(lambda p: 440 * (1 - 0.8 * p), 0.7, "square", 0.4, release=0.4),
                           tone(lambda p: 0, 0.5, "noise", 0.3, release=0.45)))
    write("level", concat(tone(lambda p: 392, 0.09, "tri", 0.45, release=0.03),
                          tone(lambda p: 587, 0.16, "tri", 0.45)))
    write("clear", concat(*[tone(lambda p, f=f: f, 0.09, "tri", 0.45, release=0.03)
                            for f in (523, 659, 784)], tone(lambda p: 1046, 0.3, "tri", 0.45, release=0.2)))
    write("shield", mixdown(tone(lambda p: 1200 - 700 * p, 0.35, "sine", 0.45, release=0.25),
                            tone(lambda p: 0, 0.2, "noise", 0.2, release=0.15)))
    write("click", tone(lambda p: 660, 0.05, "tri", 0.35, release=0.03))
    write("surprise", concat(*[tone(lambda p, f=f: f, 0.045, "tri", 0.4, release=0.02)
                               for f in (880, 1175, 1568)]))
    write("heartbeat", concat(tone(lambda p: 62 - 20 * p, 0.12, "sine", 0.9, release=0.09),
                              [0.0] * int(RATE * 0.12),
                              tone(lambda p: 55 - 18 * p, 0.10, "sine", 0.6, release=0.08)))
    write("confused", tone(lambda p: 700 - 400 * p + 120 * math.sin(p * 40), 0.6, "sine", 0.4,
                           release=0.2))
    write("taunt", concat(*[tone(lambda p, f=f: f, 0.04, "square", 0.18, release=0.015)
                            for f in (420, 330, 470)]))
    write("killcam", mixdown(tone(lambda p: 1400 - 1200 * p, 0.5, "sine", 0.3, release=0.15),
                             tone(lambda p: 0, 0.5, "noise", 0.12, release=0.3)))
    write("music_a", music(bpm=104, intense=False))
    write("music_b", music(bpm=132, intense=True))
    print("sounds written to", OUT)


def music(bpm, intense):
    """A 4-bar loop: kick, hats and an A-minor bass line (seamless when looped)."""
    beat = int(RATE * 60 / bpm)
    total = beat * 16
    buf = [0.0] * total

    def add(start, samples):
        for i, s in enumerate(samples):
            j = start + i
            if j < total:
                buf[j] += s

    kick = tone(lambda p: 150 * (1 - p) + 45, 0.16, "sine", 0.75, release=0.1)
    hat = tone(lambda p: 0, 0.03, "noise", 0.12, release=0.025)
    snare = mixdown(tone(lambda p: 0, 0.12, "noise", 0.25, release=0.1),
                    tone(lambda p: 190, 0.1, "sine", 0.2, release=0.08))
    roots = (110.0, 87.31, 130.81, 98.0)          # A2 F2 C3 G2
    for bar, root in enumerate(roots):
        for b in range(4):
            t = (bar * 4 + b) * beat
            add(t, kick)
            add(t + beat // 2, hat)
            if intense:
                add(t + beat // 4, hat)
                add(t + 3 * beat // 4, hat)
                if b in (1, 3):
                    add(t, snare)
            steps = 2 if intense else 1
            for s in range(steps):
                f = root * (2 if (intense and s == 1) else 1)
                note = tone(lambda p, f=f: f, 0.9 * beat / steps / RATE, "tri", 0.32, release=0.04)
                add(t + s * beat // steps, note)
    peak = max(abs(s) for s in buf) or 1.0
    return [s * 0.85 / peak for s in buf]          # normalise: no clipping


if __name__ == "__main__":
    main()
