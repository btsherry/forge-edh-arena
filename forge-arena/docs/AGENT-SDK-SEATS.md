# seatd — autonomous per-seat brains (Track 5 build plan)

**Status: build-ready blueprint.** Synthesized 2026-08-07 from a 9-agent research
workflow: 3 fact-finders (SDK/API surface verified against docs; the mailbox
contract extracted from the actual Java source; token economics modeled from this
project's measured session data), 3 independent designs (ship-today "seatd",
release-grade "Anvil", capability-first "Tablemind"), and a 3-lens adversarial
judge panel (pragmatist / maintainer / economist). **seatd won 2 of 3 lenses
(49-49-47/60)**; this plan is seatd plus the panel's consensus grafts from the
other two. Engine side needs **zero changes** — the mailbox contract
(INTERACTIVE-ARENA.md) is the frozen seam.

## The verdict in one paragraph

One synchronous Python loop per seat (~700 LOC total across 4 modules). **Raw
`anthropic` Messages API, NOT claude-agent-sdk**: zero tools are needed (the
runner does the file I/O deterministically), per-call statelessness is a
*feature* (anti-confabulation: re-derive from request state every time), and
caching must be explicit and auditable. Dossier+primer ride as a **byte-stable
1-hour-TTL cached system prefix**; one stable union JSON schema (structured
outputs) guarantees parseable responses; a local `rules.py` validates per-type
semantics and falls back to an always-legal safe default. The engine's
timeout→stock fallback is the only supervisor needed; `while true` restart loops
are the process manager. **The orchestrator (main session) exits the routing
path entirely.**

## Corrected facts (things we believed wrong until measured)

| Belief | Measured truth |
|---|---|
| Dossier ≈ 35–40k tokens | **34–37 KB ≈ 8.5–9.5k tokens** (+brief+rules card → prefix ~10–12k). All cost fears were ~3× inflated. Verify in-build with `client.messages.count_tokens`. |
| "Persistent subagent = cheap resumes" | Sleep/wake re-pays the prefix when human-paced gaps blow the 5-min cache TTL. Resident + 1h TTL pays the 2× write **once per game**. |
| Cost of a game (3 AI seats, ~66 decisions) | A(status quo) $5.95–14.90 → **B(resident) $1.05–5.30** by tier. Sonnet-5 seats ≈ **$2.10/game** (intro pricing thru 2026-08-31; ~$3.20 after — read rates from config, not code). |
| Always-on is the ideal | Rejected: 10–12× B's cost, zero effective gain (anti-confabulation forces re-derivation anyway). Pre-plan-on-deck (C, +28%) deferred behind a named stub hook; **in-band turn_plan ships day one at ~zero cost**. |

Model policy: **Sonnet 5, effort low** is the default seat tier (econ pick; Haiku
rejected as default — the same pressure that made summarized text confabulate
makes weaker models confabulate from full text). `--model` per seat allows an
Opus "boss" seat (~$5/game mixed table). Quality lives in tier+effort, not
architecture — all architectures see identical state.

## Architecture (seatd + grafts)

```
forge-arena/runner/
  seat_runner.py       # CLI: --seat N --deck NAME [--model claude-sonnet-5] [--base ...]
  run_table.sh         # seats 1-3, while-true restart loops, per-seat logs
  replay.py            # fixtures -> brain -> rules end-to-end, no engine
  requirements.txt     # anthropic
  seatd/
    protocol.py        # inbox watch (ignore *.tmp), seq+answered-set, atomic write,
                       #   startup hygiene, consumption check, orphan-req mtime rule
    rules.py           # UNION_SCHEMA + per-type {validate, safe_default} table
    brain.py           # byte-stable system blocks, prompt builder, streaming call,
                       #   deadline abort, cache-hit assertion, react_autopass fastpath
    runner.py          # loop, turn-plan cache, memoized REACT signatures,
                       #   costs JSONL, heartbeat file
    edh-rules-card.md
  tests/{fixtures/, test_protocol.py, test_rules.py}
  logs/                # GITIGNORED — contains that seat's private hand
```

