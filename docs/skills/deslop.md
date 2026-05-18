# `techne:deslop`

Scans the codebase for AI-generated slop in comments and docstrings (temporal markers, self-referential AI framing, narrative WHAT-comments, marketing padding) and proposes tightened rewrites.

## When to use

- After other AI assistants (Copilot, Gemini, GPT) have touched a repo.
- Auditing pending changes for verbose, low-value commentary.
- Cleaning up a codebase that's drifted toward over-narrated comments.
- Pre-release: eliminate slop before shipping.

## What it targets

- **Temporal markers**: "as of 2025", "currently", "now we"
- **Self-referential AI framing**: "this function helps you", "let me explain"
- **Narrative WHAT-comments**: comments that restate what the code clearly does
- **Marketing padding**: "robust", "elegant", "powerful", "seamless", "state-of-the-art"
- **Redundant docstrings**: multi-line docstrings that just repeat the function signature

## Usage

```bash
# Scan entire codebase
techne:deslop

# Scan only pending changes
techne:deslop --staged

# Scan specific file(s)
techne:deslop src/auth.py src/parser.py
```

## Configuration

Optional `.claude/skill-context.md`:

```yaml
deslop:
  file_patterns:
    - "**/*.py"
    - "**/*.ts"
    - "**/*.vue"
  skip_files:
    - "vendor/*"
    - "node_modules/*"
  strictness: "medium"  # loose, medium, strict
```

## What it produces

A diff or report of proposed rewrites. The skill doesn't auto-commit; you review the changes.

Examples:

```python
# Before
def fetch_user(user_id):
    """
    This function helps you fetch a user from the database.
    It takes a user ID and returns the user object.
    """
    return db.get(user_id)

# After
def fetch_user(user_id):
    """Retrieve user from database by ID."""
    return db.get(user_id)
```

## Troubleshooting

**"False positives"**: Increase `strictness` to "strict" to reduce noise, or skip certain patterns in skill context.

**"Too aggressive"**: Lower `strictness` to "loose". The skill is opinionated about prose quality; adjust to your taste.

## See also

- [`techne:reslop`](reslop.md) — rewrites docstrings grounded in the implementation rather than deleting them.
- [`techne:docsync`](docsync.md) — verifies documentation claims against code.

## Reads

- `<repo>/**/*.py`, `*.ts`, `*.vue`, etc. (configurable)
- Pending git diff (when scanning changes only)
