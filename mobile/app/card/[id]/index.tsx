import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import {
  Alert,
  Linking,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { Image } from 'expo-image';
import { SafeAreaView } from 'react-native-safe-area-context';

import { theme, radii } from '@/src/theme';
import { deleteCard, getCard, updateCard, type Card } from '@/src/db';
import { deleteCardImages } from '@/src/image-store';
import { ebaySearchUrl, type PriceSource, type SuggestedPrice, type PricingResult } from '@/src/api/pricing';

const CONDITIONS = ['Near Mint', 'Lightly Played', 'Moderately Played', 'Heavily Played', 'Damaged'];

export default function CardDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [card, setCard] = useState<Card | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [draftPrice, setDraftPrice] = useState('');
  const [draftNotes, setDraftNotes] = useState('');
  const [draftCondition, setDraftCondition] = useState<string | null>(null);
  const [sourcesExpanded, setSourcesExpanded] = useState(false);

  // Parsed pricing payload (sources + suggested) stashed in pricing_raw at scan time.
  const pricingPayload: PricingResult | null = (() => {
    const raw = (card as any)?.pricing_raw;
    if (!raw || typeof raw !== 'string') return null;
    try { return JSON.parse(raw) as PricingResult; } catch { return null; }
  })();
  const sources: PriceSource[] = pricingPayload?.sources ?? [];
  const suggested: SuggestedPrice | null = pricingPayload?.suggested ?? null;

  useEffect(() => {
    (async () => {
      if (!id) return;
      const c = await getCard(String(id));
      setCard(c);
      if (c) {
        setDraftPrice(c.user_price != null ? String(c.user_price) : '');
        setDraftNotes(c.notes ?? '');
        setDraftCondition(c.condition ?? null);
      }
      setLoading(false);
    })();
  }, [id]);

  async function saveEdits() {
    if (!card) return;
    const priceNum = draftPrice.trim() === '' ? null : parseFloat(draftPrice);
    const updated = await updateCard(card.id, {
      user_price: Number.isFinite(priceNum as number) ? (priceNum as number) : null,
      notes: draftNotes.trim() || null,
      condition: draftCondition,
    });
    setCard(updated);
    setEditing(false);
  }

  async function removeCard() {
    if (!card) return;
    Alert.alert('Delete card', `Remove "${card.name ?? 'Untitled'}" from inventory? This cannot be undone.`, [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Delete',
        style: 'destructive',
        onPress: async () => {
          await deleteCard(card.id);
          await deleteCardImages(card.id);
          router.back();
        },
      },
    ]);
  }

  function listOnEbay() {
    if (!card) return;
    router.push({ pathname: '/card/[id]/list-on-ebay', params: { id: card.id } });
  }

  if (loading) return <SafeAreaView style={[styles.root, styles.center]}><Text style={styles.muted}>Loading…</Text></SafeAreaView>;
  if (!card) return <SafeAreaView style={[styles.root, styles.center]}><Text style={styles.muted}>Card not found.</Text></SafeAreaView>;

  return (
    <SafeAreaView style={styles.root} edges={['bottom']}>
      <ScrollView contentContainerStyle={{ paddingBottom: 30 }}>
        <View style={styles.hero}>
          <View style={styles.heroImages}>
            {card.front_image ? <Image source={{ uri: card.front_image }} style={styles.heroImg} contentFit="cover" /> : null}
            {card.back_image ? <Image source={{ uri: card.back_image }} style={styles.heroImg} contentFit="cover" /> : null}
            {card.ref_image_url && !card.back_image ? <Image source={{ uri: card.ref_image_url }} style={styles.heroImg} contentFit="cover" /> : null}
          </View>
          <View style={styles.heroInfo}>
            <Text style={styles.eyebrow}>{card.set_code || (card.tcg_id ? card.tcg_id.split('-')[0].toUpperCase() : 'CARD')}</Text>
            <Text style={styles.title}>{card.name ?? 'Unknown'}</Text>
            <Text style={styles.subtitle}>
              {[card.set_name, card.number ? `#${card.number}` : null, card.rarity].filter(Boolean).join(' · ')}
              {card.foil ? ' · FOIL' : ''}
            </Text>
            {card.confidence === 'low' ? <Text style={styles.lowConf}>⚠ Low confidence identification — verify before listing</Text> : null}
          </View>
        </View>

        {suggested && suggested.suggested > 0 ? (
          <View style={styles.suggestWrap}>
            <View style={[styles.suggestPill, suggestStyle(suggested.confidence)]}>
              <View style={{ flex: 1 }}>
                <Text style={styles.suggestEyebrow}>SUGGESTED · {suggested.basis.toUpperCase()} · {suggested.confidence.toUpperCase()}</Text>
                <Text style={styles.suggestPrice}>${suggested.suggested.toFixed(2)}</Text>
                <Text style={styles.suggestReason}>{suggested.reasoning}</Text>
              </View>
            </View>
          </View>
        ) : null}

        <View style={styles.priceGrid}>
          <PriceCell label="TCG Market" value={fmt(card.tcg_market)} accent />
          <PriceCell label="TCG Low" value={fmt(card.tcg_low)} />
          <PriceCell label="CM Trend" value={fmt(card.cm_trend)} />
        </View>
        <View style={styles.priceGrid}>
          <PriceCell label="TCG Mid" value={fmt(card.tcg_mid)} />
          <PriceCell label="TCG High" value={fmt(card.tcg_high)} />
          <PriceCell label="CM 30d avg" value={fmt(card.cm_avg30)} />
        </View>

        {sources.length > 0 ? (
          <View style={styles.section}>
            <TouchableOpacity onPress={() => setSourcesExpanded((v) => !v)} style={styles.sectionHeader}>
              <Text style={styles.sectionLabel}>Pricing sources · {sources.length}</Text>
              <Text style={styles.linkAction}>{sourcesExpanded ? 'Hide' : 'Show'}</Text>
            </TouchableOpacity>
            {sourcesExpanded ? (
              <View>
                {sources.map((s, idx) => (
                  <SourceRow key={`${s.source}-${idx}`} src={s} />
                ))}
              </View>
            ) : null}
          </View>
        ) : null}

        <View style={styles.section}>
          <View style={styles.sectionHeader}>
            <Text style={styles.sectionLabel}>Your data</Text>
            <TouchableOpacity onPress={() => editing ? saveEdits() : setEditing(true)}>
              <Text style={styles.linkAction}>{editing ? 'Save' : 'Edit'}</Text>
            </TouchableOpacity>
          </View>

          <Field label="Your list price">
            {editing ? (
              <TextInput
                value={draftPrice}
                onChangeText={setDraftPrice}
                keyboardType="decimal-pad"
                style={styles.input}
                placeholder="0.00"
                placeholderTextColor={theme.textDim}
              />
            ) : (
              <Text style={styles.fieldVal}>{card.user_price != null ? `$${card.user_price.toFixed(2)}` : '—'}</Text>
            )}
          </Field>

          <Field label="Condition">
            {editing ? (
              <View style={styles.conditionChips}>
                {CONDITIONS.map((c) => (
                  <Pressable key={c} onPress={() => setDraftCondition(c)} style={[styles.condChip, draftCondition === c && styles.condChipActive]}>
                    <Text style={[styles.condChipText, draftCondition === c && styles.condChipTextActive]}>{c}</Text>
                  </Pressable>
                ))}
              </View>
            ) : (
              <Text style={styles.fieldVal}>{card.condition ?? '—'}</Text>
            )}
          </Field>

          <Field label="Notes">
            {editing ? (
              <TextInput
                value={draftNotes}
                onChangeText={setDraftNotes}
                style={[styles.input, { minHeight: 80 }]}
                multiline
                placeholder="Anything about this copy…"
                placeholderTextColor={theme.textDim}
              />
            ) : (
              <Text style={styles.fieldVal}>{card.notes ?? '—'}</Text>
            )}
          </Field>

          {card.condition_hints ? (
            <Field label="Vision condition hints">
              <Text style={[styles.fieldVal, { color: theme.textMuted, fontStyle: 'italic' }]}>{card.condition_hints}</Text>
            </Field>
          ) : null}
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionLabel}>Actions</Text>
          <TouchableOpacity style={styles.btnGold} onPress={listOnEbay}>
            <Text style={styles.btnGoldText}>List on eBay</Text>
          </TouchableOpacity>
          <View style={styles.linkRow}>
            {card.tcg_url ? <LinkBtn label="TCGplayer" url={card.tcg_url} /> : null}
            {card.cm_url ? <LinkBtn label="Cardmarket" url={card.cm_url} /> : null}
            <LinkBtn label="eBay sold" url={ebaySearchUrl({ name: card.name ?? '', set_name: card.set_name, number: card.number, foil: card.foil } as any)} />
          </View>
          <TouchableOpacity style={styles.btnDanger} onPress={removeCard}>
            <Text style={styles.btnDangerText}>Delete from inventory</Text>
          </TouchableOpacity>
        </View>

        <View style={styles.meta}>
          <Text style={styles.metaText}>Captured {new Date(card.captured_at).toLocaleString()}</Text>
          {card.synced_at ? <Text style={styles.metaText}>Synced {new Date(card.synced_at).toLocaleString()}</Text> : <Text style={styles.metaText}>Not synced</Text>}
          <Text style={styles.metaText}>id {card.id}</Text>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

