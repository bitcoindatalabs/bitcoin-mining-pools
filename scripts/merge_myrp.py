"""
merge_myrp.py (deprecated, kept so older callers keep working)

Until bdl-060 this script merged bitcoin_miners_myrp.parquet / bitcoin_blocks_pool.parquet into
blocks_post_2021.parquet with a coinbase-tag-only resolver. Its `--rebuild` run in commit effa0cb (2026-04-08)
re-resolved every 2021+ block from tags alone and dropped the jlopp labels and the payout-address matches, which
left 8,736 blocks unknown. Block labels now come from one resolver (pool_resolver.py) through resolve_blocks.py,
which this file simply runs.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import resolve_blocks  # noqa: E402

if __name__ == "__main__":
    print("merge_myrp.py is deprecated; running resolve_blocks.py")
    sys.argv = [sys.argv[0]] + [a for a in sys.argv[1:] if a == "--full"] + (["--full"] if "--rebuild" in sys.argv else [])
    sys.exit(resolve_blocks.main())
