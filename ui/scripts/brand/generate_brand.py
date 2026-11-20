"""Generate the NIMBORA brand assets (logo, favicon, social image, illustrations).

Everything is vector-first and reproducible:

    python ui/scripts/brand/generate_brand.py      # needs fonttools, brotli, rsvg-convert, ImageMagick

The wordmark is set in Space Grotesk Bold (SIL OFL, shipped by
@fontsource-variable/space-grotesk) and converted to outlines, so the SVG logos
render identically everywhere without the font installed.
"""

from __future__ import annotations

import math
import subprocess
import tempfile
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

UI = Path(__file__).resolve().parents[2]
PUBLIC = UI / "public"
BRAND = PUBLIC / "brand"
APP = UI / "src" / "app"
FONT = (
    UI
    / "node_modules/@fontsource-variable/space-grotesk/files/space-grotesk-latin-wght-normal.woff2"
)

# ----------------------------------------------------------------- palette
VOID = "#060814"  # deep space background
SURFACE = "#0D1124"
INK = "#0B0F24"  # text on light backgrounds
CYAN = "#22E5FF"  # Nimbus cyan
VIOLET = "#7C5CFF"  # Aurora violet
MAGENTA = "#FF4FD8"  # Pulse magenta (sparingly)
MINT = "#34F5C5"
WHITE = "#F5F7FF"


def gradient_defs(prefix: str) -> str:
    return f"""
  <defs>
    <linearGradient id="{prefix}-ring" x1="8" y1="8" x2="56" y2="56" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="{CYAN}"/>
      <stop offset="0.55" stop-color="{VIOLET}"/>
      <stop offset="1" stop-color="{MAGENTA}"/>
    </linearGradient>
    <linearGradient id="{prefix}-bars" x1="32" y1="14" x2="32" y2="50" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="{CYAN}"/>
      <stop offset="1" stop-color="{VIOLET}"/>
    </linearGradient>
    <radialGradient id="{prefix}-dot" cx="0.5" cy="0.5" r="0.5">
      <stop offset="0" stop-color="#FFFFFF"/>
      <stop offset="0.45" stop-color="{MAGENTA}"/>
      <stop offset="1" stop-color="{MAGENTA}" stop-opacity="0"/>
    </radialGradient>
  </defs>"""


def mark_shapes(prefix: str, bars_fill: str | None = None, ring: str | None = None) -> str:
    """The NIMBORA mark on a 64×64 grid: an open orbit (the nimbus) around a
    voice waveform, with a satellite dot — the AI agent — at the orbit's end."""
    cx = cy = 32.0
    r = 25.0
    start, end = math.radians(-62), math.radians(-62 + 300)  # 300° arc, gap top-right

    def pt(a: float) -> tuple[float, float]:
        return cx + r * math.cos(a), cy + r * math.sin(a)

    (x1, y1), (x2, y2) = pt(start), pt(end)
    arc = f"M{x1:.2f} {y1:.2f} A{r} {r} 0 1 1 {x2:.2f} {y2:.2f}"
    dx, dy = pt(math.radians(-62 - 18))
    heights = [10, 22, 30, 20, 11]
    xs = [19, 25.5, 32, 38.5, 45]
    bars = "".join(
        f'<rect x="{x - 2.2:.1f}" y="{cy - h / 2:.1f}" width="4.4" height="{h}" rx="2.2"/>'
        for x, h in zip(xs, heights)
    )
    ring_stroke = ring or f"url(#{prefix}-ring)"
    fill = bars_fill or f"url(#{prefix}-bars)"
    return f"""
  <path d="{arc}" fill="none" stroke="{ring_stroke}" stroke-width="5" stroke-linecap="round"/>
  <g fill="{fill}">{bars}</g>
  <circle cx="{dx:.2f}" cy="{dy:.2f}" r="7" fill="url(#{prefix}-dot)" opacity="{0.9 if not ring else 0}"/>
  <circle cx="{dx:.2f}" cy="{dy:.2f}" r="3.2" fill="{ring or MAGENTA}"/>"""


