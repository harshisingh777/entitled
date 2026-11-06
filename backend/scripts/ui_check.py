"""Drives the running app in a real browser: the whole journey by tapping, then every screen at every size.

Run with both servers up:  python scripts/ui_check.py [--shots DIR] [--base URL]
Against the live site:     python scripts/ui_check.py --base https://entitled-pi.vercel.app
"""
import argparse
import sys
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

BASE = "http://127.0.0.1:3000"
SAMPLES = Path(__file__).resolve().parents[1] / "app" / "static" / "samples"
HINDI_CARD = Path(__file__).resolve().parents[1] / "tests" / "data" / "ration_card_hi.jpg"
sent_to_server: list[str] = []
SIZES = {
    "phone-small": (320, 568), "phone": (390, 844), "phone-landscape": (844, 390),
    "tablet": (768, 1024), "tablet-landscape": (1024, 768), "laptop": (1366, 768), "desktop": (1920, 1080),
}
TABS = ["Schemes", "Documents", "Applications", "Profile"]
MIN_TAP = 40

problems: list[str] = []
console_errors: list[str] = []


def check_layout(page: Page, where: str) -> None:
    if page.get_by_role("button", name="Hindi").count():
        problems.append(f"{where}: a Hindi switch is still on the page")
    hindi = page.evaluate(r"""(document.body.innerText + ' ' + [...document.querySelectorAll('[aria-label]')].map(e => e.getAttribute('aria-label')).join(' ')).match(/[\u0900-\u097F]+/)""")
    if hindi:
        problems.append(f"{where}: Hindi text on screen: {hindi[0]}")
    overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    if overflow > 0:
        problems.append(f"{where}: page scrolls sideways by {overflow}px")
    clipped = page.evaluate("""() => {
        const width = document.documentElement.clientWidth, bad = [];
        for (const el of document.querySelectorAll('button, a, input, h1, h2, h3, p, dd, .stamp')) {
            const box = el.getBoundingClientRect();
            if (!box.width || !box.height || el.closest('.filters, .panel-tabs, .sr-only') || el.hidden) continue;
            if (box.left < -1 || box.right > width + 1) bad.push(el.tagName + ':' + (el.innerText || '').slice(0, 24));
        }
        return bad.slice(0, 5);
    }""")
    if clipped:
        problems.append(f"{where}: past the screen edge: {clipped}")
    small = page.evaluate(f"""() => {{
        const bad = [];
        for (const el of document.querySelectorAll('button, a.btn, input:not([type=file])')) {{
            const box = el.getBoundingClientRect();
            if (!box.width || !box.height) continue;
            if (box.height < {MIN_TAP} || box.width < {MIN_TAP}) bad.push((el.getAttribute('aria-label') || el.innerText || el.tagName).slice(0, 24) + ' ' + Math.round(box.width) + 'x' + Math.round(box.height));
        }}
        return [...new Set(bad)].slice(0, 5);
    }}""")
    if small:
        problems.append(f"{where}: tap targets under {MIN_TAP}px: {small}")


def tap_text(page: Page, text: str) -> None:
    page.get_by_role("button", name=text, exact=True).first.click()


def wait_idle(page: Page) -> None:
    page.wait_for_function("!document.querySelector('.bubble-wait')", timeout=180000)
    page.wait_for_timeout(150)


SHORT_LABELS = {"Documents": "Docs", "Applications": "Forms"}


def bottom_tab(page: Page, label: str) -> None:
    page.locator(".bottom-nav button", has_text=SHORT_LABELS.get(label, label)).click()


