"""Draws a synthetic Hindi ration card for the OCR tests, in a real browser so Devanagari is shaped correctly.

Pillow cannot shape Devanagari without libraqm, so make_samples.py is no use here. Everything on the card is invented.
"""
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[1] / "tests" / "data" / "ration_card_hi.jpg"
ROWS = [
    ("कार्ड का प्रकार", "अंत्योदय"),
    ("नाम", "सुनीता देवी"),
    ("पति का नाम", "राम प्रसाद"),
    ("पता", "ग्राम सरेनी"),
    ("जिला", "रायबरेली"),
]
PAGE = f"""<!doctype html><meta charset="utf-8">
<style>
  body {{ margin: 0; width: 1100px; height: 680px; background: #fbfaf5; font-family: 'Nirmala UI', 'Noto Sans Devanagari', sans-serif; }}
  header {{ background: #2f6b3a; color: white; font: bold 40px 'Nirmala UI', 'Noto Sans Devanagari', sans-serif; padding: 24px 40px; }}
  p {{ font-size: 36px; margin: 0; padding: 14px 48px; color: #14161c; }}
  footer {{ position: absolute; top: 620px; width: 1100px; height: 60px; background: #7a2e0e; color: white; font: bold 28px Arial; padding: 12px 40px; box-sizing: border-box; }}
</style>
<header>राशन कार्ड</header>
{''.join(f'<p>{label}: {value}</p>' for label, value in ROWS)}
<footer>SPECIMEN - SYNTHETIC DEMO DOCUMENT - NOT VALID ANYWHERE</footer>"""

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1100, "height": 680})
    page.set_content(PAGE)
    page.screenshot(path=str(OUT), type="jpeg", quality=92)
    browser.close()
print("written", OUT)
