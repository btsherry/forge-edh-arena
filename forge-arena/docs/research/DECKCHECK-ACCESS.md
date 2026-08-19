# DeckCheck.co — programmatic access (test results)

**Date:** 2026-08-11. **Context:** Anthony (DeckCheck.co owner) opened the deck
data endpoint so it no longer requires a key and is rate-limited to ~10 req/s,
now carrying the AI-related data (analysis prose, CRISPI stats, bracket). This
doc records what works, established black-box against the live site. It is the
factual companion to `SPEC-arena-add-deck.md` step 5 (strategy primer) and its
"real arrangement with DeckCheck, don't scrape" stance.

> **Standing policy (unchanged):** we do not scrape or automate against DeckCheck
> without the owner's blessing. The keyless *read* endpoint below was opened for
> us deliberately and is fine to use. The *create + analyze* path (below) spends
> credits and is session-authed — hold it pending an explicit arrangement with
> Anthony.

---

## 1. Reading a deck's analysis — WORKS, keyless (tested)

```
GET https://deckcheck.co/builder/api/public/deck/{deckId}
```

- **No API key, no auth cookie.** Returns `application/json` (~268 KB for the
  test deck). No throttling hit across ~30 probe requests.
- `{deckId}` is the id in a builder/share URL (`/app/builder/{deckId}`) and the
  payload's `id` / `deckview_id` field.
- The deck must be public or **unlisted** (the test deck was `visibility: unlisted`).
- **Note on the path:** the bare `/deck` path *is* a live Flask route (GET/HEAD/
  OPTIONS — POST → 405) but 404s for a normal deck id. The working data path is
  `/builder/api/public/deck/{id}`, which is what the app itself calls. Anthony
  referred to it as "the /deck endpoint" — confirm whether that is the canonical
  public URL or whether a cleaner top-level `/deck/{id}` alias is intended.

### Worked example — `l7wP9TzWfwkq`

Deck **"Mono Red Big Wheels 25.1"**, commander **Purphoros, God of the Forge**,
creator `l8knight`, `visibility: unlisted`. All three AI payloads present:

| Data | Field(s) | Value in the test deck |
|---|---|---|
| **Analysis prose** | `full_analysis` | 19,541 chars of HTML (Overview + sections, `data-card-name` spans) |
| | `analysis_preview` | 880-char plain summary |
| | `has_full_analysis` / `analysis_intelligence_level` | `true` / `null` |
| **CRISPI stats** | `attribute_ratings` | `consistency 6.75 · interaction 5.25 · resilience 10.0 · speed 6.5` |
| | `metadata.performanceIndex` | `7.25` |
| **Bracket** | `metadata.bracketLevel` | `4` |
| | `metadata.bracketDescription` | full `all_violations` breakdown per bracket tier |
| Composition | `cards` | 78 entries (`metadata.totalCards` 100) |
| | `commander` / `commander2` / `companion` | Purphoros, God of the Forge / — / — |
| | `deck_roles` | `{"commander": ["Purphoros, God of the Forge"]}` |
| | `metadata` | `avgCmc 3.19`, `deckCostRaw 3169.49`, `color_identity ["R"]`, `isPrecon false` |
| | `format_label` / `format_legal` | Commander / `true` |

**Full top-level key set:** `analysis_intelligence_level, analysis_preview,
attribute_ratings, cards, commander, commander2, companion, considering,
created_at, creator, deck_format, deck_roles, deckview_id, format_label,
format_legal, full_analysis, has_deckview, has_full_analysis, id, is_owner,
metadata, name, sideboard, updated_at, visibility`.

This is dossier-grade: enough to serve `SPEC-arena-add-deck` step 5's primer
(`full_analysis`/`analysis_preview`) **and** feed the bracket + CRISPI + role
data straight into an ingest, all from one keyless GET.

---

## 2. Endpoint inventory (from the app bundle `core.js`)

