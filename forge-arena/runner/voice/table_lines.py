#!/usr/bin/env python3
"""table_lines.py — the "table" sub-library of every seat voice (round 31, 2026-09-10).

Five Game Knights tapes: the talk at a real table is mostly PROCEDURAL — "land,
go", "pass", "I'll take five, going to sixteen", "no blocks", "in response",
"sure" — plus reactions and a little politics addressed by NAME. Game 45 had
none of that. This script holds the wordings and writes, for each voice,
    voice/stock/voices/<lib>/table/manifest.json
(schema arena.voice-stock/1, rendered/baked by build_stock.py with
--library <lib>/table). Three kinds of line:

  procedural  self-narration and acks the runner fires from board events
  number      "I'm at twelve." (1-40, 45, 50, 60, 80, 100) and "Six cards." (0-10)
              as whole sentences — a stitched number never sounds like a person
  address     four families with the target's name baked in: hit-<who>,
              threat-<who>, leave-me-<who>, deal-<who>, <who> = a commander
              (decks/<slug>/dossier/deck-cards.json) or, as the fallback for a
              deck without a rendered name, its colour identity (Ben's chart:
              mono, the ten guilds, the ten shards/wedges, Glint/Dune/Ink/Witch/
              Yore, five-colour, colourless) — voices/address.json

Dev-only (excluded from the package like build_stock.py). Rules as everywhere:
one eleven_v3 delivery tag leads each wording, about ten words at most, no
hidden information, the register of the voice (Harry fiery, Bill dry professor,
Lily warm and theatrical).

    python3 runner/voice/table_lines.py            # print a summary
    python3 runner/voice/table_lines.py --write    # (re)write the three manifests + address.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
VOICES = HERE / "stock" / "voices"
DECKS = HERE.parent.parent / "decks"
LIBS = ("harry", "bill", "lily")

# ---- number words ---------------------------------------------------------------
ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
        "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
TENS = {20: "twenty", 30: "thirty", 40: "forty", 50: "fifty", 60: "sixty", 70: "seventy", 80: "eighty", 90: "ninety"}


def words(n: int) -> str:
    if n < 20:
        return ONES[n]
    if n == 100:
        return "a hundred"
    t, o = (n // 10) * 10, n % 10
    return TENS[t] + ("" if o == 0 else "-" + ONES[o])


LIFE_NUMBERS = list(range(1, 41)) + [45, 50, 60, 80, 100]
HAND_NUMBERS = list(range(0, 11))

# ---- colour identities (Ben's chart, 2026-09-10) ---------------------------------
# key = the identity's letters in WUBRG order; say = as a subject, voc = when addressed
COLORS = {
    "W": ("mono-white", "mono-white", "mono-white"), "U": ("mono-blue", "mono-blue", "mono-blue"),
    "B": ("mono-black", "mono-black", "mono-black"), "R": ("mono-red", "mono-red", "mono-red"),
    "G": ("mono-green", "mono-green", "mono-green"), "C": ("colorless", "the artifact deck", "artifacts"),
    "WU": ("azorius", "Azorius", "Azorius"), "WR": ("boros", "Boros", "Boros"), "UB": ("dimir", "Dimir", "Dimir"),
    "BG": ("golgari", "Golgari", "Golgari"), "RG": ("gruul", "Gruul", "Gruul"), "UR": ("izzet", "Izzet", "Izzet"),
    "WB": ("orzhov", "Orzhov", "Orzhov"), "BR": ("rakdos", "Rakdos", "Rakdos"), "WG": ("selesnya", "Selesnya", "Selesnya"),
    "UG": ("simic", "Simic", "Simic"),
    "WBG": ("abzan", "Abzan", "Abzan"), "WUG": ("bant", "Bant", "Bant"), "WUB": ("esper", "Esper", "Esper"),
    "UBR": ("grixis", "Grixis", "Grixis"), "WUR": ("jeskai", "Jeskai", "Jeskai"), "BRG": ("jund", "Jund", "Jund"),
    "WBR": ("mardu", "Mardu", "Mardu"), "WRG": ("naya", "Naya", "Naya"), "UBG": ("sultai", "Sultai", "Sultai"),
    "URG": ("temur", "Temur", "Temur"),
    "UBRG": ("glint", "the Glint deck", "Glint"), "WBRG": ("dune", "the Dune deck", "Dune"), "WURG": ("ink", "the Ink deck", "Ink"),
    "WUBG": ("witch", "the Witch deck", "Witch"), "WUBR": ("yore", "the Yore deck", "Yore"),
    "WUBRG": ("five-color", "five-colour", "five-colour"),
}
ORDER = "WUBRG"


def color_key(identity) -> str:
    letters = set(identity if isinstance(identity, str) else "".join(identity or []))
    letters &= set(ORDER)
    return "".join(c for c in ORDER if c in letters) or "C"


def commanders() -> dict[str, dict]:
    """deck slug -> {"name", "say", "slug", "colors"} from every dossier's commander card."""
    out: dict[str, dict] = {}
    for d in sorted(DECKS.iterdir()) if DECKS.exists() else []:
        f = d / "dossier" / "deck-cards.json"
        if not f.exists():
            continue
        try:
            cards = json.loads(f.read_text()).get("cards") or []
        except (OSError, ValueError):
            continue
        cmd = next((c for c in cards if isinstance(c, dict) and c.get("zone") == "commander"), None)
        if not cmd:
            continue
        name = str(cmd["name"])
        first = name.split(" // ")[0].split(",")[0].strip()          # "Sheoldred // The True Scriptures" -> "Sheoldred"
        slug = "".join(ch if ch.isalnum() else "-" for ch in first.lower()).strip("-")
        slug = "-".join(p for p in slug.split("-") if p)
        out[d.name] = {"name": name, "say": first, "slug": slug, "colors": color_key(cmd.get("color_identity") or "C")}
    return out


