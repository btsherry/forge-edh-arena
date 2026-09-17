#!/usr/bin/env python3
"""card_lines.py — the "cards" sub-library of every seat voice (round 31, 2026-09-10).

Card-specific lines, grounded in the oracle text on record (decks/<slug>/dossier/
deck-cards.json — Ben's rule: card facts from the record, not memory), in the three
registers (Harry fiery, Bill dry professor, Lily warm and theatrical). Written for:

  game changers   every card Scryfall flags game_changer in any deck on disk:
                  gc-<slug>-cast (the caster crows, x2), gc-<slug>-react (someone
                  else, x2), gc-<slug>-gone (someone else, relieved, x1)
  commanders      every commander on disk: cmd-<who>-cast (x2), cmd-<who>-react (x2),
                  cmd-<who>-dead (the owner, x1) — <who> is the address slug
                  (voices/address.json), so Rev's two decks share one set
  combos          every <=3-piece battlefield combo in every dossier's combos.json,
                  grouped by SHAPE so "Hullbreaker + any rock" is one line:
                  combo-<key>-online (the assembler, x1), combo-<key>-react (x1);
                  voices/combos.json maps each key to its card sets for the runner

The voice runner keeps its generic hooks (game-changer, gc-react, gc-gone,
commander-cast, lost-commander, engine-online and the replies they invite) and
swaps in the specific wording when the seat's cards library carries it.

Dev-only (excluded from the package like build_stock.py). One eleven_v3 delivery
tag leads each wording, about ten words at most, no hidden information.

    python3 runner/voice/card_lines.py            # summary + coverage check
    python3 runner/voice/card_lines.py --write    # (re)write voices/<lib>/cards/manifest.json + voices/combos.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VOICES = HERE / "stock" / "voices"
DECKS = HERE.parent.parent / "decks"
LIBS = ("harry", "bill", "lily", "joshua")     # joshua's card wordings live in joshua_lines.py


def _gc(by: dict, lib: str, name: str, part: str) -> list:
    if lib in by:
        return list(by[lib][part])
    import joshua_lines
    return list(joshua_lines.GC[name][part])


def _cmd(by: dict, lib: str, who: str, part: str) -> list:
    if lib in by:
        return list(by[lib][part])
    import joshua_lines
    return list(joshua_lines.CMD[who][part])


def _combo(info: dict, lib: str, key: str):
    if lib in info:
        return info[lib]
    import joshua_lines
    return joshua_lines.COMBOS[key]


def card_slug(name: str) -> str:
    """'Tergrid, God of Fright // Tergrid's Lantern' -> 'tergrid-god-of-fright' (the voice runner has the same function)."""
    front = name.split(" // ")[0].lower()
    s = "".join(ch if ch.isalnum() else "-" for ch in front)
    return "-".join(p for p in s.split("-") if p)


