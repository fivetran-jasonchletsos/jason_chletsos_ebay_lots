/**
 * Settings backed by SecureStore (keychain on iOS, encrypted prefs on Android).
 * API keys never live in plain AsyncStorage.
 */
import * as SecureStore from 'expo-secure-store';

const KEY_ANTHROPIC = 'anthropic_api_key';
const KEY_MODEL     = 'identify_model';
const KEY_QUALITY   = 'capture_quality';

const KEY_EBAY_CLIENT_ID     = 'ebay_client_id';
const KEY_EBAY_CLIENT_SECRET = 'ebay_client_secret';
const KEY_EBAY_REFRESH_TOKEN = 'ebay_refresh_token';
const KEY_EBAY_DEV_ID        = 'ebay_dev_id';

const KEY_SCP_API_KEY        = 'scp_api_key';

export type IdentifyModel = 'claude-sonnet-4-6' | 'claude-opus-4-7' | 'claude-haiku-4-5-20251001';

export async function getAnthropicKey(): Promise<string | null> {
  try { return await SecureStore.getItemAsync(KEY_ANTHROPIC); } catch { return null; }
}
export async function setAnthropicKey(k: string | null): Promise<void> {
  if (k && k.trim()) await SecureStore.setItemAsync(KEY_ANTHROPIC, k.trim());
  else await SecureStore.deleteItemAsync(KEY_ANTHROPIC);
}

export async function getModel(): Promise<IdentifyModel> {
  const v = await SecureStore.getItemAsync(KEY_MODEL);
  return (v as IdentifyModel) || 'claude-sonnet-4-6';
}
export async function setModel(m: IdentifyModel): Promise<void> {
  await SecureStore.setItemAsync(KEY_MODEL, m);
}

export async function getQuality(): Promise<number> {
  const v = await SecureStore.getItemAsync(KEY_QUALITY);
  return v ? parseFloat(v) : 0.85;
}
export async function setQuality(q: number): Promise<void> {
  await SecureStore.setItemAsync(KEY_QUALITY, String(q));
}

// ---------------------------------------------------------------------------
// eBay Trading API credentials. Mirrors configuration.json from the web
// pipeline so the same refresh_token can be used end-to-end.

export interface EbayCredentials {
  client_id: string;
  client_secret: string;
  refresh_token: string;
  dev_id: string | null;
}

async function _get(k: string): Promise<string | null> {
  try { return await SecureStore.getItemAsync(k); } catch { return null; }
}
async function _set(k: string, v: string | null): Promise<void> {
  if (v && v.trim()) await SecureStore.setItemAsync(k, v.trim());
  else await SecureStore.deleteItemAsync(k);
}

export async function getEbayClientId(): Promise<string | null>     { return _get(KEY_EBAY_CLIENT_ID); }
export async function setEbayClientId(v: string | null): Promise<void> { return _set(KEY_EBAY_CLIENT_ID, v); }

export async function getEbayClientSecret(): Promise<string | null>     { return _get(KEY_EBAY_CLIENT_SECRET); }
export async function setEbayClientSecret(v: string | null): Promise<void> { return _set(KEY_EBAY_CLIENT_SECRET, v); }

export async function getEbayRefreshToken(): Promise<string | null>     { return _get(KEY_EBAY_REFRESH_TOKEN); }
export async function setEbayRefreshToken(v: string | null): Promise<void> { return _set(KEY_EBAY_REFRESH_TOKEN, v); }

export async function getEbayDevId(): Promise<string | null>     { return _get(KEY_EBAY_DEV_ID); }
export async function setEbayDevId(v: string | null): Promise<void> { return _set(KEY_EBAY_DEV_ID, v); }

// ---------------------------------------------------------------------------
// SportsCardsPro / PriceCharting API key — paid subscription, single token.
// ---------------------------------------------------------------------------
export async function getScpKey(): Promise<string | null>     { return _get(KEY_SCP_API_KEY); }
export async function setScpKey(v: string | null): Promise<void> { return _set(KEY_SCP_API_KEY, v); }

// eBay Finding API just needs an "app id" — same value as the OAuth client_id.
// Expose under a dedicated name so the pricing layer doesn't have to know that.
export async function getEbayAppId(): Promise<string | null> { return getEbayClientId(); }

export async function getEbayCredentials(): Promise<EbayCredentials | null> {
  const [client_id, client_secret, refresh_token, dev_id] = await Promise.all([
    getEbayClientId(),
    getEbayClientSecret(),
    getEbayRefreshToken(),
    getEbayDevId(),
  ]);
  if (!client_id || !client_secret || !refresh_token) return null;
  return { client_id, client_secret, refresh_token, dev_id };
}
