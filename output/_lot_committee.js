export const meta = {
  name: 'three-card-lot-committee',
  description: '4 experts design five themed 3-card lots from stale inventory',
  phases: [{ title: 'Propose' }, { title: 'Chair' }],
}

const DEPTH = {"Patrick Mahomes II": [18, 3.85], "Patrick Mahomes": [21, 4.21], "Tetairoa McMillan": [30, 3.76], "Bryce Young": [5, 3.04], "Bo Nix": [8, 4.65], "Joe Burrow": [32, 11.05], "Dillon Gabriel": [15, 4.32], "Ashton Jeanty": [33, 4.53], "Tyler Shough": [10, 4.02], "Jordan Love": [12, 4.24], "Cam Ward": [37, 3.72], "Drake Maye": [29, 5.12], "Matthew Golden": [15, 8.35], "Caleb Williams": [31, 4.1], "Brian Thomas": [10, 3.71], "Tate Ratledge": [3, 2.66], "Jared Goff": [5, 2.66], "Shedeur Sanders": [21, 4.34], "Jaylen Waddle": [17, 3.72], "Will Howard": [4, 3.49], "Dak Prescott": [9, 14.1], "Lamar Jackson": [41, 4.38], "Travis Hunter": [43, 5.72], "Brock Bowers": [5, 8.73], "Puka Nacua": [13, 4.55], "Emeka Egbuka": [37, 4.7], "Tyler Warren": [20, 4.3], "Josh Allen": [40, 4.33], "Nico Collins": [3, 2.41], "Justin Jefferson": [24, 5.28], "Brock Purdy": [27, 4.13], "Jayden Daniels": [39, 3.9], "Justin Herbert": [4, 4.24], "CeeDee Lamb": [21, 4.78], "Omarion Hampton": [30, 8.23], "Keon Coleman": [4, 4.24], "Trey Amos": [4, 2.74], "Rome Odunze": [3, 2.32], "Jayden Reed": [3, 2.72], "Will Johnson": [12, 3.92], "Kyren Williams": [5, 2.81], "Kyle Williams": [11, 3.26], "Mykel Williams": [20, 3.28], "Tyreek Hill": [12, 5.11], "Khalil Mack": [3, 3.44], "Bijan Robinson": [4, 5.02], "Saquon Barkley": [4, 5.82], "George Kittle": [15, 4.21], "Trevor Lawrence": [4, 8.49], "Ja'Marr Chase": [17, 4.7], "Derrick Henry": [15, 3.72], "C.J. Stroud": [5, 4.39]};

const CONTEXT = `JC runs JC2 Cards (eBay, modern NFL singles). His ENTIRE 1506-listing catalog is low-visibility
(every listing is in the cassini "red" bucket — nothing gets views). He is cash-flow constrained and must
MOVE inventory to fund more buying. Strategy: bundle slow singles into attractive THREE-CARD LOTS that sell
as a unit, then delist the 3 originals. He has DEEP duplicate stacks (spares) on marquee names, so lots can
be built without giving up a last copy.

INVENTORY DEPTH (player -> [count, avg_single_price]); only players with 3+ cards shown:
${JSON.stringify(DEPTH)}

RULES:
- Each lot = exactly 3 players (one card each). Use players from the depth list (he has spares).
- EXCLUDE New York Giants players and Jaxson Dart (keepers, never sell).
- Theme each lot so it's searchable and attractive: rookie-class lots, QB-room lots, team lots, position
  lots (RB/WR/TE), breakout lots, etc. JC's example: "Travis Hunter + Cam Ward + Ashton Jeanty = 2025 rookie lot".
- VELOCITY PRICING: price the lot to MOVE, not to maximize. A 3-card lot should undercut the sum of the
  singles (buyers expect a bundle discount) and land at a clean price point that sells fast. JC explicitly
  prefers lower-and-faster over squeezing margin.
- Favor bundling his DEEPEST stacks (Hunter 43, Ward 37, Egbuka 37, Jeanty 33, McMillan 30, Caleb 31,
  Hampton 30, Maye 29, Shedeur 21, Tyler Warren 20) — clearing duplicates is the point.`;

const LOT_SCHEMA = { type:'object', properties:{ lots:{ type:'array', items:{ type:'object', properties:{
  theme:{type:'string'}, title:{type:'string', description:'eBay lot title under 80 chars'},
  players:{type:'array', items:{type:'string'}, description:'exactly 3 player names from the depth list'},
  lot_price:{type:'number'}, why:{type:'string'} },
  required:['theme','title','players','lot_price','why'] } } }, required:['lots'] };

const EXPERTS=[
 ['Bundler','You are the Lot Strategist. You know what makes a 3-card lot sell as a UNIT: a thematic hook, one anchor name plus two complements, a clean sub-$25 price point. Design cohesive, irresistible bundles.'],
 ['Rookie','You are the 2025 Rookie Specialist. You know which rookies have the most bundle demand (Hunter, Ward, Jeanty, McMillan, Egbuka, Maye, Shedeur, Hampton, Warren, Golden) and how RC lots get searched. Build rookie-class lots.'],
 ['Liquidator','You are the Liquidation Expert. Your only goal is CLEARING dead stock fast. Bundle the DEEPEST duplicate stacks at aggressive velocity prices so they actually sell this week. Volume over margin.'],
 ['SEO','You are the eBay Search/SEO Expert. You optimize lot TITLES for how buyers actually search ("2025 Rookie RC Lot", "Lions WR Lot", "QB Lot 3 Cards"). Make titles findable and the theme obvious at a glance.'],
];

phase('Propose')
const proposals = await parallel(EXPERTS.map(([k,lens]) => () =>
  agent(CONTEXT+`\n\nYou are ${k}. ${lens}\n\nPropose 4-6 three-card lots through your lens. Each must have exactly 3 players from the depth list, a searchable title, a velocity lot price, and a one-line why.`,
    {label:k, phase:'Propose', schema:LOT_SCHEMA}).then(r=>({expert:k, lots:(r&&r.lots)||[]}))));

const pool = proposals.filter(Boolean).flatMap(p=>p.lots.map(l=>`[${p.expert}] ${l.theme}: ${l.players.join(' + ')} @ $${l.lot_price} — "${l.title}"`)).join('\n');

phase('Chair')
const FINAL={type:'object',properties:{
  final5:{type:'array',items:{type:'object',properties:{
    rank:{type:'number'}, theme:{type:'string'}, title:{type:'string'},
    players:{type:'array',items:{type:'string'}}, lot_price:{type:'number'}, why:{type:'string'}},
    required:['rank','theme','title','players','lot_price','why']}},
  notes:{type:'string'}},required:['final5','notes']};

const chair=await agent(CONTEXT+`\n\nYou are the CHAIR. The four experts proposed these lots:\n${pool}\n\nChoose the FINAL FIVE 3-card lots. Maximize: (1) diversity of theme, (2) clearing the deepest duplicate stacks, (3) velocity pricing, (4) searchable titles. No player should appear in more than 2 of the 5 lots. Every lot = exactly 3 players from the depth list, no Giants/Dart. Give each a clean eBay title (<80 chars), a move-it lot price, and why.`,
  {label:'chair', phase:'Chair', schema:FINAL});
return chair;
