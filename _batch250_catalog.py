"""Catalog of scans 252-261 (~90 cards) read from the sheets, with de-dup against
the cached listings snapshot. Prints NEW vs LIKELY-ALREADY-LISTED so we only plan
to post cards that aren't already live. (Live API check deferred: Trading call
limit hit; will re-verify before posting.)"""
import json, re
from pathlib import Path

# (scan, idx, player, product, parallel, rc, dedup_keys)
C = [
 # Scan 252
 (252,1,"Dalton Kincaid","Panini Revolution","",0),
 (252,2,"Evan Engram","Prizm","",0),
 (252,3,"Puka Nacua","Select","Turbocharged",0),
 (252,4,"L'Jarius Sneed","Prizm","",0),
 (252,5,"Arian Smith","Select","",1),
 (252,6,"Jalen Milroe","Select","",1),
 (252,7,"Khalil Mack","Prizm","",0),
 (252,8,"Jakobi Meyers","Select","",0),
 (252,9,"Jake Ferguson","Select","",0),
 # Scan 253
 (253,1,"Shedeur Sanders","Prizm","",1),
 (253,2,"CeeDee Lamb","Select","",0),
 (253,3,"Tee Higgins","Mosaic","",0),
 (253,4,"Tory Horton","Topps Cosmic","Round 6 Pick 30",1),
 (253,5,"Tre Harris","Topps Cosmic","Round 2 Pick 23",1),
 (253,6,"Michael Irvin","Mosaic","Touchdown Masters",0),
 (253,7,"Tate Ratledge","Topps Cosmic","Round 2 Pick 26",1),
 (253,8,"Cedric Tillman","Mosaic","",0),
 (253,9,"Derek Stingley Jr","Mosaic","Epic Performers",0),
 # Scan 254 — ALL Mike Evans
 (254,1,"Mike Evans","Donruss","",0),
 (254,2,"Mike Evans","Topps Cosmic","Round 1 Pick 7",0),
 (254,3,"Mike Evans","Prizm","",0),
 (254,4,"Mike Evans","Select","",0),
 (254,5,"Mike Evans","Mosaic","",0),
 (254,6,"Mike Evans","Prizm Draft","Red Cracked Ice",0),
 (254,7,"Mike Evans","Totally Certified","",0),
 (254,8,"Mike Evans","Contenders","Season Ticket",0),
 (254,9,"Mike Evans","Prizm Draft","",0),
 # Scan 255
 (255,1,"Mark Andrews","Phoenix","Silver",0),
 (255,2,"Omarion Hampton","Prizm","Green Cracked Ice",1),
 (255,3,"Tate Ratledge","Topps Cosmic","Round 2 Pick 26",1),
 (255,4,"Tai Felton","Mosaic","Elevate",1),
 (255,5,"Kelvin Banks Jr","Prizm","Green",1),
 (255,6,"De'Von Achane","Topps Cosmic","Round 3 Pick 21",0),
 (255,7,"Ashton Jeanty","Prizm","Prizmatic",1),
 (255,8,"Tory Horton","Topps Cosmic","Round 6 Pick 30",1),
 (255,9,"Mike Evans","Topps Cosmic","Round 1 Pick 7",0),
 # Scan 256
 (256,1,"Jordan Addison","Topps Cosmic","Round 1 Pick 23",0),
 (256,2,"Quinn Ewers","Topps Cosmic","Round 7 Pick 15",1),
 (256,3,"Braelon Allen","Prizm","",0),
 (256,4,"Jaylen Warren","Topps Cosmic","Undrafted",0),
 (256,5,"Trey McBride","Topps Cosmic","Round 2 Pick 23",0),
 (256,6,"Kwity Paye","Prizm","",0),
 (256,7,"Nico Collins","Topps Cosmic","Round 3 Pick 25",0),
 (256,8,"C.J. Stroud","Prizm","",0),
 (256,9,"Keyshawn Johnson","Prizm","",0),
 # Scan 257
 (257,1,"Josh Jacobs","Prizm","",0),
 (257,2,"Dawson Knox","Prizm","",0),
 (257,3,"Stefon Diggs","Mosaic","",0),
 (257,4,"Jaydon Blue","Prizm","",1),
 (257,5,"Pat Bryant","Prizm","",1),
 (257,6,"Woody Marks","Mosaic","Green",1),
 (257,7,"Tony Dorsett","Prizm","",0),
 (257,8,"Mike Gesicki","Mosaic","",0),
 (257,9,"Nick Emmanwori","Mosaic","Purple",1),
 # Scan 258 — Stafford heavy
 (258,1,"Breece Hall","Panini Revolution","",0),
 (258,2,"Matthew Stafford","Contenders","Season Ticket",0),
 (258,3,"Brock Bowers","Prizm","",0),
 (258,4,"Matthew Stafford","Mosaic","",0),
 (258,5,"Matthew Stafford","Prizm","",0),
 (258,6,"Matthew Stafford","Contenders","Season Ticket",0),
 (258,7,"Matthew Stafford","Mosaic","Silver",0),
 (258,8,"Tai Felton","Select","",1),
 (258,9,"Matthew Stafford","Prizm","Black",0),
 # Scan 259
 (259,1,"Jared Goff","Prizm","Red White Blue",0),
 (259,2,"Breece Hall","Prizm","",0),
 (259,3,"Puka Nacua","Prizm","",0),
 (259,4,"Tremaine Edmunds","Prizm","",0),
 (259,5,"Nick Bosa","Prizm","",0),
 (259,6,"DJ Giddens","Prizm","",1),
 (259,7,"Marshon Lattimore","Prizm","",0),
 (259,8,"Hines Ward","Prizm","",0),
 (259,9,"T.J. Watt","Optic","Light It Up",0),
 # Scan 260
 (260,1,"Derwin James Jr","Prizm","Green",0),
 (260,2,"RJ Harvey","Prizm","Emergent",1),
 (260,3,"DeAndre Hopkins","Topps Cosmic","Round 1 Pick 27",0),
 (260,4,"Caleb Williams","Prizm","Global Reach",0),
 (260,5,"Jacory Croskey-Merritt","Topps Cosmic","Round 7 Pick 23",1),
 (260,6,"Tyler Baron","Topps Cosmic","Round 5 Pick 38",1),
 (260,7,"Mike Vrabel","Prizm","Green",0),
 (260,8,"Jonah Savaiinaea","Topps Cosmic","Round 2 Pick 5",1),
 (260,9,"Michael Penix Jr","Topps Cosmic","Round 1 Pick 8",1),
 # Scan 261
 (261,1,"Jordan James","Mosaic","Green",1),
 (261,2,"Derwin James Jr","Mosaic","",0),
 (261,3,"Jamal Anderson","Mosaic","",0),
 (261,4,"Jayden Daniels","Mosaic","Touchdown Masters",0),
 (261,5,"Cam Ward","Topps","Notoriety",1),
 (261,6,"Derwin James Jr","Mosaic","",0),
 (261,7,"Eric Allen","Mosaic","Hall of Fame Green",0),
 (261,8,"Dwight Freeney","Mosaic","Green",0),
 (261,9,"Matthew Stafford","Select","",0),
]

