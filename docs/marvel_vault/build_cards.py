"""Build cards.json for the Marvel Vault showcase from the catalogued scan grids.

Each entry is (scan, row, col, name, brand, series, cardType, firstApp, serial,
alignment, team, estValue). Image file = images/{scan}_{row}_{col}.jpg (see
crop_scans.py). To add a future scan: photograph/scan the binder page, run it
through crop_scans.py with a new scanN key, then append 9 rows below.
"""
import json

# (scan, row, col, name, brand, series, cardType, firstApp, serial, alignment, team, estValue)
CARDS = [
    # ── scan1 : Toxin / Kid Juggernaut / Enchantress page ──────────────────
    ("scan1", 0, 0, "Toxin", "Topps Chrome", "Base", "Base", False, None, "Anti-Hero", "Symbiotes", 4),
    ("scan1", 0, 1, "Spot", "Topps Chrome", "Marvel Beginnings", "Insert", False, None, "Villain", "Spider-Man Villains", 6),
    ("scan1", 0, 2, "Cassandra Romulus", "Topps Chrome", "Marvel Beginnings", "Insert", False, None, "Villain", "X-Men Villains", 5),
    ("scan1", 1, 0, "Kid Juggernaut", "Topps Chrome", "Base", "Base", False, None, "Anti-Hero", "X-Men Adjacent", 4),
    ("scan1", 1, 1, "Wasp", "Topps Chrome", "Base", "Base", False, None, "Hero", "Avengers", 6),
    ("scan1", 1, 2, "U.S. Agent", "Topps Chrome", "Base", "Base", False, None, "Hero", "Avengers", 5),
    ("scan1", 2, 0, "Enchantress", "Topps Chrome", "Marvel Beginnings", "Insert", False, None, "Villain", "Asgardians", 6),
    ("scan1", 2, 1, "Slingshot", "Topps Chrome", "Marvel Beginnings", "Insert", False, None, "Hero", "New Warriors", 5),
    ("scan1", 2, 2, "Rogue", "Topps Chrome", "Marvel Beginnings", "Insert", False, None, "Hero", "X-Men", 10),

    # ── scan2 : Blade / Daredevil / Mystique page ───────────────────────────
    ("scan2", 0, 0, "Blade", "Topps Chrome", "Base", "Base", False, None, "Anti-Hero", "Midnight Sons", 8),
    ("scan2", 0, 1, "Doyle Dormammu", "Topps Chrome", "Base", "Base", False, None, "Villain", "Dread Dimension", 5),
    ("scan2", 0, 2, "Glob", "Topps Chrome", "Base", "Base", False, None, "Villain", "Brotherhood", 4),
    ("scan2", 1, 0, "Daredevil", "Topps Chrome", "Base", "Base", False, None, "Hero", "Defenders", 9),
    ("scan2", 1, 1, "Hellgate", "Topps Chrome", "Base", "Base", True, None, "Villain", "X-Men Villains", 8),
    ("scan2", 1, 2, "Devil Dinosaur", "Topps Chrome", "Base", "Base", False, None, "Hero", "Moon Girl & Devil Dinosaur", 7),
    ("scan2", 2, 0, "Mystique", "Topps Chrome", "Base", "Base", False, None, "Villain", "Brotherhood", 9),
    ("scan2", 2, 1, "White Fox", "Topps Chrome", "Base", "Base", False, None, "Hero", "Avengers Allies", 5),
    ("scan2", 2, 2, "Mister Fantastic", "Topps Chrome", "Base", "Base", False, None, "Hero", "Fantastic Four", 8),

    # ── scan3 : She-Venom / Ironheart / Spider-Punk page ────────────────────
    ("scan3", 0, 0, "She-Venom", "Topps Chrome", "Base", "Wave Refractor", False, None, "Anti-Hero", "Symbiotes", 18),
    ("scan3", 0, 1, "Spider-Woman", "Topps Chrome", "Base", "Base", False, None, "Hero", "Avengers", 8),
    ("scan3", 0, 2, "Ms. Marvel", "Topps Chrome", "Base", "Base", False, None, "Hero", "Avengers", 8),
    ("scan3", 1, 0, "Colleen Wing", "Topps Chrome", "Marvel Beginnings", "Insert", False, None, "Hero", "Daughters of the Dragon", 6),
    ("scan3", 1, 1, "Ironheart", "Topps Chrome", "Base", "Base", False, None, "Hero", "Avengers", 9),
    ("scan3", 1, 2, "Domino", "Topps Chrome", "Base", "Wave Refractor", False, None, "Anti-Hero", "X-Force", 16),
    ("scan3", 2, 0, "Gorgon", "Topps Chrome", "Marvel Beginnings", "Insert", False, None, "Anti-Hero", "Inhumans", 5),
    ("scan3", 2, 1, "Jubilee", "Topps Chrome", "Base", "Base", False, None, "Hero", "X-Men", 7),
    ("scan3", 2, 2, "Spider-Punk", "Topps Chrome", "Base", "Base", False, None, "Hero", "Spider-Society", 9),

    # ── scan4 : Raelith / Tombstone / Moon Knight page ──────────────────────
    ("scan4", 0, 0, "Raelith", "Topps Chrome", "Base", "Base", True, None, "Villain", "New Character", 8),
    ("scan4", 0, 1, "Ikaris", "Topps Chrome", "Base", "Base", False, None, "Hero", "Eternals", 6),
    ("scan4", 0, 2, "Rek-Rap", "Topps Chrome", "Base", "Base", False, None, "Villain", "Spider-Man Villains", 5),
    ("scan4", 1, 0, "Shuri", "Topps Chrome", "Base", "Base", False, None, "Hero", "Wakanda", 8),
    ("scan4", 1, 1, "Tombstone", "Topps Chrome", "Base", "Wave Refractor", False, None, "Villain", "Spider-Man Villains", 15),
    ("scan4", 1, 2, "Wrecking Crew", "Upper Deck", "Team Formations", "Insert", False, None, "Villain", "Wrecking Crew", 6),
    ("scan4", 2, 0, "Moon Knight", "Topps Chrome", "Base", "Base", False, None, "Anti-Hero", "Midnight Sons", 10),
    ("scan4", 2, 1, "Jean Grey", "Topps Chrome", "Base", "Base", False, None, "Hero", "X-Men", 9),
    ("scan4", 2, 2, "Chameleon", "Topps Chrome", "Base", "Base", False, None, "Villain", "Spider-Man Villains", 6),

    # ── scan5 : Leader / Galactus / Dormammu page ───────────────────────────
    ("scan5", 0, 0, "Leader", "Topps Chrome", "Base", "Base", False, None, "Villain", "Hulk Villains", 5),
    ("scan5", 0, 1, "Elbecca Voss", "Topps Chrome", "Base", "Wave Refractor", True, "55/75", "Villain", "New Character", 30),
    ("scan5", 0, 2, "Apocalypse", "Topps Chrome", "Base", "Base", False, None, "Villain", "X-Men Villains", 9),
    ("scan5", 1, 0, "Galactus", "Topps Chrome", "Base", "Base", False, None, "Villain", "Cosmic", 9),
    ("scan5", 1, 1, "She-Hulk", "Topps Chrome", "Base", "Base", False, None, "Hero", "Avengers", 8),
    ("scan5", 1, 2, "Shang-Chi", "Topps Chrome", "Base", "Base", False, None, "Hero", "Avengers", 8),
    ("scan5", 2, 0, "White Tiger", "Topps Chrome", "Base", "Base", False, None, "Hero", "Avengers Allies", 6),
    ("scan5", 2, 1, "Mister Sinister", "Topps Chrome", "Base", "Base", False, None, "Villain", "X-Men Villains", 8),
    ("scan5", 2, 2, "Dormammu", "Topps Chrome", "Base", "Base", False, None, "Villain", "Dread Dimension", 8),

    # ── scan6 : Thanos / Captain America / Arcade page ──────────────────────
    ("scan6", 0, 0, "Thanos", "Topps Chrome", "Base", "Base", False, None, "Villain", "Cosmic Villains", 12),
    ("scan6", 0, 1, "Mysterio", "Topps Chrome", "Base", "Base", False, None, "Villain", "Spider-Man Villains", 8),
    ("scan6", 0, 2, "A Point in Time (Natasha Romanoff)", "Upper Deck", "A Point in Time", "Insert", False, None, "Hero", "Avengers", 6),
    ("scan6", 1, 0, "Captain America", "Topps Chrome", "Base", "Base", False, None, "Hero", "Avengers", 10),
    ("scan6", 1, 1, "Spider-Boy", "Topps Chrome", "Base", "Base", False, None, "Hero", "Spider-Society", 7),
    ("scan6", 1, 2, "Jack O'Lantern", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Villain", "Spider-Man Villains", 5),
    ("scan6", 2, 0, "Vulture", "Topps Chrome", "Base", "Base", False, None, "Villain", "Spider-Man Villains", 7),
    ("scan6", 2, 1, "Spider-Man Noir", "Topps Chrome", "Base", "Base", False, None, "Hero", "Spider-Society", 8),
    ("scan6", 2, 2, "Arcade", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Villain", "Murderworld", 5),

    # ── scan7 : Elektra / Thor / Longshot page ──────────────────────────────
    ("scan7", 0, 0, "Elektra", "Topps Chrome", "Base", "Base", False, None, "Anti-Hero", "Defenders", 9),
    ("scan7", 0, 1, "Dragonfire", "Topps Chrome", "Base", "Base", True, None, "Hero", "New Character", 8),
    ("scan7", 0, 2, "Black Panther", "Topps Chrome", "The Beyond", "Insert", False, None, "Hero", "Avengers", 9),
    ("scan7", 1, 0, "Rhino", "Topps Chrome", "Base", "Base", False, None, "Villain", "Spider-Man Villains", 6),
    ("scan7", 1, 1, "Thor", "Topps Chrome", "Base", "Base", False, None, "Hero", "Avengers", 10),
    ("scan7", 1, 2, "Husk", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Hero", "X-Men", 5),
    ("scan7", 2, 0, "Thor Corps", "Upper Deck", "Team Formations", "Insert", False, None, "Hero", "Thor Corps", 6),
    ("scan7", 2, 1, "Groot", "Topps Chrome", "Base", "Base", False, None, "Hero", "Guardians of the Galaxy", 8),
    ("scan7", 2, 2, "Longshot", "Topps Chrome", "Base", "Base", False, None, "Hero", "X-Men", 6),

    # ── scan8 : Mary Jane / Deep Lore / Black Cat page ──────────────────────
    ("scan8", 0, 0, "Mary Jane Watson", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Hero", "Spider-Man Supporting Cast", 6),
    ("scan8", 0, 1, "Blastaar", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Villain", "Negative Zone", 5),
    ("scan8", 0, 2, "Professor X", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Hero", "X-Men", 9),
    ("scan8", 1, 0, "Deep Lore: Weapon Plus Program", "Upper Deck", "Deep Lore", "Insert", False, None, "Neutral", "Weapon Plus", 6),
    ("scan8", 1, 1, "Nightshade", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Villain", "Villains for Hire", 5),
    ("scan8", 1, 2, "Stingray", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Hero", "Avengers Allies", 5),
    ("scan8", 2, 0, "Beast", "Topps Chrome", "Base", "Wave Refractor", False, None, "Hero", "X-Men", 16),
    ("scan8", 2, 1, "Bats", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Neutral", "Iron Fist Supporting Cast", 5),
    ("scan8", 2, 2, "Black Cat", "Topps Chrome", "Base", "Base", False, None, "Anti-Hero", "Spider-Man Allies", 9),

    # ── scan9 : Callisto / Squirrel Girl / Echo page ────────────────────────
    ("scan9", 0, 0, "Callisto", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Anti-Hero", "Morlocks", 5),
    ("scan9", 0, 1, "Wasp", "Upper Deck", "Women of Marvel", "Insert", False, None, "Hero", "Avengers", 7),
    ("scan9", 0, 2, "GLX-Mas #1", "Upper Deck", "Monumental Covers", "Insert", False, None, "Neutral", "Guardians of the Galaxy", 6),
    ("scan9", 1, 0, "Hobgoblin", "Topps Chrome", "Base", "Base", False, None, "Villain", "Spider-Man Villains", 7),
    ("scan9", 1, 1, "Squirrel Girl", "Upper Deck", "Women of Marvel", "Insert", False, None, "Hero", "Avengers", 8),
    ("scan9", 1, 2, "Polaris", "Upper Deck", "Women of Marvel", "Insert", False, None, "Hero", "X-Men", 6),
    ("scan9", 2, 0, "Venom", "Topps Chrome", "Base", "Base", False, None, "Anti-Hero", "Symbiotes", 10),
    ("scan9", 2, 1, "Jean Grey", "Upper Deck", "Women of Marvel", "Insert", False, None, "Hero", "X-Men", 7),
    ("scan9", 2, 2, "Echo", "Upper Deck", "Women of Marvel", "Insert", False, None, "Hero", "Avengers Allies", 6),

    # ── scan10 : Scream / Psylocke / Ant-Man page ───────────────────────────
    ("scan10", 0, 0, "Scream", "Topps Chrome", "Base", "Base", False, None, "Villain", "Symbiotes", 6),
    ("scan10", 0, 1, "Invisible Woman", "Topps Chrome", "65 Fantastic Years", "Refractor", False, None, "Hero", "Fantastic Four", 14),
    ("scan10", 0, 2, "Dazzler", "Topps Chrome", "Base", "Base", False, None, "Hero", "X-Men", 7),
    ("scan10", 1, 0, "Wave", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Anti-Hero", "Ultimates", 6),
    ("scan10", 1, 1, "Psylocke", "Topps Chrome", "Base", "Base", False, None, "Hero", "X-Men", 9),
    ("scan10", 1, 2, "Ant-Man", "Topps Chrome", "Base", "Base", False, None, "Hero", "Avengers", 8),
    ("scan10", 2, 0, "The Maker", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Villain", "Maker/Reed Richards", 6),
    ("scan10", 2, 1, "Echo", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Hero", "Avengers Allies", 6),
    ("scan10", 2, 2, "Beast", "Topps Chrome", "Base", "Base", False, None, "Hero", "X-Men", 8),

    # ── scan11 : Human Torch / X-23 / Green Goblin page ─────────────────────
    ("scan11", 0, 0, "Human Torch", "Topps Chrome", "65 Fantastic Years", "Refractor", False, None, "Hero", "Fantastic Four", 14),
    ("scan11", 0, 1, "Proteus", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Villain", "X-Men Villains", 6),
    ("scan11", 0, 2, "Gorilla Girl", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Anti-Hero", "X-Statix", 5),
    ("scan11", 1, 0, "Ghost Riders Unite", "Topps Chrome", "Meanwhile", "Insert", False, None, "Neutral", "Ghost Rider", 7),
    ("scan11", 1, 1, "X-23", "Topps Chrome", "Base", "Base", False, None, "Anti-Hero", "X-Men", 9),
    ("scan11", 1, 2, "Deep Lore: Weapon Plus Program", "Upper Deck", "Deep Lore", "Insert", False, None, "Neutral", "Weapon Plus", 6),
    ("scan11", 2, 0, "One World Under Doom", "Topps Chrome", "One World Under Doom", "Insert", False, None, "Neutral", "Doom's Earth (Event)", 7),
    ("scan11", 2, 1, "The Human Torch", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Hero", "Fantastic Four", 6),
    ("scan11", 2, 2, "Green Goblin", "Upper Deck", "Marvel Beginnings", "Insert", False, None, "Villain", "Spider-Man Villains", 6),
]

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
    })

with open("cards.json", "w") as f:
    json.dump(out, f, indent=2)

print(f"wrote {len(out)} cards to cards.json")
