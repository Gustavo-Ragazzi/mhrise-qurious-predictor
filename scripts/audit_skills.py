"""Validate the reviewed skill roster and regenerate its human-readable report."""

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from qurious_predictor.skill_values import VALUES, supplement
from qurious_predictor.skill_values_extra import UNVERIFIED_VALUES


def audit():
    review = json.loads((ROOT / "tests/data/skill_catalog_review.json").read_text(encoding="utf-8"))
    rows = review["skills"]
    names = {r["name"] for r in rows}
    if len(names) != len(rows) or len(rows) != 147:
        raise ValueError("The reviewed Sunbreak roster must contain 147 unique skills.")
    if (set(VALUES) | set(UNVERIFIED_VALUES)) - names:
        raise ValueError("A supplement is missing from the reviewed roster.")
    for row in rows:
        for lang in ("en", "pt-br"):
            result = supplement({"en": row["name"]}, row["max"], lang)
            if row["review"] in ("supplemented", "partial", "pending"):
                if not result or result["status"] != row["review"]:
                    raise ValueError(f"Reference status or level cap mismatch: {row['name']}")
                if len(result["levels"]) != row["max"] or not all(result["levels"]):
                    raise ValueError(f"Missing level reference: {row['name']}")
            elif result:
                raise ValueError(f"Review needs updating: {row['name']}")
    return review


def report(review):
    rows = review["skills"]
    counts = Counter(r["review"] for r in rows)
    labels = {"supplemented": "Numeric supplement", "partial": "Partial numeric reference",
              "pending": "Numeric reference unverified", "game_text": "Quantity in game text",
              "categorical": "Categorical effect"}
    text = ["# Complete equipment-skill audit", "", f"Checked: {review['checked']}.", "", review["scope"], "",
            f"Roster: [Kiranico]({review['catalog_source']}). Numeric checks use the individual sources in the cards and "
            f"[Sunbreak.txt]({review['reference_source']}).", "", "## Results", ""]
    text += [f"- {counts[k]}: {labels[k]}." for k in labels]
    text += ["", "## Outstanding measurements", "",
             "These gaps are explicitly displayed in the app. Use **Missing / partial values** in the Skills tab. "
             "Unverified quantities are not replaced with guessed values or values from other games.", ""]
    text += [f"- **{r['name']}**: {r['note']}" for r in rows if r["review"] in ("partial", "pending")]
    text += ["", "## Every reviewed skill", "", "| Skill | Max level | Result | Reference |", "| --- | --- | --- | --- |"]
    for row in rows:
        value = VALUES.get(row["name"]) or UNVERIFIED_VALUES.get(row["name"])
        source = value["source"] if value else ("Game-text roster", review["catalog_source"])
        text.append(f"| {row['name']} | {row['max']} | {labels[row['review']]} | [{source[0]}]({source[1]}) |")
    text += ["", "Run `python scripts/audit_skills.py --write-report` after changing the reference. "
             "The audit fails on an omitted supplement, mismatched level cap, missing translation or stale review status.", ""]
    return "\n".join(text)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-report", action="store_true")
    args = parser.parse_args()
    review = audit()
    if args.write_report:
        (ROOT / "docs/SKILL_AUDIT.md").write_text(report(review), encoding="utf-8")
    print(json.dumps(dict(Counter(r["review"] for r in review["skills"]))))