function PriceCell({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <View style={[styles.priceCell, accent && { borderColor: theme.gold }]}>
      <Text style={styles.priceLabel}>{label}</Text>
      <Text style={[styles.priceVal, accent && { color: theme.gold }]}>{value}</Text>
    </View>
  );
}

function SourceRow({ src }: { src: PriceSource }) {
  const confPct = src.confidence != null ? Math.round(src.confidence * 100) : null;
  return (
    <View style={styles.sourceRow}>
      <View style={{ flex: 1 }}>
        <View style={styles.sourceTopLine}>
          <Text style={styles.sourceLabel}>{src.label}</Text>
          {confPct != null ? (
            <View style={[styles.confPip, confStyle(src.confidence ?? 0)]}>
              <Text style={styles.confPipText}>{confPct}%</Text>
            </View>
          ) : null}
        </View>
        <Text style={styles.sourceMedian}>${src.median.toFixed(2)}</Text>
        <Text style={styles.sourceMeta}>
          Range ${src.low.toFixed(2)}–${src.high.toFixed(2)} · n={src.count}
          {src.matched_title ? ` · matched: ${src.matched_title.slice(0, 60)}` : ''}
        </Text>
      </View>
      {src.url ? (
        <TouchableOpacity onPress={() => Linking.openURL(src.url!)} style={styles.sourceLink}>
          <Text style={styles.sourceLinkText}>Open ↗</Text>
        </TouchableOpacity>
      ) : null}
    </View>
  );
}

