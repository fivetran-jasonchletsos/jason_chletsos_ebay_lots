import { CameraView, useCameraPermissions, CameraType } from 'expo-camera';
import { router } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Linking,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
  Platform,
} from 'react-native';
import { Image } from 'expo-image';
import * as Haptics from 'expo-haptics';
import { SafeAreaView } from 'react-native-safe-area-context';

import { theme, radii } from '@/src/theme';
import { identifyCard, type IdentifiedCard } from '@/src/api/identify';
import { fetchPricing, type PricingResult, ebaySearchUrl } from '@/src/api/pricing';
import { insertCard, listCards, type Card } from '@/src/db';
import { persistCardImages } from '@/src/image-store';
import { getAnthropicKey, getQuality } from '@/src/settings';

type Capture = { uri: string; side: 'front' | 'back' };

export default function ScanScreen() {
  const [permission, requestPermission] = useCameraPermissions();
  const cameraRef = useRef<CameraView | null>(null);
  const [facing] = useState<CameraType>('back');
  const [busy, setBusy] = useState(false);
  const [pendingFront, setPendingFront] = useState<string | null>(null);
  const [pendingBack, setPendingBack] = useState<string | null>(null);
  const [phase, setPhase] = useState<'idle' | 'identifying' | 'pricing' | 'saving'>('idle');
  const [statusText, setStatusText] = useState<string>('Ready');
  const [errorText, setErrorText] = useState<string | null>(null);
  const [recent, setRecent] = useState<Card[]>([]);
  const [hasKey, setHasKey] = useState<boolean | null>(null);

  useEffect(() => {
    getAnthropicKey().then((k) => setHasKey(!!k));
    refreshRecent();
  }, []);

  async function refreshRecent() {
    try { setRecent(await listCards({ limit: 6 })); } catch {}
  }

  if (!permission) {
    return <Centered text="Loading camera permission…" />;
  }
  if (!permission.granted) {
    return (
      <Centered>
        <Text style={styles.bigDim}>Camera access needed</Text>
        <Text style={styles.dim}>The scanner needs your camera to identify cards.</Text>
        <TouchableOpacity style={styles.btnGold} onPress={requestPermission}>
          <Text style={styles.btnGoldText}>Allow camera</Text>
        </TouchableOpacity>
      </Centered>
    );
  }

  async function capture(side: 'front' | 'back') {
    if (!cameraRef.current || busy) return;
    setBusy(true);
    try {
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
      const photo = await cameraRef.current.takePictureAsync({ quality: 1, skipProcessing: false });
      if (!photo?.uri) throw new Error('No photo');
      if (side === 'front') setPendingFront(photo.uri);
      else setPendingBack(photo.uri);
    } catch (e: any) {
      setErrorText(e?.message || 'Capture failed');
    } finally {
      setBusy(false);
    }
  }

  function discardCapture() {
    setPendingFront(null);
    setPendingBack(null);
    setErrorText(null);
    setPhase('idle');
    setStatusText('Ready');
  }

  async function processCard() {
    if (!pendingFront) return;
    if (!hasKey) {
      Alert.alert('No API key', 'Add your Anthropic key in Settings first.', [
        { text: 'Settings', onPress: () => router.push('/(tabs)/settings') },
        { text: 'Cancel', style: 'cancel' },
      ]);
      return;
    }
    setErrorText(null);
    setBusy(true);
    setPhase('identifying');
    setStatusText('Reading the card…');
    try {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      const { card: identified, raw } = await identifyCard(pendingFront, pendingBack ?? undefined);
      if (!identified.name) {
        throw new Error(identified.error || 'Could not identify');
      }
      setPhase('pricing');
      setStatusText(`Found ${identified.name} — looking up pricing…`);
      let pricing: PricingResult | null = null;
      try {
        pricing = await fetchPricing(identified);
      } catch (e: any) {
        pricing = { found: false };
      }

      setPhase('saving');
      setStatusText('Saving…');
      const tempId = 'card_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 8);
      const quality = await getQuality();
      const persisted = await persistCardImages(tempId, pendingFront, pendingBack ?? undefined, quality);
      const card = await insertCard({
        id: tempId,
        name: identified.name,
        set_name: identified.set_name ?? pricing?.set_name ?? null,
        set_code: identified.set_code,
        number: identified.number ?? pricing?.number ?? null,
        total: identified.total,
        rarity: identified.rarity ?? pricing?.rarity ?? null,
        foil: identified.foil,
        edition: identified.edition,
        language: identified.language,
        condition_hints: identified.condition_hints,
        confidence: identified.confidence,
        identify_raw: raw,
        tcg_id: pricing?.tcg_id ?? null,
        tcg_market: pricing?.tcg_market ?? null,
        tcg_low: pricing?.tcg_low ?? null,
        tcg_mid: pricing?.tcg_mid ?? null,
        tcg_high: pricing?.tcg_high ?? null,
        tcg_url: pricing?.tcg_url ?? null,
        cm_trend: pricing?.cm_trend ?? null,
        cm_avg30: pricing?.cm_avg30 ?? null,
        cm_low: pricing?.cm_low ?? null,
        cm_url: pricing?.cm_url ?? null,
        variant: pricing?.variant ?? null,
        pricing_raw: JSON.stringify(pricing),
        front_image: persisted.front,
        back_image: persisted.back ?? null,
        ref_image_url: pricing?.image_small ?? null,
        thumb_uri: persisted.thumb,
        listing_status: 'draft',
      } as any);

      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      setStatusText(`Saved ${card.name}`);
      setPendingFront(null);
      setPendingBack(null);
      setPhase('idle');
      refreshRecent();
      // Briefly preview the saved card via push to detail screen
      router.push({ pathname: '/card/[id]', params: { id: card.id } });
    } catch (e: any) {
      console.error(e);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      setErrorText(e?.message || 'Something went wrong');
      setPhase('idle');
      setStatusText('Failed — try again or discard');
    } finally {
      setBusy(false);
    }
  }

  // Pending review UI (after at least one capture)
  if (pendingFront) {
    return (
      <SafeAreaView style={styles.root} edges={['top']}>
        <ScrollView contentContainerStyle={{ padding: 14, paddingBottom: 80 }}>
          <Text style={styles.heading}>Review captures</Text>

          <View style={styles.previewRow}>
            <View style={styles.previewBox}>
              <Text style={styles.previewLabel}>Front</Text>
              <Image source={{ uri: pendingFront }} style={styles.previewImg} contentFit="cover" />
              <Pressable onPress={() => setPendingFront(null)} disabled={busy} style={styles.previewRetake}>
                <Text style={styles.previewRetakeText}>Retake</Text>
              </Pressable>
            </View>
            <View style={styles.previewBox}>
              <Text style={styles.previewLabel}>Back {pendingBack ? '' : '(optional)'}</Text>
              {pendingBack ? (
                <>
                  <Image source={{ uri: pendingBack }} style={styles.previewImg} contentFit="cover" />
                  <Pressable onPress={() => setPendingBack(null)} disabled={busy} style={styles.previewRetake}>
                    <Text style={styles.previewRetakeText}>Retake</Text>
                  </Pressable>
                </>
              ) : (
                <View style={[styles.previewImg, styles.previewEmpty]}>
                  <Text style={styles.dim}>Skip or shoot back</Text>
                </View>
              )}
            </View>
          </View>

          <View style={styles.cameraSmallWrap}>
            <CameraView ref={cameraRef} style={styles.cameraSmall} facing={facing} />
            <View style={styles.cameraSmallActions}>
              {!pendingBack ? (
                <TouchableOpacity style={styles.btnGoldSmall} onPress={() => capture('back')} disabled={busy}>
                  <Text style={styles.btnGoldText}>Shoot back</Text>
                </TouchableOpacity>
              ) : null}
              <TouchableOpacity style={styles.btnGhostSmall} onPress={discardCapture} disabled={busy}>
                <Text style={styles.btnGhostText}>Discard</Text>
              </TouchableOpacity>
            </View>
          </View>

          <View style={styles.statusBox}>
            {phase !== 'idle' ? <ActivityIndicator size="small" color={theme.gold} /> : null}
            <Text style={[styles.dim, { marginLeft: phase !== 'idle' ? 8 : 0 }]}>{statusText}</Text>
          </View>
          {errorText ? <Text style={styles.err}>⚠ {errorText}</Text> : null}

          <TouchableOpacity
            style={[styles.btnGold, busy && { opacity: 0.5 }]}
            onPress={processCard}
            disabled={busy}
          >
            <Text style={styles.btnGoldText}>{busy ? 'Working…' : 'Identify & save'}</Text>
          </TouchableOpacity>
        </ScrollView>
      </SafeAreaView>
    );
  }

  // Camera / idle UI
  return (
    <SafeAreaView style={styles.root} edges={['top']}>
      <View style={styles.header}>
        <View>
          <Text style={styles.eyebrow}>HARPUA SCANNER</Text>
          <Text style={styles.headerTitle}>Scan</Text>
        </View>
        {hasKey === false ? (
          <TouchableOpacity onPress={() => router.push('/(tabs)/settings')} style={styles.warnPill}>
            <Text style={styles.warnPillText}>Add API key →</Text>
          </TouchableOpacity>
        ) : null}
      </View>

      <View style={styles.cameraWrap}>
        <CameraView ref={cameraRef} style={styles.camera} facing={facing}>
          <View style={styles.cornerTL} />
          <View style={styles.cornerTR} />
          <View style={styles.cornerBL} />
          <View style={styles.cornerBR} />
        </CameraView>
      </View>

      <Text style={styles.hint}>Frame one card inside the gold corners.</Text>

      <View style={styles.shutterRow}>
        <View style={{ width: 60 }} />
        <Pressable
          onPress={() => capture('front')}
          disabled={busy}
          style={({ pressed }) => [styles.shutter, pressed && { transform: [{ scale: 0.94 }] }]}
        >
          {busy ? <ActivityIndicator color="#0a0a0a" /> : <View style={styles.shutterInner} />}
        </Pressable>
        <TouchableOpacity onPress={() => router.push('/(tabs)/inventory')} style={{ width: 60, alignItems: 'center' }}>
          <Text style={styles.dim}>📦</Text>
          <Text style={[styles.dim, { fontSize: 10 }]}>INVENTORY</Text>
        </TouchableOpacity>
      </View>

      {recent.length > 0 ? (
        <View style={styles.recentBlock}>
          <Text style={styles.recentLabel}>Recent</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ paddingHorizontal: 14, gap: 10 }}>
            {recent.map((c) => (
              <TouchableOpacity key={c.id} onPress={() => router.push({ pathname: '/card/[id]', params: { id: c.id } })} style={styles.recentItem}>
                {c.thumb_uri ? <Image source={{ uri: c.thumb_uri }} style={styles.recentThumb} /> : <View style={[styles.recentThumb, styles.previewEmpty]} />}
                <Text numberOfLines={1} style={styles.recentName}>{c.name ?? '—'}</Text>
                <Text style={styles.recentPrice}>{c.tcg_market != null ? `$${c.tcg_market.toFixed(2)}` : ''}</Text>
              </TouchableOpacity>
            ))}
          </ScrollView>
        </View>
      ) : null}
    </SafeAreaView>
  );
}

