##
## techne — Makefile
## Wraps the validate.yml pipeline behind the canonical target vocabulary
## that techne itself documents at docs/conventions.md.
##

.PHONY: help check-env setup manifests plugin-validate plugin-test test-hooks-oldest frontmatter fix lint shellcheck guards test-unit zizmor test validate build ci clean docs evals evals-bash
.DEFAULT_GOAL := help

check-env:              ## Verify required tools are on PATH
	@command -v uv >/dev/null || { echo "uv not on PATH (https://docs.astral.sh/uv/)"; exit 1; }

setup: check-env        ## Install dev dependencies (uv sync)
	@uv sync

manifests:              ## Verify plugin + marketplace manifest JSON (stdlib json.tool)
	@for f in .claude-plugin/marketplace.json plugins/*/.claude-plugin/plugin.json; do \
		uv run python -m json.tool "$$f" >/dev/null || { echo "FAIL: $$f"; exit 1; }; \
	done

# The Claude Code build plugin-validate and plugin-test run through npx, so local runs and CI
# judge the same output. Mods need 2.1.287 or later.
export CLAUDE_CODE_VERSION := 2.1.291

plugin-validate:        ## claude plugin validate on each plugin + the marketplace (hooks, userConfig)
	@bash scripts/check_plugin_manifest.sh

export TYPESCRIPT_VERSION := 7.0.2

plugin-test:            ## claude plugin test + strict tsc on each plugin that ships a hooks module
	@bash scripts/check_hooks_modules.sh

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
	@uv run shellcheck --severity=warning scripts/*.sh $(wildcard plugins/*/_shared/*.sh plugins/*/skills/*/scripts/*.sh)

# Skill names are derived from the directory listing, so a new skill is guarded
# the day it lands rather than when someone remembers to extend the pattern.
SKILL_NAMES := $(shell find plugins/*/skills -mindepth 1 -maxdepth 1 -type d -printf '%f|' 2>/dev/null | sed 's/|$$//')
# Excluded because they name the forbidden patterns in order to document them.
GUARD_SKIP := ':!Makefile' ':!ROADMAP.md' ':!.claude/skill-context.md'

# plugins/techne/_shared/ is the source for a file several plugins need; another plugin
# carries a copy, since a plugin installs alone and can't read a sibling's files.
guards:                 ## Stale-path + legacy-name + shared-copy + plugin-path + action-pin guards
	@for f in plugins/*/_shared/*; do \
		src="plugins/techne/_shared/$${f##*/}"; \
		[ -f "$$src" ] && [ "$$f" != "$$src" ] || continue; \
		cmp -s "$$f" "$$src" || { echo "FAIL: $$f differs from $$src"; exit 1; }; \
	done
	@bash scripts/check_plugin_refs.sh
	@if git grep -n --untracked -E '\.claude/skills/_shared' -- $(GUARD_SKIP); then \
		echo "FAIL: still references the old absolute _shared path"; exit 1; \
	fi
	@if git grep -n --untracked -E '\baj-($(SKILL_NAMES))\b' -- $(GUARD_SKIP); then \
		echo "FAIL: still references aj-* names"; exit 1; \
	fi
	@bash scripts/check_action_pins.sh

# End-to-end cases need TeX Live (latex), the typst wheel (pdf) and Playwright's Chromium
# (web slides). Where one is absent, TECHNE_NO_TEX / TECHNE_NO_TYPST / TECHNE_NO_BROWSER
# declares the opt-out; without the declaration the suite fails rather than skipping them
# unnoticed. The wheels are pulled per-run at the pins the skills use, rather than held as
# dev dependencies.
test-unit:              ## pytest over skill-shipped Python
	@uv run --with 'typst>=0.15,<0.16' --with playwright==1.63.0 --with axe-playwright-python==0.1.8 --with pillow pytest

# The hooks run on the user's system python3, not the project venv. 3.9 is macOS's.
HOOKS_OLDEST_PYTHON := 3.9

test-hooks-oldest:      ## Hook tests with the hook run on the oldest supported python3
	@py="$$(uv python find --no-project $(HOOKS_OLDEST_PYTHON) 2>/dev/null || { uv python install -q $(HOOKS_OLDEST_PYTHON) && uv python find --no-project $(HOOKS_OLDEST_PYTHON); })"; \
	[ -n "$$py" ] || { echo "FAIL: no Python $(HOOKS_OLDEST_PYTHON) from uv"; exit 1; }; \
	TECHNE_GUARD_PYTHON="$$py" uv run pytest tests/test_git_guards.py tests/test_stale_restart.py

zizmor:                 ## zizmor GHA security scan (.github/workflows/)
	@uv run zizmor .github/workflows/

test: manifests frontmatter guards test-unit  ## Structural checks + pytest

# `build` belongs here: a dependency bump can leave lint and tests green and
# still abort the site build, and docs.yml only runs on push to main, so
# nothing else would catch it before it landed.
validate: lint shellcheck zizmor plugin-validate plugin-test test test-hooks-oldest build  ## Fast pre-push gate

build:                  ## Build docs site (strict; mirrors docs.yml deploy)
	@uv run zensical build --clean --strict

ci: setup validate      ## Mirror CI end-to-end (validate.yml, which includes the docs build)

# Routing evals run real Claude sessions on your own login: they draw on your plan's usage,
# or bill your API key if you use one, so they stay out of validate. Every routing case
# loads stand-ins for the general document and catch-up skills its plugin shares a session
# with, so a collision shows up as a failed case.
# Behavior cases build a fixture repo with a scaffold script and grade what the skill produced.
EVAL_PLUGINS := $(patsubst %/evals,%,$(wildcard plugins/*/evals))

evals:                  ## Routing + behavior evals (claude plugin eval; runs on your credential)
	@bash scripts/eval-plugin.sh
	@failed=""; for p in $(EVAL_PLUGINS); do \
		(cd "$$p" && claude plugin eval . --tag routing --ablation none --trust-plugin \
			--no-publish -j 2 --threshold 0.9) || failed="$$failed $$p"; \
	done; \
	[ -z "$$failed" ] || { echo "FAIL: routing evals below threshold in:$$failed"; exit 1; }
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