# ---- game changers: name -> {lib: {"cast": [..], "react": [..], "gone": [..]}} ----------------
GC = {
    "Ancient Tomb": {
        "harry": {"cast": ["[excited] Tomb! Two mana, two damage. Worth it!", "[laughs] Ancient Tomb. Pain is mana!"],
                  "react": ["[scoffs] Tomb. Enjoy the paper cuts.", "[angry] Two extra mana on turn one? Come on!"],
                  "gone": ["[laughs] Tomb's gone. No more free mana!"]},
        "bill": {"cast": ["[calmly] Ancient Tomb. Two mana, at a price.", "[dryly] Tomb. The damage is an investment."],
                 "react": ["[dryly] A Tomb. Fast mana, slow bleeding.", "[calmly] Two mana on turn one. Noted."],
                 "gone": ["[calmly] The Tomb is gone. Fewer fast starts."]},
        "lily": {"cast": ["[warmly] Ancient Tomb, dears. It bites, but it pays.", "[chuckles] Tomb. A little pain for a lot of mana."],
                 "react": ["[gently] Tomb, love? That'll hurt over time.", "[softly] Oh, a Tomb. Someone's in a hurry."],
                 "gone": ["[gently] Goodbye, Tomb. Your life total thanks you."]}},
    "Aura Shards": {
        "harry": {"cast": ["[shouting] Aura Shards! Every creature blows something up!", "[laughs] Shards! Say goodbye to your rocks!"],
                  "react": ["[angry] Aura Shards?! My artifacts are all dead!", "[shouting] Kill that! Every creature is removal now!"],
                  "gone": ["[laughs] Shards is gone! My rocks can breathe!"]},
        "bill": {"cast": ["[calmly] Aura Shards. Each creature destroys an artifact or enchantment.", "[dryly] Shards. Your trinkets are on notice."],
                 "react": ["[sighs] Aura Shards. My artifacts have an expiry date.", "[calmly] Every creature they play is removal now."],
                 "gone": ["[calmly] Shards is gone. The artifacts may relax."]},
        "lily": {"cast": ["[warmly] Aura Shards, dears. My friends will tidy up.", "[mischievously] Shards. Every creature brings a little demolition."],
                 "react": ["[gasps] Aura Shards? Oh, my poor enchantments.", "[gently] That needs answering, loves. Every creature is a Disenchant."],
                 "gone": ["[softly] Shards is gone. What a relief."]}},
    "Chrome Mox": {
        "harry": {"cast": ["[excited] Chrome Mox! Free mana, let's go!", "[laughs] Mox! Turn one is mine!"],
                  "react": ["[scoffs] Chrome Mox. What did you exile for that?", "[angry] A Mox on turn one? Ugh!"],
                  "gone": ["[laughs] Mox is gone! Back to fair mana!"]},
        "bill": {"cast": ["[calmly] Chrome Mox. One card for one mana, every turn.", "[dryly] Mox. Tempo, purchased with a card."],
                 "react": ["[calmly] Chrome Mox. Card disadvantage, but fast.", "[dryly] A Mox. How very competitive."],
                 "gone": ["[calmly] The Mox is gone. Tempo lost."]},
        "lily": {"cast": ["[warmly] Chrome Mox, dears. A little sacrifice for speed.", "[chuckles] Mox. I've given up a card for this."],
                 "react": ["[gently] A Mox, love? Someone means business.", "[softly] Free mana. Hmm."],
                 "gone": ["[gently] The Mox is gone. Slower now, dear."]}},
    "Consecrated Sphinx": {
        "harry": {"cast": ["[shouting] Sphinx! Every card you draw, I draw two!", "[laughs] Consecrated Sphinx! Keep drawing, I dare you!"],
                  "react": ["[angry] Kill the Sphinx! Kill it now!", "[shouting] Sphinx?! I'm not drawing anymore!"],
                  "gone": ["[laughs] Sphinx is dead! Draw freely, everyone!"]},
        "bill": {"cast": ["[calmly] Consecrated Sphinx. Your draws feed mine.", "[dryly] The Sphinx. Please, draw your cards."],
                 "react": ["[sighs] The Sphinx. That must die before my draw step.", "[calmly] Every draw gives them two. Untenable."],
                 "gone": ["[calmly] The Sphinx is gone. Draw steps are safe again."]},
        "lily": {"cast": ["[warmly] The Sphinx, dears. Two cards for every one of yours.", "[mischievously] Consecrated Sphinx. Do draw, loves."],
                 "react": ["[gasps] A Sphinx? That's terribly greedy, dear.", "[gently] We must remove that Sphinx, dears. Quickly."],
                 "gone": ["[softly] The Sphinx is gone. Good."]}},
    "Cyclonic Rift": {
        "harry": {"cast": ["[shouting] Rift! Everything goes back!", "[laughs] Cyclonic Rift! Overloaded! Enjoy your hands!"],
                  "react": ["[angry] Rift?! My whole board! Argh!", "[groans] Not Rift. Anything but Rift."],
                  "gone": ["[laughs] Rift's used up. Rebuild time!"]},
        "bill": {"cast": ["[calmly] Cyclonic Rift. Your permanents return to hand.", "[dryly] Rift, overloaded. Do enjoy recasting all that."],
                 "react": ["[sighs] Rift. Years of work, back to hand.", "[dryly] The blue player's favourite. Predictable."],
                 "gone": ["[calmly] The Rift is spent. Rebuild."]},
        "lily": {"cast": ["[warmly] Cyclonic Rift, dears. Everything back where it came from.", "[mischievously] Rift. A fresh start for all of you."],
                 "react": ["[gasps] Rift? Oh, my whole board, love.", "[sighs] That's the one card I feared."],
                 "gone": ["[gently] The Rift is gone. We may rebuild, dears."]}},
    "Demonic Tutor": {
        "harry": {"cast": ["[laughs] Demonic Tutor! I get whatever I want!", "[excited] Tutor! Come to me, best card!"],
                  "react": ["[angry] Demonic Tutor? What are they finding?!", "[scoffs] Tutor. Great. Here comes the combo."],
                  "gone": ["[laughs] Tutor's in the yard. Hope it was worth it!"]},
        "bill": {"cast": ["[calmly] Demonic Tutor. Any card. I know which.", "[dryly] Tutor. The library obliges."],
                 "react": ["[calmly] A Demonic Tutor. Watch what follows it.", "[dryly] They found their piece. Brace yourselves."],
                 "gone": ["[calmly] The Tutor is spent. What did it find?"]},
        "lily": {"cast": ["[warmly] Demonic Tutor, dears. Just what I needed.", "[mischievously] Tutor. Let me fetch something special."],
                 "react": ["[gently] A Tutor, love? Whatever did you take?", "[softly] Tutors worry me, dears."],
                 "gone": ["[softly] The Tutor is gone. Remember what it fetched."]}},
    "Drannith Magistrate": {
        "harry": {"cast": ["[shouting] Magistrate! Cast from your hand or not at all!", "[laughs] Drannith Magistrate! No cheating from exile!"],
                  "react": ["[angry] Magistrate?! My commander's stuck in the zone!", "[shouting] Kill the Magistrate! It's locking us out!"],
                  "gone": ["[laughs] Magistrate's dead! Cast from anywhere again!"]},
        "bill": {"cast": ["[calmly] Drannith Magistrate. Spells from your hand only.", "[dryly] The Magistrate. Your command zone is closed."],
                 "react": ["[sighs] Magistrate. My commander is grounded.", "[calmly] That must go. It shuts off half the table."],
                 "gone": ["[calmly] The Magistrate is gone. Commanders may return."]},
        "lily": {"cast": ["[warmly] Drannith Magistrate, dears. Hands only, please.", "[gently] The Magistrate. No casting from elsewhere, loves."],
                 "react": ["[gasps] The Magistrate? My commander is stranded.", "[gently] Someone deal with the Magistrate, dears."],
                 "gone": ["[softly] The Magistrate is gone. Freedom, dears."]}},
    "Enlightened Tutor": {
        "harry": {"cast": ["[excited] Enlightened Tutor! My best piece, on top!", "[laughs] Tutor! Next draw is a killer!"],
                  "react": ["[scoffs] Enlightened Tutor. What's coming next turn?", "[angry] They just set up their draw. Watch out!"],
                  "gone": ["[laughs] Tutor's done. Whatever's on top, I'm ready."]},
        "bill": {"cast": ["[calmly] Enlightened Tutor. The right piece, on top.", "[dryly] Tutor. My next draw is no longer random."],
                 "react": ["[calmly] Enlightened Tutor. Their next draw is chosen.", "[dryly] A tutor to the top. Expect it next turn."],
                 "gone": ["[calmly] Tutor spent. The top card is the tell."]},
        "lily": {"cast": ["[warmly] Enlightened Tutor, dears. I know my next card.", "[mischievously] Tutor. Something lovely on top."],
                 "react": ["[gently] A tutor, love? Do tell what's coming.", "[softly] They've stacked their draw, dears."],
                 "gone": ["[softly] The Tutor is gone. Mind their next draw."]}},
    "Farewell": {
        "harry": {"cast": ["[shouting] Farewell! Everything you love, exiled!", "[laughs] Farewell! Say goodbye to all of it!"],
                  "react": ["[angry] Farewell?! Six mana to ruin everyone's day!", "[groans] Not Farewell. Everything's gone. Gone!"],
                  "gone": ["[laughs] Farewell's done. Start over, everybody!"]},
        "bill": {"cast": ["[calmly] Farewell. I choose the modes. Exile it all.", "[dryly] Farewell. A clean slate, thoroughly."],
                 "react": ["[sighs] Farewell. Exiled, not destroyed. Nothing comes back.", "[calmly] A total reset. Regrettable."],
                 "gone": ["[calmly] Farewell resolved. Rebuilding from nothing."]},
        "lily": {"cast": ["[warmly] Farewell, dears. Time for a clean table.", "[gently] Farewell. I'm so sorry, loves."],
                 "react": ["[gasps] Farewell? Everything, exiled? Oh dear.", "[sighs] A Farewell. Well. That's that, then."],
                 "gone": ["[softly] Farewell is done. We begin again, dears."]}},
    "Fierce Guardianship": {
        "harry": {"cast": ["[shouting] Guardianship! Free counter! Denied!", "[laughs] Fierce Guardianship! Cost me nothing!"],
                  "react": ["[angry] Free counterspell?! That's not fair!", "[scoffs] Guardianship. Of course. Blue."],
                  "gone": ["[laughs] Guardianship's spent. Cast freely now!"]},
        "bill": {"cast": ["[calmly] Fierce Guardianship. No mana required. Countered.", "[dryly] Guardianship. My commander pays for that."],
                 "react": ["[dryly] Guardianship. Free, with a commander. Naturally.", "[sighs] A free counter. Blue remains blue."],
                 "gone": ["[calmly] Guardianship is spent. One less free answer."]},
        "lily": {"cast": ["[warmly] Fierce Guardianship, dear. No, thank you.", "[mischievously] Guardianship. Free of charge."],
                 "react": ["[gasps] A free counter? That's cheeky, love.", "[gently] Guardianship. They're holding those, dears."],
                 "gone": ["[softly] Guardianship is gone. Breathe, dears."]}},
    "Force of Will": {
        "harry": {"cast": ["[shouting] Force of Will! Nope!", "[laughs] Force! Pitched a card, still worth it!"],
                  "react": ["[angry] Force of Will?! Really?! For that?!", "[groans] Forced. Of course I got Forced."],
                  "gone": ["[laughs] Force is gone. The coast is clear!"]},
        "bill": {"cast": ["[calmly] Force of Will. A card and a life. Countered.", "[dryly] Force. Some things must not resolve."],
                 "react": ["[dryly] Force of Will. They pitched a card for that.", "[calmly] Forced. They mean it, then."],
                 "gone": ["[calmly] The Force is spent. Proceed."]},
        "lily": {"cast": ["[warmly] Force of Will, dear. I'm afraid not.", "[gently] Force. It pains me, but no."],
                 "react": ["[gasps] Force of Will? Oh, my poor spell.", "[softly] They Forced it. That was important, then."],
                 "gone": ["[softly] The Force is gone. Carry on, dears."]}},
    "Gaea's Cradle": {
        "harry": {"cast": ["[shouting] Cradle! Mana for every creature!", "[laughs] Gaea's Cradle! I'll never be short again!"],
                  "react": ["[angry] Cradle?! Kill their creatures, fast!", "[shouting] A Cradle! That's a hundred mana!"],
                  "gone": ["[laughs] Cradle's gone! Back to counting lands!"]},
        "bill": {"cast": ["[calmly] Gaea's Cradle. Mana scales with the board.", "[dryly] Cradle. Each creature is a land now."],
                 "react": ["[sighs] A Cradle. Their creatures are lands.", "[calmly] Cradle. Whatever they cast next will be large."],
                 "gone": ["[calmly] The Cradle is gone. Back to lands."]},
        "lily": {"cast": ["[warmly] Gaea's Cradle, dears. My friends are my mana.", "[mischievously] Cradle. Count my creatures, loves."],
                 "react": ["[gasps] Cradle? That's so much mana, dear.", "[gently] A Cradle. Watch their board, dears."],
                 "gone": ["[softly] The Cradle is gone. Smaller turns ahead."]}},
    "Gamble": {
        "harry": {"cast": ["[excited] Gamble! Come on, don't discard it!", "[laughs] Gamble! Fortune favours the bold!"],
                  "react": ["[laughs] Gamble! Hope you flipped the wrong card!", "[scoffs] Gambling already? Desperate."],
                  "gone": ["[laughs] Gamble's done. Did it work?"]},
        "bill": {"cast": ["[calmly] Gamble. One tutor, one random discard. Acceptable odds.", "[dryly] Gamble. Statistics, please be kind."],
                 "react": ["[dryly] Gamble. Ah, red's idea of a tutor.", "[calmly] Random discard. Let us hope it was the piece."],
                 "gone": ["[calmly] Gamble is spent. Did the dice cooperate?"]},
        "lily": {"cast": ["[warmly] Gamble, dears. Wish me luck.", "[chuckles] Gamble. Fortune, be gentle."],
                 "react": ["[chuckles] Gambling, love? How exciting.", "[gently] I hope they discarded the wrong one, dears."],
                 "gone": ["[softly] The Gamble is over. Was it kind?"]}},
    "Grim Monolith": {
        "harry": {"cast": ["[excited] Grim Monolith! Three mana, turn two!", "[laughs] Monolith! Big spells early!"],
                  "react": ["[angry] Grim Monolith? That's a combo piece!", "[scoffs] Monolith. Fast mana again."],
                  "gone": ["[laughs] Monolith's gone! Combo's off!"]},
        "bill": {"cast": ["[calmly] Grim Monolith. Three mana, once.", "[dryly] Monolith. It untaps when I say so."],
                 "react": ["[calmly] Grim Monolith. Watch for the untap trick.", "[dryly] A Monolith. Rings would make that infinite."],
                 "gone": ["[calmly] The Monolith is gone. Good riddance to fast mana."]},
        "lily": {"cast": ["[warmly] Grim Monolith, dears. A burst of mana.", "[mischievously] Monolith. Three lovely colourless."],
                 "react": ["[gently] A Monolith, love? That's combo mana.", "[softly] Watch that Monolith, dears."],
                 "gone": ["[softly] The Monolith is gone. Well done, dears."]}},
    "Jeska's Will": {
        "harry": {"cast": ["[shouting] Jeska's Will! Your hand is my mana!", "[laughs] Jeska's Will! Both modes! Here we go!"],
                  "react": ["[angry] Jeska's Will?! That's like ten mana!", "[shouting] Big red turn incoming! Brace!"],
                  "gone": ["[laughs] Will's spent. Hope it was worth it!"]},
        "bill": {"cast": ["[calmly] Jeska's Will. Your full hand funds my turn.", "[dryly] Jeska's Will. Both modes, with a commander."],
                 "react": ["[dryly] Jeska's Will. A ritual with ambitions.", "[calmly] Expect a very large turn. Now."],
                 "gone": ["[calmly] The Will is spent. What did it buy?"]},
        "lily": {"cast": ["[warmly] Jeska's Will, dears. Thank you for the mana.", "[mischievously] Jeska's Will. Both halves, please."],
                 "react": ["[gasps] Jeska's Will? Oh, here comes a big turn.", "[gently] Hold on to your hats, dears."],
                 "gone": ["[softly] The Will is spent. Take a breath, loves."]}},
    "Mana Vault": {
        "harry": {"cast": ["[excited] Mana Vault! Three mana, turn one!", "[laughs] Vault! Who cares about the damage!"],
                  "react": ["[angry] Mana Vault? Another fast mana rock!", "[scoffs] Vault. Enjoy the ping every turn."],
                  "gone": ["[laughs] Vault's gone! One less turbo start!"]},
        "bill": {"cast": ["[calmly] Mana Vault. Three mana, now. Pain later.", "[dryly] Vault. Efficiency with a small tax."],
                 "react": ["[calmly] Mana Vault. Turn one, three mana. Noted.", "[dryly] A Vault. Watch the untap combos."],
                 "gone": ["[calmly] The Vault is gone. The pings stop too."]},
        "lily": {"cast": ["[warmly] Mana Vault, dears. A little burst of speed.", "[chuckles] Vault. It'll nip me, but worth it."],
                 "react": ["[gently] A Vault, love? Someone's racing.", "[softly] Fast mana. Keep an eye on that, dears."],
                 "gone": ["[softly] The Vault is gone. Slower, safer."]}},
    "Mishra's Workshop": {
        "harry": {"cast": ["[shouting] Workshop! Three mana for artifacts!", "[laughs] Mishra's Workshop! Rocks for everyone!"],
                  "react": ["[angry] Workshop?! That's a turn-one bomb!", "[scoffs] Workshop. Artifacts, artifacts, artifacts."],
                  "gone": ["[laughs] Workshop's gone! Slow down, tinkerer!"]},
        "bill": {"cast": ["[calmly] Mishra's Workshop. Three mana for artifact spells.", "[dryly] Workshop. My artifacts arrive early."],
                 "react": ["[calmly] A Workshop. Expect a fast artifact start.", "[dryly] Three mana on turn one. For artifacts only, mercifully."],
                 "gone": ["[calmly] The Workshop is gone. The factory closes."]},
        "lily": {"cast": ["[warmly] Mishra's Workshop, dears. My trinkets come faster.", "[mischievously] Workshop. Three mana for my toys."],
                 "react": ["[gently] A Workshop, love? Someone's building quickly.", "[softly] Watch the artifact player, dears."],
                 "gone": ["[softly] The Workshop is gone. A quieter forge."]}},
    "Mox Diamond": {
        "harry": {"cast": ["[excited] Mox Diamond! One land for a Mox! Deal!", "[laughs] Diamond! Turn one is mine!"],
                  "react": ["[scoffs] Mox Diamond. Card disadvantage for speed.", "[angry] Free mana again! Stop it!"],
                  "gone": ["[laughs] Diamond's gone! One less rock!"]},
        "bill": {"cast": ["[calmly] Mox Diamond. A land becomes a Mox.", "[dryly] Diamond. Any colour, from turn one."],
                 "react": ["[calmly] Mox Diamond. They spent a land for tempo.", "[dryly] A Diamond. The fast mana continues."],
                 "gone": ["[calmly] The Diamond is gone. Down a land and a Mox."]},
        "lily": {"cast": ["[warmly] Mox Diamond, dears. A land for a little jewel.", "[chuckles] Diamond. Sparkly mana."],
                 "react": ["[gently] A Diamond, love? Someone's in a hurry.", "[softly] Fast mana, dears. Be wary."],
                 "gone": ["[softly] The Diamond is gone. Poor thing."]}},
    "Necropotence": {
        "harry": {"cast": ["[shouting] Necro! Life is cards now!", "[laughs] Necropotence! I'll pay twenty!"],
                  "react": ["[angry] Necro?! They're drawing their whole deck!", "[shouting] Hit them! Life is their resource now!"],
                  "gone": ["[laughs] Necro's gone! Back to one card a turn!"]},
        "bill": {"cast": ["[calmly] Necropotence. Life for cards, at end step.", "[dryly] Necro. I have life to spare."],
                 "react": ["[calmly] Necropotence. Every point of life is a card. Attack them.", "[dryly] Necro. The skull. Of course."],
                 "gone": ["[calmly] Necro is gone. Their life is just life again."]},
        "lily": {"cast": ["[warmly] Necropotence, dears. A little life for knowledge.", "[mischievously] Necro. I'll be paying quite a lot."],
                 "react": ["[gasps] Necro? Oh, they'll draw everything, dears.", "[gently] Punish their life total, loves. It's cards now."],
                 "gone": ["[softly] Necro is gone. Their hand shrinks again."]}},
    "Orcish Bowmasters": {
        "harry": {"cast": ["[shouting] Bowmasters! Draw a card, take an arrow!", "[laughs] Orcish Bowmasters! Flash! Surprise!"],
                  "react": ["[angry] Bowmasters?! Stop shooting my creatures!", "[groans] Not Bowmasters. Every draw hurts."],
                  "gone": ["[laughs] Bowmasters are dead! Draw all you want!"]},
        "bill": {"cast": ["[calmly] Orcish Bowmasters. Extra draws cost you.", "[dryly] Bowmasters. At flash speed, in response."],
                 "react": ["[calmly] Bowmasters. Their orcs punish card draw.", "[sighs] Bowmasters. My draw engine just became a liability."],
                 "gone": ["[calmly] The Bowmasters are gone. Draw freely."]},
        "lily": {"cast": ["[warmly] Bowmasters, dears. Mind your extra draws.", "[mischievously] Orcish Bowmasters. Flash. Hello."],
                 "react": ["[gasps] Bowmasters? Oh, my little creatures.", "[gently] Those orcs need to go, dears."],
                 "gone": ["[softly] The Bowmasters are gone. Peace for the drawers."]}},
    "Panoptic Mirror": {
        "harry": {"cast": ["[shouting] Panoptic Mirror! Free spell every turn!", "[laughs] Mirror! Imprint something nasty!"],
                  "react": ["[angry] Panoptic Mirror?! Break it! Break it now!", "[shouting] If that gets a Time Warp, we lose!"],
                  "gone": ["[laughs] Mirror's shattered! No free spells!"]},
        "bill": {"cast": ["[calmly] Panoptic Mirror. One spell, every upkeep, forever.", "[dryly] The Mirror. Do guess what I imprint."],
                 "react": ["[calmly] Panoptic Mirror. Destroy it before the imprint.", "[dryly] A Mirror. An extra-turn spell would end us."],
                 "gone": ["[calmly] The Mirror is gone. Sanity returns."]},
        "lily": {"cast": ["[warmly] Panoptic Mirror, dears. A spell for every morning.", "[mischievously] The Mirror. Now, what to imprint?"],
                 "react": ["[gasps] Panoptic Mirror? Break it, dears, quickly.", "[gently] That Mirror mustn't survive, loves."],
                 "gone": ["[softly] The Mirror is gone. Thank goodness."]}},
    "Rhystic Study": {
        "harry": {"cast": ["[laughs] Rhystic Study! Pay the one or I draw!", "[excited] Rhystic! Did you pay? Didn't think so!"],
                  "react": ["[angry] Rhystic Study! I'm not paying! Ever!", "[groans] Rhystic. Here comes the question every spell."],
                  "gone": ["[laughs] Rhystic's gone! No more questions!"]},
        "bill": {"cast": ["[calmly] Rhystic Study. Will you be paying the one?", "[dryly] Rhystic. I shall be asking. Frequently."],
                 "react": ["[sighs] Rhystic Study. I'll be paying all game.", "[dryly] Rhystic. The tax collector has arrived."],
                 "gone": ["[calmly] Rhystic is gone. Spells are untaxed again."]},
        "lily": {"cast": ["[warmly] Rhystic Study, dears. Do you pay the one?", "[mischievously] Rhystic. I'll be asking sweetly."],
                 "react": ["[sighs] Rhystic Study. I shan't pay, dear. Draw.", "[gently] That enchantment will bury us in cards, loves."],
                 "gone": ["[softly] Rhystic is gone. No more asking."]}},
    "Seedborn Muse": {
        "harry": {"cast": ["[shouting] Seedborn Muse! I untap every turn!", "[laughs] Muse! Four turns for the price of one!"],
                  "react": ["[angry] Seedborn Muse?! Kill it before it untaps!", "[shouting] They untap on my turn! Not fair!"],
                  "gone": ["[laughs] Muse is dead! One untap like the rest of us!"]},
        "bill": {"cast": ["[calmly] Seedborn Muse. I untap on your turns.", "[dryly] Muse. Every untap step is mine."],
                 "react": ["[calmly] Seedborn Muse. That must die before my untap.", "[sighs] Muse. Their mana is always available."],
                 "gone": ["[calmly] The Muse is gone. One untap step each, as intended."]},
        "lily": {"cast": ["[warmly] Seedborn Muse, dears. I'm always ready.", "[mischievously] Muse. Your untap step is mine too."],
                 "react": ["[gasps] Seedborn? Oh, they'll never be tapped out.", "[gently] Kill the Muse, dears. Please."],
                 "gone": ["[softly] The Muse is gone. Rest, dears."]}},
    "Serra's Sanctum": {
        "harry": {"cast": ["[shouting] Sanctum! Mana for every enchantment!", "[laughs] Serra's Sanctum! Enchantments pay me!"],
                  "react": ["[angry] Sanctum?! That's so much white mana!", "[scoffs] Sanctum. Enchantress deck, of course."],
                  "gone": ["[laughs] Sanctum's gone! Back to lands!"]},
        "bill": {"cast": ["[calmly] Serra's Sanctum. Mana per enchantment.", "[dryly] Sanctum. My enchantments are lands."],
                 "react": ["[calmly] A Sanctum. Their enchantments fund everything.", "[dryly] Sanctum. Count their enchantments. Then worry."],
                 "gone": ["[calmly] The Sanctum is gone. Enchantments stop paying."]},
        "lily": {"cast": ["[warmly] Serra's Sanctum, dears. My enchantments sing.", "[mischievously] Sanctum. Count my enchantments, loves."],
                 "react": ["[gently] Sanctum, love? That's a great deal of mana.", "[softly] Watch that land, dears."],
                 "gone": ["[softly] The Sanctum is gone. Quieter now."]}},
    "Smothering Tithe": {
        "harry": {"cast": ["[laughs] Smothering Tithe! Pay two or I get Treasure!", "[shouting] Tithe! Every draw pays me!"],
                  "react": ["[angry] Tithe?! I'm not paying two every draw!", "[groans] Smothering Tithe. They'll have twenty Treasures."],
                  "gone": ["[laughs] Tithe's gone! Keep your mana!"]},
        "bill": {"cast": ["[calmly] Smothering Tithe. Two mana, or I take Treasure.", "[dryly] Tithe. Taxes are due on every draw."],
                 "react": ["[sighs] Smothering Tithe. The Treasures will pile up.", "[dryly] Tithe. Pay two, or fund the enemy. Charming."],
                 "gone": ["[calmly] The Tithe is gone. Draws are free again."]},
        "lily": {"cast": ["[warmly] Smothering Tithe, dears. Two mana, or a Treasure for me.", "[mischievously] Tithe. Thank you in advance."],
                 "react": ["[gasps] Tithe? Oh, that'll snowball, dears.", "[gently] Someone must remove that Tithe, loves."],
                 "gone": ["[softly] The Tithe is gone. No more taxes."]}},
    "Teferi's Protection": {
        "harry": {"cast": ["[shouting] Teferi's Protection! Can't touch me!", "[laughs] Protection! Everything phases out! Ha!"],
                  "react": ["[angry] Teferi's Protection?! All that for nothing!", "[groans] Phased out. My whole attack, wasted."],
                  "gone": ["[laughs] Protection's over! Back to hitting them!"]},
        "bill": {"cast": ["[calmly] Teferi's Protection. I am elsewhere until my turn.", "[dryly] Teferi's. Your efforts are noted, and wasted."],
                 "react": ["[sighs] Teferi's Protection. The board wipe missed them.", "[dryly] Phased out. Untouchable. How convenient."],
                 "gone": ["[calmly] Their protection is over. Open season."]},
        "lily": {"cast": ["[warmly] Teferi's Protection, dears. Not today.", "[gently] Protection. I'll be back for my turn, loves."],
                 "react": ["[gasps] Teferi's? Oh, they dodged everything.", "[softly] They're untouchable for now, dears."],
                 "gone": ["[softly] Their protection is gone. Carry on, dears."]}},
    "Tergrid, God of Fright // Tergrid's Lantern": {
        "harry": {"cast": ["[shouting] Tergrid! Sacrifice anything, I keep it!", "[laughs] Tergrid, God of Fright! Your losses, my gains!"],
                  "react": ["[angry] Tergrid?! Don't sacrifice anything! Ever!", "[shouting] Kill Tergrid! It steals everything!"],
                  "gone": ["[laughs] Tergrid's gone! Sacrifice freely!"]},
        "bill": {"cast": ["[calmly] Tergrid. What you sacrifice, I keep.", "[dryly] Tergrid. Your discards are my permanents."],
                 "react": ["[calmly] Tergrid. Sacrifice nothing. Discard nothing.", "[sighs] Tergrid. My whole plan just became theirs."],
                 "gone": ["[calmly] Tergrid is gone. Sacrifice at will."]},
        "lily": {"cast": ["[warmly] Tergrid, dears. Whatever you lose, I'll cherish.", "[mischievously] Tergrid. Do keep sacrificing, loves."],
                 "react": ["[gasps] Tergrid? Oh, that's a wicked card, dear.", "[gently] Nobody sacrifice anything, dears."],
                 "gone": ["[softly] Tergrid is gone. What a relief."]}},
    "The One Ring": {
        "harry": {"cast": ["[shouting] The Ring! Can't touch me this turn!", "[laughs] The One Ring! Cards every turn!"],
                  "react": ["[angry] The Ring?! Indestructible and it draws!", "[groans] The Ring. Precious. Ugh."],
                  "gone": ["[laughs] The Ring's gone! Back to fair draws!"]},
        "bill": {"cast": ["[calmly] The One Ring. Protection now, cards later.", "[dryly] The Ring. Indestructible. Draw engine. Yes."],
                 "react": ["[sighs] The One Ring. Exile it, or watch them draw.", "[dryly] The Ring. Naturally."],
                 "gone": ["[calmly] The Ring is gone. Its burden with it."]},
        "lily": {"cast": ["[warmly] The One Ring, dears. Precious, isn't it?", "[mischievously] The Ring. I'll be drawing quite a bit."],
                 "react": ["[gasps] The Ring? Oh, that draws so many cards.", "[gently] Exile that Ring, dears. Destroying won't do."],
                 "gone": ["[softly] The Ring is gone. Free at last."]}},
    "The Tabernacle at Pendrell Vale": {
        "harry": {"cast": ["[shouting] Tabernacle! Pay for your creatures!", "[laughs] Tabernacle! Rent is due, every upkeep!"],
                  "react": ["[angry] Tabernacle?! I can't pay for all of these!", "[groans] Tabernacle. My whole board is a bill."],
                  "gone": ["[laughs] Tabernacle's gone! Free creatures again!"]},
        "bill": {"cast": ["[calmly] The Tabernacle. Upkeep, per creature.", "[dryly] Tabernacle. Creatures are a subscription now."],
                 "react": ["[sighs] The Tabernacle. My creatures cost a mana each.", "[dryly] Tabernacle. The token decks weep."],
                 "gone": ["[calmly] The Tabernacle is gone. Creatures are free again."]},
        "lily": {"cast": ["[warmly] The Tabernacle, dears. A mana per creature, please.", "[mischievously] Tabernacle. Rent, loves."],
                 "react": ["[gasps] Tabernacle? Oh, my poor tokens.", "[gently] That land needs removing, dears."],
                 "gone": ["[softly] The Tabernacle is gone. Freedom for the creatures."]}},
}

