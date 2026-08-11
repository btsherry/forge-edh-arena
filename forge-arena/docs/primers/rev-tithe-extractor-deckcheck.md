# Rev, Tithe Extractor — Strategy Primer

*Mono-black evasive-aggro built on Treasures, theft, sacrifice, and big-mana
drain. You win by connecting with hard-to-block creatures, snowballing the
resources that connection generates, and converting that lead into a drain or a
voltron kill. Every line in the deck feeds "make an unblockable creature hit a
face."*

## The commander

**Rev, Tithe Extractor** — {3}{B}, and the whole deck is her support structure.
- **On attack:** target creature gains **deathtouch** until end of turn. Use it
  to make a chump-block suicidal, to trade up, or to turn any attacker into a
  removal threat. It's a *combat lever*, not a wincon — deploy it to force damage
  through, not for its own sake.
- **On combat damage to a player:** create a **Treasure**, then look at the top
  card of *that player's* library and **exile it face down — you may cast it**
  while exiled. This triggers **once per player hit**, batched over all your
  creatures. So the payoff scales with how many *different players* you connect
  with, not how many creatures — a single unblockable creature that hits all
  three opponents is three Treasures and three stolen cards. Evasion + going wide
  across the pod is the maximizer.

**Read this first:** Rev is a value/tempo engine, and the deck is an
aggro-combo. You are not durdling to a single infinite; you are grinding an
evasive advantage and then closing with one of several drain/voltron finishes.
Protect Rev, keep a body connecting, and don't over-commit into a wrath.

## Subthemes (the play patterns to internalize)

**1. Evasion (the enabler — this is the deck's spine).** Nearly every creature is
built to connect: **Changeling Outcast** (can't be blocked), **Dauthi
Voidwalker / Nether Traitor / Vashta Nerada** (shadow — effectively
unblockable), **Vault Skirge / Bitterblossom Faeries / Deep-Cavern Bat / Oona's
Blackguard** (flying), **Vampire Cutthroat** (skulk), and a menace suite
(**Blackbloom Rogue, Rapacious Guest, Snarling Gorehound, Stalactite Stalker**).
Two grant-evasion enablers matter a lot: **Shadow Alley Denizen** (a black
creature ETB grants intimidate — chain these to push a big threat through) and
**Shizo, Death's Storehouse** (fear onto a legendary — i.e., onto Rev herself).
Prioritize keeping *one* reliable connector online at all times; that's what
turns the engine.

**2. Treasure / wealth.** Rev makes Treasures on connect; **Grim Hireling**
doubles it (two per player hit), **Academy Manufactor** turns each Treasure into
Treasure+Clue+Food, **Sword of Wealth and Power** and **Mastermind Plum** add
more, **Warren Soultrader** and **Treasure Vault** manufacture them from
sacrifice/mana, and **Rapacious Guest** spins Food into counters. Treasures are
not just ramp — they power **Cranial Plating**, fuel **Cabal Coffers** turns,
enable **Beseech the Mirror**'s bargain, and are the payoff cards for
**Revel in Riches** (win at 10 Treasures — a real alternate line here).

**3. Theft.** A genuine, committed subtheme, not incidental: Rev steals the top
of each hit player's library; **Tinybones, the Pickpocket** and **Nashi, Moon
Sage's Scion** cast from opponents' graveyards/decks; **Dauthi Voidwalker**
exiles their graveyard and lets you cast one for free; **Deep-Cavern Bat** strips
a card from hand; **Thieving Varmint** makes mana *specifically to cast spells
you don't own*. When you connect, actually spend the stolen cards — the extra
resources are how you out-grind a three-player table.

**4. Sacrifice / aristocrats.** **Grave Pact** turns any creature death into a
table-wide edict; feed it with token generators (**Bitterblossom**, **Jadar**'s
decayed zombies) and free sac outlets (**Warren Soultrader**, **Phyrexian
Tower**, **Braids, Arisen Nightmare**). **Nadier's Nightblade** drains 1 per
token that leaves — with Bitterblossom + a sac outlet that's a per-turn drain
clock. **Morbid Opportunist** and **Mari, the Killing Quill** convert the death
churn into cards/value. **Braids** is a soft-stax edict engine that favors you
because you have tokens to feed it and opponents don't.

**5. Reanimation.** **Necromancy** (flash), **Chthonian Nightmare** (energy
loop), **Agadeem's Awakening** (mass, scalable), **Balthor the Defiled** (mass
black/red), and **Finale of Eternity** (X≥10 returns your yard) recur your best
bodies — usually **Gray Merchant of Asphodel** for a repeatable drain, or a
threat after a wipe. **Yawgmoth's Will** replays your whole graveyard (rituals,
tutors, drains) and is frequently the setup turn for a kill.

