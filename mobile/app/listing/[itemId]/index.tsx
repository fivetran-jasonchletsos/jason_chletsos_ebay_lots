/**
 * Listing detail — single eBay item.
 *
 *   - Photo gallery (current eBay-hosted images, horizontal pager).
 *   - Photo health readout vs the top-seller 8+ at 1600px+ recommendation.
 *   - Inline price edit (confirmation required before live revise).
 *   - "Replace photos" routes to the camera flow.
 *   - "View on eBay" opens the public URL.
 */
import { router, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Animated,
  Linking,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
  useWindowDimensions,
} from 'react-native';
import { Image } from 'expo-image';
import * as Haptics from 'expo-haptics';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Price } from '@/components/Price';
import { fonts, radii, theme } from '@/src/theme';
import { getListing, revisePrice, type ListingDetail } from '@/src/api/listings';
import { EbayApiError, EbayAuthError } from '@/src/api/ebay';

const TOP_SELLER_PHOTO_TARGET = 8;

export default function ListingDetailScreen() {
  const { itemId } = useLocalSearchParams<{ itemId: string }>();
  const { width } = useWindowDimensions();

  const [listing, setListing] = useState<ListingDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [editingPrice, setEditingPrice] = useState(false);
  const [priceDraft, setPriceDraft] = useState('');
  const [savingPrice, setSavingPrice] = useState(false);

  const load = useCallback(async () => {
    if (!itemId) return;
    setLoading(true);
    setError(null);
    try {
      const l = await getListing(String(itemId));
      setListing(l);
      if (l.price != null) setPriceDraft(l.price.toFixed(2));
    } catch (e: any) {
      if (e instanceof EbayAuthError) setError('eBay authentication failed. Check Settings.');
      else if (e instanceof EbayApiError) setError(e.longMessage || e.message);
      else setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }, [itemId]);

  useEffect(() => { load(); }, [load]);

  function confirmPriceSave() {
    if (!listing) return;
    const next = parseFloat(priceDraft);
    if (!Number.isFinite(next) || next <= 0) {
      Alert.alert('Invalid price', 'Enter a positive dollar amount.');
      return;
    }
    if (listing.price != null && Math.abs(next - listing.price) < 0.005) {
      setEditingPrice(false);
      return;
    }
    Alert.alert(
      'Update price on eBay?',
      `Change "${listing.title.slice(0, 50)}${listing.title.length > 50 ? '…' : ''}" from $${listing.price?.toFixed(2) ?? '—'} to $${next.toFixed(2)}?`,
      [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Update', style: 'destructive', onPress: () => savePrice(next) },
      ],
    );
  }

  async function savePrice(next: number) {
    if (!listing) return;
    setSavingPrice(true);
    try {
      await revisePrice(listing.item_id, next);
      setEditingPrice(false);
      await load();
    } catch (e: any) {
      Alert.alert('Price update failed', e?.message || String(e));
    } finally {
      setSavingPrice(false);
    }
  }

  if (loading) {
    return (
      <SafeAreaView style={[styles.root, styles.center]}>
        <ActivityIndicator color={theme.gold} />
      </SafeAreaView>
    );
  }
  if (error || !listing) {
    return (
      <SafeAreaView style={[styles.root, styles.center]}>
        <Text style={[styles.bigDim, { color: theme.danger }]}>Couldn't load listing</Text>
        {error ? <Text style={[styles.muted, { textAlign: 'center', paddingHorizontal: 32, marginTop: 8 }]}>{error}</Text> : null}
        <TouchableOpacity style={styles.btnGold} onPress={() => load()}>
          <Text style={styles.btnGoldText}>Retry</Text>
        </TouchableOpacity>
      </SafeAreaView>
    );
  }

  const photoCount = listing.picture_urls.length;
  const photosLow = photoCount < TOP_SELLER_PHOTO_TARGET;
  const photoW = Math.min(width - 36, 380);

  return (
    <SafeAreaView style={styles.root} edges={['bottom']}>
      <ScrollView contentContainerStyle={{ paddingBottom: 40 }}>
        {/* Photo gallery */}
        <View style={styles.gallery}>
          {photoCount === 0 ? (
            <View style={[styles.photoPlaceholder, { width: photoW, height: photoW }]}>
              <Text style={styles.muted}>No photos on this listing.</Text>
            </View>
          ) : (
            <ScrollView horizontal pagingEnabled showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 12, paddingHorizontal: 18 }}>
              {listing.picture_urls.map((u, i) => (
                <Image key={`${u}-${i}`} source={{ uri: u }} style={[styles.photo, { width: photoW, height: photoW }]} contentFit="cover" />
              ))}
            </ScrollView>
          )}
        </View>

        {/* Photo health vs top-seller recommendation */}
        <View style={[styles.gateCard, photosLow ? styles.gateBad : styles.gateGood]}>
          <Text style={[styles.gateEyebrow, { color: photosLow ? theme.danger : theme.success }]}>
            PHOTO HEALTH
          </Text>
          <Text style={[styles.gateBig, { color: photosLow ? theme.danger : theme.success }]}>
            {photoCount} / {TOP_SELLER_PHOTO_TARGET}+
          </Text>
          <Text style={styles.gateExplain}>
            {photosLow
              ? `Add ${TOP_SELLER_PHOTO_TARGET - photoCount} more photo${TOP_SELLER_PHOTO_TARGET - photoCount === 1 ? '' : 's'} at 1600px or larger. Top sellers consistently post 8+ — listings below that tend to under-perform.`
              : 'Hits the top-seller recommendation. Aim for 1600px or larger on each shot.'}
          </Text>
          <TouchableOpacity style={[styles.btnGold, { marginTop: 12 }]} onPress={() => router.push(`/listing/${listing.item_id}/replace-photos`)}>
            <Text style={styles.btnGoldText}>{photoCount === 0 ? 'Add photos' : 'Replace photos'}</Text>
          </TouchableOpacity>
        </View>

        {/* Title */}
        <View style={styles.section}>
          <Text style={styles.label}>Title</Text>
          <Text style={styles.titleText}>{listing.title}</Text>
        </View>

        {/* Price (inline edit) */}
        <View style={styles.section}>
          <Text style={styles.label}>Price</Text>
          {editingPrice ? (
            <View>
              <View style={styles.priceRow}>
                <Text style={styles.priceCurrency}>$</Text>
                <TextInput
                  value={priceDraft}
                  onChangeText={setPriceDraft}
                  keyboardType="decimal-pad"
                  style={styles.priceInput}
                  placeholder="0.00"
                  placeholderTextColor={theme.textDim}
                  autoFocus
                />
              </View>
              <View style={{ flexDirection: 'row', gap: 8, marginTop: 10 }}>
                <View style={{ flex: 1 }}>
                  <GoldButton
                    label={savingPrice ? '' : 'Save price'}
                    onPress={confirmPriceSave}
                    disabled={savingPrice}
                  >
                    {savingPrice ? <ActivityIndicator color="#0a0a0a" /> : null}
                  </GoldButton>
                </View>
                <TouchableOpacity
                  style={[styles.btnGhost, { flex: 1 }]}
                  onPress={() => { setEditingPrice(false); setPriceDraft(listing.price?.toFixed(2) ?? ''); }}
                  disabled={savingPrice}
                >
                  <Text style={styles.btnGhostText}>Cancel</Text>
                </TouchableOpacity>
              </View>
            </View>
          ) : (
            <Pressable onPress={() => setEditingPrice(true)} style={({ pressed }) => [styles.priceDisplay, pressed && { opacity: 0.7 }]}>
              <Price value={listing.price ?? null} size="xl" />
              <Text style={styles.priceTapHint}>Tap to edit</Text>
            </Pressable>
          )}
        </View>

        {/* Engagement stat panel — three cells with vertical dividers above
            the condition/shipping grid. Stops the wall of identical-weight
            gray cells. */}
        <View style={styles.section}>
          <View style={styles.statPanel}>
            <StatCell
              label="Watchers"
              value={listing.watch_count != null ? String(listing.watch_count) : '—'}
            />
            <View style={styles.statDivider} />
            <StatCell
              label="Views"
              value={listing.view_count != null ? String(listing.view_count) : '—'}
            />
            <View style={styles.statDivider} />
            <StatCell label="Sold" value={String(listing.quantity_sold)} />
          </View>
        </View>

        {/* Meta */}
        <View style={styles.metaGrid}>
          <MetaCell label="Quantity" value={`${listing.quantity_available}/${listing.quantity}`} />
          <MetaCell label="Condition" value={listing.condition_label ?? '—'} />
          <MetaCell label="Category" value={listing.category_name ?? listing.category_id ?? '—'} />
          <MetaCell label="Best Offer" value={listing.best_offer_enabled ? 'Yes' : 'No'} />
          <MetaCell label="Free shipping" value={listing.free_shipping ? 'Yes' : 'No'} />
        </View>

        {/* Footer actions */}
        <View style={styles.section}>
          <TouchableOpacity style={styles.btnGhost} onPress={() => Linking.openURL(listing.view_url)}>
            <Text style={styles.btnGhostText}>View on eBay</Text>
          </TouchableOpacity>
          <Text style={styles.fineprint}>Item #{listing.item_id}</Text>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

function MetaCell({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.metaCell}>
      <Text style={styles.metaLabel}>{label}</Text>
      <Text style={styles.metaValue} numberOfLines={1}>{value}</Text>
    </View>
  );
}

