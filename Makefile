##
## techne — Makefile
## Wraps the validate.yml pipeline behind the canonical target vocabulary
## that techne itself documents at docs/conventions.md.
##

.PHONY: help check-env setup manifests frontmatter fix lint shellcheck guards test-unit zizmor test validate build ci clean docs evals evals-bash
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

# Paths must match lint's, or fix cannot repair what lint rejects.
fix:                    ## Auto-fix ruff issues in scripts/ and skill-shipped Python
	@uv run ruff check --fix scripts/ plugins/ tests/
	@uv run ruff format scripts/ plugins/ tests/

# Covers scripts/ and any Python a skill ships. The catchup skill's sweep.py sat
# outside scripts/ and so went unlinted entirely until the paths were widened.
lint:                   ## ruff check + format check + ty on scripts/ and skill-shipped Python
	@uv run ruff check scripts/ plugins/ tests/
	@uv run ruff format --check scripts/ plugins/ tests/
	@uv run ty check scripts/ plugins/ tests/

shellcheck:             ## shellcheck on repo and skill-shipped shell scripts (shellcheck-py binary)
	@uv run shellcheck --severity=warning scripts/*.sh plugins/techne/skills/*/scripts/*.sh

# Skill names are derived from the directory listing, so a new skill is guarded
# the day it lands rather than when someone remembers to extend the pattern.
SKILL_NAMES := $(shell find plugins/techne/skills -mindepth 1 -maxdepth 1 -type d -printf '%f|' 2>/dev/null | sed 's/|$$//')
# Excluded because they name the forbidden patterns in order to document them.
GUARD_SKIP := ':!Makefile' ':!ROADMAP.md' ':!.claude/skill-context.md'

guards:                 ## Stale-path + legacy-name + action-pin guards
	@if git grep -n --untracked -E '\.claude/skills/_shared' -- $(GUARD_SKIP); then \
		echo "FAIL: still references the old absolute _shared path"; exit 1; \
	fi
	@if git grep -n --untracked -E '\baj-($(SKILL_NAMES))\b' -- $(GUARD_SKIP); then \
		echo "FAIL: still references aj-* names"; exit 1; \
	fi
	@bash scripts/check_action_pins.sh

# End-to-end cases need TeX Live (latex) and the typst wheel (pdf). Where either
# is absent, TECHNE_NO_TEX / TECHNE_NO_TYPST declares the opt-out; without the
# declaration the suite fails rather than skipping them unnoticed. The wheel is
# pulled per-run rather than pinned as a dev dependency, matching how the skill
# itself runs.
test-unit:              ## pytest over skill-shipped Python
	@uv run --with typst pytest

zizmor:                 ## zizmor GHA security scan (.github/workflows/)
	@uv run zizmor .github/workflows/

test: manifests frontmatter guards test-unit  ## Structural checks + pytest

# `build` belongs here: a dependency bump can leave lint and tests green and
# still abort the site build, and docs.yml only runs on push to main, so
# nothing else would catch it before it landed.
validate: lint shellcheck zizmor test build  ## Fast pre-push gate

build:                  ## Build docs site (strict; mirrors docs.yml deploy)
	@uv run zensical build --clean --strict

ci: setup validate      ## Mirror CI end-to-end (validate.yml, which includes the docs build)

# Routing evals run real Claude sessions on your own credential, so they cost money and
# stay out of validate. Every routing case loads stand-ins for the general document and
# catch-up skills techne shares a session with, so a collision shows up as a failed case.
# Behavior cases build a fixture repo with a scaffold script and grade what the skill produced.
evals:                  ## Routing + behavior evals (claude plugin eval; runs on your credential)
	@bash scripts/eval-plugin.sh
	@cd plugins/techne && claude plugin eval . --tag routing --ablation none --trust-plugin \
		--no-publish -j 2 --threshold 0.9
	@cd plugins/techne && claude plugin eval . --tag behavior --ablation none --trust-plugin \
		--no-publish -j 2 --threshold 0.9 --scaffold

# Cases that need Bash inside the run. The eval sandbox refuses to grant Bash on a machine
# whose Docker credential store holds a symlink (Docker Desktop's WSL integration does).
evals-bash:             ## Behavior evals that grant Bash (needs a symlink-free ~/.docker)
	@cd plugins/techne && claude plugin eval . --tag behavior-bash --ablation none \
		--trust-plugin --no-publish -j 2 --threshold 0.9 --scaffold \
		--allow-tools Write 'Bash(git *)' 'Bash(bash *)'

clean:                  ## Remove ruff + build caches
	@rm -rf .ruff_cache .pytest_cache site/

# Interactive — marked do_not_run in .claude/skill-context.md
docs:                   ## Serve docs site locally (do-not-run)
	@uv run zensical serve

help:                   ## Show this help
	@grep -hE '^[a-zA-Z][a-zA-Z0-9_-]*:.*?##' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'
