#!/usr/bin/env python3
"""Render the Sports Plus Denver daily trivia as 3-slide carousels.

Usage:
    python3 render_slides.py trivia.json OUT_DIR [--format both|tiktok|instagram] [--video]

--video also writes short.mp4: an animated 1080x1920 YouTube Short, usually 35-45 seconds,
and short_tiktok.mp4: the same video ending on a "Follow" card instead of "Subscribe"
(hook, question, choices with a 5-second countdown, reveal with confetti, answer, subscribe card).
Screen times scale with the amount of text, at about 3 words per second.
Needs ffmpeg with libx264.

Formats (default: both):
  tiktok     1080x1920 (9:16). TikTok photo mode, Instagram/Facebook Stories.
             Text stays clear of TikTok's status bar, caption and side buttons.
  instagram  1080x1350 (4:5). Instagram/Facebook feed carousel. Text stays clear
             of the ~34px per side the 3:4 profile grid crops off.

trivia.json:
{
  "sport": "Baseball",                 # short label shown on the tag
  "date": "2026-10-08",                # ISO date (Denver time)
  "question": "...",                   # the question, 1-3 sentences
  "choices": ["2", "47", "312", "..."],# 0 or 2-4 short options (A-D); [] for open-ended
  "answer": "Just 2 games",            # short headline answer (include the letter if multiple choice)
  "answer_detail": "...",              # 1-2 sentences of backstory
  "source": "Baseball-Reference",      # short source name for the slide
  "promo_tag": "Free tote bag this weekend",  # optional: short label on slide 1 and the promo box title
  "promo": "Say this answer at the register..."  # optional: one sentence shown in a box on slide 3
}

Writes into OUT_DIR:
  tiktok:    slide1_question.png, slide2_guess.png, slide3_answer.png
  instagram: ig_slide1_question.png, ig_slide2_guess.png, ig_slide3_answer.png
  preview.png: every rendered slide, scaled down, for a quick visual check.
"""
import datetime
import json
import os
import re
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(HERE, "fonts")

# Canvas and text safe zone per format. configure() sets the globals below.
FORMATS = {
    # TikTok overlays the status bar/tabs (top), caption and username (bottom)
    # and the like/comment/share column (right).
    "tiktok": dict(W=1080, H=1920, SAFE_L=90, SAFE_R=925, SAFE_T=230, SAFE_B=1440, prefix=""),
    # Instagram feed: nothing overlays the image; the 3:4 profile grid trims ~34px per side.
    "instagram": dict(W=1080, H=1350, SAFE_L=90, SAFE_R=990, SAFE_T=100, SAFE_B=1250, prefix="ig_"),
}
W = H = SAFE_L = SAFE_R = SAFE_T = SAFE_B = TEXT_W = 0


def configure(fmt):
    global W, H, SAFE_L, SAFE_R, SAFE_T, SAFE_B, TEXT_W
    f = FORMATS[fmt]
    W, H = f["W"], f["H"]
    SAFE_L, SAFE_R, SAFE_T, SAFE_B = f["SAFE_L"], f["SAFE_R"], f["SAFE_T"], f["SAFE_B"]
    TEXT_W = SAFE_R - SAFE_L
    return f["prefix"]

# Sports Plus brand palette (Brand Book v1, 09.22.25).
# Rule from the book: never put green on pink or pink on green.
PINK = (237, 189, 211)   # #edbdd3  primary
MINT = (158, 212, 188)   # #9ed4bc  primary ("Green")
BLACK = (22, 22, 22)     # #161616  secondary
CREAM = (242, 226, 203)  # #f2e2cb  secondary
INK = BLACK
WHITE = (255, 255, 255)  # the book allows plain white for social

HANDLE = "@sportsplusdenver"
SITE = "sportsplusdenver.com"
BRAND = os.path.join(HERE, "brand")
LOGO_H = 46        # straight logo height in slide headers
LOGO_GAP = 38      # clear space under the logo (about one "S" tall, per the book)

# Brand type is Helvetica Neue Bold (primary) and Medium (secondary). Helvetica Neue
# can't be bundled, so the kit uses TeX Gyre Heros, a free Helvetica-style face.
BOLD = "texgyreheros-bold.otf"
MEDIUM = "texgyreheros-regular.otf"
FONT_DIRS = [FONTS, "/usr/share/texmf/fonts/opentype/public/tex-gyre"]
_LOGOS = {}


def logo(name, color, height=None, width=None):
    """Brand artwork (logo_straight, logo_stack, brandmark) in one brand color."""
    key = (name, color, height, width)
    if key not in _LOGOS:
        src = Image.open(os.path.join(BRAND, name + ".png")).convert("RGBA")
        a = src.getchannel("A")
        a = a.crop(a.getbbox())
        if height:
            size = (max(1, round(a.width * height / a.height)), height)
        else:
            size = (width, max(1, round(a.height * width / a.width)))
        im = Image.new("RGBA", size, color + (255,))
        im.putalpha(a.resize(size, Image.LANCZOS))
        _LOGOS[key] = im
    return _LOGOS[key]


def font(name, size):
    for folder in FONT_DIRS:
        path = os.path.join(folder, name)
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    raise SystemExit(f"font not found: {name} (looked in {FONT_DIRS})")


def wrap(text, fnt, max_w):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if fnt.getlength(trial) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def fit(text, font_name, max_w, max_h, max_size, min_size, spacing=1.12):
    """Largest font size (stepping down) whose wrapped text fits the box."""
    size = max_size
    while True:
        fnt = font(font_name, size)
        lines = wrap(text, fnt, max_w)
        line_h = int(size * spacing)
        total = line_h * len(lines)
        widest = max((fnt.getlength(l) for l in lines), default=0)
        if (total <= max_h and widest <= max_w) or size <= min_size:
            return fnt, lines, line_h, total
        size -= 2


def draw_lines(d, x, y, lines, fnt, line_h, fill):
    for i, line in enumerate(lines):
        d.text((x, y + i * line_h), line, font=fnt, fill=fill)
    return y + line_h * len(lines)


def tracked(d, xy, text, fnt, fill, tracking=0):
    """Draw text with letter spacing; returns end x."""
    x, y = xy
    for ch in text:
        d.text((x, y), ch, font=fnt, fill=fill)
        x += fnt.getlength(ch) + tracking
    return x


def tracked_len(text, fnt, tracking=0):
    return sum(fnt.getlength(c) + tracking for c in text) - tracking


def stripes(d, colors, corner="tr", width=34, gap=10, start=150):
    """Retro diagonal stripes cutting across a corner (decoration, outside the safe zone)."""
    for i, col in enumerate(colors):
        o = start + i * (width + gap)
        if corner == "tr":
            d.polygon([(W - o - width, 0), (W - o, 0), (W, o), (W, o + width)], fill=col)
        else:  # bottom-left
            d.polygon([(0, H - o - width), (0, H - o), (o, H), (o + width, H)], fill=col)


