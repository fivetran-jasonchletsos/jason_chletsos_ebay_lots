/**
 * Multi-source pricing for scanned cards.
 *
 * Sources, in priority order when blending:
 *   1. SportsCardsPro / PriceCharting   — paid API, canonical guide prices (needs API key)
 *   2. eBay Finding API (sold listings) — best-effort comp median (needs eBay app id)
 *   3. Pokemon TCG API                  — free, no key, always available for Pokemon cards
 *
 * All sources return the same shape (`PriceSource`) so the UI can render them uniformly.
 * `suggestPrice(parsed, sources)` blends them into a single recommendation.
 *
 * Mirrors the priority + grade-detection logic in ../../card_price_agent.py and
 * ../../promote.py — keep them in sync if the rules change.
 */
import type { IdentifiedCard } from './identify';
import { getScpKey, getEbayAppId } from '../settings';

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export interface PriceSource {
  source: 'scp' | 'ebay_sold' | 'pokemontcg';
  label: string;            // human-readable badge: 'SportsCardsPro · PSA 9'
  median: number;           // dollars
  low: number;
  high: number;
  count: number;
  url?: string;
  matched_title?: string;
  grade?: string;
  confidence?: number;      // 0..1 — only SCP populates this
}

export interface SuggestedPrice {
  suggested: number;
  basis: 'scp' | 'ebay_sold' | 'pokemontcg' | 'fallback';
  confidence: 'high' | 'medium' | 'low';
  reasoning: string;
}

export interface ParsedTitle {
  player: string | null;
  year: string | null;
  set_tokens: string[];
  card_number: string | null;
  grade: GradeKey | null;
}

export type GradeKey =
  | 'psa10' | 'psa9' | 'psa8' | 'psa7'
  | 'bgs10' | 'bgs95'
  | 'cgc10' | 'sgc10'
  | 'raw';

// Legacy result shape — kept so existing callers (scan flow / DB columns) keep working.
export interface PricingResult {
  found: boolean;
  tcg_id?: string | null;
  set_name?: string | null;
  set_series?: string | null;
  number?: string | null;
  rarity?: string | null;
  image_small?: string | null;
  image_large?: string | null;
  variant?: string | null;
  tcg_low?: number | null;
  tcg_mid?: number | null;
  tcg_market?: number | null;
  tcg_high?: number | null;
  cm_trend?: number | null;
  cm_avg30?: number | null;
  cm_low?: number | null;
  tcg_url?: string | null;
  cm_url?: string | null;
  all_variants?: string[];
  // New: every source we queried, plus the blended suggestion.
  sources?: PriceSource[];
  parsed?: ParsedTitle;
  suggested?: SuggestedPrice;
}

// ---------------------------------------------------------------------------
// Title parser — port of parse_title from card_price_agent.py
// ---------------------------------------------------------------------------

const SET_BRANDS = [
  'topps', 'bowman', 'panini', 'donruss', 'fleer', 'upper deck', 'score',
  'prizm', 'optic', 'mosaic', 'select', 'chrome', 'stadium club', 'leaf',
  'pinnacle', 'skybox', 'hoops', 'metal', 'finest', 'pokemon', 'magic',
  'yugioh', 'yu-gi-oh', 'mtg', 'tcg', 'rookie',
];

const NAME_STOPWORDS = new Set([
  'psa', 'bgs', 'cgc', 'sgc', 'gem', 'mint', 'rookie', 'rc', 'card',
  'cards', 'lot', 'graded', 'raw', 'near', 'auto', 'autograph', 'patch',
  'holo', 'refractor', 'prizm', 'optic', 'mosaic', 'the', 'and',
  'vintage', 'topps', 'panini', 'bowman', 'donruss', 'fleer',
  'upper', 'deck', 'score', 'select', 'chrome', 'stadium', 'club', 'leaf',
  'pokemon', 'japanese', 'english', 'promo', 'magic', 'gathering', 'yugioh',
  'yu', 'gi', 'oh', 'rare', 'ultra', 'common', 'uncommon', 'foil', 'nm',
  'sealed', 'set', 'edition', 'first', '1st', '2nd', 'free', 'shipping',
]);