def journey(page: Page, shots: Path | None) -> str:
    def shot(name: str) -> None:
        if shots:
            page.screenshot(path=str(shots / f"journey-{name}.png"))

    # Every document request is kept, to prove what left the phone.
    page.on("request", lambda r: sent_to_server.append(f"{r.url} {r.post_data or ''}") if "/ocr" in r.url else None)
    page.goto(BASE)
    page.get_by_role("button", name="Walk through Kamla Devi's case").click()
    page.wait_for_url("**/h/**")
    household = page.url.split("/h/")[1].split("?")[0]
    expect(page.locator(".bubble-agent").first).to_contain_text("How old are you")
    shot("01-start")

    tap_text(page, "Speak as Kamla Devi")
    wait_idle(page)
    expect(page.locator(".meter-value").first).not_to_have_text("₹0")
    shot("02-after-intro")

    answers = {"LPG connection": "No", "pucca house": "No", "income tax": "No", "any of these apply": "No", "bank account": "Yes", "income certificate": "No"}
    for _ in range(12):
        last = page.locator(".bubble-agent").last.inner_text()
        if page.locator(".meter-note").inner_text().startswith("All "):
            break
        reply = next((value for key, value in answers.items() if key in last), None)
        assert reply, f"No answer for: {last}"
        tap_text(page, reply)
        wait_idle(page)
    expect(page.locator(".meter-value").first).to_have_text("₹18,000")
    shot("03-eligibility")

    bottom_tab(page, "Schemes")
    expect(page.get_by_test_id("scheme-up_nirashrit_mahila")).to_contain_text("Entitled")
    expect(page.get_by_test_id("scheme-up_vridhavastha")).to_contain_text("in 2 years")
    expect(page.get_by_test_id("scheme-up_kanya_sumangala")).to_contain_text("income certificate")
    shot("04-schemes")

    bottom_tab(page, "Documents")
    for sample in ("Ration card", "Aadhaar", "Passbook"):
        page.locator(".sample-row").get_by_role("button", name=sample, exact=True).click()
        page.wait_for_function("!document.querySelector('.sample-row button[disabled]')", timeout=240000)
    expect(page.get_by_test_id("doc-aadhaar")).to_be_visible()
    expect(page.locator(".extracted")).to_contain_text("DEMO0001234")
    expect(page.locator(".extracted")).to_contain_text("XXXX0412")
    expect(page.locator(".device-note")).to_contain_text("never left it")
    if any("/ocr " in item or item.split(" ")[0].endswith("/ocr") for item in sent_to_server):
        problems.append("journey: a demo photo went to the server instead of being read on the device")
    if any("9999" in item and "8888" in item for item in sent_to_server):
        problems.append("journey: the full Aadhaar number left the device")
    shot("05-documents")

    bottom_tab(page, "Chat")
    page.locator("#chat-input").fill("fill the form")
    page.keyboard.press("Enter")
    wait_idle(page)
    replies = {"Is that right": "Yes", "death certificate": "Yes", "mobile number": "9876543210", "Land record": "Yes", "passbook": "Yes", "Aadhaar card": "Yes", "Ration card": "Yes"}
    for _ in range(10):
        if page.locator(".confirm-card").count():
            break
        last = page.locator(".bubble-agent").last.inner_text()
        reply = next((value for key, value in replies.items() if key in last), None)
        assert reply, f"No answer for: {last}"
        page.locator("#chat-input").fill(reply)
        page.keyboard.press("Enter")
        wait_idle(page)
    expect(page.locator(".confirm-card")).to_be_visible()
    expect(page.locator(".frames img")).to_be_visible()
    page.wait_for_function("document.querySelector('.frames figcaption').innerText.includes('Form filled')", timeout=30000)
    shot("06-confirm")
    check_layout(page, "journey/confirm")

    page.get_by_role("button", name="Demo: try sending without confirmation").click()
    expect(page.locator(".refusal")).to_contain_text("Refused")
    shot("07-refused")

    page.get_by_role("button", name="Yes, send it").click()
    wait_idle(page)
    expect(page.locator(".bubble-agent", has_text="Reference").last).to_be_visible()
    shot("08-submitted")

    bottom_tab(page, "Applications")
    expect(page.get_by_test_id("application-up_nirashrit_mahila")).to_contain_text("MOCK-")
    page.get_by_role("button", name="12 days on").click()
    page.wait_for_function("document.querySelector('.tracker li:nth-child(2)').dataset.done === 'true'", timeout=30000)
    expect(page.locator(".notices")).to_contain_text("block office")
    shot("09-tracker")
    bottom_tab(page, "Chat")
    expect(page.locator(".bubble-agent").last).to_contain_text("in verification for 12 days")
    shot("10-resume")

    bottom_tab(page, "Applications")
    page.get_by_role("button", name="20 days on").click()
    page.wait_for_function("document.querySelector('.tracker li:nth-child(4)').dataset.done === 'true'", timeout=30000)
    expect(page.locator(".meter-value-got")).to_have_text("₹12,000")
    shot("11-money-landed")

    bottom_tab(page, "Profile")
    expect(page.locator(".facts")).to_contain_text("From document")
    expect(page.locator(".facts")).to_contain_text("XXXX0412")
    if "100200300412" in page.content() or "9999 8888" in page.content():
        problems.append("journey: a full account or Aadhaar number reached the screen")
    return household


