Review: forge-arena/docs/INTERACTIVE-ARENA.md

  Bottom line: This is a high-quality engineering log wearing the header of a reference doc. The
  protocol contract is accurate (I verified it against MailboxProtocol.java / MailboxController.java),
  and the 49 field notes are unusually candid and valuable. But the doc has grown by accretion —
  corrections are layered on top of stale statements instead of replacing them — so a newcomer following
  the intro's "read these first" pointer lands on a section that describes a world that no longer
  exists. Several early claims are now contradicted by later notes or by the code.

  ---

  1. Stale or contradicted claims (verified against code)

  Where: INTERACTIVE-ARENA.md:44-47
  Doc says: 16 files outside forge-arena: 8 patches (~150 lines), 7 new, 1 layout
  Reality: INVENTORY.md:17-18 (which this doc calls authoritative) says 17 files: 9 modified (~215
  lines). Missing the ComputerUtilMana.java Gemstone Caverns patch from 08-19 (commit ce4b019e7c0).
  ────────────────────────────────────────
  Where: :228-229
  Doc says: Launcher runs react-autopass as a step
  Reality: arena-play.sh:86-88 says it was retired 2026-08-17. Note 42 in this same doc agrees. The
  code-block comment was never updated.
  ────────────────────────────────────────
  Where: :749-753 (note 24)
  Doc says: react-autopass.py "promoted to standard launch"
  Reality: Superseded by note 42 but — unlike notes 12 and 23 — carries no "superseded" marker.
  ────────────────────────────────────────
  Where: :88-89
  Doc says: Still stock: "proactively flashing into an empty stack, and responding to interaction during
   
  the agent's own turn"
  Reality: MailboxController.java:177-186: the reactive gate checks only ap != me — no turn restriction,

  so own-turn responses are mailboxed. tactical (:195-202) covers empty-stack combat/end-step on any
  turn. The only remaining empty-stack gap is main/upkeep/draw on opponents' turns. Half of this
  sentence is wrong.
  ────────────────────────────────────────
  Where: :311-316 (Track 3)
  Doc says: Twice: "Remaining: normal spell targeting (chooseTargetsFor)"
  Reality: Fixed in v3 per notes 14/14b/14c; :96-99 says targeting is seat-owned. Should be ✅.
  ────────────────────────────────────────
  Where: :338-393 "Next architecture"
  Doc says: "Today each brain is a subagent of one interactive session… sleep/wake…"
  Reality: Track 5 (:328) says SHIPPED. This whole section is a historical design written in present
  tense, and it duplicates AGENT-SDK-SEATS.md, which :330 already designates as the retained historical
   plan.
  ────────────────────────────────────────
  Where: :17-19 intro
  Doc says: "read Operational learnings and Next architecture first if you are picking this up"
  Reality: Points a newcomer straight at the stale section above.
  ────────────────────────────────────────
  Where: :261
  Doc says: "Known limitations (current, 2026-08-17)"
  Reality: Status line is 08-19; notes run to 08-19. A header that declares its own currency should be
  current.

  2. Protocol-contract gaps (a brain implementer would miss these)

  - confirmMode == "PLAY_FROM_EFFECT" is undocumented in the contract. :146 only lists TRIGGER.
    MailboxController.java:1925 emits PLAY_FROM_EFFECT with state.spell/state.free — that's only
    mentioned in note 49 at line 947. Add it to the CONFIRM bullet at :209-211 and the state comment at
    :146.
  - Two timeouts, no relationship stated. :121 says 300s (engine property, confirmed
    MailboxProtocol.java:51). :233 says 90s (arena-play.sh:26, via ARENA_MAILBOX_TIMEOUT). Both true;
    one sentence saying "the launcher overrides the 300s engine default to 90s" would resolve the
    apparent conflict.
  - Everything else checks out: arena.mailbox.dir default, pollMillis 75, and all 13 decisionType
    strings at :128 exactly match what the controller emits.

  3. Path references

  - :24 — "packaging/README.md + PATCH-NOTES.md": the latter lives at packaging/PATCH-NOTES.md; bare
    reference reads as forge-arena root, where it doesn't exist.
  - :237 uses runner/status.py; :503 uses arena-status.py. Both exist (runner/status.py,
    scripts/arena-status.py) but the doc never says whether they're the same tool or different ones.
  - :240 — run_table.sh is in runner/, not scripts/ like its neighbors on that line; no path given.

  4. Formatting

  - Note 22 (:723) is written 22 — COMBAT… instead of 22. **…**, which breaks the ordered list: 1–21 is
    one list, 22 renders as a paragraph, 23–49 becomes a second list.
  - Note numbering jumps 17 → 21. Note 17 explains it ("was: notes 17-20"), so it's deliberate, but a
    one-line tombstone for 18–20 would be kinder than making readers hunt.
  - Notes 14/14b/14c, 15/15b/15b-correction, 21/21b: nested corrections inside single list items run
    30–60 lines each. These are exactly the content that argues for the split in §6.

  5. Redundancy

  The same features are described three times — in the Tracks (:282-336), "The shipped stack"
  (:394-429), and the field notes. ELO: :408-413 + note 33. Advisor: :414-416 + notes 23 + 46. Cycle
  replay: :423-426 + note 39. MCP skip: :423 + note 26. When one of these changes (as cadence did in
  note 46), the others drift.

  6. What's good — keep it
  
  - The protocol section (:114-223) is tight, accurate, and complete enough to implement against (modulo
    §2).
  - Per-card serialization spec (:152-184) is precise about what's present/omitted and why.
  - The field notes are the best part. Retractions are kept and labeled ("proven WRONG then re-fixed",
    "RETRACTED-AND-REWRITTEN"), root causes name the exact method on the exact call path, and the
    lessons generalize ("a hook that fires on the human path is NOT automatically on the AI cast path";
    "treat 'feature has never fired in telemetry' as a red flag"). Don't lose any of this.

  7. Suggested restructure
  
  Split along the seam the doc already half-acknowledges (note 43 set the docs/archive/ precedent):

  1. INTERACTIVE-ARENA.md → stable reference, ~250 lines. Why / Architecture (table as-is) / Hybrid
     control model rewritten to describe current behavior only (the four gates: ownMainEmpty, reactive,
     tactical, selfTrigger — straight from MailboxController.java:162-230, which is already clearer than
     the prose) / Fairness / Protocol / Running it / Known limitations. Point to INVENTORY §2 for the
     seat-vs-stock matrix instead of restating it.
  2. docs/FIELD-NOTES.md — the 49 notes verbatim, plus the Track history.
  3. Delete "Next architecture" — AGENT-SDK-SEATS.md already holds it.

  Even without the split, the eight items in §1 are one sitting of edits and would remove every
  statement a reader could currently be misled by.