# ---- the wordings -----------------------------------------------------------------
# procedural: id -> (when, {lib: [wordings]})
PROCEDURAL: dict[str, tuple[str, dict[str, list[str]]]] = {
    "land-go": ("its own turn was a land and nothing else", {
        "harry": ["[scoffs] Land. Go.", "[frustrated] Land, pass. Don't laugh.", "[exhales] Just a land. Next.", "[angry] Land. Pass. Not a word."],
        "bill": ["[calmly] A land. Pass.", "[dryly] Land, go. Riveting.", "[calmly] Nothing further. Pass.", "[sighs] A land, and that is all."],
        "lily": ["[gently] A land, and I'll pass, dears.", "[softly] Just a land. Go on.", "[chuckles] Land, pass. Nothing to see.", "[warmly] Only a land today, loves."]}),
    "pass": ("ends its own turn after doing something", {
        "harry": ["[excited] Done! Your go!", "[shouting] Pass! Beat that!", "[smug] That's my turn. Go.", "[laughs] Over to you. Good luck."],
        "bill": ["[calmly] That concludes my turn.", "[calmly] Pass.", "[dryly] I'm done. Proceed.", "[calmly] Your turn. Do try."],
        "lily": ["[warmly] And that's me. Go on, dear.", "[gently] Pass, love.", "[softly] Over to you.", "[warmly] I'll pass. Be kind."]}),
    "mana-up": ("ends its own turn with mana untapped and cards in hand", {
        "harry": ["[smug] Passing. Mana up. Try me.", "[laughs] Pass. I've got mana. Guess why.", "[mischievously] Pass. Don't mind the open mana."],
        "bill": ["[calmly] Pass, with mana available.", "[dryly] I'll pass. Mana open. Draw your conclusions.", "[calmly] Passing. Note the untapped lands."],
        "lily": ["[gently] I'll pass, with mana up, dears.", "[mischievously] Passing. Mana open. Hmm.", "[softly] Pass, love. I'm keeping this mana."]}),
    "tapped-out": ("ends its own turn tapped out with cards in hand", {
        "harry": ["[exhales] Tapped out. Go nuts.", "[frustrated] Tapped out. Don't get ideas.", "[laughs] All in. Nothing left. Pass."],
        "bill": ["[calmly] Tapped out. Regrettably.", "[dryly] No mana. Proceed freely.", "[sighs] Fully committed. Pass."],
        "lily": ["[softly] I'm tapped out, dears.", "[gently] All tapped. Be gentle.", "[chuckles] Not a drop left. Pass."]}),
    "untap-draw": ("its own turn begins (an alternative to my-turn)", {
        "harry": ["[excited] Untap, draw, go time!", "[shouting] Untap! Draw! Let's go!", "[smug] Untap. Draw. Here we go."],
        "bill": ["[calmly] Untap. Upkeep. Draw.", "[calmly] Untap, draw. Proceeding.", "[dryly] Untap, upkeep, draw. The ritual."],
        "lily": ["[gently] Untap, upkeep, draw, dears.", "[softly] Untap, draw. Let's see.", "[warmly] Untap and draw. Lovely."]}),
    "come-on-land": ("its own turn begins short on lands", {
        "harry": ["[angry] Come on, land!", "[groans] Land! Just one land!", "[frustrated] Draw a land. Please. Anything."],
        "bill": ["[sighs] A land would be appreciated.", "[calmly] Statistically, a land is due.", "[dryly] Mana screw. Delightful."],
        "lily": ["[softly] Come on, a land, please.", "[sighs] Just one little land, dears.", "[gently] Any day now, land."]}),
    "thinking": ("its own decision has been pending a while", {
        "harry": ["[exhales] Okay. Options.", "[mischievously] Let me think. Yeah.", "[groans] Hang on. Thinking."],
        "bill": ["[calmly] Let me think.", "[calmly] Considering.", "[whispers] One moment. Calculating."],
        "lily": ["[softly] Hmm. Let me see.", "[gently] Thinking, dears.", "[softly] One moment, loves."]}),
    "cast-creature": ("casts a creature (not its commander, not a game changer)", {
        "harry": ["[excited] Creature! Come on out!", "[shouting] Here's a body!", "[smug] Another one for the army."],
        "bill": ["[calmly] A creature. Nothing special.", "[dryly] Casting this. Try to contain yourselves.", "[calmly] A body for the board."],
        "lily": ["[warmly] A little friend for me.", "[gently] Casting a creature, dears.", "[softly] Another for the board."]}),
    "cast-artifact": ("casts an artifact", {
        "harry": ["[scoffs] Another rock. Sue me.", "[excited] Artifact. Ramp, ramp, ramp!", "[smug] More toys."],
        "bill": ["[calmly] An artifact. Efficiency.", "[dryly] Another trinket.", "[calmly] Mana. One needs mana."],
        "lily": ["[gently] A little trinket.", "[warmly] An artifact, dears.", "[chuckles] Just a rock. Nothing scary."]}),
    "cast-enchantment": ("casts an enchantment", {
        "harry": ["[excited] Enchantment! Read it later!", "[smug] This stays. Get used to it.", "[laughs] Sticky. Good luck removing it."],
        "bill": ["[calmly] An enchantment. It stays.", "[dryly] Permanent value. Observe.", "[calmly] This will matter later."],
        "lily": ["[warmly] An enchantment, love. It'll linger.", "[gently] Something that stays.", "[mischievously] This one's for later."]}),
    "cast-instant": ("casts an instant on its own turn", {
        "harry": ["[shouting] Instant! Boom!", "[excited] Quick one!", "[laughs] Zap. Instant."],
        "bill": ["[calmly] An instant. At instant speed.", "[dryly] Efficiently, then.", "[calmly] A small instant."],
        "lily": ["[softly] Just a little instant.", "[gently] A quick one.", "[warmly] Something quick, dears."]}),
    "cast-sorcery": ("casts a sorcery", {
        "harry": ["[excited] Sorcery! Big effect!", "[shouting] Watch this one!", "[smug] Main phase. My phase."],
        "bill": ["[calmly] A sorcery. Let it resolve.", "[dryly] Main phase business.", "[calmly] Sorcery speed. Patience."],
        "lily": ["[gently] A sorcery, dears.", "[warmly] Something dramatic.", "[softly] Casting this, love."]}),
    "cast-planeswalker": ("casts a planeswalker", {
        "harry": ["[shouting] Walker! Come on down!", "[excited] Planeswalker! Protect the walker!", "[smug] A walker. Deal with it."],
        "bill": ["[calmly] A planeswalker. Do be gentle.", "[dryly] A walker. It will not last.", "[calmly] Loyalty. We shall see."],
        "lily": ["[warmly] A planeswalker, love. Be nice to her.", "[gently] A walker for me.", "[softly] Someone new joins us."]}),
    "cast-big": ("casts a six-plus mana spell that is not a game changer or its commander", {
        "harry": ["[shouting] Big one! Here it comes!", "[excited] Six mana! Worth it!", "[laughs] All in on this!"],
        "bill": ["[calmly] A large investment. Observe.", "[dryly] Expensive. Justified.", "[calmly] This one costs. It also wins."],
        "lily": ["[warmly] Something big, dears.", "[gasps] Here she comes.", "[gently] I've saved up for this."]}),
    "in-response": ("casts an instant on someone else's turn", {
        "harry": ["[shouting] Hold on! In response!", "[angry] Not so fast!", "[excited] Wait wait wait! Response!", "[laughs] Before that resolves..."],
        "bill": ["[calmly] In response.", "[dryly] Before that resolves, a word.", "[calmly] Hold on. I have something.", "[whispers] Not yet. In response."],
        "lily": ["[gently] Oh, one moment, dear. In response.", "[softly] Before that resolves, love.", "[mischievously] Hold that thought.", "[warmly] Sorry, dears. In response."]}),
    "poke": ("declares a small attack", {
        "harry": ["[laughs] Just a poke. Take it.", "[smug] Little swing. Don't cry.", "[mischievously] Chip damage. Adds up."],
        "bill": ["[calmly] A modest attack.", "[dryly] Chip damage. It accumulates.", "[calmly] A small swing. Nothing personal."],
        "lily": ["[gently] Just a little poke, dear.", "[softly] A small swing. Sorry, love.", "[chuckles] Chip, chip."]}),
    "attack-you": ("declares a medium attack at one player", {
        "harry": ["[shouting] Swinging at you!", "[excited] You! Attack!", "[laughs] Coming for you!"],
        "bill": ["[calmly] Attacking you.", "[dryly] You, I'm afraid.", "[calmly] You take this one."],
        "lily": ["[gently] I'm coming at you, love.", "[softly] You, dear. Sorry.", "[warmly] This one's for you."]}),
    "no-blocks": ("it is attacked with nothing untapped to block", {
        "harry": ["[angry] No blocks. Take it.", "[groans] Nothing to block with.", "[frustrated] Fine. No blocks."],
        "bill": ["[calmly] No blocks.", "[dryly] I have no blockers. Proceed.", "[calmly] Unblocked. Noted."],
        "lily": ["[sighs] No blocks, dear.", "[softly] I can't block that.", "[gently] Through it goes."]}),
    "take-it": ("takes small combat damage", {
        "harry": ["[scoffs] I'll take it.", "[laughs] That's all? Fine.", "[exhales] Take it. Whatever."],
        "bill": ["[calmly] I'll take that.", "[dryly] Acceptable losses.", "[calmly] Taken."],
        "lily": ["[gently] I'll take it, love.", "[softly] Fine. I'll take that.", "[chuckles] Just a scratch."]}),
    "sure": ("lets another player's spell resolve", {
        "harry": ["[scoffs] Sure.", "[exhales] Fine. Resolves.", "[laughs] Yeah, okay.", "[angry] Whatever. Resolves."],
        "bill": ["[calmly] Resolves.", "[calmly] Fine.", "[dryly] Very well.", "[calmly] No response."],
        "lily": ["[gently] Go on, dear.", "[softly] That's fine.", "[warmly] Resolves, love.", "[gently] No objection."]}),
    "hold-on": ("something on the stack targets its permanent or itself", {
        "harry": ["[angry] Wait. Which one?!", "[shouting] Hold on! Targeting what?!", "[frustrated] Hey! That's mine!"],
        "bill": ["[calmly] One moment. Which target?", "[dryly] Excuse me. That is mine.", "[calmly] Hold on. Let me read that."],
        "lily": ["[gasps] Wait, dear. Mine?", "[gently] One moment, love. Which one?", "[softly] Oh. That's mine."]}),
    "holding-mana": ("sees another seat pass with mana untapped", {
        "harry": ["[scoffs] Passing with mana up? Suspicious.", "[angry] They're holding something!", "[laughs] Mana open. Cute."],
        "bill": ["[dryly] Untapped mana. Interesting.", "[calmly] Someone is holding a card.", "[whispers] Mana up. Take note."],
        "lily": ["[mischievously] Someone's holding something, dears.", "[gently] All that mana untapped, love?", "[softly] Hmm. Mana open."]}),
}

