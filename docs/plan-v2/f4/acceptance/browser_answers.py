"""Check that a downloaded HTML answer file is accepted by the agent at three viewport widths."""
import argparse
import json
from pathlib import Path
import sys
from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--browser", help="Optional Chrome or Edge executable")
    args = parser.parse_args()
    sys.path.insert(0, str(args.repo.resolve() / "src"))
    from bcc_review.v2.stages.recheck import parse_answers_text

    args.out.mkdir(parents=True, exist_ok=True)
    url = args.report.resolve().as_uri()
    note = "Проверяем вручную через 17 минут."
    rows = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=args.browser)
        try:
            for width in (1440, 768, 390):
                page = browser.new_page(viewport={"width": width, "height": 900}, accept_downloads=True)
                page.goto(url)
                page.locator("#t-questions").click()
                page.locator('input[name="Q-01"][value="1"]').check()
                page.locator('textarea[data-own="Q-02"]').fill(note)
                with page.expect_download() as event:
                    page.locator("#dlanswers").click()
                download = event.value
                target = args.out / f"answers-{width}.md"
                download.save_as(target)
                replies = {item["id"]: item for item in parse_answers_text(
                    target.read_text(encoding="utf-8-sig"))["answers"]}
                if replies["Q-01"]["choice"] != 1 or replies["Q-02"]["text"] != note:
                    raise ValueError(f"Downloaded answers changed at width {width}")
                overflow = page.evaluate("document.documentElement.scrollWidth > innerWidth")
                if overflow:
                    raise ValueError(f"Horizontal scrolling at width {width}")
                rows.append(dict(width=width, letter="B", free_text_preserved=True,
                                 horizontal_overflow=overflow, downloaded=download.suggested_filename))
                page.close()
        finally:
            browser.close()
    (args.out / "browser-result.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    print("Passed at", ", ".join(str(r["width"]) for r in rows), "pixels")


if __name__ == "__main__":
    main()
