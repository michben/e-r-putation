"""Registre de suivi : un dossier par (personne x cible), machine à états validée et délais RGPD.

Chaque transition est vérifiée contre TRANSITIONS et copiée dans audit.jsonl (noms de champs
transmis seulement, jamais leurs valeurs).
"""
from __future__ import annotations

import datetime as _dt

from erep import store

TRANSITIONS: dict[str, set[str]] = {
    # new -> submitted : demande « à l'aveugle » (accès art. 15 à un courtier B2B, opt-out) qui ne
    # transmet que les identifiants de la personne au canal officiel de la cible.
    "new": {"searching", "found", "not_found", "indirect_exposure", "submitted",
            "human_task_queued", "blocked"},
    "searching": {"found", "not_found", "indirect_exposure", "blocked"},
    "not_found": {"searching", "found", "indirect_exposure", "submitted", "blocked"},
    # found -> not_found : un homonyme pris pour la personne, retiré avec preuve.
    "found": {"submitted", "human_task_queued", "indirect_exposure", "blocked", "not_found"},
    # Donnée de la personne sur la fiche d'un tiers : seule une demande RGPD ciblée s'applique.
    "indirect_exposure": {"submitted", "human_task_queued", "found", "not_found", "blocked"},
    "submitted": {"extended", "awaiting_processing", "access_answered", "confirmed_removed",
                  "delisted", "refused", "reminded", "human_task_queued", "blocked"},
    # Prolongation de deux mois annoncée par le responsable (art. 12.3).
    "extended": {"awaiting_processing", "access_answered", "confirmed_removed", "delisted",
                 "refused", "reminded", "human_task_queued"},
    "reminded": {"awaiting_processing", "access_answered", "confirmed_removed", "delisted",
                 "refused", "escalated_cnil", "human_task_queued"},
    # Réponse à une demande d'accès : on connaît la source, on enchaîne sur l'effacement.
    "access_answered": {"submitted", "found", "confirmed_removed", "not_found"},
    "awaiting_processing": {"confirmed_removed", "delisted", "reminded", "refused",
                            "human_task_queued", "blocked"},
    "refused": {"escalated_cnil", "submitted", "human_task_queued"},
    "escalated_cnil": {"confirmed_removed", "delisted", "refused", "awaiting_processing"},
    "confirmed_removed": {"reappeared"},
    # Déréférencé n'est pas supprimé : la page existe encore, elle n'apparaît plus sur le nom.
    "delisted": {"reappeared"},
    "reappeared": {"found", "indirect_exposure"},
    "human_task_queued": {"found", "indirect_exposure", "submitted", "awaiting_processing",
                          "confirmed_removed", "delisted", "escalated_cnil", "blocked"},
    "blocked": {"searching", "found", "not_found", "indirect_exposure", "submitted",
                "human_task_queued"},
}
STATES = sorted(TRANSITIONS)

# Délai de réponse par type de demande. RGPD : un mois (art. 12.3). DSA : « dans les meilleurs
# délais » (art. 16), on relance au bout de 14 jours par usage, pas par obligation légale.
RESPONSE_DELAY = {"rgpd": ("months", 1), "dsa": ("days", 14)}
EXTENSION_MONTHS = 2
REMINDER_DAYS = 15
RESCAN_DAYS = 90
NEEDS_REASON = {"human_task_queued", "refused", "blocked", "escalated_cnil"}
NEEDS_VERIFIED = {"confirmed_removed", "delisted"}


class TransitionError(ValueError):
    pass


def _paths(subject_id: str):
    d = store.subject_dir(subject_id)
    return d / "ledger.json", d / "audit.jsonl"


def load(subject_id: str) -> dict:
    return store.read_json(_paths(subject_id)[0], {}) or {}