| Endpoint | Method | Purpose | Auth |
|---|---|---|---|
| `/builder/api/public/deck/{deckId}` | GET | read a public deck + analysis (§1) | **none** |
| `/builder/api/draft-deck` | POST | create / draft a deck | session cookie |
| `/app/api/view/deckview` (`/app/api/view/{section}`) | GET | server-rendered HTML view fragments | — |
| `/builder/api/preferences` | POST | user prefs | session cookie |
| `/app/api/legal/accept` | POST | ToS accept | session cookie |
| `/deckview/share-image/{deckId}.png` | GET | share image | none |

Backend is Flask (werkzeug 404/405 pages, Cloudflare in front).

---

## 3. Authenticated create + analyze flow — VERIFIED END-TO-END (2026-08-11)

Reverse-engineered from the site bundles (`core.js` + the lazy `builder-*` /
`deckview.js` modules) and **run end-to-end live**: login → draft → Moxfield import
→ pro analysis → job poll → result.

### Auth
`POST https://deckcheck.co/login` — **form-encoded** `username` + `password` (creds
at `hello/deckcheck-hello`, keys `u`/`p`). Returns an **HttpOnly session cookie**
(hold it in a cookie jar for every later call). No CSRF token. Cloudflare fronts the
site but a normal browser User-Agent passes. Google/Apple SSO also exist. Verify:
`GET /api/credits-status` → `{access_level, available_credits, subscription_credits,
purchased_credits, pending_credits, daily_limit, daily_remaining, is_daily_system,
current_usage}`. Our account: `access_level 2`, **405 credits** (400 subscription + 5 daily).

All authenticated POSTs send `Content-Type: application/json` +
`X-Requested-With: XMLHttpRequest` (plus `Origin`/`Referer`).

### Analysis tiers (`intelligenceLevel`)
`standard` = "Standard AI" → **1 credit**; `pro` = "Pro AI" → **5 credits**.
Analysis runs as an **async job** (HTTP 202 + `job_id`; wait-toast at ~5 min).

### The verified flow

**1. Create an empty draft** — `POST /builder/api/draft-deck`
body `{"name": "...", "deck_format": "Commander", "folder_id": null}`
→ `201 {"deck": {"id": "<deckId>", ...}, "status": "success"}` (id at `deck.id`, e.g. `lm_fdOMy4HFo`).

**2. Import a Moxfield/Archidekt/ManaBox URL** — `POST /builder/api/import-deck-builder`
body `{"url": "<moxfield url>", "deckId": "<deckId>"}`
→ `200 {cards[], commanders[], companion, considering[], deck_format, name, sideboard[]}`.
Card shape: `{name, quantity, scryfall_id, set_code, collector_number, finish, is_foil}`.
**Gotcha:** this sets the deck's name/commander but returns the cards to the client
**without persisting them** (the draft still reads `cards: 0`). To analyze them you
either (a) persist via `save-draft`, or (b) pass them straight to `evaluate-deck`
(what we did).

**3. Run the analysis** — `POST /api/evaluate-deck`, body:
```json
{
  "commanderInput": ["Sythis, Harvest's Hand"],
  "companionInput": "",
  "deckList": "1 Sythis, Harvest's Hand\n1 Idyllic Tutor\n…  (\"N CardName\" per line, commander included)",
  "draftDeckId": "<deckId>",
  "deckStateHash": "",
  "intelligenceLevel": "pro",
  "userInput": "",
  "forceRescan": true
}
```
→ `202 {"job_id": "<uuid>"}`; credits decrement immediately (pro = −5).
*(Alt: `POST /api/reevaluate-deck` `{deck_id, intelligenceLevel, userInput}`
re-analyzes an already-**saved** deck — needs the cards persisted first.)*