def wordmark_paths(text: str, size: float, tracking: float) -> tuple[str, float]:
    """Outline ``text`` in Space Grotesk Bold. Returns (path data, width)."""
    font = TTFont(str(FONT))
    font = instantiateVariableFont(font, {"wght": 700})
    glyphs = font.getGlyphSet()
    cmap = font.getBestCmap()
    upm = font["head"].unitsPerEm
    scale = size / upm
    ascent = font["hhea"].ascent
    pen = SVGPathPen(glyphs)
    x = 0.0
    for i, char in enumerate(text):
        name = cmap[ord(char)]
        tpen = TransformPen(pen, (scale, 0, 0, -scale, x, ascent * scale * 0.74))
        glyphs[name].draw(tpen)
        x += glyphs[name].width * scale
        if i < len(text) - 1:
            x += tracking
    return pen.getCommands(), x


def logo_svg(prefix: str, text_fill: str) -> str:
    size = 30
    path, width = wordmark_paths("NIMBORA", size, tracking=3.2)
    total = 64 + 14 + width + 4
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total:.0f} 64" fill="none" role="img" aria-label="NIMBORA">
  <title>NIMBORA</title>{gradient_defs(prefix)}{mark_shapes(prefix)}
  <path transform="translate(78 19)" d="{path}" fill="{text_fill}"/>
</svg>
"""


def mark_svg(prefix: str = "nm") -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" fill="none" role="img" aria-label="NIMBORA">
  <title>NIMBORA</title>{gradient_defs(prefix)}{mark_shapes(prefix)}
</svg>
"""


def mono_mark_svg(color: str) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" fill="none" role="img" aria-label="NIMBORA">
  <title>NIMBORA</title>{mark_shapes("mono", bars_fill=color, ring=color)}
</svg>
"""


def app_icon_svg() -> str:
    """Favicon / app icon: the mark on a deep-space rounded tile with a glow."""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" fill="none">{gradient_defs("ic")}
  <defs>
    <radialGradient id="ic-glow" cx="0.3" cy="0.2" r="0.9">
      <stop offset="0" stop-color="{VIOLET}" stop-opacity="0.55"/>
      <stop offset="1" stop-color="{VOID}" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="64" height="64" rx="15" fill="{VOID}"/>
  <rect width="64" height="64" rx="15" fill="url(#ic-glow)"/>
  <g transform="translate(5 5) scale(0.844)">{mark_shapes("ic")}</g>
</svg>
"""


def og_image_svg(logo_inner: str) -> str:
    """1200×630 social card."""
    stars = []
    seed = 7
    for _ in range(90):
        seed = (seed * 1103515245 + 12345) % 2**31
        x = seed % 1200
        seed = (seed * 1103515245 + 12345) % 2**31
        y = seed % 630
        seed = (seed * 1103515245 + 12345) % 2**31
        o = 0.15 + (seed % 60) / 100
        stars.append(f'<circle cx="{x}" cy="{y}" r="{1 if o < 0.5 else 1.4}" fill="#fff" opacity="{o:.2f}"/>')
    wave = []
    for i in range(64):
        h = 18 + 70 * abs(math.sin(i * 0.37) * math.cos(i * 0.11))
        wave.append(
            f'<rect x="{620 + i * 9}" y="{555 - h / 2:.1f}" width="4" height="{h:.1f}" rx="2" fill="url(#og-wave)" opacity="{0.35 + 0.6 * (i / 64):.2f}"/>'
        )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 630" width="1200" height="630">
  <defs>
    <radialGradient id="og-a" cx="0.82" cy="0.18" r="0.6">
      <stop offset="0" stop-color="{VIOLET}" stop-opacity="0.65"/>
      <stop offset="1" stop-color="{VOID}" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="og-b" cx="0.1" cy="0.95" r="0.55">
      <stop offset="0" stop-color="{CYAN}" stop-opacity="0.35"/>
      <stop offset="1" stop-color="{VOID}" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="og-wave" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="{CYAN}"/>
      <stop offset="1" stop-color="{MAGENTA}"/>
    </linearGradient>
    <linearGradient id="og-text" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="{CYAN}"/>
      <stop offset="0.6" stop-color="{VIOLET}"/>
      <stop offset="1" stop-color="{MAGENTA}"/>
    </linearGradient>
  </defs>
  <rect width="1200" height="630" fill="{VOID}"/>
  <rect width="1200" height="630" fill="url(#og-a)"/>
  <rect width="1200" height="630" fill="url(#og-b)"/>
  {''.join(stars)}
  <g transform="translate(860 40)" opacity="0.5">
    <circle cx="150" cy="150" r="140" fill="none" stroke="url(#og-text)" stroke-width="1.5" stroke-dasharray="2 10"/>
    <circle cx="150" cy="150" r="96" fill="none" stroke="url(#og-text)" stroke-width="1" opacity="0.6"/>
  </g>
  <g transform="translate(80 120) scale(1.6)">{logo_inner}</g>
  {''.join(wave)}
  <text x="84" y="330" font-family="Space Grotesk, Geist, sans-serif" font-size="54" font-weight="700" fill="{WHITE}">Le centre d'appels qui pense,</text>
  <text x="84" y="396" font-family="Space Grotesk, Geist, sans-serif" font-size="54" font-weight="700" fill="url(#og-text)">parle et décide.</text>
  <text x="86" y="470" font-family="Geist, sans-serif" font-size="24" fill="#AAB2D5">Agents vocaux IA · centre d'appels humain · IA souveraine</text>
