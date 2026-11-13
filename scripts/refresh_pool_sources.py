"""
refresh_pool_sources.py
Daily refresh of the two upstream pool lists: fetch (pinned to a commit), validate, merge into the registry.

For each source in data/raw/pool_sources.lock.json:
  1. Fetch, pinned to a commit. One GitHub API call finds the newest commit on the branch that touched the file
     (GET /repos/<repo>/commits?sha=<branch>&path=<file>&per_page=1); if it is the pinned SHA, nothing is
     downloaded. Otherwise the file is downloaded from raw.githubusercontent.com/<repo>/<sha>/<file>. A file whose
     bytes equal the pinned snapshot (md5) keeps the old pin.
  2. Validate before use: the JSON parses and has the expected schema; every payout address decodes to a mainnet
     scriptPubKey; every mempool regex compiles in Python (pool_resolver.js_regex_to_python translates the JS-only
     forms) and does not match the empty string; no empty substring tag. An entry that fails is rejected on its own
     and listed in the run report. The whole snapshot is refused, and the last good one kept, when the file does
     not parse, the schema is wrong, or the usable tags, addresses or pools drop by more than 10% against the last
     good snapshot.
  3. Merge: build_pools_lookup.build() merges supplement > mempool > bitcoin-data into
     dashboard/data/lookup/pools_enriched.json with a new registry_version; conflicts go to pool_conflicts.json.
     The candidate registry is built and diffed before any file in the repo changes.

Failure policy: a fetch failure (network, GitHub) keeps the last good snapshot and is a warning; it becomes an
alert when a source has not been checked successfully for more than --stale-days (default 7). A validation
failure keeps the last good snapshot and is an alert. Neither fails the run (exit 0), so the block refresh still
runs on the last good list. Exit 1 only for a real error (corrupt lock, a snapshot that cannot be restored, a merge
that crashes).

Writes (not with --dry-run):
  data/raw/<snapshot files>, data/raw/pool_sources.lock.json      only when a source changed
  dashboard/data/lookup/pools_enriched.json, pool_conflicts.json, ...  (build_pools_lookup)
  dashboard/data/lookup/pool_list_status.json   when each source was last checked ("pool list as of", footer)
  data/processed/pool_refresh_run.json          this run's report, read by the automation for its ops alert

Usage:
  python3 scripts/refresh_pool_sources.py                   # daily refresh
  python3 scripts/refresh_pool_sources.py --dry-run         # fetch into a temp dir; print the diff and how many
                                                            # blocks would change label; write nothing
  python3 scripts/refresh_pool_sources.py --pin bitcoin-data=<sha>   # use this commit instead of the newest
  python3 scripts/refresh_pool_sources.py --offline         # no network: check the snapshots, rebuild the registry
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
LOCK = RAW / "pool_sources.lock.json"
LOOKUP_DIR = ROOT / "dashboard" / "data" / "lookup"
REGISTRY = LOOKUP_DIR / "pools_enriched.json"
CONFLICTS = LOOKUP_DIR / "pool_conflicts.json"
STATUS = LOOKUP_DIR / "pool_list_status.json"
RUN_REPORT = ROOT / "data" / "processed" / "pool_refresh_run.json"
MAX_DROP = 0.10
STALE_DAYS = 7
USER_AGENT = "bitcoin-mining-pools-refresh"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pool_resolver import addr_to_script, regex_problem  # noqa: E402


class FetchError(Exception):
    pass


class ValidationError(Exception):
    pass


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def md5(b: bytes) -> str:
    return hashlib.md5(b).hexdigest()


def load_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def write_json_atomic(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------
def http_get(url: str, timeout: int = 30, tries: int = 3) -> bytes:
    headers = {"User-Agent": USER_AGENT}
    if url.startswith("https://api.github.com/"):
        headers["Accept"] = "application/vnd.github+json"
        if os.environ.get("GITHUB_TOKEN"):
            headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    last = None
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code < 500 and e.code != 429:      # 404, 403 (rate limit): retrying will not help
                break
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            last = str(getattr(e, "reason", e))
        time.sleep(2 * (attempt + 1))
    raise FetchError(f"{url}: {last}")


def newest_commit(repo: str, branch: str, file: str) -> tuple[str, str]:
    """(sha, committer date) of the newest commit on `branch` that touched `file`."""
    url = f"https://api.github.com/repos/{repo}/commits?sha={branch}&path={file}&per_page=1"
    try:
        data = json.loads(http_get(url))
        return data[0]["sha"], data[0]["commit"]["committer"]["date"]
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise FetchError(f"{url}: unexpected response ({e})") from e


def commit_date(repo: str, sha: str) -> tuple[str, str]:
    """(full sha, committer date) of one commit; used with --pin."""
    url = f"https://api.github.com/repos/{repo}/commits/{sha}"
    try:
        data = json.loads(http_get(url))
        return data["sha"], data["commit"]["committer"]["date"]
    except (ValueError, KeyError, TypeError) as e:
        raise FetchError(f"{url}: unexpected response ({e})") from e


def raw_url(repo: str, sha: str, file: str) -> str:
    return f"https://raw.githubusercontent.com/{repo}/{sha}/{file}"


# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------
NON_MAINNET_PREFIXES = ("tb1", "bcrt1", "2", "m", "n")


def parse_snapshot(fmt: str, data: bytes):
    """Parse and schema-check one snapshot. Returns (obj, raw counts). Raises ValidationError."""
    try:
        obj = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise ValidationError(f"not valid JSON: {e}") from e

    def need(cond, msg):
        if not cond:
            raise ValidationError(f"schema: {msg}")

    if fmt == "bitcoin-data-v1":
        need(isinstance(obj, dict), "top level is not an object")
        for key in ("coinbase_tags", "payout_addresses"):
            need(isinstance(obj.get(key), dict), f"'{key}' missing or not an object")
            for k, v in obj[key].items():
                need(isinstance(k, str) and isinstance(v, dict) and isinstance(v.get("name"), str)
                     and v["name"].strip(), f"{key}[{k!r}] has no pool name")
        pools = {v["name"] for k in ("coinbase_tags", "payout_addresses") for v in obj[k].values()}
        return obj, {"coinbase_tags": len(obj["coinbase_tags"]), "payout_addresses": len(obj["payout_addresses"]),
                     "pools": len(pools)}
    if fmt == "mempool-v2":
        need(isinstance(obj, list) and obj, "top level is not a non-empty list")
        for i, p in enumerate(obj):
            need(isinstance(p, dict), f"entry {i} is not an object")
            need(isinstance(p.get("name"), str) and p["name"].strip(), f"entry {i} has no name")
            need(isinstance(p.get("id"), int), f"entry {i} ({p.get('name')}) has no integer id")
            pats = p.get("tags", p.get("regexes"))
            need(isinstance(pats, list) and all(isinstance(x, str) for x in pats),
                 f"entry {i} ({p['name']}) has no list of tags/regexes")
            need(isinstance(p.get("addresses", []), list) and all(isinstance(x, str) for x in p.get("addresses", [])),
                 f"entry {i} ({p['name']}) addresses is not a list of strings")
        return obj, {"regexes": sum(len(p.get("tags", p.get("regexes", []))) for p in obj),
                     "payout_addresses": sum(len(p.get("addresses", [])) for p in obj), "pools": len(obj)}
    raise ValidationError(f"unknown format {fmt!r}")


def check_entries(fmt: str, obj) -> tuple[dict, dict]:
    """Per-entry checks. Returns (problems, usable counts). Problems: rejected entries (they can never match or
    would match everything) and non-mainnet addresses (skipped; expected in mempool's list)."""
    problems = {"rejected": [], "non_mainnet_addresses": []}
    addrs, pats, tags = [], [], []
    if fmt == "bitcoin-data-v1":
        addrs = [(a, v["name"]) for a, v in obj["payout_addresses"].items()]
        tags = [(t, v["name"]) for t, v in obj["coinbase_tags"].items()]
    else:
        for p in obj:
            addrs += [(a, p["name"]) for a in p.get("addresses", [])]
            pats += [(t, p["name"]) for t in p.get("tags", p.get("regexes", []))]
    good_addrs = good_pats = good_tags = 0
    pools = set()
    for a, name in addrs:
        try:
            addr_to_script(a)
            good_addrs += 1
            pools.add(name)
        except (ValueError, IndexError) as e:
            if a.lower().startswith(NON_MAINNET_PREFIXES):
                problems["non_mainnet_addresses"].append({"address": a, "pool": name})
            else:
                problems["rejected"].append({"kind": "address", "key": a, "pool": name, "error": str(e)})
    for t, name in pats:
        err = regex_problem(t)
        if err:
            problems["rejected"].append({"kind": "regex", "key": t, "pool": name, "error": err})
        else:
            good_pats += 1
            pools.add(name)
    for t, name in tags:
        if not t.strip():
            problems["rejected"].append({"kind": "tag", "key": t, "pool": name, "error": "empty tag"})
        else:
            good_tags += 1
            pools.add(name)
    usable = {"payout_addresses": good_addrs, "pools": len(pools)}
    usable["regexes" if fmt == "mempool-v2" else "coinbase_tags"] = good_pats if fmt == "mempool-v2" else good_tags
    return problems, usable


def validate(fmt: str, data: bytes, baseline_usable: dict | None, max_drop: float = MAX_DROP):
    """Full validation of a candidate snapshot against the last good one. Raises ValidationError."""
    obj, counts = parse_snapshot(fmt, data)
    problems, usable = check_entries(fmt, obj)
    if baseline_usable:
        drops = []
        for k, old in baseline_usable.items():
            new = usable.get(k, 0)
            if old and (old - new) / old > max_drop:
                drops.append(f"{k} {old} -> {new} (-{(old - new) / old:.0%})")
        if drops:
            raise ValidationError(f"usable entries dropped by more than {max_drop:.0%}: " + "; ".join(drops))
    return obj, counts, usable, problems


def baseline(fmt: str, path: Path) -> dict | None:
    """Usable counts of the last good snapshot (the file in data/raw/)."""
    try:
        obj, _ = parse_snapshot(fmt, path.read_bytes())
        return check_entries(fmt, obj)[1]
    except (OSError, ValidationError):
        return None


# ---------------------------------------------------------------------------
# Registry diff
# ---------------------------------------------------------------------------
def _slugs(reg: dict) -> set:
    return ({v["slug"] for v in reg.get("coinbase_tags", {}).values()}
            | {r["slug"] for r in reg.get("regexes", [])}
            | {v["slug"] for v in reg.get("payout_addresses", {}).values()})


def registry_diff(old: dict, new: dict, old_conflicts: list, new_conflicts: list) -> dict:
    out = {"registry_version": [old.get("registry_version"), new.get("registry_version")]}
    for key in ("coinbase_tags", "payout_addresses"):
        o, n = old.get(key, {}), new.get(key, {})
        out[key] = {
            "added": [{"key": k, "slug": n[k]["slug"], "source": n[k]["source"]} for k in sorted(set(n) - set(o))],
            "removed": [{"key": k, "slug": o[k]["slug"], "source": o[k]["source"]} for k in sorted(set(o) - set(n))],
            "changed": [{"key": k, "from": o[k]["slug"], "to": n[k]["slug"], "source": n[k]["source"]}
                        for k in sorted(set(o) & set(n)) if o[k]["slug"] != n[k]["slug"]],
        }
    ro = {(r["pattern"], r["slug"]): r["source"] for r in old.get("regexes", [])}
    rn = {(r["pattern"], r["slug"]): r["source"] for r in new.get("regexes", [])}
    out["regexes"] = {
        "added": [{"key": p, "slug": s, "source": rn[(p, s)]} for p, s in sorted(set(rn) - set(ro))],
        "removed": [{"key": p, "slug": s, "source": ro[(p, s)]} for p, s in sorted(set(ro) - set(rn))],
    }
    so, sn = _slugs(old), _slugs(new)
    out["pools"] = {"added": sorted(sn - so), "removed": sorted(so - sn)}
    co = {(c["kind"], c["key"]): c for c in old_conflicts}
    cn = {(c["kind"], c["key"]): c for c in new_conflicts}
    out["conflicts"] = {
        "added": [cn[k] for k in sorted(set(cn) - set(co))],
        "removed": [co[k] for k in sorted(set(co) - set(cn))],
        "total": len(cn),
    }
    vo, vn = old.get("validation", {}), new.get("validation", {})
    out["validation_new"] = {
        "rejected_regexes": [r for r in vn.get("rejected_regexes", []) if r not in vo.get("rejected_regexes", [])],
        "undecoded_addresses": [r for r in vn.get("undecoded_addresses", [])
                                if r not in vo.get("undecoded_addresses", [])],
    }
    return out


def diff_counts(d: dict) -> str:
    parts = []
    for key, label in (("coinbase_tags", "tags"), ("regexes", "regexes"), ("payout_addresses", "addresses")):
        x = d[key]
        bits = [f"+{len(x['added'])}" if x["added"] else "", f"-{len(x['removed'])}" if x["removed"] else "",
                f"~{len(x.get('changed', []))}" if x.get("changed") else ""]
        if any(bits):
            parts.append(f"{label} {' '.join(b for b in bits if b)}")
    if d["pools"]["added"] or d["pools"]["removed"]:
        parts.append(f"pools +{len(d['pools']['added'])} -{len(d['pools']['removed'])}")
    if d["conflicts"]["added"] or d["conflicts"]["removed"]:
        parts.append(f"conflicts +{len(d['conflicts']['added'])} -{len(d['conflicts']['removed'])}")
    return ", ".join(parts) or "no entry changes"


def print_diff(d: dict, limit: int = 25) -> None:
    print(f"  registry {d['registry_version'][0]} -> {d['registry_version'][1]}: {diff_counts(d)}")
    for key in ("coinbase_tags", "regexes", "payout_addresses"):
        for kind in ("added", "removed", "changed"):
            rows = d[key].get(kind, [])
            for r in rows[:limit]:
                extra = f"{r['from']} -> {r['to']}" if kind == "changed" else r["slug"]
                print(f"    {key} {kind}: {r['key']!r} {extra} ({r['source']})")
            if len(rows) > limit:
                print(f"    ... {len(rows) - limit} more {key} {kind}")
    for kind in ("added", "removed"):
        if d["pools"][kind]:
            print(f"    pools {kind}: {', '.join(d['pools'][kind])}")
        for c in d["conflicts"][kind]:
            print(f"    conflict {kind}: {c['kind']} {c['key']!r} -> {c['winner']} ({c['winner_source']}); "
                  f"candidates {[(x['source'], x['slug']) for x in c['candidates']]}")
    for r in d["validation_new"]["rejected_regexes"]:
        print(f"    regex rejected: {r['pattern']!r} ({r['slug']}): {r['error']}")


# ---------------------------------------------------------------------------
# Blocks that would change (dry run)
# ---------------------------------------------------------------------------
def blocks_that_would_change(candidate: dict, workers: int) -> dict:
    import pandas as pd
    from resolve_blocks import ATTRIBUTION, COINBASE, resolve, summarise_relabels
    if not (COINBASE.exists() and ATTRIBUTION.exists()):
        return {"error": "data/raw/coinbase_blocks.parquet or data/processed/block_attribution.parquet missing; "
                         "run extract_coinbase.py and resolve_blocks.py first"}
    cb = pd.read_parquet(COINBASE)
    prev = pd.read_parquet(ATTRIBUTION, columns=["height", "pool_slug", "method"])
    cb = cb[cb["height"] <= prev["height"].max()]
    new = resolve(cb, candidate, workers)
    return summarise_relabels(prev, new)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="Refresh the upstream pool lists (fetch, validate, merge).")
    ap.add_argument("--dry-run", action="store_true",
                    help="fetch into a temp dir, print the diff and the blocks that would change; write nothing")
    ap.add_argument("--pin", action="append", default=[], metavar="SOURCE=SHA",
                    help="use this commit for SOURCE instead of the newest one (repeatable)")
    ap.add_argument("--offline", action="store_true", help="no network: check snapshots and rebuild the registry")
    ap.add_argument("--max-drop", type=float, default=MAX_DROP)
    ap.add_argument("--stale-days", type=float, default=STALE_DAYS)
    ap.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1))
    ap.add_argument("--no-block-check", action="store_true", help="dry run: skip the blocks-would-change count")
    ap.add_argument("--report-out", default=None,
                    help=f"write the run report here (default {RUN_REPORT.relative_to(ROOT)}; a dry run writes one "
                         f"only when this is given)")
    a = ap.parse_args()

    from build_pools_lookup import build

    lock = load_json(LOCK)
    if not lock or not lock.get("sources"):
        print(f"ERROR: {LOCK} missing or empty", file=sys.stderr)
        return 1
    pins = {}
    for p in a.pin:
        name, _, sha = p.partition("=")
        if name not in lock["sources"] or not sha:
            print(f"ERROR: --pin {p!r}: expected SOURCE=SHA with SOURCE in {sorted(lock['sources'])}",
                  file=sys.stderr)
            return 1
        pins[name] = sha

    now = now_utc()
    status_prev = load_json(STATUS, {}) or {}
    report = {"run_at": now.isoformat(), "dry_run": a.dry_run, "sources": {}, "alerts": [], "warnings": [],
              "registry_changed": False}
    cur_registry = load_json(REGISTRY, {}) or {}
    cur_conflicts = (load_json(CONFLICTS, {}) or {}).get("conflicts", [])
    report["registry_version_before"] = cur_registry.get("registry_version")

    tmp = tempfile.TemporaryDirectory(prefix="pool_refresh_") if a.dry_run else None
    stage_dir = Path(tmp.name) if tmp else RAW
    staged: dict[str, Path] = {}             # source -> staged candidate file
    new_lock = copy.deepcopy(lock)
    checked: dict[str, str] = {}             # source -> time of a successful upstream check

    try:
        for name, src in lock["sources"].items():
            r = report["sources"][name] = {"repo": src["repo"], "branch": src["branch"], "file": src["file"],
                                           "pinned_sha": src["sha"]}
            local = ROOT / src["local"]
            local_ok = local.exists() and md5(local.read_bytes()) == src["md5"]
            if not local_ok:
                r["local_integrity"] = "snapshot missing or its md5 differs from the lock"
            # 1. which commit?
            if a.offline:
                r["status"] = "offline"
                if not local_ok:
                    raise RuntimeError(f"{name}: {r['local_integrity']} and --offline: cannot restore it")
                continue
            try:
                if name in pins:
                    sha, cdate = commit_date(src["repo"], pins[name])
                else:
                    sha, cdate = newest_commit(src["repo"], src["branch"], src["file"])
            except FetchError as e:
                r.update(status="fetch_failed", error=str(e))
                report["warnings"].append(f"{name}: fetch failed, keeping {src['sha'][:7]}: {e}")
                if not local_ok:
                    raise RuntimeError(f"{name}: {r['local_integrity']} and upstream unreachable") from e
                continue
            checked[name] = now.isoformat()
            r.update(head_sha=sha, head_date=cdate)
            prev_src = (status_prev.get("sources") or {}).get(name, {})
            if local_ok and (sha == src["sha"] or (sha == prev_src.get("head_sha")
                                                   and prev_src.get("head_md5") == src["md5"])):
                r["status"] = "unchanged"   # pinned commit, or a newer commit already seen with the same bytes
                continue
            # 2. download that commit's file
            try:
                data = http_get(raw_url(src["repo"], sha, src["file"]))
            except FetchError as e:
                checked.pop(name, None)
                r.update(status="fetch_failed", error=str(e))
                report["warnings"].append(f"{name}: download failed, keeping {src['sha'][:7]}: {e}")
                if not local_ok:
                    raise RuntimeError(f"{name}: {r['local_integrity']} and download failed") from e
                continue
            r["head_md5"] = md5(data)
            if md5(data) == src["md5"]:
                r["status"] = "same_content"     # e.g. a merge commit with identical bytes: keep the old pin
                if not local_ok:                 # restore a damaged snapshot from the pinned bytes
                    staged[name] = stage_dir / (Path(src["local"]).name + ".new")
                    staged[name].write_bytes(data)
                    r["status"] = "restored"
                continue
            # 3. validate against the last good snapshot
            try:
                _obj, counts, usable, problems = validate(src["format"], data, baseline(src["format"], local),
                                                          a.max_drop)
            except ValidationError as e:
                r.update(status="validation_failed", candidate_sha=sha, error=str(e))
                report["alerts"].append(f"{name}: snapshot {sha[:7]} refused, keeping {src['sha'][:7]}: {e}")
                if not local_ok:
                    raise RuntimeError(f"{name}: {r['local_integrity']} and the new snapshot is invalid") from e
                continue
            r.update(status="changed", new_sha=sha, counts=counts, usable=usable,
                     rejected_entries=problems["rejected"],
                     non_mainnet_addresses=len(problems["non_mainnet_addresses"]))
            for p in problems["rejected"]:
                report["warnings"].append(f"{name} {sha[:7]}: {p['kind']} {p['key']!r} ({p['pool']}) rejected: "
                                          f"{p['error']}")
            staged[name] = stage_dir / (Path(src["local"]).name + ".new")
            staged[name].write_bytes(data)
            new_lock["sources"][name].update(
                sha=sha, commit_date=cdate, url=raw_url(src["repo"], sha, src["file"]),
                fetched_at=now.isoformat(), md5=md5(data), counts=counts)

        # 4. candidate registry, built before anything in the repo changes
        cand_lock = copy.deepcopy(new_lock)
        for name, path in staged.items():
            cand_lock["sources"][name]["local"] = str(path)
        cand_registry, *_rest, cand_conflicts = build(write=False, lock=cand_lock, quiet=True)
        changed = cand_registry["registry_version"] != cur_registry.get("registry_version")
        report["registry_changed"] = changed
        report["registry_version"] = cand_registry["registry_version"]
        report["sources_pinned"] = {k: v["sha"] for k, v in new_lock["sources"].items()}
        if changed:
            d = registry_diff(cur_registry, cand_registry, cur_conflicts, cand_conflicts)
            report["diff"] = d
            report["diff_summary"] = diff_counts(d)
            for c in d["conflicts"]["added"]:
                report["alerts"].append(f"new conflict: {c['kind']} {c['key']!r} claimed by "
                                        f"{sorted({x['slug'] for x in c['candidates']})}; {c['winner']} "
                                        f"({c['winner_source']}) wins until the supplement decides")

        # 5a. dry run: how many blocks would change label
        if a.dry_run:
            if (changed or pins) and not a.no_block_check:
                print("Resolving every block with the candidate registry ...")
                report["blocks_would_change"] = blocks_that_would_change(cand_registry, a.workers)
            if a.report_out:
                write_json_atomic(Path(a.report_out), report)
            print_report(report)
            return 0

        # 5b. commit the new snapshots, the lock and the registry
        for name, path in staged.items():
            os.replace(path, ROOT / lock["sources"][name]["local"])
        staged.clear()
        if new_lock != lock:
            write_json_atomic(LOCK, new_lock)
        build(write=True, quiet=True)
    except Exception as e:  # noqa: BLE001 - anything here is a real failure: report it and exit 1
        report["error"] = f"{type(e).__name__}: {e}"
        report["alerts"].append(f"refresh failed: {report['error']}")
        if a.report_out or not a.dry_run:
            write_json_atomic(Path(a.report_out) if a.report_out else RUN_REPORT, report)
        print_report(report)
        return 1
    finally:
        for path in staged.values():         # candidate files left behind by a failed run
            if path.exists() and not a.dry_run:
                path.unlink()
        if tmp:
            tmp.cleanup()

    # 6. status: when each source was last checked; stale sources alert
    status = {"registry_version": report["registry_version"], "sources": {}}
    for name, src in new_lock["sources"].items():
        prev = (status_prev.get("sources") or {}).get(name, {})
        last = checked.get(name) or prev.get("checked_at") or src.get("fetched_at")
        r = report["sources"].get(name, {})
        status["sources"][name] = {"repo": src["repo"], "branch": src["branch"], "sha": src["sha"],
                                   "commit_date": src["commit_date"], "checked_at": last,
                                   # newest upstream commit seen, and its file's md5 (skip re-downloading it)
                                   "head_sha": r.get("head_sha") or prev.get("head_sha"),
                                   "head_md5": r.get("head_md5") or (src["md5"] if r.get("head_sha") == src["sha"]
                                                                     else prev.get("head_md5"))}
        age = (now - datetime.fromisoformat(last).astimezone(timezone.utc)).total_seconds() / 86400 if last else 1e9
        if age > a.stale_days:
            report["alerts"].append(f"{name}: not checked successfully for {age:.0f} days (last {last}); "
                                    f"still on {src['sha'][:7]}")
    status["checked_at"] = min(s["checked_at"] for s in status["sources"].values())[:10]
    write_json_atomic(STATUS, status)
    write_json_atomic(Path(a.report_out) if a.report_out else RUN_REPORT, report)
    print_report(report)
    return 0


