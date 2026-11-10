"""The settings page's `careful.json` (what she already handles with care, so listing it changes nothing) is the same fact as
`ashley/tools/tiers.json`: the domains with a `runs` rule, and the device classes a `judged` rule takes back."""

import json
from pathlib import Path

from ashley.tools.tiers_config import load

PAGE_DATA = Path(__file__).parent.parent / "web" / "src" / "rooms" / "connections" / "settings" / "careful.json"


def test_the_page_s_data_is_what_tiers_json_says() -> None:
    rules = load().house_do
    runs = {r.tier for r in rules}
    assert runs == {"runs", "judged"}, "the control must see both tiers"
    free = sorted({(r.domain or (r.action or "").partition(".")[0]) for r in rules if r.tier == "runs"})
    careful: dict[str, list[str]] = {}
    for r in rules:
        if r.tier == "judged" and r.domain and r.device_class:
            careful.setdefault(r.domain, []).extend(sorted(r.device_class))
    assert json.loads(PAGE_DATA.read_text()) == {"domains": free, "careful_classes": dict(sorted(careful.items()))}