# memory and arc (phase D): grudges, running jokes, the shape of the game, deals kept and broken
ARC: dict[str, tuple[str, dict[str, list[str]]]] = {
    "grudge": ("hit by the same seat for the third time this game", {
        "harry": ["[angry] You again?! Pick on someone else!", "[shouting] Every time! It's always me!", "[frustrated] What did I ever do to you?!"],
        "bill": ["[dryly] You again. I'm sensing a pattern.", "[calmly] Third time. I am keeping count.", "[sighs] Must it always be me?"],
        "lily": ["[gently] You do keep hitting me, love.", "[softly] Again, dear? What did I do?", "[chuckles] I'm starting to take this personally."]}),
    "again-countered": ("its third spell countered this game", {
        "harry": ["[angry] Again?! Counter something else!", "[shouting] Every spell! Every single one!", "[groans] Countered. Again. Of course."],
        "bill": ["[dryly] Countered. Again. How original.", "[sighs] The third one. I'm keeping a ledger.", "[calmly] Predictable. And still annoying."],
        "lily": ["[sighs] Again, love? Let one resolve.", "[gently] You've countered everything, dear.", "[softly] Third time. I'm getting used to it."]}),
    "not-again-sweep": ("the second board wipe of the game hits it", {
        "harry": ["[groans] Another wipe?! Come on!", "[angry] Not again! I just rebuilt!", "[frustrated] Two wipes! Who builds a deck like this?!"],
        "bill": ["[sighs] Another wipe. Rebuilding, again.", "[dryly] The second wipe. Tedious.", "[calmly] Wipe two. My patience is finite."],
        "lily": ["[sighs] Not another wipe, dears.", "[gently] Oh, everything again? Oh dear.", "[softly] Twice now. My poor board."]}),
    "heads-up": ("only two players remain and it is one of them", {
        "harry": ["[excited] Just you and me! Let's finish this!", "[shouting] Two left! No more hiding!", "[laughs] Heads up. I like my odds."],
        "bill": ["[calmly] Just the two of us. Finally.", "[dryly] Heads up. May the better deck win.", "[calmly] Two remain. Let us be efficient."],
        "lily": ["[warmly] Just us now, dear. Shall we?", "[gently] Two left. Let's make it a good ending.", "[softly] Heads up, love. Good luck."]}),
    "early-game": ("its turn begins in the first round", {
        "harry": ["[laughs] Early game. Nobody's dead yet!", "[excited] First turns! Let's get moving!", "[smug] Setting up. Watch closely."],
        "bill": ["[calmly] Early days. Everyone develops.", "[dryly] The opening. Ramp, ramp, pass.", "[calmly] Turn one. Patience, all."],
        "lily": ["[warmly] Early yet, dears. Settle in.", "[gently] Still setting up, loves.", "[softly] The quiet part. Enjoy it."]}),
    "long-game": ("the game has run past turn fourteen", {
        "harry": ["[groans] This game is taking forever!", "[frustrated] Somebody win already!", "[laughs] Still going? Fine. I've got time."],
        "bill": ["[dryly] Turn fourteen. Riveting.", "[sighs] A long game. Someone should end it.", "[calmly] The grind. My favourite phase."],
        "lily": ["[chuckles] We've been here a while, dears.", "[gently] Long game. Anyone winning?", "[softly] Shall we wrap this up, loves?"]}),
    "someone-wins": ("a board that could end the game next turn", {
        "harry": ["[shouting] Somebody's winning this turn! Do something!", "[angry] They're about to win! Wake up!", "[shouting] That board is lethal! Answers, now!"],
        "bill": ["[calmly] Someone wins next turn unless we act.", "[dryly] The end approaches. Any answers?", "[calmly] That board is lethal. Respond, or lose."],
        "lily": ["[gasps] Someone's about to win, dears.", "[gently] This is the turn, loves. Do something.", "[softly] That board ends us, dears."]}),
    "take-the-deal": ("accepts a truce", {
        "harry": ["[laughs] Deal. For one turn. Then you're mine.", "[smug] Fine. Deal. Don't push it.", "[laughs] Okay, okay. Truce. For now."],
        "bill": ["[calmly] Agreed. This turn only.", "[dryly] A truce. I'll hold you to it.", "[calmly] Very well. We have terms."],
        "lily": ["[warmly] Deal, love. Be good.", "[gently] Peace it is, dear.", "[softly] Agreed, dear. For now."]}),
    "no-deal": ("refuses a truce", {
        "harry": ["[laughs] No deal! You're the threat!", "[scoffs] Deal? With you? Never.", "[shouting] No truce! Not with that board!"],
        "bill": ["[calmly] No. Your board says otherwise.", "[dryly] Declined. Politely.", "[calmly] I think not. Not today."],
        "lily": ["[gently] I'm afraid not, dear.", "[chuckles] No deal, love. Not this time.", "[softly] I'd rather not, dear. Sorry."]}),
    "you-promised": ("attacked by a seat it had a truce with", {
        "harry": ["[angry] You promised! Liar!", "[shouting] We had a deal!", "[frustrated] Oh, so that's what your word is worth!"],
        "bill": ["[dryly] We had an agreement. Noted.", "[calmly] So much for the truce.", "[sighs] A deal, broken. I shall remember."],
        "lily": ["[gasps] You promised, love!", "[gently] We had a deal, dear. Shame.", "[softly] Oh. So much for our truce."]}),
}

