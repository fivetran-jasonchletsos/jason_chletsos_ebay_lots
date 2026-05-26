/**
 * Replace photos on a live eBay listing.
 *
 * Flow:
 *   1. Camera capture loop — snap up to 12 photos in one session.
 *   2. Thumbnail tray with delete + reorder (drag-free reorder via tap-to-promote).
 *   3. Confirm prompt -> downscale each photo to <=2400px wide (top sellers
 *      recommend 1600px+, headroom for sharper crops), upload via
 *      UploadSiteHostedPictures with a small concurrency cap, collect FullURLs.
 *   4. revisePictures(itemId, urls) -> success card.
 *
 * eBay's PictureDetails block replaces the entire gallery when sent via
 * ReviseFixedPriceItem, so we always upload the full set the seller
 * approved on this screen.
 */
import { CameraView, useCameraPermissions } from 'expo-camera';
import * as ImageManipulator from 'expo-image-manipulator';
import * as Haptics from 'expo-haptics';
import { Image } from 'expo-image';
import { router, useLocalSearchParams } from 'expo-router';
import { useRef, useState } from 'react';
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
  useWindowDimensions,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { radii, theme } from '@/src/theme';
import { EbayApiError, EbayAuthError, uploadImage } from '@/src/api/ebay';
import { revisePictures } from '@/src/api/listings';

const MAX_PHOTOS = 12;
const RECOMMENDED_PHOTO_COUNT = 8;
const TARGET_LONG_EDGE_PX = 2400;     // headroom over the 1600px top-seller recommendation

type Phase = 'capture' | 'submitting' | 'success' | 'error';