snap=json.loads(Path("output/listings_snapshot.json").read_text())
L = snap.get("listings",snap) if isinstance(snap,dict) else snap
titles=[ (x.get("title") or "").lower() for x in L ]

def surname(p):
    p=p.replace(" Jr","").replace(" Sr","").strip()
    return p.split()[-1].lower()

print(f"{'CARD':46} {'PRODUCT/PARALLEL':30} VERDICT")
print("-"*100)
new=[]; listed=[]
for scan,idx,player,prod,par,rc in C:
    sn=surname(player)
    prodwords=[w for w in (prod.lower().split()+par.lower().split()) if len(w)>3]
    # a listing "matches" if it has the surname AND at least one product/parallel word
    matches=[t for t in titles if sn in t and (not prodwords or any(w in t for w in prodwords))]
    verdict = "LISTED?" if matches else "NEW"
    (listed if matches else new).append((scan,idx,player,prod,par,rc))
    tag=f"{player} ({scan}_{idx})"
    print(f"{tag:46} {prod+' '+par:30} {verdict}  {('['+matches[0][:40]+']') if matches else ''}")
print("-"*100)
print(f"NEW (plan to post): {len(new)}   LISTED?/review: {len(listed)}   total {len(C)}")
json.dump({"new":new,"listed":listed}, open("output/_batch250_dedup.json","w"))
