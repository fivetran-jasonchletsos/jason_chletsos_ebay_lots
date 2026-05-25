/**
 * Quick-list — generic (non-card) snap-to-list flow for store inventory.
 *
 *   1. Snap up to 12 photos.
 *   2. Title, price, condition, category, quantity, duration, Best Offer,
 *      free-shipping, optional description.
 *   3. Confirm prompt -> downscale + upload each photo via
 *      UploadSiteHostedPictures -> AddFixedPriceItem via createQuickListing.
 *   4. Success card with the live item URL.
 *
 * For the card-specific flow (with Claude vision identification + TCG
 * pricing), see /scan -> /card/[id]/list-on-ebay.
 */
import { CameraView, useCameraPermissions } from 'expo-camera';
import * as ImageManipulator from 'expo-image-manipulator';
import * as Haptics from 'expo-haptics';
import { Image } from 'expo-image';
import { router } from 'expo-router';
import { useRef, useState } from 'react';
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
import { SafeAreaView } from 'react-native-safe-area-context';

import { radii, theme } from '@/src/theme';
import { EbayApiError, EbayAuthError, uploadImage } from '@/src/api/ebay';
import {
  createQuickListing,
  GENERIC_CONDITIONS,
  QUICK_LIST_CATEGORIES,
  type GenericConditionLabel,
} from '@/src/api/listings';
import { getEbayCredentials } from '@/src/settings';

const MAX_PHOTOS = 12;
const CASSINI_PHOTO_GATE = 8;
const TARGET_LONG_EDGE_PX = 2400;

const DURATIONS: { label: string; value: 'Days_7' | 'Days_10' | 'Days_30' | 'GTC' }[] = [
  { label: '7 days',  value: 'Days_7'  },
  { label: '10 days', value: 'Days_10' },
  { label: '30 days', value: 'Days_30' },
  { label: 'GTC',     value: 'GTC'     },
];

type Phase = 'capture' | 'review' | 'submitting' | 'success' | 'error';

