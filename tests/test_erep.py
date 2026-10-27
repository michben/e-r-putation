"""Tests hermétiques : ni réseau, ni navigateur, ni e-mail. `python3 -m unittest discover tests`."""
from __future__ import annotations

import contextlib
import io
import json
import os
import stat
import tempfile
import unittest

from erep import cli, dossier, ledger, legal, store, targets


def run(*argv: str) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        code = cli.main(list(argv))
    return code, buf.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = {k: os.environ.get(k) for k in ("EREP_DATA_DIR", "EREP_NOW")}
        os.environ["EREP_DATA_DIR"] = self.tmp.name
        os.environ["EREP_NOW"] = "2026-01-31T10:00:00Z"

    def tearDown(self):
        for k, v in self.env.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self.tmp.cleanup()

    def intake(self, *extra: str) -> str:
        code, out = run("intake", "--full-name", "Jeanne Exemple", "--birth-name", "Jeanne Modèle",
                        "--email", "jeanne@example.org", "--phone", "+33600000000",
                        "--city", "Lyon", "--consent", *extra)
        self.assertEqual(code, 0)
        return json.loads(out)["subject_id"]


class TestDates(unittest.TestCase):
    def test_add_months_clamps_end_of_month(self):
        d = store.parse_ts("2026-01-31T10:00:00Z")
        self.assertEqual(store.ts(store.add_months(d, 1)), "2026-02-28T10:00:00Z")
        self.assertEqual(store.ts(store.add_months(d, 3)), "2026-04-30T10:00:00Z")
        self.assertEqual(store.ts(store.add_months(store.parse_ts("2026-12-15"), 1)),
                         "2027-01-15T00:00:00Z")


class TestConsent(Base):
    def test_intake_refuses_without_consent(self):
        code, _ = run("intake", "--full-name", "X Y")
        self.assertEqual(code, 2)

    def test_mandate_requires_reference(self):
        code, _ = run("intake", "--full-name", "X Y", "--consent", "--consent-method", "mandate")
        self.assertEqual(code, 2)
        code, _ = run("intake", "--full-name", "X Y", "--consent", "--consent-method", "mandate",
                      "--mandate-ref", "classeur/mandat-xy.pdf")
        self.assertEqual(code, 0)

    def test_subject_id_is_opaque_and_files_private(self):
        sid = self.intake()
        self.assertNotIn("jeanne", sid.lower())
        mode = stat.S_IMODE(os.stat(dossier.path(sid)).st_mode)
        self.assertEqual(mode, 0o600)

    def test_actions_refused_when_consent_missing(self):
        sid = self.intake()
        d = dossier.load(sid)
        d["consent"]["authorized"] = False
        store.write_json(dossier.path(sid), d)
        self.assertEqual(run("plan", sid)[0], 2)


class TestDisclosure(Base):
    def test_only_required_fields_and_never_volunteer(self):
        sid = self.intake("--dob", "1980-01-01")
        d = dossier.load(sid)
        d["identity"]["nir"] = "1800199999999"
        out = dossier.select_disclosure(d, ["full_name", "contact_email", "nir"])
        self.assertEqual(set(out), {"full_name", "contact_email"})

    def test_rendered_request_excludes_unrequested_fields(self):
        sid = self.intake("--dob", "1980-01-01")
        req = legal.render("rgpd_effacement", dossier.load(sid), targets.get("lusha"))
        self.assertNotIn("1980", req["body"])
        self.assertNotIn("+33600000000", req["body"])
        self.assertEqual(req["disclosed_fields"], ["contact_email", "full_name"])


class TestJurisdiction(Base):
    def test_no_rgpd_claim_outside_eu_against_non_eu_target(self):
        sid = self.intake("--residence", "US")
        with self.assertRaises(legal.LegalError):
            legal.render("rgpd_acces", dossier.load(sid), targets.get("lusha"))

    def test_rgpd_applies_to_eu_established_target_for_non_resident(self):
        sid = self.intake("--residence", "US")
        req = legal.render("rgpd_acces", dossier.load(sid), targets.get("kaspr"))
        self.assertIn("article 15", req["body"])

    def test_motif_required_for_delisting(self):
        sid = self.intake()
        with self.assertRaises(legal.LegalError):
            legal.render("dereferencement", dossier.load(sid), targets.get("google-search"),
                         listing_urls=["https://exemple.fr/a"])