def print_report(report: dict) -> None:
    tag = "[dry run] " if report.get("dry_run") else ""
    print(f"{tag}pool list refresh {report['run_at']}")
    for name, r in report["sources"].items():
        line = f"  {name:13s} {r.get('status', '?'):17s} pinned {r['pinned_sha'][:7]}"
        if r.get("head_sha"):
            line += f", newest {r['head_sha'][:7]} ({(r.get('head_date') or '')[:10]})"
        if r.get("error"):
            line += f": {r['error']}"
        print(line)
        for p in r.get("rejected_entries", []):
            print(f"      rejected {p['kind']} {p['key']!r} ({p['pool']}): {p['error']}")
    if report.get("registry_version"):
        print(f"  registry {report.get('registry_version_before')} -> {report['registry_version']}"
              f" ({'changed' if report['registry_changed'] else 'unchanged'})")
    if report.get("diff"):
        print_diff(report["diff"])
    b = report.get("blocks_would_change")
    if b:
        if b.get("error"):
            print(f"  blocks: {b['error']}")
        else:
            print(f"  blocks that would change label: {b['blocks_changed']:,} of {b['blocks_compared']:,}")
            for t in b["transitions"][:25]:
                print(f"    {t['from']} -> {t['to']}: {t['blocks']:,} (heights {fmt_ranges(t['heights'])})")
    for w in report["warnings"]:
        print(f"  WARNING: {w}")
    for al in report["alerts"]:
        print(f"  ALERT: {al}")


def fmt_ranges(ranges, limit: int = 6) -> str:
    s = [f"{x[0]:,}-{x[1]:,}" if isinstance(x, list) else f"{x:,}" for x in ranges[:limit]]
    return ", ".join(s) + (f", ... ({len(ranges) - limit} more)" if len(ranges) > limit else "")


if __name__ == "__main__":
    sys.exit(main())
