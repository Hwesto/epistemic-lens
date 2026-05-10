"""synthesize_voiceover.py — multi-provider TTS for video scripts.

Three providers, selectable via --provider:

  kokoro      (recommended) — Kokoro 82M local ONNX. Free, offline, no
                              API key, no rate limits. Quality: close
                              to ElevenLabs / Azure Neural. Voices
                              include bm_george (British male broadcaster),
                              bm_lewis, bf_emma, am_adam, etc. Model
                              auto-downloads to public/voices/ on
                              first use (~325 MB).

  piper                    — Piper local ONNX. Free, offline, no API
                              key. Quality: lower than Kokoro; can have
                              audio crackling artefacts. Works as fallback.

  elevenlabs               — ElevenLabs cloud API. Quality: production-
                              grade. Free tier 10K chars/mo (~5-7 videos).
                              Set ELEVENLABS_API_KEY. NOTE: Free tier is
                              blocked from datacenter IPs (incl. most
                              cloud runners) — works from residential IPs
                              only. Use kokoro from CI / GH Actions.

Per scene synthesizes one audio file (WAV for piper, MP3 for elevenlabs)
and writes a durations.json sidecar so render_video.py can sync visual
scenes to actual audio length.

Usage:
  python synthesize_voiceover.py video_scripts/<id>.json
  python synthesize_voiceover.py <id>.json --provider elevenlabs --voice Brian
  python synthesize_voiceover.py <id>.json --provider piper --voice en_GB-alan-medium
"""
from __future__ import annotations

import argparse
import functools
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
import wave

from meta import REPO_ROOT as ROOT
TEMPLATE = ROOT / "video"
VOICES_DIR = TEMPLATE / "public" / "voices"
VOICEOVERS_DIR = TEMPLATE / "public" / "voiceovers"

# Piper default voice — alan-medium is a British male broadcaster-style.
# Free, runs locally. Override with --voice to test alternatives.
DEFAULT_VOICE = "en_GB-alan-medium"

# Kokoro defaults
KOKORO_DEFAULT_VOICE = "bm_george"  # British male broadcaster
KOKORO_VOICES = [
    "af", "af_bella", "af_nicole", "af_sarah", "af_sky",  # American female
    "am_adam", "am_michael",                              # American male
    "bf_emma", "bf_isabella",                             # British female
    "bm_george", "bm_lewis",                              # British male
]
KOKORO_MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/kokoro-v0_19.onnx"
KOKORO_VOICES_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/voices.bin"

# Map voice name -> (locale, voice_id, quality) for download URL construction
VOICE_HF_PATHS: dict[str, str] = {
    "en_US-amy-medium": "en/en_US/amy/medium",
    "en_US-libritts_r-medium": "en/en_US/libritts_r/medium",
    "en_US-ryan-high": "en/en_US/ryan/high",
    "en_GB-alan-medium": "en/en_GB/alan/medium",
    "en_GB-northern_english_male-medium": "en/en_GB/northern_english_male/medium",
}


def ensure_voice_model(voice: str) -> Path:
    """Download voice model + config from HuggingFace if not present."""
    VOICES_DIR.mkdir(parents=True, exist_ok=True)
    onnx_path = VOICES_DIR / f"{voice}.onnx"
    cfg_path = VOICES_DIR / f"{voice}.onnx.json"
    if onnx_path.exists() and cfg_path.exists():
        return onnx_path
    if voice not in VOICE_HF_PATHS:
        raise SystemExit(f"Unknown voice: {voice}. "
                         f"Add HF path to VOICE_HF_PATHS in this script.")
    base = f"https://huggingface.co/rhasspy/piper-voices/resolve/main/{VOICE_HF_PATHS[voice]}"
    for fname in (f"{voice}.onnx", f"{voice}.onnx.json"):
        dest = VOICES_DIR / fname
        if dest.exists():
            continue
        url = f"{base}/{fname}?download=true"
        print(f"[tts] downloading {fname} (~63MB) ...", flush=True)
        urllib.request.urlretrieve(url, dest)
    return onnx_path


