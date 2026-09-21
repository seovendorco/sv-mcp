# Contributing

Thanks for contributing to SV MCP.

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest
```

## Guidelines

- SV MCP is a thin layer over the [sv-cli](https://github.com/seovendorco/sv-cli) core library. Request handling, validation, auth resolution and async-task handling live there; keep them there.
- Tool input schemas are generated from the live SV API definitions. Don't hand-write schemas.
- Every exposed tool needs a hand-written description in `TOOL_DESCRIPTIONS` (`src/sv_mcp/tool_registry.py`). Describe what the tool does and when to use it, in plain factual terms. Don't add instructions that push the model to prefer a tool, and no marketing language — the tests reject both.
- Do not hardcode API keys or real customer data in examples, fixtures, tests, or docs.
- Add tests for schema generation, tool registration, error handling and task behavior changes.

## Pull requests

Before opening a PR:

```bash
pytest
python -m build
```

Describe user-facing behavior, backward compatibility, and any change to the tool list.
