"""Playwright agent, run as its own process so the browser never shares the API's event loop.

stdin:  {"action": "fill"|"pdf", "url": ..., "fields": {...}, "out": path}
stdout: one JSON object
"""
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

VIEWPORT = {"width": 820, "height": 900}


def fill(page, job: dict) -> dict:
    out = Path(job["out"])
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.jpg"):
        old.unlink()

    def shot(n: int) -> None:
        page.screenshot(path=str(out / f"{n:02d}.jpg"), type="jpeg", quality=62, full_page=True)

    page.goto(job["url"], wait_until="load")
    shot(0)
    frames = 1
    for name, value in job["fields"].items():
        locator = page.locator(f'[name="{name}"]')
        locator.scroll_into_view_if_needed()
        locator.fill(str(value))
        shot(frames)
        frames += 1
    readback = {name: page.locator(f'[name="{name}"]').input_value() for name in job["fields"]}
    return {"frames": frames, "readback": readback}


def pdf(page, job: dict) -> dict:
    page.goto(job["url"], wait_until="networkidle")
    page.pdf(path=job["out"], format="A4", print_background=True, margin={"top": "12mm", "bottom": "12mm", "left": "10mm", "right": "10mm"})
    return {"path": job["out"]}


def main() -> None:
    job = json.loads(sys.stdin.read())
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport=VIEWPORT)
        result = fill(page, job) if job["action"] == "fill" else pdf(page, job)
        browser.close()
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
    main()
