/**
 * Best Offers tab — every pending buyer offer across the seller's listings.
 *
 * Each row shows the listing thumbnail + buyer + their offer vs list price,
 * and three actions: Accept, Counter, Decline. Counter pops a single input.
 * Each action confirms before hitting the eBay Trading API.
 *
 * Offers decay fast — buyers ping three sellers and take the first response.
 * One-tap accept from the phone is the whole reason this tab exists.
 */
import { useFocusEffect } from 'expo-router';
import { useCallback, useRef, useState } from 'react';
import {
  Animated,
  ActivityIndicator,
  Alert,
  Modal,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { FlashList } from '@shopify/flash-list';
import { Image } from 'expo-image';
import * as Haptics from 'expo-haptics';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Price } from '@/components/Price';
import { fonts, radii, theme } from '@/src/theme';
import {
  getBestOffers,
  respondToBestOffer,
  type BestOffer,
  type OfferAction,
} from '@/src/api/listings';
import { EbayApiError, EbayAuthError } from '@/src/api/ebay';
import { getEbayCredentials } from '@/src/settings';

export default function OffersScreen() {
  const [offers, setOffers] = useState<BestOffer[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasCreds, setHasCreds] = useState<boolean | null>(null);

  // Counter modal state.
  const [counterTarget, setCounterTarget] = useState<BestOffer | null>(null);
  const [counterPrice, setCounterPrice] = useState('');
  // Per-row in-flight lock — keyed by best_offer_id. We only disable the
  // row whose submit is pending, so Accept on offer A doesn't block Decline
  // on offer B. The Set is replaced on add/remove so React picks up the
  // identity change.
  const [inFlight, setInFlight] = useState<Set<string>>(new Set());

  const load = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    else setLoading(true);
    setError(null);
    try {
      const creds = await getEbayCredentials();
      setHasCreds(!!creds);
      if (!creds) { setOffers([]); return; }
      const list = await getBestOffers();
      setOffers(list);
    } catch (e: any) {
      if (e instanceof EbayAuthError) setError('Couldn\'t authenticate with eBay. Check Settings.');
      else if (e instanceof EbayApiError) setError(e.longMessage || e.message);
      else setError(e?.message || String(e));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(false); }, [load]));

  function confirmAction(offer: BestOffer, action: OfferAction) {
    const summary = action === 'Accept'
      ? `Accepting closes the listing and charges the buyer $${offer.offer_price.toFixed(2)}.`
      : `Decline ${offer.buyer_user_id}'s $${offer.offer_price.toFixed(2)} offer on "${offer.item_title.slice(0, 40)}…"?`;
    Alert.alert(
      `${action} offer?`,
      summary,
      [
        { text: 'Cancel', style: 'cancel' },
        { text: action, style: action === 'Decline' ? 'destructive' : 'default', onPress: () => submit(offer, action) },
      ],
    );
  }

  function openCounter(offer: BestOffer) {
    setCounterTarget(offer);
    // Default counter is the midpoint, charm-priced to $x.99 just above it —
    // a counter below the midpoint barely feels like a counter. Clamp the
    // floor to `offer_price + 0.01` so the suggested counter is always
    // strictly greater than the buyer's offer.
    const list = offer.item_price ?? offer.offer_price;
    const mid = (offer.offer_price + list) / 2;
    const charm = Math.ceil(mid) - 0.01;
    const floor = offer.offer_price + 0.01;
    const suggested = Math.max(0.5, floor, charm);
    setCounterPrice(suggested.toFixed(2));
  }

  function submitCounter() {
    if (!counterTarget) return;
    const n = parseFloat(counterPrice);
    if (!Number.isFinite(n) || n <= 0) {
      Alert.alert('Invalid counter', 'Enter a positive dollar amount.');
      return;
    }
    // A counter must be strictly greater than what the buyer offered —
    // otherwise it isn't actually a counter, just a re-acceptance.
    if (n <= counterTarget.offer_price) {
      Alert.alert(
        'Counter must be higher',
        `Counter must be higher than the buyer's offer of $${counterTarget.offer_price.toFixed(2)}.`,
      );
      return;
    }
    if (counterTarget.item_price != null && n >= counterTarget.item_price) {
      Alert.alert('Counter too high', `Counter must be below the listing price of $${counterTarget.item_price.toFixed(2)}.`);
      return;
    }
    Alert.alert(
      'Send counter?',
      `Counter ${counterTarget.buyer_user_id} at $${n.toFixed(2)} on "${counterTarget.item_title.slice(0, 40)}…"?`,
      [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Send counter', onPress: () => {
          const target = counterTarget;
          setCounterTarget(null);
          submit(target, 'Counter', n);
        } },
      ],
    );
  }

  async function submit(offer: BestOffer, action: OfferAction, counter?: number) {
    setInFlight((prev) => {
      const next = new Set(prev);
      next.add(offer.best_offer_id);
      return next;
    });
    try {
      await respondToBestOffer({
        item_id: offer.item_id,
        best_offer_id: offer.best_offer_id,
        action,
        counter_price: counter,
      });
      setOffers((prev) => prev.filter((o) => o.best_offer_id !== offer.best_offer_id));
    } catch (e: any) {
      Alert.alert(`${action} failed`, e?.longMessage || e?.message || String(e));
    } finally {
      setInFlight((prev) => {
        const next = new Set(prev);
        next.delete(offer.best_offer_id);
        return next;
      });
    }
  }

  if (loading && offers.length === 0) {
    return (
      <SafeAreaView style={[styles.root, styles.center]}>
        <ActivityIndicator color={theme.gold} />
        <Text style={[styles.muted, { marginTop: 12 }]}>Loading offers…</Text>
      </SafeAreaView>
    );
  }
  if (hasCreds === false) {
    return (
      <SafeAreaView style={[styles.root, styles.center]}>
        <Text style={styles.bigDim}>eBay not connected</Text>
        <Text style={[styles.muted, { textAlign: 'center', paddingHorizontal: 32, marginTop: 8 }]}>
          Add your eBay credentials in Settings to load offers.
        </Text>
      </SafeAreaView>
    );
  }
  if (error && offers.length === 0) {
    return (
      <SafeAreaView style={[styles.root, styles.center]}>
        <Text style={[styles.bigDim, { color: theme.danger }]}>Couldn't load offers</Text>
        <Text style={[styles.muted, { textAlign: 'center', paddingHorizontal: 32, marginTop: 8 }]}>{error}</Text>
        <TouchableOpacity style={styles.btnGold} onPress={() => load(false)}>
          <Text style={styles.btnGoldText}>Retry</Text>
        </TouchableOpacity>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.root} edges={['top']}>
      <View style={styles.header}>
        <Text style={styles.eyebrow}>PENDING BEST OFFERS</Text>
        <Text style={styles.title}>{offers.length}</Text>
        <Text style={styles.sub}>Tap accept / counter / decline. Offers expire on eBay's clock.</Text>
      </View>

      <FlashList
        data={offers}
        keyExtractor={(o) => o.best_offer_id}
        contentContainerStyle={{ paddingBottom: 32 }}
        refreshControl={<RefreshControl tintColor={theme.gold} refreshing={refreshing} onRefresh={() => load(true)} />}
        renderItem={({ item }) => (
          <OfferRow
            offer={item}
            disabled={inFlight.has(item.best_offer_id)}
            onAccept={() => confirmAction(item, 'Accept')}
            onDecline={() => confirmAction(item, 'Decline')}
            onCounter={() => openCounter(item)}
          />
        )}
        ListEmptyComponent={() => (
          <View style={[styles.center, { paddingTop: 80 }]}>
            {/* One oversized Fraunces line + a small Familjen caption beats
                the two-line muted gray we had before. */}
            <Text style={styles.emptyTitle}>All caught up.</Text>
            <Text style={styles.emptyCaption}>No pending offers right now. Pull to refresh.</Text>
          </View>
        )}
      />

      <Modal transparent visible={!!counterTarget} animationType="fade" onRequestClose={() => setCounterTarget(null)}>
        <Pressable style={styles.modalBackdrop} onPress={() => setCounterTarget(null)}>
          <Pressable style={styles.modalCard} onPress={(e) => e.stopPropagation()}>
            <Text style={styles.modalEyebrow}>COUNTER OFFER</Text>
            <Text style={styles.modalTitle} numberOfLines={2}>{counterTarget?.item_title}</Text>
            <View style={styles.modalCompareRow}>
              <CompareCell label="List">
                <Price value={counterTarget?.item_price ?? null} size="md" tone="muted" />
              </CompareCell>
              <CompareCell label="Offer">
                <Price value={counterTarget?.offer_price ?? null} size="md" />
              </CompareCell>
            </View>
            <Text style={styles.modalLabel}>Your counter</Text>
            <View style={styles.priceRow}>
              <Text style={styles.priceCurrency}>$</Text>
              <TextInput
                value={counterPrice}
                onChangeText={setCounterPrice}
                keyboardType="decimal-pad"
                style={styles.priceInput}
                placeholder="0.00"
                placeholderTextColor={theme.textDim}
                autoFocus
              />
            </View>
            <View style={{ flexDirection: 'row', gap: 8, marginTop: 14 }}>
              <TouchableOpacity
                style={[styles.btnGold, { flex: 1 }]}
                onPress={submitCounter}
                disabled={counterTarget != null && inFlight.has(counterTarget.best_offer_id)}
              >
                <Text style={styles.btnGoldText}>Send counter</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.btnGhost, { flex: 1 }]}
                onPress={() => setCounterTarget(null)}
                disabled={counterTarget != null && inFlight.has(counterTarget.best_offer_id)}
              >
                <Text style={styles.btnGhostText}>Cancel</Text>
              </TouchableOpacity>
            </View>
          </Pressable>
        </Pressable>
      </Modal>
    </SafeAreaView>
  );
}

