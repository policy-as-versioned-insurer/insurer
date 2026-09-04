#!/usr/bin/env bash
# Offline verify for the insurer's quote slice (ticket 36; policy-composition
# ticket 14 answers 1 to 5; ADR-0019, ADR-0020, ADR-0021). Gate contract
# (BUILD-BRIEF.md): exit 0 = observed true, exit 3 = could not look with the
# reason on the last line, else = observed false with FAIL on the last line.
# No cluster, no network: every fact below is a file in this repo or in a
# sibling checkout of the party it is about.
#
# It also grades ONE seam on synthetic trees before it looks at the estate at
# all (`--selfcheck` runs that alone): eco-system ticket 77's rule that a quote
# never names a tag whose tree lacks the `exposure` section it priced, and the
# could-not-look that rule degrades to while no platform release carries it.
# Every published quote below is priced from a tree that does carry the section,
# so neither path is reachable from the estate observation.
#
# What it looks at, per published quote feed:
#   1. the quote is one ADR-0019 envelope and its payload validates against
#      quote/payload.schema.json;
#   2. the attachment EQUALS the insured adopter's own signed appetite -- the
#      retention it declared, not one this carrier restated (ticket 14 answer 1);
#   3. every exclusion and condition names a control id that really exists in
#      nist's published catalogue, and a regime the adopter's own exposure
#      actually prices;
#   4. the premium is REPRODUCIBLE: pricing/quote.py's own versioned formula,
#      re-run over the adopter's current signed exposure and this repo's signed
#      terms, lands on the same premium and the same intermediates. A quote
#      priced against an exposure that has since moved is a could-not-look
#      (a re-quote PR is due), never a pass;
#   5. no sum crosses a perspective: the layer arithmetic is the insurer's view,
#      the premium is a cost on the adopter's sheet, and the platform's own
#      fair.sum_prices refuses to add the two.
#
# It also LOOKS at the exposure parents party_artefact.py can only note (no Flux
# pin exists for a `feed` kind anywhere in this estate, and feed-contract grades
# subscriptions only for parties with the adopter role, which this one is not).
set -uo pipefail

# Gate contract (BUILD-BRIEF.md): exit 0 = observed true, exit 3 = could not
# look, anything else = observed false WITH `FAIL: <reason>` on the LAST line.
# 2026-08-29 review: planting a real defect here ended the run on a raw Python
# traceback ("AssertionError: ..."), which talk/verify-all.sh prints verbatim as
# the row's reason and verify-e2e-step7-honesty.sh grades UNGRADED. The defect
# was always detected; only the reason line was unreadable. This trap makes the
# last line legible without swallowing the traceback above it.
__verdict_trap() {
  local rc=$?
  [ "$rc" = 0 ] || [ "$rc" = 3 ] || echo "FAIL: a check above observed false (exit $rc); its own error line is the last one before this"
  return "$rc"
}
trap __verdict_trap EXIT

cd "$(dirname "${BASH_SOURCE[0]}")"

ADOPTERS_DIR="${ADOPTERS_DIR:-..}"
NIST_DIR="${NIST_DIR:-../nist}"
PLATFORM_DIR="${PLATFORM_DIR:-../platform}"

# ---------------------------------------------------------------------------
# The seam, on synthetic trees, run BEFORE the estate observation below
# (BUILD-BRIEF definition of done, point 2). Eco-system ticket 77 gave
# pricing/quote.py two new behaviours that NOTHING else in this repository or in
# the hub's gate reaches: a refusal (never emit `priced_against` naming a version
# whose tree lacks the `exposure` section it priced) and a could-not-look (no
# platform tag carries party/pin_content.py yet, and a rule the estate has not
# released is not a reason to stop a clock that would otherwise run). The
# published quotes below are all priced from trees that DO carry the section, so
# neither path is on the estate-observation route and without this leg the whole
# of ticket 77's insurer half would be graded by no check anywhere.
#
# It prints ONE verdict line, and the main block records it, so the aggregate at
# the bottom counts it like any other check. `--selfcheck` runs it alone.
selfcheck() {
  python3 - "$PLATFORM_DIR" <<'PYSELF'
import importlib.util
import os
import sys
import tempfile

import yaml

PLATFORM_DIR = sys.argv[1]
spec = importlib.util.spec_from_file_location("quote", os.path.join("pricing", "quote.py"))
quote = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quote)


