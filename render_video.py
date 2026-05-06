"""render_video.py — wrap `npx remotion render` for a video_scripts JSON.

Usage:
  python render_video.py video_scripts/2026-05-06_01_hormuz.json
  python render_video.py video_scripts/2026-05-06_*.json --out videos/

The Remotion template lives in video_template/ and consumes the JSON's
top-level shape as its props payload (matches src/types.ts VideoScriptProps).

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
from pathlib import Path

ROOT = Path(__file__).parent
TEMPLATE = ROOT / "video_template"
DEFAULT_OUT = ROOT / "videos"


def ensure_node_modules() -> None:
    if (TEMPLATE / "node_modules").exists():
        return
    print("[render] node_modules missing — running `npm install`...", flush=True)
    subprocess.check_call(
        ["npm", "install", "--no-audit", "--fund=false", "--progress=false"],
        cwd=TEMPLATE,
    )


def render_one(script_path: Path, out_dir: Path) -> Path:
    """Render one video_scripts/*.json into an MP4."""
    if not script_path.exists():
        raise SystemExit(f"script not found: {script_path}")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{script_path.stem}.mp4"

    # Remotion accepts --props=<json-string-or-path>. Pass an absolute
    # path to the script JSON so the template reads the full object as props.
    props_arg = f"--props={script_path.resolve()}"

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
    subprocess.check_call(cmd, cwd=TEMPLATE)
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
