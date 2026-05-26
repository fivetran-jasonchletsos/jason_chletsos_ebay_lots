# Harpua Mobile — Companion app (Expo / React Native)

Local-first mobile app for the harpua2001 eBay store. Two halves:

1. **Card scanner** — snap a Pokémon / sports card, get back Claude-vision
   identification + TCGplayer market price, store in on-device SQLite, list
   on eBay.
2. **Store companion** — pull your live eBay listings, fix thin photo
   galleries from the phone, accept / counter / decline Best Offers, and
   quick-list new (non-card) inventory.

Runs on iPhone, iPad, and Android.

## What's built

**Card scanner**
- Camera (`expo-camera`) — single-hand UX, optional front + back capture.
- Claude vision identification — same prompt + JSON schema as the web
  scanner so rows stay compatible across both surfaces.
- Pricing — Pokémon TCG API (free, no key) for TCGplayer + Cardmarket.
- Local inventory — `expo-sqlite`, draft/listed/foil filters.
- List card to eBay — full `AddFixedPriceItem` + `UploadSiteHostedPictures`
  via the Trading API, with a confirmation gate before the LIVE write.

**Store companion**
- **Listings tab** — `GetMyeBaySelling`, sorted by time-left ascending so
  about-to-expire items bubble up. Pages in more rows as you scroll. Tap
  any listing to see its photo gallery status against the top-seller 8+
  recommendation.
- **Listing detail** — current eBay photos, title, price, condition,
  watchers, view count, Best Offer status. Inline price edit via
  `ReviseFixedPriceItem` (confirmation prompt before live write). Photo
  health readout shows current count vs the top-seller 8+ guideline.
- **Replace photos flow** — camera multi-shot up to 12, tap-to-promote
  cover photo, long-press to remove, then upload via
  `UploadSiteHostedPictures` and replace the gallery via
  `ReviseFixedPriceItem` `<PictureDetails>`. Uploads run concurrently so
  a full 12-photo gallery finishes in seconds, not minutes. Each photo
  is downscaled to 2400px JPEG (top sellers tend to post 1600px+; the
  extra headroom keeps cropping useful).
- **Offers tab** — `GetBestOffers` across all listings, one-tap Accept /
  Counter / Decline via `RespondToBestOffer`. Counter modal pre-fills
  the midpoint between offer and list, charm-priced to `$x.99` just
  above the midpoint so the counter still feels like a real move.
- **Quick list flow** — generic snap-to-list for non-card inventory
  (sealed product, video games, etc.) using the same camera UX as the
  photo-replace flow, with a curated category picker and the standard
  store shipping/return policy.

## Run it

### Real device (recommended)

```bash
cd mobile
npm install
npx expo start
```

Scan the QR with iOS Camera (needs **Expo Go** from the App Store) or the
Android Expo Go app.

### Simulators

```bash
npx expo start --ios       # macOS + Xcode
npx expo start --android   # Android Studio emulator
```

### Sideload / TestFlight (production builds)

```bash
npx eas build --profile preview --platform android   # signed APK to sideload
npx eas build --profile preview --platform ios       # TestFlight build
```

EAS handles signing on Apple's cloud builders, so a Mac isn't required for
iOS builds (Apple Developer account is, $99/yr).

## First-time setup

1. Open **Settings** tab.
2. Paste your **Anthropic API key** (for the card-vision scanner only).
3. Paste your **eBay App ID, Cert ID, Dev ID, and refresh token**. The
   refresh token comes from the OAuth callback flow at
   `${LAMBDA_BASE}/oauth/callback`. All four live in
   `expo-secure-store` (iOS Keychain / Android encrypted prefs).
4. Pick a vision model (Sonnet 4.6 default, ~$0.005/scan).
5. Permissions: allow camera when prompted.

## Project layout

```
mobile/
├── app/
│   ├── _layout.tsx              # root: theme + DB init + Stack routes
│   ├── (tabs)/
│   │   ├── _layout.tsx          # bottom-tab nav, Scan, Listings, Offers, Inventory, Settings
│   │   ├── index.tsx            # Scan (card-vision)
│   │   ├── listings.tsx         # live eBay listings, paginated, opens detail for photo health
│   │   ├── offers.tsx           # pending Best Offers, Accept/Counter/Decline
│   │   ├── inventory.tsx        # local card inventory
│   │   └── settings.tsx
│   ├── listing/[itemId]/
│   │   ├── index.tsx            # listing detail + inline price edit
│   │   └── replace-photos.tsx   # multi-shot camera → eBay gallery replacement
│   ├── card/[id]/
│   │   ├── index.tsx            # card detail
│   │   └── list-on-ebay.tsx     # card-specific listing creation
│   └── quick-list.tsx           # generic (non-card) snap-to-list flow
└── src/
    ├── theme.ts                 # dark-luxe palette (matches web)
    ├── db.ts                    # SQLite schema + CRUD
    ├── image-store.ts           # FS persistence + thumb generation
    ├── settings.ts              # SecureStore wrappers (Anthropic + eBay creds)
    └── api/
        ├── identify.ts          # Claude vision call
        ├── pricing.ts           # Pokémon TCG API
        ├── ebay.ts              # OAuth + UploadSiteHostedPictures + AddFixedPriceItem
        └── listings.ts          # GetMyeBaySelling / GetItem / ReviseFixedPriceItem / GetBestOffers / RespondToBestOffer
```

## Notes

- Every write to eBay is LIVE and confirmed via an `Alert` before the
  Trading API call.
- `ReviseFixedPriceItem` `<PictureDetails>` replaces the entire gallery —
  the replace-photos flow always submits the full set the seller approved
  on that screen.
- Photo downscale target is 2400px long-edge. Top sellers tend to post
  at 1600px or larger, and the extra headroom keeps cropping useful
  without bloating uploads. The 8-photo / 1600px target is a top-seller
  heuristic, not a published eBay rule.
- Best Offer counter validates against list price (counter must be lower)
  and rejects non-positive amounts on the client before the API call.
- The card scanner's SQLite schema is intentionally a superset of the web
  scanner's localStorage shape — cross-surface sync is a future task.
