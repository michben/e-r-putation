"""Dossier d'une personne : identité, consentement ou mandat, minimisation des données."""
from __future__ import annotations

import secrets

from erep import store

# Jamais transmis spontanément : cela élargirait l'exposition au lieu de la réduire.
NEVER_VOLUNTEER = {"nir", "numero_securite_sociale", "numero_cni", "numero_passeport", "iban",
                   "permis_conduire"}

# self : la personne agit pour elle-même. mandate : mandat écrit signé (tiers, client, proche).
CONSENT_METHODS = {"self", "mandate"}

EU_EEA = {"FR", "DE", "BE", "LU", "NL", "IT", "ES", "PT", "IE", "AT", "DK", "SE", "FI", "PL", "CZ",
          "SK", "SI", "HR", "HU", "RO", "BG", "GR", "CY", "MT", "EE", "LV", "LT", "IS", "LI", "NO"}


def path(subject_id: str):
    return store.subject_dir(subject_id) / "dossier.json"


def create(identity: dict, consent: dict, residence: str = "FR") -> dict:
    method = consent.get("method")
    if method not in CONSENT_METHODS:
        raise ValueError(f"méthode de consentement inconnue : {method!r}")
    if method == "mandate" and not consent.get("mandate_ref"):
        raise ValueError("un mandat exige --mandate-ref (où est rangé le mandat signé)")
    subject_id = "s_" + secrets.token_hex(6)  # opaque : rien du nom dans les chemins ou le journal
    dossier = {
        "subject_id": subject_id,
        "identity": identity,
        "consent": {**consent, "recorded_at": store.ts(store.utcnow())},
        "residence": residence.upper(),
        "created_at": store.ts(store.utcnow()),
    }
    store.write_json(path(subject_id), dossier)
    return dossier


def load(subject_id: str) -> dict:
    d = store.read_json(path(subject_id))
    if d is None:
        raise LookupError(f"personne inconnue : {subject_id}")
    return d


def require_authorized(dossier: dict) -> None:
    c = dossier.get("consent") or {}
    if not c.get("authorized") or c.get("method") not in CONSENT_METHODS:
        raise PermissionError(f"{dossier.get('subject_id')} : aucun consentement enregistré, refus d'agir")


def in_eu(dossier: dict) -> bool:
    return dossier.get("residence", "").upper() in EU_EEA


def names(dossier: dict) -> list[str]:
    """Nom d'usage, nom de naissance et autres noms, sans doublon."""
    ident = dossier.get("identity") or {}
    out, seen = [], set()
    for n in [ident.get("full_name"), ident.get("birth_name"), *(ident.get("aliases") or [])]:
        if n and n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    return out


def search_vectors(dossier: dict, target: dict) -> list[dict]:
    """Toutes les combinaisons utiles à la recherche, filtrées par ce que la cible accepte."""
    ident = dossier.get("identity") or {}
    by = set((target.get("search") or {}).get("by") or ["name"])
    cities = [c for c in [ident.get("city"), *(ident.get("prior_cities") or [])] if c]
    out: list[dict] = []
    if "name" in by:
        for n in names(dossier):
            out.append({"name": n})
            out.extend({"name": n, "city": c} for c in cities)
    if "phone" in by:
        out.extend({"phone": p} for p in ident.get("phones") or [])
    if "email" in by:
        out.extend({"email": e} for e in ident.get("emails") or [])
    return out


def select_disclosure(dossier: dict, inputs: list[str]) -> dict:
    """Uniquement les champs que la cible exige (art. 5.1.c RGPD, minimisation)."""
    ident = dossier.get("identity") or {}
    emails = ident.get("emails") or []
    phones = ident.get("phones") or []
    available = {
        "full_name": ident.get("full_name"),
        "birth_name": ident.get("birth_name"),
        "contact_email": ident.get("contact_email") or (emails[0] if emails else None),
        "phone": phones[0] if phones else None,
        "city": ident.get("city"),
        "postal_code": ident.get("postal_code"),
        "date_of_birth": ident.get("date_of_birth"),
    }
    return {k: available[k] for k in inputs
            if k not in NEVER_VOLUNTEER and available.get(k) is not None}