**Data flow per decision:** poll inbox 0.5s → parse req (atomic write ⇒ parse
failure is transient) → seq-regression / answered-set check (engine restart ⇒
wipe memory) → **fastpaths first** (below) → else build user msg = brief header +
req JSON verbatim + per-type answer contract + observer summary + advisory
turn_plan ("state wins") → `messages.stream` with system=[rules+brief,
dossier+primer w/ `cache_control {ephemeral, ttl:"1h"}`], union schema, effort
low, adaptive thinking summarized (streams to per-seat log = the live-reasoning
feel) → `rules.validate()`; on any failure `rules.safe_default()` — **always
answer, never silence** → re-check req still exists → atomic write → confirm
consumption (~1s); GC own stale resp.

**Zero-API fastpaths (the Giver-of-Runes cure, from Anvil+Tablemind):**
1. `react_autopass`: config name-list per seat (e.g. `["Giver of Runes"]`) — a
   REACT whose only non-pass options are all on the list → instant
   `{"chosenId":0}`, logged as `fastpath`.
2. Memoized same-turn REACT: signature = (sorted stack names, sorted option
   hosts); identical signature already passed this turn → repeat pass, no call.
   Cleared on turn change / seq regression.

**Deadline discipline (Anvil):** deadline = req mtime + 0.8×`ARENA_MAILBOX_TIMEOUT`;
client timeout sized so `(max_retries+1)×per-request-timeout < deadline`; abort
the stream at deadline and write safe_default. Launch with
**`ARENA_MAILBOX_TIMEOUT=90–120`** so any residual silence degrades to stock in
~90s, not 300s.

**Safe defaults are per-type LEGAL (maintainer graft):** CAST/REACT→`{"chosenId":0}`;
MULLIGAN→`{"keep":true}`; DECLARE_*→`[]`; optional CHOOSE_*→`{"chosenId":0}`;
**mandatory** CHOOSE_ENTITY/CARD→first offered id; CHOOSE_ENTITIES→first `min`
ids; CHOOSE_MODE→first `min` indices respecting `allowRepeat`. Every default
must itself pass `validate()` (tested).

**Fairness, mechanical:** protocol.py can only construct paths from its own seat
id; sole cross-seat read is `observer-state.json`; unit test asserts no glob
above the seat dir; request state always overrides the debounced snapshot.
Per-seat logs contain the seat's private hand → gitignored now; any future
shared viewer must hide live seat logs from the human (release blocker noted).

**Observability:** per-decision `costs.jsonl` (tokens in/out, cache read/write,
$ from **config-supplied rates** — intro pricing dies 2026-08-31), heartbeat
file + one-line status renderer, `tail -f logs/seat-*.log` for live reasoning.

## Contract hard parts (encode as data + fixtures, not prompt prose)

From the source-extracted contract — the traps that silently burn windows:
- Engine deletes BOTH files once the resp **parses as JSON**, *before* shape
  validation: a malformed-but-parseable answer irrevocably loses the window to
  stock. Self-validate before writing. Unknown/non-int id → stock (NOT a pass);
  only `chosenId:0` is an explicit pass, and 0 is only legal when offered.
- `CHOOSE_MODE` ids are **0-based indices** (0 is a real mode); everywhere else
  0 = pass. MULLIGAN answers `{"keep":bool}` (its option ids are decorative;
  state.hand is a plain name list there). Ids must be bare JSON ints ('1'/1.0 → stock).
- Combat: whole-assignment atomicity (one bad pair discards ALL to stock);
  defenders always explicit (3 opponents = ambiguity poisons the declaration).
- Engine restart: seq resets to 1; stale outbox resp-1 is a landmine (startup
  sweep); killed engine leaves orphan reqs (answer only if mtime < timeout);
  timeout deletes req mid-think (re-check existence before writing).
- CAST_SPELL option lists include uncastable lines (canPlay quirk) — verify
  affordability from `untappedManaSources` before picking (field-observed).
- Mindslaver spawns a second seq counter on the same seat dir — rare; degrade to
  stock, don't engineer for it.

