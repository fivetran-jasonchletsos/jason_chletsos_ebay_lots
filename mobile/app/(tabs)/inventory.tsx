import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import {
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { FlashList } from '@shopify/flash-list';
import { Image } from 'expo-image';
import { SafeAreaView } from 'react-native-safe-area-context';

import { theme, radii } from '@/src/theme';
import { listCards, countCards, type Card } from '@/src/db';

type FilterKey = 'all' | 'draft' | 'listed' | 'foil';

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'draft', label: 'Drafts' },
  { key: 'listed', label: 'Listed' },
  { key: 'foil', label: 'Foil' },
];

export default function InventoryScreen() {
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState<FilterKey>('all');
  const [cards, setCards] = useState<Card[]>([]);
  const [stats, setStats] = useState<{ total: number; listed: number; drafts: number; portfolioValue: number } | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const opts: Parameters<typeof listCards>[0] = {
        search: query.trim() || undefined,
        status: filter === 'draft' ? 'draft' : filter === 'listed' ? 'listed' : undefined,
        foilOnly: filter === 'foil',
      };
      const [rows, s] = await Promise.all([listCards(opts), countCards()]);
      setCards(rows);
      setStats(s);
    } finally {
      setLoading(false);
    }
  }, [query, filter]);

  useFocusEffect(useCallback(() => { refresh(); }, [refresh]));

  return (
    <SafeAreaView style={styles.root} edges={['top']}>
      <View style={styles.header}>
        <View>
          <Text style={styles.eyebrow}>HARPUA SCANNER</Text>
          <Text style={styles.headerTitle}>Inventory</Text>
        </View>
      </View>

      {stats ? (
        <View style={styles.statsRow}>
          <Stat label="Total" value={String(stats.total)} />
          <Stat label="Drafts" value={String(stats.drafts)} />
          <Stat label="Listed" value={String(stats.listed)} />
          <Stat label="Value" value={`$${stats.portfolioValue.toFixed(0)}`} highlight />
        </View>
      ) : null}

      <View style={styles.controls}>
        <TextInput
          value={query}
          onChangeText={setQuery}
          onSubmitEditing={refresh}
          placeholder="Search name, set, number…"
          placeholderTextColor={theme.textDim}
          style={styles.search}
          autoCapitalize="none"
          returnKeyType="search"
        />
        <View style={styles.filterRow}>
          {FILTERS.map((f) => (
            <Pressable
              key={f.key}
              onPress={() => setFilter(f.key)}
              style={[styles.chip, filter === f.key && styles.chipActive]}
            >
              <Text style={[styles.chipText, filter === f.key && styles.chipTextActive]}>{f.label}</Text>
            </Pressable>
          ))}
        </View>
      </View>

      <View style={{ flex: 1 }}>
        {!loading && cards.length === 0 ? (
          <View style={styles.empty}>
            <Text style={styles.emptyTitle}>Nothing yet</Text>
            <Text style={styles.emptySub}>
              {query ? 'No cards match that search.' : 'Snap a card on the Scan tab to start your inventory.'}
            </Text>
            {query ? (
              <TouchableOpacity onPress={() => { setQuery(''); setFilter('all'); }} style={styles.linkBtn}>
                <Text style={styles.linkBtnText}>Clear filters</Text>
              </TouchableOpacity>
            ) : null}
          </View>
        ) : (
          <FlashList
            data={cards}
            extraData={filter}
            keyExtractor={(item) => item.id}
            renderItem={({ item }) => <Row card={item} onPress={() => router.push({ pathname: '/card/[id]', params: { id: item.id } })} />}
            contentContainerStyle={{ paddingBottom: 24 }}
          />
        )}
      </View>
    </SafeAreaView>
  );
}

function Row({ card, onPress }: { card: Card; onPress: () => void }) {
  const price = card.user_price ?? card.tcg_market;
  const subtitle = [card.set_name, card.number ? `#${card.number}` : null, card.foil ? 'Foil' : null]
    .filter(Boolean)
    .join(' · ');
  return (
    <TouchableOpacity onPress={onPress} style={styles.row}>
      {card.thumb_uri ? (
        <Image source={{ uri: card.thumb_uri }} style={styles.rowThumb} />
      ) : (
        <View style={[styles.rowThumb, styles.emptyThumb]} />
      )}
      <View style={{ flex: 1, marginLeft: 12, minWidth: 0 }}>
        <Text numberOfLines={1} style={styles.rowName}>{card.name ?? '—'}</Text>
        {subtitle ? <Text numberOfLines={1} style={styles.rowSub}>{subtitle}</Text> : null}
        <View style={styles.rowMetaRow}>
          {card.listing_status === 'listed' ? <Tag label="Listed" tone="ok" /> : card.listing_status === 'sold' ? <Tag label="Sold" tone="ok" /> : <Tag label="Draft" tone="muted" />}
          {card.confidence === 'low' ? <Tag label="Low conf" tone="warn" /> : null}
        </View>
      </View>
      <View style={{ alignItems: 'flex-end' }}>
        <Text style={styles.rowPrice}>{price != null ? `$${price.toFixed(2)}` : '—'}</Text>
        {card.tcg_low != null ? <Text style={styles.rowLowHi}>${card.tcg_low.toFixed(2)} low</Text> : null}
      </View>
    </TouchableOpacity>
  );
}

