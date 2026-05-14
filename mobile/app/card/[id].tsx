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
import { ebaySearchUrl } from '@/src/api/pricing';

const CONDITIONS = ['Near Mint', 'Lightly Played', 'Moderately Played', 'Heavily Played', 'Damaged'];

export default function CardDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [card, setCard] = useState<Card | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [draftPrice, setDraftPrice] = useState('');
  const [draftNotes, setDraftNotes] = useState('');
  const [draftCondition, setDraftCondition] = useState<string | null>(null);

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
    // Phase 4 will wire AddFixedPriceItem to your existing Trading API auth.
    // For now: pre-fill an eBay sold-search and copy a draft title.
    Alert.alert(
      'List on eBay',
      'Direct AddFixedPriceItem is wired in phase 4. For now we open eBay sold listings so you can sanity-check pricing before listing.',
      [
        { text: 'Open eBay sold', onPress: () => Linking.openURL(ebaySearchUrl({ name: card.name ?? '', set_name: card.set_name, number: card.number, foil: card.foil } as any)) },
        { text: 'Cancel', style: 'cancel' },
      ],
    );
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
});