function OfferRow({
  offer, disabled, onAccept, onCounter, onDecline,
}: {
  offer: BestOffer; disabled: boolean;
  onAccept: () => void; onCounter: () => void; onDecline: () => void;
}) {
  const list = offer.item_price ?? 0;
  const discount = list > 0 ? Math.round((1 - offer.offer_price / list) * 100) : null;
  return (
    <View style={styles.row}>
      <View style={styles.rowTop}>
        {offer.item_picture_url ? (
          <Image source={{ uri: offer.item_picture_url }} style={styles.thumb} contentFit="cover" />
        ) : (
          <View style={[styles.thumb, styles.thumbBlank]}><Text style={styles.thumbBlankText}>NO IMG</Text></View>
        )}
        <View style={{ flex: 1 }}>
          <Text style={styles.title2} numberOfLines={2}>{offer.item_title}</Text>
          <Text style={styles.buyer}>From <Text style={styles.buyerName}>{offer.buyer_user_id}</Text></Text>
          {offer.buyer_message ? <Text style={styles.buyerMsg} numberOfLines={3}>"{offer.buyer_message}"</Text> : null}
        </View>
      </View>

      <View style={styles.compareRow}>
        <CompareCell label="List">
          <Price value={offer.item_price ?? null} size="md" tone="muted" />
        </CompareCell>
        <CompareCell label="Offer">
          <Price value={offer.offer_price} size="md" />
        </CompareCell>
        <CompareCell label="Discount">
          <Text style={styles.compareValueText}>{discount != null ? `${discount}%` : '—'}</Text>
        </CompareCell>
      </View>

      <View style={styles.actions}>
        <GoldButton
          label="Accept"
          onPress={onAccept}
          disabled={disabled}
        />
        <TouchableOpacity style={[styles.btnCounter, disabled && { opacity: 0.5 }]} onPress={onCounter} disabled={disabled}>
          <Text style={styles.btnCounterText}>Counter</Text>
        </TouchableOpacity>
        <TouchableOpacity style={[styles.btnDecline, disabled && { opacity: 0.5 }]} onPress={onDecline} disabled={disabled}>
          <Text style={styles.btnDeclineText}>Decline</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

function CompareCell({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <View style={styles.compareCell}>
      <Text style={styles.compareLabel}>{label}</Text>
      <View style={{ marginTop: 2 }}>{children}</View>
    </View>
  );
}

/**
 * Shared primary gold button — adds medium haptic on press + a 120ms
 * scale(0.97) so the seller gets a tactile cue when launching an irreversible
 * eBay write. Lives in this file because offers is the most write-heavy
 * surface; lifted out if/when listing detail + quick-list share it.
 */
function GoldButton({
  label,
  onPress,
  disabled,
}: { label: string; onPress: () => void; disabled?: boolean }) {
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
    <Animated.View style={[styles.btnAcceptWrap, { transform: [{ scale }] }]}>
      <TouchableOpacity
        activeOpacity={0.85}
        style={[styles.btnAccept, disabled && { opacity: 0.5 }]}
        onPress={handlePress}
        disabled={disabled}
      >
        <Text style={styles.btnAcceptText}>{label}</Text>
      </TouchableOpacity>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.bg },
  center: { alignItems: 'center', justifyContent: 'center', flex: 1 },
  muted: { color: theme.textMuted, fontSize: 13 },
  bigDim: { color: theme.text, fontSize: 18, fontWeight: '700' },

  header: { paddingHorizontal: 18, paddingTop: 14, paddingBottom: 14, borderBottomColor: theme.border, borderBottomWidth: 1 },
  eyebrow: { color: theme.textDim, fontFamily: fonts.bodyBold, fontSize: 10, letterSpacing: 1.6 },
  title: { color: theme.text, fontFamily: fonts.display, fontSize: 36, letterSpacing: 0 },
  sub: { color: theme.textMuted, fontSize: 11, marginTop: 4 },

  emptyTitle: { color: theme.text, fontFamily: fonts.display, fontSize: 36, letterSpacing: 0 },
  emptyCaption: { color: theme.textMuted, fontFamily: fonts.body, fontSize: 12, marginTop: 8 },

  row: { paddingHorizontal: 18, paddingVertical: 14, borderBottomColor: theme.border, borderBottomWidth: 1 },
  rowTop: { flexDirection: 'row', gap: 12 },
  thumb: { width: 56, height: 56, borderRadius: radii.sm, backgroundColor: theme.surface, borderColor: theme.border, borderWidth: 1 },
  thumbBlank: { alignItems: 'center', justifyContent: 'center' },
  thumbBlankText: { color: theme.textDim, fontSize: 9, fontWeight: '800', letterSpacing: 0.8 },

  title2: { color: theme.text, fontSize: 14, fontWeight: '600', lineHeight: 18 },
  buyer: { color: theme.textDim, fontSize: 11, marginTop: 4 },
  buyerName: { color: theme.gold, fontWeight: '700' },
  buyerMsg: { color: theme.textMuted, fontSize: 12, marginTop: 6, fontStyle: 'italic', lineHeight: 16 },

  compareRow: { flexDirection: 'row', marginTop: 12, backgroundColor: theme.surface, borderRadius: radii.sm, padding: 10, gap: 12 },
  compareCell: { flex: 1 },
  compareLabel: { color: theme.textDim, fontSize: 10, fontWeight: '800', letterSpacing: 1.4, textTransform: 'uppercase' },
  compareValueText: { color: theme.text, fontSize: 16, fontWeight: '800', marginTop: 2 },

  actions: { flexDirection: 'row', gap: 8, marginTop: 12 },
  btnAcceptWrap: { flex: 1 },
  btnAccept: { backgroundColor: theme.gold, paddingVertical: 11, borderRadius: radii.sm, alignItems: 'center' },
  btnAcceptText: { color: '#0a0a0a', fontWeight: '800', fontSize: 12, letterSpacing: 0.6, textTransform: 'uppercase' },
  btnCounter: { flex: 1, backgroundColor: theme.surface, borderColor: theme.gold, borderWidth: 1, paddingVertical: 10, borderRadius: radii.sm, alignItems: 'center' },
  btnCounterText: { color: theme.gold, fontWeight: '800', fontSize: 12, letterSpacing: 0.6, textTransform: 'uppercase' },
  btnDecline: { flex: 1, backgroundColor: 'transparent', borderColor: 'rgba(224,123,111,0.4)', borderWidth: 1, paddingVertical: 10, borderRadius: radii.sm, alignItems: 'center' },
  btnDeclineText: { color: theme.danger, fontWeight: '700', fontSize: 12, letterSpacing: 0.6, textTransform: 'uppercase' },

  modalBackdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.75)', alignItems: 'center', justifyContent: 'center', padding: 18 },
  modalCard: { width: '100%', maxWidth: 380, backgroundColor: theme.surface, borderColor: theme.border, borderWidth: 1, borderRadius: radii.md, padding: 18 },
  modalEyebrow: { color: theme.gold, fontSize: 10, fontWeight: '800', letterSpacing: 1.5 },
  modalTitle: { color: theme.text, fontSize: 15, fontWeight: '600', marginTop: 6, lineHeight: 20 },
  modalCompareRow: { flexDirection: 'row', marginTop: 14, gap: 12, backgroundColor: theme.bg, borderRadius: radii.sm, padding: 10 },
  modalLabel: { color: theme.textDim, fontSize: 10, fontWeight: '800', letterSpacing: 1.5, textTransform: 'uppercase', marginTop: 14, marginBottom: 6 },

  priceRow: { flexDirection: 'row', alignItems: 'center', backgroundColor: theme.bg, borderColor: theme.border, borderWidth: 1, borderRadius: radii.sm, paddingHorizontal: 12 },
  priceCurrency: { color: theme.gold, fontSize: 20, fontWeight: '800', marginRight: 6 },
  priceInput: { flex: 1, color: theme.text, fontSize: 22, fontWeight: '700', paddingVertical: 10 },

  btnGold: { backgroundColor: theme.gold, paddingVertical: 12, borderRadius: radii.sm, alignItems: 'center', marginTop: 4 },
  btnGoldText: { color: '#0a0a0a', fontWeight: '800', fontSize: 13, textTransform: 'uppercase', letterSpacing: 0.6 },
  btnGhost: { backgroundColor: 'transparent', borderColor: theme.border, borderWidth: 1, paddingVertical: 12, borderRadius: radii.sm, alignItems: 'center' },
  btnGhostText: { color: theme.textMuted, fontWeight: '700', fontSize: 13, textTransform: 'uppercase', letterSpacing: 0.5 },
});
