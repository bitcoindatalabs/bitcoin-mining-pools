"""
pool_resolver.py
The one block -> mining pool resolver. Everything that labels blocks uses it: resolve_blocks.py in this repo and
python/automation/miner_data_updater.py (which imports this file from the repo's scripts/ directory).

Input is a registry: the merged pool list written by build_pools_lookup.py
(dashboard/data/lookup/pools_enriched.json), passed as a path or as an already-loaded dict. The resolver reads no
other file.

Registry entries used here:
  coinbase_tags     {tag: {slug, name, source}}       exact, case-sensitive substring of the coinbase scriptSig
  regexes           [{pattern, slug, name, source}]   mempool's JS regexes, case-insensitive (as mempool runs them)
  payout_addresses  {address: {slug, name, source}}   exact scriptPubKey match against a coinbase output
  generic_tags      [tag or pattern]                  tags that name pool *software* (bare 'ckpool', 'BTCPool'),
                                                      not a pool; KanoPool blocks carry 'ckpool' next to '/Kano'
  generic_slugs     [slug]                            every tag of these slugs is generic
  payout_to_miners_slugs [slug]                       pools whose coinbase outputs pay miners (rule 2 exception)
  source_rank       {source: rank}                    tie-break between equally long tag matches (lower wins)

Precedence for one block:
  1. specific coinbase tag or regex. Among all hits the longest matched text wins; ties go to the source with the
     lower rank (supplement < mempool < bitcoin-data), then to the longer pattern.      method 'tag' | 'regex'
  2. payout address: the first coinbase output, in vout order, whose script is a known payout script.
     When rule 1 and rule 2 both apply and disagree, the payout address wins (method 'payout'): the tag is then
     a sub-account, worker or proxy name inside another pool's coinbase ("/ViaBTC/Trustpool/", BTC.com
     "eu/Bitdeer/", Huobi "bj/TMSPOOL/", F2Pool "Mined by emcd"), and the pool that was paid is the pool.
     Exception: the tag wins when its pool pays its miners directly in the coinbase (registry
     payout_to_miners_slugs: OCEAN, Eligius, ckpool.org, solo pools), because there the outputs are miners.
                                                                                          method 'payout'
  3. the frozen jlopp label (heights <= 869,305 only), after slug aliases, when not unknown.
                                                                                          method 'jlopp'
  4. a generic software tag (ckpool, btcpool): a weak label used only when nothing above applies.
                                                                                          method 'tag' | 'regex'
  5. unknown.                                                                             method 'unknown'

Matching is done on the scriptSig decoded byte-for-byte as Latin-1 (like mempool's hex2ascii), so no byte is
dropped or merged. Tags and regexes are converted to the same byte space (UTF-8 encoded, read as Latin-1), so a
tag such as the F2Pool fish emoji still matches its UTF-8 bytes. Regex case folding is ASCII only.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Iterable, NamedTuple

METHODS = ("tag", "regex", "payout", "jlopp", "unknown")
# Bump when the matching rules below change; it is part of registry_version, so a rule change re-resolves blocks.
RESOLVER_VERSION = "2026-11-12.1"


# ---------------------------------------------------------------------------
# Slugs
# ---------------------------------------------------------------------------
def to_slug(name) -> str:
    """Canonical slug: lowercase, strip spaces / hyphens / underscores / dots (unchanged from the original repo)."""
    if not name or not isinstance(name, str):
        return "unknown"
    s = name.lower()
    if s == "unknown":
        return "unknown"
    for ch in (" ", "-", "_", "."):
        s = s.replace(ch, "")
    return s or "unknown"


def apply_alias(slug: str, aliases: dict) -> str:
    seen = set()
    while slug in aliases and slug not in seen:   # follow chains (a -> b -> c), stop on cycles
        seen.add(slug)
        slug = aliases[slug]
    return slug


# ---------------------------------------------------------------------------
# Address -> scriptPubKey
# ---------------------------------------------------------------------------
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B32 = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _b58decode_check(addr: str) -> bytes:
    n = 0
    for c in addr:
        n = n * 58 + _B58.index(c)
    raw = n.to_bytes(25, "big")
    data, checksum = raw[:-4], raw[-4:]
    if hashlib.sha256(hashlib.sha256(data).digest()).digest()[:4] != checksum:
        raise ValueError("bad base58 checksum")
    return data


def _bech32_polymod(values) -> int:
    gen = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    chk = 1
    for v in values:
        b = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ v
        for i in range(5):
            chk ^= gen[i] if ((b >> i) & 1) else 0
    return chk


def _segwit_decode(addr: str):
    a = addr.lower()
    pos = a.rfind("1")
    hrp, data = a[:pos], [_B32.find(c) for c in a[pos + 1:]]
    if hrp != "bc" or len(data) < 7 or -1 in data:
        raise ValueError("not a mainnet bech32 address")
    const = _bech32_polymod([ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp] + data)
    witver = data[0]
    if const != (1 if witver == 0 else 0x2BC830A3):          # bech32 for v0, bech32m for v1+
        raise ValueError("bad bech32 checksum")
    acc = bits = 0
    prog = bytearray()
    for v in data[1:-6]:
        acc = (acc << 5) | v
        bits += 5
        while bits >= 8:
            bits -= 8
            prog.append((acc >> bits) & 0xFF)
    if not 2 <= len(prog) <= 40:
        raise ValueError("bad witness program length")
    return witver, bytes(prog)


def addr_to_script(addr: str) -> bytes:
    """Mainnet address -> scriptPubKey bytes. Raises ValueError for anything else (testnet, signet, malformed)."""
    if addr.startswith("1"):
        return b"\x76\xa9\x14" + _b58decode_check(addr)[1:] + b"\x88\xac"
    if addr.startswith("3"):
        return b"\xa9\x14" + _b58decode_check(addr)[1:] + b"\x87"
    if addr.lower().startswith("bc1"):
        v, prog = _segwit_decode(addr)
        return bytes([v if v == 0 else v + 0x50, len(prog)]) + prog
    raise ValueError("not a mainnet address")


def _b58encode_check(payload: bytes) -> str:
    data = payload + hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    n, out = int.from_bytes(data, "big"), ""
    while n:
        n, r = divmod(n, 58)
        out = _B58[r] + out
    return "1" * (len(data) - len(data.lstrip(b"\0"))) + out


def _segwit_encode(witver: int, prog: bytes) -> str:
    acc = bits = 0
    data = [witver]
    for b in prog:
        acc = (acc << 8) | b
        bits += 8
        while bits >= 5:
            bits -= 5
            data.append((acc >> bits) & 31)
    if bits:
        data.append((acc << (5 - bits)) & 31)
    const = 1 if witver == 0 else 0x2BC830A3
    pm = _bech32_polymod([ord(x) >> 5 for x in "bc"] + [0] + [ord(x) & 31 for x in "bc"] + data + [0] * 6) ^ const
    return "bc1" + "".join(_B32[d] for d in data + [(pm >> 5 * (5 - i)) & 31 for i in range(6)])


def script_to_addr(script: bytes):
    """scriptPubKey -> mainnet address for P2PKH, P2SH and segwit outputs; None for anything else (bare
    pubkeys, multisig). The inverse of addr_to_script, used to report unknown blocks' payout addresses."""
    s = bytes(script)
    if len(s) == 25 and s[:3] == b"\x76\xa9\x14" and s[-2:] == b"\x88\xac":
        return _b58encode_check(b"\x00" + s[3:23])
    if len(s) == 23 and s[:2] == b"\xa9\x14" and s[-1:] == b"\x87":
        return _b58encode_check(b"\x05" + s[2:22])
    if 4 <= len(s) <= 42 and (s[0] == 0 or 0x51 <= s[0] <= 0x60) and s[1] == len(s) - 2:
        return _segwit_encode(0 if s[0] == 0 else s[0] - 0x50, s[2:])
    return None


