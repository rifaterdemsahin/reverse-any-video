"""Cost calculator and price for one video analysis. Every rate and assumption is shown to the buyer.

Price = cost of the run + margin on that cost, then the card-payment fee when Stripe is used.
The margin is MARGIN (default 10%) of the cost, not of the price.

Rates are in USD unless marked. Each has a source. The sources are third-party listings, so check them before
you quote a customer. Override any rate with an environment variable of the same name in upper case.
"""
from __future__ import annotations

import math
import os

MARGIN = float(os.environ.get("PRICE_MARGIN", "0.10"))            # 10% on cost
FX_GBP_USD = float(os.environ.get("FX_GBP_USD", "1.27"))          # assumption: set to today's rate
STRIPE_PERCENT = float(os.environ.get("STRIPE_FEE_PERCENT", "0.015"))  # verify against your Stripe plan
STRIPE_FIXED = float(os.environ.get("STRIPE_FEE_FIXED", "0.20"))      # verify against your Stripe plan

RATES = {
    # DeepInfra, per million tokens. Aggregator listings, not DeepInfra's own page.
    "vision_in_per_m": (0.20, "Qwen/Qwen2.5-VL-32B-Instruct input, DeepInfra listings"),
    "vision_out_per_m": (0.60, "Qwen/Qwen2.5-VL-32B-Instruct output, DeepInfra listings"),
    "text_in_per_m": (0.10, "meta-llama/Llama-3.3-70B-Instruct input, DeepInfra listings"),
    "text_out_per_m": (0.32, "meta-llama/Llama-3.3-70B-Instruct output, DeepInfra listings"),
    # Fly.io shared-cpu-2x 1GB, per second. Third-party 2026 calculators.
    "fly_per_s": (0.00000256, "Fly.io shared-cpu-2x 1GB, per second"),
    # Azure Blob Storage, Standard LRS hot, UK South, GBP per GB per month. Undated third-party figure.
    "blob_gbp_per_gb_month": (0.0142, "Azure Blob Storage, UK South, GBP per GB per month (undated)"),
}

# How much each run uses. These are estimates. The quote shows them so they can be checked.
TOKENS_PER_PANEL_IMAGE = 1500      # a 640 px JPEG in a vision model
PANEL_PROMPT_TOKENS = 200
PANEL_OUTPUT_TOKENS = 250
CHARS_PER_TOKEN = 4
CPU_SECONDS_PER_VIDEO_SECOND = 0.5  # download, ffmpeg, frames and model waits
CPU_OVERHEAD_S = 60
CUTS_PER_MIN = 20                  # the test video measured 19.8
STORYBOARD_SHOTS = int(os.environ.get("STORYBOARD_SHOTS", "40"))
FRAME_KB = 60                      # 640 px JPEG
VIDEO_MB_PER_S = 0.25              # 480p download
RETAIN_MONTHS = 1


def _rate(name: str) -> float:
    default, _ = RATES[name]
    return float(os.environ.get(name.upper(), default))


def estimate(duration_s: float, transcript_chars: int | None = None, shots: int | None = None,
             storyboard: bool = True) -> dict:
    """Usage for one run. transcript_chars defaults to about 150 words a minute."""
    duration_s = max(0.0, float(duration_s))
    if transcript_chars is None:
        transcript_chars = int(duration_s / 60 * 150 * 6)          # 150 words a minute, 6 characters a word
    if shots is None:
        shots = max(1, round(duration_s / 60 * CUTS_PER_MIN))
    panels = min(shots, STORYBOARD_SHOTS) if storyboard else 0
    text_tokens = transcript_chars / CHARS_PER_TOKEN
    frame_mb = shots * FRAME_KB / 1024
    video_mb = duration_s * VIDEO_MB_PER_S
    return {
        "duration_s": round(duration_s, 1),
        "shots": shots,
        "panels": panels,
        "transcript_chars": transcript_chars,
        "vision_in_tokens": panels * (TOKENS_PER_PANEL_IMAGE + PANEL_PROMPT_TOKENS),
        "vision_out_tokens": panels * PANEL_OUTPUT_TOKENS,
        "text_in_tokens": round(text_tokens + 300),                 # the transcript plus the prompt
        "text_out_tokens": round(text_tokens * 1.1),                # the clean script is about the same length
        "cpu_seconds": round(CPU_OVERHEAD_S + duration_s * CPU_SECONDS_PER_VIDEO_SECOND),
        "stored_gb": round((frame_mb + video_mb + 0.5) / 1024, 6),   # outputs plus the 480p video, plus ~0.5 MB text
    }