def record(subject_id: str, target: dict, state: str, *, kind: str | None = None,
           legal_basis: str | None = None, evidence: dict | None = None,
           disclosed: list[str] | None = None, channel: str | None = None,
           reason: str | None = None, verified: bool = False) -> dict:
    if state not in TRANSITIONS:
        raise TransitionError(f"état inconnu : {state}")
    if state in NEEDS_REASON and not reason:
        raise TransitionError(f"l'état {state} exige --reason")
    if state in NEEDS_VERIFIED and not verified:
        raise TransitionError(f"{state} seulement après une nouvelle recherche qui le confirme "
                              "(--verified), jamais sur la seule page de confirmation du site")
    ledger_path, audit_path = _paths(subject_id)
    with store.locked(ledger_path):
        ledger = load(subject_id)
        tid = target["id"]
        case = ledger.get(tid) or {"target_id": tid, "state": "new", "history": []}
        prev = case["state"]
        if state != prev and state not in TRANSITIONS[prev]:
            raise TransitionError(f"{tid} : transition interdite {prev} -> {state}")
        now = store.utcnow()
        case["state"] = state
        case["updated_at"] = store.ts(now)
        if evidence:
            case.setdefault("evidence", {}).update(evidence)
        if reason:
            case["reason"] = reason
        _apply_deadlines(case, target, state, now, kind, legal_basis)
        case["history"].append({"at": store.ts(now), "from": prev, "to": state,
                                **({"reason": reason} if reason else {})})
        if disclosed:
            case.setdefault("disclosures", []).append(
                {"at": store.ts(now), "fields": sorted(disclosed), "channel": channel})
        ledger[tid] = case
        store.write_json(ledger_path, ledger)
        store.append_jsonl(audit_path, {"at": store.ts(now), "target": tid, "from": prev,
                                        "to": state, "disclosed_fields": sorted(disclosed or []),
                                        "channel": channel})
    return case


def _apply_deadlines(case: dict, target: dict, state: str, now: _dt.datetime,
                     kind: str | None, legal_basis: str | None) -> None:
    if state == "submitted":
        if not kind:
            raise TransitionError("submitted exige --kind (type de demande envoyée)")
        basis = legal_basis or ("dsa" if kind == "dsa_notification" else "rgpd")
        unit, n = RESPONSE_DELAY[basis]
        due = store.add_months(now, n) if unit == "months" else now + _dt.timedelta(days=n)
        case.update(kind=kind, legal_basis=basis, submitted_at=store.ts(now),
                    response_due_at=store.ts(due))
        case.pop("reminder_due_at", None)
        case.pop("next_recheck_at", None)
    elif state == "extended":
        start = store.parse_ts(case["submitted_at"])
        case["response_due_at"] = store.ts(store.add_months(start, 1 + EXTENSION_MONTHS))
    elif state == "reminded":
        case["reminder_due_at"] = store.ts(now + _dt.timedelta(days=REMINDER_DAYS))
    elif state == "awaiting_processing":
        days = int((target.get("removal") or {}).get("est_processing_days") or 30)
        case["next_recheck_at"] = store.ts(now + _dt.timedelta(days=days))
    elif state in ("confirmed_removed", "delisted", "not_found"):
        case["next_recheck_at"] = store.ts(now + _dt.timedelta(days=RESCAN_DAYS))
        case.pop("response_due_at", None)
        case.pop("reminder_due_at", None)


def due(subject_id: str, now: _dt.datetime | None = None) -> list[dict]:
    """Ce qui est arrivé à échéance : relances, escalades CNIL, nouvelles recherches."""
    now = now or store.utcnow()
    out = []
    for tid, case in sorted(load(subject_id).items()):
        st = case["state"]

        def passed(key: str) -> bool:
            return bool(case.get(key)) and store.parse_ts(case[key]) <= now

        if st in ("submitted", "extended", "awaiting_processing") and passed("response_due_at"):
            out.append({"target_id": tid, "action": "send_reminder",
                        "why": f"pas de réponse au {case['response_due_at'][:10]}"})
        elif st == "reminded" and passed("reminder_due_at"):
            action = "file_cnil_complaint" if case.get("legal_basis") == "rgpd" else "escalate"
            out.append({"target_id": tid, "action": action,
                        "why": f"relance restée sans réponse au {case['reminder_due_at'][:10]}"})
        elif st == "refused" and case.get("legal_basis") == "rgpd":
            out.append({"target_id": tid, "action": "file_cnil_complaint",
                        "why": f"refus : {case.get('reason', '')}"})
        elif st in ("not_found", "confirmed_removed", "delisted", "awaiting_processing") \
                and passed("next_recheck_at"):
            out.append({"target_id": tid, "action": "rescan",
                        "why": f"nouvelle vérification prévue au {case['next_recheck_at'][:10]}"})
    return out