# mulligans (Ben, 2026-09-11: "a clear easy moment — digging for combos, pity, risky play, mana screw")
MULLIGAN: dict[str, tuple[str, dict[str, list[str]]]] = {
    "keep-seven": ("keeps its opening seven", {
        "harry": ["[smug] Seven. Keeping.", "[excited] Keep! Let's go!", "[laughs] Seven cards, no complaints."],
        "bill": ["[calmly] Seven. I keep.", "[dryly] Keeping. Naturally.", "[calmly] A keep. Proceed."],
        "lily": ["[warmly] I'll keep, dears.", "[gently] Seven, thank you. Keeping.", "[softly] A lovely seven."]}),
    "mull-to-six": ("takes its first mulligan", {
        "harry": ["[frustrated] Mulligan. Six.", "[angry] Ugh. Going to six.", "[exhales] Shipping it. Six."],
        "bill": ["[sighs] A mulligan. Six.", "[calmly] Down to six. Acceptable.", "[dryly] Six cards. Statistics, be kind."],
        "lily": ["[sighs] Oh, a mulligan. Six for me.", "[gently] Six it is, dears.", "[softly] Down to six. Wish me luck."]}),
    "mull-to-five": ("takes its second mulligan", {
        "harry": ["[groans] Five. Five!", "[angry] Two mulligans! This is fine!", "[frustrated] Five cards. Don't laugh."],
        "bill": ["[sighs] Five. This will be a long game.", "[dryly] Five cards. Character-building.", "[calmly] Down to five. Regrettable."],
        "lily": ["[sighs] Five, dears. Oh dear.", "[gently] Five cards. Be kind to me.", "[softly] Two mulligans. Poor me."]}),
    "mull-to-four": ("takes its third mulligan", {
        "harry": ["[shouting] Four! Somebody shuffle me properly!", "[groans] Four cards. Just end me.", "[angry] Three mulligans. Unbelievable."],
        "bill": ["[sighs] Four. Well.", "[dryly] Four cards. A philosophical exercise.", "[calmly] Three mulligans. Noted, bitterly."],
        "lily": ["[gasps] Four cards. Goodness.", "[sighs] Four, dears. Say nothing.", "[softly] Three mulligans. Be gentle with me."]}),
    "mull-pity": ("another seat mulliganed: sympathy", {
        "harry": ["[laughs] Oof. Rough start!", "[scoffs] Mulligan already? Yikes.", "[laughs] Shuffle better next time!"],
        "bill": ["[calmly] Unfortunate. My condolences.", "[dryly] A mulligan. The variance giveth.", "[calmly] Down a card already. Noted."],
        "lily": ["[gently] Oh, bad luck, dear.", "[softly] Poor thing. Rough start.", "[warmly] It happens to the best of us, love."]}),
    "mull-dig": ("another seat mulliganed: suspicion", {
        "harry": ["[angry] Digging for the combo, are we?!", "[scoffs] Mulligan for the good stuff. Typical.", "[laughs] Fishing! Watch them!"],
        "bill": ["[dryly] Digging for something specific, I presume.", "[calmly] A mulligan for the combo piece. Watch that seat.", "[dryly] Searching for the good hand. Naturally."],
        "lily": ["[mischievously] Fishing for something, love?", "[gently] Looking for the combo, are we, dear?", "[softly] Someone wants a particular hand."]}),
    "mull-screw": ("another seat mulliganed: the mana question", {
        "harry": ["[laughs] No lands? Ha!", "[scoffs] Mana screw already? Brutal.", "[laughs] Keep a land next time!"],
        "bill": ["[calmly] No lands, I take it.", "[dryly] Mana problems before turn one. Impressive.", "[calmly] A land-light seven, was it?"],
        "lily": ["[gently] No lands, dear?", "[softly] Mana troubles already? Oh dear.", "[chuckles] Did the lands hide from you, love?"]}),
    "mull-risky": ("another seat kept a small hand", {
        "harry": ["[laughs] Keeping five? Bold!", "[scoffs] Risky keep. Love it.", "[excited] Small hand, big dreams!"],
        "bill": ["[dryly] A risky keep. We shall see.", "[calmly] Five cards, kept. Confidence, or desperation.", "[dryly] A brave hand. Or a desperate one."],
        "lily": ["[mischievously] A brave keep, dear.", "[gently] Risky, love. Good luck.", "[softly] Keeping that? Bold, dear."]}),
    "mull-gloat": ("kept seven while another seat went small", {
        "harry": ["[smug] Seven for me. Enjoy your five!", "[laughs] My seven's perfect. Sorry!", "[smug] Full grip here. Just saying."],
        "bill": ["[dryly] I kept seven. Do catch up.", "[calmly] Seven here. No complaints.", "[dryly] A full hand. How novel."],
        "lily": ["[chuckles] Seven here, dears. Sorry.", "[warmly] My seven's lovely. Poor you.", "[mischievously] Full hand. Don't hate me."]}),
}

