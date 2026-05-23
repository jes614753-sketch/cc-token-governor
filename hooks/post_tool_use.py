#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cc_token_governor.runtime.hook_runner import run_post_tool_use


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", default=None)
    args = parser.parse_args()
    payload = json.load(sys.stdin)
    print(json.dumps(run_post_tool_use(payload, args.state), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
