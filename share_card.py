# -*- coding: utf-8 -*-
"""Generate a self-designed share card (PNG, 1200x675 — ideal for X posts)."""
import io
import math
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1200, 675
BG = (14, 17, 23)
PANEL = (22, 27, 36)
PANEL_LINE = (38, 45, 58)
TXT = (235, 238, 243)
MUT = (140, 150, 165)
GREEN = (34, 197, 94)
RED = (239, 68, 68)
YELLOW = (250, 204, 21)
BLUE = (56, 189, 248)
SLATE = (100, 116, 139)
BAR_COLORS = [(56, 189, 248), (74, 222, 128), (163, 230, 53), (250, 204, 21),
              (251, 146, 60), (248, 113, 113), (192, 132, 252)]


def _font(size: int, bold: bool = False):
    names = (["DejaVuSans-Bold.ttf"] if bold else ["DejaVuSans.ttf"])
    dirs = ["/usr/share/fonts/truetype/dejavu"]
    try:
        import matplotlib
        dirs.append(os.path.join(os.path.dirname(matplotlib.__file__),
                                 "mpl-data", "fonts", "ttf"))
    except Exception:
        pass
    for d in dirs:
        for n in names:
            p = os.path.join(d, n)
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


def _panel(d, x0, y0, x1, y1, r=14):
    d.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=PANEL,
                        outline=PANEL_LINE, width=1)


def _fmt_cnt(v):
    return f"{v/1000:.1f}K" if v >= 1000 else f"{v:,}"


