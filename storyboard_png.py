"""The storyboard image: one sheet with a card per scene, made from the template only.

Made with DeepInfra image generation when DEEPINFRA_API_KEY is set. If that call fails, or there is no key,
the sheet is drawn with Pillow instead. Neither route uses frames or words from the analysed video.

DeepInfra: POST {DEEPINFRA_BASE_URL}/images/generations (OpenAI-compatible), model DEEPINFRA_IMAGE_MODEL.
The exact response format is checked on the first live call; an unexpected reply falls back to Pillow.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

import deepinfra as di

IMAGE_MODEL = os.environ.get("DEEPINFRA_IMAGE_MODEL", "black-forest-labs/FLUX-1-schnell")
IMAGE_SIZE = (1024, 576)
ROLE_COLOURS = {"hook": (246, 198, 0), "body": (42, 50, 61), "cta": (15, 110, 92)}


def image_prompt(template: dict) -> str:
    st, tl = template["style"], template["timeline"]
    dur = st.get("duration_s") or sum(t["duration_s"] for t in tl)
    cards = "; ".join(f"panel {t['scene']} {t['role']} {t['duration_s']:.0f} seconds" for t in tl)
    return ("Clean storyboard sheet, flat vector style, white background, a grid of simple empty 16:9 frames "
            f"with thin borders, {len(tl)} panels for a {dur:.0f} second video. Each panel has a small number label. "
            f"Panels in order: {cards}. No people, no logos, no text other than numbers.")


def generate(prompt: str, key: str) -> bytes:
    body = json.dumps({"model": IMAGE_MODEL, "prompt": prompt, "n": 1,
                       "size": f"{IMAGE_SIZE[0]}x{IMAGE_SIZE[1]}", "response_format": "b64_json"}).encode()
    req = urllib.request.Request(f"{di.BASE_URL}/images/generations", data=body, method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise di.DeepInfraError(f"DeepInfra image HTTP {e.code}: {e.read(200).decode('utf-8', 'replace')}") from None
    except (urllib.error.URLError, TimeoutError) as e:
        raise di.DeepInfraError(f"DeepInfra image unreachable: {getattr(e, 'reason', e)}") from None
    try:
        return base64.b64decode(data["data"][0]["b64_json"])
    except (KeyError, IndexError, TypeError, ValueError):
        raise di.DeepInfraError("DeepInfra image reply had no b64_json image") from None


def draw_pillow(template: dict, path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    tl = template["timeline"]
    cols = 3 if len(tl) > 4 else max(1, len(tl))
    rows = -(-len(tl) // cols)
    card_w, card_h, pad = 360, 300, 24
    head = 70
    W = cols * card_w + (cols + 1) * pad
    H = head + rows * card_h + (rows + 1) * pad
    img = Image.new("RGB", (W, H), (247, 246, 242))
    d = ImageDraw.Draw(img)
    try:
        title_font, small = ImageFont.load_default(size=26), ImageFont.load_default(size=16)
    except TypeError:  # old Pillow without sized default font
        title_font = small = ImageFont.load_default()
    d.text((pad, 20), f"Storyboard · {len(tl)} scenes", fill=(29, 29, 27), font=title_font)
    for n, t in enumerate(tl):
        r, c = divmod(n, cols)
        x = pad + c * (card_w + pad)
        y = head + pad + r * (card_h + pad)
        colour = ROLE_COLOURS.get(t["role"], (42, 50, 61))
        d.rectangle([x, y, x + card_w, y + card_h], fill=(255, 255, 255), outline=(200, 200, 196), width=2)
        frame = [x + 16, y + 16, x + card_w - 16, y + 16 + int((card_w - 32) * 9 / 16)]
        d.rectangle(frame, fill=colour)
        d.text((frame[0] + 10, frame[1] + 8), f"{t['scene']}", fill=(255, 255, 255), font=title_font)
        ty = frame[3] + 14
        d.text((x + 16, ty), f"{t['role'].upper()} · {t['duration_s']:.0f} s", fill=(29, 29, 27), font=small)
        d.text((x + 16, ty + 24), f"{t['start_s']:.1f} s to {t['start_s'] + t['duration_s']:.1f} s", fill=(95, 99, 104), font=small)
        d.text((x + 16, ty + 48), f"about {t['target_words']} words", fill=(95, 99, 104), font=small)
    img.save(path, "PNG")


def draw(template: dict, path: Path, key: str | None = None, log=None) -> dict:
    """Writes the storyboard PNG. Returns how it was made, and the prompt if the model was used."""
    path = Path(path)
    key = key if key is not None else di.api_key()
    prompt = image_prompt(template)
    if key:
        try:
            path.write_bytes(generate(prompt, key))
            return {"method": "deepinfra", "model": IMAGE_MODEL, "prompt": prompt}
        except di.DeepInfraError as e:
            if log:
                log(f"storyboard image: DeepInfra failed, drawing it locally: {e}")
            draw_pillow(template, path)
            return {"method": "pillow", "model": None, "prompt": prompt, "error": str(e)}
    draw_pillow(template, path)
    return {"method": "pillow", "model": None, "prompt": prompt}