# ---------------------------------------------------------------------------
# Regexes: mempool writes JavaScript regexes; translate the few JS-only forms
# ---------------------------------------------------------------------------
def js_regex_to_python(pattern: str) -> str:
    """JS and Python agree on everything mempool's list uses today (literals, '.', '$'). Translate the JS-only
    forms we know of; anything else that fails to compile is rejected by the caller (regex_problem):
      \\u{HHHH}      code-point escape          -> the character itself
      (?<name>...)   named group                -> (?P<name>...)
      \\k<name>      named back-reference       -> (?P=name)
      [^]            "any character" class      -> [\\s\\S]
    """
    p = re.sub(r"\\u\{([0-9a-fA-F]+)\}", lambda m: re.escape(chr(int(m.group(1), 16))), pattern)
    p = re.sub(r"\(\?<([A-Za-z_][A-Za-z0-9_]*)>", r"(?P<\1>", p)
    p = re.sub(r"\\k<([A-Za-z_][A-Za-z0-9_]*)>", r"(?P=\1)", p)
    return p.replace("[^]", r"[\s\S]")


def compile_pattern(pattern: str):
    """Compile a mempool (JS) regex the way the resolver runs it: in the Latin-1 byte space, ASCII case folding."""
    return re.compile(_to_bytespace(js_regex_to_python(pattern)), re.IGNORECASE | re.ASCII)


def regex_problem(pattern: str):
    """Why a regex must not be used, or None. A regex that fails to compile in Python, or that matches the empty
    string (it would label every block), is rejected."""
    try:
        rx = compile_pattern(pattern)
    except re.error as e:
        return f"does not compile in Python: {e}"
    if rx.search("") is not None:
        return "matches the empty string (would match every block)"
    return None


