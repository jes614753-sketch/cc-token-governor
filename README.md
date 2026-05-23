# cc-token-governor

`cc-token-governor` is a **policy-driven, local-first runtime governor** for Claude Code. It audits JSONL sessions, detects wasteful behavior patterns, compiles enforcement policies, and runs lightweight hooks that warn or block repeated waste before it burns more context.

It is not a token dashboard. The goal is to help Claude Code finish the task with fewer repeated reads, huge shell outputs, blind retries, and whole-file rewrites.

## What's New in 2.0.2

- **Toxic file policies now work at runtime**: Compiled `avoid-toxic-files` policies receive a real `toxic_file_path` signal for `Read`, `Edit`, `Write`, and `MultiEdit`.
- **Hook examples fixed**: README examples now show the Claude Code `hookSpecificOutput` shape instead of the internal evaluator shape.

## What's New in 2.0.1

- **Claude Code hooks format**: Hook output now uses official `hookSpecificOutput.permissionDecision` format. `warn` policies output `permissionDecision: "allow"` + `additionalContext`. `block` policies output `permissionDecision: "deny"`.
- **Portable install-hooks**: `--portable` flag generates `python -m cc_token_governor.cli` commands (no repo path needed). `--relative` flag for relative paths.
- **Environment variable support**: `CC_GOVERNOR_DB` and `CC_GOVERNOR_STATE` env vars for DB/state path override. Falls back to project-local if home dir is not writable.

## What's New in 2.0

- **Policy-driven runtime**: The `governor-policy.json` file now actually drives hook decisions. No more hardcoded logic — policies are compiled into an evaluator that produces runtime decisions.
- **SQLite state management**: Runtime state (reads, failed commands, events) is stored in SQLite with WAL mode, replacing the fragile JSON file. Transactions, crash recovery, and concurrent safety included.
- **JSONL schema version detection**: The reader detects the JSONL format version and gracefully degrades on unknown schemas instead of silently producing wrong results.
- **Comprehensive test suite**: 74 tests covering evaluator, sniffers, hook runner, CLI, JSONL reader edge cases, and more.
- **MIT License**: Now properly licensed for use, distribution, and modification.

## Architecture

```
audit/jsonl_reader.py   → Read & version-detect JSONL sessions
diagnosis/sniffers.py   → Detect 5 waste patterns
policy/compiler.py      → Compile findings into policy JSON
policy/evaluator.py     → Evaluate tool calls against policies (NEW)
runtime/hook_runner.py  → Policy-driven hook execution
runtime/state.py        → SQLite-backed state store
learning/store.py       → SQLite learning store with FTS5
```

**Safety invariants** (non-configurable): State corruption protection, hook timeout protection.

**Governor rules** (policy-driven): Repeated reads, death loops, large edits, risky output, plus toxic files when audit findings compile an `avoid-toxic-files` policy.

## Install

```bash
pip install -e .
```

Use `cc-governor install-hooks --portable` after installing the package. The portable hook snippet uses `python -m cc_token_governor.cli`, so Python must be able to import the installed package.

## Quick Start

```bash
# Audit a session
cc-governor audit --path tests/fixtures/waste_session.jsonl --json
cc-governor audit --path tests/fixtures/waste_session.jsonl --output audit.json

# Compile audit findings into policies
cc-governor compile-policy --input audit.json --output governor-policy.json

# Run hooks with the policy file
python hooks/pre_tool_use.py --policy governor-policy.json < tests/fixtures/repeated_read_payload.json
python hooks/post_tool_use.py < tests/fixtures/failed_bash_result_payload.json
```

## Policy-Driven Decisions

The evaluator loads `governor-policy.json` and matches each tool call against policy triggers:

```json
{
  "schema_version": 1,
  "policies": [
    {
      "id": "avoid-repeated-read",
      "trigger": {"tool_name": "Read", "same_file_read_count_gte": 2},
      "action": "warn",
      "message": "This file was already read in this session.",
      "confidence": "high"
    }
  ]
}
```

Trigger conditions: `tool_name`, `*_gte` (numeric thresholds), `*_lte`, boolean flags. The first matching policy wins.

## Learning

```bash
cc-governor learn "不要全量重写文件，优先使用局部 patch" --project .
cc-governor suggest --prompt "帮我修复测试失败" --project .
```

The learning store is local SQLite with FTS5 full-text search. No data is uploaded.

## Claude Code Hook Shape

```json
{
  "session_id": "demo",
  "tool_name": "Read",
  "tool_input": {"file_path": "src/app.py"}
}
```

Output:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "allow",
    "additionalContext": "This file was already read in this session."
  },
  "policy_id": "avoid-repeated-read"
}
```

## Safety Defaults

- Repeated reads **warn**, they do not block.
- Repeated failed commands **block** only when the same command has failed twice before.
- Large edit/write calls **warn**, they do not block.
- Command text is local only and shortened in reports.
- State corruption triggers an immediate **block** with a clear error message.

## Development

```bash
python -m unittest discover -s tests -v
python -m compileall -q src hooks tests
```

## License

MIT — see [LICENSE](LICENSE).