# ---- commanders: address slug -> {lib: {"cast": [..], "react": [..], "dead": [..]}} -----------
CMD = {
    "giada": {
        "harry": {"cast": ["[shouting] Giada! Angels grow up fast!", "[excited] Giada's here! Every angel comes in bigger!"],
                  "react": ["[angry] Giada?! Angels incoming! Brace!", "[scoffs] Giada. Cute angel. For now."],
                  "dead": ["[angry] They killed Giada! The angels will remember!"]},
        "bill": {"cast": ["[calmly] Giada. My angels arrive with counters.", "[dryly] Giada, Font of Hope. The angels follow."],
                 "react": ["[calmly] Giada. Every angel after her is larger.", "[dryly] Giada. The angel engine is online."],
                 "dead": ["[sighs] Giada has fallen. The angels grieve. I recast."]},
        "lily": {"cast": ["[warmly] Giada, dears. My angels will be magnificent.", "[gently] Here's Giada. Be kind to her, loves."],
                 "react": ["[gently] Giada, love? The angels come next.", "[softly] Watch her, dears. Angels grow behind her."],
                 "dead": ["[sighs] Giada's gone. I'll bring her home, dears."]}},
    "liberator": {
        "harry": {"cast": ["[shouting] Liberator! Flash! Surprise!", "[laughs] Liberator! Artifacts at instant speed!"],
                  "react": ["[angry] Liberator?! Now everything has flash!", "[scoffs] A thopter. A very annoying thopter."],
                  "dead": ["[angry] Liberator's down! I'll rebuild it!"]},
        "bill": {"cast": ["[calmly] Liberator. My artifacts have flash now.", "[dryly] Liberator. At flash speed, naturally."],
                 "react": ["[calmly] Liberator. Their artifacts arrive at instant speed.", "[dryly] The thopter. It grows with every spell."],
                 "dead": ["[sighs] Liberator is scrap. The commander tax rises."]},
        "lily": {"cast": ["[warmly] Liberator, dears. Flash, flying, and clever.", "[mischievously] Liberator. My toys come whenever I like."],
                 "react": ["[gently] Liberator, love? Flash artifacts. Hmm.", "[softly] That thopter grows, dears."],
                 "dead": ["[sighs] Liberator's gone. Poor little thopter."]}},
    "purphoros": {
        "harry": {"cast": ["[shouting] Purphoros! Every creature burns you all!", "[laughs] Purphoros, God of the Forge! Feel the heat!"],
                  "react": ["[angry] Purphoros?! Two damage per creature! Everyone!", "[shouting] Indestructible god! Exile it or die slowly!"],
                  "dead": ["[angry] Purphoros exiled?! The forge will burn again!"]},
        "bill": {"cast": ["[calmly] Purphoros. Two damage to each of you, per creature.", "[dryly] Purphoros. Indestructible. Do try."],
                 "react": ["[calmly] Purphoros. Every token is two damage to us all.", "[sighs] Purphoros. Only exile works. Inconvenient."],
                 "dead": ["[sighs] Purphoros is gone. The forge cools, briefly."]},
        "lily": {"cast": ["[warmly] Purphoros, dears. Every friend I make burns you.", "[mischievously] Purphoros. Indestructible, loves."],
                 "react": ["[gasps] Purphoros? That's two damage for everything.", "[gently] Exile the god, dears. Destroy won't do."],
                 "dead": ["[sighs] Purphoros is gone. He'll be back, dears."]}},
    "selvala": {
        "harry": {"cast": ["[shouting] Selvala! Big mana, big creatures!", "[laughs] Selvala's back! Mana for days!"],
                  "react": ["[angry] Selvala?! Kill it before it taps!", "[shouting] That elf makes ten mana! Ten!"],
                  "dead": ["[angry] Selvala's dead! The wilds will answer!"]},
        "bill": {"cast": ["[calmly] Selvala. Mana equal to my largest creature.", "[dryly] Selvala. The wilds provide."],
                 "react": ["[calmly] Selvala. Their biggest creature is their mana count.", "[sighs] Selvala. Untapped, she is a problem."],
                 "dead": ["[sighs] Selvala has fallen. The forest will recover."]},
        "lily": {"cast": ["[warmly] Selvala, dears. Nature's own mana.", "[gently] Here's Selvala. My biggest friend pays."],
                 "react": ["[gently] Selvala, love? That's a mana engine.", "[softly] Kill the elf before she taps, dears."],
                 "dead": ["[sighs] Selvala's gone. Back to the wilds."]}},
    "sheoldred": {
        "harry": {"cast": ["[shouting] Sheoldred! Everybody sacrifice something!", "[laughs] Sheoldred! Pick your victim!"],
                  "react": ["[angry] Sheoldred?! I have to sacrifice?! Argh!", "[groans] Sheoldred. Goodbye, best creature."],
                  "dead": ["[angry] Sheoldred's down! Phyrexia remembers!"]},
        "bill": {"cast": ["[calmly] Sheoldred. Each of you sacrifices a creature.", "[dryly] Sheoldred. Choose what you lose."],
                 "react": ["[sighs] Sheoldred. A sacrifice on arrival. Charming.", "[calmly] Sheoldred. Menace, and a saga waiting."],
                 "dead": ["[sighs] Sheoldred is gone. The Scriptures wait."]},
        "lily": {"cast": ["[warmly] Sheoldred, dears. Offer something up.", "[mischievously] Sheoldred. Choose wisely, loves."],
                 "react": ["[gasps] Sheoldred? Oh, I must sacrifice something.", "[gently] That praetor is trouble, dears."],
                 "dead": ["[sighs] Sheoldred's gone. She'll return, dears."]}},
    "rev": {
        "harry": {"cast": ["[shouting] Rev! Hit you, steal your cards!", "[laughs] Rev, Tithe Extractor! Pay up!"],
                  "react": ["[angry] Rev?! Stop stealing my library!", "[scoffs] Rev. Deathtouch on everything. Great."],
                  "dead": ["[angry] Rev's dead! The tithe still comes!"]},
        "bill": {"cast": ["[calmly] Rev. Combat damage takes your top card.", "[dryly] Rev. Deathtouch, Treasure, and theft."],
                 "react": ["[calmly] Rev. Every hit exiles a card they may cast.", "[dryly] Rev. Blocking is discouraged. Deathtouch."],
                 "dead": ["[sighs] Rev is gone. The extraction pauses."]},
        "lily": {"cast": ["[warmly] Rev, dears. A little tithe from each of you.", "[mischievously] Rev. I'll be borrowing your cards."],
                 "react": ["[gently] Rev, love? Mind your library.", "[softly] Deathtouch attackers, dears. Careful blocking."],
                 "dead": ["[sighs] Rev's gone. The tithe waits."]}},
    "sythis": {
        "harry": {"cast": ["[shouting] Sythis! Enchantments draw me cards!", "[laughs] Sythis! Every enchantment, a card!"],
                  "react": ["[angry] Sythis?! That's an enchantress! Kill it!", "[scoffs] Sythis. Cards for days."],
                  "dead": ["[angry] Sythis is dead! The harvest continues!"]},
        "bill": {"cast": ["[calmly] Sythis. Each enchantment draws a card.", "[dryly] Sythis. The engine, in the command zone."],
                 "react": ["[calmly] Sythis. Every enchantment is a cantrip now.", "[sighs] Sythis. Card advantage incarnate."],
                 "dead": ["[sighs] Sythis has fallen. The harvest resumes later."]},
        "lily": {"cast": ["[warmly] Sythis, dears. Every enchantment feeds me.", "[gently] Here's Sythis. The harvest begins."],
                 "react": ["[gently] Sythis, love? That's a card engine.", "[softly] Watch the enchantress, dears."],
                 "dead": ["[sighs] Sythis is gone. The field lies fallow."]}},
    "urza": {
        "harry": {"cast": ["[shouting] Urza! Artifacts are mana now!", "[laughs] Urza, Lord High Artificer! Construct, come!"],
                  "react": ["[angry] Urza?! Every artifact taps for blue!", "[shouting] Kill Urza! Kill it now!"],
                  "dead": ["[angry] Urza's down! The workshop rebuilds!"]},
        "bill": {"cast": ["[calmly] Urza. My artifacts tap for blue.", "[dryly] Urza. The Construct grows with every artifact."],
                 "react": ["[calmly] Urza. Their mana just doubled.", "[sighs] Urza. That must not survive a turn."],
                 "dead": ["[sighs] Urza has fallen. The artificer returns."]},
        "lily": {"cast": ["[warmly] Urza, dears. My artifacts have a purpose.", "[mischievously] Urza. Build me a Construct."],
                 "react": ["[gasps] Urza? Oh, that's a lot of mana, dear.", "[gently] Kill the artificer, dears. Quickly."],
                 "dead": ["[sighs] Urza's gone. The workshop grieves."]}},
    "y-shtola": {
        "harry": {"cast": ["[shouting] Y'shtola! Every big spell burns you!", "[laughs] Y'shtola's here! Feel the magic!"],
                  "react": ["[angry] Y'shtola?! Two damage per spell! Each of us!", "[scoffs] A cat warlock. Annoying cat."],
                  "dead": ["[angry] Y'shtola's down! She'll be back!"]},
        "bill": {"cast": ["[calmly] Y'shtola. My spells cost you two life each.", "[dryly] Y'shtola. Drain and draw. Efficient."],
                 "react": ["[calmly] Y'shtola. Every noncreature spell pings us all.", "[sighs] Y'shtola. Life loss and cards. Both."],
                 "dead": ["[sighs] Y'shtola has fallen. Night's blessing fades."]},
        "lily": {"cast": ["[warmly] Y'shtola, dears. My spells will sting a little.", "[gently] Here's Y'shtola. Vigilant and clever."],
                 "react": ["[gently] Y'shtola, love? Every spell burns us.", "[softly] Watch the warlock, dears."],
                 "dead": ["[sighs] Y'shtola is gone. She'll return, dears."]}},
}

