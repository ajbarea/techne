# `techne:reslop`

Rewrites docstrings and comments by reading the actual implementation, call sites, and tests. Produces grounded, factual prose instead of deleting slop.

## When to use

- You want to replace overhyped or hallucinated documentation with accurate one- or two-line descriptions derived from what the code actually does.
- A function's docstring contradicts its behavior and needs a rewrite, not a delete.
- You want fresh docstrings that cite the real input/output shape, not the AI-generated wishful thinking.
- After major refactors: regenerate docstrings to match new implementations.

## How it differs from `deslop`

| Skill | What it does |
|---|---|
| [`techne:deslop`](deslop.md) | Identifies slop, proposes tightened (or removed) rewrites. |
| `techne:reslop` | Reads the implementation and produces grounded replacement prose. |

Use `deslop` first for triage. Use `reslop` when the answer is "this needs better prose, not less prose."

## Usage

```bash
# Rewrite docstrings across the codebase
techne:reslop

# Rewrite specific file(s)
techne:reslop src/auth.py src/parser.py

# Show proposed rewrites, don't apply
techne:reslop --dry-run
```

## Configuration

Optional `.claude/skill-context.md`:

```yaml
reslop:
  file_patterns:
    - "**/*.py"
  skip_functions:
    - "__init__"
    - "__repr__"
  style: "one-liner"  # one-liner, multi-line
```

## What it reads

- The function or class body.
- Call sites (who invokes it, with what arguments).
- Tests (what inputs and outputs are actually exercised).
- Adjacent docs (for tone consistency).
- Type hints (infer input/output shape).

## What it produces

Updated docstrings as a diff. Examples:

```python
# Before
def fetch_user(user_id):
    """
    This function is a comprehensive user fetching solution that retrieves
    user information from the database with error handling and logging.
    It takes a user ID as input and returns the user object if found.
    """
    logger.info(f"Fetching user {user_id}")
    try:
        return db.get(User, user_id)
    except NotFoundError:
        return None

# After
def fetch_user(user_id: int) -> Optional[User]:
    """Retrieve user by ID; return None if not found."""
    logger.info(f"Fetching user {user_id}")
    try:
        return db.get(User, user_id)
    except NotFoundError:
        return None
```

## Troubleshooting

**"Rewrites are too terse"**: Increase `style` to "multi-line" for richer prose.

**"Rewrites miss important details"**: Ensure the tests cover the edge cases. If they don't, the skill will miss them. Add tests first, then re-run.

## See also

- [`techne:deslop`](deslop.md) — identifies and trims AI-generated slop.
- [`techne:docsync`](docsync.md) — verifies docstring claims against reality.
