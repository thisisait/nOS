"""The winged engine — public document -> static SVG + HTML.

Rendering technique, decided against the alternatives:

  * files/anatomy/face/src/lib/anatomy/graphLayout.ts is a layered-DAG
    layout for the INTERNAL graph (~60 visible nodes, rank/barycenter).
    The public surface has 13 designed organs, not 207 measured nodes —
    a designed emblem, not a data layout. Reusing it would couple the
    public page to the internal graph shape for no gain.
  * d3-force (docs/idea/17's recommendation for the face) buys crossing
    minimisation at the cost of a runtime JS dependency and a layout
    that moves when the data does. The apex page must be offline, near
    dependency-free, and STILL — structure may move only when a human
    re-rules it.
  * So: build-time Python, zero new dependencies, deterministic output.
    All "motion" is CSS animation seeded from the ruling version — a
    build-time constant, never live state (ruling decision D3).

Every random-looking number is sha256-derived from the ruling name +
version, so the same ruling renders byte-identical files forever.
"""

from __future__ import annotations

import hashlib
import math
from string import Template

# ---------------------------------------------------------------------------
# deterministic "randomness" — seeded by the ruling, never by content/clock
# ---------------------------------------------------------------------------

def _rand(seed: str, *parts, lo: float = 0.0, hi: float = 1.0) -> float:
    key = ":".join([seed, *map(str, parts)]).encode()
    n = int.from_bytes(hashlib.sha256(key).digest()[:8], "big")
    return lo + (hi - lo) * (n / float(1 << 64))


# ---------------------------------------------------------------------------
# geometry — a core column and two limbs, sweeping up and out: the engine
# ---------------------------------------------------------------------------

W, H = 800, 880
CENTER = (W / 2, 430)

_CORE_Y = [150, 296, 442, 588, 716]
_LEFT = [(168, 172), (102, 350), (146, 528), (252, 664)]
_RIGHT = [(W - x, y) for (x, y) in _LEFT]


def _organ_pos(organ: dict) -> tuple[float, float]:
    idx = organ["order"] - 1
    if organ["limb"] == "core":
        return (W / 2, _CORE_Y[idx])
    if organ["limb"] == "left":
        return _LEFT[idx]
    return _RIGHT[idx]


def _constellation(seed: str, organ: dict) -> str:
    """One organ: a glow, a ring of stars joined into an abstract polygon,
    a few chords, and a small-caps label. Star positions are seeded by the
    organ id and index only — never by which internal node an atom is."""
    oid = organ["id"]
    cx, cy = _organ_pos(organ)
    n = len(organ["atoms"])
    r = 24 + 7.5 * math.sqrt(n)

    pts = []
    for i in range(n):
        ang = (2 * math.pi * i / n) + _rand(seed, oid, i, "a", lo=-0.3, hi=0.3)
        rad = r * _rand(seed, oid, i, "r", lo=0.55, hi=0.98)
        pts.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    pts.sort(key=lambda p: math.atan2(p[1] - cy, p[0] - cx))

    poly = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in pts) + " Z" if n >= 3 else ""
    chords = []
    if n >= 5:
        step = 2 if n < 8 else 3
        for i in range(0, n, 3):
            a, b = pts[i], pts[(i + step) % n]
            chords.append(f"M {a[0]:.1f} {a[1]:.1f} L {b[0]:.1f} {b[1]:.1f}")

    stars = "\n      ".join(
        f'<circle class="star" cx="{x:.1f}" cy="{y:.1f}" '
        f'r="{_rand(seed, oid, i, "s", lo=1.4, hi=2.6):.1f}" '
        f'style="--tw:{_rand(seed, oid, i, "t", lo=0, hi=5):.2f}s"/>'
        for i, (x, y) in enumerate(pts)
    )

    dur = _rand(seed, oid, "dur", lo=5.0, hi=8.0)
    delay = _rand(seed, oid, "ph", lo=0.0, hi=4.0)
    label_y = cy + r + 16

    return f'''
    <g class="organ" id="organ-{oid}" data-organ="{oid}" tabindex="0" role="button"
       aria-label="{organ['title']}. {organ['tells']} {n} parts."
       style="--dur:{dur:.2f}s; --ph:{delay:.2f}s">
      <circle class="halo" cx="{cx:.1f}" cy="{cy:.1f}" r="{r + 10:.1f}"/>
      {f'<path class="poly" d="{poly}"/>' if poly else ''}
      {"".join(f'<path class="chord" d="{c}"/>' for c in chords)}
      {stars}
      <text class="organ-label" x="{cx:.1f}" y="{label_y:.1f}" text-anchor="middle">{organ['title'].upper()}</text>
    </g>'''


