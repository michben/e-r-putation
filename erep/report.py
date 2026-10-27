"""Récapitulatif des tâches humaines et rapport d'état en Markdown."""
from __future__ import annotations

from erep import ledger as ledger_mod

DONE = {"confirmed_removed", "delisted", "not_found"}
STATE_LABELS = {
    "new": "à rechercher", "searching": "recherche en cours", "not_found": "absent",
    "found": "trouvé", "indirect_exposure": "sur la fiche d'un tiers", "submitted": "demande envoyée",
    "extended": "délai prolongé", "reminded": "relancé", "access_answered": "accès obtenu",
    "awaiting_processing": "en traitement", "refused": "refusé", "escalated_cnil": "plainte CNIL",
    "confirmed_removed": "supprimé (vérifié)", "delisted": "déréférencé (vérifié)",
    "reappeared": "réapparu", "human_task_queued": "action humaine", "blocked": "bloqué",
}


def tasks(subject_id: str, plan_rows: list[dict]) -> list[dict]:
    """Tout ce que seul un humain peut faire, en une seule liste, présentée en fin de passage."""
    led = ledger_mod.load(subject_id)
    out = []
    for row in plan_rows:
        case = led.get(row["target_id"]) or {}
        state = case.get("state", "new")
        if state == "human_task_queued":
            out.append({"target_id": row["target_id"], "task": case.get("reason")})
        elif row["tier"] == "T3" and state not in DONE and state != "submitted":
            out.append({"target_id": row["target_id"], "task": row["notes"]})
    for d in ledger_mod.due(subject_id):
        if d["action"] == "file_cnil_complaint":
            out.append({"target_id": d["target_id"],
                        "task": f"Déposer la plainte CNIL préparée (render --kind plainte_cnil) : {d['why']}"})
    return out


def status_markdown(subject_id: str, plan_rows: list[dict]) -> str:
    led = ledger_mod.load(subject_id)
    lines = [f"# État des démarches : {subject_id}", "",
             "| Cible | État | Palier | Échéance |", "|---|---|---|---|"]
    counts: dict[str, int] = {}
    for row in plan_rows:
        case = led.get(row["target_id"]) or {}
        state = case.get("state", "new")
        counts[state] = counts.get(state, 0) + 1
        due = case.get("reminder_due_at") or case.get("response_due_at") or case.get("next_recheck_at")
        lines.append(f"| {row['name']} | {STATE_LABELS.get(state, state)} | {row['tier']} | "
                     f"{due[:10] if due else ''} |")
    lines += ["", "Résumé : " + ", ".join(f"{STATE_LABELS.get(k, k)} {v}"
                                          for k, v in sorted(counts.items())), "",
              "Un contenu déréférencé reste en ligne : il n'apparaît plus sur une recherche à "
              "votre nom. Les données légalement publiques (RCS, décisions de justice) ne sont "
              "pas effaçables, seulement moins exposées."]
    return "\n".join(lines) + "\n"