**4. Poll the job** — `GET /api/job-status/{jobId}`
→ `{status:"in_progress", queue_position, enqueued_at}` … then on finish
`{status:"completed", analysis_intelligence_level, analyzed_main_deck_count,
attribute_ratings, bracket_level, full_analysis, performance_index, deck_id,
published_state_hash}`. **The completed job payload carries the whole analysis**
(prose + CRISPI + bracket) — no separate read required. Its `deck_id` is the
deckview/analysis id (hex), distinct from the builder `deckId`.

**5. (Optional) read back** — `GET /builder/api/public/deck/{deckId}` (§1), once the
deck is saved + unlisted/public.

### Persisting imported cards (VERIFIED) — makes a complete, readable deck
`POST /builder/api/save-draft` with `{id, name, deck_format, commander,
commander2, companion, cards, sideboard, considering, notes, deck_roles,
deck_metadata}`. `cards`/`sideboard` are **dicts keyed by card name**, each
`{"printings": [{quantity, finish, card_scryfall_id, set_code, collector_number}]}`
(built from the import card list). A minimal payload (empty
`deck_roles`/`deck_metadata`/`considering`, no `details`) is accepted — **verified:
92 cards persisted** (read-back `cards` 0 → 92; `→ {"message":"Draft saved
successfully"}`). `POST /builder/api/update-deck-visibility` `{deck_id, visibility}`
→ `unlisted`/`public`/`private` (**verified** → `{"status":"success"}`). This is
optional for the primer (the analysis is keyless-readable without it) but makes the
DeckCheck deck coherent (cards + analysis) for re-analysis/reuse.

### Tooling + repeatable pattern
- **`scripts/deckcheck-import.py`** (LOCAL TESTING TOOL, never bundled) chains the
  whole authenticated flow: `<moxfield-url> [--tier pro] [--visibility unlisted]
  [--dck-out PATH]` → login → draft → import → save-draft → visibility → analyze →
  poll → prints the `deckId` (and optionally emits the `.dck`). Spends credits.
- **`scripts/arena-add-deck.py <deck.dck> --slug <slug> --deckcheck <deckId>`**
  (bundle-safe, keyless) then builds the dossier and pulls the primer.
- Verified end-to-end on the Sythis deck: import → pro analysis → `.dck` +
  `docs/primers/sythis-harvests-hand-deckcheck.md` (bracket 4 + CRISPI + prose).

### Known gaps
- **MDFC card names:** Scryfall's `{"name":"A // B"}` lookup fails on full
  double-faced names (e.g. `Bala Ged Recovery // Bala Ged Sanctuary`) — 5 such
  cards landed in `deck-cards.json`'s `unresolved` on the Sythis run. `arena-add-deck`
  should retry the front face / use a `scryfall_id` when available.
- **No delete-deck endpoint** located yet — test drafts accumulate (kept `unlisted`).
- `parse_deckcheck_id` originally rejected ids with `_` (fixed → `[A-Za-z0-9_-]{6,}`).

### Live test result (2026-08-11)
Moxfield `…/decks/Nykf4L0i_Uu7R9TXOX3naQ` → imported as **"Green White Cushion
Castle 25"** (commander **Sythis, Harvest's Hand**), pro analysis, **5 credits
(405 → 400)**:
- `bracket_level: 4`, `performance_index: 5.75`, `analyzed_main_deck_count: 99`
- CRISPI `attribute_ratings`: `consistency 7 · interaction 4.25 · resilience 7.25 · speed 4.5`
- `full_analysis`: 21,432 chars (GW enchantress value; Sanctum Weaver + Gauntlets of
  Light → Luminarch Ascension infinite-angels line identified).
- Builder draft id `lm_fdOMy4HFo`; analysis/deckview id `752f7b7a979d…`.

