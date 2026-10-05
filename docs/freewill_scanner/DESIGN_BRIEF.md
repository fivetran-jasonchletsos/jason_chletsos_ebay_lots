# Free Will Art Collective — scanner + storefront (clone of freewillglass.com)

Brand: **Free Will Art Collective** — smoke shop + glass gallery, Ardmore PA.
Tagline: **CREATIVITY. CULTURE. COMMUNITY. ARDMORE.**
Blurb: "Clothing, jewelry, and hemp-inspired goods curated for community, creativity, and conscious living."
Contact: (610) 612-9062 · Ardmore, PA · Instagram / Facebook / TikTok.

## Visual spec (match the real site)
- Palette: near-black bg (#0b0b0d), white text (#f5f5f2), **gold accent (#c9a24b / #d4af37)**. Keep it dark, premium, gallery-like.
- Fonts: clean modern sans-serif (system stack or Google "Inter"/"Oswald" for headers). Uppercase, letter-spaced headers.
- Layout: centered logo/wordmark header, nav for the 4 categories, hero with the tagline + CTA, **3-column responsive product grid** (cards: image, brand, name, price, in-stock chip), footer with contact + Ardmore + social links.

## Categories
Glass Gallery · Clothing · Incense & Candles · Jewelry

## Architecture (reuse the family-scanner pattern — see docs/big_blue_scanner/)
- Shared vision Lambda base: `https://jw0hur2091.execute-api.us-east-1.amazonaws.com/ebay`
- Scanner: capture product photo -> downscale client-side to 1280px JPEG dataURL -> POST `/upload-photos` with `{image, mode:"product"}` -> returns `{success, identified, product:{name,category,price,brand,desc}}` -> then POST `/freewill-save` with `{image, product, scannedAt}` to append to products.json.
- Storefront index.html renders products.json in the grid, filterable by category.
- data file: docs/freewill_scanner/products.json (seeded with 4 sample items).
