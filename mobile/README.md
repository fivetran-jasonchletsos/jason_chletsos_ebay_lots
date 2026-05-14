# Harpua Scanner — React Native (Expo)

Local-first mobile inventory app for sports/trading card resellers. Snap a
card, get back identification + market pricing in seconds, store in
on-device SQLite, list on eBay (phase 4).

## What's built (phase 1–3)

- **Camera** (`expo-camera`) — single-hand UX, optional front + back capture
- **Claude vision identification** — same prompt + JSON schema as the web
  scanner so rows stay compatible across both surfaces
- **Pricing** — Pokemon TCG API (free, no key) for TCGplayer + Cardmarket
- **Local inventory** — `expo-sqlite`, full-text-ish search, filter by
  draft/listed/foil
- **Image storage** — `expo-file-system` under app document directory;
  images move from cache → permanent on save; thumbnail for list view
- **Card detail** — edit list price, condition, notes; eBay-sold link;
  delete with image cleanup
- **Settings** — Anthropic key in `expo-secure-store` (Keychain /
  encrypted prefs), model + capture quality picker

## What's stubbed (phase 4–5)

- **List on eBay** — opens an eBay sold-search; phase 4 will wire
  `AddFixedPriceItem` against your existing Trading API auth in
  `../configuration.json`
- **Backend sync** — fields exist on the schema (`sync_status`,
  `synced_at`); phase 5 will choose between Cloudflare Worker → repo
  commit vs. Supabase

## Run it

### On a real iPhone (recommended)

```bash
cd mobile
npm install
npx expo start
```

Scan the QR code with the iPhone's Camera app. Requires the
**Expo Go** app from the App Store.

### iOS simulator

```bash
npx expo start --ios   # requires Xcode
```

### Android emulator

```bash
npx expo start --android   # requires Android Studio
```

## First-time setup

1. Open **Settings** tab
2. Paste your Anthropic API key (get one at
   [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys))
3. Pick a model — Sonnet 4.6 is the default and recommended (~$0.005/scan)
4. Go to the **Scan** tab → allow camera → frame card → tap the gold shutter

## Project layout

```
mobile/
├── app/                          # expo-router file-based routes
│   ├── _layout.tsx              # root: theme + DB init
│   ├── (tabs)/_layout.tsx       # bottom-tab nav
│   ├── (tabs)/index.tsx         # Scan
│   ├── (tabs)/inventory.tsx     # Inventory list
│   ├── (tabs)/settings.tsx      # Settings
│   └── card/[id].tsx            # Card detail
├── src/
│   ├── theme.ts                 # dark luxe palette (matches web)
│   ├── db.ts                    # SQLite schema + CRUD
│   ├── image-store.ts           # FS persistence + thumb generation
│   ├── settings.ts              # SecureStore wrappers
│   └── api/
│       ├── identify.ts          # Claude vision call
│       └── pricing.ts           # Pokemon TCG API call
└── app.json                     # Expo config (camera + iOS bundle id)
```

## Notes

- The SQLite schema is intentionally a superset of the web scanner's
  localStorage shape — sync between the two is a future task
- Images live in app sandbox; uninstalling the app deletes the inventory.
  Phase 5 sync will fix this
- The `condition_hints` field captures Claude's free-form notes about
  visible defects — useful but not authoritative; treat as a hint, not a
  grading