def _vein(seed: str, doc_organs: dict, vein: dict) -> str:
    a, b = vein["between"]
    ax, ay = _organ_pos(doc_organs[a])
    bx, by = _organ_pos(doc_organs[b])
    mx, my = (ax + bx) / 2, (ay + by) / 2
    # pull toward the engine's heart, plus a seeded perpendicular sway
    px, py = mx + (CENTER[0] - mx) * 0.22, my + (CENTER[1] - my) * 0.22
    dx, dy = bx - ax, by - ay
    norm = math.hypot(dx, dy) or 1.0
    sway = _rand(seed, a, b, "sw", lo=-26, hi=26)
    px += -dy / norm * sway
    py += dx / norm * sway
    drift = _rand(seed, a, b, "dr", lo=14.0, hi=26.0)
    return (
        f'<path class="vein" data-a="{a}" data-b="{b}" '
        f'style="--drift:{drift:.1f}s" '
        f'd="M {ax:.1f} {ay:.1f} Q {px:.1f} {py:.1f} {bx:.1f} {by:.1f}"/>'
    )


def _feathers(seed: str, organ: dict) -> str:
    """Faint strokes sweeping outward from limb organs — the wings."""
    if organ["limb"] == "core":
        return ""
    sign = -1 if organ["limb"] == "left" else 1
    cx, cy = _organ_pos(organ)
    out = []
    for i in range(3):
        ln = _rand(seed, organ["id"], i, "fl", lo=52, hi=118)
        droop = _rand(seed, organ["id"], i, "fd", lo=8, hi=44)
        x1 = cx + sign * (28 + 12 * i)
        y1 = cy - 6 + 10 * i
        x2 = x1 + sign * ln
        y2 = y1 + droop
        out.append(
            f'<path class="feather" d="M {x1:.1f} {y1:.1f} '
            f'Q {x1 + sign * ln * 0.6:.1f} {y1 + droop * 0.2:.1f} {x2:.1f} {y2:.1f}"/>'
        )
    return "\n    ".join(out)


def _wing_silhouette(seed: str, sign: int) -> str:
    """Four long swept arcs per side — the wing itself, drawn behind the
    constellations: shoulder near the spine, a low bow, a rising tip."""
    sx, sy = W / 2 + sign * 54, 336
    arcs = []
    for k in range(4):
        span = 268 + 34 * k + _rand(seed, "sweep", sign, k, "sp", lo=-8, hi=8)
        tip_x = W / 2 + sign * span
        tip_y = 132 - 16 * k + _rand(seed, "sweep", sign, k, "ty", lo=-6, hi=6)
        c1x, c1y = W / 2 + sign * (150 + 20 * k), 470 + 14 * k
        c2x, c2y = W / 2 + sign * (span * 0.82), 300 - 10 * k
        arcs.append(
            f'<path class="sweep" style="--wo:{0.16 - 0.03 * k:.2f}" '
            f'd="M {sx:.1f} {sy + 10 * k:.1f} '
            f'C {c1x:.1f} {c1y:.1f} {c2x:.1f} {c2y:.1f} {tip_x:.1f} {tip_y:.1f}"/>'
        )
    return "\n    ".join(arcs)


def engine_svg(doc: dict, seed: str) -> str:
    organs = {o["id"]: o for o in doc["organs"]}
    veins = "\n    ".join(_vein(seed, organs, v) for v in doc["veins"])
    feathers = "\n    ".join(f for f in (_feathers(seed, o) for o in doc["organs"]) if f)
    bodies = "\n".join(_constellation(seed, o) for o in doc["organs"])
    spine_top, spine_bot = _CORE_Y[0], _CORE_Y[-1]
    return f'''<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="group"
     aria-label="The winged engine: {doc['counts']['organs']} organs, {doc['counts']['atoms']} parts, drawn as constellations.">
  <defs>
    <radialGradient id="heart" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#2A63A8" stop-opacity="0.16"/>
      <stop offset="100%" stop-color="#2A63A8" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <circle cx="{CENTER[0]}" cy="{CENTER[1]}" r="330" fill="url(#heart)"/>
  <g class="silhouette">
    {_wing_silhouette(seed, -1)}
    {_wing_silhouette(seed, 1)}
    <line class="spine-line" x1="{W / 2}" y1="{spine_top}" x2="{W / 2}" y2="{spine_bot}"/>
  </g>
  <g class="feathers">
    {feathers}
  </g>
  <g class="veins">
    {veins}
  </g>
  {bodies}
</svg>'''