def quote(usage: dict) -> dict:
    """Turn usage into line items, the margin, and the price. Every number is in USD."""
    lines = [
        _line("LLM: vision (storyboard)", usage["vision_in_tokens"] / 1e6 * _rate("vision_in_per_m")
              + usage["vision_out_tokens"] / 1e6 * _rate("vision_out_per_m"),
              f"{usage['vision_in_tokens']:,} input and {usage['vision_out_tokens']:,} output tokens", short="AI reading the video"),
        _line("LLM: script and text", usage["text_in_tokens"] / 1e6 * _rate("text_in_per_m")
              + usage["text_out_tokens"] / 1e6 * _rate("text_out_per_m"),
              f"{usage['text_in_tokens']:,} input and {usage['text_out_tokens']:,} output tokens", short="AI writing the summary"),
        _line("Fly.io compute", usage["cpu_seconds"] * _rate("fly_per_s"),
              f"{usage['cpu_seconds']:,} seconds on a 1 GB Fly.io machine", short="Cloud processing"),
        _line("Azure Blob storage (video and frames)", usage["stored_gb"] * _rate("blob_gbp_per_gb_month") * RETAIN_MONTHS * FX_GBP_USD,
              f"{usage['stored_gb'] * 1024:.1f} MB kept in Azure for {RETAIN_MONTHS} month, "
              f"converted at {FX_GBP_USD} USD per GBP. The video and frames stay with us, not with the customer", short="Storage"),
    ]
    cost = sum(l["amount"] for l in lines)
    margin = cost * MARGIN
    before_fees = cost + margin
    stripe = (before_fees * STRIPE_PERCENT + STRIPE_FIXED) if STRIPE_PERCENT or STRIPE_FIXED else 0.0
    shown_costs = round(sum(l["display"] for l in lines), 2)
    shown_margin = _cent_up(margin)
    shown_fee = _cent_up(stripe)
    price = round(shown_costs + shown_margin + shown_fee, 2)   # the customer pays exactly what they see
    return {
        "currency": "USD",
        "usage": usage,
        "lines": lines,
        "cost": _money(cost),
        "shown": {"costs": shown_costs, "margin": shown_margin, "card_fee": shown_fee},
        "margin_percent": round(MARGIN * 100, 1),
        "margin": _money(margin),
        "card_fee_estimate": _money(stripe),
        "price": price,
        "rates": {k: {"value": _rate(k), "source": src} for k, (_, src) in RATES.items()},
        "assumptions": [
            "Price = cost + 10% margin on cost, plus the card fee when you pay by card.",
            "The customer receives the deliverables only: storyboard, EDL, metrics and the HyperFrames template.",
            "The source video and the frames are kept in our Azure storage for one month and are not delivered.",
            "Storage is charged for one month of retention.",
            "Usage is estimated from the video length. Real runs can differ by a few cents.",
            "Each amount is rounded up to the next cent, and no amount is shown below $0.01.",
            f"Card fee estimate uses {STRIPE_PERCENT * 100:g}% + {STRIPE_FIXED:.2f} (verify against your Stripe plan).",
            f"Pounds converted at {FX_GBP_USD} USD per GBP (set FX_GBP_USD to today's rate).",
        ],
    }


# Credit packs: the customer pays once, the card fee is paid once, and each video uses credit equal to its
# cost plus margin (no per-video card fee). Estimates are how many videos a pack buys at a given length.
PACKAGE_AMOUNTS = (5.00, 20.00, 50.00)   # USD, three packs, whole dollars
PACKAGE_NAMES = {5.00: "Starter", 20.00: "Creator", 50.00: "Studio"}
PACKAGE_BEST = 20.00                      # the one we recommend


def credit_per_video(duration_s: float) -> float:
    """What one video of this length uses from a pack: the costs shown plus the margin, without the card fee."""
    q = quote(estimate(duration_s))
    return round(q["shown"]["costs"] + q["shown"]["margin"], 2)


def package_estimates(duration_s: float) -> list[dict]:
    per = credit_per_video(duration_s)
    out = []
    for amount in PACKAGE_AMOUNTS:
        fee = _cent_up(amount * STRIPE_PERCENT + STRIPE_FIXED)
        out.append({
            "name": PACKAGE_NAMES[amount],
            "best": amount == PACKAGE_BEST,
            "pays": amount,
            "card_fee": fee,
            "net_to_us": round(amount - fee, 2),
            "credit_per_video": per,
            "videos": int(amount // per) if per else 0,
            "duration_s": round(duration_s, 1),
        })
    return out


def _line(label: str, amount: float, detail: str, short: str = "") -> dict:
    return {"label": label, "short": short or label, "amount": _money(amount),
            "display": _cent_up(amount), "detail": detail}


def _cent_up(x: float) -> float:
    """What the customer sees: rounded up to the next cent, never below $0.01."""
    return max(0.01, math.ceil(round(x * 100, 6)) / 100) if x > 0 else 0.01


def _money(x: float) -> float:
    return round(x, 6)


def _up(x: float) -> float:
    """Round up to whole cents, so the price never sits below cost plus margin."""
    return math.ceil(round(x * 100, 6)) / 100