# loops (Ben, game 47: "Vault's gone!" fell flat while Urza bounced his own Mana Vault over and over)
LOOP: dict[str, tuple[str, dict[str, list[str]]]] = {
    "loop": ("sees another seat recast or bounce the same card again — a loop, an engine, not removal", {
        "harry": ["[angry] Again?! Stop looping that thing!", "[shouting] That's a loop! Somebody break it!", "[groans] Round and round. Kill the engine!"],
        "bill": ["[dryly] A loop. How tedious.", "[calmly] The same card, again. That is an engine.", "[sighs] Bounce, recast, repeat. Someone interrupt."],
        "lily": ["[sighs] Round and round, dear.", "[gently] That's a loop, loves. Break it.", "[softly] Again? Oh, we're in trouble."]}),
    "looping": ("recasts or bounces its own card again", {
        "harry": ["[laughs] Again! And again!", "[smug] One more time. And another.", "[excited] Loop it! Loop it!"],
        "bill": ["[calmly] Once more. And again.", "[dryly] The engine turns.", "[calmly] Bounce. Recast. Proceed."],
        "lily": ["[mischievously] Round we go again, dears.", "[warmly] Once more, with feeling.", "[chuckles] And again. Sorry, loves."]}),
}

# The player's window has sat open a while (Ben, 2026-09-14: "heckles are great, but the advisor
# should not respond" — the seats speak to the player; Joshua is a ghost outside the game).
HECKLE: dict[str, tuple[str, dict[str, list[str]]]] = {
    "waiting-on-you": ("the human's decision window has been open for a while", {
        "harry": ["[impatient] We're waiting on you.", "[loud] Hello? Your turn!", "[mocking] Take your time. No, really, take it.", "[sighs] Any day now."],
        "bill": ["[dryly] We are waiting on you.", "[calmly] Player One. Whenever you're ready.", "[dryly] The clock is a suggestion, apparently.", "[sighs] Any day now."],
        "lily": ["[gently] We're waiting on you, dear.", "[warmly] Take your time. We're not going anywhere.", "[softly] Hello? Still with us?", "[amused] Any day now, sweetheart."]}),
    "still-waiting": ("the same window, a good deal later", {
        "harry": ["[annoyed] Still waiting.", "[loud] Did they leave?", "[mocking] I think we lost them.", "[groans] Somebody poke Player One."],
        "bill": ["[dryly] Still waiting.", "[calmly] Have they stepped away?", "[dryly] We appear to have lost Player One.", "[sighs] Shall we send a search party?"],
        "lily": ["[gently] Still waiting, dear.", "[softly] Did we lose them?", "[amused] I think they went for tea.", "[warmly] Come back to us, Player One."]}),
    "there-you-are": ("the human finally acts after a long wait", {
        "harry": ["[relieved] There you are!", "[mocking] Finally.", "[laughs] Welcome back!", "[loud] Thought we'd lost you."],
        "bill": ["[dryly] There you are.", "[calmly] Welcome back.", "[dryly] Finally.", "[calmly] Thought we had lost you."],
        "lily": ["[warmly] There you are, dear.", "[gently] Welcome back.", "[amused] Thought we'd lost you.", "[softly] Ah, finally."]}),
}

