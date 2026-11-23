# techne — Implementation scratchpad (feat/actionlint-pins-391)

## Sisters: shared action-pin check & actionlint (issue #391)

- Slice:
  - Single shared action-pin check: `scripts/check_action_pins.sh` accepts target directory argument `$1`, supports repos with or without `plugins/`, exempts local `./…`, `$/…`, and `docker://…` refs, emits GitHub Actions `::error` annotations when `GITHUB_ACTIONS` is set.
  - Composite action: `.github/actions/check-action-pins/action.yml` so sister repositories can invoke techne's canonical action pin engine directly without duplicating inline regexes.
  - actionlint integration: `actionlint` target in `Makefile`, added to `validate` target and `.github/workflows/validate.yml`.
  - actionlint config: `.github/actionlint.yaml` registers `ubuntu-26.04` runner label and ignores `$/` format in `mutation.yml`.
  - Security floor check 17: `plugins/techne/skills/sisters/scripts/security_floor.py` audits that CI runs both `zizmor` and `actionlint`, and exempts `$/` local composite actions.
- Done:
  - ✅ Updated `Makefile` with `actionlint` target and wired into `validate`.
  - ✅ Configured `.github/actionlint.yaml` (`ubuntu-26.04` self-hosted label, `$/` ignore).
  - ✅ Updated `scripts/check_action_pins.sh` with custom target dir `$1`, `$/` exemption, and GHA annotations.
  - ✅ Created composite action `.github/actions/check-action-pins/action.yml`.
  - ✅ Updated `.github/workflows/validate.yml` with `make actionlint`.
  - ✅ Updated `plugins/techne/skills/sisters/scripts/security_floor.py` with `actionlint` check and `$/` exemption.
  - ✅ Updated `docs/conventions.md` documenting shared composite action and `$/` exemption.
  - ✅ Added unit tests in `tests/test_sisters_security_floor.py` and `tests/test_check_action_pins.py`.
- Next:
  - Run `make fix && make lint`.
  - Run pytest suite (`test_sisters_security_floor.py`, `test_check_action_pins.py`).
  - Run `make actionlint` and `make zizmor`.
  - Run `make guards`.
  - Commit, push branch `feat/actionlint-pins-391`, open PR, and log in Desktop delivery file.
- Verify:
  - `make lint`
  - `make actionlint`
  - `make zizmor`
  - `make guards`
  - `uv run pytest tests/test_sisters_security_floor.py tests/test_check_action_pins.py`
  - `uv run python3 plugins/techne/skills/sisters/scripts/security_floor.py $(pwd) .`
