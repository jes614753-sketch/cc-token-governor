from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cc_token_governor.audit.jsonl_reader import read_tool_calls
from cc_token_governor.diagnosis.sniffers import audit_tool_calls
from cc_token_governor.learning.store import LearningStore
from cc_token_governor.models import AuditReport
from cc_token_governor.policy.compiler import compile_policies, load_findings, write_policy_file
from cc_token_governor.runtime.hook_runner import run_post_tool_use, run_pre_tool_use, run_user_prompt_submit


def cmd_audit(args: argparse.Namespace) -> int:
    tool_calls = read_tool_calls(args.path)
    findings = audit_tool_calls(tool_calls)
    report = AuditReport(
        schema_version=1,
        source={"path": str(args.path or "~/.claude/projects"), "tool_call_count": len(tool_calls)},
        tool_calls=tool_calls,
        findings=findings,
    ).to_dict()
    if args.output:
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json or not args.output:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def cmd_compile_policy(args: argparse.Namespace) -> int:
    findings = load_findings(args.input)
    policies = compile_policies(findings)
    write_policy_file(policies, args.output)
    print(f"Wrote {len(policies)} policies to {args.output}")
    return 0


def cmd_learn(args: argparse.Namespace) -> int:
    store = LearningStore(args.db)
    rule_id = store.learn(
        args.correction,
        project_root=args.project,
        tool_name=args.tool_name or "",
        file_glob=args.file_glob or "",
    )
    print(f"Learned rule #{rule_id}")
    return 0


def cmd_suggest(args: argparse.Namespace) -> int:
    store = LearningStore(args.db)
    rules = store.suggest(args.prompt, project_root=args.project, limit=args.limit)
    print(json.dumps({"rules": rules}, ensure_ascii=False, indent=2))
    return 0


def cmd_explain(args: argparse.Namespace) -> int:
    """Show all learned rules for a project (auditable)."""
    store = LearningStore(args.db)
    rules = store.list_rules(project_root=args.project, limit=args.limit)
    print(json.dumps({"rules": rules, "count": len(rules)}, ensure_ascii=False, indent=2))
    return 0


def cmd_clear_rules(args: argparse.Namespace) -> int:
    """Clear all learned rules for a project."""
    store = LearningStore(args.db)
    count = store.clear_rules(project_root=args.project)
    print(f"Cleared {count} rules for project {args.project}")
    return 0


def cmd_hook_pre(args: argparse.Namespace) -> int:
    payload = json.load(sys.stdin)
    result = run_pre_tool_use(payload, policy_path=args.policy, state_path=args.state)
    print(json.dumps(result, ensure_ascii=False))
    return 0


def cmd_hook_post(args: argparse.Namespace) -> int:
    payload = json.load(sys.stdin)
    result = run_post_tool_use(payload, state_path=args.state)
    print(json.dumps(result, ensure_ascii=False))
    return 0


def cmd_hook_prompt(args: argparse.Namespace) -> int:
    payload = json.load(sys.stdin)
    result = run_user_prompt_submit(payload, db_path=args.db, limit=args.limit)
    print(json.dumps(result, ensure_ascii=False))
    return 0


def cmd_install_hooks(args: argparse.Namespace) -> int:
    if args.portable:
        pre = "python -m cc_token_governor.cli hook-pre-tool-use --policy governor-policy.json"
        post = "python -m cc_token_governor.cli hook-post-tool-use"
        prompt = "python -m cc_token_governor.cli hook-user-prompt-submit"
    elif args.relative:
        root = Path(args.root)
        pre = f"python {root / 'hooks' / 'pre_tool_use.py'} --policy governor-policy.json"
        post = f"python {root / 'hooks' / 'post_tool_use.py'}"
        prompt = f"python {root / 'hooks' / 'user_prompt_submit.py'}"
    else:
        root = Path(args.root).resolve()
        pre = f"python {root / 'hooks' / 'pre_tool_use.py'} --policy governor-policy.json"
        post = f"python {root / 'hooks' / 'post_tool_use.py'}"
        prompt = f"python {root / 'hooks' / 'user_prompt_submit.py'}"

    config = {
        "hooks": {
            "PreToolUse": [{"command": pre}],
            "PostToolUse": [{"command": post}],
            "UserPromptSubmit": [{"command": prompt}],
        }
    }
    print(json.dumps(config, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Claude Code Token Governor")
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit", help="Audit Claude Code JSONL sessions")
    audit.add_argument("--path", default=None, help="JSONL file or projects directory")
    audit.add_argument("--json", action="store_true", help="Print JSON report")
    audit.add_argument("--output", "-o", default=None, help="Write audit report JSON")
    audit.set_defaults(func=cmd_audit)

    compile_policy = sub.add_parser("compile-policy", help="Compile audit findings into policies")
    compile_policy.add_argument("--input", required=True, help="Audit report JSON")
    compile_policy.add_argument("--output", default="governor-policy.json", help="Policy output path")
    compile_policy.set_defaults(func=cmd_compile_policy)

    learn = sub.add_parser("learn", help="Learn a user correction")
    learn.add_argument("correction")
    learn.add_argument("--project", default=".")
    learn.add_argument("--db", default=None)
    learn.add_argument("--tool-name", default="")
    learn.add_argument("--file-glob", default="")
    learn.set_defaults(func=cmd_learn)

    suggest = sub.add_parser("suggest", help="Suggest learned rules for a prompt")
    suggest.add_argument("--prompt", required=True)
    suggest.add_argument("--project", default=".")
    suggest.add_argument("--db", default=None)
    suggest.add_argument("--limit", type=int, default=5)
    suggest.set_defaults(func=cmd_suggest)

    explain = sub.add_parser("explain", help="List all learned rules for a project")
    explain.add_argument("--project", default=".")
    explain.add_argument("--db", default=None)
    explain.add_argument("--limit", type=int, default=50)
    explain.set_defaults(func=cmd_explain)

    clear = sub.add_parser("clear-rules", help="Clear all learned rules for a project")
    clear.add_argument("--project", default=".")
    clear.add_argument("--db", default=None)
    clear.set_defaults(func=cmd_clear_rules)

    hook_pre = sub.add_parser("hook-pre-tool-use", help="Run PreToolUse hook from stdin")
    hook_pre.add_argument("--policy", default=None)
    hook_pre.add_argument("--state", default=None)
    hook_pre.set_defaults(func=cmd_hook_pre)

    hook_post = sub.add_parser("hook-post-tool-use", help="Run PostToolUse hook from stdin")
    hook_post.add_argument("--state", default=None)
    hook_post.set_defaults(func=cmd_hook_post)

    hook_prompt = sub.add_parser("hook-user-prompt-submit", help="Run UserPromptSubmit hook from stdin")
    hook_prompt.add_argument("--db", default=None)
    hook_prompt.add_argument("--limit", type=int, default=5)
    hook_prompt.set_defaults(func=cmd_hook_prompt)

    install = sub.add_parser("install-hooks", help="Print Claude Code hook config snippet")
    install.add_argument("--root", default=".")
    install.add_argument("--portable", action="store_true", help="Use python -m cc_token_governor.cli (no repo path needed)")
    install.add_argument("--relative", action="store_true", help="Use relative paths instead of absolute")
    install.set_defaults(func=cmd_install_hooks)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