# Table deals (plan 2026-09-16 §7, §11): the player deals through the Advisor chat; the seat answers in its own
# voice and MEANS it. These are fixed "Player One" lines (the {say}/{voc} fills are for commanders — the player
# has no commander name at the table): the seat's answer to the player's offer (accept / refuse / counter), the
# lapse, the human breaking a deal (the seat, angry), and a seat breaking its own (it chose — it owns it). The
# generic take-the-deal / no-deal / promise / you-promised keep serving seat-to-seat.
DEALS: dict[str, tuple[str, dict[str, list[str]]]] = {
    "deal-with-you": ("accepts the player's offer of a deal (addressed to Player One)", {
        "harry": ["[laughs] Deal, Player One. One turn. Then you're mine.", "[smug] Fine, Player One. We have a deal.",
                  "[laughs] Alright, Player One. Truce. Don't push it.", "[excited] Deal! You and me, Player One. For now."],
        "bill": ["[calmly] Agreed, Player One. We have terms.", "[dryly] Very well, Player One. I'll hold you to it.",
                 "[calmly] Deal, Player One. This turn only.", "[calmly] Accepted, Player One. Do keep your word."],
        "lily": ["[warmly] Deal, Player One. Be good, dear.", "[gently] Peace it is, Player One.",
                 "[softly] Agreed, Player One. For now, love.", "[warmly] You have a deal, Player One."]}),
    "no-deal-with-you": ("refuses the player's offer of a deal (addressed to Player One)", {
        "harry": ["[laughs] No deal, Player One! You're the threat!", "[scoffs] A deal? With you, Player One? Never.",
                  "[shouting] No truce, Player One! Not with that board!", "[angry] No, Player One. I don't do deals."],
        "bill": ["[calmly] No, Player One. Your board says otherwise.", "[dryly] Declined, Player One. Politely.",
                 "[calmly] I think not, Player One. Not today.", "[dryly] No deal, Player One. Nothing personal."],
        "lily": ["[gently] I'm afraid not, Player One.", "[chuckles] No deal, Player One. Not this time.",
                 "[softly] I'd rather not, Player One. Sorry.", "[gently] No, dear Player One. Not today."]}),
    "counter-offer": ("answers the player's offer with different terms (addressed to Player One; the terms reach the panel)", {
        "harry": ["[laughs] Not that deal, Player One. Try mine.", "[smug] Counter, Player One. My terms, not yours.",
                  "[mischievously] Close, Player One. Here's my offer.", "[laughs] No. But here's a deal, Player One."],
        "bill": ["[calmly] Not those terms, Player One. Consider mine.", "[dryly] A counter-offer, Player One. Read it.",
                 "[calmly] Almost, Player One. Different terms.", "[calmly] I propose an amendment, Player One."],
        "lily": ["[gently] Not quite, Player One. How about this?", "[warmly] Let me counter, Player One, dear.",
                 "[softly] Different terms, Player One. Hear me out.", "[mischievously] Close, love. Try my offer, Player One."]}),
    "deal-over": ("its deal has run its course (the lapse)", {
        "harry": ["[laughs] Our truce is done. Watch yourself.", "[smug] Deal's over. Gloves off.",
                  "[excited] Time's up! No more truce!", "[mischievously] That deal? Expired. Sorry."],
        "bill": ["[calmly] Our truce has ended.", "[dryly] The deal has expired. Noted.",
                 "[calmly] Terms concluded. We proceed as before.", "[dryly] Our arrangement is over."],
        "lily": ["[gently] Our truce is done, dear.", "[softly] The deal's over, love. No hard feelings.",
                 "[warmly] Time's up on our little pact.", "[gently] Our peace has ended, dears."]}),
    "you-broke-it": ("the player attacked or targeted it across their deal (addressed to Player One, angry)", {
        "harry": ["[angry] You broke it, Player One! Liar!", "[shouting] We had a deal, Player One!",
                  "[frustrated] Your word, Player One? Worthless!", "[angry] You promised, Player One! You promised!"],
        "bill": ["[dryly] We had an agreement, Player One.", "[calmly] So much for your word, Player One.",
                 "[sighs] A deal broken, Player One. I'll remember.", "[dryly] Noted, Player One. Your promises are decorative."],
        "lily": ["[gasps] You promised, Player One!", "[gently] We had a deal, Player One. Shame.",
                 "[softly] Oh, Player One. So much for our truce.", "[sighs] You broke it, Player One. I trusted you."]}),
    "i-broke-it": ("breaks its own deal by attacking or targeting the other party — it chose, and owns it", {
        "harry": ["[laughs] I know what I promised. I lied.", "[smug] Deal's off. My call.",
                  "[laughs] Yeah, I promised. Yeah, I'm attacking.", "[mischievously] Truce? What truce?"],
        "bill": ["[calmly] I am aware of what I promised.", "[dryly] The deal was useful. It no longer is.",
                 "[calmly] I promised. I reconsidered.", "[dryly] Consider our arrangement terminated."],
        "lily": ["[softly] I know what I promised, dear. Sorry.", "[gently] Forgive me, love. Needs must.",
                 "[mischievously] I did promise. And yet.", "[softly] A promise, broken. I know."]}),
}
DEALS_ADDRESSED = ("deal-with-you", "no-deal-with-you", "counter-offer", "you-broke-it")     # every wording names Player One