def pill(d, x, y, text, fnt, bg, fg, pad_x=26, pad_y=14, tracking=2):
    tw = tracked_len(text, fnt, tracking)
    asc, desc = fnt.getmetrics()
    h = asc + pad_y * 2
    d.rounded_rectangle([x, y, x + tw + pad_x * 2, y + h], radius=h // 2, fill=bg)
    tracked(d, (x + pad_x, y + pad_y - 2), text, fnt, fg, tracking)
    return x + tw + pad_x * 2, y + h


def header(img, d, date_str, sport, on_dark):
    # pink logo on black; black on cream, where pink is too faint to read at this size
    lg = logo("logo_straight", PINK if on_dark else INK, height=LOGO_H)
    img.paste(lg, (SAFE_L, SAFE_T), lg)
    py = SAFE_T + LOGO_H + LOGO_GAP
    tag_font = font(BOLD, 30)
    tag_bg = MINT if on_dark else INK
    tag_fg = INK if on_dark else CREAM
    x2, y2 = pill(d, SAFE_L, py, f"DAILY TRIVIA · {sport.upper()}", tag_font, tag_bg, tag_fg)
    df = font(MEDIUM, 30)
    dim = (190, 180, 165) if on_dark else (90, 84, 76)
    d.text((x2 + 22, py + 14), date_str, font=df, fill=dim)
    return y2


def smart(text):
    """Curly quotes/apostrophes and en dashes in number ranges and scores."""
    text = str(text)
    text = re.sub(r"(?<=[0-9])-(?=[0-9])", "\u2013", text)
    text = re.sub(r"(^|[\s(\[])\"", "\\1\u201c", text)
    text = text.replace('"', "\u201d")
    text = re.sub(r"(^|[\s(\[])'(?=\w)", "\\1\u2018", text)
    text = text.replace("'", "\u2019")
    return text


def nice_date(iso):
    try:
        dt = datetime.date.fromisoformat(iso)
        return dt.strftime("%a · %b ").upper() + str(dt.day)
    except Exception:
        return iso.upper()


SWIPE = "Swipe for the answer →"


def slide_question(data, date_str, cta=SWIPE):
    img = Image.new("RGB", (W, H), BLACK)
    d = ImageDraw.Draw(img)
    # Giant faded question mark for depth.
    qf = font(BOLD, int(1250 * H / 1920))
    d.text((W - 40, H // 2 + 60 * H // 1920), "?", font=qf, fill=(30, 30, 30), anchor="rm")
    stripes(d, [PINK, MINT, CREAM])
    top = header(img, d, date_str, data["sport"], on_dark=True)

    cta_font = font(BOLD, 46)
    cta_y = SAFE_B - 60
    q_top = top + 90
    q_bottom = cta_y - 70
    tag = data.get("promo_tag")
    if tag:
        q_bottom -= 100  # room for the promo label above the swipe line
    q_box_h = q_bottom - q_top
    fnt, lines, lh, total = fit(data["question"], BOLD, TEXT_W, q_box_h, 104, 56)
    # Vertically center the question in its box, nudged up a little.
    y = q_top + max(0, (q_box_h - total) // 2 - 30)
    draw_lines(d, SAFE_L, y, lines, fnt, lh, CREAM)

    if tag:
        pill(d, SAFE_L, cta_y - 100, tag.upper(), font(BOLD, 32), PINK, INK)
    d.text((SAFE_L, cta_y), cta, font=cta_font, fill=PINK)
    return img


def slide_guess(data, date_str, cta=SWIPE, sub="Lock it in the comments, then swipe.", cta_size=46):
    img = Image.new("RGB", (W, H), CREAM)
    d = ImageDraw.Draw(img)
    stripes(d, [PINK, MINT, INK])
    top = header(img, d, date_str, data["sport"], on_dark=False)

    choices = [c for c in (data.get("choices") or []) if str(c).strip()][:4]
    title_font = font(BOLD, 96)
    y = top + 80
    d.text((SAFE_L, y), "Your pick?" if choices else "Your guess?", font=title_font, fill=INK)
    y += 118
    sub_font = font(MEDIUM, 38)
    d.text((SAFE_L, y), sub, font=sub_font, fill=(60, 60, 60))
    y += 90

    cta_font = font(BOLD, 46)
    cta_y = SAFE_B - 60

    if choices:
        letters = "ABCD"
        badge = 92
        gap = 26
        avail = cta_y - 60 - y
        box_w = TEXT_W
        text_w = box_w - badge - 30 - 60
        # Find one font size that lets every choice fit in the available height.
        size = 54
        while True:
            cf = font(BOLD, size)
            lh = int(size * 1.15)
            heights = []
            for c in choices:
                n = len(wrap(str(c), cf, text_w))
                heights.append(max(badge + 36, n * lh + 44))
            total = sum(heights) + gap * (len(choices) - 1)
            if total <= avail or size <= 34:
                break
            size -= 2
        bf = font(BOLD, 50)
        for i, c in enumerate(choices):
            bh = heights[i]
            d.rounded_rectangle([SAFE_L, y, SAFE_L + box_w, y + bh], radius=26, fill=WHITE, outline=INK, width=5)
            cx, cy = SAFE_L + 24 + badge // 2, y + bh // 2
            d.ellipse([cx - badge // 2, cy - badge // 2, cx + badge // 2, cy + badge // 2],
                      fill=PINK if i % 2 == 0 else MINT, outline=INK, width=4)
            d.text((cx, cy), letters[i], font=bf, fill=INK, anchor="mm")
            lines = wrap(str(c), cf, text_w)
            ty = y + (bh - len(lines) * lh) // 2
            for j, line in enumerate(lines):
                d.text((SAFE_L + 24 + badge + 30, ty + j * lh), line, font=cf, fill=INK)
            y += bh + gap
    else:
        qf = font(BOLD, min(560, max(240, int((cta_y - y) * 0.8))))
        d.text((W // 2 - 40, (y + cta_y) // 2), "?", font=qf, fill=PINK, anchor="mm",
               stroke_width=10, stroke_fill=INK)

    d.text((SAFE_L, cta_y + 46 - cta_size), cta, font=font(BOLD, cta_size), fill=INK)
    return img


def slide_answer(data, date_str):
    img = Image.new("RGB", (W, H), MINT)
    d = ImageDraw.Draw(img)
    stripes(d, [INK, CREAM, INK])  # no pink on the green slide
    # Logo in black here: the brand book rules out pink on green.
    lg = logo("logo_straight", INK, height=LOGO_H)
    img.paste(lg, (SAFE_L, SAFE_T), lg)
    _, y = pill(d, SAFE_L, SAFE_T + LOGO_H + LOGO_GAP, "THE ANSWER", font(BOLD, 30), INK, MINT)
    y += 50

    foot_font = font(BOLD, 38)
    foot_y = SAFE_B - 60
    src_font = font(MEDIUM, 30)
    src_y = foot_y - 80

    # Optional promo box sits just above the source line.
    promo = data.get("promo")
    content_bottom = src_y
    if promo:
        pad = 30
        title = (data.get("promo_tag") or "In store").upper()
        tf = font(BOLD, 30)
        pf = font(MEDIUM, 36)
        plines = wrap(promo, pf, TEXT_W - 2 * pad)
        plh = int(36 * 1.3)
        box_h = pad + 40 + 14 + plh * len(plines) + pad - 6
        box_top = src_y - 36 - box_h
        d.rounded_rectangle([SAFE_L, box_top, SAFE_R, box_top + box_h], radius=24, fill=INK)
        tracked(d, (SAFE_L + pad, box_top + pad), title, tf, PINK, tracking=2)
        draw_lines(d, SAFE_L + pad, box_top + pad + 54, plines, pf, plh, CREAM)
        content_bottom = box_top - 10

    # Answer headline and backstory share the space between the tag and the source line (or promo box).
    avail = content_bottom - 50 - y
    ans_max_h = int(avail * 0.42)
    af, alines, alh, atot = fit(data["answer"], BOLD, TEXT_W, ans_max_h, 150, 70, spacing=1.05)
    y = draw_lines(d, SAFE_L, y, alines, af, alh, INK)
    y += af.getmetrics()[1] + 24  # clear the descenders (g, y, p) before the rule
    d.rectangle([SAFE_L, y, SAFE_L + 170, y + 10], fill=INK)
    y += 50
    det_h = content_bottom - 40 - y
    df, dlines, dlh, dtot = fit(data.get("answer_detail", ""), MEDIUM, TEXT_W, det_h, 50, 32, spacing=1.32)
    draw_lines(d, SAFE_L, y, dlines, df, dlh, INK)

    if data.get("source"):
        d.text((SAFE_L, src_y), f"Source: {data['source']}", font=src_font, fill=INK)
    d.text((SAFE_L, foot_y), f"New question every day · {HANDLE}", font=foot_font, fill=INK)
    return img


# ----------------------------------------------------------------------------
# Animated YouTube Short (--video)
# Timeline on a 120 BPM grid (0.5 s beats); set_timeline() sizes it to the text:
#   0.0-2.5   hook: stripes sweep, sport emoji pops, sport name slams in
#   question  lines slide in, numbers in pink, progress bar fills (3 s + ~3 words/s, 8-16 s)
#   wipe      stripe wipe
#   choices   slide in, 2 s to read, then a 5-second countdown ring + draining bar
#   reveal    1.5 s: wrong picks dim, right pick turns mint with a check, confetti
#   answer    headline slams, backstory slides in (4 s + ~3 words/s, 9-20 s)
#   outro     3.5 s subscribe card: button pops, a hand taps it, it flips to "Subscribed"
#             (TikTok version: "Follow" flips to "Following")
# Audio is synthesized here (beat, whooshes, ticks, riser, chime): no music rights needed.
# ----------------------------------------------------------------------------

FPS = 30
T_Q, T_CH, T_CD, T_REV, T_ANS, T_OUT, T_END = 2.5, 9.0, 11.0, 16.0, 17.5, 26.5, 30.0
OUTRO = 3.5
WORDS_PER_SEC = 3.0


def _half(x):
    return round(x * 2) / 2


def set_timeline(data):
    """Give the question and answer screens enough time to read comfortably."""
    global T_CH, T_CD, T_REV, T_ANS, T_OUT, T_END
    q_words = len(data["question"].split())
    a_words = (len(data["answer"].split()) + len((data.get("answer_detail") or "").split())
               + len((data.get("promo") or "").split()))
    q_dur = min(16.0, max(8.0, _half(3.0 + q_words / WORDS_PER_SEC)))
    a_dur = min(20.0, max(9.0, _half(4.0 + a_words / WORDS_PER_SEC)))
    T_CH = T_Q + q_dur
    T_CD = T_CH + 2.0
    T_REV = T_CD + 5.0
    T_ANS = T_REV + 1.5
    T_OUT = T_ANS + a_dur
    T_END = T_OUT + OUTRO


EMOJI_FONT = "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"
SPORT_EMOJI = [
    ("baseball", "⚾"), ("rockies", "⚾"), ("mlb", "⚾"),
    ("football", "\U0001F3C8"), ("broncos", "\U0001F3C8"), ("nfl", "\U0001F3C8"),
    ("basketball", "\U0001F3C0"), ("nuggets", "\U0001F3C0"), ("nba", "\U0001F3C0"),
    ("hockey", "\U0001F3D2"), ("avalanche", "\U0001F3D2"), ("nhl", "\U0001F3D2"),
    ("cycling", "\U0001F6B4"), ("bike", "\U0001F6B4"), ("tour", "\U0001F6B4"),
    ("soccer", "⚽"), ("rapids", "⚽"), ("golf", "⛳"), ("tennis", "\U0001F3BE"),
    ("ski", "⛷"), ("snowboard", "\U0001F3C2"), ("olympic", "\U0001F3C5"),
    ("motor", "\U0001F3C1"), ("racing", "\U0001F3C1"), ("nascar", "\U0001F3C1"),
    ("f1", "\U0001F3C1"), ("boxing", "\U0001F94A"),
]


def _ease(t):
    t = min(1.0, max(0.0, t))
    return 1 - (1 - t) ** 3


def _back(t, s=1.9):
    t = min(1.0, max(0.0, t)) - 1
    return 1 + (s + 1) * t ** 3 + s * t ** 2


def _prog(t, start, dur):
    return min(1.0, max(0.0, (t - start) / dur))


def _lerp(a, b, u):
    return a + (b - a) * u


def _mix(c1, c2, u):
    return tuple(int(_lerp(a, b, u)) for a, b in zip(c1, c2))


def _layer(text, fnt, fill, tracking=0):
    """Text on a transparent layer; paste at (x - 6, y - 6) to match d.text((x, y))."""
    asc, desc = fnt.getmetrics()
    w = int(tracked_len(text, fnt, tracking) if tracking else fnt.getlength(text)) + 12
    im = Image.new("RGBA", (max(w, 1), asc + desc + 12), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if tracking:
        tracked(d, (6, 6), text, fnt, fill, tracking)
    else:
        d.text((6, 6), text, font=fnt, fill=fill)
    return im


def _rich_layer(line, fnt, fill, hi):
    """A line where any word containing a digit is drawn in the highlight color."""
    asc, desc = fnt.getmetrics()
    im = Image.new("RGBA", (int(fnt.getlength(line)) + 12, asc + desc + 12), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    x, space = 6, fnt.getlength(" ")
    for word in line.split(" "):
        d.text((x, 6), word, font=fnt, fill=hi if re.search(r"\d", word) else fill)
        x += fnt.getlength(word) + space
    return im


def _put(frame, im, x, y, alpha=1.0, scale=1.0):
    """Paste an RGBA layer with fade and scale (around its center); clips at the edges."""
    if alpha <= 0.01 or scale <= 0.01:
        return
    if abs(scale - 1) > 0.005:
        w, h = im.size
        nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
        x, y = x + (w - nw) / 2, y + (h - nh) / 2
        im = im.resize((nw, nh), Image.BICUBIC)
    if alpha < 0.99:
        im = im.copy()
        im.putalpha(im.getchannel("A").point(lambda v: int(v * alpha)))
    frame.paste(im, (int(round(x)), int(round(y))), im)


def _emoji(sport, size):
    key = sport.lower()
    return _emoji_img(next((e for k, e in SPORT_EMOJI if k in key), "\U0001F3C6"), size)


def _emoji_img(ch, size):
    try:
        f = ImageFont.truetype(EMOJI_FONT, 109)
    except OSError:
        return None
    im = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((80, 80), ch, font=f, embedded_color=True, anchor="mm")
    bb = im.getbbox()
    if not bb:
        return None
    im = im.crop(bb)
    return im.resize((size, int(size * im.height / im.width)), Image.LANCZOS)


def _ring(rem, color, num, num_scale):
    """Countdown ring (drawn at 2x then downscaled for smooth edges)."""
    S = 2
    r, wd = 74, 15
    size = (r + wd + 6) * 2
    im = Image.new("RGBA", (size * S, size * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    box = [(wd / 2 + 6) * S, (wd / 2 + 6) * S, (size - wd / 2 - 6) * S, (size - wd / 2 - 6) * S]
    d.ellipse([b for b in box], fill=WHITE + (255,))
    d.arc(box, 0, 360, fill=(228, 216, 200, 255), width=wd * S)
    if rem > 0.002:
        d.arc(box, -90 + 360 * (1 - rem), 270, fill=color + (255,), width=wd * S)
    im = im.resize((size, size), Image.LANCZOS)
    if num is not None:
        nf = font(BOLD, int(78 * num_scale))
        ImageDraw.Draw(im).text((size / 2, size / 2 + 2), str(num), font=nf, fill=INK, anchor="mm")
    return im


def _check_badge(size):
    S = 3
    im = Image.new("RGBA", (size * S, size * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse([0, 0, size * S - 1, size * S - 1], fill=INK)
    c = size * S
    d.line([(c * 0.28, c * 0.52), (c * 0.44, c * 0.68), (c * 0.74, c * 0.34)], fill=MINT,
           width=int(c * 0.11), joint="curve")
    return im.resize((size, size), Image.LANCZOS)


def _confetti(seed, x0, y0, n, spread=900, up=1500, cols=None):
    import random
    rnd = random.Random(seed)
    cols = cols or [PINK, MINT, INK]
    parts = []
    for _ in range(n):
        ang = rnd.uniform(-2.6, -0.55)
        sp = rnd.uniform(0.35, 1.0)
        parts.append(dict(x=x0 + rnd.uniform(-60, 60), y=y0 + rnd.uniform(-20, 20),
                          vx=spread * sp * (1 if rnd.random() > 0.5 else -1) * rnd.uniform(0.2, 1.0),
                          vy=-up * sp * rnd.uniform(0.5, 1.0) + 0 * ang,
                          rot=rnd.uniform(0, 6.28), vr=rnd.uniform(-9, 9),
                          w=rnd.uniform(14, 26), h=rnd.uniform(8, 14), c=rnd.choice(cols)))
    return parts


def _draw_confetti(d, parts, tau, life=2.2):
    import math
    if tau < 0 or tau > life:
        return
    g = 2600
    for p in parts:
        x = p["x"] + p["vx"] * tau
        y = p["y"] + p["vy"] * tau + 0.5 * g * tau * tau
        if y > H + 40:
            continue
        a = p["rot"] + p["vr"] * tau
        ca, sa = math.cos(a), math.sin(a)
        hw, hh = p["w"] / 2, p["h"] / 2 * (0.4 + 0.6 * abs(math.sin(a * 1.7)))
        pts = [(x + ca * dx - sa * dy, y + sa * dx + ca * dy) for dx, dy in
               ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh))]
        d.polygon(pts, fill=p["c"])


def _header_layer(date_str, sport, on_dark):
    im = Image.new("RGBA", (W, 420), (0, 0, 0, 0))
    bottom = header(im, ImageDraw.Draw(im), date_str, sport, on_dark)
    bb = im.getbbox()
    return im.crop(bb), bb[0], bb[1], bottom


def _synth_audio(path, total, reveal_has_choices=True):
    import numpy as np
    import wave
    sr = 44100
    n = int(sr * total)
    mix = np.zeros(n)
    rng = np.random.default_rng(7)

    def tt(d):
        return np.arange(int(sr * d)) / sr

    def add(sig, at, gain):
        i = int(at * sr)
        if i >= n:
            return
        j = min(n, i + len(sig))
        mix[i:j] += gain * sig[:j - i]

    def kick():
        x = tt(0.32)
        f = 48 + 110 * np.exp(-x * 32)
        return np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-x * 10)

    def hat():
        x = tt(0.05)
        nz = rng.standard_normal(len(x))
        return np.diff(nz, prepend=0) * np.exp(-x * 90)

    def bass(freq, d=0.22):
        x = tt(d)
        s = np.sin(2 * np.pi * freq * x) + 0.35 * np.sin(4 * np.pi * freq * x)
        return np.tanh(1.6 * s) * np.minimum(1, x * 200) * np.exp(-x * 7)

    def whoosh(d=0.55):
        x = tt(d)
        u = x / d
        nz = rng.standard_normal(len(x))
        out = np.zeros_like(nz)
        acc = 0.0
        for i in range(len(nz)):  # one-pole low-pass with a sweeping cutoff
            k = 0.02 + 0.5 * np.sin(np.pi * u[i]) ** 2
            acc += k * (nz[i] - acc)
            out[i] = acc
        return out * np.sin(np.pi * u) ** 2

    def boom():
        x = tt(0.7)
        f = 35 + 60 * np.exp(-x * 9)
        return np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-x * 4.5)

    def tick(freq):
        x = tt(0.08)
        return np.sin(2 * np.pi * freq * x) * np.exp(-x * 45)

    def bell(freq, d=1.4):
        x = tt(d)
        return (np.sin(2 * np.pi * freq * x) + 0.4 * np.sin(2 * np.pi * freq * 2.01 * x)) * np.exp(-x * 3.2)

    def riser(d):
        x = tt(d)
        f = 220 * (4 ** (x / d))
        return np.sin(2 * np.pi * np.cumsum(f) / sr) * (x / d) ** 2 * 0.6

    roots = [110.0, 87.31, 130.81, 98.0]  # A F C G
    beat = 0.5
    t = 0.0
    while t < T_END - 0.01:
        in_reveal_gap = T_REV <= t < T_ANS
        soft = t >= T_ANS
        if t >= 0.0 and not in_reveal_gap:
            add(kick(), t, 0.55 if soft else 0.85)
            add(hat(), t + beat / 2, 0.10 if soft else 0.14)
            root = roots[int(t // 2) % 4]
            add(bass(root), t, 0.22 if soft else 0.3)
            add(bass(root), t + beat / 2, 0.14 if soft else 0.2)
        t += beat
    add(boom(), 0.02, 0.9)
    for at in (T_Q - 0.25, T_CH - 0.3, T_ANS - 0.25, T_OUT - 0.25):
        add(whoosh(), at, 0.5)
    add(tick(1760), T_OUT + 1.5, 0.5)  # the subscribe tap
    add(bell(2093.0, 0.8), T_OUT + 1.55, 0.2)
    for k in range(5):
        add(tick(1320 if k >= 2 else 990), T_CD + k, 0.45)
    add(riser(T_REV - (T_CD + 3)), T_CD + 3, 0.18)
    add(boom(), T_REV, 0.7)
    for i, f in enumerate((1046.5, 1318.5, 1568.0, 2093.0)):
        add(bell(f), T_REV + 0.02 + i * 0.07, 0.22)
    add(bell(1568.0, 1.0), T_ANS + 0.05, 0.12)
    fade = np.ones(n)
    k = int(sr * 0.6)
    fade[-k:] = np.linspace(1, 0, k)
    mix = np.tanh(mix * 1.1) * fade
    mix = mix / (np.max(np.abs(mix)) + 1e-9) * 0.89
    pcm = (mix * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def make_video(data, date_str, out, platform="youtube"):
    import math
    import shutil
    import subprocess
    import tempfile

    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg not found; cannot render short.mp4")
    configure("tiktok")
    set_timeline(data)
    sport = data["sport"]
    choices = [c for c in (data.get("choices") or []) if str(c).strip()][:4]
    m = re.match(r"\s*([A-Da-d])\s*[:.)\-–]", data["answer"])
    correct = "ABCD".index(m.group(1).upper()) if (m and choices and "ABCD".index(m.group(1).upper()) < len(choices)) else None

    # ---------- hook layers ----------
    mark = logo("brandmark", PINK, width=290)
    emoji = _emoji(sport, 140)
    kicker = _layer("DAILY TRIVIA", font(BOLD, 46), MINT, tracking=6)
    big_size = 190
    while font(BOLD, big_size).getlength(sport.upper()) > TEXT_W and big_size > 80:
        big_size -= 6
    sport_big = _layer(sport.upper(), font(BOLD, big_size), CREAM)
    hook_line = _layer("Deep cut. Can you get it?", font(BOLD, 54), PINK)

    # ---------- question layers (mirrors slide_question) ----------
    hdr_d, hdx, hdy, top = _header_layer(date_str, sport, True)
    qmark = _layer("?", font(BOLD, 1250), (30, 30, 30))
    cta_y = SAFE_B - 60
    q_top, q_bottom = top + 90, cta_y - 70
    tag = data.get("promo_tag")
    if tag:
        q_bottom -= 100
    q_box_h = q_bottom - q_top
    qf, qlines, qlh, qtotal = fit(data["question"], BOLD, TEXT_W, q_box_h, 104, 56)
    qy = q_top + max(0, (q_box_h - qtotal) // 2 - 30)
    q_layers = [_rich_layer(l, qf, CREAM, PINK) for l in qlines]
    tag_layer = None
    if tag:
        tf = font(BOLD, 32)
        tmp = Image.new("RGBA", (W, 120), (0, 0, 0, 0))
        x2, y2 = pill(ImageDraw.Draw(tmp), 0, 0, tag.upper(), tf, PINK, INK)
        tag_layer = tmp.crop((0, 0, int(x2) + 1, int(y2) + 1))

    # ---------- choices layers (mirrors slide_guess) ----------
    hdr_l, hlx, hly, ltop = _header_layer(date_str, sport, False)
    title_y = ltop + 80
    title_f = font(BOLD, 96)
    title_pick = _layer("Your pick?" if choices else "Your guess?", title_f, INK)
    reveal_title = _layer(f"It’s {'ABCD'[correct]}!" if correct is not None else "Time’s up!", title_f, INK)
    sub = _layer("Lock it in the comments!", font(MEDIUM, 38), (60, 60, 60))
    sub_rev = _layer("Did you get it? Tell us below.", font(MEDIUM, 38), (60, 60, 60))
    cy0 = title_y + 118 + 90
    boxes, boxes_ok, box_pos = [], [], []
    if choices:
        badge, gap = 92, 26
        avail = cta_y - 60 - cy0
        text_w = TEXT_W - badge - 30 - 60
        size = 54
        while True:
            cf = font(BOLD, size)
            lh = int(size * 1.15)
            heights = [max(badge + 36, len(wrap(str(c), cf, text_w)) * lh + 44) for c in choices]
            if sum(heights) + gap * (len(choices) - 1) <= avail or size <= 34:
                break
            size -= 2
        bf = font(BOLD, 50)
        check = _check_badge(badge)
        y = cy0
        for i, c in enumerate(choices):
            bh = heights[i]
            for ok in (False, True):
                im = Image.new("RGBA", (TEXT_W + 1, bh + 1), (0, 0, 0, 0))
                d = ImageDraw.Draw(im)
                d.rounded_rectangle([0, 0, TEXT_W, bh], radius=26, fill=MINT if ok else WHITE,
                                    outline=INK, width=7 if ok else 5)
                bx, by = 24 + badge // 2, bh // 2
                if ok:
                    im.paste(check, (bx - badge // 2, by - badge // 2), check)
                else:
                    d.ellipse([bx - badge // 2, by - badge // 2, bx + badge // 2, by + badge // 2],
                              fill=PINK if i % 2 == 0 else MINT, outline=INK, width=4)
                    d.text((bx, by), "ABCD"[i], font=bf, fill=INK, anchor="mm")
                ls = wrap(str(c), cf, text_w)
                ty = (bh - len(ls) * lh) // 2
                for j, line in enumerate(ls):
                    d.text((24 + badge + 30, ty + j * lh), line, font=cf, fill=INK)
                (boxes_ok if ok else boxes).append(im)
            box_pos.append((SAFE_L, y))
            y += bh + gap
    big_q = None
    if not choices:
        qs = min(560, max(240, int((cta_y - cy0) * 0.8)))
        tmp = Image.new("RGBA", (qs + 60, qs + 60), (0, 0, 0, 0))
        ImageDraw.Draw(tmp).text(((qs + 60) // 2, (qs + 60) // 2), "?", font=font(BOLD, qs),
                                 fill=PINK, anchor="mm", stroke_width=10, stroke_fill=INK)
        big_q = tmp.crop(tmp.getbbox())
    ring_cx, ring_cy = SAFE_R - 92, title_y + 60
    confetti_ch = None
    open_reveal = None
    if correct is not None:
        bx, by = box_pos[correct]
        confetti_ch = _confetti(11, bx + 120, by + boxes[correct].height // 2, 90)
    elif not choices:
        # open-ended: the answer itself slams in where the big "?" was
        of, olines, olh, ototal = fit(data["answer"], BOLD, TEXT_W, 420, 150, 70, spacing=1.05)
        open_reveal = Image.new("RGBA", (TEXT_W + 12, ototal + 40), (0, 0, 0, 0))
        draw_lines(ImageDraw.Draw(open_reveal), 6, 6, olines, of, olh, INK)
        confetti_ch = _confetti(11, W // 2, (cy0 + cta_y) // 2, 100)

    # ---------- answer layers (mirrors slide_answer) ----------
    wm = logo("logo_straight", INK, height=LOGO_H)
    tmp = Image.new("RGBA", (W, 160), (0, 0, 0, 0))
    ax2, ay2 = pill(ImageDraw.Draw(tmp), 0, 0, "THE ANSWER", font(BOLD, 30), INK, MINT)
    ans_pill = tmp.crop((0, 0, int(ax2) + 1, int(ay2) + 1))
    ay = SAFE_T + LOGO_H + LOGO_GAP + ans_pill.height + 50
    foot_y = cta_y
    src_y = foot_y - 80
    promo = data.get("promo")
    content_bottom = src_y
    promo_layer, promo_y = None, 0
    if promo:
        pad = 30
        pf = font(MEDIUM, 36)
        plines = wrap(promo, pf, TEXT_W - 2 * pad)
        plh = int(36 * 1.3)
        box_h = pad + 40 + 14 + plh * len(plines) + pad - 6
        promo_y = src_y - 36 - box_h
        promo_layer = Image.new("RGBA", (TEXT_W + 1, box_h + 1), (0, 0, 0, 0))
        d = ImageDraw.Draw(promo_layer)
        d.rounded_rectangle([0, 0, TEXT_W, box_h], radius=24, fill=INK)
        tracked(d, (pad, pad), (tag or "In store").upper(), font(BOLD, 30), PINK, tracking=2)
        draw_lines(d, pad, pad + 54, plines, pf, plh, CREAM)
        content_bottom = promo_y - 10
    avail = content_bottom - 50 - ay
    af, alines, alh, _ = fit(data["answer"], BOLD, TEXT_W, int(avail * 0.42), 150, 70, spacing=1.05)
    a_layers = [_layer(l, af, INK) for l in alines]
    rule_y = ay + alh * len(alines) + af.getmetrics()[1] + 24
    det_y = rule_y + 50
    df, dlines, dlh, _ = fit(data.get("answer_detail", ""), MEDIUM, TEXT_W,
                             content_bottom - 40 - det_y, 50, 32, spacing=1.32)
    d_layers = [_layer(l, df, INK) for l in dlines]
    src_layer = _layer(f"Source: {data['source']}", font(MEDIUM, 30), INK) if data.get("source") else None

    # ---------- subscribe outro layers ----------
    out_kicker = _layer("ENJOY THAT ONE?", font(BOLD, 46), MINT, tracking=6)
    out_line = _layer("New deep-cut trivia every day.", font(BOLD, 54), CREAM)
    out_wm = logo("logo_stack", PINK, width=330)
    hand = _emoji_img("\U0001F446", 170)

    def _button(label, icon, bg, fg, outline=None):
        bf_ = font(BOLD, 76)
        icon_w = icon.width if icon is not None else 0
        bw, bh_ = 56 + icon_w + (24 if icon_w else 0) + int(bf_.getlength(label)) + 60, 150
        im = Image.new("RGBA", (bw * 2, bh_ * 2), (0, 0, 0, 0))
        ImageDraw.Draw(im).rounded_rectangle([0, 0, bw * 2 - 1, bh_ * 2 - 1], radius=bh_, fill=bg,
                                             outline=outline, width=12 if outline else 0)
        im = im.resize((bw, bh_), Image.LANCZOS)
        x = 56
        if icon is not None:
            im.paste(icon, (x, (bh_ - icon.height) // 2), icon)
            x += icon_w + 24
        ImageDraw.Draw(im).text((x, bh_ // 2 + 2), label, font=bf_, fill=fg, anchor="lm")
        return im

    if platform == "tiktok":
        plus = Image.new("RGBA", (72, 72), (0, 0, 0, 0))
        pd = ImageDraw.Draw(plus)
        pd.rounded_rectangle([27, 4, 45, 68], radius=6, fill=INK)
        pd.rounded_rectangle([4, 27, 68, 45], radius=6, fill=INK)
        btn_off = _button("Follow", plus, PINK, INK)
        btn_on = _button("Following", _check_badge(84), CREAM, INK, outline=INK)
    else:
        btn_off = _button("Subscribe", _emoji_img("\U0001F514", 80), PINK, INK)
        btn_on = _button("Subscribed", _check_badge(84), CREAM, INK, outline=INK)
    btn_cy = 860
    confetti_sub = _confetti(31, W // 2 + 120, btn_cy, 45, spread=700, up=1200, cols=[PINK, MINT, CREAM])
    confetti_ans = _confetti(23, W // 2, ay + 40, 110, spread=1100, up=1700, cols=[INK, CREAM, WHITE])

    def stripes_at(d, colors, slide):
        # corner stripes slide in from the top-right as `slide` goes 0 -> 1
        off = int((1 - _ease(slide)) * 420)
        for i, col in enumerate(colors):
            o = 150 + i * 44 - off
            d.polygon([(W - o - 34, 0), (W - o, 0), (W, o), (W, o + 34)], fill=col)

    def wipe(d, u, lead_c=PINK, trail_c=MINT):
        # a cream band with colored edges sweeps left to right; fully covered at u = 0.5.
        # Edge colors are picked per transition so pink never lands on green (brand rule).
        lead = _lerp(-0.1 * W, 3.5 * W, u)
        skew = 0.45 * W
        for x0, x1, col in ((lead - 2.0 * W, lead, CREAM), (lead - 70, lead, lead_c),
                            (lead - 2.0 * W, lead - 2.0 * W + 70, trail_c)):
            d.polygon([(x0, 0), (x1, 0), (x1 - skew, H), (x0 - skew, H)], fill=col)

    def frame_at(t):
        if t < T_Q:  # ------------------------------------------------ hook
            fr = Image.new("RGB", (W, H), BLACK)
            d = ImageDraw.Draw(fr)
            stripes_at(d, [PINK, MINT, CREAM], _prog(t, 0.0, 0.5))
            s = _back(_prog(t, 0.08, 0.45))
            _put(fr, mark, (W - mark.width) / 2, 380, alpha=min(1, s * 1.5), scale=s)
            _put(fr, kicker, (W - kicker.width) / 2, 740 + 30 * (1 - _ease(_prog(t, 0.25, 0.3))),
                 alpha=_prog(t, 0.25, 0.25))
            p = _prog(t, 0.35, 0.28)
            _put(fr, sport_big, (W - sport_big.width) / 2, 810, alpha=p, scale=_lerp(1.9, 1.0, _ease(p)))
            _put(fr, hook_line, (W - hook_line.width) / 2, 1030 + 40 * (1 - _ease(_prog(t, 0.7, 0.3))),
                 alpha=_prog(t, 0.7, 0.25))
            if emoji is not None:
                s = _back(_prog(t, 1.0, 0.45), 2.4)
                _put(fr, emoji, (W - emoji.width) / 2, 1140, alpha=min(1, s * 1.5), scale=s)
            if t < 0.4:  # open on a full-screen stripe sweep that clears to reveal the hook
                wipe(ImageDraw.Draw(fr), _lerp(0.5, 1.0, _ease(_prog(t, 0.0, 0.4))))
            return fr
        if t < T_CH:  # ----------------------------------------------- question
            lt = t - T_Q
            fr = Image.new("RGB", (W, H), BLACK)
            drift = lt / (T_CH - T_Q)
            _put(fr, qmark, W - qmark.width + 60 - 80 * drift, H / 2 - qmark.height / 2 + 40, scale=1.0 + 0.06 * drift)
            d = ImageDraw.Draw(fr)
            stripes_at(d, [PINK, MINT, CREAM], 1)
            hp = _ease(_prog(lt, 0.0, 0.35))
            _put(fr, hdr_d, hdx, hdy - 50 * (1 - hp), alpha=hp)
            for i, ly in enumerate(q_layers):
                p = _prog(lt, 0.25 + i * 0.2, 0.32)
                _put(fr, ly, SAFE_L - 6, qy + i * qlh - 6 + 60 * (1 - _ease(p)), alpha=p)
            if tag_layer is not None:
                s = _back(_prog(lt, 1.6, 0.4))
                _put(fr, tag_layer, SAFE_L, cta_y - 100, alpha=min(1, s * 1.5), scale=s)
            bar_y = cta_y + 18
            d.rounded_rectangle([SAFE_L, bar_y, SAFE_R, bar_y + 16], radius=8, fill=(48, 48, 48))
            fill_w = int(TEXT_W * _prog(lt, 0.3, (T_CH - T_Q) - 0.5))
            if fill_w > 16:
                d.rounded_rectangle([SAFE_L, bar_y, SAFE_L + fill_w, bar_y + 16], radius=8, fill=PINK)
            if t > T_CH - 0.3:
                wipe(d, _lerp(0.0, 0.5, _prog(t, T_CH - 0.3, 0.3)))
            if lt < 0.15:
                fr = Image.blend(fr, Image.new("RGB", (W, H), CREAM), 0.5 * (1 - lt / 0.15))
            return fr
        if t < T_ANS:  # ---------------------------------------------- choices, countdown, reveal
            lt = t - T_CH
            fr = Image.new("RGB", (W, H), CREAM)
            d = ImageDraw.Draw(fr)
            stripes_at(d, [PINK, MINT, INK], 1)
            fr.paste(hdr_l, (hlx, hly), hdr_l)
            revealing = t >= T_REV
            rp = _prog(t, T_REV, 0.35)
            if not revealing:
                s = _back(_prog(lt, 0.2, 0.4), 2.4)
                _put(fr, title_pick, SAFE_L - 6, title_y - 6, alpha=min(1, s * 1.4), scale=_lerp(0.7, 1, s))
            else:
                s = _back(rp, 2.6)
                _put(fr, reveal_title, SAFE_L - 6, title_y - 6, alpha=min(1, s * 1.4), scale=_lerp(0.6, 1, s))
            if not revealing:
                _put(fr, sub, SAFE_L - 6, title_y + 118 - 6, alpha=_prog(lt, 0.4, 0.3))
            else:
                _put(fr, sub_rev, SAFE_L - 6, title_y + 118 - 6, alpha=rp)
            for i, im in enumerate(boxes):
                bx, by = box_pos[i]
                p = _ease(_prog(lt, 0.5 + i * 0.13, 0.35))
                x = bx + (1 - p) * 700
                if revealing and correct is not None:
                    if i == correct:
                        pop = 1 + 0.08 * math.sin(math.pi * _prog(t, T_REV, 0.45))
                        _put(fr, boxes_ok[i], x, by, alpha=rp, scale=pop)
                        if rp < 1:
                            _put(fr, im, x, by, alpha=1 - rp)
                    else:
                        _put(fr, im, x - 20 * rp, by, alpha=1 - 0.62 * rp)
                else:
                    _put(fr, im, x, by, alpha=p)
            if big_q is not None:
                beatp = ((t - T_CD) % 1.0) if t >= T_CD else 1.0
                s = 1 + 0.07 * (1 - _ease(beatp / 0.35)) if not revealing else 1 + 0.6 * rp
                _put(fr, big_q, (W - big_q.width) / 2 - 40, (cy0 + cta_y) / 2 - big_q.height / 2,
                     alpha=_prog(lt, 0.4, 0.3) * (1 - rp), scale=s)
            if open_reveal is not None and revealing:
                s = _back(_prog(t, T_REV + 0.1, 0.35), 2.2)
                _put(fr, open_reveal, SAFE_L - 6, (cy0 + cta_y) / 2 - open_reveal.height / 2,
                     alpha=min(1, s * 1.5), scale=_lerp(1.6, 1.0, min(1, s)))
            # countdown ring + draining bar
            if t >= T_CD - 0.3:
                rem = 1 - _prog(t, T_CD, T_REV - T_CD)
                col = _mix(MINT, PINK, min(1, (1 - rem) * 1.6)) if rem > 0.375 else _mix(PINK, INK, 1 - rem / 0.375)
                if not revealing:
                    num = max(1, math.ceil(rem * 5 - 1e-6))
                    since = (t - T_CD) % 1.0 if t >= T_CD else 1.0
                    ns = 1 + 0.45 * (1 - _ease(since / 0.3))
                    ring = _ring(rem, col, num, ns)
                    ap = _back(_prog(t, T_CD - 0.3, 0.3))
                    _put(fr, ring, ring_cx - ring.width / 2, ring_cy - ring.height / 2, alpha=min(1, ap), scale=ap)
                else:
                    cb = _check_badge(160)
                    s = _back(rp, 2.2)
                    _put(fr, cb, ring_cx - 80, ring_cy - 80, alpha=min(1, s * 1.5), scale=s)
                bar_y = cta_y + 18
                d.rounded_rectangle([SAFE_L, bar_y, SAFE_R, bar_y + 18], radius=9, fill=(228, 216, 200))
                fw = int(TEXT_W * rem)
                if fw > 18:
                    d.rounded_rectangle([SAFE_L, bar_y, SAFE_L + fw, bar_y + 18], radius=9, fill=col)
            if revealing:
                if confetti_ch is not None:
                    _draw_confetti(d, confetti_ch, t - T_REV)
                if rp < 1:
                    fr = Image.blend(fr, Image.new("RGB", (W, H), (255, 255, 255)), 0.45 * (1 - rp))
            if lt < 0.3:
                wipe(ImageDraw.Draw(fr), _lerp(0.5, 1.0, _ease(_prog(lt, 0.0, 0.3))))
            if t > T_ANS - 0.3:
                wipe(ImageDraw.Draw(fr), _lerp(0.0, 0.5, _prog(t, T_ANS - 0.3, 0.3)), PINK, INK)
            return fr
        if t >= T_OUT:  # --------------------------------------------- subscribe outro
            lt = t - T_OUT
            fr = Image.new("RGB", (W, H), BLACK)
            d = ImageDraw.Draw(fr)
            stripes_at(d, [PINK, MINT, CREAM], 1)
            stripes(d, [CREAM, MINT, PINK], corner="bl")
            p = _prog(lt, 0.2, 0.3)
            _put(fr, out_kicker, (W - out_kicker.width) / 2, 640 + 30 * (1 - _ease(p)), alpha=p)
            tap = _prog(lt, 1.45, 0.15)
            on = _prog(lt, 1.5, 0.15)
            s = _back(_prog(lt, 0.3, 0.4), 2.2) * (1 + 0.1 * math.sin(math.pi * _prog(lt, 1.5, 0.35)))
            if on < 1:
                _put(fr, btn_off, (W - btn_off.width) / 2, btn_cy - btn_off.height / 2,
                     alpha=min(1, s * 1.5) * (1 - on), scale=s * (1 - 0.06 * math.sin(math.pi * tap)))
            if on > 0:
                _put(fr, btn_on, (W - btn_on.width) / 2, btn_cy - btn_on.height / 2, alpha=on, scale=s)
            p = _prog(lt, 0.6, 0.3)
            _put(fr, out_line, (W - out_line.width) / 2, 1090 + 30 * (1 - _ease(p)), alpha=p)
            _put(fr, out_wm, (W - out_wm.width) / 2, 1200, alpha=_prog(lt, 0.8, 0.3))
            if hand is not None:
                arrive = _ease(_prog(lt, 0.85, 0.5))
                leave = _ease(_prog(lt, 2.4, 0.4))
                hx = W / 2 + 120 - hand.width / 2
                hy = _lerp(H + 40, btn_cy + 10, arrive) + (H - btn_cy) * leave + 18 * math.sin(math.pi * tap)
                _put(fr, hand, hx, hy, scale=1 - 0.08 * math.sin(math.pi * tap))
            _draw_confetti(d, confetti_sub, lt - 1.55, life=1.8)
            if lt < 0.35:
                wipe(ImageDraw.Draw(fr), _lerp(0.5, 1.0, _ease(_prog(lt, 0.0, 0.35))), INK, PINK)
            if t > T_END - 0.3:  # brief wipe at the end so the loop restarts cleanly
                wipe(ImageDraw.Draw(fr), _lerp(0.0, 0.5, _prog(t, T_END - 0.3, 0.3)))
            return fr
        # ------------------------------------------------------------------- answer
        lt = t - T_ANS
        fr = Image.new("RGB", (W, H), MINT)
        d = ImageDraw.Draw(fr)
        stripes_at(d, [INK, CREAM, INK], 1)
        hp = _ease(_prog(lt, 0.0, 0.3))
        _put(fr, wm, SAFE_L, SAFE_T - 40 * (1 - hp), alpha=hp)
        _put(fr, ans_pill, SAFE_L, SAFE_T + LOGO_H + LOGO_GAP - 40 * (1 - hp), alpha=hp)
        for i, ly in enumerate(a_layers):
            p = _prog(lt, 0.15 + i * 0.1, 0.3)
            _put(fr, ly, SAFE_L - 6, ay + i * alh - 6, alpha=min(1, p * 1.6), scale=_lerp(1.45, 1.0, _ease(p)))
        rw = int(170 * _ease(_prog(lt, 0.45, 0.3)))
        if rw > 2:
            d.rectangle([SAFE_L, rule_y, SAFE_L + rw, rule_y + 10], fill=INK)
        for i, ly in enumerate(d_layers):
            p = _prog(lt, 0.7 + i * 0.12, 0.35)
            _put(fr, ly, SAFE_L - 6 + 40 * (1 - _ease(p)), det_y + i * dlh - 6, alpha=p)
        if promo_layer is not None:
            p = _ease(_prog(lt, 1.6, 0.4))
            _put(fr, promo_layer, SAFE_L, promo_y + 80 * (1 - p), alpha=p)
        if src_layer is not None:
            _put(fr, src_layer, SAFE_L - 6, src_y - 6, alpha=_prog(lt, 1.4, 0.4))
        # timer bar: drains over the time left on the answer screen
        bar_y = cta_y + 18
        rem = 1 - _prog(t, T_ANS + 0.4, T_OUT - T_ANS - 0.4)
        d.rounded_rectangle([SAFE_L, bar_y, SAFE_R, bar_y + 18], radius=9, fill=(124, 178, 154))
        fw = int(TEXT_W * rem)
        if fw > 18:
            d.rounded_rectangle([SAFE_L, bar_y, SAFE_L + fw, bar_y + 18], radius=9, fill=INK)
        _draw_confetti(d, confetti_ans, lt - 0.1)
        if lt < 0.3:
            wipe(d, _lerp(0.5, 1.0, _ease(_prog(lt, 0.0, 0.3))), PINK, INK)
        if t > T_OUT - 0.3:  # wipe into the subscribe card
            wipe(d, _lerp(0.0, 0.5, _prog(t, T_OUT - 0.3, 0.3)), INK, PINK)
        return fr

    tmpdir = tempfile.mkdtemp(prefix="short_")
    wav = os.path.join(tmpdir, "audio.wav")
    _synth_audio(wav, T_END)
    name = "short_tiktok.mp4" if platform == "tiktok" else "short.mp4"
    mp4 = os.path.join(out, name)
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-i", wav, "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", mp4]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for i in range(int(T_END * FPS)):
            proc.stdin.write(frame_at(i / FPS).convert("RGB").tobytes())
    finally:
        proc.stdin.close()
        proc.wait()
    shutil.rmtree(tmpdir, ignore_errors=True)
    if proc.returncode:
        raise SystemExit(f"ffmpeg failed to write {name}")
    return name


def main():
    args = sys.argv[1:]
    want_video = "--video" in args
    if want_video:
        args.remove("--video")
    fmt = "both"
    if "--format" in args:
        i = args.index("--format")
        if i + 1 >= len(args):
            sys.exit("--format needs a value: both, tiktok or instagram")
        fmt = args[i + 1]
        del args[i:i + 2]
    if len(args) != 2 or fmt not in ("both", "tiktok", "instagram"):
        print(__doc__)
        sys.exit(1)
    with open(args[0]) as f:
        data = json.load(f)
    out = args[1]
    os.makedirs(out, exist_ok=True)
    for key in ("sport", "question", "answer"):
        if not str(data.get(key, "")).strip():
            sys.exit(f"missing field: {key}")
    for key in ("question", "answer", "answer_detail", "source", "promo_tag", "promo"):
        if data.get(key):
            data[key] = smart(data[key])
    data["choices"] = [smart(c) for c in (data.get("choices") or [])]
    date_str = nice_date(data.get("date", datetime.date.today().isoformat()))
    formats = ["tiktok", "instagram"] if fmt == "both" else [fmt]
    rows, written = [], []
    for f in formats:
        prefix = configure(f)
        slides = [
            (prefix + "slide1_question.png", slide_question(data, date_str)),
            (prefix + "slide2_guess.png", slide_guess(data, date_str)),
            (prefix + "slide3_answer.png", slide_answer(data, date_str)),
        ]
        for name, img in slides:
            img.save(os.path.join(out, name), optimize=True)
            written.append(name)
        rows.append([img for _, img in slides])
    # One preview image: a row of three slides per format, all scaled to the same height.
    ph = 600
    pad = 12
    scaled = [[im.resize((im.width * ph // im.height, ph)) for im in row] for row in rows]
    pw = max(sum(im.width for im in row) + pad * (len(row) + 1) for row in scaled)
    prev = Image.new("RGB", (pw, len(scaled) * (ph + pad) + pad), (90, 90, 90))
    for r, row in enumerate(scaled):
        x = pad
        for im in row:
            prev.paste(im, (x, pad + r * (ph + pad)))
            x += im.width + pad
    prev.save(os.path.join(out, "preview.png"))
    if want_video:
        written.append(make_video(data, date_str, out, "youtube"))
        written.append(make_video(data, date_str, out, "tiktok"))
    print("wrote", ", ".join(written), "to", out)


if __name__ == "__main__":
    main()
