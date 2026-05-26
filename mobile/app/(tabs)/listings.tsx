/**
 * Listings tab — your live eBay listings, sorted by time left ascending so
 * the about-to-expire stuff bubbles up first. Tap a row to open detail and
 * fix photos / price.
 *
 * The photo-count gate is enforced on the detail screen (which uses GetItem
 * and gets the full PictureURL list). GetMyeBaySelling only returns the
 * gallery thumb, so we can't compute it accurately here.
 */
import { useFocusEffect, router } from 'expo-router';
import { useCallback, useRef, useState } from 'react';
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

import { Price } from '@/components/Price';
import { fonts, radii, theme } from '@/src/theme';
import { getMyListings, type ListingSummary } from '@/src/api/listings';
import { EbayApiError, EbayAuthError } from '@/src/api/ebay';
import { getEbayCredentials } from '@/src/settings';

const PER_PAGE = 200;

export default function ListingsScreen() {
  const [listings, setListings] = useState<ListingSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasCreds, setHasCreds] = useState<boolean | null>(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  // Guards against onEndReached double-firing while a fetch is already in flight.
  const loadingMoreRef = useRef(false);

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
      const r = await getMyListings({ page: 1, perPage: PER_PAGE });
      setListings(r.listings);
      setTotal(r.total);
      setPage(r.page);
      setTotalPages(r.pages);
    } catch (e: any) {
      if (e instanceof EbayAuthError) setError('Couldn\'t authenticate with eBay. Check Settings.');
      else if (e instanceof EbayApiError) setError(e.longMessage || e.message);
      else setError(e?.message || String(e));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  const loadMore = useCallback(async () => {
    if (loadingMoreRef.current) return;
    if (page >= totalPages) return;
    loadingMoreRef.current = true;
    setLoadingMore(true);
    try {
      const next = page + 1;
      const r = await getMyListings({ page: next, perPage: PER_PAGE });
      setListings((prev) => {
        const seen = new Set(prev.map((l) => l.item_id));
        const fresh = r.listings.filter((l) => !seen.has(l.item_id));
        return prev.concat(fresh);
      });
      setPage(r.page);
      setTotalPages(r.pages);
      setTotal(r.total);
    } catch (e: any) {
      if (e instanceof EbayAuthError) setError('Couldn\'t authenticate with eBay. Check Settings.');
      else if (e instanceof EbayApiError) setError(e.longMessage || e.message);
      else setError(e?.message || String(e));
    } finally {
      setLoadingMore(false);
      loadingMoreRef.current = false;
    }
  }, [page, totalPages]);

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

  const headerCount = total || listings.length;

  return (
    <SafeAreaView style={styles.root} edges={['top']}>
      <View style={styles.header}>
        <Text style={styles.eyebrow}>ACTIVE LISTINGS</Text>
        <Text style={styles.title}>{headerCount}</Text>
        <Text style={styles.headerSub}>
          {listings.length < headerCount
            ? `Showing ${listings.length} of ${headerCount} — scroll for more`
            : 'All listings loaded'}
        </Text>
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
        onEndReached={loadMore}
        onEndReachedThreshold={0.4}
        ListFooterComponent={() => (
          loadingMore ? (
            <View style={styles.footer}>
              <ActivityIndicator color={theme.gold} />
              <Text style={styles.footerText}>
                Loading page {page + 1} of {totalPages}…
              </Text>
            </View>
          ) : null
        )}
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
  return (
    <Pressable
      onPress={() => router.push(`/listing/${item.item_id}`)}
      style={({ pressed }) => [styles.row, pressed && { opacity: 0.7 }]}
    >
      <View style={styles.thumbWrap}>
        {item.picture_url ? (
          <Image source={{ uri: item.picture_url }} style={styles.thumb} contentFit="cover" />
        ) : (
          <View style={[styles.thumb, styles.thumbBlank]}>
            <Text style={styles.thumbBlankText}>NO IMG</Text>
          </View>
        )}
      </View>
      <View style={styles.rowBody}>
        <Text style={styles.rowTitle} numberOfLines={2}>{item.title}</Text>
        <View style={styles.metaRow}>
          <Price value={item.price ?? null} size="md" />
          {item.watch_count != null ? <Text style={styles.meta}>{item.watch_count} watching</Text> : null}
          {item.best_offer_count > 0 ? <Text style={styles.metaHot}>{item.best_offer_count} offer{item.best_offer_count === 1 ? '' : 's'}</Text> : null}
        </View>
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
  eyebrow: { color: theme.textDim, fontFamily: fonts.bodyBold, fontSize: 10, letterSpacing: 1.6 },
  // Fraunces italic carries the visual weight — drop the heavy weight + tight tracking.
  title: { color: theme.text, fontFamily: fonts.display, fontSize: 36, letterSpacing: 0 },
  headerSub: { color: theme.textMuted, fontSize: 12, marginTop: 4 },

  btnQuickList: { marginTop: 12, backgroundColor: theme.surface, borderColor: theme.gold, borderWidth: 1, paddingVertical: 10, borderRadius: radii.sm, alignItems: 'center' },
  btnQuickListText: { color: theme.gold, fontSize: 12, fontWeight: '800', letterSpacing: 0.8, textTransform: 'uppercase' },

  row: { flexDirection: 'row', paddingHorizontal: 18, paddingVertical: 12, gap: 12, borderBottomColor: theme.border, borderBottomWidth: 1, backgroundColor: theme.bg },

  thumbWrap: { position: 'relative' },
  // Portrait 3:4 — matches the card-face aspect ratio used on the site.
  thumb: { width: 60, height: 80, borderRadius: radii.sm, backgroundColor: theme.surface, borderColor: theme.border, borderWidth: 1 },
  thumbBlank: { alignItems: 'center', justifyContent: 'center' },
  thumbBlankText: { color: theme.textDim, fontSize: 10, fontWeight: '800', letterSpacing: 1 },

  rowBody: { flex: 1 },
  rowTitle: { color: theme.text, fontSize: 14, fontWeight: '600', lineHeight: 18 },
  metaRow: { flexDirection: 'row', alignItems: 'baseline', gap: 12, marginTop: 4, flexWrap: 'wrap' },
  meta: { color: theme.textDim, fontSize: 11 },
  metaHot: { color: theme.gold, fontSize: 11, fontWeight: '700' },

  footer: { paddingVertical: 18, alignItems: 'center', gap: 8 },
  footerText: { color: theme.textMuted, fontSize: 11, letterSpacing: 0.6, textTransform: 'uppercase', fontWeight: '700' },

  btnGold: { backgroundColor: theme.gold, paddingVertical: 12, paddingHorizontal: 24, borderRadius: radii.sm, alignItems: 'center', marginTop: 18 },
  btnGoldText: { color: '#0a0a0a', fontWeight: '800', fontSize: 13, textTransform: 'uppercase', letterSpacing: 0.6 },
});
