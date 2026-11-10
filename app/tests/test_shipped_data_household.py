"""Nothing household-specific ships. Every string value in the JSON under `ashley/` is checked for a Home
Assistant entity id (`domain.object_id` over HA's own domains), and every URL host in the JSON, markdown
and html is checked against `PUBLIC_HOSTS`. A household's entities and hosts live in its connection's settings
or its own data, never in the tree.

Values under `SERVICE_KEYS` hold HA service names (`light.turn_on`), which share the entity-id shape and are
general. Markdown is scanned for URL hosts only: its prose is never judged. A host that is not a public service
is not added here; it moves out of the tree."""

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import TypeGuard

ASHLEY = Path(__file__).resolve().parent.parent / "ashley"

HA_DOMAINS = frozenset("""alarm_control_panel assist_satellite automation binary_sensor button calendar camera climate
cover device_tracker event fan group humidifier input_boolean input_button input_datetime input_number input_select
input_text light lock media_player notify number person remote scene script select sensor siren sun switch text timer
todo update vacuum valve water_heater weather zone""".split())

SERVICE_KEYS = frozenset({"action", "excluded"})

PUBLIC_HOSTS = frozenset({
    "platform.claude.com",      # Anthropic's API docs, linked from the price and provider tables
    "developers.openai.com",    # OpenAI's API docs
    "ai.google.dev",            # Google's Gemini API docs
    "aistudio.google.com",      # Google AI Studio, where a Gemini key is made
    "huggingface.co",           # Hugging Face model pages
    "github.com",               # a price source's public repository
    "elevenlabs.io",            # ElevenLabs' public site
    "api.printables.com",       # Printables' public API
    "www.printables.com",       # Printables' public site
    "photon.komoot.io",         # the public Photon geocoder behind place search
    "developers.google.com",    # Google's public developer docs, linked from sign-in help
    "myaccount.google.com",     # Google's account page, linked from sign-in help
})

ENTITY = re.compile(r"^([a-z_]+)\.[a-z0-9_]+$")
HOST = re.compile(r"https?://([^/\s:\"'<>?#)\]]+)", re.IGNORECASE)


def is_object(node: object) -> TypeGuard[dict[str, object]]:
    return isinstance(node, dict)


def is_array(node: object) -> TypeGuard[list[object]]:
    return isinstance(node, list)


def strings(node: object, key: str = "") -> Iterator[tuple[str, str]]:
    if is_object(node):
        for k, v in node.items():
            yield from strings(v, k)
    elif is_array(node):
        for v in node:
            yield from strings(v, key)
    elif isinstance(node, str):
        yield key, node


def violations(values: list[tuple[str, str]]) -> list[str]:
    """What is household-specific among (key, string value) pairs."""
    found: list[str] = []
    for key, text in values:
        match = ENTITY.match(text)
        if match and match.group(1) in HA_DOMAINS and key not in SERVICE_KEYS:
            found.append(f"entity id {text!r} under {key!r}")
        for host in HOST.findall(text):
            if host.lower() not in PUBLIC_HOSTS:
                found.append(f"host {host!r} in {text[:60]!r}")
    return found


def shipped() -> tuple[list[Path], list[tuple[Path, str, str]]]:
    files = sorted(p for p in ASHLEY.rglob("*") if p.suffix in {".json", ".md", ".html"})
    values: list[tuple[Path, str, str]] = []
    for p in files:
        if p.suffix == ".json":
            values += [(p, k, s) for k, s in strings(json.loads(p.read_text()))]
        else:
            values += [(p, "", f"https://{host}") for host in HOST.findall(p.read_text())]
    return files, values


def test_nothing_household_specific_ships():
    files, values = shipped()
    json_files = [p for p in files if p.suffix == ".json"]
    assert len(json_files) >= 50 and len(values) >= 1500, f"scanned {len(json_files)} json files, {len(values)} values"
    assert sum(1 for _, _, s in values if HOST.match(s)) >= 10, "the scan saw no URLs"
    assert sum(1 for _, k, s in values if ENTITY.match(s) and k in SERVICE_KEYS) >= 5, "the scan saw no service names"
    found = [f"{p.relative_to(ASHLEY)}: {v}" for p, k, s in values for v in violations([(k, s)])]
    assert not found, "household-specific values ship:\n" + "\n".join(found)


def test_controls_a_household_value_goes_red_and_a_public_one_stays_green():
    assert violations([("entity", "light.kitchen_ceiling")]) == ["entity id 'light.kitchen_ceiling' under 'entity'"]
    assert violations([("url", "http://homeassistant.local:8123/api")]) != []
    assert violations([("url", "https://ha.example.internal/x")]) != []
    assert violations([("url", "https://photon.komoot.io/api")]) == []
    assert violations([("action", "light.turn_on")]) == []
    assert violations([("name", "not.an_entity_domain")]) == []
