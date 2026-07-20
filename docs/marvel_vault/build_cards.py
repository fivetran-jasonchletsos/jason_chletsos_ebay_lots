"""Build cards.json for the Marvel Vault showcase from the catalogued scan grids.

Each entry is (scan, row, col, name, brand, series, cardType, firstApp, serial,
alignment, team, estValue). Image file = images/{scan}_{row}_{col}.jpg (see
crop_scans.py). To add a future scan: photograph/scan the binder page, run it
through crop_scans.py with a new scanN key, then append rows below.

estValue was priced 2026-07-20 via the AI vision appraiser (/ebay/upload-photos),
not the SportsCardsPro comp used for eBay lot pricing -- that database has no
coverage of these Topps Chrome Marvel / Marvel Beginnings / Marvel Platinum
sets (verified live: every query matched an unrelated sports card on a stray
keyword). These are AI estimates, not sold comps -- treat as ballpark.
"""
import json
from collections import Counter

# (scan, row, col, name, brand, series, cardType, firstApp, serial, alignment, team, estValue)
CARDS = [
    # ── scan18 : Cable vs Wolverine / Ulik / Pepper Potts page ────────────────
    ("scan18", 0, 0, "Cable vs Wolverine", "Flair", "'94 Flair", "Insert", False, None, "Anti-Hero", "X-Men Adjacent", 5),
    ("scan18", 0, 1, "Deadpool & Wolverine", "Topps Chrome", "Cover Stars", "Insert", False, None, "Anti-Hero", "X-Men Adjacent", 3),
    ("scan18", 0, 2, "Ulik", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Villain", "Asgardians", 3),
    ("scan18", 1, 0, "Wolverine vs Cyber", "Topps Chrome", "Famous Combat 1993", "Insert", False, None, "Anti-Hero", "X-Men Adjacent", 20),
    ("scan18", 1, 1, "Dazzler", "Topps Chrome", "Base", "Base", False, None, "Hero", "X-Men", 1),
    ("scan18", 1, 2, "Angel", "Topps Chrome", "One World Under Doom", "Insert", False, None, "Hero", "X-Men", 2),
    ("scan18", 2, 0, "Wolverine", "Topps Chrome", "You Will Never Save The World", "Insert", False, None, "Anti-Hero", "X-Men", 3),
    ("scan18", 2, 1, "The Hood", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Villain", "Criminal Underworld", 3),
    ("scan18", 2, 2, "Pepper Potts", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Hero", "Iron Man Supporting Cast", 5),

    # ── scan19 : Thor Corps / Deadpool Icons / Longshot page ──────────────────
    ("scan19", 0, 0, "Thor Corps", "Upper Deck", "Marvel Beginnings: Team Formations", "Insert", False, None, "Hero", "Asgardians", 3),
    ("scan19", 0, 1, "Wolverines and Deadpools", "Topps Chrome", "Cover Stars", "Insert", False, None, "Anti-Hero", "X-Men Adjacent", 2),
    ("scan19", 0, 2, "Raelith", "Topps Chrome", "Base", "Base", True, None, "Villain", "Unaffiliated", 5),
    ("scan19", 1, 0, "Aftermath", "Topps Chrome", "Deadpool Chrome", "Insert", False, None, "Anti-Hero", "X-Men Adjacent", 2),
    ("scan19", 1, 1, "Wolverine", "Topps Chrome", "Deadpool Icons", "Insert", False, None, "Anti-Hero", "X-Men", 5),
    ("scan19", 1, 2, "Jeff the Land Shark", "Topps Chrome", "Base", "Base", False, None, "Hero", "Guardians of the Galaxy", 2),
    ("scan19", 2, 0, "Groot", "Topps Chrome", "Base", "Base", False, None, "Hero", "Guardians of the Galaxy", 5),
    ("scan19", 2, 1, "Wrecking Crew", "Upper Deck", "Marvel Beginnings: Team Formations", "Insert", False, None, "Villain", "Wrecking Crew", 3),
    ("scan19", 2, 2, "Longshot", "Topps Chrome", "Base", "Base", False, None, "Hero", "X-Men", 3),

    # ── scan20 : Green Goblin / Fantastic Years / Echo page ───────────────────
    ("scan20", 0, 0, "Green Goblin", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Villain", "Spider-Man Villains", 10),
    ("scan20", 0, 1, "X-23", "Topps Chrome", "Base", "Base", False, None, "Anti-Hero", "X-Men", 1),
    ("scan20", 0, 2, "Colossus", "Topps Chrome", "Base", "Base", False, None, "Hero", "X-Men", 2),
    ("scan20", 1, 0, "Human Torch", "Topps Chrome", "65 Fantastic Years", "Insert", False, None, "Hero", "Fantastic Four", 2),
    ("scan20", 1, 1, "She-Hulk", "Topps Chrome", "65 Fantastic Years", "Insert", False, None, "Hero", "Fantastic Four", 5),
    ("scan20", 1, 2, "The Human Torch", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Hero", "Fantastic Four", 2),
    ("scan20", 2, 0, "Invisible Woman", "Topps Chrome", "65 Fantastic Years", "Insert", False, None, "Hero", "Fantastic Four", 2),
    ("scan20", 2, 1, "Ghost Riders Unite", "Topps Chrome", "Meanwhile...", "Insert", False, None, "Anti-Hero", "Midnight Sons", 2),
    ("scan20", 2, 2, "Echo", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Anti-Hero", "Unaffiliated", 20),

    # ── scan21 : Aracnhix / Black Panther / Punisher vs Ghost Rider page ─────
    ("scan21", 0, 0, "Aracnhix", "Topps Chrome", "Base", "Base", True, None, "Villain", "Spider-Man Villains", 20),
    ("scan21", 0, 1, "Black Panther", "Topps Chrome", "The Beyond", "Insert", False, None, "Hero", "Avengers", 2),
    ("scan21", 0, 2, "Domino", "Topps Chrome", "Base", "Base", False, None, "Anti-Hero", "X-Force", 3),
    ("scan21", 1, 0, "Silver Surfer", "Topps Chrome", "65 Fantastic Years", "Insert", False, None, "Hero", "Fantastic Four Adjacent", 20),
    ("scan21", 1, 1, "Patch", "Topps Chrome", "Base", "Base", False, None, "Anti-Hero", "X-Men", 2),
    ("scan21", 1, 2, "GLX-Mas #1", "Upper Deck", "Monumental Covers / Women of Marvel", "Insert", False, None, "Hero", "X-Men", 10),
    ("scan21", 2, 0, "Star-Lord", "Topps Chrome", "The Beyond", "Insert", False, None, "Hero", "Guardians of the Galaxy", 2),
    ("scan21", 2, 1, "Elektra", "Topps Chrome", "Base", "Base", False, None, "Anti-Hero", "Unaffiliated", 2),
    ("scan21", 2, 2, "Punisher vs Ghost Rider", "Topps Chrome", "Famous Battles 1991", "Insert", False, None, "Anti-Hero", "Midnight Sons Adjacent", 2),

    # ── scan22 : Spider-Ham / Psylocke / Ant-Man page ─────────────────────────
    ("scan22", 0, 0, "Spider-Ham", "Topps Chrome", "Base", "Base", False, None, "Hero", "Spider-Verse", 3),
    ("scan22", 0, 1, "Revelation", "Topps Chrome", "Base", "Base", False, None, "Villain", "X-Men Villains", 3),
    ("scan22", 0, 2, "Rhino", "Topps Chrome", "Base", "Base", False, None, "Villain", "Spider-Man Villains", 2),
    ("scan22", 1, 0, "Psylocke", "Topps Chrome", "Base", "Base", False, None, "Hero", "X-Men", 2),
    ("scan22", 1, 1, "Galactus", "Topps Chrome", "Base", "Base", False, None, "Villain", "Cosmic", 3),
    ("scan22", 1, 2, "Scream", "Topps Chrome", "Base", "Base", False, None, "Villain", "Symbiotes", 5),
    ("scan22", 2, 0, "Moonstar", "Topps Chrome", "Base", "Base", False, None, "Hero", "New Mutants", 3),
    ("scan22", 2, 1, "Emma Frost", "Topps Chrome", "Base", "Base", False, None, "Hero", "X-Men", 2),
    ("scan22", 2, 2, "Ant-Man", "Topps Chrome", "Base", "Base", False, None, "Hero", "Avengers", 1),

    # ── scan23 : Ultimate Wolverine / Tombstone / Wave page ───────────────────
    ("scan23", 0, 0, "Ultimate Wolverine", "Topps Chrome", "Base", "Base", False, None, "Anti-Hero", "X-Men", 20),
    ("scan23", 0, 1, "Bloody Battle", "Topps Chrome", "Marvel Battles Masterpieces", "Insert", False, None, "Anti-Hero", "X-Men Adjacent", 20),
    ("scan23", 0, 2, "Beast", "Topps Chrome", "Base", "Base", False, None, "Hero", "X-Men", 15),
    ("scan23", 1, 0, "Hellverine", "Topps Chrome", "Base", "Base", False, None, "Anti-Hero", "Unaffiliated", 3),
    ("scan23", 1, 1, "Tombstone", "Topps Chrome", "Base", "Base", False, None, "Villain", "Spider-Man Villains", 2),
    ("scan23", 1, 2, "She-Venom", "Topps Chrome", "Base", "Base", False, None, "Villain", "Symbiotes", 20),
    ("scan23", 2, 0, "Wolverine vs Omega Red", "Topps Chrome", "Famous Battles", "Insert", False, None, "Anti-Hero", "X-Men Adjacent", 2),
    ("scan23", 2, 1, "Kate Bishop", "Topps Chrome", "Base", "Base", False, None, "Hero", "Young Avengers", 5),
    ("scan23", 2, 2, "Wave", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Villain", "Wrecking Crew", 5),

    # ── scan24 : Mister Fantastic / Jean Grey / Colleen Wing page ─────────────
    ("scan24", 0, 0, "Mister Fantastic", "Topps Chrome", "Base", "Base", False, None, "Hero", "Fantastic Four", 2),
    ("scan24", 0, 1, "Rek-Rap", "Topps Chrome", "Base", "Base", False, None, "Villain", "Spider-Man Villains", 5),
    ("scan24", 0, 2, "She-Hulk", "Topps Chrome", "Base", "Base", False, None, "Hero", "Avengers", 2),
    ("scan24", 1, 0, "Daredevil", "Topps Chrome", "Base", "Base", False, None, "Hero", "Defenders", 3),
    ("scan24", 1, 1, "Jean Grey", "Topps Chrome", "Base", "Base", False, None, "Hero", "X-Men", 2),
    ("scan24", 1, 2, "Nightshade", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Villain", "Criminal Underworld", 2),
    ("scan24", 2, 0, "White Fox", "Topps Chrome", "Base", "Base", False, None, "Hero", "Avengers Allies", 3),
    ("scan24", 2, 1, "Glob Herman", "Topps Chrome", "Base", "Base", False, None, "Hero", "X-Men", 2),
    ("scan24", 2, 2, "Colleen Wing", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Hero", "Daughters of the Dragon", 1),

    # ── scan25 : Eimin / Uatu the Watcher / Psylocke page ─────────────────────
    ("scan25", 0, 0, "Eimin", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Villain", "Apocalypse Twins", 2),
    ("scan25", 0, 1, "Hellgate", "Topps Chrome", "Base", "Base", True, None, "Villain", "Unaffiliated", 2),
    ("scan25", 0, 2, "Doctor Doom", "Topps Chrome", "One World Under Doom", "Insert", False, None, "Villain", "Fantastic Four Villains", 20),
    ("scan25", 1, 0, "Silver Samurai", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Villain", "X-Men Villains", 2),
    ("scan25", 1, 1, "Proteus", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Villain", "X-Men Villains", 2),
    ("scan25", 1, 2, "Echo", "Upper Deck", "Women of Marvel", "Insert", False, None, "Anti-Hero", "Unaffiliated", 2),
    ("scan25", 2, 0, "Uatu the Watcher", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Neutral", "The Watchers", 2),
    ("scan25", 2, 1, "Deep Lore: Weapon Plus Program", "Upper Deck", "Deep Lore", "Insert", False, None, "Neutral", "Weapon Plus", 3),
    ("scan25", 2, 2, "Psylocke", "Topps Chrome", "Base", "Base", False, None, "Hero", "X-Men", 2),

    # ── scan26 : Mariko Yashida / Fantastic Four / The Maker page ─────────────
    ("scan26", 0, 0, "Mariko Yashida", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Hero", "Wolverine Supporting Cast", 2),
    ("scan26", 0, 1, "Johnny Watts", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Hero", "Spider-Man 2099 Supporting Cast", 2),
    ("scan26", 0, 2, "Cosmic Alpha Mjolnir", "Upper Deck", "Begin the Saga", "Insert", False, None, "Hero", "Avengers", 2),
    ("scan26", 1, 0, "Jubilee", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Hero", "X-Men", 2),
    ("scan26", 1, 1, "Fantastic Four", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Hero", "Fantastic Four", 2),
    ("scan26", 1, 2, "Griffin", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Villain", "Spider-Man Villains", 2),
    ("scan26", 2, 0, "Dazzler", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Hero", "X-Men", 1),
    ("scan26", 2, 1, "Profile", "Upper Deck", "Marvel Beginnings: Profile", "Insert", False, None, "Unknown", "Unaffiliated", 2),
    ("scan26", 2, 2, "The Maker", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Villain", "Fantastic Four Villains", 1),

    # ── scan27 : Mystique / Captain America / Toxin page ──────────────────────
    ("scan27", 0, 0, "Mystique", "Topps Chrome", "Base", "Base", False, None, "Anti-Hero", "X-Men Adjacent", 3),
    ("scan27", 0, 1, "Spider-Boy", "Topps Chrome", "Base", "Base", False, None, "Hero", "Spider-Society", 3),
    ("scan27", 0, 2, "Wasp", "Topps Chrome", "Base", "Base", False, None, "Hero", "Avengers", 3),
    ("scan27", 1, 0, "Mysterio", "Topps Chrome", "Base", "Base", False, None, "Villain", "Spider-Man Villains", 2),
    ("scan27", 1, 1, "Captain America", "Topps Chrome", "Base", "Base", False, None, "Hero", "Avengers", 2),
    ("scan27", 1, 2, "U.S. Agent", "Topps Chrome", "Base", "Base", False, None, "Hero", "Avengers", 5),
    ("scan27", 2, 0, "Thanos", "Topps Chrome", "Base", "Base", False, None, "Villain", "Cosmic", 2),
    ("scan27", 2, 1, "Deep Lore: Weapon Plus Program", "Upper Deck", "Deep Lore", "Insert", False, None, "Neutral", "Weapon Plus", 2),
    ("scan27", 2, 2, "Toxin", "Topps Chrome", "Base", "Base", False, None, "Anti-Hero", "Symbiotes", 2),

    # ── scan28 : Cassandra Romulus / Professor X / Black Cat page ────────────
    ("scan28", 0, 0, "Cassandra Romulus", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Villain", "Unaffiliated", 3),
    ("scan28", 0, 1, "Rhino", "Topps Chrome", "Base", "Base", False, None, "Villain", "Spider-Man Villains", 2),
    ("scan28", 0, 2, "Thor", "Topps Chrome", "Base", "Base", False, None, "Hero", "Avengers", 2),
    ("scan28", 1, 0, "Ms. Marvel", "Topps Chrome", "Base", "Base", True, None, "Hero", "Avengers", 1),
    ("scan28", 1, 1, "Spider-Woman", "Topps Chrome", "Base", "Base", False, None, "Hero", "Avengers", 2),
    ("scan28", 1, 2, "Professor X", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Hero", "X-Men", 2),
    ("scan28", 2, 0, "Dragonfire", "Topps Chrome", "Base", "Base", True, None, "Anti-Hero", "Unaffiliated", 20),
    ("scan28", 2, 1, "Ikaris", "Topps Chrome", "Base", "Base", False, None, "Hero", "Eternals", 2),
    ("scan28", 2, 2, "Black Cat", "Topps Chrome", "Base", "Base", False, None, "Anti-Hero", "Spider-Man Supporting Cast", 3),

    # ── scan29 : Jubilee / Rogue / Emma Frost page ────────────────────────────
    ("scan29", 0, 0, "Jubilee", "Topps Chrome", "Base", "Base", False, None, "Hero", "X-Men", 2),
    ("scan29", 0, 1, "Abomination", "Topps Chrome", "Base", "Base", False, None, "Villain", "Hulk Villains", 3),
    ("scan29", 0, 2, "Rocket Raccoon", "Topps Chrome", "Base", "Base", False, None, "Hero", "Guardians of the Galaxy", 2),
    ("scan29", 1, 0, "Gorgon", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Villain", "Inhumans", 2),
    ("scan29", 1, 1, "Rogue", "Topps Chrome", "Base", "Base", False, None, "Hero", "X-Men", 2),
    ("scan29", 1, 2, "Ghost-Spider", "Topps Chrome", "Base", "Base", False, None, "Hero", "Spider-Verse", 3),
    ("scan29", 2, 0, "Iceman", "Topps Chrome", "Base", "Base", False, None, "Hero", "X-Men", 2),
    ("scan29", 2, 1, "Black Panther", "Topps Chrome", "Base", "Base", False, None, "Hero", "Avengers", 2),
    ("scan29", 2, 2, "Emma Frost", "Topps Chrome", "Base", "Base", False, None, "Hero", "X-Men", 2),

    # ── scan30 : Captain Marvel / Apocalypse / Vulture page ───────────────────
    ("scan30", 0, 0, "Captain Marvel", "Topps Chrome", "Base", "Base", False, None, "Hero", "Avengers", 2),
    ("scan30", 0, 1, "Spider-Man 2099", "Topps Chrome", "Base", "Base", False, None, "Hero", "Spider-Society", 3),
    ("scan30", 0, 2, "Apocalypse", "Topps Chrome", "Base", "Base", False, None, "Villain", "X-Men Villains", 5),
    ("scan30", 1, 0, "Man-Thing", "Topps Chrome", "Base", "Base", False, None, "Neutral", "Midnight Sons", 3),
    ("scan30", 1, 1, "Silence", "Topps Chrome", "Base", "Base", False, None, "Anti-Hero", "Symbiotes", 2),
    ("scan30", 1, 2, "Leader", "Topps Chrome", "Base", "Base", False, None, "Villain", "Hulk Villains", 5),
    ("scan30", 2, 0, "Rasputin IV", "Topps Chrome", "Base", "Base", False, None, "Anti-Hero", "X-Men Adjacent", 2),
    ("scan30", 2, 1, "Shang-Chi", "Topps Chrome", "Base", "Base", False, None, "Hero", "Avengers", 3),
    ("scan30", 2, 2, "Vulture", "Topps Chrome", "Base", "Base", False, None, "Villain", "Spider-Man Villains", 5),

    # ── scan31 : Chameleon / Mister Sinister / Spider-Punk page ───────────────
    ("scan31", 0, 0, "Chameleon", "Topps Chrome", "Base", "Base", False, None, "Villain", "Spider-Man Villains", 5),
    ("scan31", 0, 1, "Dormammu", "Topps Chrome", "Base", "Base", False, None, "Villain", "Cosmic / Mystic", 10),
    ("scan31", 0, 2, "Slingshot", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Hero", "Unaffiliated", 2),
    ("scan31", 1, 0, "Ironheart", "Topps Chrome", "Base", "Base", False, None, "Hero", "Avengers", 3),
    ("scan31", 1, 1, "Mister Sinister", "Topps Chrome", "Base", "Base", False, None, "Villain", "X-Men Villains", 2),
    ("scan31", 1, 2, "Doyle Dormammu", "Topps Chrome", "Base", "Base", False, None, "Villain", "Cosmic / Mystic", 2),
    ("scan31", 2, 0, "Husk", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Hero", "X-Men", 2),
    ("scan31", 2, 1, "White Tiger", "Topps Chrome", "Base", "Base", False, None, "Hero", "Avengers", 5),
    ("scan31", 2, 2, "Spider-Punk", "Topps Chrome", "Base", "Base", False, None, "Hero", "Spider-Verse", 5),

    # ── scan32 : Beast / Omega Red / Human Torch page ─────────────────────────
    ("scan32", 0, 0, "Beast", "Topps Chrome", "Base", "Base", False, None, "Hero", "X-Men", 1),
    ("scan32", 0, 1, "Galactus", "Topps Chrome", "Base", "Base", False, None, "Villain", "Cosmic", 2),
    ("scan32", 0, 2, "Omega Red", "Topps Chrome", "Base", "Base", False, None, "Villain", "X-Men Villains", 2),
    ("scan32", 1, 0, "Chameleon", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Villain", "Spider-Man Villains", 2),
    ("scan32", 1, 1, "Kid Juggernaut", "Topps Chrome", "Base", "Base", False, None, "Anti-Hero", "X-Men Adjacent", 1),
    ("scan32", 1, 2, "Wasp", "Upper Deck", "Women of Marvel", "Insert", False, None, "Hero", "Avengers", 3),
    ("scan32", 2, 0, "Shuri", "Topps Chrome", "Base", "Base", False, None, "Hero", "Avengers", 2),
    ("scan32", 2, 1, "Dazzler", "Topps Chrome", "Base", "Base", False, None, "Hero", "X-Men", 1),
    ("scan32", 2, 2, "Human Torch", "Topps Chrome", "Base", "Base", False, None, "Hero", "Fantastic Four", 3),

    # ── scan33 : Beta Ray Bill / Hulk / Hallows' Eve page ─────────────────────
    ("scan33", 0, 0, "Beta Ray Bill", "Topps Chrome", "Base", "Base", False, None, "Hero", "Avengers", 5),
    ("scan33", 0, 1, "Enchantress", "Topps Chrome", "Base", "Base", False, None, "Villain", "Asgardians", 5),
    ("scan33", 0, 2, "Agatha Harkness", "Topps Chrome", "Base", "Base", False, None, "Villain", "Scarlet Witch Adjacent", 2),
    ("scan33", 1, 0, "Kraven the Hunter", "Topps Chrome", "Base", "Base", False, None, "Villain", "Spider-Man Villains", 1),
    ("scan33", 1, 1, "Hulk", "Topps Chrome", "Base", "Base", False, None, "Hero", "Avengers", 2),
    ("scan33", 1, 2, "Nova", "Topps Chrome", "Base", "Base", False, None, "Hero", "Avengers", 3),
    ("scan33", 2, 0, "Silk", "Topps Chrome", "Base", "Base", False, None, "Hero", "Spider-Society", 2),
    ("scan33", 2, 1, "Cyclops", "Topps Chrome", "Base", "Base", False, None, "Hero", "X-Men", 5),
    ("scan33", 2, 2, "Hallows' Eve", "Topps Chrome", "Base", "Base", False, None, "Anti-Hero", "Moon Knight Family", 3),

    # ── scan34 : Callisto / Venom / Blade page ─────────────────────────────────
    ("scan34", 0, 0, "Callisto", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Anti-Hero", "Morlocks", 2),
    ("scan34", 0, 1, "Black Widow", "Topps Chrome", "Base", "Base", False, None, "Hero", "Avengers", 3),
    ("scan34", 0, 2, "Kingpin", "Topps Chrome", "Base", "Base", False, None, "Villain", "Daredevil Villains", 10),
    ("scan34", 1, 0, "Hobgoblin", "Topps Chrome", "Base", "Base", False, None, "Villain", "Spider-Man Villains", 3),
    ("scan34", 1, 1, "Venom", "Topps Chrome", "Base", "Base", False, None, "Anti-Hero", "Symbiotes", 2),
    ("scan34", 1, 2, "Rogue", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Hero", "X-Men", 1),
    ("scan34", 2, 0, "Polaris", "Upper Deck", "Women of Marvel", "Insert", False, None, "Hero", "X-Men", 2),
    ("scan34", 2, 1, "Jean Grey", "Upper Deck", "Women of Marvel", "Insert", False, None, "Hero", "X-Men", 2),
    ("scan34", 2, 2, "Blade", "Topps Chrome", "Base", "Base", False, None, "Hero", "Vampire Hunters", 3),

    # ── scan35 : Stingray / Elbecca Voss / Patch page (8 cards, one empty slot) ─
    ("scan35", 0, 0, "Stingray", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Hero", "Avengers Allies", 2),
    ("scan35", 0, 1, "Arcade", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Villain", "Murderworld", 2),
    ("scan35", 0, 2, "Tigra", "Topps Chrome", "Teal Parallel", "Parallel", False, "079/199", "Hero", "Avengers", 2),
    ("scan35", 1, 0, "Jack O'Lantern", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Villain", "Spider-Man Villains", 3),
    ("scan35", 1, 1, "Spider-Man Noir", "Topps Chrome", "Base", "Base", False, None, "Hero", "Spider-Verse", 2),
    ("scan35", 1, 2, "Elbecca Voss", "Topps Chrome", "Purple Lava Parallel", "Parallel", True, "55/75", "Villain", "Unaffiliated", 3),
    ("scan35", 2, 0, "A Point in Time", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Anti-Hero", "Avengers Adjacent", 2),
    ("scan35", 2, 1, "Patch", "Topps Chrome", "Purple Mosaic Parallel", "Parallel", False, "160/250", "Anti-Hero", "X-Men", 20),

    # ── scan36 : PSA-graded 2023 Marvel Platinum slabs (3 cards) ─────────────
    ("scan36", 0, 0, "Elektra", "Upper Deck", "2023 Marvel Platinum #103 - Rainbow Parallel", "Parallel", False, "PSA 10 GEM MT - Cert #148946789", "Anti-Hero", "Unaffiliated", 150),
    ("scan36", 0, 1, "Wolverine", "Upper Deck", "2023 Marvel Platinum #182 - Yellow Rainbow Parallel", "Parallel", False, "PSA 10 GEM MT - Cert #146117312", "Anti-Hero", "X-Men", 150),
    ("scan36", 1, 0, "Wolverine", "Upper Deck", "2023 Marvel Platinum #182 - Rainbow Color Wheel Parallel", "Parallel", False, "PSA 10 GEM MT - Cert #103306390", "Anti-Hero", "X-Men", 200),

    # ── scan37 : Magneto / Leader / Gamora page ───────────────────────────────
    ("scan37", 0, 0, "Magneto", "Topps Chrome", "Base", "Base", False, None, "Anti-Hero", "Brotherhood of Mutants", 3),
    ("scan37", 0, 1, "Mysterio", "Topps Chrome", "Base", "Base", False, None, "Villain", "Spider-Man Villains", 5),
    ("scan37", 0, 2, "Mister Fantastic", "Topps Chrome", "Base", "Base", False, None, "Hero", "Fantastic Four", 3),
    ("scan37", 1, 0, "Agatha Harkness", "Topps Chrome", "Base", "Base", False, None, "Villain", "Scarlet Witch Adjacent", 2),
    ("scan37", 1, 1, "Leader", "Topps Chrome", "Base", "Base", False, None, "Villain", "Hulk Villains", 2),
    ("scan37", 1, 2, "Thena", "Topps Chrome", "Base", "Base", False, None, "Hero", "Eternals", 3),
    ("scan37", 2, 0, "Iron Man", "Topps Chrome", "Base", "Base", False, None, "Hero", "Avengers", 5),
    ("scan37", 2, 1, "Hope Summers", "Topps Chrome", "Base", "Base", False, None, "Hero", "X-Men", 1),
    ("scan37", 2, 2, "Gamora", "Topps Chrome", "Base", "Base", False, None, "Hero", "Guardians of the Galaxy", 2),

    # ── scan38 : Doctor Doom / Mephisto / Quicksilver / Professor X (4 cards) ─
    ("scan38", 0, 0, "Doctor Doom", "Topps Chrome", "One World Under Doom", "Insert", False, None, "Villain", "Fantastic Four Villains", 20),
    ("scan38", 0, 1, "Mephisto", "Topps Chrome", "Base", "Base", False, None, "Villain", "Cosmic / Mystic", 5),
    ("scan38", 1, 0, "Quicksilver", "Topps Chrome", "Base", "Base", False, None, "Hero", "Avengers", 2),
    ("scan38", 1, 1, "Professor X", "Topps Chrome", "Base", "Base", False, None, "Hero", "X-Men", 1),
]

name_counts = Counter(name for (_, _, _, name, *_rest) in CARDS)

out = []
for i, (scan, row, col, name, brand, series, cardType, firstApp, serial, alignment, team, value) in enumerate(CARDS, start=1):
    out.append({
        "id": i,
        "name": name,
        "image": f"images/{scan}_{row}_{col}.jpg",
        "brand": brand,
        "series": series,
        "cardType": cardType,
        "firstAppearance": firstApp,
        "serial": serial,
        "alignment": alignment,
        "team": team,
        "estValue": value,
        "copies": name_counts[name],
    })

with open("cards.json", "w") as f:
    json.dump(out, f, indent=2)

print(f"wrote {len(out)} cards to cards.json")