export default function QuickListScreen() {
  const [permission, requestPermission] = useCameraPermissions();
  const cameraRef = useRef<CameraView | null>(null);
  const { width } = useWindowDimensions();

  const [phase, setPhase] = useState<Phase>('capture');
  const [photos, setPhotos] = useState<string[]>([]);
  const [busyShutter, setBusyShutter] = useState(false);

  // Review-phase form.
  const [title, setTitle] = useState('');
  const [priceStr, setPriceStr] = useState('');
  const [quantity, setQuantity] = useState('1');
  const [condition, setCondition] = useState<GenericConditionLabel>('Used — Very Good');
  const [categoryId, setCategoryId] = useState(QUICK_LIST_CATEGORIES[0].id);
  const [duration, setDuration] = useState<typeof DURATIONS[number]['value']>('GTC');
  const [bestOffer, setBestOffer] = useState(true);
  const [freeShipping, setFreeShipping] = useState(true);
  const [description, setDescription] = useState('');

  const [progressMsg, setProgressMsg] = useState('');
  const [resultUrl, setResultUrl] = useState<string | null>(null);
  const [resultItemId, setResultItemId] = useState<string | null>(null);
  const [errorTitle, setErrorTitle] = useState('');
  const [errorDetail, setErrorDetail] = useState('');
  const submitting = useRef(false);

  if (!permission) {
    return <SafeAreaView style={[styles.root, styles.center]}><ActivityIndicator color={theme.gold} /></SafeAreaView>;
  }
  if (!permission.granted) {
    return (
      <SafeAreaView style={[styles.root, styles.center]}>
        <Text style={styles.bigDim}>Camera access needed</Text>
        <TouchableOpacity style={styles.btnGold} onPress={requestPermission}>
          <Text style={styles.btnGoldText}>Allow camera</Text>
        </TouchableOpacity>
      </SafeAreaView>
    );
  }

  async function shoot() {
    if (!cameraRef.current || busyShutter) return;
    if (photos.length >= MAX_PHOTOS) return;
    setBusyShutter(true);
    try {
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
      const photo = await cameraRef.current.takePictureAsync({ quality: 1, skipProcessing: false });
      if (!photo?.uri) throw new Error('No photo');
      setPhotos((prev) => [...prev, photo.uri]);
    } catch (e: any) {
      Alert.alert('Capture failed', e?.message ?? String(e));
    } finally {
      setBusyShutter(false);
    }
  }

  function removeAt(i: number) { setPhotos((prev) => prev.filter((_, idx) => idx !== i)); }
  function promote(i: number) {
    setPhotos((prev) => {
      if (i === 0) return prev;
      const copy = prev.slice();
      const [it] = copy.splice(i, 1);
      copy.unshift(it);
      return copy;
    });
  }

  function goReview() {
    if (photos.length === 0) {
      Alert.alert('No photos', 'Shoot at least one photo to continue.');
      return;
    }
    setPhase('review');
  }

  async function confirmAndSubmit() {
    if (submitting.current) return;
    const creds = await getEbayCredentials();
    if (!creds) {
      Alert.alert('eBay not connected', 'Add your App ID, Cert ID, and refresh token in Settings.');
      return;
    }
    const price = parseFloat(priceStr);
    if (!Number.isFinite(price) || price <= 0) { Alert.alert('Price required', 'Enter a positive price.'); return; }
    const qty = parseInt(quantity, 10);
    if (!Number.isFinite(qty) || qty < 1) { Alert.alert('Quantity', 'Quantity must be 1+'); return; }
    if (!title.trim()) { Alert.alert('Title required', 'eBay needs a title.'); return; }

    Alert.alert(
      'Create LIVE eBay listing?',
      `Publish "${title.slice(0, 60)}${title.length > 60 ? '…' : ''}" at $${price.toFixed(2)} (qty ${qty})?`,
      [
        { text: 'Cancel', style: 'cancel' },
        { text: 'List it', style: 'destructive', onPress: () => submit(price, qty) },
      ],
    );
  }

  async function submit(price: number, qty: number) {
    submitting.current = true;
    setPhase('submitting');
    setProgressMsg('Preparing photos…');
    try {
      const uploaded: string[] = [];
      for (let i = 0; i < photos.length; i++) {
        setProgressMsg(`Optimizing photo ${i + 1} of ${photos.length}…`);
        const resized = await ImageManipulator.manipulateAsync(
          photos[i],
          [{ resize: { width: TARGET_LONG_EDGE_PX } }],
          { compress: 0.85, format: ImageManipulator.SaveFormat.JPEG },
        );
        setProgressMsg(`Uploading photo ${i + 1} of ${photos.length}…`);
        const r = await uploadImage(resized.uri);
        uploaded.push(r.full_url);
      }
      setProgressMsg('Publishing to eBay…');
      const desc = description.trim() || buildAutoDescription(title, condition);
      const result = await createQuickListing({
        title: title.trim(),
        description: desc,
        price,
        quantity: qty,
        condition_label: condition,
        category_id: categoryId,
        duration,
        free_combined_shipping: freeShipping,
        picture_urls: uploaded,
        best_offer_enabled: bestOffer,
      });
      setResultItemId(result.item_id);
      setResultUrl(result.view_url);
      setPhase('success');
    } catch (e: any) {
      if (e instanceof EbayAuthError) {
        setErrorTitle('Couldn\'t authenticate with eBay');
        setErrorDetail(e.body || 'Check Settings for App ID / Cert ID / refresh token.');
      } else if (e instanceof EbayApiError) {
        setErrorTitle(e.message || 'eBay rejected the listing');
        setErrorDetail(e.longMessage || '');
      } else {
        setErrorTitle('Listing failed');
        setErrorDetail(e?.message ?? String(e));
      }
      setPhase('error');
    } finally {
      submitting.current = false;
    }
  }

  if (phase === 'submitting') {
    return (
      <SafeAreaView style={[styles.root, styles.center]}>
        <ActivityIndicator color={theme.gold} size="large" />
        <Text style={[styles.muted, { marginTop: 18, fontSize: 14 }]}>{progressMsg}</Text>
      </SafeAreaView>
    );
  }

  if (phase === 'success' && resultUrl) {
    return (
      <SafeAreaView style={styles.root}>
        <ScrollView contentContainerStyle={{ padding: 18 }}>
          <View style={styles.successCard}>
            <Text style={styles.successEyebrow}>LIVE ON eBAY</Text>
            <Text style={styles.successTitle}>{title}</Text>
            <Text style={styles.successPrice}>${parseFloat(priceStr).toFixed(2)}</Text>
            <Text style={styles.itemId}>Item #{resultItemId}</Text>
            <TouchableOpacity style={styles.btnGold} onPress={() => Linking.openURL(resultUrl)}>
              <Text style={styles.btnGoldText}>View on eBay</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.btnGhost} onPress={() => router.replace('/(tabs)/listings')}>
              <Text style={styles.btnGhostText}>Back to listings</Text>
            </TouchableOpacity>
          </View>
        </ScrollView>
      </SafeAreaView>
    );
  }

  if (phase === 'error') {
    return (
      <SafeAreaView style={styles.root}>
        <ScrollView contentContainerStyle={{ padding: 18 }}>
          <View style={styles.errorCard}>
            <Text style={styles.errorEyebrow}>LISTING FAILED</Text>
            <Text style={styles.errorTitleText}>{errorTitle}</Text>
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

  if (phase === 'review') {
    const photoW = Math.min(width - 36, 380);
    return (
      <SafeAreaView style={styles.root} edges={['bottom']}>
        <ScrollView contentContainerStyle={{ paddingBottom: 40 }}>
          {/* Photos preview */}
          <ScrollView horizontal pagingEnabled showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 12, paddingHorizontal: 18, paddingVertical: 18 }}>
            {photos.map((u, i) => (
              <Image key={`${u}-${i}`} source={{ uri: u }} style={[styles.photo, { width: photoW, height: photoW }]} contentFit="cover" />
            ))}
          </ScrollView>

          <View style={styles.section}>
            <Text style={styles.label}>Title (eBay max 80)</Text>
            <TextInput
              value={title}
              onChangeText={(t) => setTitle(t.slice(0, 80))}
              style={[styles.input, { minHeight: 60 }]}
              multiline
              placeholder="2018 Pokemon Hidden Fates Charizard GX Sealed Booster Box"
              placeholderTextColor={theme.textDim}
            />
            <Text style={styles.charCount}>{title.length}/80</Text>
          </View>

          <View style={styles.section}>
            <Text style={styles.label}>Price</Text>
            <View style={styles.priceRow}>
              <Text style={styles.priceCurrency}>$</Text>
              <TextInput value={priceStr} onChangeText={setPriceStr} keyboardType="decimal-pad" style={styles.priceInput} placeholder="0.00" placeholderTextColor={theme.textDim} />
            </View>
          </View>

          <View style={styles.section}>
            <Text style={styles.label}>Quantity</Text>
            <View style={styles.qtyRow}>
              <TouchableOpacity style={styles.qtyBtn} onPress={() => setQuantity(String(Math.max(1, parseInt(quantity || '1', 10) - 1)))}>
                <Text style={styles.qtyBtnText}>–</Text>
              </TouchableOpacity>
              <TextInput value={quantity} onChangeText={(t) => setQuantity(t.replace(/[^0-9]/g, '') || '1')} keyboardType="number-pad" style={styles.qtyInput} />
              <TouchableOpacity style={styles.qtyBtn} onPress={() => setQuantity(String((parseInt(quantity || '1', 10) || 0) + 1))}>
                <Text style={styles.qtyBtnText}>+</Text>
              </TouchableOpacity>
            </View>
          </View>

          <View style={styles.section}>
            <Text style={styles.label}>Condition</Text>
            <View style={styles.chipGrid}>
              {GENERIC_CONDITIONS.map((c) => (
                <Pressable key={c.label} onPress={() => setCondition(c.label)} style={[styles.chip, condition === c.label && styles.chipActive]}>
                  <Text style={[styles.chipText, condition === c.label && styles.chipTextActive]}>{c.label}</Text>
                </Pressable>
              ))}
            </View>
          </View>

          <View style={styles.section}>
            <Text style={styles.label}>Category</Text>
            <View style={styles.chipGrid}>
              {QUICK_LIST_CATEGORIES.map((c) => (
                <Pressable key={c.id + c.name} onPress={() => setCategoryId(c.id)} style={[styles.chip, categoryId === c.id && styles.chipActive]}>
                  <Text style={[styles.chipText, categoryId === c.id && styles.chipTextActive]}>{c.name}</Text>
                </Pressable>
              ))}
            </View>
          </View>

          <View style={styles.section}>
            <Text style={styles.label}>Duration</Text>
            <View style={styles.chipGrid}>
              {DURATIONS.map((d) => (
                <Pressable key={d.value} onPress={() => setDuration(d.value)} style={[styles.chip, duration === d.value && styles.chipActive]}>
                  <Text style={[styles.chipText, duration === d.value && styles.chipTextActive]}>{d.label}</Text>
                </Pressable>
              ))}
            </View>
          </View>

          <View style={[styles.section, styles.toggleRow]}>
            <View style={{ flex: 1, paddingRight: 12 }}>
              <Text style={styles.label}>Accept Best Offers</Text>
              <Text style={styles.help}>Buyers can negotiate. Manage from the Offers tab.</Text>
            </View>
            <Switch value={bestOffer} onValueChange={setBestOffer} trackColor={{ false: theme.surface3, true: theme.gold }} thumbColor={bestOffer ? '#0a0a0a' : '#eee'} />
          </View>

          <View style={[styles.section, styles.toggleRow]}>
            <View style={{ flex: 1, paddingRight: 12 }}>
              <Text style={styles.label}>Free shipping</Text>
              <Text style={styles.help}>Buyer pays $0; you pay USPS Ground.</Text>
            </View>
            <Switch value={freeShipping} onValueChange={setFreeShipping} trackColor={{ false: theme.surface3, true: theme.gold }} thumbColor={freeShipping ? '#0a0a0a' : '#eee'} />
          </View>

          <View style={styles.section}>
            <Text style={styles.label}>Description (optional)</Text>
            <TextInput
              value={description}
              onChangeText={setDescription}
              style={[styles.input, { minHeight: 100 }]}
              multiline
              placeholder="Auto-generated from title + condition if left blank."
              placeholderTextColor={theme.textDim}
            />
          </View>

          <View style={styles.section}>
            <TouchableOpacity style={styles.btnGold} onPress={confirmAndSubmit}>
              <Text style={styles.btnGoldText}>List it on eBay</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.btnGhost} onPress={() => setPhase('capture')}>
              <Text style={styles.btnGhostText}>Back to photos</Text>
            </TouchableOpacity>
          </View>
        </ScrollView>
      </SafeAreaView>
    );
  }

  // -- capture phase --
  const cameraSize = Math.min(width, 480);
  const thumbW = (width - 18 * 2 - 8 * 3) / 4;
  const photosLow = photos.length > 0 && photos.length < CASSINI_PHOTO_GATE;

  return (
    <SafeAreaView style={styles.root} edges={['top']}>
      <View style={styles.header}>
        <Text style={styles.eyebrow}>QUICK LIST</Text>
        <Text style={styles.headerTitle}>{photos.length}/{MAX_PHOTOS} photos</Text>
        <Text style={[styles.headerSub, photosLow && { color: theme.warning }]}>
          {photos.length === 0
            ? 'Shoot at least one photo. Cassini wants 8+ at >=1600px.'
            : photosLow
              ? `Below Cassini gate. Aim for ${CASSINI_PHOTO_GATE}+.`
              : 'Above Cassini gate — good to go.'}
        </Text>
      </View>

      <View style={[styles.cameraFrame, { height: cameraSize }]}>
        <CameraView ref={cameraRef as any} style={{ flex: 1 }} facing="back" autofocus="on" />
        <TouchableOpacity style={[styles.shutter, busyShutter && { opacity: 0.5 }]} onPress={shoot} disabled={busyShutter || photos.length >= MAX_PHOTOS} />
      </View>

      {photos.length > 0 ? (
        <View style={styles.tray}>
          <Text style={styles.trayLabel}>Tap = make cover. Long-press = remove.</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8, paddingHorizontal: 18 }}>
            {photos.map((uri, i) => (
              <Pressable key={`${uri}-${i}`} onPress={() => promote(i)} onLongPress={() => removeAt(i)}
                style={({ pressed }) => [styles.thumbWrap, { width: thumbW, height: thumbW }, pressed && { opacity: 0.7 }]}>
                <Image source={{ uri }} style={styles.thumb} contentFit="cover" />
                {i === 0 ? <View style={styles.coverBadge}><Text style={styles.coverBadgeText}>COVER</Text></View> : null}
              </Pressable>
            ))}
          </ScrollView>
        </View>
      ) : null}

      <View style={styles.footer}>
        <TouchableOpacity style={[styles.btnGold, photos.length === 0 && { opacity: 0.5 }]} onPress={goReview} disabled={photos.length === 0}>
          <Text style={styles.btnGoldText}>Next: details</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.btnGhost} onPress={() => router.back()}>
          <Text style={styles.btnGhostText}>Cancel</Text>
        </TouchableOpacity>
      </View>
    </SafeAreaView>
  );
}