def _to_bytespace(s: str) -> str:
    """Text as it appears in a Latin-1 decoded scriptSig: UTF-8 bytes, one char per byte."""
    return s.encode("utf-8").decode("latin-1")


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------
class Attribution(NamedTuple):
    slug: str
    method: str             # tag | regex | payout | jlopp | unknown
    tag: str | None         # the coinbase tag / regex that matched (for tag and regex), else None
    tag_slug: str | None    # best specific tag/regex slug, whatever won (for disagreement analysis)
    payout_slug: str | None  # payout-address slug, whatever won
    generic_slug: str | None  # generic software-tag slug, whatever won


def load_registry(registry) -> dict:
    if isinstance(registry, dict):
        return registry
    return json.loads(Path(registry).read_text(encoding="utf-8"))


class PoolResolver:
    def __init__(self, registry):
        reg = load_registry(registry)
        self.registry_version = reg.get("registry_version")
        aliases = {k: v for k, v in reg.get("slug_aliases", {}).items() if not k.startswith("_")}
        self.aliases = aliases
        rank = reg.get("source_rank", {"supplement": 0, "mempool": 1, "bitcoin-data": 2})
        generic = set(reg.get("generic_slugs", []))
        generic_tags = set(reg.get("generic_tags", []))
        self.payout_to_miners = set(reg.get("payout_to_miners_slugs", []))

        def norm(info):
            return apply_alias(info.get("slug") or to_slug(info.get("name")), aliases)

        # (needle_in_bytespace, original_tag, slug, rank, is_generic)
        self._tags = []
        for tag, info in reg.get("coinbase_tags", {}).items():
            if tag.startswith("_comment") or not tag:
                continue
            s = norm(info)
            self._tags.append((_to_bytespace(tag), tag, s, rank.get(info.get("source"), 9),
                               s in generic or tag in generic_tags))
        # (compiled, original_pattern, slug, rank, is_generic)
        self._regexes = []
        self.rejected_regexes = []
        for r in reg.get("regexes", []):
            s = norm(r)
            problem = regex_problem(r["pattern"])
            if problem:
                self.rejected_regexes.append((r["pattern"], problem))
                continue
            rx = compile_pattern(r["pattern"])
            self._regexes.append((rx, r["pattern"], s, rank.get(r.get("source"), 9),
                                  s in generic or r["pattern"] in generic_tags))
        self._scripts = {}
        self.undecoded_addresses = []
        for addr, info in reg.get("payout_addresses", {}).items():
            if addr.startswith("_comment"):
                continue
            try:
                self._scripts[addr_to_script(addr)] = norm(info)
            except (ValueError, IndexError):
                self.undecoded_addresses.append(addr)

    def slug(self, s) -> str:
        """Normalise any label (display name or slug) to the registry's canonical slug."""
        return apply_alias(to_slug(s), self.aliases)

    def tag_hits(self, scriptsig: bytes):
        """All tag / regex hits: (matched_len, rank, pattern_len, method, pattern, slug, is_generic)."""
        text = bytes(scriptsig or b"").decode("latin-1")
        hits = []
        for needle, tag, s, rk, gen in self._tags:
            if needle in text:
                hits.append((len(needle), rk, len(needle), "tag", tag, s, gen))
        for rx, pat, s, rk, gen in self._regexes:
            m = rx.search(text)
            if m:
                hits.append((m.end() - m.start(), rk, len(pat), "regex", pat, s, gen))
        return hits

    def payout_slug(self, payout_scripts: Iterable[bytes]):
        for sc in (() if payout_scripts is None else payout_scripts):
            s = self._scripts.get(bytes(sc))
            if s:
                return s
        return None

    def resolve(self, scriptsig: bytes, payout_scripts: Iterable[bytes] = (), jlopp_slug=None) -> Attribution:
        hits = self.tag_hits(scriptsig)
        best = gen = None
        if hits:
            key = lambda h: (-h[0], h[1], -h[2])      # longest match, then source rank, then longer pattern
            spec = [h for h in hits if not h[6]]
            gens = [h for h in hits if h[6]]
            best = min(spec, key=key) if spec else None
            gen = min(gens, key=key) if gens else None
        pay = self.payout_slug(payout_scripts)
        js = self.slug(jlopp_slug) if jlopp_slug else None
        tag_slug = best[5] if best else None
        gen_slug = gen[5] if gen else None
        if best and pay and best[5] != pay and best[5] not in self.payout_to_miners:
            return Attribution(pay, "payout", None, tag_slug, pay, gen_slug)
        if best:
            return Attribution(best[5], best[3], best[4], tag_slug, pay, gen_slug)
        if pay:
            return Attribution(pay, "payout", None, tag_slug, pay, gen_slug)
        if js and js != "unknown":
            return Attribution(js, "jlopp", None, tag_slug, pay, gen_slug)
        if gen:
            return Attribution(gen[5], gen[3], gen[4], tag_slug, pay, gen_slug)
        return Attribution("unknown", "unknown", None, tag_slug, pay, gen_slug)
