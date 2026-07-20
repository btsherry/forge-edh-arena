#!/usr/bin/env python3
"""PROTOTYPE for Phase 9 PR-A: extract capabilities from Forge card SCRIPTS
rather than oracle prose, and measure the coverage lift.

Throwaway. Its only job is to answer: how much of the 60-83% blind spot does
the structured script close, with zero LLM and zero hallucination?
"""
import json
import re
import sys
from pathlib import Path
from collections import Counter

ROOT = Path("/Users/toor/Claude/personal/forge-edh-arena")
CARDS = ROOT / "forge-gui/res/cardsfolder"

_index = {}


def script_for(name: str):
    """Find a card's script file. Forge lays them out a/, b/, ... by letter."""
    if not _index:
        for p in CARDS.rglob("*.txt"):
            _index[p.stem] = p
    key = (name.split("//")[0].strip().lower()
           .replace(",", "").replace("'", "").replace("-", "_")
           .replace(" ", "_").replace(".", "").replace("!", ""))
    return _index.get(key)


def capabilities(text: str):
    """Structured capabilities from a Forge card script. Facts, not guesses."""
    caps = set()
    a_lines = [l for l in text.splitlines() if l.startswith(("A:", "SVar:", "T:", "K:", "R:", "S:"))]
    blob = "\n".join(a_lines)

    # --- the one that made Urza invisible ---
    if "MayPlayWithoutManaCost$ True" in blob:
        caps.add("free_cast_grant")
    if "MayPlay$ True" in blob and "MayPlayWithoutManaCost$ True" not in blob:
        caps.add("alternate_play_grant")

    # --- mana ---
    for m in re.finditer(r"A:AB\$ Mana \|([^\n]*)", blob):
        body = m.group(1)
        # A self-bouncing mana ability (Grinning Ignus: Return<1/CARDNAME>)
        # is NOT a repeatable mana source — a subagent flagged that tagging
        # it mana_ability "would imply a false infinite-mana loop", i.e. the
        # extractor would have invented a phantom combo.
        if "Return<1/CARDNAME>" in body:
            caps.add("self_bounce_mana_ability")
            continue
        amt = re.search(r"Amount\$ (\w+)", body)
        caps.add("mana_ability")
        if amt and amt.group(1).isdigit() and int(amt.group(1)) >= 2:
            caps.add("mana_ability_big")
        if amt and not amt.group(1).isdigit():
            caps.add("mana_ability_variable")

    # --- damage / drain outlets ---
    if re.search(r"AB\$ DealDamage", blob):
        caps.add("damage_outlet")
        if "ValidTgts$ Any" in blob or "ValidTgts$ Player" in blob:
            caps.add("damage_any_target")
        if "Defined$ Player.Opponent" in blob or "ValidTgts$ Opponent" in blob:
            caps.add("damage_each_opponent")
    if re.search(r"AB\$ LoseLife", blob):
        caps.add("lifeloss_outlet")
    if re.search(r"AB\$ GainLife", blob):
        caps.add("lifegain")
    # Only OUR life. Subagent finding: Terror of the Peaks carries
    # PayLife<3> inside a RaiseCost static with Activator$ Player.Opponent
    # — it TAXES opponents, it does not cost us life. Matching PayLife
    # anywhere in the script inverted the card's meaning.
    for line in a_lines:
        if re.search(r"Cost\$[^|\n]*PayLife<", line) and "Player.Opponent" not in line:
            caps.add("life_cost_ability")

    # --- card flow ---
    if re.search(r"AB\$ Draw", blob):
        caps.add("draw")
    if re.search(r"AB\$ (ChangeZone|Dig)[^\n]*Origin\$ Library", blob):
        caps.add("tutor_or_dig")
    if re.search(r"AB\$ Mill", blob):
        caps.add("mill")

    # --- board manipulation ---
    if re.search(r"AB\$ Untap", blob):
        caps.add("untap")
    if re.search(r"AB\$ DestroyAll|AB\$ DamageAll|AB\$ WipeAll", blob):
        caps.add("board_wipe")
    elif re.search(r"AB\$ Destroy|AB\$ Exile\b", blob):
        caps.add("targeted_removal")
    if re.search(r"AB\$ Token", blob):
        caps.add("token_maker")
    if re.search(r"AB\$ Pump|AB\$ PumpAll", blob):
        caps.add("pump")
        if "PumpAll" in blob:
            caps.add("mass_pump")
    if re.search(r"AB\$ Copy(SpellAbility|Permanent)", blob):
        caps.add("copy_effect")
    if re.search(r"AB\$ Counter\b", blob):
        caps.add("counterspell")

    # --- triggers: the engine hooks combos feed on ---
    if re.search(r"T:Mode\$ SpellCast", blob):
        caps.add("cast_trigger")
    if re.search(r"T:Mode\$ ChangesZone[^\n]*Destination\$ Battlefield", blob):
        caps.add("etb_trigger")
    if re.search(r"T:Mode\$ (Attacks|AttackerBlocked)", blob):
        caps.add("attack_trigger")
    if re.search(r"T:Mode\$ Phase[^\n]*Upkeep", blob):
        caps.add("upkeep_trigger")

    # --- static / cost reduction ---
    if "ReduceCost$" in blob or "CostAdjustment" in blob:
        caps.add("cost_reducer")
    if re.search(r"K:Haste", blob):
        caps.add("has_haste")
    if re.search(r"AB\$ (Effect|Animate)[^\n]*Haste", blob) or "AddKeyword$ Haste" in blob:
        caps.add("haste_granter")

    # --- alternate win / loss protection ---
    if "AB$ WinsGame" in blob or "WinsGame" in blob:
        caps.add("alt_win")
    if "CantLoseForZeroOrLessLife" in blob or "SkipLoseGame" in blob:
        caps.add("cant_lose")

    # Repeatable = a genuinely ACTIVATED ability. Subagent finding: the
    # A: prefix covers both "A:AB$" (activated) and "A:SP$" (a spell
    # ability on an instant/sorcery). Tagging the latter invited the
    # executor to try activating a sorcery from the battlefield.
    if any(l.startswith("A:AB$") for l in a_lines):
        caps.add("has_activated_ability")
    return caps


