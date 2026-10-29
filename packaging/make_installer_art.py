"""Images of the Windows installer (black background, Eden tree) and the exe version info."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
LOGO = ROOT / "src" / "eden" / "assets" / "eden-logo.png"
OUT = ROOT / "packaging" / "build-art"


def version() -> str:
    text = (ROOT / "src" / "eden" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__ = "([^"]+)"', text).group(1)


def tree(size: int) -> Image.Image:
    return Image.open(LOGO).convert("RGBA").resize((size, size), Image.LANCZOS)


def side_image(w: int, h: int) -> Image.Image:
    img = Image.new("RGB", (w, h), (0, 0, 0))
    t = tree(int(w * 0.9))
    img.paste(t, ((w - t.width) // 2, int(h * 0.22)), t)
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", int(w * 0.17))
    except OSError:
        font = ImageFont.load_default()
    text = "Eden"
    box = d.textbbox((0, 0), text, font=font)
    d.text(((w - (box[2] - box[0])) // 2, int(h * 0.22) + t.height + int(h * 0.03)), text,
           fill=(244, 244, 246), font=font)
    return img


def small_image(s: int) -> Image.Image:
    img = Image.new("RGB", (s, s), (0, 0, 0))
    t = tree(s)
    img.paste(t, (0, 0), t)
    return img


def version_info(v: str) -> str:
    parts = (v.split(".") + ["0", "0", "0"])[:4]
    nums = ", ".join(str(int(re.sub(r"\D.*", "", p) or 0)) for p in parts)
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({nums}), prodvers=({nums})),
  kids=[
    StringFileInfo([StringTable('040C04B0', [
      StringStruct('CompanyName', 'Eden'),
      StringStruct('FileDescription', 'Eden - mixage vocal automatique'),
      StringStruct('FileVersion', '{v}'),
      StringStruct('ProductName', 'Eden'),
      StringStruct('ProductVersion', '{v}'),
      StringStruct('OriginalFilename', 'Eden.exe')])]),
    VarFileInfo([VarStruct('Translation', [1036, 1200])])
  ]
)
"""


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    # 100 %, 150 % and 200 % display scaling
    for scale, suffix in ((1, "100"), (1.5, "150"), (2, "200")):
        side_image(int(164 * scale), int(314 * scale)).save(OUT / f"wizard-{suffix}.bmp")
        small_image(int(55 * scale)).save(OUT / f"wizard-small-{suffix}.bmp")
    v = version()
    (ROOT / "packaging" / "version_info.txt").write_text(version_info(v), encoding="utf-8")
    print(v)
    sys.stdout.flush()


if __name__ == "__main__":
    main()
