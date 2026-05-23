##
## techne — Makefile
## Wraps the validate.yml pipeline behind the canonical target vocabulary
## that techne itself documents at docs/conventions.md.
##

.PHONY: help check-env setup manifests frontmatter fix lint shellcheck guards test validate build ci clean docs
.DEFAULT_GOAL := help

check-env:              ## Verify required tools are on PATH
	@command -v uv >/dev/null || { echo "uv not on PATH (https://docs.astral.sh/uv/)"; exit 1; }

setup: check-env        ## Install dev dependencies (uv sync)
	@uv sync

manifests:              ## Verify plugin + marketplace manifest JSON (stdlib json.tool)
	@uv run python -m json.tool .claude-plugin/marketplace.json >/dev/null
	@uv run python -m json.tool plugins/techne/.claude-plugin/plugin.json >/dev/null

frontmatter:            ## Verify SKILL.md frontmatter + theoros structural checks
	@uv run python scripts/validate_skill_frontmatter.py
	@bash scripts/check_theoros_skill.sh

fix:                    ## Auto-fix ruff issues in scripts/
	@uv run ruff check --fix scripts/
	@uv run ruff format scripts/

lint:                   ## ruff check + format check on scripts/
	@uv run ruff check scripts/
	@uv run ruff format --check scripts/

shellcheck:             ## shellcheck on scripts/*.sh (via shellcheck-py PyPI binary)
	@uv run shellcheck --severity=warning scripts/*.sh

guards:                 ## Stale-path + legacy-name grep guards
	@if grep -rn '\.claude/skills/_shared' plugins/techne/skills/; then \
		echo "FAIL: SKILL.md still references the old absolute _shared path"; exit 1; \
	fi
	@if grep -rohE 'aj-(audit|auto-commit|ci-audit|deslop|docs-site|docsync|reslop|sisters)' plugins/techne/skills/; then \
		echo "FAIL: SKILL.md still references aj-* names"; exit 1; \
	fi

test: manifests frontmatter guards  ## Structural checks (manifests + frontmatter + guards)

validate: lint shellcheck test  ## Fast pre-push gate

build:                  ## Build docs site (strict; mirrors docs.yml deploy)
	@uv run zensical build --clean --strict

ci: setup validate build  ## Mirror CI end-to-end (validate.yml + docs.yml build)

clean:                  ## Remove ruff + build caches
	@rm -rf .ruff_cache .pytest_cache site/

# Interactive — marked do_not_run in .claude/skill-context.md
docs:                   ## Serve docs site locally (do-not-run)
	@uv run zensical serve

help:                   ## Show this help
	@grep -hE '^[a-zA-Z][a-zA-Z0-9_-]*:.*?##' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'