def main():
    decks = ["urza-lord-high-artificer", "selvala-heart-of-the-wilds",
             "purphoros-god-of-the-forge", "giada-font-of-hope"]
    all_caps = Counter()
    print(f"{'deck':32} {'nonland':>7} {'old':>5} {'NEW':>5} {'still blind':>12}")
    for deck in decks:
        d = ROOT / f"forge-arena/decks/{deck}/dossier"
        cards = json.load(open(d / "deck-cards.json"))
        cards = cards if isinstance(cards, list) else cards.get("cards", [])
        pay = json.load(open(d / "route-coverage.json")).get("deck", {}).get("payoffs", {})
        tagged = {n for v in pay.values() for n in v}
        combos = json.load(open(d / "combos.json")).get("combos", [])
        incombo = {(c.get("name") if isinstance(c, dict) else c)
                   for x in combos for c in (x.get("cards") or [])}
        old_known = tagged | incombo

        nonland = [c for c in cards if isinstance(c, dict)
                   and "Land" not in (c.get("type_line") or "")]
        new_known, missing = set(), []
        for c in nonland:
            name = c.get("name")
            p = script_for(name)
            if not p:
                missing.append(f"{name} (no script found)")
                continue
            caps = capabilities(p.read_text(errors="replace"))
            if caps - {"has_activated_ability"}:
                new_known.add(name)
                all_caps.update(caps)
            else:
                missing.append(f"{name} (script parsed, no capability matched)")

        n = len(nonland)
        old_blind = n - len({c.get("name") for c in nonland} & old_known)
        new_blind = n - len(new_known | ({c.get("name") for c in nonland} & old_known))
        print(f"{deck:32} {n:7} {n-old_blind:5} {n-new_blind:5} {new_blind:12}")
        if deck == decks[0]:
            urza = script_for("Urza, Lord High Artificer")
            print(f"    URZA CAPABILITIES: {sorted(capabilities(urza.read_text()))}")
        if missing[:3]:
            for m in missing[:3]:
                print(f"      still blind: {m}")
    print(f"\ntop capabilities found across all four decks:")
    for c, k in all_caps.most_common(14):
        print(f"   {c:26} {k}")


if __name__ == "__main__":
    main()
