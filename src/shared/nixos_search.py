"""Package search against search.nixos.org's Elasticsearch backend.

The endpoint, index naming and read-only credentials are the ones the
search.nixos.org web page itself uses (see its static/js/index.*.js). When the
site bumps its schema version or a new NixOS release comes out, update the
index via `nixos_search_index` in config.toml.
"""

from dataclasses import dataclass

import requests

URL = "https://search.nixos.org/backend/{index}/_search"
# Public read-only credentials shipped in the search.nixos.org front end.
AUTH = ("aWVSALXpZv", "X8gPHnzL52wFEekuxsfQ9cSh")


class SearchError(Exception):
    def __init__(self, message: str, offline: bool):
        super().__init__(message)
        # True when search.nixos.org couldn't be reached at all, False when it answered with an error.
        self.offline = offline


@dataclass
class Package:
    name: str  # attribute name, e.g. "firefox"; what goes in the config
    version: str
    description: str


def search(query: str, index: str, size: int = 20, timeout: float = 8.0) -> list[Package]:
    query = query.strip()
    if not query:
        return []
    body = {
        "size": size,
        "_source": ["package_attr_name", "package_pversion", "package_description"],
        "query": {"bool": {
            "filter": [
                {"term": {"type": "package"}},
                # Only packages that run on Linux machines (drops e.g. macOS-only *-bin repacks).
                {"terms": {"package_platforms": ["x86_64-linux", "aarch64-linux"]}},
            ],
            # Skip nested package sets (python3Packages.x, emacsPackages.x...): we want apps.
            "must_not": [{"wildcard": {"package_attr_name": "*.*"}}],
            "should": [
                {"term": {"package_attr_name": {"value": query, "boost": 100}}},
                {"prefix": {"package_attr_name": {"value": query.lower(), "boost": 10}}},
                {"prefix": {"package_pname": {"value": query.lower(), "boost": 10}}},
                {"multi_match": {
                    "type": "cross_fields",
                    "query": query,
                    "fields": ["package_attr_name^9", "package_pname^6",
                               "package_programs^9", "package_description^1.3"],
                }},
            ],
            "minimum_should_match": 1,
        }},
    }
    try:
        response = requests.post(URL.format(index=index), json=body, auth=AUTH, timeout=timeout)
        response.raise_for_status()
        hits = response.json()["hits"]["hits"]
    except (requests.ConnectionError, requests.Timeout) as e:
        raise SearchError(str(e), offline=True) from e
    except (requests.RequestException, KeyError, ValueError) as e:
        raise SearchError(str(e), offline=False) from e
    packages = [Package(h["_source"]["package_attr_name"],
                        h["_source"].get("package_pversion") or "",
                        h["_source"].get("package_description") or "")
                for h in hits]
    # The name field is tokenized, so "firefox" scores firefox-esr as highly as firefox.
    # Put the exact name first, then names starting with the query; sorted() keeps the
    # search's order otherwise.
    q = query.lower()
    return sorted(packages, key=lambda p: (p.name.lower() != q, not p.name.lower().startswith(q)))