# ---- combos: key -> {"sets": [[card names]...], lib: (online, react)} -------------------------
# The sets are the <=3-piece battlefield combos in the dossiers, grouped by shape.
COMBOS = {
    "scepter-reversal": {"sets": [["Isochron Scepter", "Narset's Reversal"]],
        "harry": ("[shouting] Scepter and Reversal! Infinite turns! Mine!", "[angry] Scepter Reversal! That's infinite turns! Stop them!"),
        "bill": ("[calmly] Scepter, Reversal. The turns are all mine now.", "[calmly] Scepter and Narset's Reversal. Infinite turns. End it."),
        "lily": ("[warmly] Scepter and Reversal, dears. I'll take every turn.", "[gasps] That's infinite turns, dears. We must break it.")},
    "dramatic-scepter": {"sets": [["Dramatic Reversal", "Isochron Scepter"]],
        "harry": ("[shouting] Dramatic Scepter! Infinite mana!", "[angry] Dramatic Scepter! Infinite mana! Kill the Scepter!"),
        "bill": ("[calmly] Dramatic Reversal, Scepter. Mana without end.", "[calmly] Dramatic Scepter. Infinite mana. Respond now."),
        "lily": ("[mischievously] Dramatic Scepter, dears. Round and round.", "[gasps] Dramatic Scepter? That's infinite mana, dears.")},
    "onslaught-terror": {"sets": [["Devastating Onslaught", "Terror of the Peaks"]],
        "harry": ("[shouting] Onslaught and Terror! Everyone burns!", "[angry] Onslaught with Terror of the Peaks! We're all dead!"),
        "bill": ("[calmly] Onslaught, Terror of the Peaks. Damage without end.", "[sighs] Terror and Onslaught. The damage is lethal. Respond."),
        "lily": ("[mischievously] Onslaught and Terror, dears. Do brace.", "[gasps] Terror and Onslaught? That's lethal, loves.")},
    "heliod-ballista": {"sets": [["Heliod, Sun-Crowned", "Walking Ballista"]],
        "harry": ("[shouting] Heliod Ballista! Infinite damage! You're all dead!", "[angry] Heliod and Ballista! Kill the Ballista! Now!"),
        "bill": ("[calmly] Heliod, Ballista. Infinite damage. Any objections?", "[calmly] Heliod and Ballista. Lethal for the table. Respond."),
        "lily": ("[warmly] Heliod and Ballista, dears. I'm terribly sorry.", "[gasps] Heliod with Ballista? That's the game, dears.")},
    "thune-ballista": {"sets": [["Archangel of Thune", "Walking Ballista"]],
        "harry": ("[shouting] Thune and Ballista! Infinite damage!", "[angry] Archangel and Ballista! That's infinite! Kill it!"),
        "bill": ("[calmly] Archangel of Thune, Ballista. Infinite damage.", "[calmly] Thune and Ballista. Lethal. Respond or lose."),
        "lily": ("[warmly] Thune and Ballista, dears. My apologies.", "[gasps] Thune with Ballista? Oh dear, that's the game.")},
    "excavation-weaver": {"sets": [["Meticulous Excavation", "Sanctum Weaver"]],
        "harry": ("[shouting] Excavation Weaver! Infinite loops!", "[angry] Excavation and Weaver! That loops forever!"),
        "bill": ("[calmly] Excavation, Weaver. The loop is complete.", "[calmly] Excavation and Sanctum Weaver. Infinite enters. Stop it."),
        "lily": ("[mischievously] Excavation and Weaver, dears. Round and round.", "[gasps] That loops forever, dears.")},
    "excavation-ring": {"sets": [["Meticulous Excavation", "The One Ring"]],
        "harry": ("[laughs] Excavation and the Ring! Can't touch me, ever!", "[angry] Ring and Excavation! They're untouchable forever!"),
        "bill": ("[calmly] Excavation, the Ring. Protection every turn.", "[sighs] The Ring and Excavation. Permanent protection. Tedious."),
        "lily": ("[warmly] Excavation and the Ring, dears. I'm quite safe now.", "[gently] They're untouchable every turn, dears.")},
    "drafna-ring": {"sets": [["Drafna, Founder of Lat-Nam", "The One Ring"]],
        "harry": ("[laughs] Drafna and the Ring! Protection every turn!", "[angry] Drafna bouncing the Ring! Untouchable forever!"),
        "bill": ("[calmly] Drafna, the Ring. Protection, every turn, indefinitely.", "[sighs] Drafna and the Ring. Permanent protection. Tiresome."),
        "lily": ("[warmly] Drafna and the Ring, dears. Quite safe, always.", "[gently] They can't be touched now, dears.")},
    "gauntlets-weaver": {"sets": [["Gauntlets of Light", "Sanctum Weaver"]],
        "harry": ("[shouting] Gauntlets Weaver! Infinite mana!", "[angry] Gauntlets on Weaver! Infinite mana! Kill it!"),
        "bill": ("[calmly] Gauntlets, Weaver. Mana without limit.", "[calmly] Gauntlets and Weaver. Infinite mana. Respond now."),
        "lily": ("[mischievously] Gauntlets and Weaver, dears. All the mana.", "[gasps] Infinite mana, dears. Kill the Weaver.")},
    "weaver-staff": {"sets": [["Sanctum Weaver", "Staff of Domination"]],
        "harry": ("[shouting] Weaver Staff! I draw everything!", "[angry] Weaver and Staff! Infinite draw! Stop them!"),
        "bill": ("[calmly] Weaver, Staff. I draw my deck.", "[calmly] Weaver and Staff of Domination. Infinite. Answer it."),
        "lily": ("[warmly] Weaver and Staff, dears. My whole library.", "[gasps] Staff on Weaver? They draw everything, dears.")},
    "weaver-mantle": {"sets": [["Sanctum Weaver", "Umbral Mantle"]],
        "harry": ("[shouting] Weaver Mantle! Infinite mana!", "[angry] Mantle on Weaver! Infinite mana! Kill it!"),
        "bill": ("[calmly] Weaver, Mantle. Mana without end.", "[calmly] Mantle and Weaver. Infinite mana. Respond."),
        "lily": ("[mischievously] Weaver and Mantle, dears. Endless mana.", "[gasps] Infinite mana, dears. The Weaver must go.")},
    "selvala-staff": {"sets": [["Selvala, Heart of the Wilds", "Staff of Domination"]],
        "harry": ("[shouting] Selvala and Staff! I draw my deck!", "[angry] Staff on Selvala! Infinite draw! Kill her!"),
        "bill": ("[calmly] Selvala, Staff. Infinite mana and cards.", "[calmly] Selvala and Staff of Domination. Infinite. Answer it."),
        "lily": ("[warmly] Selvala and Staff, dears. All my cards.", "[gasps] Staff on Selvala? Infinite, dears. Oh no.")},
    "selvala-mantle": {"sets": [["Selvala, Heart of the Wilds", "Umbral Mantle"]],
        "harry": ("[shouting] Selvala Mantle! Infinite mana!", "[angry] Mantle on Selvala! Infinite mana! Stop it!"),
        "bill": ("[calmly] Selvala, Mantle. Mana without end.", "[calmly] Mantle on Selvala. Infinite mana. Respond."),
        "lily": ("[mischievously] Selvala and Mantle, dears. Endless mana.", "[gasps] Infinite mana, dears. Kill the elf.")},
    "fanatic-mantle": {"sets": [["Fanatic of Rhonas", "Umbral Mantle"]],
        "harry": ("[shouting] Fanatic Mantle! Infinite green!", "[angry] Mantle on the Fanatic! Infinite mana!"),
        "bill": ("[calmly] Fanatic, Mantle. Infinite green mana.", "[calmly] Mantle on Fanatic of Rhonas. Infinite. Respond."),
        "lily": ("[mischievously] Fanatic and Mantle, dears. Green forever.", "[gasps] Infinite mana, dears.")},
    "dualcaster": {"sets": [["Dualcaster Mage", "Twinflame"], ["Devastating Onslaught", "Dualcaster Mage"]],
        "harry": ("[shouting] Dualcaster! Infinite hasty mages!", "[angry] Dualcaster loop! Infinite attackers! Blockers!"),
        "bill": ("[calmly] Dualcaster, copied. Infinite hasty mages. Attack.", "[calmly] Dualcaster Mage, looping. Infinite attackers. Lethal."),
        "lily": ("[mischievously] Dualcaster, dears. So many mages.", "[gasps] Infinite mages, dears. Oh no.")},
    "reiterate": {"sets": [["Jeska's Will", "Reiterate"], ["Mana Geyser", "Reiterate"]],
        "harry": ("[shouting] Reiterate, buyback! Infinite red mana!", "[angry] Reiterate with buyback! That's infinite mana!"),
        "bill": ("[calmly] Reiterate, buyback, again. Infinite red.", "[calmly] Reiterate with buyback. Infinite mana. Respond."),
        "lily": ("[mischievously] Reiterate, dears. Again and again.", "[gasps] That's infinite mana, dears.")},
    "top-chip": {"sets": [["Etherium Sculptor", "Sensei's Divining Top", "The Reality Chip"], ["Cloud Key", "Sensei's Divining Top", "The Reality Chip"],
                          ["Foundry Inspector", "Sensei's Divining Top", "The Reality Chip"]],
        "harry": ("[shouting] Top and Chip! I draw my deck!", "[angry] Top with the Chip! Infinite draw!"),
        "bill": ("[calmly] Top, Chip, a discount. My library becomes my hand.", "[calmly] Top and the Reality Chip. Infinite draw. End it."),
        "lily": ("[warmly] Top and Chip, dears. All my cards.", "[gasps] They'll draw everything, dears.")},
    "forge-top": {"sets": [["Foundry Inspector", "Mystic Forge", "Sensei's Divining Top"], ["Mystic Forge", "Sensei's Divining Top", "Ugin, the Ineffable"]],
        "harry": ("[shouting] Mystic Forge and Top! Infinite cards!", "[angry] Forge with Top! They draw the deck!"),
        "bill": ("[calmly] Mystic Forge, Top, and a discount. Infinite draw.", "[calmly] Forge and Top. Infinite draw. Answer it."),
        "lily": ("[warmly] Forge and Top, dears. Every card.", "[gasps] Forge and Top? They draw everything, dears.")},
    "cradle-satyr": {"sets": [["Gaea's Cradle", "Staff of Domination", "Voyaging Satyr"], ["Gaea's Cradle", "Umbral Mantle", "Voyaging Satyr"]],
        "harry": ("[shouting] Cradle and Satyr! Infinite!", "[angry] Satyr untapping Cradle! Infinite! Kill the Satyr!"),
        "bill": ("[calmly] Cradle, Satyr, untap. Infinite mana.", "[calmly] Satyr on Cradle. Infinite. Answer it."),
        "lily": ("[mischievously] Cradle and Satyr, dears. Endless.", "[gasps] Infinite from the Cradle, dears.")},
    "sabertooth": {"sets": [["Concordant Crossroads", "Sanctum Weaver", "Temur Sabertooth"], ["Concordant Crossroads", "Selvala, Heart of the Wilds", "Temur Sabertooth"],
                            ["Selvala, Heart of the Wilds", "Surrak and Goreclaw", "Temur Sabertooth"], ["Lightning Greaves", "Selvala, Heart of the Wilds", "Temur Sabertooth"]],
        "harry": ("[shouting] Sabertooth loop! Infinite!", "[angry] Sabertooth bouncing forever! Infinite! Stop it!"),
        "bill": ("[calmly] Sabertooth, bounce, replay. Infinite.", "[calmly] The Sabertooth loop. Infinite enters. Respond."),
        "lily": ("[mischievously] Sabertooth, dears. Round and round.", "[gasps] That loops forever, dears.")},
    "tezzeret-vault": {"sets": [["Lithoform Engine", "Mana Vault", "Tezzeret the Seeker"]],
        "harry": ("[shouting] Tezzeret, Vault, Lithoform! Infinite mana!", "[angry] Tezzeret untapping Vault with Lithoform! Infinite!"),
        "bill": ("[calmly] Tezzeret, Vault, Lithoform Engine. Infinite mana.", "[calmly] Lithoform, Tezzeret, Vault. Infinite. Respond."),
        "lily": ("[mischievously] Tezzeret, Vault and Lithoform, dears.", "[gasps] Infinite mana, dears.")},
    "lithoform-dramatic": {"sets": [["Dramatic Reversal", "Lithoform Engine"]],
        "harry": ("[shouting] Lithoform Dramatic Reversal! Infinite mana!", "[angry] Lithoform copying Reversal! Infinite!"),
        "bill": ("[calmly] Dramatic Reversal, Lithoform. Infinite mana.", "[calmly] Lithoform and Dramatic Reversal. Infinite. Respond."),
        "lily": ("[mischievously] Lithoform and Reversal, dears. Endless.", "[gasps] Infinite mana, dears.")},
    "mirror-warp": {"sets": [["Panoptic Mirror", "Time Warp"]],
        "harry": ("[shouting] Mirror and Time Warp! Infinite turns!", "[angry] Time Warp in the Mirror! Infinite turns! Break it!"),
        "bill": ("[calmly] Panoptic Mirror, Time Warp. Every turn is mine.", "[calmly] Time Warp imprinted. Infinite turns. Destroy the Mirror."),
        "lily": ("[warmly] Mirror and Time Warp, dears. I'll take all the turns.", "[gasps] Infinite turns, dears. Break the Mirror.")},
    "monolith-rings": {"sets": [["Forsaken Monument", "Grim Monolith", "Rings of Brighthearth"], ["Basalt Monolith", "Rings of Brighthearth"], ["Basalt Monolith", "Forsaken Monument"]],
        "harry": ("[shouting] Monolith untaps forever! Infinite mana!", "[angry] Monolith with Rings! Infinite colourless!"),
        "bill": ("[calmly] Monolith, untap, again. Infinite colourless.", "[calmly] Monolith and Rings. Infinite mana. Respond."),
        "lily": ("[mischievously] Monolith and Rings, dears. Endless mana.", "[gasps] Infinite mana, dears.")},
    "power-artifact": {"sets": [["Grim Monolith", "Power Artifact"], ["Basalt Monolith", "Power Artifact"]],
        "harry": ("[shouting] Power Artifact on Monolith! Infinite mana!", "[angry] Power Artifact Monolith! Infinite!"),
        "bill": ("[calmly] Monolith, Power Artifact. Infinite colourless.", "[calmly] Power Artifact on Monolith. Infinite mana. Respond."),
        "lily": ("[mischievously] Monolith and Power Artifact, dears.", "[gasps] Infinite mana, dears.")},
    "basalt-gadgeteer": {"sets": [["Basalt Monolith", "Forensic Gadgeteer"]],
        "harry": ("[shouting] Gadgeteer Monolith! Infinite mana!", "[angry] Gadgeteer with Basalt! Infinite mana!"),
        "bill": ("[calmly] Basalt Monolith, Gadgeteer. Infinite colourless.", "[calmly] Gadgeteer and Basalt. Infinite mana. Respond."),
        "lily": ("[mischievously] Monolith and Gadgeteer, dears.", "[gasps] Infinite mana, dears.")},
    "earthcraft-ascension": {"sets": [["Earthcraft", "Luminarch Ascension", "Wild Growth"], ["Earthcraft", "Luminarch Ascension", "Mirari's Wake"],
                                      ["Earthcraft", "Luminarch Ascension", "Nyxbloom Ancient"], ["Earthcraft", "Luminarch Ascension", "Utopia Sprawl"]],
        "harry": ("[shouting] Earthcraft Ascension! Infinite angels!", "[angry] Earthcraft with Ascension! Infinite angels!"),
        "bill": ("[calmly] Earthcraft, Ascension, an enchanted land. Infinite angels.", "[calmly] Earthcraft and Ascension. Infinite angels. Respond."),
        "lily": ("[warmly] Earthcraft and Ascension, dears. Angels forever.", "[gasps] Infinite angels, dears. Oh my.")},
    "spiritdancer-arcade": {"sets": [["Ondu Spiritdancer", "Secret Arcade // Dusty Parlor"]],
        "harry": ("[shouting] Spiritdancer Arcade! Infinite copies!", "[angry] Spiritdancer with the Arcade! Infinite!"),
        "bill": ("[calmly] Spiritdancer, Secret Arcade. Infinite enters.", "[calmly] Spiritdancer and the Arcade. Infinite. Respond."),
        "lily": ("[mischievously] Spiritdancer and Arcade, dears. Endless.", "[gasps] That loops forever, dears.")},
    "ignus-steamkin": {"sets": [["Grinning Ignus", "Runaway Steam-Kin"]],
        "harry": ("[shouting] Ignus and Steam-Kin! Infinite enters!", "[angry] Ignus with Steam-Kin! Infinite! Purphoros!"),
        "bill": ("[calmly] Ignus, Steam-Kin. Infinite enters. Purphoros approves.", "[calmly] Ignus and Steam-Kin. Infinite triggers. Fatal."),
        "lily": ("[mischievously] Ignus and Steam-Kin, dears. Round and round.", "[gasps] Infinite enters, dears. Oh no.")},
    "karn-reservoir": {"sets": [["Aetherflux Reservoir", "Karn, the Great Creator"]],
        "harry": ("[shouting] Karn and Reservoir! Fifty damage!", "[angry] Karn Reservoir! That's lethal!"),
        "bill": ("[calmly] Karn, Reservoir. The laser is loaded.", "[calmly] Karn and Reservoir. Lethal. Respond."),
        "lily": ("[warmly] Karn and Reservoir, dears. Sorry about the laser.", "[gasps] Karn with Reservoir? That's fifty, dears.")},
    "hullbreaker": {"sets": [["Hullbreaker Horror", "Mana Vault"], ["Hullbreaker Horror", "Mox Amber"], ["Hullbreaker Horror", "Sol Ring"]],
        "harry": ("[shouting] Hullbreaker and a rock! Infinite!", "[angry] Hullbreaker with a rock! Infinite! Kill the Horror!"),
        "bill": ("[calmly] Hullbreaker, one rock. Bounce, replay, forever.", "[calmly] Hullbreaker Horror with a rock. Infinite. Respond."),
        "lily": ("[mischievously] Hullbreaker and a rock, dears. Endless.", "[gasps] Hullbreaker loop, dears. Kill the Horror.")},
    "tidespout": {"sets": [["Mana Vault", "Tidespout Tyrant"], ["Grim Monolith", "Tidespout Tyrant"], ["Mox Amber", "Tidespout Tyrant"],
                           ["Mox Opal", "Tidespout Tyrant"], ["Sol Ring", "Tidespout Tyrant"]],
        "harry": ("[shouting] Tidespout and a rock! Infinite!", "[angry] Tidespout with a rock! Infinite! Kill the Tyrant!"),
        "bill": ("[calmly] Tidespout, one rock. Bounce, replay, forever.", "[calmly] Tidespout Tyrant with a rock. Infinite. Respond."),
        "lily": ("[mischievously] Tidespout and a rock, dears. Endless.", "[gasps] Tidespout loop, dears. Kill the Tyrant.")},
    "metalworker": {"sets": [["Metalworker", "Staff of Domination"], ["Metalworker", "Rings of Brighthearth", "Voltaic Key"]],
        "harry": ("[shouting] Metalworker! Infinite mana!", "[angry] Metalworker untapping! Infinite mana! Kill it!"),
        "bill": ("[calmly] Metalworker, untap, again. Infinite colourless.", "[calmly] Metalworker with an untap. Infinite mana. Respond."),
        "lily": ("[mischievously] Metalworker, dears. Endless mana.", "[gasps] Infinite mana, dears. Kill the Metalworker.")},
    "mikaeus-altar": {"sets": [["Ashnod's Altar", "Mikaeus, the Unhallowed"], ["Mikaeus, the Unhallowed", "Phyrexian Altar"]],
        "harry": ("[shouting] Mikaeus and an Altar! Infinite mana!", "[angry] Mikaeus with an Altar! Infinite! Kill Mikaeus!"),
        "bill": ("[calmly] Mikaeus, an Altar, undying. Infinite mana.", "[calmly] Mikaeus and an Altar. Infinite. Respond."),
        "lily": ("[mischievously] Mikaeus and the Altar, dears. Endless.", "[gasps] Mikaeus loop, dears. Kill him.")},
    "mikaeus-ballista": {"sets": [["Mikaeus, the Unhallowed", "Walking Ballista"]],
        "harry": ("[shouting] Mikaeus Ballista! Infinite damage!", "[angry] Mikaeus and Ballista! Infinite damage! Now!"),
        "bill": ("[calmly] Mikaeus, Ballista. Infinite damage.", "[calmly] Mikaeus and Ballista. Lethal. Respond."),
        "lily": ("[warmly] Mikaeus and Ballista, dears. I'm so sorry.", "[gasps] Mikaeus with Ballista? That's the game, dears.")},
    "ascension-mindcrank": {"sets": [["Bloodchief Ascension", "Mindcrank"]],
        "harry": ("[shouting] Ascension Mindcrank! Mill everyone!", "[angry] Ascension and Mindcrank! We all get milled!"),
        "bill": ("[calmly] Bloodchief Ascension, Mindcrank. Infinite mill.", "[calmly] Ascension and Mindcrank. Infinite mill. Respond."),
        "lily": ("[mischievously] Ascension and Mindcrank, dears. Goodbye, libraries.", "[gasps] Infinite mill, dears. Oh no.")},
    "temple-ruins": {"sets": [["Deserted Temple", "Rings of Brighthearth", "Scorched Ruins"]],
        "harry": ("[shouting] Temple, Rings, Ruins! Infinite mana!", "[angry] Temple untapping Ruins with Rings! Infinite!"),
        "bill": ("[calmly] Temple, Rings, Scorched Ruins. Infinite colourless.", "[calmly] Temple, Rings, Ruins. Infinite mana. Respond."),
        "lily": ("[mischievously] Temple, Rings and Ruins, dears.", "[gasps] Infinite mana, dears.")},
}


