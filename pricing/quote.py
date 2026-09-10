#!/usr/bin/env python3
"""quote.py -- the insurer's pricer. One signed quote feed per insured adopter,
priced from facts the adopter and the platform already signed (ticket 36;
policy-composition ticket 14 answers 1 to 5; ADR-0019, ADR-0020, ADR-0021).

WHAT IT READS, and nothing else:
  * the adopter's own signed `exposure` section, off its composed artefact
    (`composed/HEADER.yaml`): its total priced exposure under its OWN
    perspective and currency, its appetite as the attachment, and the breakdown
    by regime name and control id. The insurer does not model the adopter's
    business; it prices what the adopter signed.
  * this repo's own signed terms for that adopter (`terms/<adopter>.yaml`): the
    limit, the exclusions, the rate and the load. Independence of view comes
    from the insurer's own signed inputs, not from different arithmetic
    (ticket 14 answer 5).

THE FORMULA -- version 1.0.0, and every quote names the version that priced it:

    excluded  = for each exclusion {regime, control_ids}:
                  no control_ids  -> the whole regime line's amount
                  control_ids     -> the named controls' amounts within it
    insured   = exposure.total - excluded
    layer     = min(max(insured - attachment, 0), limit)
    premium   = round(layer * rate * (1 + load), 2)

  The attachment IS the adopter's own signed appetite, seen from the other side
  (ticket 14 answer 1): the retention it already declared, never a second number
  this repo proposes. The exclusions key on the same regime names and (source,
  id) control keys the composition already prices on, so an excluded item is
  priced as retained with no new lookup.

  ponytail ceiling: `layer * rate` is a rate-on-line over the exposure inside
  the layer, NOT the expected loss between attachment and limit. The adopter
  signs a point total, not an aggregate loss distribution, and a TVaR-between-
  attachment-and-limit needs the distribution (ticket 14 answer 2's fuller
  shape: per-risk annual loss lists summed year by year in fair.py). Upgrade
  path, in order: composition's exposure section gains {ale, var95, tvar, tail}
  beside the total; this formula goes to 2.0.0 and reads
  `premium = (1 + load) * E[loss in layer]` off that distribution; the quote
  payload does not change shape, only `formula.version`. Until then the rate is
  the calibration knob and it is stated in the terms file, signed, per adopter.

PERSPECTIVES. The arithmetic above is the INSURER's own view and is booked under
`perspective: insurer`. The premium it produces is a CONTRACT COST under the
ADOPTER's perspective -- what the adopter pays, beside costs.fix -- and that is
the only number that crosses into the adopter's prices[] (ticket 14 answer 3,
ADR-0021). No sum here ever crosses the two.

Usage:
    quote.py render  <adopter> [--adopters-dir DIR] [--published-at TS]
    quote.py show    <adopter> [--adopters-dir DIR]     # the payload, no write
    quote.py selfcheck                                  # runnable asserts
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# The formula's own version. A change to the arithmetic above changes this, and
# every quote payload names it, so a premium is reproducible from the exact
# formula that priced it and never from "whatever the pricer does today".
FORMULA = "layer-rate-on-line"
FORMULA_VERSION = "1.0.0"

PAYLOAD_SCHEMA = "quote/payload.schema.json"
# Where an adopter's own signed exposure lives inside its repo.
EXPOSURE_FILE = os.path.join("composed", "HEADER.yaml")

# This insurer pins `platform` in its own party.yaml and gitops/platform/platform-pin.yaml, and
# reads ONE rule out of that pinned checkout: platform/party/pin_content.py, which says a pinned
# tree must carry the section the pin is used for (eco-system ticket 77 item 1). Copying the rule
# here would make two rules that could disagree; importing it through the pinned dependency is the
# same "library, not a service" shape every adopter's shift-left.yml already uses for
# party_artefact.py and composition.py. PLATFORM_DIR is the checkout, the way verify-insurer-
# quote.sh already names it; the release and fetch workflows check platform out at the pin.
# A PINNED release that does not carry the rule yet is a could-not-look and not a refusal -- see
# pin_content() below, which is where that decision is written down and why.
PLATFORM_DIR = os.environ.get("PLATFORM_DIR") or os.path.join(os.path.dirname(REPO), "platform")


class Refused(Exception):
    """A missing instrument (ADR-0020): the insurer cannot read a signed fact it
    must price from. Never a guessed number."""


# --------------------------------------------------------------------------
# reading the signed inputs
# --------------------------------------------------------------------------
def load_yaml(path):
    with open(path) as fh:
        return yaml.safe_load(fh) or {}


def exposure_of(adopter, adopters_dir):
    """The adopter's OWN signed exposure section, and the path it was read from."""
    path = os.path.join(adopters_dir, adopter, EXPOSURE_FILE)
    if not os.path.isfile(path):
        raise Refused(f"missing instrument: no {path} -- {adopter} has published no composed "
                      f"artefact this insurer can price from")
    exposure = (load_yaml(path) or {}).get("exposure")
    if not exposure:
        raise Refused(f"missing instrument: {path} carries no `exposure` section -- there is no "
                      f"signed exposure to attach a layer to")
    return exposure, path