## In-build empirical checkpoints (judge-mandated, non-negotiable)

1. **Structured-output param shape**: smoke-test the current
   `output_config={"format":{"type":"json_schema",...}}` vs older
   `response_format` on `messages.create/stream` before H3.
2. **Schema-vs-cache**: two consecutive calls WITH the schema attached must show
   `usage.cache_read_input_tokens > 0` on call 2. If schemas invalidate the
   prefix, keep the single union schema (never per-decision schemas).
3. **count_tokens** on all 4 assembled prefixes (settles ~10–12k; every cost
   claim hangs on it; also clears Sonnet's 1024-token cache minimum).
4. `max_tokens ≥ 4000` at effort low (thinking counts against the cap);
   `stop_reason=="max_tokens"` or `"refusal"` → safe_default, never parsed as answer.
5. Cache-miss tripwire: `calls>1 && cache_read==0` → WARN in heartbeat/status,
   not just a log line.

## 8-hour build order (each hour ends in a verifiable checkpoint)

- **H1 — Transport + echo-runner.** protocol.py; copy one REAL req per
  decisionType from the live mailbox/runs into fixtures (+malformed variants).
  ✔ `pytest test_protocol.py`; **echo-runner** (answers every window with the
  legal pass shape, zero API) runs against a live game — transport proven first.
- **H2 — Contract as code.** rules.py: union schema + validate/safe_default for
  all 9 types and every trap above. ✔ table-driven tests: good accepted, each
  trap rejected, `safe_default(req)` itself validates.
- **H3 — Prompt + cache proof.** brain.py byte-stable blocks (dossier verbatim).
  ✔ count_tokens printed; call-2 cache_read > 0 **with schema attached**.
- **H4 — Offline end-to-end.** replay.py: all 9 fixture types on Sonnet-5 low.
  ✔ 9/9 legal; latency logged (expect 5–30s); thinking streams to logs/.
- **H5 — Live attach.** runner.py loop + plan cache + fastpaths + deadline.
  ✔ **runner answers a real pending req in the live game's mailbox; resp
  vanishes <1s; game advances in the GUI.**
- **H6 — Full table.** run_table.sh; fresh 4-player GUI game, human seat 0.
  ✔ 3 seats answer mulligans + first mains; zero timeout-fallbacks on answered
  windows; `tail -f` shows live reasoning.
- **H7 — Soak.** Play to turn 8+. ✔ >90% of windows answered by runners; no
  crash loops; watch REACT pacing, unpayable picks, invalid-output rate (>2% ⇒
  revisit union schema).
- **H8 — Hardening + docs.** Kill/restart engine drill (stale req, seq reset,
  outbox sweep); costs.jsonl wired; README; gitignore logs/.
  ✔ restart drill clean; cold-start launch from README alone.

Schedule risk valve: if any hour overruns, the engine's stock fallback means a
partially-built table still plays — ship what's green, soak the rest next session.

## Deferred (each degrades safely)

Observer-triggered pre-plan (named stub `on_deck_preplan()`; +28% cost for
perceived latency only; needs elimination-aware turn order the snapshot lacks) ·
Haiku triage tier · supervisor daemon beyond while-true · retry-on-invalid
(deadline risk; safe_default is always legal) · Brain ABC extraction +
RandomLegalBrain (the named post-ship refactor seam for the GPL "bring your own
brain" release) · Mindslaver dual-seq · cache pre-warm (first real decision is a
MULLIGAN with the full budget — it pays the one 2× write anyway).

## Relationship to the rest of the roadmap

This replaces the sleep/wake subagent brains (INTERACTIVE-ARENA.md "Next
architecture") and closes Track 5's core. Engine-side asks that remain (tracked
in INTERACTIVE-ARENA field notes): suppress no-op protection REACTs (§12), richer
REACT stack context (targets, not just names), optional-trigger windows
(confirmAction still stock). The runner deliberately does NOT duplicate the
engine-side REACT gate beyond its config fastpath — one owner per filter.
