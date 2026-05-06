"""synthesize_voiceover.py — Piper-based offline TTS for video scripts.

Reads a video_scripts/<id>.json, synthesizes one WAV per scene using
Piper (local ONNX inference, no network, no API key), saves them to
video_template/public/voiceovers/<video_id>/scene_<n>.wav, and writes
a durations.json sidecar so render_video.py can pass per-scene audio
timing into Remotion.

Free (open-source models from rhasspy/piper-voices on Hugging Face).
First run downloads ~63MB voice model to video_template/public/voices/.

Usage:
  python synthesize_voiceover.py video_scripts/2026-05-06_01_hormuz.json
  python synthesize_voiceover.py video_scripts/*.json --voice en_US-amy-medium
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
import wave

ROOT = Path(__file__).parent
TEMPLATE = ROOT / "video_template"
VOICES_DIR = TEMPLATE / "public" / "voices"
VOICEOVERS_DIR = TEMPLATE / "public" / "voiceovers"

# Default voice — alan-medium is a British male broadcaster-style voice,
# noticeably more authoritative than the previous default amy-medium.
# Free, runs locally. Override with --voice to test alternatives.
DEFAULT_VOICE = "en_GB-alan-medium"

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


def synthesize_scene(text: str, voice_model: Path, out_path: Path,
                     length_scale: float = 1.0,
                     sentence_silence: float = 0.25) -> float:
    """Generate one WAV via piper CLI. Returns duration in seconds."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Pipe text via stdin; piper's `-i` flag also works with input files
    proc = subprocess.run(
        [
            "piper", "-m", str(voice_model),
            "-f", str(out_path),
            "--length-scale", str(length_scale),
            "--sentence-silence", str(sentence_silence),
        ],
        input=text.encode("utf-8"),
        check=True,
        capture_output=True,
    )
    if not out_path.exists():
        raise RuntimeError(f"Piper produced no output. stderr: {proc.stderr.decode()[:200]}")
    return wav_duration(out_path)


def process_script(script_path: Path, voice: str = DEFAULT_VOICE,
                   length_scale: float = 1.0) -> dict:
    """Synthesize all scene voiceovers for one video script."""
    script = json.loads(script_path.read_text(encoding="utf-8"))
    video_id = script.get("video_id") or script_path.stem
    out_dir = VOICEOVERS_DIR / video_id
    out_dir.mkdir(parents=True, exist_ok=True)

    voice_model = ensure_voice_model(voice)
    scenes = script.get("scenes") or []
    print(f"[tts] {video_id}: {len(scenes)} scenes -> {out_dir}", flush=True)
    durations = []
    for i, sc in enumerate(scenes):
        text = (sc.get("voiceover") or "").strip()
        scene_no = sc.get("scene", i + 1)
        out_path = out_dir / f"scene_{scene_no:02d}.wav"
        if not text:
            print(f"  scene {scene_no:>2}: (empty voiceover, skipped)", flush=True)
            durations.append({"scene": scene_no, "duration_seconds": 0.0,
                              "audio": None, "text": ""})
            continue
        dur = synthesize_scene(text, voice_model, out_path,
                               length_scale=length_scale)
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
        "voice": voice,
        "length_scale": length_scale,
        "scenes": durations,
        "total_seconds": round(sum(d["duration_seconds"] for d in durations), 2),
    }, indent=2, ensure_ascii=False))
    print(f"[tts] total: {sum(d['duration_seconds'] for d in durations):.1f}s "
          f"-> {durations_path.relative_to(ROOT)}", flush=True)
    return {"video_id": video_id, "out_dir": str(out_dir),
            "durations": durations}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scripts", nargs="+",
                    help="One or more video_scripts/*.json files")
    ap.add_argument("--voice", default=DEFAULT_VOICE,
                    help=f"Piper voice id (default: {DEFAULT_VOICE}). "
                         f"Options: {', '.join(VOICE_HF_PATHS)}")
    ap.add_argument("--length-scale", type=float, default=1.0,
                    help="Speech rate. <1.0 faster, >1.0 slower (default 1.0)")
    args = ap.parse_args()

    if not shutil.which("piper"):
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
        process_script(sp, voice=args.voice, length_scale=args.length_scale)


if __name__ == "__main__":
    main()