def pin_content():
    """platform/party/pin_content.py, out of this repo's PINNED platform checkout, or None when
    the platform release this repository pins does not carry it.

    None is a COULD-NOT-LOOK, deliberately, and not a refusal. The rule is new on the platform's
    `ecosystem/build-2026-09-03` branch and no signed platform tag carries it yet (checked
    2026-09-04, tag by tag: v0.1.0 to v2.0.1 and policy/v2.0.0 to policy/v4.0.0 -- none has
    party/pin_content.py). Refusing here would have stopped a re-quote clock that works today on
    every adopter, on the ground that a rule the estate has not released yet could not be read:
    that is a check breaking the thing it grades. The pin is checked instead by the hub's
    verify/feed-contract, which reads the publisher's real tag with git plumbing and needs no
    platform release, and the day platform cuts a tag carrying this file the insurer's pin bump
    turns the rule on here with no further change. See ## Waits on the owner in eco-system
    ticket 77."""
    path = os.path.join(PLATFORM_DIR, "party", "pin_content.py")
    if not os.path.isfile(path):
        return None
    spec = importlib.util.spec_from_file_location("pin_content", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def refuse_unless_tree_carries_exposure(adopter, adopters_dir, parents):
    """Ticket 77 item 1, the insurer's half: never emit `priced_against` naming a version whose
    tree does not carry an `exposure` section.

    The tree graded is the one this pricer was handed. Whether that tree is really the pinned
    tag is asserted where it can be: fetch.yml checks the adopter out at `ref: <the pin>` and
    nowhere else, and the hub's verify/feed-contract resolves the same pin against the adopter's
    real remote. What is checked HERE is the thing only the pricer knows -- that the content the
    premium was computed from is the content the pin names.

    Returns True when the rule ran, False when it could not be read out of the pinned platform
    checkout. A could-not-look is announced on STDERR and never on stdout: `bump` writes the
    computed bump to stdout and fetch.yml captures it."""
    pin = next((p for p in parents if p["party"] == adopter), None)
    if pin is None:                       # parents_of() has already refused; belt and braces
        raise Refused(f"missing instrument: no exposure pin for {adopter} to price against")
    rule = pin_content()
    if rule is None:
        print(f"NOTE: the platform release this repository pins "
              f"(gitops/platform/platform-pin.yaml) carries no party/pin_content.py at "
              f"{PLATFORM_DIR} -- no platform tag does yet -- so whether {adopter}'s pinned tree "
              f"really carries the exposure section this quote prices was NOT checked here. It "
              f"is checked by the hub's verify/feed-contract against {adopter}'s real remote, "
              f"which today says could-not-look on this very pin. This is a could-not-look, not "
              f"a pass and not a refusal.", file=sys.stderr)
        return False
    lacks = rule.refusal_for_pin(
        os.path.join(adopters_dir, adopter), adopter, "feed", "exposure", pin["version"],
        require_declaration=True)
    if lacks:
        raise Refused(lacks)
    return True


def exposure_sha256(exposure):
    """A content digest of the exact exposure section a quote was priced against
    (ticket 14 answer 3's exposure hash). Canonical JSON, so the digest is of
    the facts and not of their YAML layout."""
    return "sha256:" + hashlib.sha256(
        json.dumps(exposure, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def terms_of(adopter):
    path = os.path.join(REPO, "terms", f"{adopter}.yaml")
    if not os.path.isfile(path):
        raise Refused(f"missing instrument: this insurer has signed no terms for {adopter} "
                      f"({path}) -- there is nothing to quote")
    return load_yaml(path)


def parents_of(adopter):
    """What this quote is priced against, read off this repo's OWN party.yaml
    `inherits[]` and nowhere else -- so `priced_against` names the exact
    versions this insurer pins, and a Renovate bump of a pin is what re-prices
    a quote (ticket 14 answers 3 and 5; ADR-0019).

    Two parents: the platform whose fair.py and composition define the £, and
    the insured adopter's own signed exposure."""
    inherits = load_yaml(os.path.join(REPO, "party.yaml")).get("inherits") or []
    parents = [dict(e) for e in inherits
               if (e.get("party") == "platform" and e.get("kind") == "implementations")
               or (e.get("party") == adopter and e.get("name") == "exposure")]
    for e in parents:
        e.pop("since", None)
    if not any(p["party"] == adopter for p in parents):
        raise Refused(f"missing instrument: this insurer's party.yaml pins no exposure parent "
                      f"for {adopter}, so a quote for it would name no signed source")
    if not any(p["party"] == "platform" for p in parents):
        raise Refused("missing instrument: this insurer's party.yaml pins no platform "
                      "implementations parent, so the £ it prices in is unattributable")
    return parents


# --------------------------------------------------------------------------
# the formula
# --------------------------------------------------------------------------
def excluded_amount(exposure, exclusions):
    """What the exclusions take out of the adopter's own priced exposure, keyed
    on ITS OWN regime names and (source, id) control keys. An exclusion naming a
    regime or a control the exposure does not carry is a missing instrument: an
    exclusion that excludes nothing observable would quietly widen the cover."""
    by_name = {r["name"]: r for r in exposure.get("regimes") or []}
    total = 0.0
    for ex in exclusions or []:
        regime = by_name.get(ex["regime"])
        if regime is None:
            raise Refused(f"missing instrument: exclusion names regime {ex['regime']!r}, which "
                          f"{exposure['perspective']}'s signed exposure does not price")
        ids = ex.get("control_ids") or []
        if not ids:
            total += float(regime["amount"])
            continue
        priced = {c["id"]: float(c["amount"]) for c in regime.get("controls") or []}
        for cid in ids:
            if cid not in priced:
                raise Refused(f"missing instrument: exclusion names {ex['regime']}/{cid}, which "
                              f"the signed exposure does not partition a price onto")
            total += priced[cid]
    return total


def price(exposure, terms):
    """The formula, and the working it showed. Returns every intermediate the
    verify script re-derives, so the premium is reproducible from signed inputs
    and this function's own arithmetic is never the only witness to it."""
    if terms["currency"] != exposure["currency"]:
        # ADR-0020: no rate, no relabelling. The composition converts a premium
        # in another currency through the signed FX feed when it books it; the
        # LAYER, though, is arithmetic on the adopter's own figures and cannot
        # be done in two currencies at once.
        raise Refused(f"missing instrument: terms are in {terms['currency']} but "
                      f"{exposure['perspective']}'s exposure is in {exposure['currency']} -- "
                      f"a layer is not computed across two currencies")
    attachment = float(exposure["attachment"]["amount"])
    if exposure["attachment"]["currency"] != exposure["currency"]:
        raise Refused(f"missing instrument: {exposure['perspective']} signs its appetite in "
                      f"{exposure['attachment']['currency']} and its exposure in "
                      f"{exposure['currency']}; the attachment cannot be compared to the total")
    excluded = excluded_amount(exposure, terms.get("exclusions"))
    insured = float(exposure["total"]) - excluded
    limit = float(terms["limit"]["amount"])
    layer = min(max(insured - attachment, 0.0), limit)
    premium = round(layer * float(terms["rate"]) * (1.0 + float(terms["load"])), 2)
    return {"excluded": excluded, "insured": insured, "attachment": attachment,
            "limit": limit, "layer": layer, "premium": premium}


# --------------------------------------------------------------------------
# the implied loss ratio (eco-system ticket 79 item 6)
# --------------------------------------------------------------------------
# THE DEFAULT BAND, when a terms file declares none. Delegated (ADR-0025); the
# reason is below and a terms file overrides it per adopter.
DEFAULT_LOSS_RATIO_BAND = {"min": 5.0, "max": 50.0}


def implied_loss_ratio(worked, terms):
    """The ORDINAL exposure inside the layer over the premium — printed on EVERY
    run of verify-insurer-quote.sh, and red outside a declared band. It is what
    eco-system ticket 79 item 6 asked for as "expected layer loss over premium",
    and it is deliberately NOT called that here, because no expected layer loss
    exists to divide by anything (below).

    WHAT THE NUMERATOR ACTUALLY IS, said before the number is used. A true loss
    ratio wants E[loss in the layer]. The insured signs a POINT TOTAL, not an
    aggregate loss distribution, so no expected layer loss exists to divide by
    anything. The numerator here is the LAYER itself: the insured's own ordinal,
    auditable exposure sitting between the attachment and the limit (ticket 75
    Q4; the composed artefact carries the same sentence on its total from
    eco-system ticket 79 item 10). So this is the reciprocal of the rate on line,
    not an actuarial loss ratio, and this function says so rather than borrowing
    the name's authority.

    And it is an IDENTITY, which is the useful part:

        layer / premium  ==  1 / (rate x (1 + load))

    exactly, because `premium = layer x rate x (1 + load)`. The ratio therefore
    carries no information about the insured at all -- it is a statement about
    this carrier's own two knobs. That makes it exactly the right thing to band:
    a ratio above the band means the premium is a token sum against the layer it
    stands behind (a rate on line so thin the account cannot fund itself), and
    one below it means the premium approaches the whole ordinal exposure, which
    is not cover, it is prepayment. The band is declared in the carrier's own
    signed terms and printed beside the number.

    A layer of zero (an exposure inside the retention) is not a ratio at all and
    is returned as a NAMED absence, never as a division or a zero.
    """
    # Review F6: WHERE the band came from, not just what it is. The verdict line
    # used to say "declared in terms/<adopter>.yaml" whether or not it was: with
    # `loss_ratio_band` deleted from a terms file it still said so, while the band
    # came from the module default below.
    band = dict(DEFAULT_LOSS_RATIO_BAND)
    declared = terms.get("loss_ratio_band")
    band_source = ("pricing/quote.py DEFAULT_LOSS_RATIO_BAND -- this carrier's own terms file "
                   "declares no `loss_ratio_band`")
    if isinstance(declared, dict):
        given = {k: float(v) for k, v in declared.items() if k in ("min", "max")}
        band.update(given)
        band_source = ("the carrier's own signed terms, which declare "
                        + ", ".join(f"{k} {v}" for k, v in sorted(given.items()))
                        + (" (the other end is pricing/quote.py's default)"
                           if len(given) < 2 else ""))
    layer, premium = float(worked["layer"]), float(worked["premium"])
    identity = 1.0 / (float(terms["rate"]) * (1.0 + float(terms["load"])))
    if layer <= 0 or premium <= 0:
        return {"ratio": None, "band": band, "band_source": band_source,
                "identity": identity, "in_band": None,
                "basis": ("the layer is %.2f and the premium is %.2f, so there is no ratio to "
                           "take: this account's exposure sits inside its own retention. A named "
                           "absence, not a zero." % (layer, premium))}
    ratio = layer / premium
    return {
        "ratio": ratio,
        "band": band,
        "band_source": band_source,
        "identity": identity,
        "in_band": band["min"] <= ratio <= band["max"],
        "basis": ("%.4f = layer %.2f / premium %.2f, and identically 1 / (rate %.4f x (1 + load "
                   "%.4f)) = %.4f. The numerator is the insured's ORDINAL exposure inside the "
                   "layer, not an expected layer loss -- the insured signs a point total and no "
                   "distribution exists to take one from -- so this is the reciprocal of the "
                   "rate on line and NOT an actuarial loss ratio. It becomes one at formula "
                   "2.0.0, when the exposure section carries {ale, var95, tvar, tail} and the "
                   "premium is priced as (1 + load) x E[loss in layer]."
                   % (ratio, layer, premium, float(terms["rate"]), float(terms["load"]),
                      identity)),
    }


# --------------------------------------------------------------------------
# the envelope
# --------------------------------------------------------------------------
def payload(adopter, adopters_dir):
    # The shared rule FIRST (ticket 77 item 1), so the refusal a reader sees is the estate's one
    # sentence about pins and not this file's private restatement of half of it.
    parents = parents_of(adopter)
    refuse_unless_tree_carries_exposure(adopter, adopters_dir, parents)
    exposure, _ = exposure_of(adopter, adopters_dir)
    if exposure["perspective"] != adopter:
        raise Refused(f"missing instrument: {adopter}'s composed artefact signs an exposure "
                      f"under perspective {exposure['perspective']!r}")
    terms = terms_of(adopter)
    worked = price(exposure, terms)
    return {
        "adopter": adopter,
        # The insurer's own arithmetic is the insurer's view; the premium below
        # is booked on the adopter's sheet. Two perspectives, never one sum.
        "perspective": "insurer",
        "currency": terms["currency"],
        "attachment": {"amount": worked["attachment"], "currency": exposure["currency"]},
        "limit": terms["limit"],
        "exclusions": terms.get("exclusions") or [],
        "premium": {"amount": worked["premium"], "currency": terms["currency"],
                     "perspective": adopter},
        "formula": {"id": FORMULA, "version": FORMULA_VERSION,
                     "rate": float(terms["rate"]), "load": float(terms["load"]),
                     "excluded": worked["excluded"], "insured": worked["insured"],
                     "layer": worked["layer"]},
        "valid_from": terms["valid_from"],
        "valid_until": terms["valid_until"],
        "priced_against": [
            dict(p, **({"exposure_sha256": exposure_sha256(exposure)}
                        if p.get("name") == "exposure" else {}))
            for p in parents
        ],
        "conditions": terms.get("conditions") or [],
    }


def envelope(adopter, adopters_dir, published_at=None):
    """The ADR-0019 envelope. The signature is the gitsign tag on this repo and
    nothing else -- there is no in-band signature field."""
    terms = terms_of(adopter)
    return {
        "kind": "feed",
        "name": f"quote-{adopter}",
        "version": terms["version"],
        "published_by": "insurer",
        "published_at": published_at or terms["published_at"],
        "payload_schema": PAYLOAD_SCHEMA,
        "payload": payload(adopter, adopters_dir),
    }


def feed_path(adopter):
    return os.path.join(REPO, "quote", adopter,
                         "v" + terms_of(adopter)["version"].split(".")[0], "feed.json")


def render(adopter, adopters_dir, published_at=None):
    doc = envelope(adopter, adopters_dir, published_at)
    path = feed_path(adopter)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")
    return path, doc


# --------------------------------------------------------------------------
# what "changed" means for a quote (ADR-0019, decision D2)
# --------------------------------------------------------------------------
def _split(value, prefix=""):
    """(every numeric leaf keyed by its path, the document with the numbers
    blanked) -- the two halves feeds/bump.py compares, so a re-quote whose only
    difference is a number inside the declared tolerance is an observation and
    not a release.

    ponytail: the semantics are feeds/bump.py's and this is a second copy of
    them. This repo pins no `feeds` parent, and the clock must compute its own
    bump on a runner that has only this checkout. It is the SMALL half of that
    ladder: a quote payload has a fixed key set, so bump.py's entry-added and
    entry-removed rungs are unreachable here and are not copied. Upgrade path:
    the day the insurer pins the feeds repo (it would have to subscribe to
    something it publishes), import bump.py and delete this."""
    if isinstance(value, bool):
        return {}, value
    if isinstance(value, (int, float)):
        return {prefix: float(value)}, "<number>"
    if isinstance(value, dict):
        pairs = {k: _split(v, f"{prefix}.{k}") for k, v in value.items()}
        numbers = {p: n for half in pairs.values() for p, n in half[0].items()}
        return numbers, {k: half[1] for k, half in pairs.items()}
    if isinstance(value, list):
        halves = [_split(v, f"{prefix}[{i}]") for i, v in enumerate(value)]
        return ({p: n for half in halves for p, n in half[0].items()},
                [half[1] for half in halves])
    return {}, value


def _within(old, new, tolerance):
    if old == new:
        return True
    scale = max(abs(old), abs(new))
    return scale > 0 and abs(new - old) / scale <= tolerance


def bump(adopter, adopters_dir):
    """The bump between what is published for this adopter and what today's
    re-price produces, under the feed's own versioned rule.yaml. The clock opens
    a PR only when this is not "none" (decision D2); below the threshold it
    appends an observation and commits nothing."""
    path, new = feed_path(adopter), envelope(adopter, adopters_dir)
    if not os.path.isfile(path):
        return "major"     # nothing published yet: the first release of this feed
    with open(path) as fh:
        old = json.load(fh)
    if old.get("payload_schema") != new["payload_schema"]:
        return "major"     # ADR-0019: a payload_schema change is always major
    rule = load_yaml(os.path.join(os.path.dirname(path), os.pardir, "rule.yaml"))
    old_numbers, old_shape = _split(old.get("payload", {}))
    new_numbers, new_shape = _split(new["payload"])
    if old_shape != new_shape or set(old_numbers) != set(new_numbers):
        return "patch"
    tolerance = float(rule["numeric_tolerance"])
    if all(_within(v, new_numbers[k], tolerance) for k, v in old_numbers.items()):
        return "none"
    return "patch"


# --------------------------------------------------------------------------
# the check that fails if the arithmetic breaks
# --------------------------------------------------------------------------
def selfcheck():
    exposure = {
        "perspective": "acme", "currency": "GBP",
        "attachment": {"amount": 10_000.0, "currency": "GBP"},
        "total": 1_000_000.0,
        "regimes": [
            {"name": "uk-gdpr", "source": "ico", "feed": "penalty-schema", "version": "v3",
             "amount": 900_000.0,
             "controls": [{"source": "nist", "id": "pl-2", "amount": 600_000.0},
                          {"source": "nist", "id": "ra-3", "amount": 300_000.0}]},
            {"name": "threat-register", "source": "feeds", "feed": "threat-register",
             "version": "v1", "amount": 100_000.0, "controls": []},
        ],
    }
    terms = {"currency": "GBP", "limit": {"amount": 500_000.0, "currency": "GBP"},
             "rate": 0.04, "load": 0.25,
             "exclusions": [{"regime": "uk-gdpr", "control_ids": ["pl-2"]}]}

    w = price(exposure, terms)
    assert w["excluded"] == 600_000.0, w
    assert w["insured"] == 400_000.0, w
    assert w["layer"] == 390_000.0, w                       # 400,000 - 10,000 attachment
    assert w["premium"] == round(390_000.0 * 0.04 * 1.25, 2) == 19_500.0, w
    print("ok  formula %s: exclusion partitions the regime, the attachment is retained, "
          "the premium is layer * rate * (1 + load)" % FORMULA_VERSION)

    # the limit clamps
    clamped = price(exposure, dict(terms, limit={"amount": 100_000.0, "currency": "GBP"}))
    assert clamped["layer"] == 100_000.0, clamped
    print("ok  the layer clamps at the limit")

    # eco-system ticket 79 item 6: the implied loss ratio, and the identity that
    # makes it a statement about the carrier's own knobs.
    lr = implied_loss_ratio(w, terms)
    assert abs(lr["ratio"] - lr["identity"]) < 1e-9, lr
    assert abs(lr["ratio"] - 1.0 / (terms["rate"] * (1.0 + terms["load"]))) < 1e-9, lr
    tight = implied_loss_ratio(w, dict(terms, loss_ratio_band={"min": 0.0, "max": 0.5}))
    assert tight["in_band"] is False, tight
    # review F6: a band that came from the default must not claim the terms file
    bare = implied_loss_ratio(w, {k: v for k, v in terms.items() if k != "loss_ratio_band"})
    assert "DEFAULT_LOSS_RATIO_BAND" in bare["band_source"], bare
    assert "signed terms" in tight["band_source"], tight
    wide = implied_loss_ratio(w, dict(terms, loss_ratio_band={"min": 0.0, "max": 1e9}))
    assert wide["in_band"] is True, wide
    zero = implied_loss_ratio(price(exposure, dict(terms, limit={"amount": 0.0,
                                                                  "currency": "GBP"})), terms)
    assert zero["ratio"] is None and "named absence" in zero["basis"], zero
    print("ok  the implied loss ratio is %.4f = layer/premium = 1/(rate x (1+load)); a band it "
          "sits outside reds, and a zero layer is a named absence" % lr["ratio"])

    # an exposure entirely below the attachment buys nothing
    small = price(dict(exposure, total=5_000.0, regimes=[]), dict(terms, exclusions=[]))
    assert small["layer"] == 0.0 and small["premium"] == 0.0, small
    print("ok  an exposure inside the retention is a zero layer, not a negative one")

    # excluding a whole regime, not a control within it
    whole = price(exposure, dict(terms, exclusions=[{"regime": "uk-gdpr", "control_ids": []}]))
    assert whole["excluded"] == 900_000.0, whole
    print("ok  an exclusion with no control ids excludes the whole regime line")

    # every refusal bites: an unreadable instrument is never a number
    for bad, why in (
        (dict(terms, exclusions=[{"regime": "pci-dss", "control_ids": []}]), "unpriced regime"),
        (dict(terms, exclusions=[{"regime": "uk-gdpr", "control_ids": ["ac-6"]}]), "unpriced control"),
        (dict(terms, currency="USD"), "a layer across two currencies"),
    ):
        try:
            price(exposure, bad)
        except Refused:
            continue
        raise AssertionError(f"priced {why} instead of refusing")
    print("ok  every missing instrument refuses and none of them invents a premium")

    # the digest is of the facts, not of their layout
    assert exposure_sha256(exposure) == exposure_sha256(json.loads(json.dumps(exposure)))
    print("ok  exposure_sha256 is stable over a round trip")

    # what "changed" means (D2): a sub-threshold premium move is an observation
    def payloads(premium, **rest):
        base = {"adopter": "acme", "premium": {"amount": premium, "currency": "GBP"},
                "exclusions": [{"regime": "uk-gdpr", "control_ids": ["pl-2"]}]}
        base.update(rest)
        return base

    tol = 0.02
    same = _split(payloads(100_000.0))
    near = _split(payloads(101_000.0))          # +1%, inside the tolerance
    far = _split(payloads(110_000.0))           # +10%, outside it
    other = _split(payloads(100_000.0, exclusions=[{"regime": "uk-gdpr", "control_ids": []}]))
    assert same[1] == near[1] == far[1], "blanking the numbers should leave one shape"
    assert all(_within(v, near[0][k], tol) for k, v in same[0].items())
    assert not all(_within(v, far[0][k], tol) for k, v in same[0].items())
    assert same[1] != other[1], "a changed exclusion is a shape change, not a number"
    print("ok  the bump rule: a premium move inside numeric_tolerance is an observation, one "
          "outside it and any non-numeric change are a release a human merges")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("render", "show", "bump"):
        p = sub.add_parser(name)
        p.add_argument("adopter")
        p.add_argument("--adopters-dir", default=os.path.dirname(REPO),
                        help="where the adopter repos are checked out (default: beside this one)")
        if name == "render":
            p.add_argument("--published-at", default=None)
    sub.add_parser("selfcheck")
    args = ap.parse_args(argv)

    if args.cmd == "selfcheck":
        return selfcheck()
    try:
        if args.cmd == "show":
            print(json.dumps(envelope(args.adopter, args.adopters_dir), indent=2))
        elif args.cmd == "bump":
            print(bump(args.adopter, args.adopters_dir))
        else:
            path, _ = render(args.adopter, args.adopters_dir, args.published_at)
            print(f"wrote {path}")
    except Refused as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
