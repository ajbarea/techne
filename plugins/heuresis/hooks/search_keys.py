"""The search keys heuresis reads: option name, environment variable, and what each adds.

The one table the plugin.json options, the SessionStart hook, the store script and the doctor
all share. Standard library only, so system python3 (3.9 or newer) can import it.
"""

from __future__ import annotations

from typing import NamedTuple

EPO = "EPO_OPS"
EPO_WHY = "adds European patents; register at developers.epo.org"


class Key(NamedTuple):
    option: str  # the plugin.json userConfig name
    env: str  # the variable the sources read
    why: str  # what the key adds and where to get it
    group: str = ""  # keys with the same group only work together


KEYS = (
    Key(
        "openalex_api_key",
        "OPENALEX_API_KEY",
        "raises OpenAlex's search budget; free at openalex.org/settings/api",
    ),
    Key(
        "s2_api_key",
        "S2_API_KEY",
        "adds Semantic Scholar; request one at semanticscholar.org/product/api",
    ),
    Key(
        "lens_api_token",
        "LENS_API_TOKEN",
        "adds worldwide patents; request API access in your lens.org profile",
    ),
    Key(
        "epo_ops_key",
        "EPO_OPS_KEY",
        EPO_WHY,
        EPO,
    ),
    Key(
        "epo_ops_secret",
        "EPO_OPS_SECRET",
        EPO_WHY,
        EPO,
    ),
)

BY_ENV = {k.env: k for k in KEYS}
