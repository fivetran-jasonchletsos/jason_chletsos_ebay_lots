/**
 * Settings backed by SecureStore (keychain on iOS, encrypted prefs on Android).
 * API keys never live in plain AsyncStorage.
 */
import * as SecureStore from 'expo-secure-store';

const KEY_ANTHROPIC = 'anthropic_api_key';
const KEY_MODEL     = 'identify_model';
const KEY_QUALITY   = 'capture_quality';

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
