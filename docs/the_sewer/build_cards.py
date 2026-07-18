"""Build cards.json for The Sewer (Amanda's Marvel showcase) from catalogued scans."""
import json

# (scan, row, col, name, brand, series, cardType, firstApp, serial, alignment, team, estValue)
CARDS = [
    # ── scan1 : Sabretooth / Cable / Human Torch page ───────────────────────
    ("scan1", 0, 0, "Sabretooth", "Topps Chrome", "Base", "Sparkle Parallel", False, None, "Villain", "X-Men Villains", 10),
    ("scan1", 0, 1, "Venomizer", "Topps Chrome", "Base", "Wave Refractor", True, None, "Anti-Hero", "Symbiotes", 14),
    ("scan1", 0, 2, "Minutemen in Pursuit", "Topps Chrome", "Historical Moments", "Insert", False, None, "Neutral", "Historical/Event", 6),
    ("scan1", 1, 0, "Hulk", "Topps Chrome", "The Beyond", "Insert", False, None, "Hero", "Avengers", 8),
    ("scan1", 1, 1, "Omega Red", "Topps Chrome", "Base", "Wave Refractor", False, None, "Villain", "X-Men Villains", 14),
    ("scan1", 1, 2, "Daredevil", "Topps Chrome", "Icons", "Insert", False, None, "Hero", "Defenders", 9),
    ("scan1", 2, 0, "Cowboypool", "Topps Chrome", "Future Stars", "Insert", False, None, "Anti-Hero", "Deadpool Multiverse", 7),
    ("scan1", 2, 1, "Cable", "Topps Chrome", "Base", "Comic Book Gold", False, None, "Hero", "X-Force", 18),
    ("scan1", 2, 2, "Human Torch", "Topps Chrome", "65 Fantastic Years", "Refractor", False, None, "Hero", "Fantastic Four", 14),

    # ── scan2 : Psylocke / Deadpool movie page ──────────────────────────────
    ("scan2", 0, 0, "Psylocke", "Topps Chrome", "Base", "Green Refractor", False, "30/99", "Hero", "X-Men", 22),
    ("scan2", 0, 1, "Magnet Trap", "Topps Chrome Deadpool & Wolverine", "Movie Scene", "Insert", False, None, "Neutral", "Movie Scene", 5),
    ("scan2", 0, 2, "Pyro", "Topps Chrome", "Base", "Base", False, None, "Villain", "Brotherhood", 6),
    ("scan2", 1, 0, "Deadpool", "Topps Chrome Deadpool & Wolverine", "Base", "Base", False, None, "Anti-Hero", "X-Force", 8),
    ("scan2", 1, 1, "Advanced Weaponry", "Topps Chrome Deadpool & Wolverine", "Movie Scene", "Insert", False, None, "Neutral", "Movie Scene", 5),
    ("scan2", 1, 2, "Special Delivery", "Topps Chrome Deadpool & Wolverine", "Movie Scene", "Insert", False, None, "Neutral", "Movie Scene", 5),
    ("scan2", 2, 0, "Peter", "Topps Chrome Deadpool & Wolverine", "Base", "Base", False, None, "Neutral", "Movie Supporting Cast", 4),
    ("scan2", 2, 1, "All or Nothing", "Topps Chrome Deadpool & Wolverine", "Movie Scene", "Insert", False, None, "Neutral", "Movie Scene", 5),
    ("scan2", 2, 2, "Variant Madness", "Topps Chrome Deadpool & Wolverine", "Movie Scene", "Insert", False, None, "Neutral", "Movie Scene", 5),

    # ── scan3 : Aftermath / Iron Man / Man-Thing page ───────────────────────
    ("scan3", 0, 0, "Aftermath", "Topps Chrome Deadpool & Wolverine", "Movie Scene", "Insert", False, None, "Neutral", "Movie Scene", 5),
    ("scan3", 0, 1, "Luna Snow", "Topps Chrome", "Base", "Refractor", False, None, "Hero", "Agents of Atlas", 11),
    ("scan3", 0, 2, "Kraven the Hunter", "Topps Chrome", "Base", "Base", False, None, "Villain", "Spider-Man Villains", 7),
    ("scan3", 1, 0, "Sleeper Agent", "Topps Chrome", "Base", "Base", False, None, "Villain", "Hydra", 6),
    ("scan3", 1, 1, "Nightdrifter", "Topps Chrome", "Base", "Base", True, None, "Anti-Hero", "New Character", 8),
    ("scan3", 1, 2, "Goblin Queen", "Topps Chrome", "Base", "Base", False, None, "Villain", "Green Goblin Family", 7),
    ("scan3", 2, 0, "Iron Man", "Topps Chrome", "Base", "Base", False, None, "Hero", "Avengers", 9),
    ("scan3", 2, 1, "Silence", "Topps Chrome", "Base", "Base", False, None, "Anti-Hero", "Symbiotes", 6),
    ("scan3", 2, 2, "Man-Thing", "Topps Chrome", "Base", "Base", False, None, "Neutral", "Midnight Sons", 6),

    # ── scan4 : Professor X / Hulk / Spider-Man 2099 page ───────────────────
    ("scan4", 0, 0, "Professor X", "Topps Chrome", "Base", "Base", False, None, "Hero", "X-Men", 9),
    ("scan4", 0, 1, "Baron Zemo", "Topps Chrome", "Base", "Base", False, None, "Villain", "Thunderbolts", 7),
    ("scan4", 0, 2, "Carnage", "Topps Chrome", "Base", "Base", False, None, "Villain", "Symbiotes", 8),
    ("scan4", 1, 0, "Infernal Hulk", "Topps Chrome", "Base", "Base", True, None, "Anti-Hero", "Avengers", 9),
    ("scan4", 1, 1, "Hallows' Eve", "Topps Chrome", "Base", "Base", False, None, "Anti-Hero", "Moon Knight Family", 6),
    ("scan4", 1, 2, "Jeff the Land Shark", "Topps Chrome", "Base", "Base", False, None, "Neutral", "Guardians Adjacent", 6),
    ("scan4", 2, 0, "Hulk", "Topps Chrome", "Base", "Base", False, None, "Hero", "Avengers", 9),
    ("scan4", 2, 1, "Rocket Raccoon", "Topps Chrome", "Base", "Base", False, None, "Hero", "Guardians of the Galaxy", 7),
    ("scan4", 2, 2, "Spider-Man 2099", "Topps Chrome", "Base", "Base", False, None, "Hero", "Spider-Society", 9),

    # ── scan5 : Iceman / Rhino / Black Widow page ───────────────────────────
    ("scan5", 0, 0, "Iceman", "Topps Chrome", "Base", "Base", False, None, "Hero", "X-Men", 7),
    ("scan5", 0, 1, "Dazzler", "Topps Chrome", "Base", "Base", False, None, "Hero", "X-Men", 7),
    ("scan5", 0, 2, "Dormammu", "Topps Chrome", "Base", "Base", False, None, "Villain", "Dread Dimension", 8),
    ("scan5", 1, 0, "Mister Fantastic", "Topps Chrome", "Base", "Base", False, None, "Hero", "Fantastic Four", 8),
    ("scan5", 1, 1, "Rhino", "Topps Chrome", "Base", "Base", False, None, "Villain", "Spider-Man Villains", 6),
    ("scan5", 1, 2, "Rek-Rap", "Topps Chrome", "Base", "Base", False, None, "Villain", "Spider-Man Villains", 5),
    ("scan5", 2, 0, "Ghost-Spider", "Topps Chrome", "Base", "Base", False, None, "Hero", "Spider-Society", 8),
    ("scan5", 2, 1, "Emma Frost", "Topps Chrome", "Base", "Base", False, None, "Anti-Hero", "X-Men", 8),
    ("scan5", 2, 2, "Black Widow", "Topps Chrome", "Base", "Base", False, None, "Hero", "Avengers", 9),

    # ── scan6 : Nova / Deadpool movie / Ready for Round 2 page ──────────────
    ("scan6", 0, 0, "Nova", "Topps Chrome", "Base", "Base", False, None, "Hero", "Avengers", 7),
    ("scan6", 0, 1, "Blind Al", "Topps Chrome Deadpool & Wolverine", "Base", "Base", False, None, "Neutral", "Movie Supporting Cast", 4),
    ("scan6", 0, 2, "Mercenary Melee", "Topps Chrome Deadpool & Wolverine", "Movie Scene", "Insert", False, None, "Neutral", "Movie Scene", 5),
    ("scan6", 1, 0, "A Fiery Entrance", "Topps Chrome Deadpool & Wolverine", "Movie Scene", "Insert", False, None, "Neutral", "Movie Scene", 5),
    ("scan6", 1, 1, "Nightcrawler", "Topps Chrome Deadpool & Wolverine", "Deadpool Icons", "Insert", False, None, "Hero", "X-Men", 10),
    ("scan6", 1, 2, "Into Logan's Mind", "Topps Chrome Deadpool & Wolverine", "Movie Scene", "Insert", False, None, "Neutral", "Movie Scene", 5),
    ("scan6", 2, 0, "Weapon X", "Topps Chrome Deadpool & Wolverine", "Base", "Base", False, None, "Anti-Hero", "X-Men Legacy", 8),
    ("scan6", 2, 1, "Wade Wilson", "Topps Chrome Deadpool & Wolverine", "Base", "Base", False, None, "Anti-Hero", "X-Force", 7),
    ("scan6", 2, 2, "Ready for Round 2", "Topps Chrome Deadpool & Wolverine", "Movie Scene", "Insert", False, None, "Neutral", "Movie Scene", 5),

    # ── scan7 : Deadpool Icons / Kingpin / Invisible Woman page ─────────────
    ("scan7", 0, 0, "Deadpool", "Topps Chrome Deadpool & Wolverine", "Deadpool Icons", "Insert", False, None, "Anti-Hero", "X-Force", 11),
    ("scan7", 0, 1, "Quill", "Topps Chrome Deadpool & Wolverine", "Base", "Base", False, None, "Hero", "Movie Character", 5),
    ("scan7", 0, 2, "Domino", "Topps Chrome Deadpool & Wolverine", "Base", "Base", False, None, "Anti-Hero", "X-Force", 8),
    ("scan7", 1, 0, "The Scheming Mr. Paradox", "Topps Chrome Deadpool & Wolverine", "Base", "Base", False, None, "Villain", "Movie Character", 5),
    ("scan7", 1, 1, "Scarlet Witch", "Topps Chrome", "Icons", "Refractor", False, None, "Villain", "Avengers", 15),
    ("scan7", 1, 2, "Mister Sinister", "Topps Chrome", "Base", "Base", False, None, "Villain", "X-Men Villains", 7),
    ("scan7", 2, 0, "Kingpin", "Topps Chrome", "Base", "Base", False, None, "Villain", "Daredevil Villains", 12),
    ("scan7", 2, 1, "Captain Britain", "Topps Chrome", "Base", "Refractor", False, None, "Hero", "Excalibur", 13),
    ("scan7", 2, 2, "Invisible Woman", "Topps Chrome", "Base", "Base", False, None, "Hero", "Fantastic Four", 8),

    # ── scan8 : Daredevil / Gambit / Valeria Richards page ──────────────────
    ("scan8", 0, 0, "Daredevil", "Topps Chrome", "Base", "Base", False, None, "Hero", "Defenders", 8),
    ("scan8", 0, 1, "Mantis", "Topps Chrome", "Base", "Base", False, None, "Hero", "Guardians of the Galaxy", 7),
    ("scan8", 0, 2, "Dark Gwenpool", "Topps Chrome", "Base", "Base", True, None, "Anti-Hero", "New Character", 9),
    ("scan8", 1, 0, "Spider-Punk", "Topps Chrome", "Base", "Base", False, None, "Hero", "Spider-Society", 9),
    ("scan8", 1, 1, "Spider-Woman", "Topps Chrome", "Base", "Base", False, None, "Hero", "Avengers", 8),
    ("scan8", 1, 2, "Gambit", "Topps Chrome", "Base", "Base", False, None, "Hero", "X-Men", 8),
    ("scan8", 2, 0, "Glob", "Topps Chrome", "Base", "Base", False, None, "Villain", "Brotherhood", 5),
    ("scan8", 2, 1, "Rasputin IV", "Topps Chrome", "Base", "Base", False, None, "Anti-Hero", "X-Men Adjacent", 6),
    ("scan8", 2, 2, "Valeria Richards", "Topps Chrome", "65 Fantastic Years", "Refractor", False, None, "Hero", "Fantastic Four", 13),
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
