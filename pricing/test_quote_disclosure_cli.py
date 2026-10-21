"""Public CLI on synthetic real Git inputs; no genuine authentication credit."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

DISCLOSURE = ("Illustrative counterparty. This model-only quote is an ordinal comparison from "
              "editorial inputs; it is not an independent insurance offer or actuarial assurance.")
SOURCE = Path(__file__).resolve().parents[1]


class QuoteDisclosureCLI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.insurer = self.root / "insurer"
        (self.insurer / "pricing").mkdir(parents=True)
        shutil.copy2(SOURCE / "pricing/quote.py", self.insurer / "pricing/quote.py")
        (self.insurer / "quote").mkdir()
        for schema in (SOURCE / "quote").glob("*.schema.json"):
            shutil.copy2(schema, self.insurer / "quote" / schema.name)
        self.env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
                        PYTHONDONTWRITEBYTECODE="1")
        for key in [k for k in self.env if k in {"GH_TOKEN", "GITHUB_TOKEN"} or k.startswith("GITSIGN_")]:
            self.env.pop(key)
        platform = self.root / "platform"
        (platform / "party").mkdir(parents=True)
        declared = Path(os.environ.get("PLATFORM_DIR", SOURCE.parent / "platform"))
        rule = declared / "party/pin_content.py"
        if not rule.is_file():
            raise AssertionError(f"fixture prerequisite: unchanged pin-content rule absent at {rule}")
        shutil.copy2(rule, platform / "party/pin_content.py")
        self.env["PLATFORM_DIR"] = str(platform)
        self.write(self.insurer / "party.yaml", {"party": "insurer", "inherits": [
            {"party": "platform", "kind": "implementations", "version": "5.0.0"},
            {"party": "acme", "kind": "feed", "name": "exposure", "version": "v2.0.0"}]})
        self.terms = {"version": "2.0.0", "published_at": "2026-10-21T00:00:00Z",
                      "currency": "GBP", "limit": {"amount": 500.0, "currency": "GBP"},
                      "rate": 0.04, "load": 0.25,
                      "exclusions": [{"regime": "known", "control_ids": []}],
                      "conditions": [], "valid_from": "2026-01-01", "valid_until": "2027-01-01"}
        self.write(self.insurer / "terms/acme.yaml", self.terms)
        self.adopters = self.root / "adopters"
        adopter = self.adopters / "acme"
        self.write(adopter / "party.yaml", {"party": "acme", "reporting_currency": "GBP", "publishes": [
            {"kind": "feed", "name": "exposure", "path": "composed", "payload_schema": None}]})
        self.write(adopter / "composed/HEADER.yaml", {"exposure": {
            "perspective": "acme", "currency": "GBP", "total": 1_000.0,
            "attachment": {"amount": 100.0, "currency": "GBP"},
            "regimes": [{"name": "known", "amount": 200.0, "controls": []}]}})
        for args in [("init", "-q"), ("add", "."),
                     ("-c", "user.name=Synthetic fixture", "-c", "user.email=fixture@example.invalid",
                      "-c", "commit.gpgsign=false", "commit", "-qm", "synthetic exposure"),
                     ("tag", "v2.0.0")]:
            subprocess.run(["git", *args], cwd=adopter, env=self.env, check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    @staticmethod
    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(value))

    def cli(self, command, *extra):
        return subprocess.run([sys.executable, "-B", "pricing/quote.py", command, "acme",
                               "--adopters-dir", str(self.adopters), *extra],
                              cwd=self.insurer, env=self.env, text=True, capture_output=True)

    def test_show_and_render_put_illustrative_disclosure_on_the_quote_without_repricing(self):
        shown = self.cli("show")
        self.assertEqual(shown.returncode, 0, shown.stderr)
        doc = json.loads(shown.stdout)
        self.assertEqual(doc["payload"].get("usage"), "illustrative")
        self.assertEqual(doc["payload"].get("disclosure"), DISCLOSURE)
        self.assertEqual(doc["payload"]["premium"],
                         {"amount": 25.0, "currency": "GBP", "perspective": "acme"})
        self.assertEqual(doc["payload"]["formula"], {"id": "layer-rate-on-line", "version": "1.0.0",
                         "rate": 0.04, "load": 0.25, "excluded": 200.0, "insured": 800.0, "layer": 500.0})
        rendered = self.cli("render", "--published-at", "2026-10-21T01:02:03Z")
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        saved = json.loads((self.insurer / "quote/acme/v2/feed.json").read_text())
        self.assertEqual(saved, dict(doc, published_at="2026-10-21T01:02:03Z"))

    def test_feed_path_uses_the_declared_major_and_render_keeps_legacy_bytes(self):
        legacy = self.insurer / "quote/acme/v1/feed.json"
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(b'{"synthetic": "immutable legacy quote"}\n')
        before = legacy.read_bytes()
        path = self.cli("feed-path")
        self.assertEqual(path.returncode, 0, path.stderr)
        self.assertEqual(path.stdout.strip(), "quote/acme/v2/feed.json")
        rendered = self.cli("render")
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        self.assertTrue((self.insurer / path.stdout.strip()).is_file())
        self.assertEqual(legacy.read_bytes(), before)
        self.write(self.insurer / "terms/acme.yaml", dict(self.terms, version="7.0.0"))
        later = self.cli("feed-path")
        self.assertEqual(later.returncode, 0, later.stderr)
        self.assertEqual(later.stdout.strip(), "quote/acme/v7/feed.json")

    def native_reader(self, stdlib=False):
        # This is the production shell reader; only dependency selection is a fixture.
        shutil.copy2(SOURCE / "verify-insurer-quote.sh", self.insurer / "verify-insurer-quote.sh")
        party_path = self.insurer / "party.yaml"
        party = yaml.safe_load(party_path.read_text())
        party["publishes"] = [{"kind": "feed", "name": "quote-acme", "path": "quote/acme",
                               "payload_schema": "quote/payload.v2.schema.json"}]
        self.write(party_path, party)
        adopter_path = self.adopters / "acme/party.yaml"
        adopter = yaml.safe_load(adopter_path.read_text())
        adopter["appetite"] = {"tolerance": {"amount": 100.0, "currency": "GBP"}}
        self.write(adopter_path, adopter)
        platform_source = Path(os.environ.get("PLATFORM_DIR", SOURCE.parent / "platform"))
        fair = self.root / "platform/fair/fair.py"
        fair.parent.mkdir(exist_ok=True)
        for module in (platform_source / "fair").glob("*.py"):
            shutil.copy2(module, fair.parent / module.name)
        catalogue = self.root / "nist/catalog/NIST_SP-800-53_rev5.2.0_catalog.json"
        catalogue.parent.mkdir(parents=True, exist_ok=True)
        catalogue.write_text(json.dumps({"catalog": {"groups": []}}))
        binaries = self.root / ("python-stdlib" if stdlib else "python-normal")
        binaries.mkdir(exist_ok=True)
        import shlex
        python = binaries / "python3"
        python.write_text("#!/bin/sh\nexec " + shlex.quote(sys.executable) +
                          (" -S" if stdlib else "") + ' "$@"\n')
        python.chmod(0o755)
        env = dict(self.env, ADOPTERS_DIR=str(self.adopters), NIST_DIR=str(self.root / "nist"),
                   PATH=str(binaries) + os.pathsep + self.env["PATH"])
        if stdlib:
            dependencies = self.root / "stdlib-dependencies"
            dependencies.mkdir(exist_ok=True)
            link = dependencies / "yaml"
            if not link.exists():
                link.symlink_to(Path(yaml.__file__).parent, target_is_directory=True)
            env["PYTHONPATH"] = str(dependencies)
        return subprocess.run(["bash", "verify-insurer-quote.sh", "--published-only"],
                              cwd=self.insurer, env=env, text=True, capture_output=True)

    def test_public_reader_validates_declared_v2_schema_in_both_available_validators(self):
        self.assertEqual(self.cli("render").returncode, 0)
        path = self.insurer / "quote/acme/v2/feed.json"
        original = path.read_text()
        for stdlib in (False, True):
            with self.subTest(stdlib=stdlib):
                path.write_text(original)
                valid = self.native_reader(stdlib)
                self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)
                if stdlib:
                    self.assertIn("stdlib subset check", valid.stdout)
                for field, replacement in [("usage", None), ("usage", "binding"), ("usage", 1),
                                           ("disclosure", None), ("disclosure", ""),
                                           ("disclosure", "An independent actuarial quote")]:
                    with self.subTest(field=field, replacement=replacement):
                        altered = json.loads(original)
                        if replacement is None:
                            del altered["payload"][field]
                        else:
                            altered["payload"][field] = replacement
                        path.write_text(json.dumps(altered))
                        refused = self.native_reader(stdlib)
                        self.assertEqual(refused.returncode, 1, refused.stdout + refused.stderr)
                        self.assertIn("payload vs quote/payload.v2.schema.json", refused.stdout)
                path.write_text(original)

    def test_bump_is_major_for_new_contract_and_none_after_the_same_render(self):
        self.write(self.insurer / "quote/acme/rule.yaml", {"numeric_tolerance": 0.02})
        first = self.cli("bump")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout.strip(), "major")
        self.assertEqual(self.cli("render").returncode, 0)
        unchanged = self.cli("bump")
        self.assertEqual(unchanged.returncode, 0, unchanged.stderr)
        self.assertEqual(unchanged.stdout.strip(), "none")
        path = self.insurer / "quote/acme/v2/feed.json"
        old = json.loads(path.read_text())
        old["payload_schema"] = "quote/payload.schema.json"
        path.write_text(json.dumps(old))
        changed = self.cli("bump")
        self.assertEqual(changed.returncode, 0, changed.stderr)
        self.assertEqual(changed.stdout.strip(), "major")

    def test_public_reader_distinguishes_old_subscription_and_binds_new_booked_quote(self):
        self.assertEqual(self.cli("render").returncode, 0)
        doc = json.loads((self.insurer / "quote/acme/v2/feed.json").read_text())
        party_path = self.adopters / "acme/party.yaml"
        party = yaml.safe_load(party_path.read_text())
        edge = {"party": "insurer", "kind": "feed", "name": "quote-acme", "version": "v1"}
        party["inherits"] = [edge]
        self.write(party_path, party)
        old_subscription = self.native_reader()
        self.assertEqual(old_subscription.returncode, 0, old_subscription.stdout + old_subscription.stderr)
        self.assertIn("does not pin this quote major 2", old_subscription.stdout)
        self.assertNotIn("books it as one contract cost line", old_subscription.stdout)
        edge["version"] = "v2"
        self.write(party_path, party)
        evidence_path = self.adopters / "acme/composed/evidence.json"
        booked = {"source": "insurer", "kind": "premium", "name": "quote-acme",
                  "perspective": "acme", "currency": "GBP", "amount": 25.0,
                  "new_version": "v1", "quote_version": "1.0.0",
                  "priced_against": doc["payload"]["priced_against"]}
        evidence_path.write_text(json.dumps({"prices": [booked]}))
        old_book = self.native_reader()
        self.assertEqual(old_book.returncode, 1, old_book.stdout + old_book.stderr)
        self.assertIn("booked quote version/provenance", old_book.stdout)
        booked.update(new_version="v2", quote_version="2.0.0")
        evidence_path.write_text(json.dumps({"prices": [booked]}))
        current = self.native_reader()
        self.assertEqual(current.returncode, 0, current.stdout + current.stderr)
        self.assertIn("books it as one contract cost line", current.stdout)
        booked["priced_against"] = [dict(p, version="old") for p in booked["priced_against"]]
        evidence_path.write_text(json.dumps({"prices": [booked]}))
        stale = self.native_reader()
        self.assertEqual(stale.returncode, 1, stale.stdout + stale.stderr)
        self.assertIn("booked quote version/provenance", stale.stdout)


if __name__ == "__main__":
    unittest.main()
