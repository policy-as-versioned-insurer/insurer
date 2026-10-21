# policy-as-versioned-insurer

**GitHub org:** [`policy-as-versioned-insurer`](https://github.com/policy-as-versioned-insurer) ·
**Role:** insurer — publisher · **Licence:** [Apache-2.0](LICENSE)

*A demonstration party, not affiliated with, endorsed by or speaking for any real authority it names.*

Part of the *Policy as Versioned Code* estate: the insurer pins the platform and each adopter's
own signed exposure as parents (`inherits[]`, ADR-0019) and publishes one `quote` feed per
adopter — the premium, its terms and what it excludes, priced under the insurer's own perspective
from facts the adopter already signed.

| what | where |
| --- | --- |
| the parents this party prices from | `party.yaml` `inherits[]`, and the platform pin in `gitops/platform/platform-pin.yaml` |
| this carrier's own signed terms | `terms/<adopter>.yaml` — limit, exclusions, conditions, rate and load |
| the formula, versioned | `pricing/quote.py` — `layer-rate-on-line` 1.0.0, with its own `selfcheck` |
| the published quotes | `quote/<adopter>/v1/feed.json`, with `rule.yaml` and `bump.yaml` beside them |
| the shape consumers pin | `quote/payload.schema.json` |
| the clock | `.github/workflows/fetch.yml`, job `requote` — daily, opens a PR, never commits a quote |
| what the gate looks at | `verify-insurer-quote.sh`, `verify-insurer-party.sh` |

The attachment is not this carrier's number: it **is** the adopter's own signed
`appetite.tolerance`, read off the exposure section the adopter renders into its composed
artefact. The premium is a contract cost booked under the *adopter's* perspective, beside its
other costs; the layer arithmetic that produced it stays under `perspective: insurer` and the two
are never summed. Nothing here is signed by anything but this repo's own gitsign tag.

## Illustrative quote contract v2 (ticket162)

New quotes carry `usage: illustrative` and a plain disclosure on the payload itself: the
counterparty and quote are model-only ordinal comparisons, not independent insurance or
actuarial assurance. `quote/payload.v2.schema.json` requires that disclosure; the original
v1 schema and quote files remain unchanged. Changing the payload schema requires a major
feed release under ADR0019. Formula1, signed economic inputs and validity dates are unchanged.

`python3 pricing/quote.py feed-path <adopter>` prints the destination derived from that
adopter's declared terms version. The scheduled proposer uses this same path for reading
the generated premium and restricting its proposed files. The native reader uses the
publication's declared schema and does not treat a v1 subscription/book as adoption of v2.
Its default runs registered synthetic CLI/reader proofs and the actual artifact checks;
`--published-only` runs only the latter, while `--selfcheck` runs only synthetic proofs.
Synthetic Git tags/transport fixtures never establish genuine signature or insurance credit.

The source-only implementation is not a v2 publication: new version/publication metadata,
genuine pinned-input rendering, native verification and normal signed release remain required.
