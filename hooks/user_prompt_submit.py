#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cc_token_governor.runtime.hook_runner import run_user_prompt_submit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=None)
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    payload = json.load(sys.stdin)
    print(json.dumps(run_user_prompt_submit(payload, args.db, args.limit), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
