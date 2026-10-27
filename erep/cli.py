"""CLI e-réputation : `python3 -m erep <commande>`. Toutes les sorties sont en JSON sauf `status`."""
from __future__ import annotations

import argparse
import json
import sys

from erep import dossier as dossier_mod
from erep import ledger as ledger_mod
from erep import legal, report, store
from erep import targets as targets_mod

EMAIL_MODES = ("draft_only", "programmatic")


def _cfg() -> dict:
    return store.read_json(store.data_dir() / "config.json", {"email_mode": "draft_only"})


def _out(obj) -> int:
    json.dump(obj, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


def _subject(sid: str) -> dict:
    d = dossier_mod.load(sid)
    dossier_mod.require_authorized(d)
    return d


def _plan(sid: str) -> list[dict]:
    return targets_mod.plan(_subject(sid), targets_mod.load_all(), ledger_mod.load(sid), _cfg())


def cmd_setup(a):
    cfg = {**_cfg(), "email_mode": a.email_mode}
    store.write_json(store.data_dir() / "config.json", cfg)
    return _out(cfg)


def cmd_doctor(a):
    ts = targets_mod.load_all()
    return _out({
        "data_dir": str(store.data_dir()),
        "config": _cfg(),
        "targets": len(ts),
        "targets_unverified": sorted(t for t, v in ts.items() if v.get("confidence") != "verified"),
        "targets_missing_channel": sorted(t for t, v in ts.items() if _missing_channel(v)),
        "later": ["envoi d'e-mails SMTP/IMAP et boucle `next` (PR 2)",
                  "veille des résultats de recherche (PR 3)"],
    })


def _missing_channel(t: dict) -> bool:
    r = t.get("removal") or {}
    return r.get("method") in ("email", "web_form") and not (r.get("url") or r.get("email"))


def cmd_intake(a):
    if not a.consent:
        print("refus : --consent est obligatoire (la personne a autorisé ces démarches)",
              file=sys.stderr)
        return 2
    identity = {k: v for k, v in {
        "full_name": a.full_name, "birth_name": a.birth_name, "aliases": a.alias,
        "emails": a.email, "contact_email": a.contact_email, "phones": a.phone, "city": a.city,
        "prior_cities": a.prior_city, "postal_code": a.postal_code, "date_of_birth": a.dob,
    }.items() if v}
    consent = {"authorized": True, "method": a.consent_method, "mandate_ref": a.mandate_ref}
    d = dossier_mod.create(identity, consent, a.residence)
    return _out({"subject_id": d["subject_id"], "residence": d["residence"],
                 "rgpd_applicable": dossier_mod.in_eu(d)})


def cmd_targets(a):
    ts = targets_mod.load_all().values()
    return _out([{"id": t["id"], "name": t["name"], "category": t["category"],
                  "priority": t["priority"], "method": t["removal"].get("method"),
                  "owns": t.get("owns") or []}
                 for t in ts if not a.category or t["category"] == a.category])


def cmd_plan(a):
    rows = _plan(a.subject)
    for r in rows:
        r["missing_channel"] = _missing_channel(targets_mod.get(r["target_id"]))
    return _out(rows)


def cmd_record(a):
    _subject(a.subject)
    case = ledger_mod.record(
        a.subject, targets_mod.get(a.target), a.state, kind=a.kind, legal_basis=a.legal_basis,
        evidence=json.loads(a.evidence) if a.evidence else None,
        disclosed=[f for f in (a.disclosed or "").split(",") if f], channel=a.channel,
        reason=a.reason, verified=a.verified)
    return _out(case)


def cmd_show(a):
    _subject(a.subject)
    return _out(ledger_mod.load(a.subject).get(a.target) or {"target_id": a.target, "state": "new"})


def cmd_render(a):
    d = _subject(a.subject)
    target = targets_mod.get(a.target)
    case = ledger_mod.load(a.subject).get(a.target) or {}
    urls = a.listing or (case.get("evidence") or {}).get("listing_urls") or []
    req = legal.render(a.kind, d, target, listing_urls=urls, motif=a.motif, case=case)
    drafts = store.subject_dir(a.subject) / "drafts"
    drafts.mkdir(exist_ok=True)
    path = drafts / f"{a.target}-{a.kind}-{store.utcnow().strftime('%Y%m%dT%H%M%S')}.txt"
    path.write_text(f"Objet : {req['subject']}\n\n{req['body']}", encoding="utf-8")
    path.chmod(0o600)
    req["draft_path"] = str(path)
    req["after"] = (f"python3 -m erep record {a.subject} {a.target} submitted --kind {a.kind} "
                    f"--disclosed {','.join(req['disclosed_fields'])} --channel "
                    f"{'email' if req['to'] else 'web_form'}")
    return _out(req)


def cmd_due(a):
    _subject(a.subject)
    return _out(ledger_mod.due(a.subject))


def cmd_tasks(a):
    return _out(report.tasks(a.subject, _plan(a.subject)))


def cmd_status(a):
    sys.stdout.write(report.status_markdown(a.subject, _plan(a.subject)))
    return 0


def cmd_mandate(a):
    text = (store.REPO_ROOT / "templates" / "consentement" / "mandat.md").read_text(encoding="utf-8")
    sys.stdout.write(text.format(full_name=a.full_name, mandataire=a.mandataire,
                                 date=store.utcnow().strftime("%d/%m/%Y")))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="erep", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("setup", help="configurer le mode e-mail")
    s.add_argument("--email-mode", choices=EMAIL_MODES, default="draft_only")
    s.set_defaults(func=cmd_setup)
    sub.add_parser("doctor", help="état de l'installation").set_defaults(func=cmd_doctor)

    s = sub.add_parser("intake", help="enregistrer une personne consentante")
    s.add_argument("--full-name", required=True)
    s.add_argument("--birth-name")
    s.add_argument("--alias", action="append")
    s.add_argument("--email", action="append")
    s.add_argument("--contact-email", help="adresse utilisée pour la correspondance")
    s.add_argument("--phone", action="append")
    s.add_argument("--city")
    s.add_argument("--prior-city", action="append")
    s.add_argument("--postal-code")
    s.add_argument("--dob")
    s.add_argument("--residence", default="FR", help="code pays ISO (FR par défaut)")
    s.add_argument("--consent", action="store_true")
    s.add_argument("--consent-method", choices=sorted(dossier_mod.CONSENT_METHODS), default="self")
    s.add_argument("--mandate-ref", help="où est rangé le mandat signé (obligatoire si mandate)")
    s.set_defaults(func=cmd_intake)

    s = sub.add_parser("targets", help="lister les cibles")
    s.add_argument("--category")
    s.set_defaults(func=cmd_targets)

    for name, func, hlp in (("plan", cmd_plan, "plan par cible, parents d'abord"),
                            ("due", cmd_due, "relances, plaintes et vérifications arrivées à échéance"),
                            ("tasks", cmd_tasks, "récapitulatif des tâches humaines"),
                            ("status", cmd_status, "rapport Markdown")):
        s = sub.add_parser(name, help=hlp)
        s.add_argument("subject")
        s.set_defaults(func=func)

    s = sub.add_parser("record", help="mettre à jour le registre (transitions validées)")
    s.add_argument("subject")
    s.add_argument("target")
    s.add_argument("state", choices=ledger_mod.STATES)
    s.add_argument("--kind", choices=sorted(legal.KINDS))
    s.add_argument("--legal-basis", choices=sorted(ledger_mod.RESPONSE_DELAY))
    s.add_argument("--evidence", help='JSON, par ex. {"listing_urls": ["https://..."]}')
    s.add_argument("--disclosed", help="champs transmis, séparés par des virgules")
    s.add_argument("--channel")
    s.add_argument("--reason")
    s.add_argument("--verified", action="store_true",
                   help="une nouvelle recherche confirme la suppression ou le déréférencement")
    s.set_defaults(func=cmd_record)

    s = sub.add_parser("show", help="afficher un dossier du registre")
    s.add_argument("subject")
    s.add_argument("target")
    s.set_defaults(func=cmd_show)

    s = sub.add_parser("render", help="rédiger une demande (brouillon, rien n'est envoyé)")
    s.add_argument("subject")
    s.add_argument("target")
    s.add_argument("--kind", required=True, choices=sorted(legal.KINDS))
    s.add_argument("--listing", action="append", help="URL concernée (répétable)")
    s.add_argument("--motif", help="justification (déréférencement, DSA)")
    s.set_defaults(func=cmd_render)

    s = sub.add_parser("mandate", help="générer un mandat à faire signer")
    s.add_argument("--full-name", required=True)
    s.add_argument("--mandataire", required=True)
    s.set_defaults(func=cmd_mandate)
    return p


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    try:
        return a.func(a)
    except (PermissionError, LookupError, ValueError) as e:
        print(f"erreur : {e}", file=sys.stderr)
        return 2
