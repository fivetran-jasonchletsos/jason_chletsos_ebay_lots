/**
 * Listings tab — your live eBay listings, sorted by time left ascending so
 * the about-to-expire stuff bubbles up first. Tap a row to open detail and
 * fix photos / price.
 *
 * Highlights: each row shows the photo-count gauge against the Cassini
 * gate (8+ photos at >=1600px). Rows below the gate are tinted red — those
 * are the listings the photo-audit agent says are bleeding impressions.
 */
import { useFocusEffect, router } from 'expo-router';
import { useCallback, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { FlashList } from '@shopify/flash-list';
import { Image } from 'expo-image';
import { SafeAreaView } from 'react-native-safe-area-context';

import { radii, theme } from '@/src/theme';
import { getMyListings, type ListingSummary } from '@/src/api/listings';
import { EbayApiError, EbayAuthError } from '@/src/api/ebay';
import { getEbayCredentials } from '@/src/settings';

const CASSINI_PHOTO_GATE = 8;

export default function ListingsScreen() {
  const [listings, setListings] = useState<ListingSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasCreds, setHasCreds] = useState<boolean | null>(null);
  const [total, setTotal] = useState(0);

  const load = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    else setLoading(true);
    setError(null);
    try {
      const creds = await getEbayCredentials();
      setHasCreds(!!creds);
      if (!creds) {
        setListings([]);
        return;
      }
      const r = await getMyListings({ page: 1, perPage: 100 });
      setListings(r.listings);
      setTotal(r.total);
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

  if (loading && listings.length === 0) {
    return (
      <SafeAreaView style={[styles.root, styles.center]}>
        <ActivityIndicator color={theme.gold} />
        <Text style={[styles.muted, { marginTop: 12 }]}>Loading your eBay listings…</Text>
      </SafeAreaView>
    );
  }

  if (hasCreds === false) {
    return (
      <SafeAreaView style={[styles.root, styles.center]}>
        <Text style={styles.bigDim}>eBay not connected</Text>
        <Text style={[styles.muted, { textAlign: 'center', paddingHorizontal: 32, marginTop: 8 }]}>
          Open Settings and add your eBay App ID, Cert ID, and refresh token.
        </Text>
        <TouchableOpacity style={styles.btnGold} onPress={() => router.push('/(tabs)/settings')}>
          <Text style={styles.btnGoldText}>Go to settings</Text>
        </TouchableOpacity>
      </SafeAreaView>
    );
  }

  if (error && listings.length === 0) {
    return (
      <SafeAreaView style={[styles.root, styles.center]}>
        <Text style={[styles.bigDim, { color: theme.danger }]}>Couldn't load listings</Text>
        <Text style={[styles.muted, { textAlign: 'center', paddingHorizontal: 32, marginTop: 8 }]}>{error}</Text>
        <TouchableOpacity style={styles.btnGold} onPress={() => load(false)}>
          <Text style={styles.btnGoldText}>Try again</Text>
        </TouchableOpacity>
      </SafeAreaView>
    );
  }

  const failCount = listings.filter((l) => l.picture_count < CASSINI_PHOTO_GATE).length;

  return (
    <SafeAreaView style={styles.root} edges={['top']}>
      <View style={styles.header}>
        <Text style={styles.eyebrow}>ACTIVE LISTINGS</Text>
        <Text style={styles.title}>{total || listings.length}</Text>
        {failCount > 0 ? (
          <Text style={styles.headerWarn}>
            {failCount} listing{failCount === 1 ? '' : 's'} below Cassini photo gate ({CASSINI_PHOTO_GATE}+ photos)
          </Text>
        ) : (
          <Text style={styles.headerOK}>All listings meet the Cassini photo gate.</Text>
        )}
        <TouchableOpacity style={styles.btnQuickList} onPress={() => router.push('/quick-list')}>
          <Text style={styles.btnQuickListText}>+ Quick list new item</Text>
        </TouchableOpacity>
      </View>

      <FlashList
        data={listings}
        keyExtractor={(l) => l.item_id}
        contentContainerStyle={{ paddingBottom: 32 }}
        refreshControl={<RefreshControl tintColor={theme.gold} refreshing={refreshing} onRefresh={() => load(true)} />}
        renderItem={({ item }) => <Row item={item} />}
        ListEmptyComponent={() => (
          <View style={[styles.center, { paddingTop: 80 }]}>
            <Text style={styles.muted}>No active listings.</Text>
          </View>
        )}
      />
    </SafeAreaView>
  );
}

function Row({ item }: { item: ListingSummary }) {
  const photosLow = item.picture_count < CASSINI_PHOTO_GATE;
  return (
    <Pressable
      onPress={() => router.push(`/listing/${item.item_id}`)}
      style={({ pressed }) => [styles.row, photosLow && styles.rowWarn, pressed && { opacity: 0.7 }]}
    >
      <View style={styles.thumbWrap}>
        {item.picture_url ? (
          <Image source={{ uri: item.picture_url }} style={styles.thumb} contentFit="cover" />
        ) : (
          <View style={[styles.thumb, styles.thumbBlank]}>
            <Text style={styles.thumbBlankText}>NO IMG</Text>
          </View>
        )}
        <View style={[styles.photoBadge, photosLow && styles.photoBadgeWarn]}>
          <Text style={[styles.photoBadgeText, photosLow && styles.photoBadgeTextWarn]}>{item.picture_count}</Text>
        </View>
      </View>
      <View style={styles.rowBody}>
        <Text style={styles.rowTitle} numberOfLines={2}>{item.title}</Text>
        <View style={styles.metaRow}>
          <Text style={styles.price}>{item.price != null ? `$${item.price.toFixed(2)}` : '—'}</Text>
          {item.watch_count != null ? <Text style={styles.meta}>{item.watch_count} watching</Text> : null}
          {item.best_offer_count > 0 ? <Text style={styles.metaHot}>{item.best_offer_count} offer{item.best_offer_count === 1 ? '' : 's'}</Text> : null}
        </View>
        {photosLow ? (
          <Text style={styles.warnLine}>Only {item.picture_count} photo{item.picture_count === 1 ? '' : 's'} — replace to fix Cassini</Text>
        ) : null}
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.bg },
  center: { alignItems: 'center', justifyContent: 'center', flex: 1 },
  muted: { color: theme.textMuted, fontSize: 13 },
  bigDim: { color: theme.text, fontSize: 18, fontWeight: '700' },

  header: { paddingHorizontal: 18, paddingTop: 14, paddingBottom: 14, borderBottomColor: theme.border, borderBottomWidth: 1 },
  eyebrow: { color: theme.textDim, fontSize: 10, fontWeight: '800', letterSpacing: 1.6 },
  title: { color: theme.text, fontSize: 36, fontWeight: '800', letterSpacing: -1 },
  headerWarn: { color: theme.danger, fontSize: 12, marginTop: 4 },
  headerOK: { color: theme.success, fontSize: 12, marginTop: 4 },

  btnQuickList: { marginTop: 12, backgroundColor: theme.surface, borderColor: theme.gold, borderWidth: 1, paddingVertical: 10, borderRadius: radii.sm, alignItems: 'center' },
  btnQuickListText: { color: theme.gold, fontSize: 12, fontWeight: '800', letterSpacing: 0.8, textTransform: 'uppercase' },

  row: { flexDirection: 'row', paddingHorizontal: 18, paddingVertical: 12, gap: 12, borderBottomColor: theme.border, borderBottomWidth: 1, backgroundColor: theme.bg },
  rowWarn: { backgroundColor: 'rgba(224,123,111,0.04)' },

  thumbWrap: { position: 'relative' },
  thumb: { width: 70, height: 70, borderRadius: radii.sm, backgroundColor: theme.surface, borderColor: theme.border, borderWidth: 1 },
  thumbBlank: { alignItems: 'center', justifyContent: 'center' },
  thumbBlankText: { color: theme.textDim, fontSize: 10, fontWeight: '800', letterSpacing: 1 },

  photoBadge: { position: 'absolute', bottom: -4, right: -4, minWidth: 22, height: 22, borderRadius: 11, backgroundColor: theme.surface, borderColor: theme.gold, borderWidth: 1, paddingHorizontal: 6, alignItems: 'center', justifyContent: 'center' },
  photoBadgeWarn: { borderColor: theme.danger, backgroundColor: 'rgba(224,123,111,0.15)' },
  photoBadgeText: { color: theme.gold, fontSize: 11, fontWeight: '800' },
  photoBadgeTextWarn: { color: theme.danger },

  rowBody: { flex: 1 },
  rowTitle: { color: theme.text, fontSize: 14, fontWeight: '600', lineHeight: 18 },
  metaRow: { flexDirection: 'row', alignItems: 'baseline', gap: 12, marginTop: 4, flexWrap: 'wrap' },
  price: { color: theme.goldBright, fontSize: 16, fontWeight: '800' },
  meta: { color: theme.textDim, fontSize: 11 },
  metaHot: { color: theme.gold, fontSize: 11, fontWeight: '700' },
  warnLine: { color: theme.danger, fontSize: 11, marginTop: 4 },

  btnGold: { backgroundColor: theme.gold, paddingVertical: 12, paddingHorizontal: 24, borderRadius: radii.sm, alignItems: 'center', marginTop: 18 },
  btnGoldText: { color: '#0a0a0a', fontWeight: '800', fontSize: 13, textTransform: 'uppercase', letterSpacing: 0.6 },
});
