---
type: llm
---

The reply is a CI report as JSON for a green run whose only noise is rdflib's DeprecationWarning (ConjunctiveGraph) raised from site-packages during a test, plus a runner-image notice.
PASS if ALL hold: `failing_step` is null; `verdict` is "clean" or "green-with-findings"; the rdflib deprecation is a finding bucketed DEFER (its why names rdflib or the library as the source); the Ubuntu 26 runner notice, if listed, is EXPECTED or DEFER, not FIX; no finding claims a step failed.
FAIL if the deprecation is missing, bucketed FIX or BUMP with a repo file as its location, the verdict is "failure", or the reply is not JSON.