# ---- the record on disk ----------------------------------------------------------------------
def deck_files():
    return [d for d in sorted(DECKS.iterdir()) if (d / "dossier" / "deck-cards.json").exists()] if DECKS.exists() else []


def game_changers_on_disk() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for d in deck_files():
        for c in json.loads((d / "dossier" / "deck-cards.json").read_text()).get("cards") or []:
            if isinstance(c, dict) and c.get("game_changer") and c.get("name"):
                out.setdefault(str(c["name"]), c)
    return out


def commanders_on_disk() -> dict[str, str]:
    """deck slug -> address slug (voices/address.json, written by table_lines.py)."""
    try:
        addr = json.loads((VOICES / "address.json").read_text())
    except (OSError, ValueError):
        return {}
    return {deck: c["who"] for deck, c in (addr.get("commanders") or {}).items()}


def combos_on_disk() -> dict[frozenset, list[str]]:
    """frozenset(front-face names) -> decks, for every <=3-piece battlefield combo."""
    out: dict[frozenset, list[str]] = {}
    for d in deck_files():
        f = d / "dossier" / "combos.json"
        if not f.exists():
            continue
        for cb in json.loads(f.read_text()).get("combos") or []:
            cards = cb.get("cards") or []
            if len(cards) > 3 or any(c.get("zone_req", "battlefield") != "battlefield" for c in cards):
                continue
            key = frozenset(str(c["name"]) for c in cards)
            out.setdefault(key, []).append(d.name)
    return out


