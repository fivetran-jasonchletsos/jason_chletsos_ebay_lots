export const meta = {
  name: 'identify-scan-batch-67-69',
  description: 'Identify 162 football cards from 18 split scans into post-ready titles',
  phases: [{ title: 'Identify' }],
}

const MANIFEST = {"257": {"scan": 67, "crops": ["output/split_cards/Scan 67/Scan 257_01.jpg", "output/split_cards/Scan 67/Scan 257_02.jpg", "output/split_cards/Scan 67/Scan 257_03.jpg", "output/split_cards/Scan 67/Scan 257_04.jpg", "output/split_cards/Scan 67/Scan 257_05.jpg", "output/split_cards/Scan 67/Scan 257_06.jpg", "output/split_cards/Scan 67/Scan 257_07.jpg", "output/split_cards/Scan 67/Scan 257_08.jpg", "output/split_cards/Scan 67/Scan 257_09.jpg"]}, "258": {"scan": 68, "crops": ["output/split_cards/Scan 68/Scan 258_01.jpg", "output/split_cards/Scan 68/Scan 258_02.jpg", "output/split_cards/Scan 68/Scan 258_03.jpg", "output/split_cards/Scan 68/Scan 258_04.jpg", "output/split_cards/Scan 68/Scan 258_05.jpg", "output/split_cards/Scan 68/Scan 258_06.jpg", "output/split_cards/Scan 68/Scan 258_07.jpg", "output/split_cards/Scan 68/Scan 258_08.jpg", "output/split_cards/Scan 68/Scan 258_09.jpg"]}, "259": {"scan": 69, "crops": ["output/split_cards/Scan 69/Scan 259_01.jpg", "output/split_cards/Scan 69/Scan 259_02.jpg", "output/split_cards/Scan 69/Scan 259_03.jpg", "output/split_cards/Scan 69/Scan 259_04.jpg", "output/split_cards/Scan 69/Scan 259_05.jpg", "output/split_cards/Scan 69/Scan 259_06.jpg", "output/split_cards/Scan 69/Scan 259_07.jpg", "output/split_cards/Scan 69/Scan 259_08.jpg", "output/split_cards/Scan 69/Scan 259_09.jpg"]}};

const CARD_SCHEMA = {
  type: 'object',
  properties: {
    cards: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          image: { type: 'string' },
          title: { type: 'string' },
          price: { type: 'number' },
          route: { type: 'string', enum: ['ebay', 'collection', 'skip_dart'] },
          numbered: { type: 'boolean' },
        },
        required: ['image', 'title', 'price', 'route', 'numbered'],
      },
    },
  },
  required: ['cards'],
}

const RULES = `You are identifying modern NFL trading cards (2023-2025 Panini/Topps) from scan crops.
For EACH crop path given, use the Read tool to view the image, then identify the card.

TITLE FORMAT (match exactly, UNDER 80 chars):
"YEAR BRAND [PARALLEL/INSERT] PLAYER [RC] TEAM Football"
- YEAR: copyright year (2023/2024/2025); if unsure use 2024.
- BRAND: Select, Prizm, Mosaic, Donruss Optic, Donruss, Phoenix, Score, Contenders, Chronicles, Absolute, Revolution, Topps Chrome, Topps Cosmic/Iconic, Prestige, etc.
- PARALLEL/INSERT only if clearly present (Turbocharged, Numbers, Future, Contours, Thunderbirds, Touchdown Masters, Epic Performers, Paragon, Notoriety, Round Pick, Players, an orange/silver/pink/green parallel, etc.). Omit if base.
- RC only for rookies (Drake Maye, Tyler Shough, Tetairoa McMillan, Emeka Egbuka, Colston Loveland, Omarion Hampton, Tyler Warren, Dillon Gabriel, Will Howard, Matthew Golden, Shedeur Sanders, Kyle Williams, Mykel Williams, Will Johnson; Bryce Young is 2023).

PRICING (rough, refined later):
- Base/common veteran or low insert: 3.99
- Caleb Williams base/non-insert: EXACTLY 2.99, never the word "insert", never above 2.99
- Premium insert (Turbocharged, Numbers, Thunderbirds, Future, Touchdown Masters, Phoenix die-cuts): 5.99
- Star RC (Drake Maye, Tetairoa McMillan, Tyler Shough silver/prizm): 6.99
- Big star base (Burrow, Jefferson, Chase, Lamb, Mahomes, Puka Nacua, Tyreek Hill): 4.99
- Numbered colored parallel of a star: 8.99
If clearly a colored/numbered parallel (orange/pink/green/silver prizm), set numbered=true and add 2.00 to the tier price.

ROUTING (critical):
- Jaxson Dart: route="skip_dart" (NEVER sell Dart).
- Any NY GIANTS card (Malik Nabers, Abdul Carter, Cam Skattebo, etc.): route="collection" (JC keeps all Giants). Dart is a Giant but still use skip_dart.
- Everything else: route="ebay".

Return one object per crop, image path VERBATIM. Crops are row-major (top-left to bottom-right of a 3x3 scan).`

phase('Identify')
const entries = Object.entries(MANIFEST)
const results = await parallel(entries.map(([batchNo, info]) => () =>
  agent(
    RULES + `\n\nBatch ${batchNo} (Scan ${info.scan}). Identify these ${info.crops.length} crops in order:\n` + info.crops.map((c, i) => `${i + 1}. ${c}`).join('\n'),
    { label: `batch ${batchNo}`, phase: 'Identify', schema: CARD_SCHEMA }
  ).then(r => ({ batch: batchNo, scan: info.scan, cards: (r && r.cards) || [] }))
))

return results.filter(Boolean)