</svg>
"""


def auth_hero_svg() -> str:
    """Illustration for the sign-in panel: concentric orbits, nodes (agents),
    a central voice core. Animated with SMIL so it moves even as an <img>."""
    nodes = []
    for i, (r, deg, color, dur) in enumerate(
        [(150, 20, CYAN, 26), (150, 200, VIOLET, 26), (210, 120, MAGENTA, 40), (210, 300, MINT, 40), (270, 60, CYAN, 60)]
    ):
        a = math.radians(deg)
        x, y = 300 + r * math.cos(a), 300 + r * math.sin(a)
        nodes.append(f"""
    <g>
      <animateTransform attributeName="transform" type="rotate" from="0 300 300" to="{360 if i % 2 == 0 else -360} 300 300" dur="{dur}s" repeatCount="indefinite"/>
      <circle cx="{x:.1f}" cy="{y:.1f}" r="16" fill="{color}" opacity="0.12"/>
      <circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="{color}"/>
    </g>""")
    bars = []
    for i in range(9):
        h = [24, 48, 70, 96, 120, 96, 70, 48, 24][i]
        x = 300 - 4 * 15 + i * 15 - 3
        bars.append(
            f'<rect x="{x}" y="{300 - h / 2}" width="6" height="{h}" rx="3" fill="url(#hero-bars)">'
            f'<animate attributeName="height" values="{h};{h * 0.45:.0f};{h}" dur="{1.1 + (i % 4) * 0.17:.2f}s" repeatCount="indefinite"/>'
            f'<animate attributeName="y" values="{300 - h / 2};{300 - h * 0.225:.1f};{300 - h / 2}" dur="{1.1 + (i % 4) * 0.17:.2f}s" repeatCount="indefinite"/></rect>'
        )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 600" fill="none" role="img" aria-label="Orbites des agents IA autour d'un cœur vocal">
  <defs>
    <radialGradient id="hero-core" cx="0.5" cy="0.5" r="0.5">
      <stop offset="0" stop-color="{VIOLET}" stop-opacity="0.55"/>
      <stop offset="0.6" stop-color="{CYAN}" stop-opacity="0.12"/>
      <stop offset="1" stop-color="{VOID}" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="hero-ring" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{CYAN}"/>
      <stop offset="0.6" stop-color="{VIOLET}"/>
      <stop offset="1" stop-color="{MAGENTA}"/>
    </linearGradient>
    <linearGradient id="hero-bars" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{CYAN}"/>
      <stop offset="1" stop-color="{VIOLET}"/>
    </linearGradient>
  </defs>
  <circle cx="300" cy="300" r="200" fill="url(#hero-core)">
    <animate attributeName="r" values="190;215;190" dur="6s" repeatCount="indefinite"/>
  </circle>
  <circle cx="300" cy="300" r="150" stroke="url(#hero-ring)" stroke-width="1.2" opacity="0.5"/>
  <circle cx="300" cy="300" r="210" stroke="url(#hero-ring)" stroke-width="1" stroke-dasharray="3 9" opacity="0.45">
    <animateTransform attributeName="transform" type="rotate" from="0 300 300" to="360 300 300" dur="90s" repeatCount="indefinite"/>
  </circle>
  <circle cx="300" cy="300" r="270" stroke="url(#hero-ring)" stroke-width="0.8" opacity="0.25"/>
  {''.join(nodes)}
  {''.join(bars)}
</svg>
"""


