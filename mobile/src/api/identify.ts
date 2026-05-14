/**
 * Claude vision — identify a Pokemon TCG card from a photo.
 * Mirrors the web scanner's system prompt + JSON schema so a card scanned
 * here matches the row shape used by the eBay seller pipeline.
 */
import * as FileSystem from 'expo-file-system/legacy';
import { getAnthropicKey, getModel } from '../settings';

export interface IdentifiedCard {
  name: string | null;
  set_name: string | null;
  set_code: string | null;
  number: string | null;
  total: string | null;
  rarity: string | null;
  foil: boolean;
  edition: string | null;
  language: string | null;
  condition_hints: string | null;
  confidence: 'low' | 'medium' | 'high';
  error?: string;
}

const SYSTEM = `You are a Pokemon Trading Card Game identifier. The user uploads a photo of a single card (front, sometimes back). Read the card carefully.

Return ONLY a JSON object with this exact shape — no prose, no markdown:
{
  "name": "string — primary Pokemon or trainer name as printed",
  "set_name": "string or null — set name if you can read it from the set symbol or copyright line",
  "set_code": "string or null — printed set code from the bottom-left if visible (e.g. SV, SWSH, BS)",
  "number": "string or null — collector number as printed (e.g. '4/102', '4', 'TG12')",
  "total": "string or null — total in set if printed (e.g. '102')",
  "rarity": "string or null — Common / Uncommon / Rare / Holo Rare / Ultra Rare / Secret Rare / Promo",
  "foil": "boolean — true if the card shows holographic foil patterns",
  "edition": "string or null — '1st Edition', 'Shadowless', 'Unlimited', or null",
  "language": "string — 'English' unless clearly another language",
  "condition_hints": "string or null — visible defects (whitening, scratches, dings, centering issues)",
  "confidence": "low | medium | high — your confidence in the identification"
}

If you cannot identify the card, return {"name": null, "confidence": "low", "error": "describe what you see"}.`;

/**
 * Identify a card from one or two photos (front + optional back).
 * The local file URIs are read and sent as base64 to Anthropic.
 */
export async function identifyCard(frontUri: string, backUri?: string): Promise<{ card: IdentifiedCard; raw: string }> {
  const key = await getAnthropicKey();
  if (!key) throw new Error('No Anthropic API key — set one in Settings.');
  const model = await getModel();

  const frontB64 = await FileSystem.readAsStringAsync(frontUri, { encoding: FileSystem.EncodingType.Base64 });
  const content: any[] = [
    { type: 'image', source: { type: 'base64', media_type: 'image/jpeg', data: frontB64 } },
  ];
  if (backUri) {
    const backB64 = await FileSystem.readAsStringAsync(backUri, { encoding: FileSystem.EncodingType.Base64 });
    content.push({ type: 'image', source: { type: 'base64', media_type: 'image/jpeg', data: backB64 } });
  }
  content.push({ type: 'text', text: 'Identify this card. Return JSON only.' });

  const res = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      'x-api-key': key,
      'anthropic-version': '2023-06-01',
    },
    body: JSON.stringify({
      model,
      max_tokens: 600,
      system: SYSTEM,
      messages: [{ role: 'user', content }],
    }),
  });
  if (!res.ok) {
    const t = await res.text();
    throw new Error(`Claude ${res.status}: ${t.slice(0, 200)}`);
  }
  const payload = await res.json();
  const text: string = payload?.content?.find((c: any) => c.type === 'text')?.text ?? '';
  const card = parseCardJson(text);
  return { card, raw: text };
}

function parseCardJson(text: string): IdentifiedCard {
  try {
    const m = text.match(/\{[\s\S]*\}/);
    if (m) {
      const parsed = JSON.parse(m[0]);
      return {
        name: parsed.name ?? null,
        set_name: parsed.set_name ?? null,
        set_code: parsed.set_code ?? null,
        number: parsed.number ?? null,
        total: parsed.total ?? null,
        rarity: parsed.rarity ?? null,
        foil: !!parsed.foil,
        edition: parsed.edition ?? null,
        language: parsed.language ?? 'English',
        condition_hints: parsed.condition_hints ?? null,
        confidence: parsed.confidence ?? 'low',
        error: parsed.error,
      };
    }
  } catch {}
  return { name: null, set_name: null, set_code: null, number: null, total: null, rarity: null, foil: false, edition: null, language: 'English', condition_hints: null, confidence: 'low', error: 'unparseable response' };
}
