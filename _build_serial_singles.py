"""Build front+back listing images for the 4 serialized singles (Scans 219/220)
and write a post_from_scan batch. Geno Multiverse relic is a landscape card
scanned sideways, so rotate it upright.
"""
import json
from pathlib import Path
from PIL import Image
Image.MAX_IMAGE_PIXELS = None

F = Path("output/split_cards/Scan 219")   # fronts
B = Path("output/split_cards/Scan 220")   # backs
OUT = Path("output"); OUT.mkdir(exist_ok=True)

# idx (1-based, L-R T-B), key, front_rot, back_rot, title, price
# Landscape card scanned sideways: front needs CW (ROTATE_270), back needs the
# opposite (ROTATE_90) since flipping the card reverses orientation.
CARDS = [
    (1, "geno_multiverse", Image.ROTATE_270, Image.ROTATE_90,
     "2025 Panini Select Multiverse Geno Smith Dual Jersey Relic Seahawks Raiders Prizm",
     17.99),
    (2, "mike_green_rc", None, None,
     "2025 Panini Select Mike Green RC 461/699 Club Level Prizm Ravens Football",
     12.99),
    (3, "shemar_turner_rc", None, None,
     "2025 Topps Signature Class Shemar Turner RC 059/275 Round 2 Pick 30 Bears Football",
     9.99),
    (4, "tyleik_williams_rc", None, None,
     "2025 Panini Select Tyleik Williams RC 121/899 Premier Level Prizm Lions Football",
     12.99),
]

def load(p, rotate):
    im = Image.open(p).convert("RGB")
    if rotate is not None:
        im = im.transpose(rotate)
    return im

def combine(front, back, out):
    h = 1000
    fs = front.resize((int(front.width * h / front.height), h))
    bs = back.resize((int(back.width * h / back.height), h))
    pad = 24
    canvas = Image.new("RGB", (fs.width + bs.width + pad * 3, h + pad * 2), "white")
    canvas.paste(fs, (pad, pad))
    canvas.paste(bs, (fs.width + pad * 2, pad))
    canvas.save(out, "JPEG", quality=92)
    return out

batch = []
for idx, key, frot, brot, title, price in CARDS:
    front = load(F / f"Scan 219_{idx:02d}.jpg", frot)
    back = load(B / f"Scan 220_{idx:02d}.jpg", brot)
    out = OUT / f"_single_{key}.jpg"
    combine(front, back, out)
    batch.append({"image": str(out), "title": title, "price": price})
    print(f"built {out.name}  ${price}  {title[:60]}")

Path("output/_batch_serial_singles.json").write_text(json.dumps(batch, indent=2))
print("\nwrote output/_batch_serial_singles.json")
