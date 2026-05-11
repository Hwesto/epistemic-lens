"""render_video.py — wrap `npx remotion render` for a video_scripts JSON.

Usage:
  python render_video.py video_scripts/2026-05-06_01_hormuz.json
  python render_video.py video_scripts/2026-05-06_*.json --out videos/

The Remotion template lives in video/ and consumes the JSON's top-level
shape as its props payload (matches video/src/types.ts VideoScriptProps).

Environment:
  Requires Node.js 18+, npm. Will run `npm install` once if node_modules
  is missing. Remotion fetches its own headless Chromium on first render
  (~250 MB; cached thereafter).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import meta
from meta import REPO_ROOT as ROOT
TEMPLATE = ROOT / "video"
DEFAULT_OUT = ROOT / "videos"


def ensure_node_modules() -> None:
    if (TEMPLATE / "node_modules").exists():
        return
    print("[render] node_modules missing — running `npm install`...", flush=True)
    subprocess.check_call(
        ["npm", "install", "--no-audit", "--fund=false", "--progress=false"],
        cwd=TEMPLATE,
    )


def merge_voiceover(script: dict) -> dict:
    """If a synthesize_voiceover.py output exists for this script, merge
    per-scene `audio` paths and `duration_seconds` into the script so
    Remotion's <Audio> + Sequence durations match the actual narration."""
    video_id = script.get("video_id") or ""
    if not video_id:
        return script
    durations_path = TEMPLATE / "public" / "voiceovers" / video_id / "durations.json"
    if not durations_path.exists():
        return script
    durations = json.loads(durations_path.read_text(encoding="utf-8"))
    by_scene = {d["scene"]: d for d in durations.get("scenes", [])}
    for sc in script.get("scenes", []):
        d = by_scene.get(sc.get("scene"))
        if not d:
            continue
        if d.get("audio"):
            sc["audio"] = d["audio"]
        if d.get("duration_seconds"):
            sc["duration_seconds"] = d["duration_seconds"]
    print(f"[render]   merged voiceover: {len(by_scene)} scenes, "
          f"{durations.get('total_seconds', 0)}s total", flush=True)
    return script


def render_one(script_path: Path, out_dir: Path) -> Path:
    """Render one video_scripts/*.json into an MP4."""
    if not script_path.exists():
        raise SystemExit(f"script not found: {script_path}")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{script_path.stem}.mp4"

    script = json.loads(script_path.read_text(encoding="utf-8"))
    # Schema-validate before any side effects. Gap 17-1: video scripts
    # used to be unschema'd; a field rename silently broke the render.
    meta.validate_schema(script, "video_script")
    script = merge_voiceover(script)

    # Stage 17 (Gap 17-4): tmp props via tempfile.NamedTemporaryFile so
    # concurrent renders of the same stem can't collide and a crashed
    # render can't leak a `.tmp_props_*.json` into video/public/.
    public_dir = TEMPLATE / "public"
    public_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=public_dir, prefix=".tmp_props_",
        suffix=".json", delete=False, encoding="utf-8",
    ) as f:
        json.dump(script, f, ensure_ascii=False)
        tmp_props = Path(f.name)
    props_arg = f"--props={tmp_props.resolve()}"

    cmd = [
        "npx", "--yes", "remotion", "render",
        "src/index.ts",
        "FramingVideo",
        str(out_path.resolve()),
        props_arg,
        "--codec=h264",
        "--quality=80",
    ]
    print(f"[render] {script_path.name} -> {out_path}", flush=True)
    print(f"        {' '.join(cmd)}", flush=True)
    try:
        subprocess.check_call(cmd, cwd=TEMPLATE)
    finally:
        try:
            tmp_props.unlink()
        except FileNotFoundError:
            pass
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scripts", nargs="+",
                    help="One or more video_scripts/*.json files")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help=f"Output directory (default: {DEFAULT_OUT})")
    ap.add_argument("--skip-install", action="store_true",
                    help="Don't run npm install even if node_modules missing")
    args = ap.parse_args()

    if not shutil.which("node"):
        sys.exit("Node.js not found in PATH — install Node 18+ first")
    if not args.skip_install:
        ensure_node_modules()

    # Resolve glob-like patterns
    paths: list[Path] = []
    for p in args.scripts:
        path = Path(p)
        if path.is_file():
            paths.append(path)
        elif "*" in p or "?" in p:
            from glob import glob
            for m in glob(p):
                if Path(m).is_file():
                    paths.append(Path(m))
        else:
            paths.append(path)

    if not paths:
        sys.exit("No script files matched")

    rendered = []
    for sp in paths:
        try:
            rendered.append(render_one(sp, args.out))
        except subprocess.CalledProcessError as e:
            print(f"[render] FAILED on {sp}: exit {e.returncode}", flush=True)

    print(f"\n[render] Done. {len(rendered)}/{len(paths)} videos rendered to {args.out}/")
    for v in rendered:
        sz = v.stat().st_size if v.exists() else 0
        print(f"  - {v.name}  ({sz/1e6:.2f} MB)")


if __name__ == "__main__":
    main()