export default function ReplacePhotosScreen() {
  const { itemId } = useLocalSearchParams<{ itemId: string }>();
  const { width } = useWindowDimensions();

  const [permission, requestPermission] = useCameraPermissions();
  const cameraRef = useRef<CameraView | null>(null);

  const [photos, setPhotos] = useState<string[]>([]);
  const [busyShutter, setBusyShutter] = useState(false);

  const [phase, setPhase] = useState<Phase>('capture');
  const [progressMsg, setProgressMsg] = useState('');
  const [errorTitle, setErrorTitle] = useState('');
  const [errorDetail, setErrorDetail] = useState('');
  const [resultUrl, setResultUrl] = useState<string | null>(null);

  // Sticky upload buffer — `uploadedUrls[i]` is the eBay CDN URL for
  // photos[i] once it lands successfully. If photo 4 of 8 fails, the
  // already-uploaded URLs 1-3 stay here so retry skips them and we don't
  // orphan duplicates on eBay's CDN.
  const [uploadedUrls, setUploadedUrls] = useState<(string | null)[]>([]);

  const submitting = useRef(false);

  if (!permission) {
    return <SafeAreaView style={[styles.root, styles.center]}><ActivityIndicator color={theme.gold} /></SafeAreaView>;
  }
  if (!permission.granted) {
    return (
      <SafeAreaView style={[styles.root, styles.center]}>
        <Text style={styles.bigDim}>Camera access needed</Text>
        <Text style={[styles.muted, { marginTop: 8, textAlign: 'center', paddingHorizontal: 32 }]}>
          We need the camera to shoot replacement photos for this listing.
        </Text>
        <TouchableOpacity style={styles.btnGold} onPress={requestPermission}>
          <Text style={styles.btnGoldText}>Allow camera</Text>
        </TouchableOpacity>
      </SafeAreaView>
    );
  }

  async function shoot() {
    if (!cameraRef.current || busyShutter) return;
    if (photos.length >= MAX_PHOTOS) {
      Alert.alert('Max photos reached', `eBay caps galleries at ${MAX_PHOTOS} on this screen. Remove one to add another.`);
      return;
    }
    setBusyShutter(true);
    try {
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
      // quality 0.85 + skipProcessing=true keeps memory pressure low on
      // older devices — we downscale to 2400px before upload anyway, so a
      // full-res 12MP source is wasted bytes.
      const photo = await cameraRef.current.takePictureAsync({ quality: 0.85, skipProcessing: true });
      if (!photo?.uri) throw new Error('No photo returned');
      setPhotos((prev) => [...prev, photo.uri]);
    } catch (e: any) {
      Alert.alert('Capture failed', e?.message ?? String(e));
    } finally {
      setBusyShutter(false);
    }
  }

  function removeAt(i: number) {
    setPhotos((prev) => prev.filter((_, idx) => idx !== i));
    // Indices into uploadedUrls no longer match — drop the buffer so we
    // re-upload after a reshuffle. Cheaper than trying to splice URLs.
    setUploadedUrls([]);
  }

  function promote(i: number) {
    // Move photo i to index 0 (becomes the gallery thumbnail).
    setPhotos((prev) => {
      if (i === 0) return prev;
      const copy = prev.slice();
      const [item] = copy.splice(i, 1);
      copy.unshift(item);
      return copy;
    });
    setUploadedUrls([]);
  }

  function confirmSubmit() {
    if (submitting.current) return;
    if (!itemId) return;
    if (photos.length === 0) {
      Alert.alert('No photos', 'Shoot at least one photo before replacing.');
      return;
    }
    const warn = photos.length < RECOMMENDED_PHOTO_COUNT
      ? `\n\nHeads up: only ${photos.length} photo${photos.length === 1 ? '' : 's'} — top sellers usually post ${RECOMMENDED_PHOTO_COUNT}+. Replace anyway?`
      : '';
    Alert.alert(
      'Replace photos on eBay?',
      `This will replace the entire photo gallery on item #${itemId} with the ${photos.length} photo${photos.length === 1 ? '' : 's'} you shot.${warn}`,
      [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Replace photos', style: 'destructive', onPress: submit },
      ],
    );
  }

  /**
   * Two-phase submit, all-or-nothing on the revise call:
   *
   *   Phase A — upload each local photo to eBay's CDN sequentially, parking
   *             the resulting URL in `uploadedUrls[i]`. If any single upload
   *             fails, we stop and surface a partial-failure dialog so the
   *             seller can retry only the failed indices. We do NOT call
   *             `revisePictures` until every index has a URL — otherwise a
   *             failed-then-retried photo would orphan duplicates on eBay's
   *             CDN.
   *
   *   Phase B — once `uploadedUrls.length === photos.length` with no nulls,
   *             call `revisePictures(itemId, urls)`. If that fails after
   *             upload completes, the URLs are orphaned but it's a single
   *             API call away from succeeding, so we offer a retry instead
   *             of re-uploading.
   */
  async function submit() {
    if (!itemId) return;
    submitting.current = true;
    setPhase('submitting');
    setProgressMsg('Preparing photos…');

    // Initialize / preserve the upload buffer to match the photos array.
    let buffer = uploadedUrls.length === photos.length
      ? uploadedUrls.slice()
      : photos.map(() => null);

    try {
      // ---- Phase A: upload anything that hasn't landed yet ----
      for (let i = 0; i < photos.length; i++) {
        if (buffer[i]) continue; // already uploaded on a prior attempt
        setProgressMsg(`Uploading photo ${i + 1} of ${photos.length}…`);
        try {
          const resized = await downscale(photos[i]);
          const r = await uploadImage(resized.uri);
          buffer[i] = r.full_url;
          // Persist the URL immediately — if the very next photo fails we
          // don't want to lose what already worked.
          setUploadedUrls(buffer.slice());
        } catch (e: any) {
          // Partial-failure dialog. We hold off on revisePictures entirely
          // until every URL is in hand.
          const doneCount = buffer.filter(Boolean).length;
          const remaining = photos.length - doneCount;
          setUploadedUrls(buffer.slice());
          submitting.current = false;
          Alert.alert(
            `Uploaded ${doneCount} of ${photos.length}`,
            `Photo ${i + 1} failed: ${e?.message ?? String(e)}.\n\nRetry remaining ${remaining}?`,
            [
              { text: 'Cancel', style: 'cancel', onPress: () => setPhase('capture') },
              { text: 'Retry', onPress: () => submit() },
            ],
          );
          return;
        }
      }

      // ---- Phase B: revise the listing with the full URL set ----
      const urls = buffer.filter((u): u is string => !!u);
      if (urls.length !== photos.length) {
        throw new Error('Internal: upload buffer not complete before revise call.');
      }
      setProgressMsg('Updating listing on eBay…');
      try {
        const result = await revisePictures(String(itemId), urls);
        setResultUrl(`https://www.ebay.com/itm/${result.item_id}`);
        setPhase('success');
        // Once the gallery is replaced the URLs are committed — wipe the
        // buffer so a later retry from capture starts clean.
        setUploadedUrls([]);
      } catch (reviseErr: any) {
        submitting.current = false;
        Alert.alert(
          'Photos uploaded but gallery swap failed',
          `${reviseErr?.message ?? String(reviseErr)}\n\nThe photos are on eBay's CDN — retrying just re-sends the gallery swap.`,
          [
            { text: 'Cancel', style: 'cancel', onPress: () => {
              setErrorTitle('Gallery swap failed');
              setErrorDetail(reviseErr?.longMessage || reviseErr?.message || String(reviseErr));
              setPhase('error');
            } },
            { text: 'Retry', onPress: () => submit() },
          ],
        );
        return;
      }
    } catch (e: any) {
      if (e instanceof EbayAuthError) {
        setErrorTitle('Couldn\'t authenticate with eBay');
        setErrorDetail('Check your refresh token, App ID, and Cert ID in Settings.');
      } else if (e instanceof EbayApiError) {
        setErrorTitle(e.message || 'eBay rejected the update');
        setErrorDetail(e.longMessage || '');
      } else {
        setErrorTitle('Photo replace failed');
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
        <Text style={[styles.muted, { marginTop: 18, fontSize: 14 }]}>{progressMsg || 'Working…'}</Text>
        <Text style={[styles.muted, { marginTop: 6, fontSize: 11 }]}>Don't close the app until this finishes.</Text>
      </SafeAreaView>
    );
  }

  if (phase === 'success' && resultUrl) {
    return (
      <SafeAreaView style={styles.root}>
        <ScrollView contentContainerStyle={{ padding: 18, paddingBottom: 40 }}>
          <View style={styles.successCard}>
            <Text style={styles.successEyebrow}>PHOTOS REPLACED</Text>
            <Text style={styles.successTitle}>Live on eBay</Text>
            <Text style={styles.successDetail}>
              {photos.length} photo{photos.length === 1 ? '' : 's'} now on item #{itemId}. Most top sellers see results within a few hours.
            </Text>
            <TouchableOpacity style={styles.btnGold} onPress={() => Linking.openURL(resultUrl)}>
              <Text style={styles.btnGoldText}>View on eBay</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.btnGhost} onPress={() => router.replace(`/listing/${itemId}`)}>
              <Text style={styles.btnGhostText}>Back to listing</Text>
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
            <Text style={styles.errorEyebrow}>UPDATE FAILED</Text>
            <Text style={styles.errorTitleText}>{errorTitle}</Text>
            {errorDetail ? <Text style={styles.errorDetail}>{errorDetail}</Text> : null}
            <View style={{ flexDirection: 'row', gap: 8, marginTop: 18 }}>
              <TouchableOpacity
                style={[styles.btnGold, { flex: 1 }]}
                onPress={() => {
                  // Drop the upload buffer — a "Try again" from the error
                  // card means the seller is starting over from photos.
                  setUploadedUrls([]);
                  setPhase('capture');
                }}
              >
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

  // -- capture phase --
  const cameraSize = Math.min(width, 480);
  const thumbW = (width - 18 * 2 - 8 * 3) / 4;

  return (
    <SafeAreaView style={styles.root} edges={['top']}>
      <View style={styles.header}>
        <Text style={styles.eyebrow}>REPLACE PHOTOS</Text>
        <Text style={styles.headerTitle}>{photos.length}/{MAX_PHOTOS} photos</Text>
        <Text style={styles.headerSub}>
          Top-seller recommendation: {RECOMMENDED_PHOTO_COUNT}+ photos at 1600px+. Shoot well-lit, in focus, fill the frame.
        </Text>
      </View>

      <View style={[styles.cameraFrame, { height: cameraSize }]}>
        <CameraView
          ref={cameraRef as any}
          style={{ flex: 1 }}
          facing="back"
          autofocus="on"
        />
        <TouchableOpacity
          style={[styles.shutter, busyShutter && { opacity: 0.5 }]}
          onPress={shoot}
          disabled={busyShutter || photos.length >= MAX_PHOTOS}
        />
      </View>

      {photos.length > 0 ? (
        <View style={styles.tray}>
          <Text style={styles.trayLabel}>Tap photo to make it the gallery thumbnail. Tap the X to remove.</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8, paddingHorizontal: 18 }}>
            {photos.map((uri, i) => (
              <View key={`${uri}-${i}`} style={{ width: thumbW, height: thumbW * 1.0 }}>
                <Pressable
                  onPress={() => promote(i)}
                  style={({ pressed }) => [styles.thumbWrap, { width: '100%', height: '100%' }, pressed && { opacity: 0.7 }]}
                >
                  <Image
                    source={{ uri }}
                    style={styles.thumb}
                    contentFit="cover"
                    cachePolicy="memory-disk"
                  />
                  {i === 0 ? <View style={styles.coverBadge}><Text style={styles.coverBadgeText}>COVER</Text></View> : null}
                  <View style={styles.indexBadge}><Text style={styles.indexBadgeText}>{i + 1}</Text></View>
                </Pressable>
                <Pressable
                  onPress={() => removeAt(i)}
                  hitSlop={8}
                  style={({ pressed }) => [styles.removeBadge, pressed && { opacity: 0.7 }]}
                  accessibilityLabel={`Remove photo ${i + 1}`}
                >
                  <Text style={styles.removeBadgeText}>×</Text>
                </Pressable>
              </View>
            ))}
          </ScrollView>
        </View>
      ) : null}

      <View style={styles.footer}>
        <TouchableOpacity
          style={[styles.btnGold, photos.length === 0 && { opacity: 0.5 }]}
          onPress={confirmSubmit}
          disabled={photos.length === 0}
        >
          <Text style={styles.btnGoldText}>Replace eBay photos ({photos.length})</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.btnGhost} onPress={() => router.back()}>
          <Text style={styles.btnGhostText}>Cancel</Text>
        </TouchableOpacity>
      </View>
    </SafeAreaView>
  );
}