# number lines: (family, template per lib) — {n} = the number in words, {N} capitalised
NUMBER_TAGS = {
    "harry": lambda n: "[angry]" if n <= 10 else "[exhales]" if n <= 20 else "[smug]",
    "bill": lambda n: "[calmly]",
    "lily": lambda n: "[softly]" if n <= 10 else "[gently]",
}


def life_line(lib: str, n: int) -> str:
    return f"{NUMBER_TAGS[lib](n)} I'm at {words(n)}."


def hand_line(lib: str, n: int) -> str:
    tag = {"harry": "[scoffs]", "bill": "[calmly]", "lily": "[gently]"}[lib]
    if n == 0:
        return f"{tag} " + {"harry": "No cards. Happy?", "bill": "No cards in hand.", "lily": "Not a card, dear."}[lib]
    if n == 1:
        return f"{tag} " + {"harry": "One card.", "bill": "One card.", "lily": "Just the one, love."}[lib]
    return f"{tag} {words(n).capitalize()} cards."


# address families: template per lib; {say} as a subject, {voc} when addressed
ADDRESS = {
    "hit": ("tells the table to attack a named player", {
        "harry": "[shouting] Everybody hit {say}!", "bill": "[dryly] Might I suggest we all hit {say}.", "lily": "[gently] Dears, {say} needs attention."}),
    "threat": ("names a player as the threat", {
        "harry": "[shouting] {Say}'s the threat! Wake up!", "bill": "[calmly] For the record, {say} is the threat.", "lily": "[warmly] {Say} is the problem, loves."}),
    "leave-me": ("asks a named player to leave it alone", {
        "harry": "[angry] Leave me alone, {voc}!", "bill": "[dryly] Do leave me be, {voc}.", "lily": "[gently] Leave me be, {voc} dear."}),
    "deal": ("offers a named player a truce", {
        "harry": "[laughs] Deal, {voc}? Don't hit me, I don't hit you.", "bill": "[calmly] {Voc}. A truce, this turn?", "lily": "[warmly] Peace for a turn, {voc}?"}),
}


