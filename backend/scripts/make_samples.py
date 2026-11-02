"""Draws the synthetic demo documents. Every one is marked as a specimen and matches no real person."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parents[1] / "app" / "static" / "samples"
OUT.mkdir(parents=True, exist_ok=True)
FONT = "C:/Windows/Fonts/arial.ttf"
BOLD = "C:/Windows/Fonts/arialbd.ttf"


def _font(path: str, size: int):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default(size)


def draw(name: str, title: str, tint: str, rows: list[tuple[str, str]]) -> None:
    image = Image.new("RGB", (1100, 680), "#fbfaf5")
    pen = ImageDraw.Draw(image)
    pen.rectangle([0, 0, 1100, 96], fill=tint)
    pen.text((40, 28), title, fill="white", font=_font(BOLD, 40))
    y = 130
    for label, value in rows:
        pen.text((48, y), f"{label}: {value}", fill="#14161c", font=_font(FONT, 36))
        y += 68
    pen.rectangle([0, 620, 1100, 680], fill="#7a2e0e")
    pen.text((40, 632), "SPECIMEN - SYNTHETIC DEMO DOCUMENT - NOT VALID ANYWHERE", fill="white", font=_font(BOLD, 28))
    image.save(OUT / name, "JPEG", quality=92)


draw("ration_card.jpg", "RATION CARD", "#2f6b3a", [
    ("Card Type", "BPL"), ("Name", "Kamla Devi"), ("Husband Name", "Ramesh Kumar"),
    ("Address", "Village Bachhrawan"), ("District", "Raebareli"),
])
draw("aadhaar.jpg", "AADHAAR SPECIMEN", "#8a4b12", [
    ("Name", "Kamla Devi"), ("Date of Birth", "15/03/1968"), ("Number", "9999 8888 4821"),
])
draw("passbook.jpg", "BANK PASSBOOK", "#22375a", [
    ("Account Holder", "Kamla Devi"), ("Account No", "100200300412"), ("IFSC", "DEMO0001234"), ("Bank Name", "Demo Gramin Bank"),
])
print("samples written to", OUT)