# ---------------------------------------------------------------------------
# the page
# ---------------------------------------------------------------------------

_PAGE = Template('''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>This is AIT — the anatomy of an autonomous estate</title>
<meta name="description" content="Autonomous IT: a self-governing estate of $atoms open-source parts in $organs organs. Everything local, everything audited, everything yours.">
<link rel="stylesheet" href="assets/ait.css">
</head>
<body>
<div class="aurora" aria-hidden="true"></div>

<header class="masthead">
  <span class="wordmark">THIS&nbsp;IS&nbsp;<span class="chip-red">AIT</span></span>
  <span class="kicker">AUTONOMOUS&nbsp;IT</span>
</header>

<main>
  <section class="hero">
    <h1>A whole IT&nbsp;department,<br>on one machine you&nbsp;own.</h1>
    <p class="lede">This is the anatomy of an autonomous estate: <strong>$atoms parts</strong>
    in <strong>$organs organs</strong> — identity, memory, knowledge, senses and agents —
    every part free and open-source, every byte on hardware you control, every action
    audited. Touch an organ to see what lives there. The machine itself stays
    anonymous, by design.</p>
  </section>

  <figure class="engine">
$svg
    <figcaption class="dim">The winged engine. Structure may move; state may not —
    nothing on this page is live.</figcaption>
  </figure>

  <section class="organs" aria-label="The organs">
$cards
  </section>

  <section class="principles">
    <article class="tile"><h3>Yours</h3><p>All data stays on your machine. No cloud landlord, no rent on your own history.</p></article>
    <article class="tile"><h3>Open</h3><p>Free and open-source end to end. Every part replaceable, every licence readable.</p></article>
    <article class="tile"><h3>Accountable</h3><p>Every action lands in an append-only audit trail. Compliance is built in, not bolted on.</p></article>
    <article class="tile"><h3>Autonomous</h3><p>Agents do the night work — patching, checking, filing — behind gates that keep them honest.</p></article>
  </section>
</main>

<footer>
  <p><span class="wordmark-sm">THIS&nbsp;IS&nbsp;AIT</span> · the manifest lives at
  <a href="https://thisisait.eu">thisisait.eu</a></p>
  <p class="dim">This page is generated from a ruled public projection. It knows
  nothing live and names nothing it should not.</p>
</footer>

<script>
(function () {
  var all = document.querySelectorAll('[data-organ]');
  function set(id, on) {
    all.forEach(function (el) {
      if (el.getAttribute('data-organ') === id) el.classList.toggle('lit', on);
    });
  }
  all.forEach(function (el) {
    var id = el.getAttribute('data-organ');
    el.addEventListener('pointerenter', function () { set(id, true); });
    el.addEventListener('pointerleave', function () { set(id, false); });
    el.addEventListener('focus', function () { set(id, true); });
    el.addEventListener('blur', function () { set(id, false); });
  });
  document.querySelectorAll('g.organ').forEach(function (g) {
    var id = g.getAttribute('data-organ');
    function unfold() {
      var card = document.getElementById('card-' + id);
      if (!card) return;
      var d = card.querySelector('details');
      if (d) d.open = true;
      card.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    g.addEventListener('click', unfold);
    g.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); unfold(); }
    });
  });
})();
</script>
</body>
</html>
''')


def _card(organ: dict) -> str:
    atoms = organ["atoms"]
    lis = "\n        ".join(f"<li>{a['speaks']}</li>" for a in atoms)
    n = len(atoms)
    return f'''    <article class="card notch" data-organ="{organ['id']}" id="card-{organ['id']}">
      <h3>{organ['title']}</h3>
      <p class="tells">{organ['tells']}</p>
      <details>
        <summary>what lives here — {n} part{'s' if n != 1 else ''}</summary>
        <ul>
        {lis}
        </ul>
      </details>
    </article>'''


def page_html(doc: dict, seed: str) -> str:
    return _PAGE.substitute(
        atoms=doc["counts"]["atoms"],
        organs=doc["counts"]["organs"],
        svg=engine_svg(doc, seed),
        cards="\n".join(_card(o) for o in doc["organs"]),
    )
