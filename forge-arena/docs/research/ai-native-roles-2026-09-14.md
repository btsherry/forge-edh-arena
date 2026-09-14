# AI-native team archetypes — five short definitions, and a five-lens review of `experimental/voicework2`

**Date:** 2026-09-14. **Author:** Claude Fable 5.1, for Ben. **Companion:** `ai-native-roles-review-2026-09-14.md`
holds the five analysts' reports verbatim.

## Source

Boris Cherny (creator of Claude Code, Anthropic) posted the five archetypes on X on 2026-06-28
(post id 2071379474277613732; the date is decoded from the id, the page itself is paywalled to
fetch tools). His framing, quoted from the post's opening: *"As engineering, product, design, DS,
etc. melt into a new kind of role, I was reflecting on what roles might look like in the future.
For example, when I look at the Claude Code team I see what I think is five archetypes."* He
closes with *"Maybe product roles of the future will look more like this, and less like the
domain-specific roles of today,"* and notes that many people span two roles, sometimes three.
None of the five is a job title: at Anthropic everyone on the team is a Member of Technical
Staff, and the PM, the designer and finance all code.

The one-line descriptions below are his, as relayed by three secondary write-ups (Aakash Gupta's
note of 2026-06-29, paddo.dev's "The Archetype Under the Title", BigGo Finance, which translates
Sweeper as "Cleaner"). Wording between them differs slightly; where they agree the phrase is kept.

- Post: https://x.com/bcherny/status/2071379474277613732
- Relays: https://substack.com/@aakashgupta/note/c-285068404 · https://paddo.dev/blog/the-archetype-under-the-title/ ·
  https://finance.biggo.com/news/c8e37d53-c061-4eef-b2a7-77d68021b3b8

## The five archetypes

1. **Prototyper** — comes up with brand-new ideas and churns out many of them, knowing most will
   not ship. The value is in the rate of ideas tried, not the survival rate.
2. **Builder** — quickly turns a prototype or idea into production-grade product and
   infrastructure: the thing has to hold together for other people.
3. **Sweeper** — cleans up the interface, simplifies the code and the system, unships what is not
   pulling its weight, and optimises performance. Subtraction as a first-class job.
4. **Grower** — takes a product that has been built and iterates on it toward product-market fit:
   watches how it is actually used and steers.
5. **Maintainer** — owns a mature system and keeps it secure, reliable, fast and efficient as it
   scales; the long tail after the novelty.

## How the archetypes are used here

Each archetype becomes a review lens on the same body of work. Five analysts (Claude Fable 5.1,
one per archetype, read-only) each explore everything on the branch and report what their
archetype would notice: concerns, bugs and corrections, feature suggestions, observability and
efficiency changes, and questions for Ben. Nothing is fixed; the reports are combined verbatim in
the companion document, and the discussion with Ben decides what happens next.

| Lens | What it is asked to weigh on this branch |
|---|---|
| Prototyper | Is the idea space right? Which cheap experiments would most improve a "lifelike table" (Ben's uncanny-valley note after game 48), and which directions are dead ends? |
| Builder | Does what shipped hold together in production: failure paths, restarts, packaging (~5,000 audio files), configuration, the seam between the Java observer and the Python runners, and whether the tests exercise the live behaviour? |
| Sweeper | Where is the complexity not earning its keep: the 2,600-line runner, knobs nobody turns, raw takes committed beside baked ones, duplicated logic, ids and wordings that could be unshipped? |
| Grower | Does the live behaviour match what Ben asked for across games 38–48 (his notes are in the commit messages and BUG-LOG), what do the archived game logs measure, and what should be iterated next? |
| Maintainer | Reliability, observability and efficiency over time: logging and records, the governor, the observer poll seam (BL-50), the long-lived transport, upstream Forge drift, secrets handling, test brittleness. |

## Scope handed to the analysts

- Branch `experimental/voicework2`, 52 commits since the `arena` base `3e037fdc9a9` (2026-09-10 → 09-14),
  head `e517f2eb300`. 5,102 files changed; 5,044 are audio takes.
- Code: `runner/voice_runner.py`, `runner/chains.py`, `runner/voice/{table_lines,card_lines,build_stock}.py`,
  `runner/voice/stock/voices/**/manifest.json` + `chains.json`, `address.json`, `combos.json`, `assign.json`;
  `runner/seatd/{runner,rules,brain}.py` + `seat-brief.md`; `runner/advisor_runner.py`;
  Java `ObserverSnapshot`, `GuiPilotMatch`, `VoiceFocus`, `CAdvisor`, `VAdvisor`; scripts `arena-play.sh`,
  `arena-autostop.sh`, `arena-status.py`, `arena-config.py`, `arena-hygiene.py`, `arena-add-deck.py`;
  `packaging/build-light-package.sh`.
- Tests: `runner/tests/test_{barks_runtime,table_lines,card_lines,table_budget,bark_libraries,voice_runner,
  advisor_barks,advisor_quips,cycle_replay,cycle_history,hardening,three_steps}.py` (453 OK at head).
- Docs: `docs/BUG-LOG.md` (BL-48…50, W-18, W-19), `packaging/PATCH-NOTES.md` (v4.2 unreleased),
  `packaging/README.md` ("The table's voices"), `docs/INTERACTIVE-ARENA.md` note 103.
- Live evidence: archived game logs under `runner/logs/archive/` — 2026-09-10 (games 38–45),
  `20260911-105547-stop` (46), `20260911-204333-stop` (47), `20260914-141513-stop` (48); each holds
  `voice-0.jsonl`, `game.jsonl`, seat and advisor logs, `autostop.out`.
- Rules of engagement: analyse and report only. No edits, no git writes, no Maven or jar builds,
  no game launches, no network calls, no secrets in output.
