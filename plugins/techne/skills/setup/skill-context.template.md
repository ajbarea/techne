# Skill context

## repo
<one-paragraph description of what this repo is and who uses it>

## audit
phases:
  - setup
  - lint
  - test
  - ci
fast_subset: [lint, test]
stop_early: [setup]
log_archive_glob: "logs/dev-*-{phase}.log"
do_not_run: []

## ci_audit
referenced_configs:
  - "pyproject.toml"
  - "Makefile"
tool_error_markers:
  - "ruff"
  - "FAILED"

## slop_ground_truth
authoritative_sources:
  - "src/"
  - "tests/"
test_locations:
  - "tests/"

## scan_scope
skip:
  - "site/"
  - ".venv/"
areas:
  - "src/"
  - "tests/"
  - "docs/"

## docs_site
config: "zensical.toml"
workflow: ".github/workflows/docs.yml"
css_files: "docs/stylesheets/"
js_files: "docs/javascripts/"
build_command: "uv run zensical build --clean"
site_url: "https://<owner>.github.io/<repo>/"
action_pins: "the full-SHA pins in .github/workflows/docs.yml"

## theoros
```yaml
repl_command: <your repo's REPL command>
session_name: <your-repo-slug>-theoros
```

## paper
```yaml
author: <name>
affiliation: <institution>
email: <address>
bib: ../references          # shared bibliography, relative to the paper directory
portfolio: LINEAGE.md       # file that lists each paper
```

## paper-review
```yaml
lab_line: LINEAGE.md        # source of truth for lab and co-author overlap
retrieval: <sources>        # default OpenAlex + web
mailto: <address>           # OpenAlex polite pool, default git config user.email
report: papers/<name>/novelty-review.md
```

## latex
```yaml
markers: [FILL, TODO, XXX]   # draft words that must not survive into a built PDF
overfull_pt: 5.0             # report overfull boxes at or above this
engine: pdf                  # latexmk engine flag: pdf, xelatex, lualatex
```

## elenchus
```yaml
test_command: <how to run the suite, e.g. make test>
run_command: <how to exercise the running thing, if not in ## theoros>
destructive_ops:
  - <path:line of an irreversible op reviewers must trace to its inputs>
load_bearing_surfaces:
  - <the registered wrapper / shipped path the harness actually surfaces>
feature_works_means:
  - <what "the feature works" looks like end-to-end, beyond green CI>
```