def combo_index() -> dict[frozenset, str]:
    idx: dict[frozenset, str] = {}
    for key, info in COMBOS.items():
        for s in info["sets"]:
            idx[frozenset(s)] = key
    return idx


def coverage() -> list[str]:
    problems = []
    disk_gc = game_changers_on_disk()
    for name in disk_gc:
        if name not in GC:
            problems.append(f"game changer without lines: {name!r}")
    for name in GC:
        if name not in disk_gc:
            problems.append(f"lines for a game changer no deck carries: {name!r}")
    for deck, who in commanders_on_disk().items():
        if who not in CMD:
            problems.append(f"commander without lines: {who!r} ({deck})")
    idx = combo_index()
    for key, decks in combos_on_disk().items():
        if key not in idx:
            problems.append(f"combo without lines: {sorted(key)} ({', '.join(decks)})")
    for k, info in COMBOS.items():
        for lib in LIBS:
            if len(_combo(info, lib, k)) != 2:
                problems.append(f"combo {k}: {lib} needs (online, react)")
    return problems


def render_block(lib: str) -> dict:
    parent = json.loads((VOICES / lib / "manifest.json").read_text())
    return {k: parent[k] for k in ("voice_id", "voice_name", "temperament", "render", "bake", "sample_rate", "tags_note", "fx_chain_file") if k in parent}


