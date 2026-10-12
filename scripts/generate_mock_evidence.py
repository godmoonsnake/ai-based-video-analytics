#!/usr/bin/env python3
"""Generate synthetic evidence payloads for the DARSON mock scenario.

The mock event source fabricates evidence URLs of the form
    /mock-evidence/<camera>/<track>/snapshot.jpg | clip.mp4
(see backend/app/normalize/normalizer.py). Nothing served them, so the demo
evidence gallery showed intentional "no payload" states. This script renders
clearly-labeled SYNTHETIC camera frames (and short clips) for the demo
scenario's four tracks so the gallery, timeline and lightbox have real media.

The frames are stylised CCTV renders (noise, vignette, timestamp burn-in,
Frigate-style detection box) and are stamped "SYNTHETIC EVIDENCE" — they are
placeholders for the demo, not representations of real events.

Output: deploy/mock-evidence/<camera>/<track>/{snapshot.jpg,clip.mp4}
Serve:  docker-compose mounts the folder into the frontend nginx container.

Usage:  python scripts/generate_mock_evidence.py
Deps:   pip install pillow imageio imageio-ffmpeg
"""
from __future__ import annotations

import json
import math
import random
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter
import numpy as np
import imageio.v3 as iio

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "deploy" / "mock-evidence"

W, H = 640, 360
FPS = 12
CLIP_FRAMES = 30

# Demo scenario: camera -> (track, default event ts, person x-range walk)
SCENARIO = {
    "gate_3": {"track": "A1", "ts": 1790681903.74, "x0": 0.30, "x1": 0.52, "label": "GATE 3 / ENTRY"},
    "corridor_1": {"track": "B7", "ts": 1790681915.74, "x0": 0.28, "x1": 0.62, "label": "CORRIDOR 1 / TRANSIT"},
    "restricted_2": {"track": "C3", "ts": 1790681932.74, "x0": 0.36, "x1": 0.42, "label": "RESTRICTED 2"},
    "exit_4": {"track": "D9", "ts": 1790682033.74, "x0": 0.55, "x1": 0.86, "label": "EXIT 4 / EXIT"},
}

FONT_HINTS = ("consola.ttf", "arial.ttf")


def load_font(size: int):
    from PIL import ImageFont

    for name in FONT_HINTS:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def try_live_timestamps() -> dict[str, float]:
    """Best effort: pull the real demo timestamps from the running stack."""
    try:
        with urllib.request.urlopen(
            "http://localhost:8080/api/v1/incidents/1", timeout=3
        ) as r:
            d = json.loads(r.read())
        out = {}
        for e in d.get("events", []):
            cam, ts = e.get("camera_id"), e.get("ts")
            if cam in SCENARIO and ts:
                out[cam] = float(ts)
        if out:
            print(f"[i] using live timestamps from running stack: {out}")
        return out
    except Exception:
        return {}


