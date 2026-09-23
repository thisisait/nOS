#!/usr/bin/env python3
"""gen-invoice-images — render the consulting-firm fixture invoices as JPEG images
in varied layouts + fonts, so the vision pipeline has realistic image intake whose
DATA MATCHES the seeded party spine (so extraction resolves + books end-to-end,
unlike arbitrary real-world PDFs).

Reads each state/fixtures/consulting-firm/<slug>.image.txt (the plain-text OCR
stand-in — its own `ponytail:` comment asks for exactly this swap) and renders an
invoice image reproducing its DISPLAYED values — including the planted BETA-001
discrepancy (image says 3600, ISDOC 3630), so the cross-check judge still has its
positive control in the image path.

Deterministic: layout + font are chosen by a stable hash of the document number,
so a re-run reproduces byte-comparable images (no wall-clock, no randomness). This
is a FIXTURE generator, dev-time; not wired into a converge.

  tools/gen-invoice-images.py                         # -> <fixture>/images/*.jpg
  tools/gen-invoice-images.py --out /tmp/inv --dpi 150
  tools/gen-invoice-images.py --only inv-beta-002 --degrade crumple,shadow \
      --seed 7 --suffix                               # a degraded carry of the SAME data

ponytail: TTF fonts are resolved from a candidate list (macOS Supplemental +
common Linux paths); if none are found it falls back to PIL's bitmap font (ugly,
no diacritics) — install DejaVu/Liberation where this runs if that bites.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import pathlib
import random
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from invoice_fixture import parse_image_txt  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[1]
FIXTURE = REPO / "state" / "fixtures" / "consulting-firm"

# Candidate font families (regular, bold) — first that exists on this host wins a
# slot. Order gives variety; the per-invoice pick indexes into the resolved list.
FONT_CANDIDATES = [
    ("Arial", ["/System/Library/Fonts/Supplemental/Arial.ttf",
               "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
               "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
              ["/System/Library/Fonts/Supplemental/Arial Bold.ttf",
               "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
               "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]),
    ("Times", ["/System/Library/Fonts/Supplemental/Times New Roman.ttf",
               "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
               "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"],
              ["/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
               "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
               "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"]),
    ("Georgia", ["/System/Library/Fonts/Supplemental/Georgia.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"],
                ["/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"]),
    ("Verdana", ["/System/Library/Fonts/Supplemental/Verdana.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
                ["/System/Library/Fonts/Supplemental/Verdana Bold.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]),
    ("Courier", ["/System/Library/Fonts/Supplemental/Courier New.ttf",
                 "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"],
                ["/System/Library/Fonts/Supplemental/Courier New Bold.ttf",
                 "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"]),
]


def _first_existing(paths: list[str]) -> str | None:
    for p in paths:
        if pathlib.Path(p).exists():
            return p
    return None


def resolve_fonts() -> list[tuple[str, str, str]]:
    """(name, regular_path, bold_path) for every family whose regular face exists
    on this host — the palette the per-invoice picker indexes into."""
    out = []
    for name, reg, bold in FONT_CANDIDATES:
        r = _first_existing(reg)
        if r:
            out.append((name, r, _first_existing(bold) or r))
    return out


def _pick(doc_id: str, n: int) -> int:
    """Stable index in [0,n) from the doc id — deterministic layout/font choice."""
    return int(hashlib.sha1(doc_id.encode()).hexdigest(), 16) % n


def _money(v: float, currency: str) -> str:
    return f"{v:,.2f} {currency}".replace(",", " ")


def render(rec: dict, fonts: list, dpi: int) -> Image.Image:
    """Three layouts (chosen by hash): totals-bottom, totals-top-right, compact.
    Each draws the same fields differently — position of the totals box, the party
    blocks, and the label style vary, so the VLM meets real layout diversity."""
    scale = dpi / 150.0
    W, H = int(1240 * scale), int(1754 * scale)   # ~A4 at dpi
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    name, reg_path, bold_path = fonts[_pick(rec["id"] + "-font", len(fonts))]

    def F(size, bold=False):
        return ImageFont.truetype(bold_path if bold else reg_path, int(size * scale))

    layout = _pick(rec["id"] + "-layout", 3)
    m = int(70 * scale)                            # margin
    ink, faint = (20, 20, 20), (110, 110, 110)

    def parties(y):
        d.text((m, y), "DODAVATEL", font=F(11), fill=faint)
        d.text((m, y + 18 * scale), rec.get("seller_name", "?"), font=F(15, True), fill=ink)
        d.text((m, y + 40 * scale), f"IČO {rec.get('seller_ico', '?')}", font=F(13), fill=ink)
        d.text((W // 2 + m // 2, y), "ODBĚRATEL", font=F(11), fill=faint)
        d.text((W // 2 + m // 2, y + 18 * scale), rec.get("buyer_name", "?"), font=F(15, True), fill=ink)
        d.text((W // 2 + m // 2, y + 40 * scale), f"IČO {rec.get('buyer_ico', '?')}", font=F(13), fill=ink)
        return y + 80 * scale

    def totals(x, y, align_right=False):
        rows = [("Sazba", "Základ", "DPH")] + \
            [(f"{r['rate']} %", _money(r["base"], ""), _money(r["vat"], "")) for r in rec["rates"]]
        for i, (a, b, c) in enumerate(rows):
            f = F(12, i == 0)
            line = f"{a:<8}{b:>16}{c:>14}"
            d.text((x, y + i * 26 * scale), line, font=f, fill=ink if i else faint)
        yy = y + (len(rows) + 0.5) * 26 * scale
        d.line([(x, yy), (x + 380 * scale, yy)], fill=faint, width=max(1, int(scale)))
        d.text((x, yy + 8 * scale), "Částka k úhradě", font=F(13), fill=faint)
        d.text((x, yy + 30 * scale), _money(rec["payable"], rec.get("currency", "CZK")),
               font=F(20, True), fill=ink)

    def meta(x, y):
        for i, (lbl, val) in enumerate([("Datum vystavení", rec.get("issue", "")),
                                        ("Datum splatnosti", rec.get("due", "")),
                                        ("Měna", rec.get("currency", ""))]):
            d.text((x, y + i * 24 * scale), f"{lbl}:", font=F(12), fill=faint)
            d.text((x + 160 * scale, y + i * 24 * scale), str(val), font=F(12, True), fill=ink)

    # header (common)
    d.text((m, m), "FAKTURA", font=F(30, True), fill=ink)
    d.text((m, m + 42 * scale), f"— daňový doklad č. {rec['id']}", font=F(14), fill=faint)

    if layout == 0:                                # totals at the bottom
        meta(m, m + 90 * scale)
        y = parties(m + 190 * scale)
        totals(m, y + 40 * scale)
    elif layout == 1:                              # totals top-right, parties below
        meta(m, m + 90 * scale)
        totals(W - 470 * scale, m + 90 * scale)
        parties(m + 260 * scale)
    else:                                          # compact
        meta(W - 420 * scale, m)
        y = parties(m + 110 * scale)
        totals(m, y + 20 * scale)
    return img


# ── degradation (pipeline-exercise unit, 2026-09-23) ─────────────────────────
# A degraded render carries the SAME DATA — only worse. That is the whole point:
# the ground truth stays the .image.txt the clean render used, so the code oracle
# can still score a crumpled, stained, 150-dpi photo of the same invoice.
#
# Deterministic in (doc id, profile list, seed): a cycle that fails is
# re-renderable from its record alone. PIL only — no new dependency.
#: Applied in this order whatever order the caller lists them: you crumple the
#: paper, THEN light it, THEN photograph it. Reversing that looks like a filter
#: stack rather than a document.
DEGRADE_ORDER = ("crumple", "skew", "shadow", "stains", "lowres", "jpeg")
DEGRADE_PROFILES = ("clean",) + DEGRADE_ORDER + ("combo",)


def _rng(doc_id: str, profile: str, seed: int) -> random.Random:
    return random.Random(f"{doc_id}|{profile}|{seed}")


def _crumple(img, r):
    """Mesh warp over a grid, plus faint fold lines. Offsets stay small — a fold
    that displaces a glyph by 20px is not a crumpled invoice, it is a shredded one."""
    W, H = img.size
    gx, gy = 6, 8
    jitter = max(2, int(min(W, H) * 0.006))
    mesh = []
    for i in range(gx):
        for j in range(gy):
            x0, x1 = W * i // gx, W * (i + 1) // gx
            y0, y1 = H * j // gy, H * (j + 1) // gy
            d = [r.randint(-jitter, jitter) for _ in range(8)]
            mesh.append(((x0, y0, x1, y1),
                         (x0 + d[0], y0 + d[1], x0 + d[2], y1 + d[3],
                          x1 + d[4], y1 + d[5], x1 + d[6], y0 + d[7])))
    img = img.transform(img.size, Image.MESH, mesh, Image.BILINEAR, fillcolor="white")
    fold = Image.new("L", img.size, 0)
    fd = ImageDraw.Draw(fold)
    for _ in range(r.randint(2, 4)):
        y = r.randint(int(H * 0.1), int(H * 0.9))
        fd.line([(0, y + r.randint(-8, 8)), (W, y + r.randint(-8, 8))],
                fill=r.randint(18, 34), width=max(2, H // 400))
    fold = fold.filter(ImageFilter.GaussianBlur(radius=max(2, H // 300)))
    return Image.composite(Image.new("RGB", img.size, (90, 90, 90)), img, fold)


def _shadow(img, r):
    """A hand holding a phone casts a gradient, not a uniform dim."""
    W, H = img.size
    horizontal = r.random() < 0.5
    span = W if horizontal else H
    # Full 0..255 ramp, then blend — a ramp quantised to the darkness level
    # itself bands visibly at A4 size (measured on the first render).
    ramp = Image.new("L", (span, 1))
    ramp.putdata([int(255 * k / max(1, span - 1)) for k in range(span)])
    if r.random() < 0.5:
        ramp = ramp.transpose(Image.FLIP_LEFT_RIGHT)
    grad = ramp.resize((W, H) if horizontal else (H, W))
    if not horizontal:
        grad = grad.transpose(Image.ROTATE_90)
    shaded = Image.composite(Image.new("RGB", (W, H), (35, 35, 40)), img, grad)
    return Image.blend(img, shaded, r.uniform(0.22, 0.40))


def _stains(img, r):
    W, H = img.size
    over = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(over)
    tones = [(120, 80, 40), (90, 60, 30), (40, 40, 90)]
    for _ in range(r.randint(2, 5)):
        cx, cy = r.randint(0, W), r.randint(0, H)
        rx, ry = r.randint(W // 20, W // 7), r.randint(H // 25, H // 9)
        od.ellipse([cx - rx, cy - ry, cx + rx, cy + ry],
                   fill=(*r.choice(tones), r.randint(28, 62)))
    over = over.filter(ImageFilter.GaussianBlur(radius=max(2, W // 250)))
    return Image.alpha_composite(img.convert("RGBA"), over).convert("RGB")


def _lowres(img, r):
    f = r.uniform(0.40, 0.60)
    small = img.resize((max(1, int(img.width * f)), max(1, int(img.height * f))), Image.BILINEAR)
    return small.resize(img.size, Image.BILINEAR)


def _jpeg(img, r):
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=r.randint(25, 40))
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def _skew(img, r):
    return img.rotate(r.uniform(-4.0, 4.0), resample=Image.BILINEAR, fillcolor="white")


_DEGRADERS = {"crumple": _crumple, "skew": _skew, "shadow": _shadow,
              "stains": _stains, "lowres": _lowres, "jpeg": _jpeg}


def degrade(img, profiles, doc_id: str, seed: int):
    """Apply the named profiles in DEGRADE_ORDER. 'clean' is a no-op (the control
    every batch carries); 'combo' expands to 2-3 of the real ones."""
    wanted = set()
    for p in profiles:
        if p == "clean":
            continue
        if p == "combo":
            wanted |= set(_rng(doc_id, "combo", seed).sample(list(DEGRADE_ORDER),
                                                             _rng(doc_id, "combo-n", seed).randint(2, 3)))
        elif p in _DEGRADERS:
            wanted.add(p)
        else:
            raise ValueError(f"unknown degradation profile {p!r} — have {DEGRADE_PROFILES}")
    for name in DEGRADE_ORDER:
        if name in wanted:
            img = _DEGRADERS[name](img, _rng(doc_id, name, seed))
    return img


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", default=str(FIXTURE), help="fixture dir with *.image.txt")
    ap.add_argument("--out", default=str(FIXTURE / "images"), help="output dir for *.jpg")
    ap.add_argument("--dpi", type=int, default=150)
    ap.add_argument("--degrade", default="clean",
                    help=f"comma-separated: {', '.join(DEGRADE_PROFILES)} (data is preserved; "
                         "only the carrying is made worse)")
    ap.add_argument("--seed", type=int, default=0, help="degradation seed (re-render a failing cycle)")
    ap.add_argument("--only", help="render just this fixture slug")
    ap.add_argument("--suffix", action="store_true",
                    help="name the file <slug>.<profiles>.<seed>.jpg instead of overwriting the clean render")
    args = ap.parse_args()
    profiles = [p.strip() for p in args.degrade.split(",") if p.strip()]
    unknown = [p for p in profiles if p not in DEGRADE_PROFILES]
    if unknown:
        print(f"REFUSING: unknown degradation profile(s) {unknown} — have {list(DEGRADE_PROFILES)}",
              file=sys.stderr)
        return 1

    fonts = resolve_fonts()
    if not fonts:
        print("WARN: no TTF fonts found — falling back to PIL default (no diacritics)", file=sys.stderr)
        fonts = [("default", "", "")]
    src, out = pathlib.Path(args.src), pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    txts = sorted(src.glob("*.image.txt"))
    if not txts:
        print(f"REFUSING: no *.image.txt in {src}", file=sys.stderr)
        return 1
    for t in txts:
        rec = parse_image_txt(t.read_text(encoding="utf-8"))
        if "id" not in rec:
            print(f"skip {t.name}: no Doklad c.", file=sys.stderr)
            continue
        slug = t.name.replace(".image.txt", "")
        if args.only and slug != args.only:
            continue
        img = degrade(render(rec, fonts, args.dpi), profiles, rec["id"], args.seed)
        tag = f".{'-'.join(profiles)}.{args.seed}" if args.suffix else ""
        dst = out / f"{slug}{tag}.jpg"
        img.save(dst, "JPEG", quality=88)
        print(f"{dst.name}  ({img.size[0]}x{img.size[1]}, {rec['id']}, payable {rec['payable']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
