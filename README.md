# cc-token-governor

`cc-token-governor` is a local-first runtime governor for Claude Code. It reads Claude Code JSONL sessions, detects expensive behavior patterns, compiles them into policies, and runs lightweight hooks that warn or block repeated waste before it burns more context.

It is not a token dashboard. The goal is to help Claude Code finish the task with fewer repeated reads, huge shell outputs, blind retries, and whole-file rewrites.

## Features

- Audit Claude Code `~/.claude/projects/**/*.jsonl` sessions.
- Detect repeated file reads, toxic files, bloated shell output, death loops, and large edits.
- Compile findings into `governor-policy.json`.
- Run `PreToolUse` and `PostToolUse` hook scripts with a small local state file.
- Learn user corrections into SQLite and retrieve the most relevant rules for future prompts.
- Uses only the Python standard library.

## Install

```bash
pip install -e .
```

## Quick Start

```bash
cc-governor audit --path tests/fixtures/waste_session.jsonl --json
cc-governor audit --path tests/fixtures/waste_session.jsonl --output audit.json
cc-governor compile-policy --input audit.json --output governor-policy.json

python hooks/pre_tool_use.py --policy governor-policy.json < tests/fixtures/repeated_read_payload.json
python hooks/post_tool_use.py < tests/fixtures/failed_bash_result_payload.json
python hooks/pre_tool_use.py --policy governor-policy.json < tests/fixtures/death_loop_payload.json
```

## Learning

```bash
cc-governor learn "不要全量重写文件，优先使用局部 patch" --project .
cc-governor suggest --prompt "帮我修复测试失败" --project .
```

The learning store is local SQLite. No JSONL logs or source files are uploaded.

## Claude Code Hook Shape

The hook runner accepts common Claude Code-like payload shapes:

```json
{
  "session_id": "demo",
  "tool_name": "Read",
  "tool_input": {"file_path": "src/app.py"}
}
```

The output is a decision object:

```json
{
  "decision": "approve",
  "additionalContext": "This file was already read in this session. Reuse existing context unless it changed."
}
```

## Safety Defaults

- Repeated reads warn, they do not block.
- Repeated failed commands block only when the next run would be the third blind retry.
- Large edit/write calls warn, they do not block.
- Command text is local only and shortened in reports.

## Development

```bash
python -m unittest discover -s tests
python -m compileall -q src hooks tests
```
