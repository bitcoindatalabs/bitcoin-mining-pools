"""
unknown_watch.py
Daily watch for blocks the resolver leaves unknown, so a new pool is noticed within days.

Takes the unknown blocks of the last --days (default 7, counted back from the newest block's time), and clusters
them: two blocks are in one cluster when they share a coinbase text token or their first payout script.
  - text token: a run of >= 6 bytes from [A-Za-z0-9 ./_:@#!+=,-] in the coinbase scriptSig (after the BIP34 height
    push), with digit runs replaced by '#' and case folded, that has at least 3 letters. Random extranonce bytes
    rarely form such a run (and two equal ones almost never), so noise does not link blocks, while '/Foo12/'
    sub-accounts with changing numbers still do. Shorter tags ('Kano') do not form tokens; such blocks still
    cluster by payout script.
  - first payout script: the first non-OP_RETURN coinbase output

A cluster of --min-blocks (default 3) or more is reported with its texts, heights, payout addresses and when it was
first seen (the earliest unknown block anywhere in the chain that shares a token or script with it). A cluster is
*new* when none of its tokens or scripts was reported in the last --forget-days (default 90); new clusters are the
ones the automation sends to the ops chat. The watch also flags a pile-up: more than --max-unknown-share (default
1%) of the window's blocks unknown.

It never edits the pool list. A human or agent adds a cited entry to data/raw/pools_supplement.json.

Inputs:  data/processed/block_attribution.parquet (resolve_blocks.py), data/raw/coinbase_blocks.parquet
Output:  data/status/unknown_clusters.json (not with --dry-run)

Usage: python3 scripts/unknown_watch.py [--dry-run] [--days 7] [--min-blocks 3] [--end-height H]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent
ATTRIBUTION = ROOT / "data" / "processed" / "block_attribution.parquet"
COINBASE = ROOT / "data" / "raw" / "coinbase_blocks.parquet"
OUT = ROOT / "data" / "status" / "unknown_clusters.json"
BIP34_HEIGHT = 227_931
RUN_RE = re.compile(rb"[A-Za-z0-9 ./_:@#!+=,\-]{6,}")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pool_resolver import script_to_addr  # noqa: E402


def body(sig: bytes, height: int) -> bytes:
    sig = bytes(sig or b"")
    if height >= BIP34_HEIGHT and sig and 1 <= sig[0] <= 8:
        return sig[1 + sig[0]:]
    return sig


def runs(sig: bytes, height: int) -> list[str]:
    return [r.decode("ascii").strip() for r in RUN_RE.findall(body(sig, height))]


def tokens(sig: bytes, height: int) -> set[str]:
    out = set()
    for r in runs(sig, height):
        t = re.sub(r"\d+", "#", r).lower()
        if sum(c.isalpha() for c in t) >= 3:
            out.add(t)
    return out


def first_script(scripts) -> bytes | None:
    return bytes(scripts[0]) if scripts is not None and len(scripts) else None


class DSU:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        a, b = self.find(a), self.find(b)
        if a != b:
            self.p[max(a, b)] = min(a, b)


def iso_day(ts: int) -> str:
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")


def main() -> int:
    ap = argparse.ArgumentParser(description="Cluster recent unknown blocks and flag new clusters.")
    ap.add_argument("--dry-run", action="store_true", help="print the result; write nothing")
    ap.add_argument("--days", type=float, default=7)
    ap.add_argument("--min-blocks", type=int, default=3)
    ap.add_argument("--max-unknown-share", type=float, default=0.01)
    ap.add_argument("--forget-days", type=float, default=90,
                    help="a token or script not seen for this long can alert again")
    ap.add_argument("--end-height", type=int, default=None, help="evaluate the window ending here (tests)")
    a = ap.parse_args()

    for f in (ATTRIBUTION, COINBASE):
        if not f.exists():
            print(f"ERROR: {f} missing (run extract_coinbase.py and resolve_blocks.py first)", file=sys.stderr)
            return 1
    attr = pd.read_parquet(ATTRIBUTION, columns=["height", "time", "pool_slug"])
    version = (pq.read_schema(ATTRIBUTION).metadata or {}).get(b"registry_version", b"").decode()
    if a.end_height is not None:
        attr = attr[attr["height"] <= a.end_height]
    if attr.empty:
        print("ERROR: no attributed blocks", file=sys.stderr)
        return 1
    tip_time = int(attr["time"].iloc[-1])
    win = attr[attr["time"] >= tip_time - a.days * 86400]
    unknown_all = attr[attr["pool_slug"] == "unknown"]
    cb = pd.read_parquet(COINBASE, columns=["height", "scriptsig", "payout_scripts"])
    cb = cb[cb["height"].isin(unknown_all["height"])].merge(unknown_all[["height", "time"]], on="height")
    cb = cb.sort_values("height").reset_index(drop=True)
    cb["tokens"] = [tokens(s, h) for s, h in zip(cb["scriptsig"], cb["height"])]
    cb["script0"] = [first_script(x) for x in cb["payout_scripts"]]
    w = cb[cb["height"] >= int(win["height"].min())].reset_index(drop=True)

    # cluster the window's unknown blocks
    dsu = DSU(len(w))
    owner: dict[str, int] = {}
    for i, (toks, sc) in enumerate(zip(w["tokens"], w["script0"])):
        keys = [f"t:{t}" for t in toks] + ([f"s:{sc.hex()}"] if sc else [])
        for k in keys:
            if k in owner:
                dsu.union(owner[k], i)
            else:
                owner[k] = i
    groups: dict[int, list[int]] = {}
    for i in range(len(w)):
        groups.setdefault(dsu.find(i), []).append(i)

    prev = {}
    if OUT.exists():
        prev = json.loads(OUT.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    forget_before = (now - timedelta(days=a.forget_days)).strftime("%Y-%m-%d")
    seen = {k: v for k, v in (prev.get("seen_keys") or {}).items() if v.get("last_seen", "") >= forget_before}

    # first time each key appears among all unknown blocks in the chain
    first_by_key: dict[str, tuple[int, int]] = {}
    for h, t, toks, sc in zip(cb["height"], cb["time"], cb["tokens"], cb["script0"]):
        for k in [f"t:{x}" for x in toks] + ([f"s:{sc.hex()}"] if sc else []):
            if k not in first_by_key:
                first_by_key[k] = (int(h), int(t))

    clusters = []
    for members in groups.values():
        if len(members) < a.min_blocks:
            continue
        g = w.iloc[members]
        keys = sorted({f"t:{t}" for ts in g["tokens"] for t in ts}
                      | {f"s:{s.hex()}" for s in g["script0"] if s})
        texts = Counter(r for s, h in zip(g["scriptsig"], g["height"]) for r in runs(s, h)
                        if sum(c.isalpha() for c in r) >= 3)
        scripts = Counter(s for s in g["script0"] if s)
        fh, ft = min((first_by_key[k] for k in keys), default=(int(g["height"].min()), int(g["time"].min())))
        cid = "u-" + hashlib.sha1(keys[0].encode() if keys else b"").hexdigest()[:10]
        clusters.append({
            "id": cid,
            "blocks": int(len(g)),
            "heights": [int(h) for h in g["height"]],
            "first_block_in_window": iso_day(g["time"].min()),
            "last_block": iso_day(g["time"].max()),
            "first_seen_height": fh, "first_seen": iso_day(ft),
            "texts": [{"text": t, "blocks": n} for t, n in texts.most_common(5)],
            "payout_scripts": [{"script": s.hex(), "address": script_to_addr(s), "blocks": n}
                               for s, n in scripts.most_common(5)],
            "keys": keys,
            "new": not any(k in seen for k in keys),
        })
    clusters.sort(key=lambda c: -c["blocks"])

    alerts = []
    for c in clusters:
        if c["new"]:
            text = c["texts"][0]["text"] if c["texts"] else "(no text)"
            pay = c["payout_scripts"][0] if c["payout_scripts"] else None
            pay = (pay["address"] or pay["script"][:24] + "...") if pay else "(none)"
            hs = c["heights"]
            alerts.append(f"new unknown cluster {c['id']}: {c['blocks']} blocks in {a.days:g} days "
                          f"(heights {hs[0]:,}-{hs[-1]:,}), text {text!r}, pays {pay}, "
                          f"first seen {c['first_seen']} (height {c['first_seen_height']:,})")
        for k in c["keys"]:
            seen.setdefault(k, {"first_reported": today})["last_seen"] = today
    share = len(w) / max(1, len(win))
    if share > a.max_unknown_share:
        alerts.append(f"unknown blocks pile up: {len(w)} of {len(win)} blocks in the last {a.days:g} days "
                      f"({share:.1%}) are unknown")

    result = {
        "generated_at": now.isoformat(timespec="seconds"),
        "registry_version": version,
        "window": {"days": a.days, "from_height": int(win["height"].min()), "to_height": int(win["height"].max()),
                   "from_time": iso_day(win["time"].min()), "to_time": iso_day(win["time"].max()),
                   "blocks": int(len(win))},
        "unknown_blocks": int(len(w)),
        "unknown_share": round(share, 5),
        "unknown_heights": [int(h) for h in w["height"]],
        "min_cluster_blocks": a.min_blocks,
        "clusters": clusters,
        "new_clusters": [c["id"] for c in clusters if c["new"]],
        "alerts": alerts,
        "seen_keys": dict(sorted(seen.items())),
    }
    tag = "[dry run] " if a.dry_run else ""
    print(f"{tag}unknown watch: {len(w)} unknown of {len(win)} blocks, heights "
          f"{result['window']['from_height']:,}-{result['window']['to_height']:,} "
          f"({result['window']['from_time']} to {result['window']['to_time']}); {len(clusters)} cluster(s) of "
          f">= {a.min_blocks}, {len(result['new_clusters'])} new")
    for c in clusters:
        print(f"  {c['id']} {'NEW ' if c['new'] else ''}{c['blocks']} blocks, first seen {c['first_seen']}: "
              f"texts {[t['text'] for t in c['texts'][:3]]}, "
              f"payout {[p['address'] or p['script'][:20] for p in c['payout_scripts'][:2]]}")
    for al in alerts:
        print(f"  ALERT: {al}")
    if not a.dry_run:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        tmp = OUT.with_name(OUT.name + ".tmp")
        tmp.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, OUT)
        print(f"  wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