def build_manifest(lib: str) -> dict:
    m = {"schema": "arena.voice-stock/1", "library": f"{lib}/cards", "parent": lib, "seat": None,
         "note": ("the cards sub-library (round 31): game changers, commanders and combos by name, grounded in the oracle text on record; "
                  "regenerate with runner/voice/card_lines.py --write"),
         **render_block(lib), "phrases": {}}
    ph = m["phrases"]
    disk_gc = game_changers_on_disk()
    for name, by in GC.items():
        slug = card_slug(name)
        oracle = str((disk_gc.get(name) or {}).get("oracle_text") or "")[:140]
        for part, when in (("cast", "casts it"), ("react", "sees another seat cast it"), ("gone", "sees it leave the battlefield (someone else's)")):
            ph[f"gc-{slug}-{part}"] = {"category": "card", "card": name, "when": f"{when}: {name} — {oracle}", "text": _gc(by, lib, name, part), "source": "cards-2026-09-10"}
    for who, by in CMD.items():
        for part, when in (("cast", "casts its commander"), ("react", "sees another seat cast its commander"), ("dead", "its commander left the battlefield")):
            ph[f"cmd-{who}-{part}"] = {"category": "commander", "card": who, "when": f"{when}: {who}", "text": _cmd(by, lib, who, part), "source": "cards-2026-09-10"}
    for key, info in COMBOS.items():
        online, react = _combo(info, lib, key)
        pieces = " / ".join(" + ".join(s) for s in info["sets"])
        ph[f"combo-{key}-online"] = {"category": "combo", "card": key, "when": f"the last piece landed on its battlefield: {pieces}", "text": [online], "source": "cards-2026-09-10"}
        ph[f"combo-{key}-react"] = {"category": "combo", "card": key, "when": f"sees another seat assemble it: {pieces}", "text": [react], "source": "cards-2026-09-10"}
    return m


