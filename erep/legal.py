"""Rendu des demandes en français (RGPD, déréférencement, DSA, relance, plainte CNIL)."""
from __future__ import annotations

from erep import dossier as dossier_mod
from erep import store
from erep import targets as targets_mod

TEMPLATES_DIR = store.REPO_ROOT / "templates" / "demandes"

KINDS = {
    "rgpd_acces": "Droit d'accès (art. 15 RGPD)",
    "rgpd_effacement": "Effacement et opposition (art. 17 et 21 RGPD)",
    "rgpd_opposition": "Opposition à la prospection (art. 21 RGPD)",
    "dereferencement": "Déréférencement par un moteur de recherche (art. 17 RGPD)",
    "dsa_notification": "Notification de contenu illicite (art. 16 DSA)",
    "relance": "Relance après expiration du délai (art. 12.3 RGPD)",
    "plainte_cnil": "Plainte auprès de la CNIL (art. 77 RGPD)",
}
# Toujours nécessaires pour qu'une demande soit traitable, en plus des `inputs` de la cible.
BASE_FIELDS = ["full_name", "contact_email"]
NEEDS_MOTIF = {"dereferencement", "dsa_notification"}
LABELS = {"full_name": "Nom", "birth_name": "Nom de naissance", "contact_email": "E-mail",
          "phone": "Téléphone", "city": "Ville", "postal_code": "Code postal",
          "date_of_birth": "Date de naissance"}


class LegalError(ValueError):
    pass


def render(kind: str, dossier: dict, target: dict, *, listing_urls: list[str] | None = None,
           motif: str | None = None, case: dict | None = None) -> dict:
    if kind not in KINDS:
        raise LegalError(f"type de demande inconnu : {kind}")
    if not targets_mod.applicable(kind, dossier, target):
        raise LegalError(f"{kind} ne s'applique pas : la personne réside hors UE/EEE et "
                         f"{target['name']} n'y est pas établi")
    if kind in NEEDS_MOTIF and not motif:
        raise LegalError(f"{kind} exige --motif (pourquoi ce contenu doit disparaître)")
    removal = target.get("removal") or {}
    inputs = list(dict.fromkeys(BASE_FIELDS + list(removal.get("inputs") or [])))
    disclosed = dossier_mod.select_disclosure(dossier, inputs)
    case = case or {}
    fields = {
        "target_name": target["name"],
        "full_name": disclosed.get("full_name", ""),
        "contact_email": disclosed.get("contact_email", ""),
        "identifying_details": "\n".join(f"  {LABELS.get(k, k)} : {v}"
                                         for k, v in disclosed.items()),
        "listing_urls": "\n".join(f"  - {u}" for u in listing_urls or []) or "  (non précisé)",
        "motif": motif or "",
        "date": store.utcnow().strftime("%d/%m/%Y"),
        "submitted_at": _fr_date(case.get("submitted_at")),
        "response_due_at": _fr_date(case.get("response_due_at")),
        "initial_kind": KINDS.get(case.get("kind", ""), "demande"),
    }
    text = (TEMPLATES_DIR / f"{kind}.txt").read_text(encoding="utf-8").format_map(fields)
    subject_line, _, body = text.partition("\n")
    return {
        "kind": kind,
        "label": KINDS[kind],
        # Destinataire verrouillé sur le canal officiel de la cible : jamais une adresse libre.
        "to": None if kind == "plainte_cnil" else removal.get("email"),
        "web_form": "https://www.cnil.fr/fr/plaintes" if kind == "plainte_cnil" else removal.get("url"),
        "subject": subject_line.removeprefix("Objet : ").strip(),
        "body": body.lstrip("\n"),
        "disclosed_fields": sorted(disclosed),
    }


def _fr_date(s: str | None) -> str:
    return store.parse_ts(s).strftime("%d/%m/%Y") if s else "(date inconnue)"