def adopter_tree(root, with_exposure):
    """A synthetic driftwood release: the publishes[] record ADR-0019 point 5 discovers the
    section through, and a composed/HEADER.yaml that either carries the section or does not."""
    os.makedirs(os.path.join(root, "composed"), exist_ok=True)
    with open(os.path.join(root, "party.yaml"), "w") as fh:
        yaml.safe_dump({"party": "driftwood", "roles": ["publisher"], "publishes": [
            {"kind": "feed", "name": "exposure", "path": "composed",
             "payload_schema": None}]}, fh)
    header = {"perspective": "driftwood"}
    if with_exposure:
        header["exposure"] = {"total": 1, "currency": "GBP"}
    with open(os.path.join(root, "composed", "HEADER.yaml"), "w") as fh:
        yaml.safe_dump(header, fh)


def fail(msg):
    print(f"FAIL: quote.py pin-content seam: {msg}")
    sys.exit(1)


# The real pin out of this repo's own party.yaml -- the selfcheck grades the code, not a
# made-up dependency graph.
parents = quote.parents_of("driftwood")

with tempfile.TemporaryDirectory() as tmp:
    adopters = os.path.join(tmp, "adopters")
    adopter_tree(os.path.join(adopters, "driftwood"), with_exposure=False)

    # Leg 1. The pinned platform release does not carry the rule. Could-not-look, never a
    # refusal: refusing here would stop the scheduled re-quote on every adopter because a
    # rule the estate has not released yet could not be read.
    quote.PLATFORM_DIR = os.path.join(tmp, "platform-without-the-rule")
    try:
        graded = quote.refuse_unless_tree_carries_exposure("driftwood", adopters, parents)
    except quote.Refused as e:
        fail(f"a pinned platform release with no party/pin_content.py made the pricer refuse "
             f"({e}); an unreleased rule must not stop the clock")
    if graded is not False:
        fail("the pricer reported it had graded the pin while the rule was unreadable")

    # Leg 2. The rule IS in the pinned release and the pinned tree lacks the section.
    rule = os.path.join(PLATFORM_DIR, "party", "pin_content.py")
    if not os.path.isfile(rule):
        print(f"SKIP: quote.py pin-content seam: the could-not-look half is graded (a platform "
              f"release without the rule prices on and says so), but the REFUSAL half could not "
              f"be looked at: no {rule} in the platform checkout this run was given, and no "
              f"platform tag carries the rule yet")
        sys.exit(3)
    quote.PLATFORM_DIR = PLATFORM_DIR
    try:
        quote.refuse_unless_tree_carries_exposure("driftwood", adopters, parents)
    except quote.Refused as e:
        if "missing instrument" not in str(e) or "exposure" not in str(e):
            fail(f"the refusal does not name a missing instrument and the section: {e}")
    else:
        fail("a pinned tree whose composed/HEADER.yaml carries no exposure section was priced "
             "anyway -- ticket 77's refusal does not bite")

    # ... and a tree that does carry it is priced, so the refusal is not a blanket one.
    adopter_tree(os.path.join(adopters, "driftwood"), with_exposure=True)
    if quote.refuse_unless_tree_carries_exposure("driftwood", adopters, parents) is not True:
        fail("a pinned tree that carries the exposure section was not graded by the rule")

print("PASS: quote.py pin-content seam: with the rule absent from the pinned platform release "
      "the pricer says could-not-look and prices on; with it present, a pinned tree that lacks "
      "the exposure section is refused as a missing instrument and one that carries it is priced")
PYSELF
}

if [ "${1:-}" = "--selfcheck" ]; then
  selfcheck
  exit $?
fi

# stderr carries the pricer's own could-not-look NOTE, which is the thing being graded and not
# a verdict; the verdict is the single line on stdout.
_sc_rc=0
SELFCHECK_LINE="$(selfcheck 2>/dev/null)" || _sc_rc=$?
if [ "$_sc_rc" != 0 ] && [ "$_sc_rc" != 3 ]; then
  echo "${SELFCHECK_LINE:-FAIL: verify-insurer-quote.sh --selfcheck crashed}"
  exit 1
