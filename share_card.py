# -*- coding: utf-8 -*-
"""Self-designed share card (PNG 1200x675, X-ready) — drawn with PIL.
Fonts are bundled in assets/fonts so it renders identically everywhere."""
import io
import os

from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 675
BG_TOP = (10, 13, 20)
BG_BOT = (17, 24, 39)
PANEL = (21, 28, 41)
PANEL_LINE = (45, 55, 72)
TXT = (238, 242, 248)
MUT = (148, 158, 174)
GREEN = (52, 211, 122)
RED = (248, 90, 90)
YELLOW = (250, 204, 21)
BLUE = (56, 189, 248)
SLATE = (102, 116, 138)
PURPLE = (167, 139, 250)
BAR_COLORS = [(56, 189, 248), (74, 222, 128), (163, 230, 53), (250, 204, 21),
              (251, 146, 60), (248, 113, 113), (192, 132, 252)]

_FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "assets", "fonts")


def _font(size: int, bold: bool = False):
    fname = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    candidates = [
        os.path.join(_FONT_DIR, fname),
        f"/usr/share/fonts/truetype/dejavu/{fname}",
    ]
    for p in candidates:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _score_color(score):
    return GREEN if score >= 70 else (YELLOW if score >= 45 else RED)


def _fmt_usd(v):
    if v >= 1e9:
        return f"${v/1e9:.2f}B"
    if v >= 1e6:
        return f"${v/1e6:.2f}M"
    if v >= 1e3:
        return f"${v/1e3:.1f}K"
    return f"${v:,.0f}"


def _fmt_cnt(v):
    return f"{v/1000:.1f}K" if v >= 1000 else f"{v:,}"


def _gradient_bg():
    img = Image.new("RGB", (W, H), BG_TOP)
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        c = tuple(int(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOT))
        d.line([(0, y), (W, y)], fill=c)
    return img


def _panel(d, x0, y0, x1, y1, r=16, title=None, title_color=TXT):
    # soft shadow
    d.rounded_rectangle([x0 + 3, y0 + 4, x1 + 3, y1 + 4], radius=r,
                        fill=(6, 8, 13))
    d.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=PANEL,
                        outline=PANEL_LINE, width=1)
    if title:
        d.text((x0 + 18, y0 + 14), title, font=_font(15, True),
               fill=title_color)
        d.line([(x0 + 18, y0 + 40), (x1 - 18, y0 + 40)], fill=PANEL_LINE,
               width=1)


