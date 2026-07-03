export const meta = {
  name: 'next-10-players-committee',
  description: '5 persona agents debate and pick the next 10 players for JC to target',
  phases: [{ title: 'Propose' }, { title: 'Debate' }, { title: 'Chair' }],
}

const CONTEXT = `JC runs JC2 Cards, an eBay store selling modern NFL single cards (2020-2025 Panini/Topps),
mostly rookies, stars, and colored/numbered parallels, priced ~$3-15. He sources, scans, and lists
regularly. We are picking the NEXT 10 PLAYERS he should prioritize targeting/sourcing/listing.

CURRENT INVENTORY SATURATION (active listings he already holds — avoid piling onto the deep ones
unless velocity clearly justifies it):
  Travis Hunter 43, Josh Allen 41, Lamar Jackson 40, Jayden Daniels 39, Cam Ward 38, Patrick Mahomes 36,
  Ashton Jeanty 33, Caleb Williams 29, Tetairoa McMillan 27, Brock Purdy 27, Drake Maye 20, Joe Burrow 17,
  CeeDee Lamb 15, Jaylen Waddle 14, George Kittle 13, Jordan Love 11, Derrick Henry 11, Brian Thomas 10,
  Tyreek Hill 10, Ja'Marr Chase 10, Justin Jefferson 8, Bo Nix 7, Puka Nacua 7, Tyler Shough 6.

HARD CONSTRAINTS:
- EXCLUDE all New York Giants players and Jaxson Dart — JC KEEPS those, never sells them. Do not pick
  Malik Nabers, Abdul Carter, Cam Skattebo, Jaxson Dart, or any current Giant as a SELL target.
- Picks must fit the store: players whose modern singles/RCs/parallels actually sell at $3-15.
- Knowledge is current through early 2026 (2025 NFL season complete, 2026 draft complete).
- Favor players JC is THIN on but that sell well, plus rising 2025 breakouts / strong 2026 rookies,
  over names already at high saturation.`

const PERSONAS = [
  { key: 'numbers', name: 'Numbers (Comp Analyst)', lens: `You live in eBay sold data. You only trust sell-through velocity, price stability, and realized comps at the $3-15 band. You distrust hype without sales behind it. Pick players whose cards demonstrably MOVE and hold price.` },
  { key: 'buzz', name: 'Buzz (Hobby Trend Scout)', lens: `You track what is HOT right now: breaker demand, social/hobby buzz, playoff narratives, jersey-number chases, rookie-premiere momentum. You pick players with rising attention that will spike demand.` },
  { key: 'hold', name: 'Hold (Value Investor)', lens: `You buy low and think 1-3 years out: sophomore-leap candidates, post-hype dips, undervalued RCs with appreciation upside. You pick players the market is currently sleeping on.` },
  { key: 'churn', name: 'Churn (Velocity Flipper)', lens: `You want fast turnover at JC's price points. Big national fanbases, high-population reliable sellers, players that always find a buyer within days. You pick for liquidity, not ceiling.` },
  { key: 'brakes', name: 'Brakes (Risk Manager / Contrarian)', lens: `You kill bad picks: oversupply, injury/age risk, fading veterans, redundancy with JC's already-deep inventory. You ensure the final 10 are diverse, non-redundant, and low-regret.` },
]

const PROPOSE_SCHEMA = { type:'object', properties:{ picks:{ type:'array', items:{ type:'object', properties:{
  player:{type:'string'}, position:{type:'string'}, team:{type:'string'}, reason:{type:'string'} },
  required:['player','position','team','reason'] } } }, required:['picks'] }

phase('Propose')
const proposals = await parallel(PERSONAS.map(p => () =>
  agent(`${CONTEXT}\n\nYou are ${p.name}. ${p.lens}\n\nPropose 8-12 player targets through your lens. Be specific and varied; respect the hard constraints.`,
    { label: p.key, phase: 'Propose', schema: PROPOSE_SCHEMA })
    .then(r => ({ persona: p.name, key: p.key, picks: (r && r.picks) || [] }))))

const pool = proposals.filter(Boolean).flatMap(pr => pr.picks.map(x => `${x.player} (${x.position}, ${x.team}) — ${pr.key}: ${x.reason}`))
const poolText = pool.join('\n')

phase('Debate')
const DEBATE_SCHEMA = { type:'object', properties:{ shortlist:{ type:'array', items:{ type:'object', properties:{
  player:{type:'string'}, score:{type:'number'}, take:{type:'string'} }, required:['player','score','take'] } },
  veto:{ type:'array', items:{type:'string'} } }, required:['shortlist','veto'] }

const debates = await parallel(PERSONAS.map(p => () =>
  agent(`${CONTEXT}\n\nYou are ${p.name}. ${p.lens}\n\nHere is the COMBINED pool of every persona's proposals:\n${poolText}\n\nFrom YOUR lens, score the strongest candidates 0-10 (only the ones you'd back), give a one-line take each, and list any players you VETO (redundant with deep inventory, too risky, or a constraint violation).`,
    { label: p.key, phase: 'Debate', schema: DEBATE_SCHEMA })
    .then(r => ({ persona: p.name, key: p.key, shortlist: (r && r.shortlist) || [], veto: (r && r.veto) || [] }))))

const debateText = debates.filter(Boolean).map(d =>
  `${d.persona}\n  backs: ${d.shortlist.map(s => `${s.player}(${s.score}) ${s.take}`).join(' | ')}\n  vetoes: ${(d.veto||[]).join(', ')||'none'}`).join('\n\n')

phase('Chair')
const FINAL_SCHEMA = { type:'object', properties:{
  final10:{ type:'array', items:{ type:'object', properties:{
    rank:{type:'number'}, player:{type:'string'}, position:{type:'string'}, team:{type:'string'},
    tier:{type:'string', description:'velocity / star / rising / value'},
    why:{type:'string'}, target:{type:'string', description:'what to source: RCs, which sets/parallels, price note'} },
    required:['rank','player','position','team','tier','why','target'] } },
  honorable:{ type:'array', items:{type:'string'} },
  notes:{type:'string'} }, required:['final10','honorable','notes'] }

const chair = await agent(
  `${CONTEXT}\n\nYou are the CHAIR. Five personas proposed and debated. Their scored debate:\n${debateText}\n\nDecide the FINAL 10 players, ranked. Honor vetoes unless a strong cross-persona consensus overrides. Ensure DIVERSITY (mix of positions and of velocity/star/rising/value tiers), no redundancy with JC's already-deep inventory, and full respect for the hard constraints (no Giants, no Dart). For each pick give why + what to source. Also list 4-6 honorable mentions and any notes.`,
  { label: 'chair', phase: 'Chair', schema: FINAL_SCHEMA })

return { proposals, debates, chair }
