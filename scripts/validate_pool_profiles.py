#!/usr/bin/env python3
"""Validate dashboard/data/lookup/pool_profiles.json against schema and registry coverage."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOOKUP = ROOT / "dashboard" / "data" / "lookup"
PROFILES_PATH = LOOKUP / "pool_profiles.json"
FACTS_PATH = LOOKUP / "pool_facts.json"
SLUG_TO_NAME_PATH = LOOKUP / "lookup_slug_to_name.json"

REQUIRED_KEYS = {
    "name", "website", "operator", "country", "launched",
    "former_names", "description", "identification_note", "tier", "sources",
}

def main() -> int:
    doc = json.loads(PROFILES_PATH.read_text())
    assert doc.get("schema_version") == 1, f"Bad schema_version: {doc.get('schema_version')}"
    assert isinstance(doc.get("updated"), str) and doc["updated"], "Missing updated date"
    pools = doc.get("pools")
    assert isinstance(pools, dict) and pools, "Missing pools dict"

    facts = json.loads(FACTS_PATH.read_text())["pools"]
    slug_to_name = json.loads(SLUG_TO_NAME_PATH.read_text())

    # Every slug in pool_facts and lookup_slug_to_name must have a profile
    missing_facts = sorted(set(facts) - set(pools))
    missing_lookup = sorted(set(slug_to_name) - set(pools))
    assert not missing_facts, f"Slugs in pool_facts missing profile: {missing_facts}"
    assert not missing_lookup, f"Slugs in lookup_slug_to_name missing profile: {missing_lookup}"
    assert "unknown" in pools, "Missing 'unknown' profile"

    for slug, p in pools.items():
        extra = set(p) - REQUIRED_KEYS
        miss = REQUIRED_KEYS - set(p)
        assert not extra and not miss, f"{slug}: bad keys miss={miss} extra={extra}"
        assert isinstance(p["name"], str) and p["name"], f"{slug}: invalid name"
        assert isinstance(p["former_names"], list), f"{slug}: former_names must be list"
        assert p["tier"] in ("detailed", "minimal"), f"{slug}: invalid tier {p['tier']}"
        srcs = p["sources"]
        assert isinstance(srcs, list) and len(srcs) >= 1, f"{slug}: at least 1 source required"
        for i, s in enumerate(srcs):
            assert isinstance(s.get("claim"), str) and s["claim"].strip(), f"{slug}.sources[{i}]: empty claim"
            assert isinstance(s.get("url"), str) and s["url"].startswith("http"), f"{slug}.sources[{i}]: bad url"
            assert isinstance(s.get("accessed"), str) and len(s["accessed"]) == 10, f"{slug}.sources[{i}]: bad accessed date"
        if p["tier"] == "detailed":
            assert isinstance(p["description"], str) and p["description"].strip(), f"{slug}: detailed profile missing description"

    # Also verify old pools_info.json is no longer present in served lookup
    assert not (LOOKUP / "pools_info.json").exists(), "Legacy dashboard/data/lookup/pools_info.json must be removed"

    print(f"OK: validated {len(pools)} pool profiles ({sum(1 for p in pools.values() if p['tier']=='detailed')} detailed, {sum(1 for p in pools.values() if p['tier']=='minimal')} minimal)")
    return 0

if __name__ == "__main__":
    sys.exit(main())