**6. Big-mana drain (the primary kill).** **Cabal Coffers + Urborg, Tomb of
Yawgmoth** (every land becomes a Swamp) taps for enormous black; **Nykthos** and
**K'rrik, Son of Yawgmoth** (pay life instead of {B}) multiply it further. Dump
it into **Exsanguinate**, **Gray Merchant** (mono-black = huge devotion), or
**Finale of Eternity** to drain the table in one turn. K'rrik + a ritual + a big
drain is the deck's most explosive sequence — it can end games from an empty
board.

## Signature synergy lines (combos.json is empty by design — this is a value
deck, but these are the engines to assemble)

- **Bitterblossom + Skullclamp** → clamp a 1/1 Faerie (→2/0, dies) for 2 cards
  every turn; add **Nadier's Nightblade** and each clamped/sacrificed token also
  drains the table. Add **Grave Pact** and each token death edicts the pod. This
  three-to-four-card web is the aristocrats heart.
- **Warren Soultrader + Grave Pact + any token source** → sacrifice for Treasures
  *and* pod-wide edicts, repeatably; with Nadier it also drains.
- **K'rrik + Dark Ritual / Cabal Coffers → Exsanguinate / Gray Merchant** → the
  drain kill. Watch your life total (K'rrik and the pay-life cards make you the
  clock on yourself).
- **Cranial Plating + an unblockable body (Changeling Outcast / Vault Skirge)** →
  with a few artifacts/Treasures out, a lethal unblockable swing that also fires
  Rev's Treasure/theft trigger.
- **Hatred / Sword of Feast and Famine on an unblockable creature** → one-shot
  voltron damage (Hatred) or untap-your-lands tempo + discard (Feast and Famine),
  both on a creature that can't be blocked.
- **Revel in Riches** → with your Treasure generation plus opponents' creatures
  dying (Grave Pact, Mari, removal), the 10-Treasure alternate win is reachable.
- **Yawgmoth's Will** → replay rituals + tutors + drains for an explosive,
  often-lethal turn.

## Mulligan

Keep hands that can (a) deploy an early evasive body or Rev-enabler, or (b) ramp
fast (Sol Ring, Dark Ritual, K'rrik, Jet Medallion) toward the Coffers/drain
plan — with 2–3 lands. **Bitterblossom** is a premium keep (a standalone engine).
The Coffers/Urborg/Nykthos package keeps if you have the lands to support it.
Ship no-pressure, all-top-end hands: this deck wants to be doing something by
turn 2–3.

## Threat assessment & interaction

- **Protect Rev and your connector:** **Lightning Greaves / Swiftfoot Boots**
  (hexproof/haste), **Malakir Rebirth** (save a key creature), **Imp's Mischief**
  (redirect a removal spell or counter off your commander — or onto a rival's
  combo). **Deadly Rollick** is free removal while you control a commander — hold
  it for the scariest threat, not the first creature.
- **Sweepers** (**Toxic Deluge, Mutilate, Finale of Eternity**) hit your board
  too — use them when behind, and remember you can rebuild via reanimation.
- **Graveyard hate + disruption:** **Dauthi Voidwalker** shuts off opposing
  recursion (and steals), **Sheoldred**'s ETB edicts and can flip to a
  mass-reanimation/wrath Saga, **Braids** pressures durdle decks.
- Don't race a life total you can't win: your own pay-life cards (K'rrik, Toxic
  Deluge, Hatred, Bitterblossom, phyrexian mana) make *you* fragile. Sequence
  drains and lifelink (Vault Skirge, Barrowgoyf, Vampire Cutthroat, Deep-Cavern
  Bat, Elegy Acolyte) to stay ahead.

## Closing — win conditions, ranked

1. **Big-mana drain:** Coffers/Urborg/K'rrik → Exsanguinate / Gray Merchant /
   Finale. The most reliable kill; often from a near-empty board.
2. **Evasive voltron:** Changeling Outcast / Vault Skirge + Cranial Plating /
   Swords / Hatred / Anduril + Rev's deathtouch — lethal beats plus engine value.
3. **Aristocrats grind:** Bitterblossom + Nadier + Skullclamp/Grave Pact for
   incremental drain and card advantage, then a drain spell to finish.
4. **Revel in Riches** (10 Treasures) — a real backup the Treasure engine reaches.

**Turn shape:** deploy an evasive body + Rev early → connect for Treasures/theft
→ ramp into Coffers/K'rrik while protecting Rev → pressure the pod with
Braids/Grave Pact → close with a drain or a voltron swing. Hold your free
interaction (Deadly Rollick, Imp's Mischief) for the moment that decides the
game.