def write_all() -> None:
    for lib in LIBS:
        d = VOICES / lib / "cards"
        d.mkdir(parents=True, exist_ok=True)
        m = build_manifest(lib)
        try:
            old = json.loads((d / "manifest.json").read_text())
            if old.get("baked"):
                m["baked"] = old["baked"]                        # the library's measured gain survives a rewrite (as table_lines does)
        except (OSError, ValueError):
            pass
        (d / "manifest.json").write_text(json.dumps(m, indent=1, ensure_ascii=False) + "\n")
    (VOICES / "combos.json").write_text(json.dumps({
        "schema": "arena.voice-combos/1",
        "note": ("combo line keys -> the card sets (front-face names, all on the battlefield) that complete them; the voice runner "
                 "matches a seat's battlefield against its deck's combos.json and says combo-<key>-online / -react. "
                 "Regenerate with runner/voice/card_lines.py --write."),
        "combos": {key: [sorted(s) for s in info["sets"]] for key, info in COMBOS.items()},
    }, indent=1, ensure_ascii=False) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    problems = coverage()
    for p in problems:
        print("[card_lines] COVERAGE:", p)
    n = chars = 0
    for lib in LIBS:
        for ph in build_manifest(lib)["phrases"].values():
            n += len(ph["text"]); chars += sum(len(t) for t in ph["text"])
    print(f"{len(build_manifest('harry')['phrases'])} ids per voice: {len(GC)} game changers x5, {len(CMD)} commanders x5, {len(COMBOS)} combo shapes x2 "
          f"-> {n} lines across three voices, {chars} characters")
    if problems and a.write:
        sys.exit("[card_lines] fix the coverage gaps before writing")
    if a.write:
        write_all()
        print("written:", ", ".join(str(VOICES / lib / "cards" / "manifest.json") for lib in LIBS), "and", VOICES / "combos.json")


if __name__ == "__main__":
    main()
