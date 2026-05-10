"""generate_music_bed.py — synthesize a free royalty-free ambient music
bed for the video template.

No external network, no copyright concerns. Outputs a 2-minute WAV
(seamlessly loopable) consisting of:
  - sub bass drone at A1 (55 Hz) with slow tremolo
  - sustained minor-chord pad (A2-C3-E3)
  - subtle high-shelf shimmer
  - slow envelope modulation for breathing feel

Style is intentionally tense+spacious — works under news-framing voiceover.

Output: video/public/music_bed.wav (~21 MB at 44.1kHz).

Usage:
  python generate_music_bed.py            # default 120s
  python generate_music_bed.py --seconds 90
  python generate_music_bed.py --key am   # a-minor (default), or em / dm / fm
"""
from __future__ import annotations

import argparse
import math
import struct
import wave
from pathlib import Path

from meta import REPO_ROOT as ROOT
OUT_DEFAULT = ROOT / "video" / "public" / "music_bed.wav"

# Pre-tuned chord tones (Hz) for a few minor keys
CHORDS: dict[str, list[float]] = {
    # name: [bass, root, third, fifth] — using 12-TET frequencies
    "am": [55.0, 110.0, 130.81, 164.81],   # A1, A2, C3, E3
    "em": [41.20, 82.41, 98.0, 123.47],    # E1, E2, G2, B2
    "dm": [73.42, 146.83, 174.61, 220.0],  # D2, D3, F3, A3
    "fm": [43.65, 87.31, 103.83, 130.81],  # F1, F2, Ab2, C3
}

SR = 44100  # sample rate

def synth(seconds: int, key: str = "am") -> list[int]:
    n = int(SR * seconds)
    chord = CHORDS.get(key, CHORDS["am"])
    bass_f, root_f, third_f, fifth_f = chord
    samples: list[int] = [0] * n

    # Pre-compute envelopes
    for i in range(n):
        t = i / SR
        # Slow breathing envelope (period ~12 s)
        env = 0.55 + 0.45 * math.sin(2 * math.pi * t / 12.0)
        # Slow tremolo on bass (period 7 s)
        bass_trem = 0.7 + 0.3 * math.sin(2 * math.pi * t / 7.0)
        # Subtle pitch drift on pad for organic feel
        drift = 1.0 + 0.0009 * math.sin(2 * math.pi * t / 23.0)

        # Sub bass — sine + soft second harmonic for warmth
        bass = (
            0.30 * math.sin(2 * math.pi * bass_f * t)
            + 0.10 * math.sin(2 * math.pi * bass_f * 2 * t)
        ) * bass_trem

        # Pad — three-tone minor chord, gentle saw-style via summed sines
        pad = (
            math.sin(2 * math.pi * root_f * drift * t) * 0.07
            + math.sin(2 * math.pi * third_f * drift * t) * 0.06
            + math.sin(2 * math.pi * fifth_f * drift * t) * 0.05
            # higher harmonics for shimmer
            + math.sin(2 * math.pi * root_f * 4 * t) * 0.015
            + math.sin(2 * math.pi * third_f * 4 * t) * 0.012
        )

        mix = (bass + pad * env) * 0.85
        # Soft clipping to avoid harsh peaks
        if mix > 1.0:
            mix = 1.0 - (1.0 / (1.0 + (mix - 1.0)))
        elif mix < -1.0:
            mix = -1.0 + (1.0 / (1.0 - (mix + 1.0)))

        samples[i] = int(mix * 28000)  # leave headroom

    # Cross-fade first 1s with last 1s for seamless looping
    fade = SR
    for i in range(fade):
        a = i / fade
        # Mix start sample with end sample
        samples[i] = int(samples[i] * a + samples[n - fade + i] * (1 - a))

    return samples


def write_wav(samples: list[int], out_path: Path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)  # 16-bit
        w.setframerate(SR)
        w.writeframes(struct.pack("<" + "h" * len(samples), *samples))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=120,
                    help="Duration in seconds (default: 120, plenty to loop "
                         "across most videos)")
    ap.add_argument("--key", default="am",
                    choices=list(CHORDS),
                    help="Minor key for the chord (default: am)")
    ap.add_argument("--out", type=Path, default=OUT_DEFAULT)
    args = ap.parse_args()

    print(f"[music] generating {args.seconds}s {args.key.upper()}-minor bed...",
          flush=True)
    s = synth(args.seconds, args.key)
    write_wav(s, args.out)
    print(f"[music] wrote {args.out} "
          f"({args.out.stat().st_size / 1e6:.1f} MB, {args.seconds}s)",
          flush=True)


if __name__ == "__main__":
    main()
