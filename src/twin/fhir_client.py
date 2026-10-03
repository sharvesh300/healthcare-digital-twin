"""Minimal HAPI FHIR R4 client plus the Synthea bundle rewrite."""

from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any

import httpx

from twin.config import settings

FHIR_JSON = "application/fhir+json"
# Namespace for deterministic resource ids (reruns PUT the same ids -> idempotent).
TWIN_NS = uuid.UUID("6f1c6d0e-4c7a-4b8e-9a51-2d1f3b7c9e10")
URN_RE = re.compile(r'"urn:uuid:([0-9a-fA-F-]{36})"')
# Synthea shares these across patients (conditional references); never delete them with a patient.
SHARED_RESOURCE_TYPES = {"Organization", "Location", "Practitioner", "PractitionerRole"}


def twin_id(*parts: object) -> str:
    return str(uuid.uuid5(TWIN_NS, "/".join(str(p) for p in parts)))


class FhirError(RuntimeError):
    pass


class FhirClient:
    def __init__(self, base: str | None = None, timeout: float = 1800):
        self.base = (base or settings().fhir_base).rstrip("/")
        self.http = httpx.Client(
            base_url=self.base,
            timeout=timeout,
            headers={"Content-Type": FHIR_JSON, "Accept": FHIR_JSON},
        )

    def wait_ready(self, max_wait: float = 900) -> None:
        deadline = time.monotonic() + max_wait
        while True:
            try:
                if self.http.get("/metadata", timeout=10).status_code == 200:
                    return
            except httpx.TransportError:
                pass
            if time.monotonic() > deadline:
                raise FhirError(f"FHIR server at {self.base} not ready after {max_wait}s")
            time.sleep(5)

    def _check(self, r: httpx.Response) -> dict[str, Any]:
        if not r.is_success:
            raise FhirError(f"{r.request.method} {r.request.url} -> {r.status_code}: {r.text[:2000]}")
        return r.json() if r.content else {}

    def get(self, path: str, **params) -> dict[str, Any]:
        return self._check(self.http.get(path, params=params))

    def exists(self, resource_type: str, rid: str) -> bool:
        return self.http.get(f"/{resource_type}/{rid}").status_code == 200

    def put(self, resource: dict[str, Any]) -> dict[str, Any]:
        return self._check(self.http.put(f"/{resource['resourceType']}/{resource['id']}", json=resource))

    def post_bundle(self, bundle: dict[str, Any] | bytes) -> dict[str, Any]:
        body = bundle if isinstance(bundle, bytes) else json.dumps(bundle).encode()
        return self._check(self.http.post(self.base, content=body))

    def put_all(self, resources: list[dict[str, Any]]) -> dict[str, Any]:
        """Upsert many resources atomically in one transaction."""
        return self.post_bundle(
            {
                "resourceType": "Bundle",
                "type": "transaction",
                "entry": [
                    {
                        "fullUrl": f"{self.base}/{r['resourceType']}/{r['id']}",
                        "resource": r,
                        "request": {"method": "PUT", "url": f"{r['resourceType']}/{r['id']}"},
                    }
                    for r in resources
                ],
            }
        )

    def search_ids(self, resource_type: str, **params) -> list[str]:
        """All matching resource ids, following paging links."""
        ids: list[str] = []
        page = self.get(f"/{resource_type}", _elements="id", _count=500, **params)
        while True:
            ids += [e["resource"]["id"] for e in page.get("entry", [])]
            nxt = next((link["url"] for link in page.get("link", []) if link["relation"] == "next"), None)
            if not nxt:
                return ids
            page = self._check(self.http.get(nxt))

    def delete_patient(self, patient_id: str) -> int:
        """Delete a patient with its whole compartment in one transaction.

        HAPI's `_cascade=delete` commits round by round and can stop half way, so the
        compartment is collected with $everything and deleted atomically instead.
        Resources shared with other patients (organisations, practitioners,
        locations) are kept; if anything else still references a deleted resource,
        the server rejects the transaction and nothing is deleted.
        """
        targets: list[tuple[str, str]] = []
        page = self.get(f"/Patient/{patient_id}/$everything", _count=1000, _elements="id")
        while True:
            targets += [(e["resource"]["resourceType"], e["resource"]["id"]) for e in page.get("entry", [])]
            nxt = next((link["url"] for link in page.get("link", []) if link["relation"] == "next"), None)
            if not nxt:
                break
            page = self._check(self.http.get(nxt))
        entries = [
            {"request": {"method": "DELETE", "url": f"{rtype}/{rid}"}}
            for rtype, rid in dict.fromkeys(targets)
            if rtype not in SHARED_RESOURCE_TYPES
        ]
        self.post_bundle({"resourceType": "Bundle", "type": "transaction", "entry": entries})
        return len(entries)

    def meta_delete_tags(self, resource_type: str, rid: str, tags: list[dict[str, str]]) -> None:
        if not tags:
            return
        params = {"resourceType": "Parameters", "parameter": [{"name": "meta", "valueMeta": {"tag": tags}}]}
        self._check(self.http.post(f"/{resource_type}/{rid}/$meta-delete", json=params))


def synthea_to_put_transaction(bundle: dict[str, Any], base: str) -> bytes:
    """Rewrite a Synthea transaction so every resource keeps its Synthea UUID.

    Synthea POSTs resources with `urn:uuid:` fullUrls, which lets the server assign
    new ids. We PUT `Type/<uuid>` instead (server runs client_id_strategy=ANY) and
    rewrite internal references to `Type/<uuid>`. Conditional references
    (`Organization?identifier=...`) are left for the server to resolve against the
    hospital/practitioner bundles loaded beforehand.
    """
    types: dict[str, str] = {}
    for entry in bundle["entry"]:
        resource = entry["resource"]
        rid = resource.get("id") or entry["fullUrl"].removeprefix("urn:uuid:")
        resource["id"] = rid
        types[rid] = resource["resourceType"]
        entry["fullUrl"] = f"{base}/{resource['resourceType']}/{rid}"
        entry["request"] = {"method": "PUT", "url": f"{resource['resourceType']}/{rid}"}

    text = json.dumps(bundle)
    return URN_RE.sub(lambda m: f'"{types[m.group(1)]}/{m.group(1)}"' if m.group(1) in types else m.group(0), text).encode()