def build_share_card(*, symbol, name, ca, score, score_label, holders,
                     holder_delta, n_real, n_dust, ratio_pct, real_mc_pct,
                     marketcap, liquidity_usd, liq_pct_mc, top10_pct,
                     tier_labels, tier_counts, hist_dates, hist_holders,
                     buys24, sells24, cluster_txt, verdict_ok) -> bytes:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # ---------- header ----------
    d.text((40, 28), f"${symbol}", font=_font(44, True), fill=TXT)
    sw = d.textlength(f"${symbol}", font=_font(44, True))
    d.text((48 + sw, 44), name[:28], font=_font(22), fill=MUT)
    d.text((40, 84), ca, font=_font(17), fill=MUT)

    # verdict pill (top right, left of score)
    pill_txt = "HOLDERS OK" if verdict_ok else "UNHEALTHY HOLDERS"
    pill_col = GREEN if verdict_ok else RED
    pf = _font(19, True)
    ptw = d.textlength(pill_txt, font=pf)
    px1 = W - 210
    d.rounded_rectangle([px1 - ptw - 36, 40, px1, 82], radius=21,
                        outline=pill_col, width=2)
    d.text((px1 - ptw - 18, 50), pill_txt, font=pf, fill=pill_col)

    # ---------- score donut (top-right) ----------
    sc = _score_color(score)
    cx, cy, rr = W - 105, 78, 58
    d.arc([cx - rr, cy - rr, cx + rr, cy + rr], 0, 360, fill=PANEL_LINE, width=11)
    d.arc([cx - rr, cy - rr, cx + rr, cy + rr], -90,
          -90 + int(360 * min(score, 100) / 100), fill=sc, width=11)
    sf = _font(40, True)
    d.text((cx - d.textlength(str(score), font=sf) / 2, cy - 30), str(score),
           font=sf, fill=sc)
    lf = _font(13, True)
    d.text((cx - d.textlength(score_label, font=lf) / 2, cy + 12), score_label,
           font=lf, fill=sc)

    # ---------- stat row ----------
    stats = [
        ("HOLDERS", f"{holders:,}",
         (f"{holder_delta:+,} vs yday" if holder_delta is not None else ""),
         GREEN if (holder_delta or 0) >= 0 else RED),
        ("REAL / DUST", f"{_fmt_cnt(n_real)} / {_fmt_cnt(n_dust)}",
         f"ratio {ratio_pct:.0f}%", GREEN if ratio_pct > 30 else RED),
        ("REAL % MC", f"{real_mc_pct:.1f}%", "of marketcap", BLUE),
        ("MARKETCAP", _fmt_usd(marketcap), "", TXT),
        ("LIQUIDITY", _fmt_usd(liquidity_usd), f"{liq_pct_mc:.1f}% MC", TXT),
        ("TOP-10", f"{top10_pct:.1f}%",
         "of supply", GREEN if top10_pct <= 30 else RED),
    ]
    x, y0, bw, bh, gap = 40, 122, 178, 92, 10
    for label, val, sub, col in stats:
        _panel(d, x, y0, x + bw, y0 + bh)
        d.text((x + 14, y0 + 12), label, font=_font(13, True), fill=MUT)
        vf = _font(26, True)
        d.text((x + 14, y0 + 34), val, font=vf, fill=TXT)
        if sub:
            d.text((x + 14, y0 + 66), sub, font=_font(14), fill=col)
        x += bw + gap

    # ---------- panels ----------
    top = 238
    bottom = H - 96
    # 1) wallet depth bars
    p1 = (40, top, 480, bottom)
    _panel(d, *p1)
    d.text((p1[0] + 16, p1[1] + 12), "WALLET DEPTH BY THRESHOLD",
           font=_font(15, True), fill=TXT)
    n = len(tier_counts)
    area_x0, area_y0 = p1[0] + 24, p1[1] + 52
    area_x1, area_y1 = p1[2] - 24, p1[3] - 46
    maxc = max(tier_counts) or 1
    bw2 = (area_x1 - area_x0) / n
    cf = _font(14, True)
    tf = _font(13)
    for i, (lab, cnt) in enumerate(zip(tier_labels, tier_counts)):
        bx0 = area_x0 + i * bw2 + 6
        bx1 = area_x0 + (i + 1) * bw2 - 6
        hh = (area_y1 - area_y0 - 26) * (cnt / maxc)
        by1 = area_y1
        by0 = by1 - max(hh, 3)
        d.rounded_rectangle([bx0, by0, bx1, by1], radius=4,
                            fill=BAR_COLORS[i % len(BAR_COLORS)])
        ct = f"{cnt:,}"
        d.text(((bx0 + bx1) / 2 - d.textlength(ct, font=cf) / 2, by0 - 22),
               ct, font=cf, fill=TXT)
        d.text(((bx0 + bx1) / 2 - d.textlength(lab, font=tf) / 2, area_y1 + 8),
               lab, font=tf, fill=MUT)

    # 2) dust vs real donut
    p2 = (500, top, 780, bottom)
    _panel(d, *p2)
    d.text((p2[0] + 16, p2[1] + 12), "DUST vs REAL", font=_font(15, True),
           fill=TXT)
    dcx, dcy = (p2[0] + p2[2]) // 2, (p2[1] + p2[3]) // 2 + 14
    drr = 86
    total = max(n_dust + n_real, 1)
    ang_real = 360 * n_real / total
    d.arc([dcx - drr, dcy - drr, dcx + drr, dcy + drr], -90, -90 + ang_real,
          fill=GREEN, width=30)
    d.arc([dcx - drr, dcy - drr, dcx + drr, dcy + drr], -90 + ang_real, 270,
          fill=SLATE, width=30)
    rp = f"{n_real/total*100:.0f}%"
    rf = _font(34, True)
    d.text((dcx - d.textlength(rp, font=rf) / 2, dcy - 32), rp, font=rf,
           fill=GREEN)
    sub = "real holders"
    sbf = _font(14)
    d.text((dcx - d.textlength(sub, font=sbf) / 2, dcy + 8), sub, font=sbf,
           fill=MUT)
    # legend
    ly = p2[3] - 36
    d.ellipse([p2[0] + 24, ly + 3, p2[0] + 36, ly + 15], fill=GREEN)
    d.text((p2[0] + 42, ly), f"Real {n_real:,}", font=_font(14), fill=TXT)
    d.ellipse([p2[0] + 150, ly + 3, p2[0] + 162, ly + 15], fill=SLATE)
    d.text((p2[0] + 168, ly), f"Dust {n_dust:,}", font=_font(14), fill=TXT)

    # 3) holders trend
    p3 = (800, top, W - 40, bottom)
    _panel(d, *p3)
    d.text((p3[0] + 16, p3[1] + 12), "HOLDERS DAY-BY-DAY",
           font=_font(15, True), fill=TXT)
    gx0, gy0 = p3[0] + 30, p3[1] + 58
    gx1, gy1 = p3[2] - 30, p3[3] - 76
    if hist_holders and len(hist_holders) >= 2:
        lo, hi = min(hist_holders), max(hist_holders)
        span = (hi - lo) or 1
        pts = []
        for i, v in enumerate(hist_holders):
            px = gx0 + (gx1 - gx0) * i / (len(hist_holders) - 1)
            py = gy1 - (gy1 - gy0) * (v - lo) / span
            pts.append((px, py))
        # area fill
        poly = pts + [(gx1, gy1), (gx0, gy1)]
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        od.polygon(poly, fill=(56, 189, 248, 40))
        img.paste(Image.alpha_composite(img.convert("RGBA"), overlay)
                  .convert("RGB"), (0, 0))
        d = ImageDraw.Draw(img)
        d.line(pts, fill=BLUE, width=4, joint="curve")
        vf2 = _font(14, True)
        for i, ((px, py), v) in enumerate(zip(pts, hist_holders)):
            d.ellipse([px - 5, py - 5, px + 5, py + 5], fill=BLUE, outline=BG,
                      width=2)
            vt = f"{v:,}"
            d.text((min(max(px - d.textlength(vt, font=vf2) / 2, gx0 - 10),
                        gx1 - 40), py - 26), vt, font=vf2, fill=TXT)
        df2 = _font(12)
        for (px, py), dt in zip(pts, hist_dates):
            lbl = dt[5:]
            d.text((min(max(px - d.textlength(lbl, font=df2) / 2, gx0 - 12),
                        gx1 - 30), gy1 + 10), lbl, font=df2, fill=MUT)
        delta = hist_holders[-1] - hist_holders[-2]
        dc = GREEN if delta >= 0 else RED
        dt2 = f"{delta:+,} vs previous day"
        d.text((p3[0] + 16, p3[3] - 32), dt2, font=_font(15, True), fill=dc)
    else:
        d.text((gx0, (gy0 + gy1) // 2), "history builds up daily…",
               font=_font(15), fill=MUT)

    # ---------- footer strip ----------
    fy = H - 78
    _panel(d, 40, fy, W - 40, H - 26, r=12)
    bs = buys24 / sells24 if sells24 else float("inf")
    bs_txt = f"{bs:.2f}" if sells24 else "∞"
    parts = [
        (f"24h  Buys {buys24:,}", GREEN),
        (f"Sells {sells24:,}", RED),
        (f"B/S {bs_txt}", GREEN if bs >= 1 else RED),
        (cluster_txt, TXT),
    ]
    fx = 60
    ff = _font(16, True)
    for t, c in parts:
        if not t:
            continue
        d.text((fx, fy + 16), t, font=ff, fill=c)
        fx += d.textlength(t, font=ff) + 34
    brand = "Wallet Depth by Threshold"
    bf = _font(14)
    d.text((W - 60 - d.textlength(brand, font=bf), fy + 18), brand, font=bf,
           fill=MUT)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
