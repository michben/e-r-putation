"""Base des cibles (moteurs, annuaires, courtiers, plateformes) et planification par paliers.

Paliers :
  T0  entièrement automatisable, sans boucle de vérification
  T1  envoi automatisé et vérification automatisée (mode e-mail programmatique)
  T2  envoi automatisé, mais une étape humaine (CAPTCHA, compte, e-mail envoyé à la main)
  T3  humain de bout en bout (pièce d'identité, courrier, démarche auprès de l'opérateur)
"""
from __future__ import annotations

import json

from erep import dossier as dossier_mod
from erep import store

TARGETS_DIR = store.REPO_ROOT / "targets"
HARD_HUMAN = ("id_document", "postal")
HUMAN_METHODS = ("operator", "postal")
PRIORITY_ORDER = {"crucial": 0, "high": 1, "normal": 2}


def load_all() -> dict[str, dict]:
    out = {}
    for p in sorted(TARGETS_DIR.glob("*.json")):
        t = json.loads(p.read_text(encoding="utf-8"))
        out[t["id"]] = t
    return out


def get(target_id: str) -> dict:
    t = load_all().get(target_id)
    if t is None:
        raise LookupError(f"cible inconnue : {target_id}")
    return t


def select_tier(target: dict, email_mode: str = "draft_only") -> str:
    removal = target.get("removal") or {}
    req = removal.get("requires") or {}
    method = removal.get("method")
    if method in HUMAN_METHODS or any(req.get(k) for k in HARD_HUMAN):
        return "T3"
    if req.get("account") or req.get("captcha"):
        return "T2"
    if method == "email" or req.get("email_verification"):
        return "T1" if email_mode == "programmatic" else "T2"
    return "T0"


def plan(dossier: dict, targets: dict[str, dict], ledger: dict, cfg: dict) -> list[dict]:
    """Une action par cible, parents d'abord, puis par priorité.

    Une cible couverte par un parent (`owns`) n'est traitée seule que si le parent n'a pas suffi :
    on la marque `covered_by` pour que l'agent la re-vérifie après le parent au lieu de la doubler.
    """
    email_mode = cfg.get("email_mode", "draft_only")
    parent_of = {child: t["id"] for t in targets.values() for child in t.get("owns") or []}
    rows = []
    for t in targets.values():
        removal = t.get("removal") or {}
        case = ledger.get(t["id"]) or {}
        rows.append({
            "target_id": t["id"],
            "name": t["name"],
            "category": t.get("category"),
            "priority": t.get("priority", "normal"),
            "state": case.get("state", "new"),
            "tier": select_tier(t, email_mode),
            "method": removal.get("method"),
            "kinds": [k for k in removal.get("kinds") or []
                      if applicable(k, dossier, t)],
            "url": removal.get("url"),
            "email": removal.get("email"),
            "disclosure_fields": sorted(dossier_mod.select_disclosure(
                dossier, removal.get("inputs") or []).keys()),
            "search_vectors": dossier_mod.search_vectors(dossier, t),
            "owns": t.get("owns") or [],
            "covered_by": parent_of.get(t["id"]),
            "needs_verification": t.get("confidence") != "verified",
            "notes": removal.get("notes", ""),
        })
    rows.sort(key=lambda r: (r["covered_by"] is not None, -len(r["owns"]),
                             PRIORITY_ORDER.get(r["priority"], 9), r["target_id"]))
    return rows


def applicable(kind: str, dossier: dict, target: dict) -> bool:
    """Ne jamais invoquer un droit que la personne ne peut pas exercer.

    Le RGPD s'applique si la personne réside dans l'UE/EEE (art. 3.2) ou si le responsable y est
    établi (art. 3.1). Le DSA couvre les services proposés dans l'UE.
    """
    if kind.startswith("rgpd_") or kind == "dereferencement":
        return dossier_mod.in_eu(dossier) or bool(target.get("established_eu"))
    if kind == "dsa_notification":
        return bool(target.get("offers_in_eu", True))
    return True
