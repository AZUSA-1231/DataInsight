# Rules

Project-local ECC rules. These extend global rules at `~/.claude/rules/ecc/`.

## Installed

| Rule Set | Source | Content |
|----------|--------|---------|
| `python/` | `~/.claude/rules/ecc/python/` | coding-style, testing, patterns, security, hooks, fastapi |
| `web/` | `~/.claude/rules/ecc/web/` | coding-style, testing, patterns, security, hooks, performance, design-quality |

## Priority

Project-local rules override global rules (specific > general).