fi
export SELFCHECK_LINE

python3 - "$ADOPTERS_DIR" "$NIST_DIR" "$PLATFORM_DIR" <<'PYEOF'
import importlib.util
import json
import os
import re
import sys

import yaml

ADOPTERS_DIR, NIST_DIR, PLATFORM_DIR = sys.argv[1:4]
LINES = []


def out(status, msg):
    LINES.append(status)
    print(f"{status}: {msg}")


def load_yaml(path):
    with open(path) as fh:
        return yaml.safe_load(fh) or {}


def load_json(path):
    with open(path) as fh:
        return json.load(fh)


def close(a, b):
    return abs(float(a) - float(b)) <= max(1e-6, 1e-9 * max(abs(float(a)), abs(float(b))))


# The seam's verdict, graded above on synthetic trees, counted here so the aggregate at the
# bottom is the whole of what this script looked at.
_selfcheck = os.environ.get("SELFCHECK_LINE") or ""
if ":" in _selfcheck:
    _status, _msg = _selfcheck.split(":", 1)
    out(_status, _msg.strip())


# --- the payload schema check ------------------------------------------------
# jsonschema where the interpreter has it (the hub venv does), and a stdlib
# subset of draft-07 otherwise -- this repo's own CI and the estate's python3
# ship no jsonschema, and "could not look" for want of a library would hide the
# one check that says the published quote is the shape consumers pin.
def _subset_errors(schema, doc, root=None, path="payload"):
    root = root or schema
    errs = []
    if "$ref" in schema:
        ref = schema["$ref"].lstrip("#/").split("/")
        target = root
        for part in ref:
            target = target[part]
        return _subset_errors(target, doc, root, path)
    for sub in schema.get("allOf", []):
        errs += _subset_errors(sub, doc, root, path)
    t = schema.get("type")
    types = {"object": dict, "array": list, "string": str, "number": (int, float)}
    if t and not isinstance(doc, types[t]):
        return errs + [f"{path}: expected {t}"]
    if "enum" in schema and doc not in schema["enum"]:
        errs.append(f"{path}: {doc!r} not in {schema['enum']}")
    if isinstance(doc, str):
        if "pattern" in schema and not re.match(schema["pattern"], doc):
            errs.append(f"{path}: {doc!r} does not match {schema['pattern']}")
        if len(doc) < schema.get("minLength", 0):
            errs.append(f"{path}: shorter than minLength")
    if isinstance(doc, (int, float)) and not isinstance(doc, bool) and "minimum" in schema:
        if doc < schema["minimum"]:
            errs.append(f"{path}: {doc} < minimum {schema['minimum']}")
    if isinstance(doc, list):
        if len(doc) < schema.get("minItems", 0):
            errs.append(f"{path}: fewer than {schema['minItems']} items")
        for i, el in enumerate(doc):
            if "items" in schema:
                errs += _subset_errors(schema["items"], el, root, f"{path}[{i}]")
    if isinstance(doc, dict):
        props = schema.get("properties", {})
        for k in schema.get("required", []):
            if k not in doc:
                errs.append(f"{path}: missing required {k}")
        if schema.get("additionalProperties") is False:
            for k in doc:
                if k not in props:
                    errs.append(f"{path}: unknown key {k}")
        for k, sub in props.items():
            if k in doc:
                errs += _subset_errors(sub, doc[k], root, f"{path}.{k}")
    return errs


def schema_errors(schema, doc):
    try:
        from jsonschema import Draft7Validator
    except ImportError:
        return _subset_errors(schema, doc), "the stdlib subset check"
    return [e.message for e in Draft7Validator(schema).iter_errors(doc)], "jsonschema"


# --- the estate's own modules, at this repo's own pinned versions -------------
def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def nist_control_ids(catalog_path):
    ids = set()

    def walk(group):
        for c in group.get("controls") or []:
            ids.add(c["id"])
            for s in c.get("controls") or []:
                ids.add(s["id"])
        for g in group.get("groups") or []:
            walk(g)

    walk(load_json(catalog_path)["catalog"])
    return ids