function suggestStyle(conf: 'high' | 'medium' | 'low') {
  if (conf === 'high')   return { borderColor: theme.gold,    backgroundColor: 'rgba(212,175,55,0.10)' };
  if (conf === 'medium') return { borderColor: theme.borderMid, backgroundColor: 'rgba(212,175,55,0.05)' };
  return { borderColor: 'rgba(224,123,111,0.4)', backgroundColor: 'rgba(224,123,111,0.05)' };
}
function confStyle(c: number) {
  if (c >= 0.7) return { backgroundColor: 'rgba(127,199,122,0.25)', borderColor: theme.success };
  if (c >= 0.4) return { backgroundColor: 'rgba(224,181,74,0.20)',  borderColor: theme.warning };
  return            { backgroundColor: 'rgba(224,123,111,0.20)',    borderColor: theme.danger };
}

function LinkBtn({ label, url }: { label: string; url: string }) {
  return (
    <TouchableOpacity style={styles.linkBtn} onPress={() => Linking.openURL(url)}>
      <Text style={styles.linkBtnText}>{label} →</Text>
    </TouchableOpacity>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <View style={styles.field}>
      <Text style={styles.fieldLabel}>{label}</Text>
      {children}
    </View>
  );
}

function fmt(n: number | null): string {
  if (n == null || Number.isNaN(n)) return '—';
  return `$${n.toFixed(2)}`;
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.bg },
  center: { alignItems: 'center', justifyContent: 'center' },
  muted: { color: theme.textMuted, fontSize: 14 },

  hero: { padding: 14 },
  heroImages: { flexDirection: 'row', gap: 8 },
  heroImg: { flex: 1, aspectRatio: 3 / 4, borderRadius: radii.sm, backgroundColor: theme.surface, borderColor: theme.border, borderWidth: 1 },
  heroInfo: { marginTop: 14 },
  eyebrow: { color: theme.gold, fontSize: 10, fontWeight: '800', letterSpacing: 2 },
  title: { color: theme.text, fontSize: 26, fontWeight: '800', letterSpacing: -0.5, marginTop: 2 },
  subtitle: { color: theme.textMuted, fontSize: 13, marginTop: 4 },
  lowConf: { color: theme.warning, fontSize: 12, marginTop: 8 },

  priceGrid: { flexDirection: 'row', gap: 8, paddingHorizontal: 14, marginBottom: 8 },
  priceCell: { flex: 1, borderColor: theme.border, borderWidth: 1, borderRadius: radii.sm, paddingHorizontal: 10, paddingVertical: 8, backgroundColor: theme.surface },
  priceLabel: { color: theme.textDim, fontSize: 9, fontWeight: '800', letterSpacing: 1.5, textTransform: 'uppercase' },
  priceVal: { color: theme.text, fontSize: 22, fontWeight: '800', marginTop: 2, letterSpacing: -0.5 },

  section: { marginTop: 12, paddingHorizontal: 14 },
  sectionHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline' },
  sectionLabel: { color: theme.textMuted, fontSize: 10, fontWeight: '800', letterSpacing: 2, textTransform: 'uppercase', marginBottom: 8 },
  linkAction: { color: theme.gold, fontSize: 13, fontWeight: '700' },

  field: { marginBottom: 12 },
  fieldLabel: { color: theme.textDim, fontSize: 10, fontWeight: '800', letterSpacing: 1.5, textTransform: 'uppercase', marginBottom: 4 },
  fieldVal: { color: theme.text, fontSize: 15 },
  input: { backgroundColor: theme.surface, color: theme.text, borderColor: theme.border, borderWidth: 1, borderRadius: radii.sm, paddingHorizontal: 12, paddingVertical: 10, fontSize: 14 },

  conditionChips: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  condChip: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999, borderColor: theme.border, borderWidth: 1, backgroundColor: theme.surface2 },
  condChipActive: { borderColor: theme.gold, backgroundColor: 'rgba(212,175,55,0.15)' },
  condChipText: { color: theme.textMuted, fontSize: 11, fontWeight: '700' },
  condChipTextActive: { color: theme.gold },

  btnGold: { backgroundColor: theme.gold, paddingVertical: 14, borderRadius: radii.sm, alignItems: 'center', marginTop: 4 },
  btnGoldText: { color: '#0a0a0a', fontWeight: '800', fontSize: 14, textTransform: 'uppercase', letterSpacing: 0.6 },
  linkRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 10 },
  linkBtn: { paddingHorizontal: 12, paddingVertical: 8, borderRadius: radii.sm, backgroundColor: theme.surface, borderColor: theme.border, borderWidth: 1 },
  linkBtnText: { color: theme.text, fontSize: 12, fontWeight: '700' },

  btnDanger: { marginTop: 18, paddingVertical: 12, borderRadius: radii.sm, alignItems: 'center', borderColor: 'rgba(224,123,111,0.4)', borderWidth: 1, backgroundColor: 'rgba(224,123,111,0.05)' },
  btnDangerText: { color: theme.danger, fontWeight: '700', textTransform: 'uppercase', letterSpacing: 0.5, fontSize: 12 },

  meta: { marginTop: 24, paddingHorizontal: 14 },
  metaText: { color: theme.textDim, fontSize: 11, marginBottom: 4 },

  suggestWrap: { paddingHorizontal: 14, marginBottom: 10 },
  suggestPill: { borderWidth: 1, borderRadius: radii.md, paddingHorizontal: 14, paddingVertical: 12, flexDirection: 'row', alignItems: 'center' },
  suggestEyebrow: { color: theme.gold, fontSize: 9, fontWeight: '800', letterSpacing: 1.8 },
  suggestPrice: { color: theme.text, fontSize: 28, fontWeight: '800', letterSpacing: -0.5, marginTop: 2 },
  suggestReason: { color: theme.textMuted, fontSize: 12, marginTop: 4, lineHeight: 16 },

  sourceRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: 10, borderTopColor: theme.border, borderTopWidth: StyleSheet.hairlineWidth },
  sourceTopLine: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  sourceLabel: { color: theme.text, fontSize: 13, fontWeight: '700' },
  sourceMedian: { color: theme.gold, fontSize: 18, fontWeight: '800', marginTop: 2 },
  sourceMeta: { color: theme.textDim, fontSize: 11, marginTop: 2 },
  sourceLink: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: radii.sm, backgroundColor: theme.surface2, borderColor: theme.border, borderWidth: 1 },
  sourceLinkText: { color: theme.text, fontSize: 11, fontWeight: '700' },
  confPip: { borderWidth: 1, borderRadius: 999, paddingHorizontal: 6, paddingVertical: 1 },
  confPipText: { color: theme.text, fontSize: 9, fontWeight: '800' },
});
