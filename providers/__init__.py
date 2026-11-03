"""Answer providers. Kept outside ``sve`` so the core library never calls a model.

- ``mock``: deterministic dummy answers, for tests and dry runs
- ``manual``: paste prompts into a chat yourself, paste replies back
- ``claude_cli``: headless ``claude -p``, blind (empty temp dir, no tools,
  no CLAUDE.md, memory, skills, hooks or MCP)
"""
