"""Replay a real owner's choice against the same, reordered and regenerated question."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("repo", "evidence", "out"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--browser", help="Path to Chromium, Edge or Chrome")
    args = parser.parse_args()
    sys.path.insert(0, str(args.repo.resolve() / "src"))
    from bcc_review.v2.render.html import render_html
    from bcc_review.v2.stages.recheck import load_answers, resolve_answers

    f4 = args.evidence
    baseline = json.loads((f4 / "answers_exam/car-loan/baseline.json").read_bytes())
    current = json.loads((f4 / "acceptance/owner-e2e/car-loan/answered.json").read_bytes())
    old = baseline["questions"][0]
    assert old["id"] == "Q-01" and "пять" in old["options"][0].lower()
    chosen = old["options"][0]
    regenerated = next(q for q in current["questions"] if q["id"] == "Q-02")
    assert "пять дней — отказ" in regenerated["options"][0].lower()
    args.out.mkdir(exist_ok=True, parents=True)
    html = args.out / "report.html"
    html.write_text(render_html(baseline), encoding="utf-8")
    rows = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=args.browser)
        try:
            for width in (1440, 768, 390):
                page = browser.new_page(viewport={"width": width, "height": 900}, accept_downloads=True)
                page.goto(html.resolve().as_uri())
                page.locator("#t-questions").click()
                page.locator('input[name="Q-01"][value="0"]').check()
                with page.expect_download() as event:
                    page.locator("#dlanswers").click()
                output = args.out / f"answers-{width}.md"
                event.value.save_as(output)
                parsed = load_answers(output)
                reordered = dict(old, options=list(reversed(old["options"])))
                for condition, questions in (("original", [old]), ("reordered", [reordered]),
                                             ("regenerated", [regenerated])):
                    result = resolve_answers(questions, parsed)["answered"]
                    received = result[0]["answer"] if len(result) == 1 else ""
                    rows.append({"width": width, "condition": condition, "selected": chosen,
                                 "received": received, "preserved": received == chosen})
                page.close()
        finally:
            browser.close()
    (args.out / "result.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
                                           encoding="utf-8")
    passed = sum(r["preserved"] for r in rows)
    print(f"{passed}/{len(rows)} choices preserved")
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
