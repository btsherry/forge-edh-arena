To build a headless AI pilot for a 4-player Commander simulator, you need machine-readable, rules-enforced, turn-by-turn state transitions (mana floating, stack resolutions, exact targeting). Most Magic: The Gathering data available online focuses on *decklists* or *match outcomes*, not granular gameplay. 

Here is the deep research report on the feasibility, granularity, and acquisition of real EDH game data.

---

### 1. PlayEDH.com
* **What it is:** PlayEDH is a massive Discord-based community for playing paper Commander over webcams. They use a custom Discord bot (SpellBot) for matchmaking and have a Patreon-gated deck-checking system to enforce power levels (Battlecruiser, Low, Mid, High, cEDH).
* **Per-game data:** **NO turn-by-turn data.** Because games are played in paper via webcam (usually on SpellTable), there is no digital rules engine tracking board states, life totals, or card movements. 
* **API / Scraping:** There is no public API. Scraping their Discord server for match results violates Discord’s Terms of Service. 
* **Finding a Selvala win:** **Impossible for game logs.** You can search their Discord for "Selvala" to find decklists that passed their power-level checks, but you cannot find a turn-by-turn log of a game where Selvala won.

---

### 2 & 3. Other Repositories & Source Details

#### Sources with NO Turn-by-Turn Data (Outcomes & Decklists Only)
* **SpellTable:** Owned by Wizards of the Coast (WotC). It processes video feeds and life totals but does not record or expose game logs or card recognition data.
* **Moxfield / Archidekt / EDHREC:** These are deckbuilding and aggregation sites. Their "playtest" features do not record multiplayer games. They have zero turn-by-turn data.
* **cEDH Tournament Data (Eminence, edhtop16.com, Command Tower):** These track competitive EDH tournament results. They have APIs (e.g., Eminence API), but they only provide *metadata*: player names, seating order, decklists, and who won/drew. **No turn-by-turn actions.**
* **17Lands:** The gold standard for MTG data, but it only tracks MTG Arena. Arena does not support 4-player Commander (only 1v1 Brawl). 
* **Academic / Kaggle Datasets:** Existing Kaggle datasets (e.g., MTGJSON, MTG card embeddings) only contain card definitions and text. There are no public Kaggle datasets of turn-by-turn Commander logs.

#### Sources WITH Turn-by-Turn Data
* **MTGO (Magic Online):** 
  * **Granularity:** Perfect. MTGO enforces rules, so logs include exact mana floating, stack resolutions, targeting, and phase changes.
  * **Format:** Local `.dat` and `.txt` files saved to the user's `GameLogs` folder.
  * **Volume:** Massive, but decentralized. WotC does not publish these.
  * **TOS:** WotC strictly prohibits scraping MTGO servers. However, players own their local log files and can share them legally.
* **XMage:**
  * **Granularity:** Perfect. XMage is an open-source Java rules engine (very similar to Card-Forge). Logs contain exact state transitions.
  * **Format:** `.game` files and server-side logs.
  * **Volume:** High on public servers (e.g., `xmage.today`), but not aggregated into a public download.
  * **TOS:** Open-source and community-run. No corporate TOS preventing data sharing.
* **Cockatrice:**
  * **Granularity:** Poor for AI training. Cockatrice is a manual sandbox (no rules engine). Logs (`.cor` files) are essentially chat transcripts of players saying "pass", manually reducing life, and dragging cards. 
  * **Format:** XML-based `.cor` replay files.
  * **Volume:** High, saved locally or on servers like Rooster Ranges.
* **Playgroup.gg / Playgroup Live:**
  * **Granularity:** Medium. Playgroup.gg tracks 630k+ paper games (outcomes only). However, *Playgroup Live* is their browser-based virtual tabletop, which tracks ~7,000 games a month. It logs card movements, life, and turn duration. *Caveat:* Like Cockatrice, it does not enforce rules or the stack.
  * **Format:** JSON via their community API.
  * **TOS:** API is public for community management, but bulk scraping the entire database would likely require developer permission.

---

### 4. Top 3 Sources for Calibrating AI Pilots (Ranked)

To train an AI pilot to execute combo programs (mana engines -> outlets -> kills), you need **rules-enforced data**. Manual sandboxes (Cockatrice/Playgroup) are too noisy because players use shortcuts (e.g., "I present the Selvala loop, I make infinite green, GG") which an AI cannot parse into discrete game actions.

#### Rank 1: MTGO Local Game Logs (Crowdsourced)
* **Why it’s the best:** MTGO is the only official platform with a strict rules engine for 4-player Commander. If a player executes a Selvala combo, the log records every single untap trigger, mana generation, and card draw in exact sequence.
* **How to acquire it:** Because WotC does not provide an API, you must crowdsource the data. 
  1. Build a simple web portal.
  2. Reach out to the cEDH and MTGO Commander communities on Reddit (`r/CompetitiveEDH`, `r/MTGO`) and Discord.
  3. Ask players to zip and upload their local `C:\Users\[User]\AppData\Local\Apps\2.0\...` GameLogs folders. 
  4. Use an open-source parser like [MTGO-Tracker](https://github.com/c-f-s/MTGO-Tracker) to convert the `.dat`/`.txt` files into a SQLite database of turn-by-turn actions.

#### Rank 2: XMage Server Logs
* **Why it’s useful:** XMage is built on Java (like Card-Forge) and has a strict rules engine. The logs map perfectly to the kind of programmatic state transitions your headless simulator will use. It even has a rudimentary built-in AI, meaning the game states are already structured for machine reading.
* **How to acquire it:** 
  1. **Direct Request:** Join the XMage Discord or GitHub (`magefree/mage`). Contact the administrators of the main public servers (e.g., `xmage.today`). Explain your AI research and request an anonymized database dump of Commander game logs. Because it is an open-source community, admins are often highly receptive to research requests.
  2. **Self-Hosting:** Spin up your own headless XMage server, invite players to use it for free, and log all the games directly to your own database.

#### Rank 3: Playgroup Live API
* **Why it’s useful:** While it lacks a strict rules engine, Playgroup Live captures the exact timeline of card movements and life total changes in a modern JSON format, specifically built for Commander. It is much easier to parse than Cockatrice XMLs.
* **How to acquire it:**
  1. Go to [Playgroup.gg](https://playgroup.gg) and review their API documentation.
  2. Contact the developers (they are highly active on the `r/EDH` subreddit under the Playgroup.gg banner). 
  3. Request a research export of Playgroup Live match timelines. Since they already publish aggregate data articles (e.g., win rates by seat order), they have the infrastructure to query their database for specific commander wins (like Selvala) and export the JSON timelines of those matches.