def backdrop(rng: random.Random) -> Image.Image:
    """Stylised indoor CCTV scene: wall, floor perspective grid, glow, noise."""
    img = Image.new("RGB", (W, H))
    px = img.load()
    for y in range(H):
        t = y / H
        r = int(26 + 14 * t)
        g = int(30 + 16 * t)
        b = int(38 + 20 * t)
        for x in range(W):
            px[x, y] = (r, g, b)
    d = ImageDraw.Draw(img)

    # wall/floor horizon
    horizon = int(H * 0.62)
    d.rectangle([0, 0, W, horizon], fill=(30, 34, 44))
    d.line([0, horizon, W, horizon], fill=(52, 60, 76), width=2)

    # perspective floor grid
    for i in range(-6, 16):
        x_top = W // 2 + i * 60
        d.line([W // 2, horizon, x_top, H], fill=(40, 47, 60), width=1)
    for i in range(1, 7):
        y = horizon + int((H - horizon) * (i / 7) ** 1.7)
        d.line([0, y, W, y], fill=(40, 47, 60), width=1)

    # wall details: door frames / panels
    d.rectangle([W - 150, horizon - 150, W - 40, horizon], outline=(58, 66, 84), width=2)
    d.rectangle([36, horizon - 120, 130, horizon], outline=(58, 66, 84), width=2)

    # overhead light pools
    for cx in (W // 4, W // 2 + W // 6):
        glow = Image.new("L", (W, H), 0)
        gd = ImageDraw.Draw(glow)
        gd.ellipse([cx - 130, horizon - 190, cx + 130, horizon - 30], fill=26)
        glow = glow.filter(ImageFilter.GaussianBlur(38))
        img = Image.composite(
            Image.new("RGB", (W, H), (74, 82, 98)), img, glow
        )

    # sensor noise
    noise = Image.effect_noise((W, H), 14).convert("L")
    img = Image.blend(img, Image.merge("RGB", (noise, noise, noise)), 0.06)

    # vignette
    vig = Image.new("L", (W, H), 0)
    vd = ImageDraw.Draw(vig)
    vd.ellipse([-W * 0.25, -H * 0.45, W * 1.25, H * 1.45], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(60))
    black = Image.new("RGB", (W, H), (2, 3, 5))
    img = Image.composite(img, black, vig)
    return img


def draw_person(img: Image.Image, cx: float, scale: float, phase: float) -> None:
    """Simple walking figure + Frigate-style detection box."""
    d = ImageDraw.Draw(img)
    base_y = int(H * 0.86)
    h = int(H * 0.42 * scale)
    x = int(cx * W)
    swing = math.sin(phase) * h * 0.08

    head_r = int(h * 0.09)
    head = (x, base_y - h + head_r * 2)
    body_top = (x, base_y - h + head_r * 3.2)
    body_bot = (x, base_y - h * 0.32)

    # legs
    d.line([x, body_bot[1], x - h * 0.10 - swing, base_y], fill=(16, 18, 24), width=int(h * 0.055))
    d.line([x, body_bot[1], x + h * 0.10 + swing, base_y], fill=(16, 18, 24), width=int(h * 0.055))
    # body
    d.line([body_top, body_bot], fill=(18, 20, 27), width=int(h * 0.16))
    # arms
    d.line(
        [body_top, body_top[0] + h * 0.12 + swing, body_top[1] + h * 0.26],
        fill=(18, 20, 27),
        width=int(h * 0.045),
    )
    d.line(
        [body_top, body_top[0] - h * 0.12 - swing, body_top[1] + h * 0.26],
        fill=(18, 20, 27),
        width=int(h * 0.045),
    )
    # head
    d.ellipse(
        [head[0] - head_r, head[1] - head_r, head[0] + head_r, head[1] + head_r],
        fill=(22, 24, 31),
    )
    # detection box (Frigate-style)
    bx0, by0 = x - h * 0.26, base_y - h - 4
    bx1, by1 = x + h * 0.26, base_y + 2
    d.rectangle([bx0, by0, bx1, by1], outline=(255, 92, 92), width=2)
    tag = "person 94%"
    f = load_font(11)
    tw = d.textlength(tag, font=f)
    d.rectangle([bx0, by0 - 15, bx0 + tw + 8, by0 - 2], fill=(255, 92, 92))
    d.text((bx0 + 4, by0 - 14), tag, fill=(10, 10, 12), font=f)


def annotate(img: Image.Image, cam: str, label: str, ts: float, track: str) -> Image.Image:
    d = ImageDraw.Draw(img, "RGBA")
    f_big = load_font(16)
    f_small = load_font(11)
    stamp = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # top-left camera id + label
    d.rectangle([0, 0, W, 22], fill=(4, 6, 10, 170))
    d.text((8, 4), f"{cam}  ·  {label}", fill=(160, 235, 200), font=f_small)
    # top-right track
    tw = d.textlength(f"TRACK {track}", font=f_small)
    d.text((W - tw - 8, 4), f"TRACK {track}", fill=(140, 160, 190), font=f_small)
    # bottom timestamp
    d.rectangle([0, H - 22, W, H], fill=(4, 6, 10, 170))
    d.text((8, H - 18), stamp, fill=(220, 228, 240), font=f_small)
    # watermark
    wm = "SYNTHETIC EVIDENCE · DARSON DEMO"
    wtw = d.textlength(wm, font=f_big)
    d.text(((W - wtw) / 2, H - 44), wm, fill=(255, 179, 61, 210), font=f_big)
    # corner brackets
    m, ln = 10, 16
    for (sx, sy, dx, dy) in ((m, m, 1, 1), (W - m, m, -1, 1), (m, H - m, 1, -1), (W - m, H - m, -1, -1)):
        d.line([sx, sy, sx + ln * dx, sy], fill=(120, 200, 240, 200), width=2)
        d.line([sx, sy, sx, sy + ln * dy], fill=(120, 200, 240, 200), width=2)
    return img


def render_frame(cam: str, cfg: dict, ts: float, progress: float, rng: random.Random) -> Image.Image:
    img = backdrop(rng)
    cx = cfg["x0"] + (cfg["x1"] - cfg["x0"]) * progress
    scale = 1.0 + 0.12 * math.sin(progress * math.pi)  # nearer mid-frame
    draw_person(img, cx, scale, phase=progress * math.tau)
    return annotate(img, cam, cfg["label"], ts, cfg["track"])


def main() -> None:
    live = try_live_timestamps()
    rng = random.Random(1790681903)  # deterministic

    for cam, cfg in SCENARIO.items():
        ts = live.get(cam, cfg["ts"])
        out_dir = OUT / cam / cfg["track"]
        out_dir.mkdir(parents=True, exist_ok=True)

        snap = render_frame(cam, cfg, ts, progress=0.55, rng=rng)
        snap.save(out_dir / "snapshot.jpg", quality=88)

        frames = [
            np.asarray(render_frame(cam, cfg, ts + i / FPS, progress=i / (CLIP_FRAMES - 1), rng=rng))
            for i in range(CLIP_FRAMES)
        ]
        iio.imwrite(
            out_dir / "clip.mp4",
            frames,
            fps=FPS,
            codec="libx264",
            macro_block_size=8,  # 640x360 divides cleanly by 8
        )
        print(f"[✓] {out_dir.relative_to(ROOT)}  (snapshot + {CLIP_FRAMES}-frame clip)")

    print("[✓] done.")


if __name__ == "__main__":
    main()
