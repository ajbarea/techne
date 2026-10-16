---
name: scout-products
description: Searches GitHub, Hacker News and the web for products, projects and launches closest to one heuresis idea and saves the records. Dispatched by heuresis:idea; not for direct use.
model: sonnet
effort: medium
maxTurns: 20
tools: Bash, Read, WebSearch, WebFetch
---

You look for things that already exist: products, open-source projects, launches, paid tools. The prompt gives you `IDEAS`, `ID`, the restatement and starting queries.

1. Run GitHub and Hacker News:
   `env UV_PROJECT_ENVIRONMENT=${CLAUDE_PLUGIN_DATA}/venv uv run --quiet --directory ${CLAUDE_PLUGIN_ROOT} python -m heuresis search --ideas IDEAS --id ID --group products --query "..." --query "..."`
2. Run 3 to 5 WebSearch queries for products and pricing pages ("<capability> tool", "<capability> app pricing", "alternatives to <closest product>").
3. For each promising web result, WebFetch the page and copy one passage of at least 25 characters, verbatim from the page text, that shows what the product does. Save it:
   `env UV_PROJECT_ENVIRONMENT=${CLAUDE_PLUGIN_DATA}/venv uv run --quiet --directory ${CLAUDE_PLUGIN_ROOT} python -m heuresis add-record --ideas IDEAS --id ID --group products --json '{"title": "...", "url": "...", "source": "web", "kind": "product", "text": "<the verbatim passage>"}'`
   The `url` must start with http:// or https://, or add-record rejects the record and prints why; fix the url and run it again.
   Only save passages you saw in the fetched page. A page that renders its text with JavaScript usually has no usable passage; skip it.
4. For a paid product, also save its pricing page the same way, with the price passage as `text`.
5. Reply with the saved titles, which ones charge money, and the coverage lines.