# --------------------------------------------------------------------------
party = load_yaml("party.yaml")
published = party.get("publishes") or []
if not published:
    out("FAIL", "insurer/party.yaml publishes nothing -- there is no quote to look at")
    print("FAIL: no published quote feed")
    sys.exit(1)

pricer_path = os.path.join(os.getcwd(), "pricing", "quote.py")
if not os.path.isfile(pricer_path):
    print(f"SKIP: no {pricer_path} -- the formula that priced these quotes is not in this repo")
    sys.exit(3)
pricer = load_module("insurer_quote_pricer", pricer_path)

catalog = os.path.join(NIST_DIR, "catalog", "NIST_SP-800-53_rev5.2.0_catalog.json")
control_ids = nist_control_ids(catalog) if os.path.isfile(catalog) else None
if control_ids is None:
    out("SKIP", f"no nist catalogue at {catalog} (set NIST_DIR) -- cannot look at whether the "
                f"exclusions and conditions name real control ids")

fair_path = os.path.join(PLATFORM_DIR, "fair", "fair.py")
fair = load_module("insurer_fair", fair_path) if os.path.isfile(fair_path) else None
if fair is None:
    out("SKIP", f"no platform checkout at {PLATFORM_DIR} (set PLATFORM_DIR) -- cannot look at "
                f"whether the estate's own summing helper refuses to cross the two perspectives")

payload_schema = load_json("quote/payload.schema.json")

