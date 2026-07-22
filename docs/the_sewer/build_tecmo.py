"""Build tecmo_cards.json for The Sewer's Tecmo Bowl: Bo Jackson Battle Arena page.

Two card kinds live in this set:
  - Hero cards: name, power, element (Steel/Fire/Ice/Brawl), firstEdition
  - Play cards: name, cost, effect text, firstEdition

Add future scans the same way as crop_scans.py/build_cards.py: run
crop_tecmo.py on the new page, then append rows here.
"""
import json

# (scan, row, col, kind, name, firstEd, power/cost, element, effect, estValue)
CARDS = [
    # ── tscan1 : Weapon Mixer page (7 cards) ────────────────────────────────
    ("tscan1", 0, 0, "Play", "Weapon Mixer", False, 2, None, "Your hero gets +5 for every different weapon type revealed this game.", 2),
    ("tscan1", 0, 1, "Play", "Contract Limitations", False, 1, None, "Your hero gets +15 but you don't draw a play at the start of next battle.", 2),
    ("tscan1", 0, 2, "Play", "Unified Front", True, 2, None, "Your hero gets +15. If all of your currently revealed heroes have the same weapon type, this play costs 0.", 3),
    ("tscan1", 1, 0, "Play", "Frosty Times", True, 1, None, "For the next 3 battles, if you have a hero with an Ice weapon in the active battle, it gets +10.", 3),
    ("tscan1", 1, 1, "Play", "Should Have Tried Harder", True, 0, None, "Only run this play if your opponent has honors. If your opponent has not run any plays this battle, their hero gets -10.", 3),
    ("tscan1", 2, 0, "Play", "10 For A Sub", False, 1, None, "If you substituted this battle, your hero gets +10.", 2),
    ("tscan1", 2, 1, "Play", "Hollow Bat", False, 2, None, "Roll a dice. If it lands on 3-6, your hero gets +25. If it lands on 1 or 2, your hero gets -25.", 2),

    # ── tscan2 : Weapon Lineage page ────────────────────────────────────────
    ("tscan2", 0, 0, "Play", "Weapon Lineage", False, 1, None, "Your current hero gets +10 for every hero in your discard pile with the same weapon type.", 2),
    ("tscan2", 0, 1, "Play", "Steel Smash", False, 1, None, "If your hero has a Steel weapon, flip a coin. If it's heads, your hero gets +20.", 2),
    ("tscan2", 0, 2, "Play", "Target Acquired", True, 1, None, "Name a weapon type. Opponent's hero in the next battle loses -15 if it has that type.", 3),
    ("tscan2", 1, 0, "Play", "Flip Ya For 2 Plays", False, 0, None, "Flip a coin: if heads, you draw 2 plays. If tails, your opponent draws 2 plays.", 2),
    ("tscan2", 1, 1, "Play", "Hot Dog Flip Out", True, 0, None, "Flip a coin 3 times. For each heads, your hero gets +5. For each tails, lose 1 hot dog.", 3),
    ("tscan2", 1, 2, "Play", "Power Pick", False, 2, None, "Reveal the top 3 plays of your playbook. Add 1 to your hand and discard the rest. If it's a play with a cost of 3 or higher, your hero gets +10.", 2),
    ("tscan2", 2, 0, "Play", "Win The Toss", False, 1, None, "Flip a coin: if heads, run the top play from your playbook in this battle for free (0 hot dog cost).", 2),
    ("tscan2", 2, 1, "Play", "Protein Bar", False, 2, None, "Your hero gets +15. If you lose this battle, recover 1 hot dog.", 2),
    ("tscan2", 2, 2, "Play", "Late Hit", False, 1, None, "This must be used in Battle 7. Your opponent's hero gets -35.", 2),

    # ── tscan3 : To Fight Another Day page ──────────────────────────────────
    ("tscan3", 0, 0, "Play", "To Fight Another Day", False, 2, None, "If you lost the previous battle, your hero in the active battle gets +20.", 2),
    ("tscan3", 0, 1, "Play", "Buff Or Debuff", False, 2, None, "After paying this play's cost, if your opponent has more hot dogs than you, your hero gets +15. If you have more than them, their hero gets -15.", 2),
    ("tscan3", 0, 2, "Play", "Flaming Flip", False, 1, None, "Discard a hero with a Fire weapon from your hand and flip a coin. If it's heads, your hero gets +20.", 2),
    ("tscan3", 1, 0, "Play", "Icevantage", False, 1, None, "If your opponent's hero has an Ice weapon, your hero gets +15.", 2),
    ("tscan3", 1, 1, "Play", "Heads I Win, Tails You Lose", False, 1, None, "Flip a coin: if heads, your hero gets +15. If tails, your opponent's hero loses -5.", 2),
    ("tscan3", 1, 2, "Play", "Lucky 7", False, 0, None, "Roll a die two times; if the numbers add up to 7, your hero gets +100; if any other number, you must discard a random hero from your hand.", 2),
    ("tscan3", 2, 0, "Play", "Indestructible", False, 1, None, "This hero can't have its power reduced by an opponent's play.", 2),
    ("tscan3", 2, 1, "Play", "Frontload", True, 1, None, "If your hero in the next battle has a Steel weapon, it gets +15.", 3),
    ("tscan3", 2, 2, "Play", "Over Under", False, 2, None, "Send 2 heroes from your hand to your discard pile. Draw 1 play and 1 hero.", 2),

    # ── tscan4 : Forced Retreat page ────────────────────────────────────────
    ("tscan4", 0, 0, "Play", "Forced Retreat", False, 2, None, "Your opponent must discard their current hero, and replace it with one from their hand.", 2),
    ("tscan4", 0, 1, "Play", "High Stakes Pump-Up", False, 0, None, "Your hero gets +10. If you lose this battle, your hero in the next battle gets -20.", 2),
    ("tscan4", 0, 2, "Play", "Pre-Game Ritual", False, 1, None, "Flip a coin 3 times; your hero gets +15 if the coin lands on heads 2 or more times.", 2),
    ("tscan4", 1, 0, "Play", "Dead Red", False, 3, None, "Name a weapon type. Now and for the rest of the game, if your opponent's hero has that weapon type, they get -10. Otherwise, you discard 1 play.", 2),
    ("tscan4", 1, 1, "Play", "Substitution Boost", False, 0, None, "For the rest of the game, any hero that has been substituted in gets +5.", 2),
    ("tscan4", 1, 2, "Play", "Stain-less-Steel", False, 2, None, "If your opponent's hero has a Steel weapon, give it -15.", 2),
    ("tscan4", 2, 0, "Play", "Prevent D", False, 3, None, "Your opponent can't run any plays in Battle 7.", 2),
    ("tscan4", 2, 1, "Play", "Pass The Flame", True, 1, None, "If your hero has a Fire weapon, your next hero gets +10.", 3),
    ("tscan4", 2, 2, "Play", "Chrome Will", False, 1, None, "If your hero has a Steel weapon, it can't drop below its current power.", 2),

    # ── tscan5 : Tiebreaker Takedown page (2 hero cards mixed in) ───────────
    ("tscan5", 0, 0, "Play", "Tiebreaker Takedown", True, 2, None, "If both players have the same number of hot dogs before you used this play, your opponent's hero gets -20. If not, they get -10.", 3),
    ("tscan5", 0, 1, "Hero", "Hot Sauce", True, 95, "Steel", None, 10),
    ("tscan5", 0, 2, "Play", "Radiant Comeback", False, 2, None, "Swap your hero with a Glow weapon hero in your discard pile.", 2),
    ("tscan5", 1, 0, "Play", "Fairweather Fan", False, 1, None, "Play this in Battle 5 or later. Your hero gets +5 for each battle you've won.", 2),
    ("tscan5", 1, 1, "Play", "Double Down", False, 0, None, "Flip a coin twice. If it lands on heads both times, your hero gets +20. If both flips are tails, your hero loses -40. (Nothing happens for any other result.)", 2),
    ("tscan5", 1, 2, "Play", "Jump Ball", False, 0, None, "Flip a coin: if heads, your hero gets +10. If tails, your hero gets -10.", 2),
    ("tscan5", 2, 0, "Hero", "Quads", True, 125, "Steel", None, 6),
    ("tscan5", 2, 1, "Play", "Fire Hose", False, 1, None, "If your opponent's hero has a Fire weapon, your hero gets +15.", 2),
    ("tscan5", 2, 2, "Play", "Ice Blast", False, 1, None, "If your hero has an Ice weapon, flip a coin. If it's heads, your hero gets +20.", 2),

    # ── tscan6 : Hands page (2 hero card parallels mixed in) ────────────────
    ("tscan6", 0, 0, "Hero", "Hands", True, 130, "Steel", None, 14),
    ("tscan6", 0, 1, "Play", "One-and-One", False, 1, None, "Flip a coin. If heads, your hero gets +10. You may do this a second and final time if it lands on heads.", 2),
    ("tscan6", 0, 2, "Play", "Discard Rebate", False, 0, None, "Shuffle a hero from your discard pile back into your hero deck.", 2),
    ("tscan6", 1, 0, "Hero", "Hands", True, 135, "Fire", None, 12),
    ("tscan6", 1, 1, "Play", "Burn The Timeline", True, 0, None, "Discard a hero with a Fire weapon from your hand. If you do, cancel all plays that affect the rest of the game.", 3),
    ("tscan6", 1, 2, "Play", "Forced Substitution", False, 3, None, "Your opponent must pay 2 hot dogs and substitute next battle.", 2),
    ("tscan6", 2, 0, "Play", "Crystal Ball", False, 0, None, "Pick a number 1-6. Then your opponent picks a different number 1-6; roll a die; if it lands on either player's number, their hero gets +30.", 2),
    ("tscan6", 2, 1, "Play", "Bad Chemistry", True, 2, None, "If your opponent's last 2 revealed heroes have different weapon types, your hero gets +15 and you draw 1 play.", 3),
    ("tscan6", 2, 2, "Play", "Revoke The Future", True, 2, None, "Choose one play your opponent has run that affects the rest of the game and cancel it. Your opponent's hero in the active battle gets -15.", 3),
]

out = []
for i, (scan, row, col, kind, name, firstEd, num, element, effect, value) in enumerate(CARDS, start=1):
    entry = {
        "id": i,
        "name": name,
        "image": f"tecmo_images/{scan}_{row}_{col}.jpg",
        "cardType": kind,
        "firstEdition": firstEd,
        "estValue": value,
    }
    if kind == "Hero":
        entry["power"] = num
        entry["element"] = element
    else:
        entry["cost"] = num
        entry["effect"] = effect
    out.append(entry)

with open("tecmo_cards.json", "w") as f:
    json.dump(out, f, indent=2)

print(f"wrote {len(out)} cards to tecmo_cards.json")
