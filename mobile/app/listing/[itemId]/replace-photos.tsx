/**
 * Replace photos on a live eBay listing.
 *
 * Flow:
 *   1. Camera capture loop — snap up to 12 photos in one session.
 *   2. Thumbnail tray with delete + reorder (drag-free reorder via tap-to-promote).
 *   3. Confirm prompt -> for each photo: downscale to <=2400px wide
 *      (Cassini gate is 1600+, headroom for sharper crops), upload via
 *      UploadSiteHostedPictures, collect FullURLs.
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
const CASSINI_PHOTO_GATE = 8;
const TARGET_LONG_EDGE_PX = 2400;     // headroom over the 1600 Cassini gate

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
      const photo = await cameraRef.current.takePictureAsync({ quality: 1, skipProcessing: false });
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
  }

  function confirmSubmit() {
    if (submitting.current) return;
    if (!itemId) return;
    if (photos.length === 0) {
      Alert.alert('No photos', 'Shoot at least one photo before replacing.');
      return;
    }
    const warn = photos.length < CASSINI_PHOTO_GATE
      ? `\n\nHeads up: only ${photos.length} photo${photos.length === 1 ? '' : 's'} — Cassini wants ${CASSINI_PHOTO_GATE}+. Replace anyway?`
      : '';
    Alert.alert(
      'Replace LIVE eBay photos?',
      `This will replace the entire photo gallery on item #${itemId} with the ${photos.length} photo${photos.length === 1 ? '' : 's'} you shot.${warn}`,
      [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Replace photos', style: 'destructive', onPress: submit },
      ],
    );
  }

  async function submit() {
    if (!itemId) return;
    submitting.current = true;
    setPhase('submitting');
    setProgressMsg('Preparing photos…');

    try {
      const uploaded: string[] = [];
      for (let i = 0; i < photos.length; i++) {
        setProgressMsg(`Optimizing photo ${i + 1} of ${photos.length}…`);
        const resized = await downscale(photos[i]);
        setProgressMsg(`Uploading photo ${i + 1} of ${photos.length}…`);
        const r = await uploadImage(resized.uri);
        uploaded.push(r.full_url);
      }
      if (uploaded.length === 0) throw new Error('No photos uploaded successfully.');
      setProgressMsg('Updating listing on eBay…');
      const result = await revisePictures(String(itemId), uploaded);
      setResultUrl(`https://www.ebay.com/itm/${result.item_id}`);
      setPhase('success');
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
              {photos.length} photo{photos.length === 1 ? '' : 's'} now on item #{itemId}. Cassini reindex usually within a few hours.
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
              <TouchableOpacity style={[styles.btnGold, { flex: 1 }]} onPress={() => setPhase('capture')}>
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
          Cassini gate: {CASSINI_PHOTO_GATE}+ photos. Shoot well-lit, in focus, fill the frame.
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
          <Text style={styles.trayLabel}>Tap photo to make it the gallery thumbnail. Long-press to remove.</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8, paddingHorizontal: 18 }}>
            {photos.map((uri, i) => (
              <Pressable
                key={`${uri}-${i}`}
                onPress={() => promote(i)}
                onLongPress={() => removeAt(i)}
                style={({ pressed }) => [styles.thumbWrap, { width: thumbW, height: thumbW * 1.0 }, pressed && { opacity: 0.7 }]}
              >
                <Image source={{ uri }} style={styles.thumb} contentFit="cover" />
                {i === 0 ? <View style={styles.coverBadge}><Text style={styles.coverBadgeText}>COVER</Text></View> : null}
                <View style={styles.indexBadge}><Text style={styles.indexBadgeText}>{i + 1}</Text></View>
              </Pressable>
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
  // Downscale to a max edge of TARGET_LONG_EDGE_PX, JPEG 0.85. Cassini gate is
  // 1600px+; we ship 2400px so cropping headroom is preserved without
  // pushing 12MB per file.
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