for entry in published:
    name, path = entry["name"], entry["path"]
    adopter = name.split("-", 1)[1]
    # by major NUMBER, not by name: sorted() would put v10 before v2.
    feeds = sorted((f for f in os.listdir(path) if re.fullmatch(r"v\d+", f)),
                    key=lambda f: int(f[1:])) if os.path.isdir(path) else []
    feed_file = os.path.join(path, feeds[-1], "feed.json") if feeds else None
    if not feed_file or not os.path.isfile(feed_file):
        out("FAIL", f"{name}: party.yaml publishes it but there is no {path}/v*/feed.json")
        continue

    doc = load_json(feed_file)
    # 1. the envelope, and the payload against the schema consumers pin
    bad = [f"{k}={doc.get(k)!r} != {v!r}" for k, v in
           (("kind", entry["kind"]), ("name", name), ("published_by", "insurer"),
            ("payload_schema", entry["payload_schema"])) if doc.get(k) != v]
    if bad:
        out("FAIL", f"{feed_file}: envelope disagrees with publishes[]: {'; '.join(bad)}")
        continue
    q = doc["payload"]
    errs, how = schema_errors(payload_schema, q)
    if errs:
        out("FAIL", f"{feed_file}: payload vs {entry['payload_schema']} ({how}): "
                    f"{'; '.join(errs[:3])}")
        continue
    out("PASS", f"{name} {doc['version']}: one ADR-0019 envelope, payload valid against "
                f"{entry['payload_schema']} ({how})")

    # the insured party's own signed facts
    adopter_party_file = os.path.join(ADOPTERS_DIR, adopter, "party.yaml")
    if not os.path.isfile(adopter_party_file):
        out("SKIP", f"{name}: no checkout of {adopter} at {ADOPTERS_DIR}/{adopter} "
                    f"(set ADOPTERS_DIR) -- cannot look at the facts this quote claims to price")
        continue
    adopter_party = load_yaml(adopter_party_file)

    # 2. the attachment IS the insured's own signed appetite
    appetite = (adopter_party.get("appetite") or {}).get("tolerance") or {}
    att = q["attachment"]
    if not appetite:
        out("FAIL", f"{name}: {adopter} signs no appetite.tolerance, so this quote's attachment "
                    f"of {att['amount']} {att['currency']} is a number no party declared")
    elif not close(att["amount"], appetite["amount"]) or att["currency"] != appetite["currency"]:
        out("FAIL", f"{name}: attachment {att['amount']:,.2f} {att['currency']} is not "
                    f"{adopter}'s own signed appetite {appetite['amount']:,.2f} "
                    f"{appetite['currency']} (ticket 14 answer 1: they are one number seen "
                    f"from two sides)")
    else:
        out("PASS", f"{name}: attachment {att['amount']:,.2f} {att['currency']} equals "
                    f"{adopter}'s own signed appetite")

    # 3. every exclusion and condition keys on something real
    try:
        exposure, exposure_path = pricer.exposure_of(adopter, ADOPTERS_DIR)
    except pricer.Refused as e:
        out("SKIP", f"{name}: {e}")
        continue
    priced_regimes = {r["name"] for r in exposure.get("regimes") or []}
    unknown_regimes = [x["regime"] for x in q["exclusions"] if x["regime"] not in priced_regimes]
    if unknown_regimes:
        out("FAIL", f"{name}: excludes regime(s) {unknown_regimes} that {adopter}'s signed "
                    f"exposure does not price -- an exclusion that excludes nothing observable "
                    f"quietly widens the cover")
    elif q["exclusions"]:
        out("PASS", f"{name}: every exclusion names a regime {adopter} actually prices "
                    f"({', '.join(sorted(priced_regimes))})")
    else:
        out("PASS", f"{name}: excludes nothing (named absence)")

    if control_ids is not None:
        named = [(x["regime"], c) for x in q["exclusions"] for c in x.get("control_ids") or []]
        named += [(f"condition:{c['consequence']}", c["id"]) for c in q["conditions"]
                  if c["source"] == "nist"]
        unreal = [f"{where}/{cid}" for where, cid in named if cid not in control_ids]
        if unreal:
            out("FAIL", f"{name}: names control id(s) {unreal} that are not in nist's published "
                        f"catalogue -- a term keyed on a control nobody publishes is unpriceable")
        elif named:
            out("PASS", f"{name}: all {len(named)} exclusion/condition control id(s) exist in "
                        f"nist's published catalogue ({os.path.basename(catalog)})")
        else:
            out("PASS", f"{name}: keys on no control ids (named absence)")

    # 4. the premium reproduces from the signed inputs, and is not stale
    quoted_hash = next((p.get("exposure_sha256") for p in q["priced_against"]
                        if p.get("party") == adopter and p.get("name") == "exposure"), None)
    live_hash = pricer.exposure_sha256(exposure)
    if quoted_hash is None:
        out("FAIL", f"{name}: priced_against names no exposure parent for {adopter}, so what it "
                    f"was priced from cannot be checked")
        continue
    if quoted_hash != live_hash:
        out("SKIP", f"{name}: priced against exposure {quoted_hash[:19]} but {exposure_path} now "
                    f"signs {live_hash[:19]} -- the insured re-signed its exposure and a re-quote "
                    f"PR is due (the clock opens one; a human merges it)")
        continue
    try:
        worked = pricer.price(exposure, pricer.terms_of(adopter))
    except pricer.Refused as e:
        out("FAIL", f"{name}: the formula that priced this quote now refuses over the same "
                    f"signed inputs: {e}")
        continue
    mismatched = [k for k in ("excluded", "insured", "layer")
                  if not close(worked[k], q["formula"][k])]
    if q["formula"]["version"] != pricer.FORMULA_VERSION:
        out("SKIP", f"{name}: priced by formula {q['formula']['version']}, but this repo now "
                    f"ships {pricer.FORMULA_VERSION} -- a re-quote under the new formula is due")
    elif mismatched or not close(worked["premium"], q["premium"]["amount"]):
        out("FAIL", f"{name}: the premium does not reproduce -- formula "
                    f"{pricer.FORMULA_VERSION} over {exposure_path} and terms/{adopter}.yaml "
                    f"gives {worked['premium']:,.2f} and {mismatched or 'the intermediates'} "
                    f"disagree; the quote says {q['premium']['amount']:,.2f}")
    else:
        out("PASS", f"{name}: premium {q['premium']['amount']:,.2f} {q['premium']['currency']} "
                    f"reproduces exactly from formula {pricer.FORMULA_VERSION} over "
                    f"{adopter}'s signed exposure ({exposure['total']:,.2f} less "
                    f"{worked['excluded']:,.2f} excluded, less the {worked['attachment']:,.2f} "
                    f"attachment, capped at the {worked['limit']:,.2f} limit)")

    # 5. no sum crosses a perspective
    if q["perspective"] == q["premium"]["perspective"]:
        out("FAIL", f"{name}: the layer arithmetic and the premium are both booked under "
                    f"{q['perspective']!r} -- the insurer's own view and the adopter's cost line "
                    f"are two perspectives (ticket 14 answer 3)")
    elif q["premium"]["perspective"] != adopter:
        out("FAIL", f"{name}: books its premium under perspective "
                    f"{q['premium']['perspective']!r}, not {adopter!r} -- a premium on "
                    f"{adopter}'s balance sheet is booked under {adopter} and no other party")
    else:
        out("PASS", f"{name}: the layer is priced under perspective {q['perspective']} and the "
                    f"premium is booked under {q['premium']['perspective']} -- two perspectives, "
                    f"never one sum")

    if fair is not None:
        mixed = [{"perspective": q["perspective"], "currency": q["currency"],
                  "amount": q["formula"]["layer"]},
                 {"perspective": q["premium"]["perspective"], "currency": q["premium"]["currency"],
                  "amount": q["premium"]["amount"]}]
        try:
            fair.sum_prices(mixed)
            out("FAIL", f"{name}: platform/fair/fair.py summed the insurer's layer with "
                        f"{adopter}'s premium instead of refusing")
        except ValueError:
            out("PASS", f"{name}: the estate's own summing helper refuses to add this quote's "
                        f"layer to its premium -- the two perspectives cannot be totalled")

    # the premium as it actually lands on the insured's sheet
    evidence_file = os.path.join(ADOPTERS_DIR, adopter, "composed", "evidence.json")
    subscribes = any(i.get("party") == "insurer" and i.get("name") == name
                     for i in adopter_party.get("inherits") or [])
    if not subscribes:
        out("PASS", f"{name}: {adopter} does not pin this quote yet, so no premium line is "
                    f"expected on its sheet (named absence: a quote is published, not imposed)")
    elif not os.path.isfile(evidence_file):
        out("SKIP", f"{name}: {adopter} pins this quote but has composed no evidence to book it "
                    f"into ({evidence_file})")
    else:
        prices = load_json(evidence_file).get("prices") or []
        booked = [p for p in prices if p.get("kind") == "premium" and p.get("name") == name]
        if len(booked) != 1:
            out("FAIL", f"{name}: {adopter} pins this quote but its prices[] carries "
                        f"{len(booked)} premium entries for it, not exactly one")
        else:
            b = booked[0]
            reporting = adopter_party.get("reporting_currency") or "USD"
            if b["perspective"] != adopter or b["currency"] != reporting:
                out("FAIL", f"{name}: the booked premium is {b['perspective']}/{b['currency']}, "
                            f"not {adopter}/{reporting}")
            elif b["currency"] == q["premium"]["currency"] and \
                    not close(b["amount"], q["premium"]["amount"]):
                out("FAIL", f"{name}: {adopter} books {b['amount']:,.2f} {b['currency']} but the "
                            f"signed quote says {q['premium']['amount']:,.2f} "
                            f"{q['premium']['currency']}")
            else:
                per = (f", {b['per_customer']['amount']:.2f} per customer"
                        if b.get("per_customer") else "")
                out("PASS", f"{name}: {adopter} books it as one contract cost line, "
                            f"{b['amount']:,.2f} {b['currency']} under perspective "
                            f"{b['perspective']}{per}")

if "FAIL" in LINES:
    print(f"FAIL: {LINES.count('FAIL')} of {len(LINES)} checks observed false")
    sys.exit(1)
if "SKIP" in LINES:
    print(f"SKIP: {LINES.count('SKIP')} of {len(LINES)} checks could not be looked at "
          f"(reasons above)")
    sys.exit(3)
print(f"PASS: {len(LINES)} checks -- every published quote validates, attaches at the insured's "
      f"own signed appetite, keys on real control ids, reproduces its premium from signed "
      f"inputs, and crosses no perspective")
sys.exit(0)
PYEOF
