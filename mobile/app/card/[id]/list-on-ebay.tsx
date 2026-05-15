/**
 * List-on-eBay pre-flight screen.
 *
 * Flow:
 *   1. Load the card + suggested title/price.
 *   2. Let the seller tweak: title, price, condition, quantity, duration,
 *      free-shipping toggle.
 *   3. On "List it": confirm (live listing!), upload front/back photos via
 *      eBay Picture Service, call AddFixedPriceItem, persist item_id back to
 *      the local DB.
 *   4. Success card with the eBay view URL.
 */
import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Linking,
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  TouchableOpacity,
  View,
  useWindowDimensions,
} from 'react-native';
import { Image } from 'expo-image';
import { SafeAreaView } from 'react-native-safe-area-context';

import { radii, theme } from '@/src/theme';
import { getCard, updateCard, type Card } from '@/src/db';
import { getEbayCredentials } from '@/src/settings';
import {
  CONDITION_OPTIONS,
  DURATIONS,
  EbayApiError,
  EbayAuthError,
  type ConditionLabel,
  type DurationValue,
  createListing,
  uploadImage,
} from '@/src/api/ebay';
import { cardToTitle, detectGrade } from '@/src/api/pricing';

function mapCardConditionToEbay(label: string | null | undefined): ConditionLabel {
  if (!label) return 'Near Mint';
  const t = label.toLowerCase();
  if (t.includes('near')) return 'Near Mint';
  if (t.includes('excellent')) return 'Excellent';
  if (t.includes('light')) return 'Light Play';
  if (t.includes('moderate') || t.includes('good')) return 'Good';
  if (t.includes('heavy')) return 'Heavy Play';
  if (t.includes('damage') || t.includes('poor')) return 'Poor';
  return 'Near Mint';
}

type Phase = 'review' | 'submitting' | 'success' | 'error';

