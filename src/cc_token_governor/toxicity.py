from __future__ import annotations

import re


TOXIC_PATTERNS = [
    (r"(^|/)node_modules/", "dependency"),
    (r"(^|/)vendor/", "dependency"),
    (r"(^|/)dist/", "build_output"),
    (r"(^|/)build/", "build_output"),
    (r"(^|/)\.next/", "build_output"),
    (r"(^|/)coverage/", "generated"),
    (r"(^|/)\.git/", "vcs"),
    (r"(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|Cargo\.lock|Gemfile\.lock)$", "lockfile"),
    (r"\.(png|jpg|jpeg|gif|ico|svg|webp|pdf|zip|tar|gz|7z|rar)$", "binary_or_media"),
]


def classify_toxic(file_path: str) -> str | None:
    normalized = file_path.replace("\\", "/").lower()
    for pattern, category in TOXIC_PATTERNS:
        if re.search(pattern, normalized):
            return category
    return None