function Stat({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <View style={styles.stat}>
      <Text style={styles.statLabel}>{label}</Text>
      <Text style={[styles.statVal, highlight && { color: theme.gold }]}>{value}</Text>
    </View>
  );
}

function Tag({ label, tone }: { label: string; tone: 'ok' | 'muted' | 'warn' }) {
  const palette =
    tone === 'ok' ? { bg: 'rgba(127,199,122,0.12)', fg: theme.success, bd: 'rgba(127,199,122,0.3)' } :
    tone === 'warn' ? { bg: 'rgba(224,181,74,0.12)', fg: theme.warning, bd: 'rgba(224,181,74,0.3)' } :
    { bg: theme.surface2, fg: theme.textMuted, bd: theme.border };
  return (
    <View style={[styles.tag, { backgroundColor: palette.bg, borderColor: palette.bd }]}>
      <Text style={[styles.tagText, { color: palette.fg }]}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.bg },
  header: { paddingHorizontal: 14, paddingVertical: 4 },
  eyebrow: { color: theme.gold, fontSize: 10, fontWeight: '800', letterSpacing: 2 },
  headerTitle: { color: theme.text, fontSize: 28, fontWeight: '800', letterSpacing: -0.5 },

  statsRow: { flexDirection: 'row', paddingHorizontal: 14, marginTop: 8, marginBottom: 4, gap: 8 },
  stat: { flex: 1, backgroundColor: theme.surface, borderColor: theme.border, borderWidth: 1, borderRadius: radii.sm, paddingHorizontal: 10, paddingVertical: 8 },
  statLabel: { color: theme.textDim, fontSize: 9, fontWeight: '800', letterSpacing: 1.5, textTransform: 'uppercase' },
  statVal: { color: theme.text, fontSize: 20, fontWeight: '800', marginTop: 2 },

  controls: { paddingHorizontal: 14, paddingTop: 10 },
  search: { backgroundColor: theme.surface2, color: theme.text, borderColor: theme.border, borderWidth: 1, borderRadius: radii.sm, paddingHorizontal: 12, paddingVertical: 10, fontSize: 14 },
  filterRow: { flexDirection: 'row', gap: 6, marginTop: 8 },
  chip: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999, borderColor: theme.border, borderWidth: 1, backgroundColor: theme.surface },
  chipActive: { borderColor: theme.gold, backgroundColor: 'rgba(212,175,55,0.15)' },
  chipText: { color: theme.textMuted, fontSize: 12, fontWeight: '700' },
  chipTextActive: { color: theme.gold },

  row: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 14, paddingVertical: 10, borderBottomColor: theme.border, borderBottomWidth: 1 },
  rowThumb: { width: 60, height: 84, borderRadius: radii.sm, backgroundColor: theme.surface, borderColor: theme.border, borderWidth: 1 },
  emptyThumb: { alignItems: 'center', justifyContent: 'center' },
  rowName: { color: theme.text, fontSize: 15, fontWeight: '700' },
  rowSub: { color: theme.textMuted, fontSize: 12, marginTop: 2 },
  rowMetaRow: { flexDirection: 'row', gap: 6, marginTop: 6 },
  tag: { borderWidth: 1, borderRadius: 4, paddingHorizontal: 6, paddingVertical: 2 },
  tagText: { fontSize: 9, fontWeight: '800', letterSpacing: 0.8, textTransform: 'uppercase' },
  rowPrice: { color: theme.gold, fontSize: 18, fontWeight: '800' },
  rowLowHi: { color: theme.textDim, fontSize: 10, marginTop: 2 },

  empty: { padding: 40, alignItems: 'center' },
  emptyTitle: { color: theme.text, fontSize: 18, fontWeight: '700' },
  emptySub: { color: theme.textMuted, fontSize: 13, marginTop: 6, textAlign: 'center' },
  linkBtn: { marginTop: 14 },
  linkBtnText: { color: theme.gold, fontWeight: '700', fontSize: 13 },
});
