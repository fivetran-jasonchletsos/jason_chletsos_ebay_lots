/**
 * Pokemon TCG API — pricing lookup keyed by Claude's identification.
 * Free, no key required. Returns TCGplayer + Cardmarket prices.
 */
import type { IdentifiedCard } from './identify';

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
}

export async function fetchPricing(card: IdentifiedCard): Promise<PricingResult> {
  if (!card?.name) return { found: false };

  const parts = [`name:"${card.name.replace(/"/g, '')}"`];
  if (card.number) {
    const num = String(card.number).split('/')[0].replace(/[^A-Za-z0-9]/g, '');
    if (num) parts.push(`number:${num}`);
  }
  const url = `https://api.pokemontcg.io/v2/cards?pageSize=5&q=${encodeURIComponent(parts.join(' '))}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`TCG API ${res.status}`);
  const data = await res.json();
  const cards: any[] = data?.data || [];
  if (!cards.length) return { found: false };

  let best = cards[0];
  if (card.set_name) {
    const wanted = card.set_name.toLowerCase();
    const m = cards.find((c) => (c.set?.name || '').toLowerCase().includes(wanted) || wanted.includes((c.set?.name || '').toLowerCase()));
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

  return {
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
}

export function ebaySearchUrl(card: IdentifiedCard): string {
  const q = [card.name];
  if (card.set_name) q.push(card.set_name);
  if (card.number) q.push(String(card.number).split('/')[0]);
  if (card.foil) q.push('holo');
  return 'https://www.ebay.com/sch/i.html?_nkw=' + encodeURIComponent(q.filter(Boolean).join(' ').slice(0, 80)) + '&_sacat=0&LH_Sold=1&LH_Complete=1';
}