def empty_state_svg() -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 160" fill="none" role="img" aria-label="Aucun élément">
  <defs>
    <linearGradient id="es" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{CYAN}"/>
      <stop offset="1" stop-color="{VIOLET}"/>
    </linearGradient>
  </defs>
  <ellipse cx="120" cy="140" rx="70" ry="8" fill="{VIOLET}" opacity="0.15"/>
  <circle cx="120" cy="76" r="52" stroke="url(#es)" stroke-width="2" stroke-dasharray="4 8" opacity="0.6"/>
  <g fill="url(#es)" opacity="0.9">
    <rect x="96" y="66" width="6" height="20" rx="3"/><rect x="108" y="56" width="6" height="40" rx="3"/>
    <rect x="120" y="62" width="6" height="28" rx="3"/><rect x="132" y="52" width="6" height="48" rx="3"/>
    <rect x="144" y="68" width="6" height="16" rx="3"/>
  </g>
  <circle cx="168" cy="36" r="5" fill="{MAGENTA}"/>
</svg>
"""


def render_png(svg: str, out: Path, width: int, height: int | None = None) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".svg", delete=False) as tmp:
        tmp.write(svg)
    args = ["rsvg-convert", "-w", str(width)]
    if height:
        args += ["-h", str(height)]
    subprocess.run([*args, "-o", str(out), tmp.name], check=True)


def main() -> None:
    BRAND.mkdir(parents=True, exist_ok=True)
    files = {
        BRAND / "nimbora-mark.svg": mark_svg(),
        BRAND / "nimbora-logo-on-dark.svg": logo_svg("ld", WHITE),
        BRAND / "nimbora-logo-on-light.svg": logo_svg("ll", INK),
        BRAND / "nimbora-mark-white.svg": mono_mark_svg(WHITE),
        BRAND / "nimbora-mark-ink.svg": mono_mark_svg(INK),
        BRAND / "auth-hero.svg": auth_hero_svg(),
        BRAND / "empty-state.svg": empty_state_svg(),
        APP / "icon.svg": app_icon_svg(),
    }
    for path, content in files.items():
        path.write_text(content)

    icon = app_icon_svg()
    render_png(icon, APP / "apple-icon.png", 180)
    render_png(icon, BRAND / "icon-512.png", 512)
    render_png(icon, BRAND / "icon-192.png", 192)
    with tempfile.TemporaryDirectory() as tmp:
        sizes = []
        for size in (16, 32, 48, 64):
            out = Path(tmp) / f"{size}.png"
            render_png(icon, out, size)
            sizes.append(str(out))
        subprocess.run(["convert", *sizes, str(APP / "favicon.ico")], check=True)

    # Social card: inline the on-dark logo (without its outer <svg>).
    logo = logo_svg("og", WHITE)
    inner = logo.split(">", 1)[1].rsplit("</svg>", 1)[0]
    render_png(og_image_svg(inner), APP / "opengraph-image.png", 1200, 630)
    render_png(og_image_svg(inner), BRAND / "og-image.png", 1200, 630)
    print("NIMBORA brand assets generated.")


if __name__ == "__main__":
    main()
