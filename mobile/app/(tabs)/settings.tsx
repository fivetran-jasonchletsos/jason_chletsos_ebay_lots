import { useEffect, useState } from 'react';
import {
  Alert,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { theme, radii } from '@/src/theme';
import {
  getAnthropicKey,
  setAnthropicKey,
  getModel,
  setModel,
  getQuality,
  setQuality,
  getScpKey,
  setScpKey,
  getEbayClientId,
  setEbayClientId,
  getEbayClientSecret,
  setEbayClientSecret,
  getEbayRefreshToken,
  setEbayRefreshToken,
  getEbayDevId,
  setEbayDevId,
  type IdentifyModel,
} from '@/src/settings';
import { clearTokenCache } from '@/src/api/ebay';

const MODELS: { value: IdentifyModel; label: string; hint: string }[] = [
  { value: 'claude-sonnet-4-6', label: 'Sonnet 4.6', hint: 'Fast + cheap (~$0.005/scan, recommended)' },
  { value: 'claude-opus-4-7', label: 'Opus 4.7', hint: 'Slower, most accurate (~$0.03/scan)' },
  { value: 'claude-haiku-4-5-20251001', label: 'Haiku 4.5', hint: 'Cheapest (~$0.002/scan)' },
];

const QUALITIES: { value: number; label: string; hint: string }[] = [
  { value: 0.7, label: 'Standard', hint: 'Smaller payload' },
  { value: 0.85, label: 'High', hint: 'Recommended' },
  { value: 0.95, label: 'Maximum', hint: 'Largest payload, best detail' },
];

export default function SettingsScreen() {
  const [hasKey, setHasKey] = useState(false);
  const [keyInput, setKeyInput] = useState('');
  const [model, setModelState] = useState<IdentifyModel>('claude-sonnet-4-6');
  const [quality, setQualityState] = useState(0.85);
  const [hasScpKey, setHasScpKey] = useState(false);
  const [scpInput, setScpInput] = useState('');

  const [hasEbayId,      setHasEbayId]      = useState(false);
  const [ebayIdInput,    setEbayIdInput]    = useState('');
  const [hasEbayCert,    setHasEbayCert]    = useState(false);
  const [ebayCertInput,  setEbayCertInput]  = useState('');
  const [hasEbayRefresh, setHasEbayRefresh] = useState(false);
  const [ebayRefreshInput, setEbayRefreshInput] = useState('');
  const [hasEbayDev,     setHasEbayDev]     = useState(false);
  const [ebayDevInput,   setEbayDevInput]   = useState('');

  useEffect(() => {
    getAnthropicKey().then((k) => setHasKey(!!k));
    getModel().then(setModelState);
    getQuality().then(setQualityState);
    getScpKey().then((k) => setHasScpKey(!!k));
    getEbayClientId().then((v) => setHasEbayId(!!v));
    getEbayClientSecret().then((v) => setHasEbayCert(!!v));
    getEbayRefreshToken().then((v) => setHasEbayRefresh(!!v));
    getEbayDevId().then((v) => setHasEbayDev(!!v));
  }, []);

  async function saveKey() {
    if (!keyInput.trim()) {
      Alert.alert('Empty', 'Paste a key first.');
      return;
    }
    await setAnthropicKey(keyInput.trim());
    setKeyInput('');
    setHasKey(true);
    Alert.alert('Saved', 'API key stored in keychain.');
  }
  async function clearKey() {
    await setAnthropicKey(null);
    setHasKey(false);
  }
  async function chooseModel(m: IdentifyModel) {
    setModelState(m);
    await setModel(m);
  }
  async function chooseQuality(q: number) {
    setQualityState(q);
    await setQuality(q);
  }

  async function saveScpKey() {
    if (!scpInput.trim()) {
      Alert.alert('Empty', 'Paste a SportsCardsPro / PriceCharting API key first.');
      return;
    }
    await setScpKey(scpInput.trim());
    setScpInput('');
    setHasScpKey(true);
    Alert.alert('Saved', 'SportsCardsPro key stored in keychain.');
  }
  async function clearScpKey() {
    await setScpKey(null);
    setHasScpKey(false);
  }

  async function saveEbayId() {
    if (!ebayIdInput.trim()) { Alert.alert('Empty', 'Paste your eBay App ID first.'); return; }
    await setEbayClientId(ebayIdInput.trim()); setEbayIdInput(''); setHasEbayId(true);
    clearTokenCache();
    Alert.alert('Saved', 'eBay App ID stored.');
  }
  async function clearEbayId()      { await setEbayClientId(null); setHasEbayId(false); clearTokenCache(); }

  async function saveEbayCert() {
    if (!ebayCertInput.trim()) { Alert.alert('Empty', 'Paste your eBay Cert ID first.'); return; }
    await setEbayClientSecret(ebayCertInput.trim()); setEbayCertInput(''); setHasEbayCert(true);
    clearTokenCache();
    Alert.alert('Saved', 'eBay Cert ID stored in keychain.');
  }
  async function clearEbayCert()    { await setEbayClientSecret(null); setHasEbayCert(false); clearTokenCache(); }

  async function saveEbayRefresh() {
    if (!ebayRefreshInput.trim()) { Alert.alert('Empty', 'Paste your eBay refresh token first.'); return; }
    await setEbayRefreshToken(ebayRefreshInput.trim()); setEbayRefreshInput(''); setHasEbayRefresh(true);
    clearTokenCache();
    Alert.alert('Saved', 'eBay refresh token stored in keychain.');
  }
  async function clearEbayRefresh() { await setEbayRefreshToken(null); setHasEbayRefresh(false); clearTokenCache(); }

  async function saveEbayDev() {
    if (!ebayDevInput.trim()) { Alert.alert('Empty', 'Paste your eBay Dev ID first.'); return; }
    await setEbayDevId(ebayDevInput.trim()); setEbayDevInput(''); setHasEbayDev(true);
    Alert.alert('Saved', 'eBay Dev ID stored.');
  }
  async function clearEbayDev()     { await setEbayDevId(null); setHasEbayDev(false); }

  return (
    <SafeAreaView style={styles.root} edges={['top']}>
      <ScrollView contentContainerStyle={{ paddingBottom: 40 }}>
        <View style={styles.header}>
          <Text style={styles.eyebrow}>HARPUA SCANNER</Text>
          <Text style={styles.headerTitle}>Settings</Text>
        </View>

        <Section title="Anthropic API Key">
          {hasKey ? (
            <View style={styles.kvBox}>
              <Text style={styles.kvLabel}>Status</Text>
              <Text style={styles.kvVal}>● Saved (kept in iOS Keychain / Android encrypted prefs)</Text>
            </View>
          ) : (
            <Text style={styles.muted}>No key set. The scanner needs a Claude API key to identify cards.</Text>
          )}
          <TextInput
            value={keyInput}
            onChangeText={setKeyInput}
            placeholder={hasKey ? 'Paste new key to replace' : 'sk-ant-api03-...'}
            placeholderTextColor={theme.textDim}
            style={styles.input}
            secureTextEntry
            autoCapitalize="none"
            autoCorrect={false}
          />
          <View style={styles.btnRow}>
            <TouchableOpacity style={styles.btnGold} onPress={saveKey}>
              <Text style={styles.btnGoldText}>Save key</Text>
            </TouchableOpacity>
            {hasKey ? (
              <TouchableOpacity style={styles.btnGhost} onPress={clearKey}>
                <Text style={styles.btnGhostText}>Clear</Text>
              </TouchableOpacity>
            ) : null}
          </View>
          <Text style={styles.help}>Stored in iOS Keychain / Android encrypted prefs — never written to disk in plain text. Get a key at console.anthropic.com</Text>
        </Section>

        <Section title="SportsCardsPro API Key">
          {hasScpKey ? (
            <View style={styles.kvBox}>
              <Text style={styles.kvLabel}>Status</Text>
              <Text style={styles.kvVal}>● Saved — guide prices will blend into recommendations</Text>
            </View>
          ) : (
            <Text style={styles.muted}>Optional. With a key, scans pull canonical guide prices (PSA 10, PSA 9, raw, etc.) from sportscardspro.com.</Text>
          )}
          <TextInput
            value={scpInput}
            onChangeText={setScpInput}
            placeholder={hasScpKey ? 'Paste new token to replace' : 'pricecharting api token'}
            placeholderTextColor={theme.textDim}
            style={styles.input}
            secureTextEntry
            autoCapitalize="none"
            autoCorrect={false}
          />
          <View style={styles.btnRow}>
            <TouchableOpacity style={styles.btnGold} onPress={saveScpKey}>
              <Text style={styles.btnGoldText}>Save key</Text>
            </TouchableOpacity>
            {hasScpKey ? (
              <TouchableOpacity style={styles.btnGhost} onPress={clearScpKey}>
                <Text style={styles.btnGhostText}>Clear</Text>
              </TouchableOpacity>
            ) : null}
          </View>
          <Text style={styles.help}>Rate-limited to 1 request/sec by the provider — the app throttles automatically.</Text>
        </Section>

        <Section title="Identification Model">
          {MODELS.map((m) => (
            <Pressable
              key={m.value}
              onPress={() => chooseModel(m.value)}
              style={[styles.pickerRow, model === m.value && styles.pickerRowActive]}
            >
              <View style={{ flex: 1 }}>
                <Text style={styles.pickerLabel}>{m.label}</Text>
                <Text style={styles.pickerHint}>{m.hint}</Text>
              </View>
              {model === m.value ? <Text style={styles.check}>✓</Text> : null}
            </Pressable>
          ))}
        </Section>

        <Section title="Capture Quality">
          {QUALITIES.map((q) => (
            <Pressable
              key={q.value}
              onPress={() => chooseQuality(q.value)}
              style={[styles.pickerRow, quality === q.value && styles.pickerRowActive]}
            >
              <View style={{ flex: 1 }}>
                <Text style={styles.pickerLabel}>{q.label}</Text>
                <Text style={styles.pickerHint}>{q.hint}</Text>
              </View>
              {quality === q.value ? <Text style={styles.check}>✓</Text> : null}
            </Pressable>
          ))}
        </Section>

        <Section title="eBay Trading API">
          <Text style={styles.muted}>
            Required to create listings from the app. Use the same credentials as the web pipeline
            (configuration.json) — App ID, Cert ID, and a user OAuth refresh token from
            developer.ebay.com.
          </Text>

          <EbayField
            label="eBay App ID (client_id)"
            placeholder={hasEbayId ? 'Paste new App ID to replace' : 'YourApp-XXXXXX-PRD-...'}
            value={ebayIdInput}
            onChangeText={setEbayIdInput}
            saved={hasEbayId}
            onSave={saveEbayId}
            onClear={clearEbayId}
            secure={false}
          />
          <EbayField
            label="eBay Cert ID (client_secret)"
            placeholder={hasEbayCert ? 'Paste new Cert ID to replace' : 'PRD-...'}
            value={ebayCertInput}
            onChangeText={setEbayCertInput}
            saved={hasEbayCert}
            onSave={saveEbayCert}
            onClear={clearEbayCert}
            secure
          />
          <EbayField
            label="eBay refresh token"
            placeholder={hasEbayRefresh ? 'Paste new refresh token to replace' : 'v^1.1#i^1#...'}
            value={ebayRefreshInput}
            onChangeText={setEbayRefreshInput}
            saved={hasEbayRefresh}
            onSave={saveEbayRefresh}
            onClear={clearEbayRefresh}
            secure
          />
          <EbayField
            label="eBay Dev ID (optional)"
            placeholder={hasEbayDev ? 'Paste new Dev ID to replace' : 'GUID-style dev id'}
            value={ebayDevInput}
            onChangeText={setEbayDevInput}
            saved={hasEbayDev}
            onSave={saveEbayDev}
            onClear={clearEbayDev}
            secure={false}
          />
          <Text style={styles.help}>
            Listings are created against PRODUCTION eBay. Every "List it" action gets a confirmation prompt.
          </Text>
        </Section>

        <Section title="About">
          <Text style={styles.muted}>
            Harpua Scanner — local-first card inventory for the field. Photos and identification stay on the
            device unless you choose to sync. Pricing pulled from Pokemon TCG API (free, no key).
          </Text>
        </Section>
      </ScrollView>
    </SafeAreaView>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{title}</Text>
      <View style={styles.sectionBody}>{children}</View>
    </View>
  );
}

function EbayField(props: {
  label: string;
  placeholder: string;
  value: string;
  onChangeText: (v: string) => void;
  saved: boolean;
  onSave: () => void | Promise<void>;
  onClear: () => void | Promise<void>;
  secure: boolean;
}) {
  return (
    <View style={styles.ebayField}>
      <Text style={styles.ebayFieldLabel}>{props.label}</Text>
      <Text style={[styles.kvVal, { color: props.saved ? theme.success : theme.textDim, marginBottom: 6 }]}>
        {props.saved ? '● Saved' : '○ Not set'}
      </Text>
      <TextInput
        value={props.value}
        onChangeText={props.onChangeText}
        placeholder={props.placeholder}
        placeholderTextColor={theme.textDim}
        style={styles.input}
        secureTextEntry={props.secure}
        autoCapitalize="none"
        autoCorrect={false}
      />
      <View style={styles.btnRow}>
        <TouchableOpacity style={styles.btnGold} onPress={props.onSave}>
          <Text style={styles.btnGoldText}>Save</Text>
        </TouchableOpacity>
        {props.saved ? (
          <TouchableOpacity style={styles.btnGhost} onPress={props.onClear}>
            <Text style={styles.btnGhostText}>Clear</Text>
          </TouchableOpacity>
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.bg },
  header: { paddingHorizontal: 14, paddingTop: 4, paddingBottom: 10 },
  eyebrow: { color: theme.gold, fontSize: 10, fontWeight: '800', letterSpacing: 2 },
  headerTitle: { color: theme.text, fontSize: 28, fontWeight: '800', letterSpacing: -0.5 },

  section: { paddingHorizontal: 14, marginTop: 8 },
  sectionTitle: { color: theme.textMuted, fontSize: 10, fontWeight: '800', letterSpacing: 2, textTransform: 'uppercase', marginBottom: 8 },
  sectionBody: { backgroundColor: theme.surface, borderRadius: radii.md, borderColor: theme.border, borderWidth: 1, padding: 14 },

  kvBox: { marginBottom: 12 },
  kvLabel: { color: theme.textDim, fontSize: 10, fontWeight: '800', letterSpacing: 1.5, textTransform: 'uppercase' },
  kvVal: { color: theme.success, fontSize: 13, marginTop: 2 },

  input: { backgroundColor: theme.surface2, color: theme.text, borderColor: theme.border, borderWidth: 1, borderRadius: radii.sm, paddingHorizontal: 12, paddingVertical: 10, fontFamily: 'Menlo', fontSize: 13, marginBottom: 10 },
  btnRow: { flexDirection: 'row', gap: 8 },
  btnGold: { flex: 1, backgroundColor: theme.gold, paddingVertical: 12, borderRadius: radii.sm, alignItems: 'center' },
  btnGoldText: { color: '#0a0a0a', fontWeight: '800', fontSize: 13, textTransform: 'uppercase', letterSpacing: 0.6 },
  btnGhost: { backgroundColor: 'transparent', borderColor: theme.border, borderWidth: 1, paddingHorizontal: 16, paddingVertical: 12, borderRadius: radii.sm, alignItems: 'center' },
  btnGhostText: { color: theme.textMuted, fontWeight: '700', fontSize: 13, textTransform: 'uppercase', letterSpacing: 0.4 },
  help: { color: theme.textDim, fontSize: 11, marginTop: 8, lineHeight: 15 },
  muted: { color: theme.textMuted, fontSize: 13, lineHeight: 18 },

  ebayField: { marginTop: 14, paddingTop: 10, borderTopColor: theme.border, borderTopWidth: StyleSheet.hairlineWidth },
  ebayFieldLabel: { color: theme.textDim, fontSize: 10, fontWeight: '800', letterSpacing: 1.5, textTransform: 'uppercase', marginBottom: 4 },

  pickerRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: 8, borderTopColor: theme.border, borderTopWidth: StyleSheet.hairlineWidth },
  pickerRowActive: {},
  pickerLabel: { color: theme.text, fontSize: 14, fontWeight: '700' },
  pickerHint: { color: theme.textDim, fontSize: 11, marginTop: 2 },
  check: { color: theme.gold, fontSize: 18, fontWeight: '800', marginLeft: 8 },
});