def build_share_card(*, symbol, name, ca, score, score_label, holders,
                     holder_delta, n_real, n_dust, ratio_pct, real_mc_pct,
                     marketcap, liquidity_usd, liq_pct_mc, top10_pct,
                     tier_labels, tier_counts, hist_dates, hist_holders,
                     buys24, sells24, cluster_txt, verdict_ok) -> bytes:
    img = _gradient_bg()
    d = ImageDraw.Draw(img)
    sc = _score_color(score)

    # ============================ HEADER =====================================
    # accent bar on the left of the title
    d.rounded_rectangle([40, 32, 46, 96], radius=3, fill=sc)
    tf = _font(48, True)
    d.text((60, 26), f"${symbol}", font=tf, fill=TXT)
    tw = d.textlength(f"${symbol}", font=tf)
    if name and name.lower() != symbol.lower():
        d.text((60 + tw + 16, 48), name[:24], font=_font(20), fill=MUT)
    d.text((60, 82), ca, font=_font(16), fill=MUT)

    # verdict pill
    pill_txt = "HOLDERS OK" if verdict_ok else "UNHEALTHY HOLDERS"
    pill_col = GREEN if verdict_ok else RED
    pf = _font(18, True)
    ptw = d.textlength(pill_txt, font=pf)
    pr_x1 = W - 240
    pr_x0 = pr_x1 - ptw - 44
    d.rounded_rectangle([pr_x0, 42, pr_x1, 86], radius=22,
                        fill=(pill_col[0] // 6, pill_col[1] // 6,
                              pill_col[2] // 6),
                        outline=pill_col, width=2)
    d.text((pr_x0 + 22, 53), pill_txt, font=pf, fill=pill_col)

    # score donut
    cx, cy, rr = W - 118, 64, 52
    d.ellipse([cx - rr - 8, cy - rr - 8, cx + rr + 8, cy + rr + 8],
              fill=(sc[0] // 10, sc[1] // 10, sc[2] // 10))
    d.arc([cx - rr, cy - rr, cx + rr, cy + rr], 0, 360, fill=PANEL_LINE,
          width=10)
    d.arc([cx - rr, cy - rr, cx + rr, cy + rr], -90,
          -90 + int(360 * min(score, 100) / 100), fill=sc, width=10)
    sf = _font(36, True)
    d.text((cx - d.textlength(str(score), font=sf) / 2, cy - 26), str(score),
           font=sf, fill=sc)
    lf = _font(12, True)
    d.text((cx - d.textlength(score_label, font=lf) / 2, cy + 14),
           score_label, font=lf, fill=sc)
    cap = "HEALTH SCORE"
    cf0 = _font(11)
    d.text((cx - d.textlength(cap, font=cf0) / 2, cy + rr + 12), cap,
           font=cf0, fill=MUT)

    # ============================ STAT CHIPS =================================
    if holder_delta is None:
        h_sub, h_col = "", TXT
    else:
        h_sub = f"{holder_delta:+,} vs yesterday"
        h_col = GREEN if holder_delta >= 0 else RED
    stats = [
        ("HOLDERS", f"{holders:,}", h_sub, h_col, BLUE),
        ("REAL / DUST", f"{_fmt_cnt(n_real)} / {_fmt_cnt(n_dust)}",
         f"ratio {ratio_pct:.0f}%  (>30% ok)",
         GREEN if ratio_pct > 30 else RED,
         GREEN if ratio_pct > 30 else RED),
        ("REAL % MC", f"{real_mc_pct:.1f}%", "held by real holders", MUT,
         GREEN),
        ("MARKETCAP", _fmt_usd(marketcap), "", MUT, PURPLE),
        ("LIQUIDITY", _fmt_usd(liquidity_usd), f"{liq_pct_mc:.1f}% of MC",
         MUT, YELLOW),
        ("TOP-10", f"{top10_pct:.1f}%",
         "of supply" + ("  ⚠" if top10_pct > 30 else ""),
         RED if top10_pct > 30 else MUT,
         RED if top10_pct > 30 else BLUE),
    ]
    x, y0, bw, bh, gap = 40, 128, 180, 96, 8
    for label, val, sub, sub_col, accent in stats:
        _panel(d, x, y0, x + bw, y0 + bh, r=12)
        d.rounded_rectangle([x, y0, x + 5, y0 + bh], radius=2, fill=accent)
        d.text((x + 16, y0 + 12), label, font=_font(12, True), fill=MUT)
        vf = _font(25, True)
        d.text((x + 16, y0 + 34), val, font=vf, fill=TXT)
        if sub:
            d.text((x + 16, y0 + 68), sub, font=_font(13), fill=sub_col)
        x += bw + gap

    # ============================ PANELS =====================================
    top, bottom = 248, 590

    # ---- 1) Wallet depth bars ----
    p1 = (40, top, 486, bottom)
    _panel(d, *p1, title="WALLET DEPTH BY THRESHOLD")
    n = len(tier_counts)
    ax0, ay0 = p1[0] + 22, p1[1] + 74
    ax1, ay1 = p1[2] - 22, p1[3] - 44
    maxc = max(tier_counts) or 1
    bw2 = (ax0 - ax1) / -n
    cf = _font(14, True)
    tlf = _font(12)
    for i, (lab, cnt) in enumerate(zip(tier_labels, tier_counts)):
        bx0 = ax0 + i * bw2 + 7
        bx1 = ax0 + (i + 1) * bw2 - 7
        hh = (ay1 - ay0) * (cnt / maxc)
        by0 = ay1 - max(hh, 4)
        col = BAR_COLORS[i % len(BAR_COLORS)]
        # subtle bar background track
        d.rounded_rectangle([bx0, ay0, bx1, ay1], radius=5,
                            fill=(28, 36, 52))
        d.rounded_rectangle([bx0, by0, bx1, ay1], radius=5, fill=col)
        ct = _fmt_cnt(cnt)
        d.text(((bx0 + bx1) / 2 - d.textlength(ct, font=cf) / 2,
                by0 - 22), ct, font=cf, fill=TXT)
        d.text(((bx0 + bx1) / 2 - d.textlength(lab, font=tlf) / 2, ay1 + 10),
               lab, font=tlf, fill=MUT)

    # ---- 2) Dust vs Real donut ----
    p2 = (498, top, 760, bottom)
    _panel(d, *p2, title="DUST vs REAL")
    dcx, dcy = (p2[0] + p2[2]) // 2, (p2[1] + p2[3]) // 2 + 8
    drr, ring = 82, 30
    total = max(n_dust + n_real, 1)
    ang_real = 360 * n_real / total
    d.arc([dcx - drr, dcy - drr, dcx + drr, dcy + drr], -90 + ang_real, 270,
          fill=SLATE, width=ring)
    d.arc([dcx - drr, dcy - drr, dcx + drr, dcy + drr], -90, -90 + ang_real,
          fill=GREEN, width=ring)
    rp = f"{n_real/total*100:.0f}%"
    rf = _font(34, True)
    d.text((dcx - d.textlength(rp, font=rf) / 2, dcy - 30), rp, font=rf,
           fill=GREEN)
    sub = "real"
    sbf = _font(14)
    d.text((dcx - d.textlength(sub, font=sbf) / 2, dcy + 10), sub, font=sbf,
           fill=MUT)
    # legend centered
    lgf = _font(14, True)
    t1, t2 = f"Real {_fmt_cnt(n_real)}", f"Dust {_fmt_cnt(n_dust)}"
    w1 = d.textlength(t1, font=lgf)
    w2 = d.textlength(t2, font=lgf)
    lg_total = 14 + 8 + w1 + 26 + 14 + 8 + w2
    lx = (p2[0] + p2[2]) / 2 - lg_total / 2
    ly = p2[3] - 34
    d.ellipse([lx, ly + 3, lx + 13, ly + 16], fill=GREEN)
    d.text((lx + 21, ly), t1, font=lgf, fill=TXT)
    lx2 = lx + 14 + 8 + w1 + 26
    d.ellipse([lx2, ly + 3, lx2 + 13, ly + 16], fill=SLATE)
    d.text((lx2 + 21, ly), t2, font=lgf, fill=TXT)

    # ---- 3) Holders day-by-day ----
    p3 = (772, top, W - 40, bottom)
    delta_txt = ""
    if hist_holders and len(hist_holders) >= 2:
        delta = hist_holders[-1] - hist_holders[-2]
        delta_txt = f"{delta:+,}"
        delta_col = GREEN if delta >= 0 else RED
    _panel(d, *p3, title="HOLDERS DAY-BY-DAY")
    if delta_txt:
        dtf = _font(16, True)
        d.text((p3[2] - 18 - d.textlength(delta_txt, font=dtf), p3[1] + 13),
               delta_txt, font=dtf, fill=delta_col)
    gx0, gy0 = p3[0] + 40, p3[1] + 82
    gx1, gy1 = p3[2] - 34, p3[3] - 56
    if hist_holders and len(hist_holders) >= 2:
        lo, hi = min(hist_holders), max(hist_holders)
        span = (hi - lo) or 1
        # gridlines
        glf = _font(11)
        for g in range(3):
            gy = gy0 + (gy1 - gy0) * g / 2
            gval = hi - span * g / 2
            d.line([(gx0, gy), (gx1, gy)], fill=(34, 43, 60), width=1)
            d.text((gx0 - 6 - d.textlength(_fmt_cnt(int(gval)), font=glf),
                    gy - 6), _fmt_cnt(int(gval)), font=glf, fill=MUT)
        pts = []
        for i, v in enumerate(hist_holders):
            px = gx0 + (gx1 - gx0) * i / (len(hist_holders) - 1)
            py = gy1 - (gy1 - gy0) * (v - lo) / span
            pts.append((px, py))
        # area fill with alpha
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        od.polygon(pts + [(gx1, gy1), (gx0, gy1)], fill=(56, 189, 248, 45))
        img_rgba = Image.alpha_composite(img.convert("RGBA"), overlay)
        img.paste(img_rgba.convert("RGB"), (0, 0))
        d = ImageDraw.Draw(img)
        d.line(pts, fill=BLUE, width=4, joint="curve")
        vf2 = _font(13, True)
        for i, ((px, py), v) in enumerate(zip(pts, hist_holders)):
            d.ellipse([px - 5, py - 5, px + 5, py + 5], fill=BLUE,
                      outline=(10, 13, 20), width=2)
            vt = _fmt_cnt(v)
            vw = d.textlength(vt, font=vf2)
            # place label to the side of the point to avoid axis labels
            if px + 12 + vw <= gx1:
                vx = px + 12
            else:
                vx = px - vw - 12
            vy = max(py - 20, gy0 - 16)
            d.text((vx, vy), vt, font=vf2, fill=TXT)
        df2 = _font(12)
        for (px, py), dt in zip(pts, hist_dates):
            lbl = dt[5:]
            lx3 = min(max(px - d.textlength(lbl, font=df2) / 2, gx0 - 16),
                      gx1 - d.textlength(lbl, font=df2) + 16)
            d.text((lx3, gy1 + 12), lbl, font=df2, fill=MUT)
    else:
        ph = "history builds up daily…"
        d.text(((gx0 + gx1) / 2 - d.textlength(ph, font=_font(15)) / 2,
                (gy0 + gy1) / 2), ph, font=_font(15), fill=MUT)

    # ============================ FOOTER =====================================
    fy0, fy1 = 606, 650
    _panel(d, 40, fy0, W - 40, fy1, r=12)
    ff = _font(15, True)
    fx = 62
    bs = buys24 / sells24 if sells24 else float("inf")
    bs_txt = f"{bs:.2f}" if sells24 else "∞"
    segments = [
        ("24H", MUT), (f"Buys {buys24:,}", GREEN),
        (f"Sells {sells24:,}", RED),
        (f"B/S {bs_txt}", GREEN if bs >= 1 else RED),
    ]
    if cluster_txt:
        segments.append(("|", PANEL_LINE))
        segments.append((cluster_txt, TXT))
    for t, c in segments:
        d.text((fx, fy0 + 12), t, font=ff, fill=c)
        fx += d.textlength(t, font=ff) + 26
    brand = "Wallet Depth by Threshold"
    bf = _font(13)
    d.text((W - 62 - d.textlength(brand, font=bf), fy0 + 14), brand,
           font=bf, fill=MUT)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