def hindi_fallback(page: Page) -> None:
    """A Hindi card defeats the phone's Latin-only reader, so the photo goes to the server's Hindi reader instead."""
    page.goto(BASE)
    page.get_by_role("button", name="Start talking").click()
    page.wait_for_url("**/h/**")
    bottom_tab(page, "Documents")
    page.get_by_label("Document photo or PDF").set_input_files(str(HINDI_CARD))
    page.wait_for_function("!document.querySelector('.upload-box button[disabled]')", timeout=240000)
    expect(page.locator(".extracted")).to_contain_text("Ram Prasad")
    expect(page.locator(".extracted")).to_contain_text("Sunita Devi")
    check_layout(page, "hindi-document")


def recovery(page: Page) -> None:
    """A household lost in a server restart gets an explanation and a way back, not 'the server did not respond'."""
    page.goto(f"{BASE}/h/000000000000?demo=kamla")
    expect(page.get_by_role("heading", name="This conversation was cleared")).to_be_visible(timeout=60000)
    check_layout(page, "recovery")
    page.get_by_role("button", name="Start Kamla Devi's case again").click()
    page.wait_for_url("**/h/**?demo=kamla")
    expect(page.locator(".bubble-agent").first).to_contain_text("How old are you")


def sweep(browser, household: str, shots: Path | None) -> None:
    for name, (width, height) in SIZES.items():
        context = browser.new_context(viewport={"width": width, "height": height}, has_touch=width < 768)
        page = context.new_page()
        page.on("console", lambda m, n=name: console_errors.append(f"{n}: {m.text}") if m.type == "error" else None)
        page.on("pageerror", lambda e, n=name: console_errors.append(f"{n}: {e}"))

        def visit(path: str, label: str) -> None:
            page.goto(BASE + path, wait_until="networkidle")
            check_layout(page, f"{name}/{label}")
            if shots:
                page.screenshot(path=str(shots / f"{name}-{label}.png"))

        visit("/", "home")
        visit("/operator", "operator")
        visit("/operator/log", "log")
        visit(f"/h/{household}", "chat")
        if page.locator(".bottom-nav").is_visible():
            for tab in TABS:
                bottom_tab(page, tab)
                page.wait_for_timeout(120)
                check_layout(page, f"{name}/{tab}")
                if shots:
                    page.screenshot(path=str(shots / f"{name}-{tab}.png"))
        else:
            for tab in TABS:
                button = page.locator(".panel-tabs button", has_text=tab)
                if button.is_visible():
                    button.click()
                    page.wait_for_timeout(120)
                    check_layout(page, f"{name}/{tab}")
                    if shots:
                        page.screenshot(path=str(shots / f"{name}-{tab}.png"))
        context.close()


def main() -> int:
    global BASE
    parser = argparse.ArgumentParser()
    parser.add_argument("--shots", type=Path)
    parser.add_argument("--base", default=BASE)
    args = parser.parse_args()
    BASE = args.base.rstrip("/")
    if args.shots:
        args.shots.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True)
        page = context.new_page()
        page.on("console", lambda m: console_errors.append(f"journey: {m.text}") if m.type == "error" and "403" not in m.text else None)
        page.on("pageerror", lambda e: console_errors.append(f"journey: {e}"))
        household = journey(page, args.shots)
        print("journey passed on a phone-sized screen, household", household)
        context.close()
        # Its own context: opening a lost household logs a 404 on purpose, which is not a console error to report.
        context = browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True)
        page = context.new_page()
        recovery(page)
        print("recovery screen passed")
        hindi_fallback(page)
        print("Hindi document read through the server fallback")
        context.close()
        sweep(browser, household, args.shots)
        browser.close()
    for item in problems + console_errors:
        print("PROBLEM", item)
    print(f"{len(SIZES)} sizes checked, {len(problems)} layout problems, {len(console_errors)} console errors")
    return 1 if problems or console_errors else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