function Centered({ text, children }: { text?: string; children?: React.ReactNode }) {
  return (
    <SafeAreaView style={[styles.root, { justifyContent: 'center', alignItems: 'center', padding: 24 }]}>
      {children ?? <Text style={styles.dim}>{text}</Text>}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.bg },
  header: { paddingHorizontal: 14, paddingTop: 4, paddingBottom: 10, flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-end' },
  eyebrow: { color: theme.gold, fontSize: 10, fontWeight: '800', letterSpacing: 2 },
  headerTitle: { color: theme.text, fontSize: 28, fontWeight: '800', letterSpacing: -0.5 },
  warnPill: { backgroundColor: 'rgba(224,181,74,0.15)', borderColor: theme.warning, borderWidth: 1, borderRadius: radii.sm, paddingHorizontal: 10, paddingVertical: 6 },
  warnPillText: { color: theme.warning, fontWeight: '700', fontSize: 11, textTransform: 'uppercase', letterSpacing: 1 },

  cameraWrap: { marginHorizontal: 14, borderRadius: radii.md, overflow: 'hidden', borderWidth: 1, borderColor: theme.borderMid, aspectRatio: 3 / 4, backgroundColor: '#000' },
  camera: { flex: 1 },
  cornerTL: { position: 'absolute', top: 12, left: 12, width: 24, height: 24, borderColor: theme.gold, borderTopWidth: 2, borderLeftWidth: 2, borderTopLeftRadius: 4 },
  cornerTR: { position: 'absolute', top: 12, right: 12, width: 24, height: 24, borderColor: theme.gold, borderTopWidth: 2, borderRightWidth: 2, borderTopRightRadius: 4 },
  cornerBL: { position: 'absolute', bottom: 12, left: 12, width: 24, height: 24, borderColor: theme.gold, borderBottomWidth: 2, borderLeftWidth: 2, borderBottomLeftRadius: 4 },
  cornerBR: { position: 'absolute', bottom: 12, right: 12, width: 24, height: 24, borderColor: theme.gold, borderBottomWidth: 2, borderRightWidth: 2, borderBottomRightRadius: 4 },

  hint: { color: theme.textMuted, fontSize: 12, textAlign: 'center', marginTop: 10 },
  shutterRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: 30, marginTop: 14 },
  shutter: { width: 80, height: 80, borderRadius: 40, backgroundColor: theme.gold, alignItems: 'center', justifyContent: 'center', borderWidth: 4, borderColor: theme.bg },
  shutterInner: { width: 64, height: 64, borderRadius: 32, borderColor: theme.gold, borderWidth: 3 },

  recentBlock: { marginTop: 18, borderTopColor: theme.border, borderTopWidth: 1, paddingTop: 12 },
  recentLabel: { color: theme.textMuted, fontSize: 10, fontWeight: '800', letterSpacing: 2, marginHorizontal: 14, marginBottom: 8 },
  recentItem: { width: 90 },
  recentThumb: { width: 90, height: 120, borderRadius: radii.sm, backgroundColor: theme.surface, borderColor: theme.border, borderWidth: 1 },
  recentName: { color: theme.text, fontSize: 12, marginTop: 4, fontWeight: '600' },
  recentPrice: { color: theme.gold, fontSize: 12, fontWeight: '700', marginTop: 1 },

  heading: { color: theme.text, fontSize: 22, fontWeight: '800', letterSpacing: -0.5, marginBottom: 12 },
  previewRow: { flexDirection: 'row', gap: 10 },
  previewBox: { flex: 1 },
  previewLabel: { color: theme.textMuted, fontSize: 10, fontWeight: '800', letterSpacing: 1.5, marginBottom: 6 },
  previewImg: { aspectRatio: 3 / 4, borderRadius: radii.sm, backgroundColor: theme.surface, borderColor: theme.border, borderWidth: 1 },
  previewEmpty: { alignItems: 'center', justifyContent: 'center' },
  previewRetake: { position: 'absolute', bottom: 6, left: 6, backgroundColor: 'rgba(10,10,10,0.7)', paddingHorizontal: 8, paddingVertical: 4, borderRadius: radii.sm },
  previewRetakeText: { color: theme.text, fontSize: 11, fontWeight: '700' },

  cameraSmallWrap: { marginTop: 14, flexDirection: 'row', gap: 10 },
  cameraSmall: { width: 110, height: 150, borderRadius: radii.sm, overflow: 'hidden', backgroundColor: '#000' },
  cameraSmallActions: { flex: 1, justifyContent: 'center', gap: 8 },

  statusBox: { marginTop: 18, flexDirection: 'row', alignItems: 'center', justifyContent: 'center' },
  err: { color: theme.danger, textAlign: 'center', marginTop: 8 },

  btnGold: { backgroundColor: theme.gold, paddingVertical: 14, borderRadius: radii.md, alignItems: 'center', marginTop: 18 },
  btnGoldSmall: { backgroundColor: theme.gold, paddingVertical: 10, borderRadius: radii.sm, alignItems: 'center' },
  btnGoldText: { color: '#0a0a0a', fontWeight: '800', fontSize: 14, letterSpacing: 0.5, textTransform: 'uppercase' },
  btnGhostSmall: { backgroundColor: 'transparent', borderColor: theme.border, borderWidth: 1, paddingVertical: 10, borderRadius: radii.sm, alignItems: 'center' },
  btnGhostText: { color: theme.textMuted, fontWeight: '700', fontSize: 13, letterSpacing: 0.4, textTransform: 'uppercase' },

  bigDim: { color: theme.text, fontSize: 18, fontWeight: '700', marginBottom: 8 },
  dim: { color: theme.textMuted, fontSize: 13 },
});
