"""Patent sources: Lens (worldwide) and EPO Open Patent Services. Coverage is always partial."""

from __future__ import annotations

import base64
import json
import os
import urllib.parse
import xml.etree.ElementTree as ET

from heuresis.model import Record
from heuresis.sources import http, register

LENS_URL = "https://api.lens.org/patent/search"
LENS_INCLUDE = ["lens_id", "biblio.invention_title", "abstract", "date_published"]
EPO_AUTH = "https://ops.epo.org/3.2/auth/accesstoken"
EPO_SEARCH = "https://ops.epo.org/3.2/rest-services/published-data/search/biblio"
EX = "{http://www.epo.org/exchange}"


def _english(values: list[dict] | None) -> str:
    values = values or []
    chosen = next((v for v in values if v.get("lang") == "en"), values[0] if values else {})
    return str(chosen.get("text", ""))


def _lens_text(doc: dict) -> str:
    title = _english((doc.get("biblio") or {}).get("invention_title"))
    return f"{title} {_english(doc.get('abstract'))}"


class Lens:
    name, group = "lens", "patents"

    def available(self) -> tuple[bool, str]:
        return (True, "") if os.environ.get("LENS_API_TOKEN") else (False, "no LENS_API_TOKEN")

    def _post(self, body: dict) -> dict:
        headers = {"Authorization": f"Bearer {os.environ['LENS_API_TOKEN']}"}
        try:
            return json.loads(http.post_json(LENS_URL, body, headers))
        except ValueError as exc:
            raise http.SourceError("Lens response was not JSON") from exc

    def search(self, query: str, limit: int) -> list[Record]:
        body = {"query": {"query_string": {"query": query}}, "size": limit, "include": LENS_INCLUDE}
        out = []
        for doc in self._post(body).get("data", []):
            lens_id = doc["lens_id"]
            title = _english((doc.get("biblio") or {}).get("invention_title"))
            out.append(
                Record(
                    title=title,
                    url=f"https://www.lens.org/lens/patent/{lens_id}",
                    source=self.name,
                    kind="patent",
                    text=_english(doc.get("abstract")),
                    date=str(doc.get("date_published", "")),
                    evidence_url=f"lens:{lens_id}",
                )
            )
        return out

    def evidence(self, record: Record) -> str | None:
        lens_id = record.evidence_url.removeprefix("lens:")
        body = {"query": {"terms": {"lens_id": [lens_id]}}, "include": LENS_INCLUDE}
        docs = self._post(body).get("data", [])
        return _lens_text(docs[0]) if docs else ""


class Epo:
    name, group = "epo", "patents"
    _token: str | None = None

    def available(self) -> tuple[bool, str]:
        if os.environ.get("EPO_OPS_KEY") and os.environ.get("EPO_OPS_SECRET"):
            return True, ""
        return False, "no EPO_OPS_KEY and EPO_OPS_SECRET"

    def token(self) -> str:
        if Epo._token is None:
            pair = f"{os.environ['EPO_OPS_KEY']}:{os.environ['EPO_OPS_SECRET']}".encode()
            req_headers = {
                "Authorization": "Basic " + base64.b64encode(pair).decode(),
                "Content-Type": "application/x-www-form-urlencoded",
            }
            raw = http.post_form(EPO_AUTH, {"grant_type": "client_credentials"}, req_headers)
            Epo._token = json.loads(raw)["access_token"]
        return Epo._token

    def search(self, query: str, limit: int) -> list[Record]:
        cql = f'ta all "{query}"'
        url = f"{EPO_SEARCH}?{urllib.parse.urlencode({'q': cql})}"
        headers = {"Authorization": f"Bearer {self.token()}", "Range": f"1-{limit}"}
        try:
            root = ET.fromstring(http.get(url, headers))
        except ET.ParseError as exc:
            raise http.SourceError("EPO response was not XML") from exc
        out = []
        for doc in root.iter(f"{EX}exchange-document"):
            number = f"{doc.get('country', '')}{doc.get('doc-number', '')}{doc.get('kind', '')}"
            titles = doc.iter(f"{EX}invention-title")
            title = next((t.text or "" for t in titles if t.get("lang") == "en"), "")
            abstract = " ".join(
                "".join(p.itertext())
                for a in doc.iter(f"{EX}abstract")
                if a.get("lang") == "en"
                for p in a.iter(f"{EX}p")
            )
            out.append(
                Record(
                    title=title,
                    url=f"https://worldwide.espacenet.com/patent/search?q=pn%3D{number}",
                    source=self.name,
                    kind="patent",
                    text=abstract,
                    evidence_url=f"epo:{number}",
                )
            )
        return out

    def evidence(self, record: Record) -> str | None:
        number = record.evidence_url.removeprefix("epo:")
        url = f"https://ops.epo.org/3.2/rest-services/published-data/publication/docdb/{number}/abstract"
        root = ET.fromstring(http.get(url, {"Authorization": f"Bearer {self.token()}"}))
        return " ".join(root.itertext())


for _source in (Lens(), Epo()):
    register(_source)