def address_targets() -> dict[str, dict]:
    """who-slug -> {"say", "voc", "kind"} for every commander on disk and every colour identity."""
    out: dict[str, dict] = {}
    for deck, c in commanders().items():
        out.setdefault(c["slug"], {"say": c["say"], "voc": c["say"], "kind": "commander", "decks": []})["decks"].append(deck)
    for key, (slug, say, voc) in COLORS.items():
        out[slug] = {"say": say, "voc": voc, "kind": "color", "colors": key}
    return out


def render_block(lib: str) -> dict:
    parent = json.loads((VOICES / lib / "manifest.json").read_text())
    return {k: parent[k] for k in ("voice_id", "voice_name", "temperament", "render", "bake", "sample_rate", "tags_note") if k in parent}


def build_manifest(lib: str) -> dict:
    m = {"schema": "arena.voice-stock/1", "library": f"{lib}/table", "parent": lib, "seat": None,
         "note": ("the table sub-library (round 31): procedural self-narration, whole-sentence numbers and "
                  "named addressing, fired by the voice runner from board events; regenerate with runner/voice/table_lines.py --write"),
         **render_block(lib), "phrases": {}}
    ph = m["phrases"]
    for pid, (when, by) in PROCEDURAL.items():
        ph[pid] = {"category": "procedural", "when": when, "text": list(by[lib]), "source": "table-2026-09-10"}
    for pid, (when, by) in ARC.items():
        ph[pid] = {"category": "arc", "when": when, "text": list(by[lib]), "source": "table-arc-2026-09-10"}
    for pid, (when, by) in MULLIGAN.items():
        ph[pid] = {"category": "mulligan", "when": when, "text": list(by[lib]), "source": "table-mulligan-2026-09-11"}
    for pid, (when, by) in LOOP.items():
        ph[pid] = {"category": "loop", "when": when, "text": list(by[lib]), "source": "table-loop-2026-09-11"}
    for pid, (when, by) in HECKLE.items():
        ph[pid] = {"category": "heckle", "when": when, "text": list(by[lib]), "source": "table-heckle-2026-09-14"}
    for pid, (when, by) in DEALS.items():
        ph[pid] = {"category": "deal", "when": when, "text": list(by[lib]), "source": "table-deal-2026-09-16"}
    for n in LIFE_NUMBERS:
        ph[f"life-{n}"] = {"category": "number", "when": f"announces or answers its life total: {n}", "text": [life_line(lib, n)], "source": "table-2026-09-10"}
    for n in HAND_NUMBERS:
        ph[f"hand-{n}"] = {"category": "number", "when": f"announces or answers its hand size: {n}", "text": [hand_line(lib, n)], "source": "table-2026-09-10"}
    for who, info in address_targets().items():
        fill = {"say": info["say"], "voc": info["voc"], "Say": info["say"][0].upper() + info["say"][1:], "Voc": info["voc"][0].upper() + info["voc"][1:]}
        for fam, (when, by) in ADDRESS.items():
            ph[f"{fam}-{who}"] = {"category": "address", "when": f"{when} ({info['kind']}: {info['say']})",
                                  "text": [by[lib].format(**fill)], "source": "table-2026-09-10"}
    return m


def write_all() -> None:
    for lib in LIBS:
        d = VOICES / lib / "table"
        d.mkdir(parents=True, exist_ok=True)
        m = build_manifest(lib)
        try:
            old = json.loads((d / "manifest.json").read_text())
            if old.get("baked"):
                m["baked"] = old["baked"]                        # the library's measured gain survives a rewrite
        except (OSError, ValueError):
            pass
        (d / "manifest.json").write_text(json.dumps(m, indent=1, ensure_ascii=False) + "\n")
    addr = {"schema": "arena.voice-address/1",
            "note": ("who a seat may address by name (round 31): a deck's commander slug when the table lines carry it, "
                     "else the deck's colour identity (Ben's chart). The voice runner maps seat -> deck -> who; a missing "
                     "wav falls back to the generic line. Regenerate with runner/voice/table_lines.py --write."),
            "commanders": {deck: {"who": c["slug"], "say": c["say"], "name": c["name"], "colors": c["colors"]} for deck, c in commanders().items()},
            "colors": {key: slug for key, (slug, _, _) in COLORS.items()},
            "families": {fam: when for fam, (when, _) in ADDRESS.items()}}
    (VOICES / "address.json").write_text(json.dumps(addr, indent=1, ensure_ascii=False) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    m = build_manifest("harry")
    cats: dict[str, int] = {}
    chars = 0
    for lib in LIBS:
        for ph in build_manifest(lib)["phrases"].values():
            cats[ph["category"]] = cats.get(ph["category"], 0) + len(ph["text"])
            chars += sum(len(t) for t in ph["text"])
    print(f"{len(m['phrases'])} ids per voice; wordings across three voices: {cats} = {sum(cats.values())} lines, {chars} characters")
    print("commanders:", {d: c['slug'] for d, c in commanders().items()})
    if a.write:
        write_all()
        print("written:", ", ".join(str(VOICES / lib / "table" / "manifest.json") for lib in LIBS), "and", VOICES / "address.json")


if __name__ == "__main__":
    main()