function StatCell({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.statCell}>
      <Text style={styles.statValue}>{value}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  );
}

/**
 * Primary gold button with medium haptic + 120ms scale-down on press. The
 * extra friction is intentional — every push here is a write to a live eBay
 * listing.
 */
function GoldButton({
  label,
  onPress,
  disabled,
  children,
}: { label: string; onPress: () => void; disabled?: boolean; children?: React.ReactNode }) {
  const scale = useRef(new Animated.Value(1)).current;
  function handlePress() {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium).catch(() => { /* noop */ });
    Animated.sequence([
      Animated.timing(scale, { toValue: 0.97, duration: 60, useNativeDriver: true }),
      Animated.timing(scale, { toValue: 1, duration: 60, useNativeDriver: true }),
    ]).start();
    onPress();
  }
  return (
    <Animated.View style={{ transform: [{ scale }], opacity: disabled ? 0.6 : 1 }}>
      <TouchableOpacity
        activeOpacity={0.85}
        style={styles.btnGold}
        onPress={handlePress}
        disabled={disabled}
      >
        {children ?? <Text style={styles.btnGoldText}>{label}</Text>}
      </TouchableOpacity>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.bg },
  center: { alignItems: 'center', justifyContent: 'center', flex: 1 },
  muted: { color: theme.textMuted, fontSize: 13 },
  bigDim: { color: theme.text, fontSize: 18, fontWeight: '700' },

  gallery: { paddingVertical: 18 },
  photo: { borderRadius: radii.md, backgroundColor: theme.surface, borderColor: theme.border, borderWidth: 1 },
  photoPlaceholder: { padding: 18, alignItems: 'center', justifyContent: 'center', borderRadius: radii.md, backgroundColor: theme.surface, borderColor: theme.border, borderWidth: 1, alignSelf: 'center' },

  gateCard: { marginHorizontal: 18, padding: 14, borderRadius: radii.md, borderWidth: 1 },
  gateGood: { backgroundColor: 'rgba(127,199,122,0.08)', borderColor: 'rgba(127,199,122,0.4)' },
  gateBad: { backgroundColor: 'rgba(224,123,111,0.08)', borderColor: 'rgba(224,123,111,0.5)' },
  gateEyebrow: { fontSize: 10, fontWeight: '800', letterSpacing: 1.5 },
  gateBig: { fontSize: 30, fontWeight: '800', marginTop: 4, letterSpacing: -0.5 },
  gateExplain: { color: theme.textMuted, fontSize: 12, marginTop: 6, lineHeight: 17 },

  section: { paddingHorizontal: 18, marginTop: 16 },
  label: { color: theme.textDim, fontSize: 10, fontWeight: '800', letterSpacing: 1.5, textTransform: 'uppercase', marginBottom: 6 },
  titleText: { color: theme.text, fontSize: 17, fontWeight: '600', lineHeight: 23 },

  priceDisplay: { flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between', backgroundColor: theme.surface, borderColor: theme.border, borderWidth: 1, borderRadius: radii.sm, paddingHorizontal: 14, paddingVertical: 12 },
  priceTapHint: { color: theme.textDim, fontSize: 11 },

  statPanel: {
    flexDirection: 'row',
    backgroundColor: theme.surface,
    borderColor: theme.border,
    borderWidth: 1,
    borderRadius: radii.sm,
    paddingVertical: 12,
    paddingHorizontal: 6,
  },
  statCell: { flex: 1, alignItems: 'center', justifyContent: 'center', paddingVertical: 2 },
  statValue: { color: theme.goldBright, fontFamily: fonts.display, fontSize: 26, letterSpacing: 0 },
  statLabel: { color: theme.textDim, fontFamily: fonts.bodyBold, fontSize: 10, marginTop: 4, letterSpacing: 1.4, textTransform: 'uppercase' },
  statDivider: { width: StyleSheet.hairlineWidth, backgroundColor: theme.borderMid, marginVertical: 4 },

  priceRow: { flexDirection: 'row', alignItems: 'center', backgroundColor: theme.surface, borderColor: theme.border, borderWidth: 1, borderRadius: radii.sm, paddingHorizontal: 12 },
  priceCurrency: { color: theme.gold, fontSize: 20, fontWeight: '800', marginRight: 6 },
  priceInput: { flex: 1, color: theme.text, fontSize: 22, fontWeight: '700', paddingVertical: 10 },

  metaGrid: { flexDirection: 'row', flexWrap: 'wrap', paddingHorizontal: 12, marginTop: 14 },
  metaCell: { width: '50%', paddingHorizontal: 6, marginTop: 8 },
  metaLabel: { color: theme.textDim, fontSize: 9, fontWeight: '800', letterSpacing: 1.5, textTransform: 'uppercase' },
  metaValue: { color: theme.text, fontSize: 14, fontWeight: '600', marginTop: 2 },

  btnGold: { backgroundColor: theme.gold, paddingVertical: 12, borderRadius: radii.sm, alignItems: 'center' },
  btnGoldText: { color: '#0a0a0a', fontWeight: '800', fontSize: 13, textTransform: 'uppercase', letterSpacing: 0.6 },
  btnGhost: { backgroundColor: 'transparent', borderColor: theme.border, borderWidth: 1, paddingVertical: 12, borderRadius: radii.sm, alignItems: 'center' },
  btnGhostText: { color: theme.textMuted, fontWeight: '700', fontSize: 13, textTransform: 'uppercase', letterSpacing: 0.5 },

  fineprint: { color: theme.textDim, fontSize: 11, marginTop: 10, textAlign: 'center' },
});