def wav_duration(wav_path: Path) -> float:
    with wave.open(str(wav_path), "rb") as w:
        frames = w.getnframes()
        rate = w.getframerate()
        return frames / float(rate) if rate else 0.0


def mp3_duration(mp3_path: Path) -> float:
    """Pure-Python MP3 duration via MPEG layer 3 frame counting.
    Sufficient for ElevenLabs output (CBR at 128 kbps default)."""
    import struct
    with open(mp3_path, "rb") as f:
        data = f.read()
    i = 0
    if data[:3] == b"ID3":
        s = data[6:10]
        sz = ((s[0] & 0x7F) << 21) | ((s[1] & 0x7F) << 14) | ((s[2] & 0x7F) << 7) | (s[3] & 0x7F)
        i = 10 + sz
    bitrates = [None, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320]
    sample_rates = [44100, 48000, 32000]
    total_samples = 0
    sample_rate = 44100
    while i < len(data) - 4:
        if data[i] == 0xFF and (data[i + 1] & 0xE0) == 0xE0:
            b1, b2 = data[i + 1], data[i + 2]
            layer = (b1 >> 1) & 0x3
            if layer != 0x1:
                i += 1
                continue
            br_idx = (b2 >> 4) & 0xF
            sr_idx = (b2 >> 2) & 0x3
            if br_idx in (0, 0xF) or sr_idx == 0x3:
                i += 1
                continue
            bitrate = bitrates[br_idx] if br_idx < len(bitrates) else None
            sample_rate = sample_rates[sr_idx]
            if not bitrate:
                i += 1
                continue
            padding = (b2 >> 1) & 0x1
            frame_len = (144 * bitrate * 1000 // sample_rate) + padding
            if frame_len <= 0:
                i += 1
                continue
            total_samples += 1152
            i += frame_len
        else:
            i += 1
    return total_samples / sample_rate if sample_rate else 0.0


def audio_duration(path: Path) -> float:
    """Duration in seconds. Dispatches by extension."""
    if path.suffix.lower() == ".mp3":
        return mp3_duration(path)
    return wav_duration(path)


def synthesize_scene(text: str, voice_model: Path, out_path: Path,
                     length_scale: float = 1.0,
                     sentence_silence: float = 0.25,
                     noise_scale: float = 0.4,
                     noise_w_scale: float = 0.5) -> float:
    """Piper synthesis. Returns duration in seconds.

    Lower noise scales (default 0.4 / 0.5 vs Piper defaults 0.667 / 0.8)
    reduce stochastic crackling artefacts at the cost of slightly
    flatter prosody. Better tradeoff for news-narration use.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            "piper", "-m", str(voice_model),
            "-f", str(out_path),
            "--length-scale", str(length_scale),
            "--sentence-silence", str(sentence_silence),
            "--noise-scale", str(noise_scale),
            "--noise-w-scale", str(noise_w_scale),
        ],
        input=text.encode("utf-8"),
        check=True,
        capture_output=True,
    )
    if not out_path.exists():
        raise RuntimeError(f"Piper produced no output. stderr: {proc.stderr.decode()[:200]}")
    return wav_duration(out_path)


# ---------------------------------------------------------------------------
# Kokoro provider — local ONNX, broadcast quality, no API key, no IP issues
# ---------------------------------------------------------------------------

def ensure_kokoro_model():
    """Download Kokoro model + voices file to public/voices/ if missing."""
    VOICES_DIR.mkdir(parents=True, exist_ok=True)
    onnx_path = VOICES_DIR / "kokoro-v0_19.onnx"
    voices_path = VOICES_DIR / "voices.bin"
    for url, dest in [(KOKORO_MODEL_URL, onnx_path), (KOKORO_VOICES_URL, voices_path)]:
        if not dest.exists():
            print(f"[tts] downloading {dest.name} ...", flush=True)
            urllib.request.urlretrieve(url, dest)
    return onnx_path, voices_path


@functools.lru_cache(maxsize=1)
def _get_kokoro():
    """Load Kokoro once per process. Cached so repeated synthesize_scene_kokoro
    calls within a single render reuse the same loaded model."""
    from kokoro_onnx import Kokoro
    onnx_path, voices_path = ensure_kokoro_model()
    return Kokoro(str(onnx_path), str(voices_path))


def synthesize_scene_kokoro(text: str, voice: str, out_path: Path,
                            speed: float = 1.0) -> float:
    """Synthesize via Kokoro ONNX. Saves WAV. Returns duration in seconds."""
    import soundfile as sf
    out_path.parent.mkdir(parents=True, exist_ok=True)
    k = _get_kokoro()
    # British voices use en-gb phonemizer; American voices en-us
    lang = "en-gb" if voice.startswith("b") else "en-us"
    samples, sr = k.create(text, voice=voice, speed=speed, lang=lang)
    sf.write(str(out_path), samples, sr)
    return len(samples) / sr if sr else 0.0


# ---------------------------------------------------------------------------
# ElevenLabs provider
# ---------------------------------------------------------------------------
# Curated list of broadcaster-friendly voices on the ElevenLabs free tier.
# Voice IDs are stable across users (these are the public default voices).
ELEVENLABS_VOICES: dict[str, str] = {
    "Brian":    "nPczCjzI2devNBz1zQrb",  # deep, authoritative, default
    "Adam":     "pNInz6obpgDQGcFmaJgB",  # broadcaster-male
    "Bill":     "pqHfZKP75CvOlQylNhV4",  # older male, gravitas
    "Antoni":   "ErXwobaYiN019PkySvjV",  # warm narrator
    "Charlie":  "IKne3meq5aSn9XLyUdCD",  # measured Australian
    "Daniel":   "onwK4e9ZLuTAKqWW03F9",  # British news-anchor
    "Sam":      "yoZ06aMxZJJ28mfd3POQ",  # raspy reporter
    "George":   "JBFqnCBsd6RMkjVDRZzb",  # warm British male
}
ELEVENLABS_DEFAULT_VOICE = "Brian"
ELEVENLABS_DEFAULT_MODEL = "eleven_multilingual_v2"


def synthesize_scene_elevenlabs(text: str, voice_name: str, out_path: Path,
                                stability: float = 0.55,
                                similarity_boost: float = 0.75,
                                style: float = 0.0) -> float:
    """Synthesize via ElevenLabs API. Saves MP3. Returns duration in seconds.

    Requires ELEVENLABS_API_KEY env var. Uses ~ (text length) characters of
    free-tier quota per call (~10K chars/month on free).
    """
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise SystemExit(
            "ELEVENLABS_API_KEY env var not set. "
            "Get a free API key at https://elevenlabs.io/app/settings/api-keys"
        )
    voice_id = ELEVENLABS_VOICES.get(voice_name, voice_name)  # accept raw IDs too

    from elevenlabs.client import ElevenLabs

    out_path.parent.mkdir(parents=True, exist_ok=True)
    client = ElevenLabs(api_key=api_key)
    audio_iter = client.text_to_speech.convert(
        voice_id=voice_id,
        text=text,
        model_id=ELEVENLABS_DEFAULT_MODEL,
        output_format="mp3_44100_128",
        voice_settings={
            "stability": stability,
            "similarity_boost": similarity_boost,
            "style": style,
        },
    )
    with open(out_path, "wb") as f:
        for chunk in audio_iter:
            if chunk:
                f.write(chunk)
    return mp3_duration(out_path)


def process_script(script_path: Path, voice: str = DEFAULT_VOICE,
                   length_scale: float = 1.0,
                   provider: str = "piper") -> dict:
    """Synthesize all scene voiceovers for one video script."""
    script = json.loads(script_path.read_text(encoding="utf-8"))
    video_id = script.get("video_id") or script_path.stem
    out_dir = VOICEOVERS_DIR / video_id
    out_dir.mkdir(parents=True, exist_ok=True)

    # Provider-specific setup
    voice_model = None
    audio_ext = ".wav"
    if provider == "piper":
        voice_model = ensure_voice_model(voice)
    elif provider == "kokoro":
        ensure_kokoro_model()
    elif provider == "elevenlabs":
        audio_ext = ".mp3"
    else:
        raise SystemExit(f"Unknown provider: {provider}. Choose 'kokoro', 'piper', or 'elevenlabs'.")

    scenes = script.get("scenes") or []
    print(f"[tts] {video_id} via {provider}/{voice}: "
          f"{len(scenes)} scenes -> {out_dir}", flush=True)
    durations = []
    total_chars = 0
    for i, sc in enumerate(scenes):
        text = (sc.get("voiceover") or "").strip()
        scene_no = sc.get("scene", i + 1)
        out_path = out_dir / f"scene_{scene_no:02d}{audio_ext}"
        if not text:
            print(f"  scene {scene_no:>2}: (empty voiceover, skipped)", flush=True)
            durations.append({"scene": scene_no, "duration_seconds": 0.0,
                              "audio": None, "text": ""})
            continue
        # Per-scene speech_rate override: <1.0 = slower (paradox climax),
        # >1.0 = faster (setup); default 1.0 = normal.
        scene_rate = float(sc.get("speech_rate") or 1.0)
        if provider == "piper":
            dur = synthesize_scene(text, voice_model, out_path,
                                   length_scale=length_scale / scene_rate)
        elif provider == "kokoro":
            dur = synthesize_scene_kokoro(text, voice, out_path,
                                          speed=scene_rate / max(0.01, length_scale))
        else:  # elevenlabs
            dur = synthesize_scene_elevenlabs(text, voice, out_path)

        total_chars += len(text)
        rel = out_path.relative_to(TEMPLATE / "public").as_posix()
        durations.append({
            "scene": scene_no,
            "duration_seconds": round(dur, 2),
            "audio": rel,
            "text": text,
        })
        print(f"  scene {scene_no:>2}: {dur:>5.2f}s  {len(text):>4}c  -> {out_path.name}",
              flush=True)

    durations_path = out_dir / "durations.json"
    durations_path.write_text(json.dumps({
        "video_id": video_id,
        "provider": provider,
        "voice": voice,
        "length_scale": length_scale,
        "total_chars": total_chars,
        "scenes": durations,
        "total_seconds": round(sum(d["duration_seconds"] for d in durations), 2),
    }, indent=2, ensure_ascii=False))
    print(f"[tts] total: {sum(d['duration_seconds'] for d in durations):.1f}s, "
          f"{total_chars} chars -> {durations_path.relative_to(ROOT)}", flush=True)
    return {"video_id": video_id, "out_dir": str(out_dir),
            "durations": durations}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scripts", nargs="+",
                    help="One or more video_scripts/*.json files")
    ap.add_argument("--provider", default="kokoro",
                    choices=["kokoro", "piper", "elevenlabs"],
                    help="TTS provider. kokoro = free local high-quality "
                         "(default, recommended); piper = free local lower "
                         "quality; elevenlabs = cloud API "
                         "(set ELEVENLABS_API_KEY).")
    ap.add_argument("--voice", default=None,
                    help=f"Voice id. kokoro: {', '.join(KOKORO_VOICES)}. "
                         "piper: en_GB-alan-medium etc. "
                         "elevenlabs: Brian/Adam/Bill/Daniel etc. "
                         "Defaults: bm_george (kokoro) / alan-medium (piper) "
                         "/ Brian (elevenlabs).")
    ap.add_argument("--length-scale", type=float, default=1.0,
                    help="Piper speech rate (<1.0 faster). Ignored for elevenlabs.")
    args = ap.parse_args()

    # Default voice depends on provider
    if args.voice is None:
        args.voice = {
            "kokoro": KOKORO_DEFAULT_VOICE,
            "piper": DEFAULT_VOICE,
            "elevenlabs": ELEVENLABS_DEFAULT_VOICE,
        }[args.provider]

    if args.provider == "piper" and not shutil.which("piper"):
        sys.exit("piper not in PATH. Run: pip install piper-tts")

    paths = []
    for p in args.scripts:
        path = Path(p)
        if path.is_file():
            paths.append(path)
        elif "*" in p:
            from glob import glob
            for m in glob(p):
                paths.append(Path(m))
    if not paths:
        sys.exit("No script files found")

    for sp in paths:
        process_script(sp, voice=args.voice,
                       length_scale=args.length_scale,
                       provider=args.provider)


if __name__ == "__main__":
    main()
