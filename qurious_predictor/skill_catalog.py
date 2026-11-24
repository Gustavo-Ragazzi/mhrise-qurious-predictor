"""Plain-text, localized skill reference built from installed game messages."""

import html
import re

from .skill_values import supplement


def message_text(names: dict, lang: str) -> str:
    text = names.get(lang) or names.get("en") or next(iter(names.values()), "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    return html.unescape(re.sub(r"<[^>]*>", "", text)).strip()


def catalog(data: dict, lang: str) -> list[dict]:
    rows = []
    decorations = {}
    for deco in data.get("decorations", []):
        decorations.setdefault(int(deco["skill"]), []).append({
            "id": deco["id"], "name": message_text(deco["names"], lang),
            "slot": deco["level"], "points": deco["points"],
        })
    for sid, names in data["skills"].items():
        details = data.get("skill_details", {}).get(sid, {})
        maximum = data["max_levels"].get(sid, 0) + 1
        levels = details.get("levels", [])
        values = supplement(names, maximum, lang)
        rows.append({"id": int(sid), "name": message_text(names, lang),
                     "color": data["skill_colors"].get(sid, 0), "max": maximum,
                     "decorations": sorted(decorations.get(int(sid), []),
                                           key=lambda deco: (deco["slot"], deco["name"])),
                     "description": (values.get("description") if values else None)
                                    or message_text(details.get("description", {}), lang),
                     "levels": [{"level": lv + 1,
                                 "effect": message_text(levels[lv] if lv < len(levels) else {}, lang),
                                 "values": values["levels"][lv] if values else ""}
                                for lv in range(maximum)],
                     "valuesSource": values["source"] if values else None,
                     "referenceStatus": values["status"] if values else "game"})
    return sorted(rows, key=lambda row: row["name"].casefold())