export default function ListOnEbayScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { width } = useWindowDimensions();

  const [card, setCard] = useState<Card | null>(null);
  const [loading, setLoading] = useState(true);
  const [hasCredentials, setHasCredentials] = useState(false);

  // Form state — editable.
  const [title, setTitle] = useState('');
  const [priceStr, setPriceStr] = useState('');
  const [condition, setCondition] = useState<ConditionLabel>('Near Mint');
  const [quantity, setQuantity] = useState('1');
  const [duration, setDuration] = useState<DurationValue>('GTC');
  const [freeShipping, setFreeShipping] = useState(true);

  // Submit lifecycle.
  const [phase, setPhase] = useState<Phase>('review');
  const [progressMsg, setProgressMsg] = useState('');
  const [resultUrl, setResultUrl] = useState<string | null>(null);
  const [resultItemId, setResultItemId] = useState<string | null>(null);
  const [errorTitle, setErrorTitle] = useState('');
  const [errorDetail, setErrorDetail] = useState('');
  const [errorCode, setErrorCode] = useState<string | null>(null);

  // Avoid double-submits if the user double-taps the confirm dialog.
  const submitting = useRef(false);

  useEffect(() => {
    (async () => {
      if (!id) { setLoading(false); return; }
      const c = await getCard(String(id));
      setCard(c);
      if (c) {
        // Pre-fill title from card identity. Cap at 80 chars (eBay limit).
        const draft = cardToTitle({
          name: c.name,
          set_name: c.set_name,
          set_code: c.set_code,
          number: c.number,
          total: c.total,
          rarity: c.rarity,
          foil: c.foil,
          edition: c.edition,
          language: c.language,
          condition_hints: c.condition_hints,
          confidence: c.confidence ?? 'low',
        }).slice(0, 80);
        setTitle(draft);

        // Price: prefer user_price, else TCG market.
        const seed = c.user_price ?? c.tcg_market ?? null;
        setPriceStr(seed != null ? seed.toFixed(2) : '');

        setCondition(mapCardConditionToEbay(c.condition));
      }
      const creds = await getEbayCredentials();
      setHasCredentials(!!creds);
      setLoading(false);
    })();
  }, [id]);

  const grade = useMemo(() => (card ? detectGrade(cardToTitle({
    name: card.name, set_name: card.set_name, set_code: card.set_code, number: card.number,
    total: card.total, rarity: card.rarity, foil: card.foil, edition: card.edition,
    language: card.language, condition_hints: card.condition_hints,
    confidence: card.confidence ?? 'low',
  }) + ' ' + (card.notes ?? '')) : null), [card]);

  const images = useMemo(() => [card?.front_image, card?.back_image].filter(Boolean) as string[], [card]);

  function confirmAndSubmit() {
    if (submitting.current) return;
    if (!card) return;
    if (!hasCredentials) {
      Alert.alert(
        'eBay credentials missing',
        'Add your eBay App ID, Cert ID, and refresh token in Settings before listing.',
      );
      return;
    }
    const price = parseFloat(priceStr);
    if (!Number.isFinite(price) || price <= 0) {
      Alert.alert('Price required', 'Enter a positive listing price.');
      return;
    }
    const qty = parseInt(quantity, 10);
    if (!Number.isFinite(qty) || qty < 1) {
      Alert.alert('Quantity', 'Quantity must be 1 or more.');
      return;
    }
    if (!title.trim()) {
      Alert.alert('Title required', 'eBay needs a listing title.');
      return;
    }

    Alert.alert(
      'Create live eBay listing?',
      `This will create a LIVE eBay listing for "${title.slice(0, 60)}${title.length > 60 ? '…' : ''}" at $${price.toFixed(2)}. Continue?`,
      [
        { text: 'Cancel', style: 'cancel' },
        { text: 'List it', style: 'destructive', onPress: () => submit(price, qty) },
      ],
    );
  }

  async function submit(price: number, qty: number) {
    if (!card) return;
    submitting.current = true;
    setPhase('submitting');
    setProgressMsg('Authenticating with eBay…');

    try {
      // 1. Upload images via eBay Picture Service.
      const uploaded: string[] = [];
      for (let i = 0; i < images.length; i++) {
        setProgressMsg(`Uploading image ${i + 1} of ${images.length}…`);
        try {
          const r = await uploadImage(images[i]);
          uploaded.push(r.full_url);
        } catch (err: any) {
          // If picture upload itself fails (e.g. transient eBay issue) we
          // continue — the listing can be created without that image.
          console.warn('uploadImage failed', err?.message ?? err);
        }
      }

      // 2. Create the listing.
      setProgressMsg('Creating listing on eBay…');
      const result = await createListing(card, {
        title: title.trim(),
        price,
        quantity: qty,
        condition_label: condition,
        duration,
        free_combined_shipping: freeShipping,
        picture_urls: uploaded,
      });

      // 3. Persist back to local DB.
      await updateCard(card.id, {
        listing_id: result.item_id,
        listing_url: result.view_url,
        listing_status: 'listed',
        user_price: price,
        condition,
      });

      setResultItemId(result.item_id);
      setResultUrl(result.view_url);
      setPhase('success');
    } catch (err: any) {
      if (err instanceof EbayAuthError) {
        setErrorTitle('Couldn\'t authenticate with eBay');
        setErrorDetail(
          'Check your refresh token, App ID, and Cert ID in Settings. ' +
          (err.body ? `\n\nServer said: ${err.body}` : ''),
        );
        setErrorCode(err.status ? String(err.status) : null);
      } else if (err instanceof EbayApiError) {
        setErrorTitle(err.message || 'eBay rejected the listing');
        setErrorDetail(err.longMessage || '');
        setErrorCode(err.code ?? null);
      } else {
        setErrorTitle('Listing failed');
        setErrorDetail(err?.message ?? String(err));
        setErrorCode(null);
      }
      setPhase('error');
    } finally {
      submitting.current = false;
    }
  }

  if (loading) {
    return (
      <SafeAreaView style={[styles.root, styles.center]}>
        <ActivityIndicator color={theme.gold} />
      </SafeAreaView>
    );
  }
  if (!card) {
    return (
      <SafeAreaView style={[styles.root, styles.center]}>
        <Text style={styles.muted}>Card not found.</Text>
      </SafeAreaView>
    );
  }

  if (phase === 'submitting') {
    return (
      <SafeAreaView style={[styles.root, styles.center]}>
        <ActivityIndicator color={theme.gold} size="large" />
        <Text style={[styles.muted, { marginTop: 18, fontSize: 14 }]}>{progressMsg || 'Working…'}</Text>
        <Text style={[styles.muted, { marginTop: 6, fontSize: 11 }]}>This usually takes 10–30 seconds.</Text>
      </SafeAreaView>
    );
  }

  if (phase === 'success' && resultUrl) {
    return (
      <SafeAreaView style={styles.root}>
        <ScrollView contentContainerStyle={{ padding: 18, paddingBottom: 40 }}>
          <View style={styles.successCard}>
            <Text style={styles.successEyebrow}>LIVE ON eBAY</Text>
            <Text style={styles.successTitle}>{title}</Text>
            <Text style={styles.successPrice}>${parseFloat(priceStr).toFixed(2)}</Text>
            <Text style={styles.itemId}>Item #{resultItemId}</Text>
            <TouchableOpacity style={styles.btnGold} onPress={() => Linking.openURL(resultUrl)}>
              <Text style={styles.btnGoldText}>View on eBay</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.btnGhost} onPress={() => router.back()}>
              <Text style={styles.btnGhostText}>Done</Text>
            </TouchableOpacity>
          </View>
        </ScrollView>
      </SafeAreaView>
    );
  }

  if (phase === 'error') {
    return (
      <SafeAreaView style={styles.root}>
        <ScrollView contentContainerStyle={{ padding: 18, paddingBottom: 40 }}>
          <View style={styles.errorCard}>
            <Text style={styles.errorEyebrow}>LISTING FAILED</Text>
            <Text style={styles.errorTitleText}>{errorTitle}</Text>
            {errorCode ? <Text style={styles.errorCode}>eBay error code {errorCode}</Text> : null}
            {errorDetail ? <Text style={styles.errorDetail}>{errorDetail}</Text> : null}
            <View style={{ flexDirection: 'row', gap: 8, marginTop: 18 }}>
              <TouchableOpacity style={[styles.btnGold, { flex: 1 }]} onPress={() => setPhase('review')}>
                <Text style={styles.btnGoldText}>Try again</Text>
              </TouchableOpacity>
              <TouchableOpacity style={[styles.btnGhost, { flex: 1 }]} onPress={() => router.back()}>
                <Text style={styles.btnGhostText}>Cancel</Text>
              </TouchableOpacity>
            </View>
          </View>
        </ScrollView>
      </SafeAreaView>
    );
  }

  // -- review phase --
  const imageWidth = Math.max(120, (width - 18 * 2 - 12) / 2);

  return (
    <SafeAreaView style={styles.root} edges={['bottom']}>
      <ScrollView contentContainerStyle={{ paddingBottom: 30 }}>
        {/* Photos swipeable */}
        <View style={styles.photoStrip}>
          {images.length === 0 ? (
            <View style={[styles.photoPlaceholder, { width: '100%' }]}>
              <Text style={styles.muted}>No photos on this card.</Text>
            </View>
          ) : (
            <ScrollView horizontal pagingEnabled showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 12, paddingHorizontal: 18 }}>
              {images.map((uri) => (
                <Image key={uri} source={{ uri }} style={[styles.photo, { width: imageWidth, height: imageWidth * 1.4 }]} contentFit="cover" />
              ))}
            </ScrollView>
          )}
        </View>

        {grade ? (
          <View style={styles.gradePill}>
            <Text style={styles.gradePillText}>{grade.toUpperCase().replace('PSA', 'PSA ').replace('BGS', 'BGS ').replace('CGC', 'CGC ').replace('SGC', 'SGC ')}</Text>
          </View>
        ) : null}

        {/* Title */}
        <View style={styles.section}>
          <Text style={styles.label}>Title (eBay max 80)</Text>
          <TextInput
            value={title}
            onChangeText={(t) => setTitle(t.slice(0, 80))}
            style={[styles.input, { minHeight: 60 }]}
            multiline
            placeholder="2018 Pokemon Hidden Fates Charizard GX #SV49 Holo"
            placeholderTextColor={theme.textDim}
          />
          <Text style={styles.charCount}>{title.length}/80</Text>
        </View>

        {/* Price */}
        <View style={styles.section}>
          <Text style={styles.label}>List price</Text>
          <View style={styles.priceRow}>
            <Text style={styles.priceCurrency}>$</Text>
            <TextInput
              value={priceStr}
              onChangeText={setPriceStr}
              keyboardType="decimal-pad"
              style={styles.priceInput}
              placeholder="0.00"
              placeholderTextColor={theme.textDim}
            />
          </View>
          {card.tcg_market != null ? <Text style={styles.help}>TCG market ${card.tcg_market.toFixed(2)} · TCG low ${card.tcg_low?.toFixed(2) ?? '—'}</Text> : null}
        </View>

        {/* Condition */}
        <View style={styles.section}>
          <Text style={styles.label}>Condition</Text>
          <View style={styles.condGrid}>
            {CONDITION_OPTIONS.map((c) => (
              <Pressable
                key={c.label}
                onPress={() => setCondition(c.label)}
                style={[styles.condChip, condition === c.label && styles.condChipActive]}
              >
                <Text style={[styles.condChipText, condition === c.label && styles.condChipTextActive]}>{c.label}</Text>
              </Pressable>
            ))}
          </View>
        </View>

        {/* Quantity */}
        <View style={styles.section}>
          <Text style={styles.label}>Quantity</Text>
          <View style={styles.qtyRow}>
            <TouchableOpacity style={styles.qtyBtn} onPress={() => setQuantity(String(Math.max(1, parseInt(quantity || '1', 10) - 1)))}>
              <Text style={styles.qtyBtnText}>–</Text>
            </TouchableOpacity>
            <TextInput
              value={quantity}
              onChangeText={(t) => setQuantity(t.replace(/[^0-9]/g, '') || '1')}
              keyboardType="number-pad"
              style={styles.qtyInput}
            />
            <TouchableOpacity style={styles.qtyBtn} onPress={() => setQuantity(String((parseInt(quantity || '1', 10) || 0) + 1))}>
              <Text style={styles.qtyBtnText}>+</Text>
            </TouchableOpacity>
          </View>
        </View>

        {/* Duration */}
        <View style={styles.section}>
          <Text style={styles.label}>Duration</Text>
          <View style={styles.condGrid}>
            {DURATIONS.map((d) => (
              <Pressable
                key={d.value}
                onPress={() => setDuration(d.value)}
                style={[styles.condChip, duration === d.value && styles.condChipActive]}
              >
                <Text style={[styles.condChipText, duration === d.value && styles.condChipTextActive]}>{d.label}</Text>
              </Pressable>
            ))}
          </View>
        </View>

        {/* Shipping */}
        <View style={[styles.section, styles.shipRow]}>
          <View style={{ flex: 1, paddingRight: 12 }}>
            <Text style={styles.label}>Free combined shipping</Text>
            <Text style={styles.help}>Buyer pays $0 on this item; you eat USPS Ground. Standard store policy.</Text>
          </View>
          <Switch
            value={freeShipping}
            onValueChange={setFreeShipping}
            trackColor={{ false: theme.surface3, true: theme.gold }}
            thumbColor={freeShipping ? '#0a0a0a' : '#eee'}
          />
        </View>

        {/* Credentials warning */}
        {!hasCredentials ? (
          <View style={styles.warnBox}>
            <Text style={styles.warnText}>
              eBay credentials not configured. Add your App ID, Cert ID, and refresh token in Settings.
            </Text>
          </View>
        ) : null}

        {/* Submit */}
        <View style={styles.section}>
          <TouchableOpacity
            style={[styles.btnGold, !hasCredentials && { opacity: 0.5 }]}
            onPress={confirmAndSubmit}
            disabled={!hasCredentials}
          >
            <Text style={styles.btnGoldText}>List it on eBay</Text>
          </TouchableOpacity>
          <TouchableOpacity style={styles.btnGhost} onPress={() => router.back()}>
            <Text style={styles.btnGhostText}>Cancel</Text>
          </TouchableOpacity>
        </View>

        <Text style={styles.fineprint}>
          Tapping "List it" creates a LIVE eBay listing in your seller account. You'll get a confirmation prompt first.
        </Text>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.bg },
  center: { alignItems: 'center', justifyContent: 'center' },
  muted: { color: theme.textMuted, fontSize: 14 },

  photoStrip: { paddingVertical: 18 },
  photo: { borderRadius: radii.md, backgroundColor: theme.surface, borderColor: theme.border, borderWidth: 1 },
  photoPlaceholder: { padding: 18, alignItems: 'center', justifyContent: 'center', borderRadius: radii.md, backgroundColor: theme.surface, borderColor: theme.border, borderWidth: 1, marginHorizontal: 18, height: 180 },

  gradePill: { alignSelf: 'flex-start', marginHorizontal: 18, paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999, backgroundColor: 'rgba(212,175,55,0.15)', borderColor: theme.gold, borderWidth: 1, marginBottom: 8 },
  gradePillText: { color: theme.gold, fontSize: 11, fontWeight: '800', letterSpacing: 1 },

  section: { paddingHorizontal: 18, marginTop: 14 },
  label: { color: theme.textDim, fontSize: 10, fontWeight: '800', letterSpacing: 1.5, textTransform: 'uppercase', marginBottom: 6 },
  input: { backgroundColor: theme.surface, color: theme.text, borderColor: theme.border, borderWidth: 1, borderRadius: radii.sm, paddingHorizontal: 12, paddingVertical: 10, fontSize: 14 },
  charCount: { color: theme.textDim, fontSize: 11, marginTop: 4, textAlign: 'right' },

  priceRow: { flexDirection: 'row', alignItems: 'center', backgroundColor: theme.surface, borderColor: theme.border, borderWidth: 1, borderRadius: radii.sm, paddingHorizontal: 12 },
  priceCurrency: { color: theme.gold, fontSize: 20, fontWeight: '800', marginRight: 6 },
  priceInput: { flex: 1, color: theme.text, fontSize: 22, fontWeight: '700', paddingVertical: 10 },
  help: { color: theme.textDim, fontSize: 11, marginTop: 6, lineHeight: 15 },

  condGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  condChip: { paddingHorizontal: 10, paddingVertical: 7, borderRadius: 999, borderColor: theme.border, borderWidth: 1, backgroundColor: theme.surface2 },
  condChipActive: { borderColor: theme.gold, backgroundColor: 'rgba(212,175,55,0.15)' },
  condChipText: { color: theme.textMuted, fontSize: 12, fontWeight: '700' },
  condChipTextActive: { color: theme.gold },

  qtyRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  qtyBtn: { width: 44, height: 44, borderRadius: radii.sm, backgroundColor: theme.surface, borderColor: theme.border, borderWidth: 1, alignItems: 'center', justifyContent: 'center' },
  qtyBtnText: { color: theme.gold, fontSize: 22, fontWeight: '800' },
  qtyInput: { flex: 1, height: 44, backgroundColor: theme.surface, color: theme.text, borderColor: theme.border, borderWidth: 1, borderRadius: radii.sm, paddingHorizontal: 12, fontSize: 18, fontWeight: '700', textAlign: 'center' },

  shipRow: { flexDirection: 'row', alignItems: 'center' },

  warnBox: { marginHorizontal: 18, marginTop: 14, padding: 12, backgroundColor: 'rgba(224,123,111,0.07)', borderColor: 'rgba(224,123,111,0.4)', borderWidth: 1, borderRadius: radii.sm },
  warnText: { color: theme.danger, fontSize: 13 },

  btnGold: { backgroundColor: theme.gold, paddingVertical: 14, borderRadius: radii.sm, alignItems: 'center', marginTop: 4 },
  btnGoldText: { color: '#0a0a0a', fontWeight: '800', fontSize: 14, textTransform: 'uppercase', letterSpacing: 0.6 },
  btnGhost: { backgroundColor: 'transparent', borderColor: theme.border, borderWidth: 1, paddingVertical: 12, borderRadius: radii.sm, alignItems: 'center', marginTop: 8 },
  btnGhostText: { color: theme.textMuted, fontWeight: '700', fontSize: 13, textTransform: 'uppercase', letterSpacing: 0.5 },

  fineprint: { color: theme.textDim, fontSize: 11, paddingHorizontal: 18, marginTop: 16, lineHeight: 15, textAlign: 'center' },

  // success
  successCard: { padding: 18, borderRadius: radii.md, backgroundColor: theme.surface, borderColor: theme.gold, borderWidth: 1 },
  successEyebrow: { color: theme.gold, fontSize: 10, fontWeight: '800', letterSpacing: 2 },
  successTitle: { color: theme.text, fontSize: 18, fontWeight: '700', marginTop: 8 },
  successPrice: { color: theme.goldBright, fontSize: 32, fontWeight: '800', marginTop: 6, letterSpacing: -0.5 },
  itemId: { color: theme.textDim, fontSize: 12, marginTop: 4, marginBottom: 14 },

  // error
  errorCard: { padding: 18, borderRadius: radii.md, backgroundColor: theme.surface, borderColor: 'rgba(224,123,111,0.4)', borderWidth: 1 },
  errorEyebrow: { color: theme.danger, fontSize: 10, fontWeight: '800', letterSpacing: 2 },
  errorTitleText: { color: theme.text, fontSize: 17, fontWeight: '700', marginTop: 8 },
  errorCode: { color: theme.danger, fontSize: 12, marginTop: 4, fontFamily: 'Menlo' },
  errorDetail: { color: theme.textMuted, fontSize: 13, marginTop: 12, lineHeight: 18 },
});