export function detectGrade(title: string): GradeKey | null {
  const t = title.toUpperCase();
  if (/\bPSA\s*10\b|\bGEM\s*MINT\s*10\b/.test(t)) return 'psa10';
  if (/\bPSA\s*9\b/.test(t)) return 'psa9';
  if (/\bPSA\s*8(\.5)?\b/.test(t)) return 'psa8';
  if (/\bPSA\s*7(\.5)?\b/.test(t)) return 'psa7';
  if (/\bBGS\s*10\b|\bBLACK\s*LABEL\b/.test(t)) return 'bgs10';
  if (/\bBGS\s*9\.5\b/.test(t)) return 'bgs95';
  if (/\bCGC\s*10\b|\bCGC\s*PRISTINE\b/.test(t)) return 'cgc10';
  if (/\bSGC\s*10\b/.test(t)) return 'sgc10';
  return null;
}

export function parseTitle(title: string): ParsedTitle {
  const tLower = title.toLowerCase();

  const yearMatch = title.match(/\b(19[5-9]\d|20[0-3]\d)\b/);
  const year = yearMatch ? yearMatch[1] : null;

  let cardNum: string | null = null;
  const hashMatch = title.match(/#\s*(\d{1,4})\b/);
  if (hashMatch) {
    cardNum = hashMatch[1];
  } else {
    const noMatch = tLower.match(/\bno\.?\s*(\d{1,4})\b/);
    if (noMatch) cardNum = noMatch[1];
  }

  const grade = detectGrade(title);
  const setTokens = SET_BRANDS.filter((b) => tLower.includes(b));

  // Player/character name
  let cleaned = title.replace(/#\s*\d+.*$/, '');
  cleaned = cleaned.replace(/\b(psa|bgs|cgc|sgc)\b.*$/i, '');
  cleaned = cleaned.replace(/\b(19[5-9]\d|20[0-3]\d)\b/g, '');
  const tokens = cleaned.match(/[A-Z][a-zA-Z'\-\.]+/g) || [];
  const nameTokens = tokens.filter((t) => !NAME_STOPWORDS.has(t.toLowerCase()));
  const player = nameTokens.slice(0, 3).join(' ').trim() || null;

  return {
    player,
    year,
    set_tokens: setTokens,
    card_number: cardNum,
    grade,
  };
}

/** Build a card "title" from an IdentifiedCard for use with parser/search. */
export function cardToTitle(card: IdentifiedCard): string {
  const parts: string[] = [];
  if (card.name) parts.push(card.name);
  if (card.set_name) parts.push(card.set_name);
  if (card.number) parts.push(`#${String(card.number).split('/')[0]}`);
  if (card.foil) parts.push('Holo');
  if (card.edition) parts.push(card.edition);
  return parts.join(' ');
}

// ---------------------------------------------------------------------------
// SportsCardsPro / PriceCharting
// ---------------------------------------------------------------------------

const SCP_BASE = 'https://www.sportscardspro.com';
const SCP_MIN_INTERVAL_MS = 1050; // 1 req/sec ceiling
let scpLastRequestTs = 0;

async function scpThrottle(): Promise<void> {
  const now = Date.now();
  const wait = SCP_MIN_INTERVAL_MS - (now - scpLastRequestTs);
  if (wait > 0) {
    await new Promise((r) => setTimeout(r, wait));
  }
  scpLastRequestTs = Date.now();
}

// SCP grade priority: higher index = lower grade preference when falling back.
const SCP_GRADE_FIELDS: { grade: GradeKey; field: string }[] = [
  { grade: 'psa10', field: 'manual-only-price' },
  { grade: 'bgs10', field: 'bgs-10-price' },
  { grade: 'cgc10', field: 'condition-17-price' },
  { grade: 'sgc10', field: 'condition-18-price' },
  { grade: 'bgs95', field: 'box-only-price' },
  { grade: 'psa9',  field: 'graded-price' },
  { grade: 'psa8',  field: 'new-price' },
  { grade: 'psa7',  field: 'cib-price' },
  { grade: 'raw',   field: 'loose-price' },
];

const GRADE_LABEL: Record<GradeKey, string> = {
  psa10: 'PSA 10',
  psa9:  'PSA 9',
  psa8:  'PSA 8',
  psa7:  'PSA 7',
  bgs10: 'BGS 10',
  bgs95: 'BGS 9.5',
  cgc10: 'CGC 10',
  sgc10: 'SGC 10',
  raw:   'Raw',
};

function scoreScpMatch(parsed: ParsedTitle, candidate: any): number {
  const pname = (candidate['product-name'] || '').toLowerCase();
  const cname = (candidate['console-name'] || '').toLowerCase();
  let score = 0;

  if (parsed.player) {
    const player = parsed.player.toLowerCase();
    // Cheap fuzzy: token overlap ratio in pname
    const wantTokens = player.split(/\s+/).filter((t) => t.length > 2);
    if (wantTokens.length) {
      const hits = wantTokens.filter((t) => pname.includes(t)).length;
      score += (hits / wantTokens.length) * 0.45;
      if (hits === wantTokens.length) score += 0.15;
    }
  }
  if (parsed.year && cname.includes(parsed.year)) score += 0.20;
  if (parsed.card_number) {
    const re = new RegExp(`#\\s*${parsed.card_number}\\b`);
    if (re.test(pname)) score += 0.15;
  }
  for (const brand of parsed.set_tokens) {
    if (cname.includes(brand)) score += 0.05;
  }
  for (const noise of ['checklist', 'header', 'team card', 'leaders']) {
    if (pname.includes(noise)) score -= 0.10;
  }
  return Math.max(0, Math.min(1, score));
}

function extractScpGrades(product: any): Partial<Record<GradeKey, number>> {
  const out: Partial<Record<GradeKey, number>> = {};
  for (const { grade, field } of SCP_GRADE_FIELDS) {
    const v = product[field];
    if (typeof v === 'number' && v > 0) {
      out[grade] = Math.round(v) / 100; // cents -> dollars
    }
  }
  return out;
}

function buildScpQuery(parsed: ParsedTitle, rawTitle: string): string {
  const parts: string[] = [];
  if (parsed.player) parts.push(parsed.player);
  if (parsed.year) parts.push(parsed.year);
  parts.push(...parsed.set_tokens.slice(0, 2));
  if (parsed.card_number) parts.push(`#${parsed.card_number}`);
  const q = parts.join(' ').trim();
  if (q.length < 4) {
    // Fall back to a trimmed raw title
    return rawTitle.replace(/\s+/g, ' ').trim().slice(0, 100);
  }
  return q.slice(0, 100);
}

export async function fetchScpPricing(
  parsed: ParsedTitle,
  rawTitle: string,
  apiKey: string,
): Promise<PriceSource | null> {
  if (!apiKey) return null;

  const query = buildScpQuery(parsed, rawTitle);

  // 1. Search
  await scpThrottle();
  let searchData: any;
  try {
    const url = `${SCP_BASE}/api/products?t=${encodeURIComponent(apiKey)}&q=${encodeURIComponent(query)}`;
    const r = await fetch(url);
    if (!r.ok) return null;
    searchData = await r.json();
  } catch {
    return null;
  }
  if (searchData?.status !== 'success') return null;
  const candidates: any[] = searchData.products || [];
  if (!candidates.length) return null;

  // 2. Score + pick best
  let best: any = null;
  let bestScore = -1;
  for (const c of candidates) {
    const s = scoreScpMatch(parsed, c);
    if (s > bestScore) { bestScore = s; best = c; }
  }
  if (!best || bestScore <= 0) return null;

  const productId = best.id;
  if (!productId) return null;

  // 3. Fetch full product (only if confidence is above floor)
  if (bestScore < 0.40) {
    // Still return a low-confidence shell so the UI can show "no price"
    return {
      source: 'scp',
      label: 'SportsCardsPro · low confidence',
      median: 0,
      low: 0,
      high: 0,
      count: 0,
      url: `https://www.sportscardspro.com/game/sportscardspro/${productId}`,
      matched_title: best['product-name'],
      confidence: bestScore,
    };
  }

  await scpThrottle();
  let product: any;
  try {
    const url = `${SCP_BASE}/api/product?t=${encodeURIComponent(apiKey)}&id=${encodeURIComponent(productId)}`;
    const r = await fetch(url);
    if (!r.ok) return null;
    product = await r.json();
  } catch {
    return null;
  }
  if (product?.status !== 'success') return null;

  const grades = extractScpGrades(product);
  const gradeKeys = Object.keys(grades) as GradeKey[];
  if (!gradeKeys.length) return null;

  // Pick the grade matching the detected one, else raw, else cheapest available.
  let chosen: GradeKey;
  if (parsed.grade && grades[parsed.grade] != null) {
    chosen = parsed.grade;
  } else if (grades.raw != null) {
    chosen = 'raw';
  } else {
    chosen = gradeKeys.reduce((a, b) => (grades[a]! <= grades[b]! ? a : b));
  }
  const price = grades[chosen]!;

  // For "low/high" derive from the spread of all available grade prices (gives a useful range).
  const allPrices = gradeKeys.map((k) => grades[k]!).sort((a, b) => a - b);
  const low = allPrices[0];
  const high = allPrices[allPrices.length - 1];

  return {
    source: 'scp',
    label: `SportsCardsPro · ${GRADE_LABEL[chosen]}`,
    median: price,
    low,
    high,
    count: gradeKeys.length,
    url: `https://www.sportscardspro.com/game/sportscardspro/${productId}`,
    matched_title: product['product-name'] || best['product-name'],
    grade: chosen,
    confidence: bestScore,
  };
}

// ---------------------------------------------------------------------------
// eBay Finding API — sold/completed listings
// ---------------------------------------------------------------------------

function buildEbayQuery(card: IdentifiedCard, parsed: ParsedTitle): string {
  const parts: string[] = [];
  if (card.name) parts.push(card.name);
  if (card.set_name) parts.push(card.set_name);
  if (card.number) {
    const num = String(card.number).split('/')[0].replace(/[^A-Za-z0-9]/g, '');
    if (num) parts.push(num);
  }
  if (card.foil) parts.push('holo');
  if (parsed.grade) {
    // Add literal grade so eBay matches like-to-like
    parts.push(GRADE_LABEL[parsed.grade]);
  }
  return parts.filter(Boolean).join(' ').slice(0, 80);
}

export async function fetchEbaySold(
  card: IdentifiedCard,
  parsed: ParsedTitle,
  appId: string,
): Promise<PriceSource | null> {
  if (!appId) return null;
  const query = buildEbayQuery(card, parsed);
  if (!query) return null;

  const url = 'https://svcs.ebay.com/services/search/FindingService/v1';
  const params = new URLSearchParams({
    'OPERATION-NAME':            'findCompletedItems',
    'SERVICE-VERSION':           '1.13.0',
    'SECURITY-APPNAME':          appId,
    'RESPONSE-DATA-FORMAT':      'JSON',
    'REST-PAYLOAD':              '',
    'keywords':                  query,
    'paginationInput.entriesPerPage': '50',
    'itemFilter(0).name':        'SoldItemsOnly',
    'itemFilter(0).value':       'true',
    'itemFilter(1).name':        'LocatedIn',
    'itemFilter(1).value':       'US',
    'sortOrder':                 'EndTimeSoonest',
  });

  let data: any;
  try {
    const r = await fetch(`${url}?${params.toString()}`);
    if (!r.ok) return null;
    data = await r.json();
  } catch {
    return null;
  }

  const root = data?.findCompletedItemsResponse?.[0];
  if (!root || root.ack?.[0] !== 'Success') return null;
  const items: any[] = root.searchResult?.[0]?.item || [];
  if (!items.length) return null;

  const prices: number[] = [];
  for (const it of items) {
    const sold = it.sellingStatus?.[0]?.sellingState?.[0];
    if (sold && sold !== 'EndedWithSales') continue;
    const raw = it.sellingStatus?.[0]?.currentPrice?.[0]?.__value__
             ?? it.sellingStatus?.[0]?.convertedCurrentPrice?.[0]?.__value__;
    const p = parseFloat(raw);
    if (Number.isFinite(p) && p > 0) prices.push(p);
  }
  if (prices.length < 1) return null;

  prices.sort((a, b) => a - b);
  const median = prices.length % 2
    ? prices[(prices.length - 1) / 2]
    : (prices[prices.length / 2 - 1] + prices[prices.length / 2]) / 2;

  const ebayUrl = 'https://www.ebay.com/sch/i.html?_nkw='
    + encodeURIComponent(query) + '&_sacat=0&LH_Sold=1&LH_Complete=1';

  return {
    source: 'ebay_sold',
    label: parsed.grade ? `eBay sold · ${GRADE_LABEL[parsed.grade]}` : 'eBay sold',
    median: Math.round(median * 100) / 100,
    low: Math.round(prices[0] * 100) / 100,
    high: Math.round(prices[prices.length - 1] * 100) / 100,
    count: prices.length,
    url: ebayUrl,
    grade: parsed.grade ?? undefined,
  };
}

// ---------------------------------------------------------------------------
// Pokemon TCG (refactor of the old fetchPricing, returns the rich PricingResult
// AND a uniform PriceSource).
// ---------------------------------------------------------------------------

export async function fetchPokemonTcg(card: IdentifiedCard): Promise<{ result: PricingResult; source: PriceSource | null }> {
  if (!card?.name) return { result: { found: false }, source: null };

  const parts = [`name:"${card.name.replace(/"/g, '')}"`];
  if (card.number) {
    const num = String(card.number).split('/')[0].replace(/[^A-Za-z0-9]/g, '');
    if (num) parts.push(`number:${num}`);
  }
  const url = `https://api.pokemontcg.io/v2/cards?pageSize=5&q=${encodeURIComponent(parts.join(' '))}`;
  let data: any;
  try {
    const res = await fetch(url);
    if (!res.ok) return { result: { found: false }, source: null };
    data = await res.json();
  } catch {
    return { result: { found: false }, source: null };
  }
  const cards: any[] = data?.data || [];
  if (!cards.length) return { result: { found: false }, source: null };

  let best = cards[0];
  if (card.set_name) {
    const wanted = card.set_name.toLowerCase();
    const m = cards.find(
      (c) =>
        (c.set?.name || '').toLowerCase().includes(wanted) ||
        wanted.includes((c.set?.name || '').toLowerCase()),
    );
    if (m) best = m;
  }

  const tcg = best.tcgplayer?.prices || null;
  const cm = best.cardmarket?.prices || null;

  const variantPriority = card.foil
    ? ['holofoil', 'reverseHolofoil', 'normal', '1stEditionHolofoil', '1stEditionNormal']
    : ['normal', 'reverseHolofoil', 'holofoil', '1stEditionNormal', '1stEditionHolofoil'];
  let chosenVariant: string | null = null;
  if (tcg) {
    for (const v of variantPriority) {
      if (tcg[v]) { chosenVariant = v; break; }
    }
  }
  const variant = chosenVariant ? tcg[chosenVariant] : null;

  const result: PricingResult = {
    found: true,
    tcg_id: best.id,
    set_name: best.set?.name || null,
    set_series: best.set?.series || null,
    number: best.number || null,
    rarity: best.rarity || null,
    image_small: best.images?.small || null,
    image_large: best.images?.large || null,
    variant: chosenVariant,
    tcg_low: variant?.low ?? null,
    tcg_mid: variant?.mid ?? null,
    tcg_market: variant?.market ?? null,
    tcg_high: variant?.high ?? null,
    cm_trend: cm?.trendPrice ?? null,
    cm_avg30: cm?.avg30 ?? null,
    cm_low: cm?.lowPrice ?? null,
    tcg_url: best.tcgplayer?.url || null,
    cm_url: best.cardmarket?.url || null,
    all_variants: tcg ? Object.keys(tcg) : [],
  };

  // Build uniform source: prefer TCGplayer market, then mid, then Cardmarket trend.
  const median = result.tcg_market ?? result.tcg_mid ?? result.cm_trend ?? result.cm_avg30;
  const low    = result.tcg_low ?? result.cm_low ?? median;
  const high   = result.tcg_high ?? median;
  let source: PriceSource | null = null;
  if (median != null && low != null && high != null) {
    source = {
      source: 'pokemontcg',
      label: chosenVariant ? `PokemonTCG · ${chosenVariant}` : 'PokemonTCG',
      median,
      low,
      high,
      count: result.all_variants?.length ?? 1,
      url: result.tcg_url || result.cm_url || undefined,
      matched_title: result.set_name ? `${card.name} · ${result.set_name}` : card.name || undefined,
    };
  }

  return { result, source };
}

// ---------------------------------------------------------------------------
// Blender
// ---------------------------------------------------------------------------

export function suggestPrice(parsed: ParsedTitle, sources: PriceSource[]): SuggestedPrice {
  const scp = sources.find((s) => s.source === 'scp');
  const ebay = sources.find((s) => s.source === 'ebay_sold');
  const ptcg = sources.find((s) => s.source === 'pokemontcg');

  // 1. SCP — if confident and has a real price
  if (scp && (scp.confidence ?? 0) >= 0.5 && scp.median > 0) {
    const gradeLbl = scp.grade ? GRADE_LABEL[scp.grade as GradeKey] : 'best match';
    return {
      suggested: scp.median,
      basis: 'scp',
      confidence: (scp.confidence ?? 0) >= 0.7 ? 'high' : 'medium',
      reasoning: `SportsCardsPro guide price for ${gradeLbl} (match confidence ${Math.round((scp.confidence ?? 0) * 100)}%).`,
    };
  }

  // 2. eBay sold — need at least 3 comps
  if (ebay && ebay.count >= 3 && ebay.median > 0) {
    return {
      suggested: ebay.median,
      basis: 'ebay_sold',
      confidence: ebay.count >= 8 ? 'high' : 'medium',
      reasoning: `Median of ${ebay.count} recent eBay sold listings (range $${ebay.low.toFixed(2)}–$${ebay.high.toFixed(2)}).`,
    };
  }

  // 3. PokemonTCG
  if (ptcg && ptcg.median > 0) {
    return {
      suggested: ptcg.median,
      basis: 'pokemontcg',
      confidence: 'medium',
      reasoning: `TCGplayer market price${ptcg.matched_title ? ` for ${ptcg.matched_title}` : ''}.`,
    };
  }

  // 4. Fallback — best available even if weak
  const any = sources.find((s) => s.median > 0);
  if (any) {
    return {
      suggested: any.median,
      basis: 'fallback',
      confidence: 'low',
      reasoning: `Only weak signal from ${any.label}; verify before listing.`,
    };
  }

  return {
    suggested: 0,
    basis: 'fallback',
    confidence: 'low',
    reasoning: 'No pricing sources returned a match. Search eBay sold manually.',
  };
}

// ---------------------------------------------------------------------------
// Top-level orchestrator — what callers use.
// ---------------------------------------------------------------------------

/**
 * Pull pricing from every available source in parallel and return a
 * PricingResult enriched with the uniform `sources[]` + `suggested` blend.
 * Each source fails open: a network/auth error on one source never breaks the others.
 */
export async function fetchPricing(card: IdentifiedCard): Promise<PricingResult> {
  const title = cardToTitle(card);
  const parsed = parseTitle(title);

  // Run all three in parallel — SCP self-throttles per process.
  const [scpKey, ebayId] = await Promise.all([getScpKey(), getEbayAppId()]);

  const [ptcgRes, scpRes, ebayRes] = await Promise.all([
    safe(() => fetchPokemonTcg(card)),
    scpKey ? safe(() => fetchScpPricing(parsed, title, scpKey)) : Promise.resolve(null),
    ebayId ? safe(() => fetchEbaySold(card, parsed, ebayId)) : Promise.resolve(null),
  ]);

  const sources: PriceSource[] = [];
  if (scpRes) sources.push(scpRes);
  if (ebayRes) sources.push(ebayRes);
  if (ptcgRes?.source) sources.push(ptcgRes.source);

  const suggested = suggestPrice(parsed, sources);

  const base: PricingResult = ptcgRes?.result ?? { found: false };
  return {
    ...base,
    found: base.found || sources.length > 0,
    sources,
    parsed,
    suggested,
  };
}

async function safe<T>(fn: () => Promise<T>): Promise<T | null> {
  try { return await fn(); } catch { return null; }
}

// ---------------------------------------------------------------------------
// Helpers used elsewhere
// ---------------------------------------------------------------------------

export function ebaySearchUrl(card: IdentifiedCard): string {
  const q = [card.name];
  if (card.set_name) q.push(card.set_name);
  if (card.number) q.push(String(card.number).split('/')[0]);
  if (card.foil) q.push('holo');
  return (
    'https://www.ebay.com/sch/i.html?_nkw=' +
    encodeURIComponent(q.filter(Boolean).join(' ').slice(0, 80)) +
    '&_sacat=0&LH_Sold=1&LH_Complete=1'
  );
}