class TestLedger(Base):
    def test_rejects_illegal_transition(self):
        sid = self.intake()
        with self.assertRaises(ledger.TransitionError):
            ledger.record(sid, targets.get("lusha"), "reminded")

    def test_removed_requires_verifying_rescan(self):
        sid = self.intake()
        t = targets.get("google-search")
        ledger.record(sid, t, "found", evidence={"listing_urls": ["https://exemple.fr/a"]})
        ledger.record(sid, t, "submitted", kind="dereferencement")
        with self.assertRaises(ledger.TransitionError):
            ledger.record(sid, t, "delisted")
        case = ledger.record(sid, t, "delisted", verified=True)
        self.assertEqual(case["next_recheck_at"], "2026-05-01T10:00:00Z")

    def test_rgpd_deadline_reminder_then_cnil(self):
        sid = self.intake()
        t = targets.get("kaspr")
        case = ledger.record(sid, t, "submitted", kind="rgpd_effacement",
                             disclosed=["full_name", "contact_email"], channel="email")
        self.assertEqual(case["response_due_at"], "2026-02-28T10:00:00Z")
        self.assertEqual(ledger.due(sid, store.parse_ts("2026-02-27T00:00:00Z")), [])
        self.assertEqual(ledger.due(sid, store.parse_ts("2026-03-01T00:00:00Z"))[0]["action"],
                         "send_reminder")
        os.environ["EREP_NOW"] = "2026-03-01T00:00:00Z"
        ledger.record(sid, t, "reminded")
        self.assertEqual(ledger.due(sid, store.parse_ts("2026-03-17T00:00:00Z"))[0]["action"],
                         "file_cnil_complaint")

    def test_extension_adds_two_months(self):
        sid = self.intake()
        t = targets.get("kaspr")
        ledger.record(sid, t, "submitted", kind="rgpd_acces")
        case = ledger.record(sid, t, "extended")
        self.assertEqual(case["response_due_at"], "2026-04-30T10:00:00Z")

    def test_dsa_uses_practical_delay(self):
        sid = self.intake()
        case = ledger.record(sid, targets.get("google-avis"), "submitted", kind="dsa_notification")
        self.assertEqual(case["legal_basis"], "dsa")
        self.assertEqual(case["response_due_at"], "2026-02-14T10:00:00Z")

    def test_audit_logs_field_names_not_values(self):
        sid = self.intake()
        ledger.record(sid, targets.get("kaspr"), "submitted", kind="rgpd_acces",
                      disclosed=["full_name", "contact_email"], channel="email")
        audit = (store.subject_dir(sid) / "audit.jsonl").read_text(encoding="utf-8")
        self.assertIn("contact_email", audit)
        self.assertNotIn("jeanne@example.org", audit)


class TestPlan(Base):
    def test_parents_first_and_children_marked(self):
        sid = self.intake()
        code, out = run("plan", sid)
        rows = json.loads(out)
        ids = [r["target_id"] for r in rows]
        self.assertLess(ids.index("annuaire-universel"), ids.index("pagesblanches"))
        self.assertLess(ids.index("insee-sirene"), ids.index("societe-com"))
        by_id = {r["target_id"]: r for r in rows}
        self.assertEqual(by_id["pagesblanches"]["covered_by"], "annuaire-universel")
        self.assertEqual(by_id["annuaire-universel"]["tier"], "T3")

    def test_search_vectors_cover_birth_name_and_phone(self):
        sid = self.intake()
        vecs = dossier.search_vectors(dossier.load(sid), targets.get("pagesblanches"))
        self.assertIn({"name": "Jeanne Modèle", "city": "Lyon"}, vecs)
        self.assertIn({"phone": "+33600000000"}, vecs)

    def test_tier_depends_on_email_mode(self):
        t = targets.get("kaspr")
        self.assertEqual(targets.select_tier(t, "draft_only"), "T2")
        self.assertEqual(targets.select_tier(t, "programmatic"), "T1")

    def test_every_target_file_is_well_formed(self):
        for tid, t in targets.load_all().items():
            self.assertEqual(set(t["removal"]["kinds"]) - set(legal.KINDS), set(), tid)
            for child in t["owns"]:
                self.assertIn(child, targets.load_all(), tid)


class TestCli(Base):
    def test_render_writes_private_draft_and_hint(self):
        sid = self.intake()
        code, out = run("render", sid, "google-search", "--kind", "dereferencement",
                        "--listing", "https://exemple.fr/a", "--motif", "Information obsolète")
        self.assertEqual(code, 0)
        req = json.loads(out)
        self.assertEqual(stat.S_IMODE(os.stat(req["draft_path"]).st_mode), 0o600)
        self.assertIn("record " + sid + " google-search submitted", req["after"])

    def test_reminder_quotes_original_dates(self):
        sid = self.intake()
        run("record", sid, "kaspr", "submitted", "--kind", "rgpd_effacement")
        code, out = run("render", sid, "kaspr", "--kind", "relance")
        body = json.loads(out)["body"]
        self.assertIn("31/01/2026", body)
        self.assertIn("28/02/2026", body)

    def test_status_and_tasks(self):
        sid = self.intake()
        run("record", sid, "copains-davant", "human_task_queued", "--reason", "supprimer le compte")
        code, out = run("status", sid)
        self.assertIn("action humaine", out)
        tasks = json.loads(run("tasks", sid)[1])
        self.assertIn({"target_id": "copains-davant", "task": "supprimer le compte"}, tasks)
        self.assertIn("annuaire-universel", [t["target_id"] for t in tasks])


if __name__ == "__main__":
    unittest.main()