function buildAutoDescription(title: string, condition: string): string {
  return `<h2>${escapeHtml(title)}</h2>
<p>Condition: ${escapeHtml(condition)}</p>
<p>Ships fast, packaged with care. Combined shipping available on multiple purchases.</p>
<p>30-day returns accepted.</p>`;
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.bg },
  center: { alignItems: 'center', justifyContent: 'center', flex: 1 },
  muted: { color: theme.textMuted, fontSize: 13 },
  bigDim: { color: theme.text, fontSize: 18, fontWeight: '700' },

  header: { paddingHorizontal: 18, paddingVertical: 12, borderBottomColor: theme.border, borderBottomWidth: 1 },
  eyebrow: { color: theme.gold, fontSize: 10, fontWeight: '800', letterSpacing: 1.5 },
  headerTitle: { color: theme.text, fontSize: 22, fontWeight: '800', marginTop: 2 },
  headerSub: { color: theme.textMuted, fontSize: 11, marginTop: 4, lineHeight: 16 },

  cameraFrame: { backgroundColor: '#000', position: 'relative' },
  shutter: { position: 'absolute', bottom: 16, left: '50%', marginLeft: -34, width: 68, height: 68, borderRadius: 34, backgroundColor: theme.gold, borderColor: '#0a0a0a', borderWidth: 4 },

  tray: { paddingVertical: 12, borderBottomColor: theme.border, borderBottomWidth: 1 },
  trayLabel: { color: theme.textDim, fontSize: 10, paddingHorizontal: 18, marginBottom: 8, letterSpacing: 0.5 },
  thumbWrap: { borderRadius: radii.sm, backgroundColor: theme.surface, borderColor: theme.border, borderWidth: 1, overflow: 'hidden' },
  thumb: { width: '100%', height: '100%' },
  coverBadge: { position: 'absolute', top: 4, left: 4, paddingHorizontal: 6, paddingVertical: 2, backgroundColor: theme.gold, borderRadius: 4 },
  coverBadgeText: { color: '#0a0a0a', fontSize: 9, fontWeight: '800', letterSpacing: 0.8 },

  footer: { paddingHorizontal: 18, paddingTop: 14, paddingBottom: 18 },

  section: { paddingHorizontal: 18, marginTop: 14 },
  label: { color: theme.textDim, fontSize: 10, fontWeight: '800', letterSpacing: 1.5, textTransform: 'uppercase', marginBottom: 6 },
  input: { backgroundColor: theme.surface, color: theme.text, borderColor: theme.border, borderWidth: 1, borderRadius: radii.sm, paddingHorizontal: 12, paddingVertical: 10, fontSize: 14 },
  charCount: { color: theme.textDim, fontSize: 11, marginTop: 4, textAlign: 'right' },
  help: { color: theme.textDim, fontSize: 11, marginTop: 6, lineHeight: 15 },
  toggleRow: { flexDirection: 'row', alignItems: 'center' },

  priceRow: { flexDirection: 'row', alignItems: 'center', backgroundColor: theme.surface, borderColor: theme.border, borderWidth: 1, borderRadius: radii.sm, paddingHorizontal: 12 },
  priceCurrency: { color: theme.gold, fontSize: 20, fontWeight: '800', marginRight: 6 },
  priceInput: { flex: 1, color: theme.text, fontSize: 22, fontWeight: '700', paddingVertical: 10 },

  qtyRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  qtyBtn: { width: 44, height: 44, borderRadius: radii.sm, backgroundColor: theme.surface, borderColor: theme.border, borderWidth: 1, alignItems: 'center', justifyContent: 'center' },
  qtyBtnText: { color: theme.gold, fontSize: 22, fontWeight: '800' },
  qtyInput: { flex: 1, height: 44, backgroundColor: theme.surface, color: theme.text, borderColor: theme.border, borderWidth: 1, borderRadius: radii.sm, paddingHorizontal: 12, fontSize: 18, fontWeight: '700', textAlign: 'center' },

  chipGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  chip: { paddingHorizontal: 10, paddingVertical: 7, borderRadius: 999, borderColor: theme.border, borderWidth: 1, backgroundColor: theme.surface2 },
  chipActive: { borderColor: theme.gold, backgroundColor: 'rgba(212,175,55,0.15)' },
  chipText: { color: theme.textMuted, fontSize: 12, fontWeight: '700' },
  chipTextActive: { color: theme.gold },

  photo: { borderRadius: radii.md, backgroundColor: theme.surface, borderColor: theme.border, borderWidth: 1 },

  btnGold: { backgroundColor: theme.gold, paddingVertical: 14, borderRadius: radii.sm, alignItems: 'center', marginTop: 4 },
  btnGoldText: { color: '#0a0a0a', fontWeight: '800', fontSize: 14, textTransform: 'uppercase', letterSpacing: 0.6 },
  btnGhost: { backgroundColor: 'transparent', borderColor: theme.border, borderWidth: 1, paddingVertical: 12, borderRadius: radii.sm, alignItems: 'center', marginTop: 8 },
  btnGhostText: { color: theme.textMuted, fontWeight: '700', fontSize: 13, textTransform: 'uppercase', letterSpacing: 0.5 },

  successCard: { padding: 18, borderRadius: radii.md, backgroundColor: theme.surface, borderColor: theme.gold, borderWidth: 1 },
  successEyebrow: { color: theme.gold, fontSize: 10, fontWeight: '800', letterSpacing: 2 },
  successTitle: { color: theme.text, fontSize: 18, fontWeight: '700', marginTop: 8 },
  successPrice: { color: theme.goldBright, fontSize: 32, fontWeight: '800', marginTop: 6 },
  itemId: { color: theme.textDim, fontSize: 12, marginTop: 4, marginBottom: 14 },

  errorCard: { padding: 18, borderRadius: radii.md, backgroundColor: theme.surface, borderColor: 'rgba(224,123,111,0.4)', borderWidth: 1 },
  errorEyebrow: { color: theme.danger, fontSize: 10, fontWeight: '800', letterSpacing: 2 },
  errorTitleText: { color: theme.text, fontSize: 17, fontWeight: '700', marginTop: 8 },
  errorDetail: { color: theme.textMuted, fontSize: 13, marginTop: 12, lineHeight: 18 },
});
