You curate the elenchus bug-class catalog in this techne checkout: `plugins/techne/skills/elenchus/references/bug-classes.md`. Read its header first and keep every rule in it: the four fields per class, incidents as `repo#PR rN (YYYY-MM-DD): what happened` joined by `; `, newest last, at most three, and the word budget.

Today's plan, built from the machine-wide findings ledger, is `{plan}`. It holds:

- `incidents`: findings of classes the catalog already has. For each class, add one incident per PR, merging that PR's rounds (`r1 to r3`). Skip a PR the entry already cites. When an entry would hold more than three incidents, drop the oldest.
- `new_classes`: `new:` names found in two or more PRs. Add a full entry under **Learned classes** only if no existing class already covers the same failure. If one does, record the findings as incidents of that class instead. A new entry needs a Symptom, a Question, a Guard and its incidents, written from the findings' lines.
- `unknown_slugs`: tags that match no class. Fold each into the class it means, or leave it out if none fits.
- `retired`: classes whose mechanical check has landed. Add `- **Retired:** <the check, and where it runs>` as the entry's last field. Readers skip a retired class unless its check is missing.
- `retired_but_found`: retired classes reviewers still found. Remove their Retired line; the check did not hold.

A repo that is not in this list of public repos is private: {public}. Name a private repo by what it is ("a private plugin installer"), never by its name.

Do not rewrite entries the plan does not touch. Then run `uv run pytest -q tests/test_bug_classes.py` and fix what fails. Do not commit, push or open anything. Finish with one line per change you made.