async function downscale(uri: string): Promise<ImageManipulator.ImageResult> {
  // Downscale to a max edge of TARGET_LONG_EDGE_PX, JPEG 0.85. Top sellers
  // typically ship 1600px+; we go to 2400px so cropping headroom is preserved
  // without pushing 12MB per file.
  return ImageManipulator.manipulateAsync(
    uri,
    [{ resize: { width: TARGET_LONG_EDGE_PX } }],
    { compress: 0.85, format: ImageManipulator.SaveFormat.JPEG },
  );
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
  indexBadge: { position: 'absolute', bottom: 4, right: 4, width: 20, height: 20, borderRadius: 10, backgroundColor: 'rgba(0,0,0,0.7)', alignItems: 'center', justifyContent: 'center' },
  indexBadgeText: { color: theme.text, fontSize: 11, fontWeight: '800' },
  removeBadge: { position: 'absolute', top: -6, right: -6, width: 28, height: 28, borderRadius: 14, backgroundColor: theme.danger, alignItems: 'center', justifyContent: 'center', borderColor: '#0a0a0a', borderWidth: 2 },
  removeBadgeText: { color: theme.text, fontSize: 18, fontWeight: '800', lineHeight: 20, marginTop: -2 },

  footer: { paddingHorizontal: 18, paddingTop: 14, paddingBottom: 18 },
  btnGold: { backgroundColor: theme.gold, paddingVertical: 14, borderRadius: radii.sm, alignItems: 'center', marginTop: 4 },
  btnGoldText: { color: '#0a0a0a', fontWeight: '800', fontSize: 14, textTransform: 'uppercase', letterSpacing: 0.6 },
  btnGhost: { backgroundColor: 'transparent', borderColor: theme.border, borderWidth: 1, paddingVertical: 12, borderRadius: radii.sm, alignItems: 'center', marginTop: 8 },
  btnGhostText: { color: theme.textMuted, fontWeight: '700', fontSize: 13, textTransform: 'uppercase', letterSpacing: 0.5 },

  successCard: { padding: 18, borderRadius: radii.md, backgroundColor: theme.surface, borderColor: theme.success, borderWidth: 1 },
  successEyebrow: { color: theme.success, fontSize: 10, fontWeight: '800', letterSpacing: 2 },
  successTitle: { color: theme.text, fontSize: 22, fontWeight: '800', marginTop: 8 },
  successDetail: { color: theme.textMuted, fontSize: 13, marginTop: 6, marginBottom: 14, lineHeight: 19 },

  errorCard: { padding: 18, borderRadius: radii.md, backgroundColor: theme.surface, borderColor: 'rgba(224,123,111,0.4)', borderWidth: 1 },
  errorEyebrow: { color: theme.danger, fontSize: 10, fontWeight: '800', letterSpacing: 2 },
  errorTitleText: { color: theme.text, fontSize: 17, fontWeight: '700', marginTop: 8 },
  errorDetail: { color: theme.textMuted, fontSize: 13, marginTop: 12, lineHeight: 18 },
});