### Complete authenticated endpoint inventory
- **read (keyless):** `GET /builder/api/public/deck/{id}`, `GET /deckview/share-image/{id}.png`
- **account:** `GET /api/credits-status`, `GET /api/profile-data`, `GET /api/notifications/*`
- **create/edit:** `POST /builder/api/draft-deck`, `/import-deck-builder`, `/save-draft`,
  `/save-analysis`, `/update-deck-visibility`, `/publish-deck`,
  `/deck/{id}/add-card-to-zone`, `/deck/{id}/collection-bulk`, `/card-details/bulk`,
  `/auto-tag`, `/update-printings`, `/preferences`, `/folders-and-decks`, `/recent-decks`
- **analyze:** `POST /api/evaluate-deck`, `POST /api/reevaluate-deck`,
  `GET /api/job-status/{jobId}`, `POST /api/roast-deck`, `POST /api/deck-analysis-feedback`
- **auth:** `POST /login`, `GET /auth/google/start`, `GET /auth/apple/start`
- Backend: Flask (werkzeug 404/405), Cloudflare front. Bundles: `core.js` (shared) +
  lazy `/app/deckcheck3/static/js/{builder-core,builder-features,builder-operations,deckview,…}.js`.

### Stance (unchanged)
Real login + credit spend, ToS-sensitive — used only for our own decks in testing,
**never bundled**; the package path stays the keyless read (§4a). Still pursuing a
proper create+analyze API with Anthony.

---

## 4. Getting analysis back on a NEW deck

**Retrieval is solved and free; generation needs (a) an authenticated session and
(b) credits for the AI pass.** Two distinct cases fall out of that:

### 4a. The distributed package — SOLVED, no upload automation needed
Recipients create + analyze their own deck in their own DeckCheck session (their
account, their credits), then hand the tool the deck's DeckCheck URL/id; the tool
fetches the structured analysis via the keyless endpoint above and renders it as
the primer — no copy/paste. **Implemented** in `scripts/arena-add-deck.py`
(primer **mode A** / `--deckcheck URL_OR_ID`; the HTML analysis is converted to a
Markdown primer with a commander/bracket/CRISPI header). Local **fable/max**
generation remains the fallback (mode B), unchanged. This needs nothing further
from Anthony.

### 4b. Our own bulk prep (our decks) — three options
1. **Ben's account via a captured session cookie** — log in once, POST to
   `/builder/api/draft-deck`, trigger analysis (spends *your* credits), read back
   via the free endpoint. Works today, but handles a personal session secret,
   burns credits per deck, and the `draft-deck` body + analyze-trigger call are
   not yet reverse-engineered. Fine for a handful, wrong for scale.
2. **A dedicated `forge-arena` service account** — clean separation, but a new
   account starts with ~no credits, so analysis is blocked unless Anthony grants a
   credit/free-tier arrangement. A **username/password credential now exists** at
   `hello/deckcheck-hello` (login creds, not an API key; outside the repo, never
   committed), so option 1's session-login path is cred-unblocked — credits and
   the no-scrape/ToS stance still apply.
3. **An Anthony-provided create+analyze API** — the symmetric ask to the read
   endpoint he just opened, and exactly what `SPEC-arena-add-deck.md` anticipated
   ("a real free-tier API arrangement, don't scrape"). Cleanest and ToS-blessed.

**Recommendation:** for the ~4 bundled decks + experiments, create them in the
DeckCheck UI by hand and fetch via mode A — no automation to build. Pursue option
3 with Anthony only if programmatic bulk analysis is ever wanted. Do not build
cookie/account automation (burns credits, handles a personal secret, cuts against
the no-scrape stance).

### Open questions for Anthony
1. Is `/builder/api/public/deck/{id}` the canonical public read URL, or is a
   top-level `/deck/{id}` alias coming?
2. Is there (or could there be) a **create + analyze** API for forge-arena —
   keyed or with a free-tier/credit arrangement — so ingest can request analysis
   for a newly uploaded deck without driving a browser session?
3. Credit cost/tier expectations for programmatic analysis of arbitrary user
   decks at ingest time.
