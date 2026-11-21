"""Render public/icon.svg into every icon the apps need.

Desktop icons go to src-tauri/icons/ (PNG, ICO, ICNS); PWA icons to public/.
Android and iOS icon sets are generated in CI with `tauri icon` from
src-tauri/icons/icon.png.
"""

import subprocess
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / "public" / "icon.svg"
ICONS = ROOT / "src-tauri" / "icons"


def main() -> None:
    ICONS.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        master = Path(tmp) / "icon-1024.png"
        subprocess.run(
            ["rsvg-convert", "-w", "1024", "-h", "1024", str(SVG), "-o", str(master)],
            check=True,
        )
        image = Image.open(master).convert("RGBA")
    sizes = {
        "32x32.png": 32,
        "64x64.png": 64,
        "128x128.png": 128,
        "128x128@2x.png": 256,
        "icon.png": 512,
        "Square30x30Logo.png": 30,
        "Square44x44Logo.png": 44,
        "Square71x71Logo.png": 71,
        "Square89x89Logo.png": 89,
        "Square107x107Logo.png": 107,
        "Square142x142Logo.png": 142,
        "Square150x150Logo.png": 150,
        "Square284x284Logo.png": 284,
        "Square310x310Logo.png": 310,
        "StoreLogo.png": 50,
    }
    for name, size in sizes.items():
        image.resize((size, size), Image.LANCZOS).save(ICONS / name)
    image.save(ICONS / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    image.save(ICONS / "icon.icns")
    for size in (192, 512):
        image.resize((size, size), Image.LANCZOS).save(ROOT / "public" / f"icon-{size}.png")
    print(f"Icons written to {ICONS}")


if __name__ == "__main__":
    main()
