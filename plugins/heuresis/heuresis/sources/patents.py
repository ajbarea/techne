"""Patent source: EPO Open Patent Services. Coverage is always partial."""

from __future__ import annotations

import base64
import os
import urllib.parse
import xml.etree.ElementTree as ET

from heuresis.model import Record
from heuresis.sources import http, register

EPO_AUTH = "https://ops.epo.org/3.2/auth/accesstoken"
EPO_PUBLISHED = "https://ops.epo.org/3.2/rest-services/published-data"
EPO_SEARCH = f"{EPO_PUBLISHED}/search/biblio"
EX = "{http://www.epo.org/exchange}"


MAX_QUERY_TERMS = 10
MAX_RANGE = 100


def _by_language(elements: list[ET.Element]) -> ET.Element | None:
    return next((e for e in elements if e.get("lang") == "en"), elements[0] if elements else None)


def _abstract_text(abstract: ET.Element | None) -> str:
    if abstract is None:
        return ""
    return " ".join("".join(p.itertext()).strip() for p in abstract.iter(f"{EX}p"))


def _cql(query: str) -> str:
    terms = query.replace('"', " ").split()[:MAX_QUERY_TERMS]
    return f'ta all "{" ".join(terms)}"'


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
            token = http.json_object(raw).get("access_token")
            if not isinstance(token, str) or not token:
                raise http.SourceError("EPO token response had no access_token")
            Epo._token = token
        return Epo._token

    def _get(self, url: str, headers: dict[str, str] | None = None) -> bytes:
        """GET with the bearer token; a 401 means the token expired, so refresh once."""
        for attempt in (1, 2):
            auth = {"Authorization": f"Bearer {self.token()}", **(headers or {})}
            try:
                return http.get(url, auth)
            except http.SourceError as exc:
                if exc.status != 401 or attempt == 2:
                    raise
                Epo._token = None
        raise AssertionError("unreachable")

    def search(self, query: str, limit: int) -> list[Record]:
        url = f"{EPO_SEARCH}?{urllib.parse.urlencode({'q': _cql(query)})}"
        headers = {"Range": f"1-{max(1, min(limit, MAX_RANGE))}"}
        try:
            root = ET.fromstring(self._get(url, headers))
        except http.SourceError as exc:
            if exc.status == 404:  # OPS answers a search with no hits as SERVER.EntityNotFound
                return []
            raise
        except ET.ParseError as exc:
            raise http.SourceError("EPO response was not XML") from exc
        out = []
        for doc in root.iter(f"{EX}exchange-document"):
            country, number, kind = (doc.get(k, "") for k in ("country", "doc-number", "kind"))
            title = _by_language(list(doc.iter(f"{EX}invention-title")))
            abstract = _by_language(list(doc.iter(f"{EX}abstract")))
            out.append(
                Record(
                    title=(title.text or "") if title is not None else "",
                    url=f"https://worldwide.espacenet.com/patent/search?q=pn%3D"
                    f"{country}{number}{kind}",
                    source=self.name,
                    kind="patent",
                    text=_abstract_text(abstract),
                    evidence_url=f"epo:{country}.{number}.{kind}",
                )
            )
        return out

    def evidence(self, record: Record) -> str | None:
        docdb = record.evidence_url.removeprefix("epo:")
        url = f"{EPO_PUBLISHED}/publication/docdb/{docdb}/abstract"
        try:
            root = ET.fromstring(self._get(url))
        except ET.ParseError as exc:
            raise http.SourceError("EPO response was not XML") from exc
        abstract = _by_language(list(root.iter(f"{EX}abstract")))
        return _abstract_text(abstract)


register(Epo())
