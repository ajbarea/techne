# AI-slop hate-word glossary

Canonical cross-skill list. Referenced by `/aj-deslop`, `/aj-reslop`, `/aj-docsync`.
Update this file, not the individual skills.

Each section is a **candidate generator**, not a verdict — a hit only starts
the conversation. Always filter against the Keep rules of the skill that's
using the list. "Robust" inside a user-facing error message is fine;
"robust implementation" in a docstring is slop.

## Marketing / hype padding

- `robust`, `comprehensive`, `elegant(ly)?`, `holistic`
- `powerful`, `blazing(ly)?`, `lightning[- ]fast`, `battle[- ]tested`
- `production[- ]ready`, `enterprise[- ]grade`, `industry[- ]standard`
- `seamless(ly)?`, `effortlessly`, `with ease`, `painlessly`
- `simply`, `just` (as a filler, not a verb), `out[- ]of[- ]the[- ]box`
- `state[- ]of[- ]the[- ]art`, `cutting[- ]edge`, `next[- ]generation`
- `future[- ]proof` (unless the code provably is)
- `game[- ]?chang(er|ing)`, `revolutionary`, `transformative` (as adjectives for your own code)
- `synerg(y|ize|istic)`
- `harness(es|ing)? the power`, `unlock(s|ing)? the (power|potential)`, `unleash(es|ing)?`

## Modern LLM tells

Phrasings that almost never come from a human writing terse code comments —
they're the stylistic fingerprint of a chat assistant having padded the answer.
Easy to grep for, high signal.

- `delve(s|d|ing)?`
- `tapestry`
- `meticulous(ly)?`
- `crucial`, `pivotal`, `paramount`, `vital` (as hedge emphasis in prose)
- `navigat(e|es|ing) the (complexit(y|ies)|landscape|nuances|intricacies)`
- `in the realm of`, `in the world of`, `in today'?s .* world`
- `it'?s no secret that`, `it goes without saying`, `needless to say`
- `testament to`, `stands as a testament`
- `dive deep`, `deep dive` (as section framing)
- `not just \w+, but \w+`, `it'?s not just about \w+, it'?s about \w+` (antithesis pattern)
- `ever[- ]evolving`, `ever[- ]changing`, `rapidly evolving`

## Unsupported quantitative / comparative claims

Numeric performance or scale claims without measurement backing. The source of
truth is **repo-specific** — the invoking skill injects it via `.claude/skill-context.md`
under `slop_ground_truth`. A grep hit here is a *candidate*: the claim is fine
if it cites a measurement from that source, slop if it floats as marketing
prose.

- `\d+\s*[x×]\s*(faster|speedup|slower|speed[- ]?up)`
- `\d+%\s*(faster|improvement|reduction|less|more|quicker)`
- `sub[- ]?(millisecond|microsecond)`, `near[- ]?zero overhead`, `no overhead`
- `scales? to \d+`, `handles \d+\+?\s*(clients|users|requests|workers)`
- `O\(\s*\d\s*\)` or `linear[- ]time` in narrative prose
- `orders? of magnitude` used as a claim (rather than about a measured log scale)

Resolution for each real hit:

1. Link to the specific measurement from the repo's `slop_ground_truth` (name the file + function if possible).
2. Replace with the measured number, scoped to what was measured.
3. Delete the claim if neither fits.

## Temporal / versioning rot

- `best[- ]practice` (e.g. "based on April 2026 best practice")
- `as of 20\d\d`, `latest version`, `current(ly)? recommended`
- `modern(ly)?`, `up[- ]to[- ]date`

## Planning / task-context rot

- `PHASE ?\d`, `Phase [0-9A-Z]`, `Step \d of \d`, `Part [IVX]+`
- `TODO\((?:copilot|gpt|gemini|claude|cursor)`
- `added for (?:issue|ticket|pr) #\d+`, `fix for the .* bug`

## Self-referential AI framing

- `AI (?:assistant|debugger|debug)`
- `LLM`, `for (?:model|AI) consumption`
- `designed so an? (?:AI|assistant|model)`
- `AI-DEBUG`, `AI HINTS?`

## Verbose verbs (replace with simpler)

- `leverag(es?|ing)` → use
- `utiliz(es?|ing)` → use
- `facilitat(es?|ing)` → let / allow
- `encapsulat(es?|ing)` → hold / wrap (when overused)

## Hedging / filler docstring prose

- `it's important to note`, `it is worth noting`, `please note that`
- `in summary`, `under the hood`, `at a high level`
- `we might want to`, `in some cases this could`, `potentially`
- `needless to say`, `as mentioned earlier`

## Narrative WHAT-comment patterns

Flagged manually — greppable but high false-positive rate:

- `# Now we ...`, `# Then we ...`, `# Finally ...`
- `# This (?:function|method|class) ...` (often restates the signature)
- `# Return the ...` when the return type is already declared
- Bullet lists in docstrings that only repeat argument types
