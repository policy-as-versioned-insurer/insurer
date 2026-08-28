# policy-as-versioned-insurer

**GitHub org:** [`policy-as-versioned-insurer`](https://github.com/policy-as-versioned-insurer) ·
**Role:** insurer — publisher · **Licence:** [Apache-2.0](LICENSE)

Part of the *Policy as Versioned Code* estate: the insurer pins the platform and an adopter's
own signed exposure artefact as parents (`inherits[]`, ADR-0019) and publishes one `quote` feed
per adopter — the premium, its terms and what it excludes, priced under the insurer's own
perspective from facts the adopter already signed. The pricing seat itself, the scheduled
re-quote workflow and the first real quote payload are ticket 36 and are not built yet; this repo
today carries the party artefact, the payload schema and the release plumbing the feed contract
(ticket 21) requires so the rest of the estate can name and pin what this party will publish.
