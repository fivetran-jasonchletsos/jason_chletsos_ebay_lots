/**
 * SQLite inventory layer. One DB, one table, append-only-ish.
 * Image paths are local file:// URIs (managed in expo-file-system).
 */
import * as SQLite from 'expo-sqlite';

const DB_NAME = 'harpua-scanner.db';

let dbPromise: Promise<SQLite.SQLiteDatabase> | null = null;

export function getDb(): Promise<SQLite.SQLiteDatabase> {
  if (!dbPromise) {
    dbPromise = (async () => {
      const db = await SQLite.openDatabaseAsync(DB_NAME);
      await migrate(db);
      return db;
    })();
  }
  return dbPromise;
}

async function migrate(db: SQLite.SQLiteDatabase) {
  await db.execAsync(`
    PRAGMA journal_mode = WAL;

    CREATE TABLE IF NOT EXISTS cards (
      id              TEXT PRIMARY KEY,
      captured_at     TEXT NOT NULL,
      updated_at      TEXT NOT NULL,

      -- identification (from Claude vision)
      name            TEXT,
      set_name        TEXT,
      set_code        TEXT,
      number          TEXT,
      total           TEXT,
      rarity          TEXT,
      foil            INTEGER NOT NULL DEFAULT 0,
      edition         TEXT,
      language        TEXT,
      condition       TEXT,
      condition_hints TEXT,
      confidence      TEXT,
      identify_raw    TEXT,

      -- pricing (from Pokemon TCG API)
      tcg_id          TEXT,
      tcg_market      REAL,
      tcg_low         REAL,
      tcg_mid         REAL,
      tcg_high        REAL,
      tcg_url         TEXT,
      cm_trend        REAL,
      cm_avg30        REAL,
      cm_low          REAL,
      cm_url          TEXT,
      variant         TEXT,
      pricing_raw     TEXT,

      -- user metadata
      user_price      REAL,         -- what the user plans to list at
      notes           TEXT,
      tags            TEXT,         -- comma-separated for now

      -- listing state
      listing_id      TEXT,         -- eBay item id once listed
      listing_url     TEXT,
      listing_status  TEXT,         -- draft | listed | sold | removed

      -- image URIs (local file:// paths)
      front_image     TEXT,
      back_image      TEXT,
      ref_image_url   TEXT,         -- canonical card image from TCG API
      thumb_uri       TEXT,         -- the image we surface in the list

      -- sync state
      sync_status     TEXT NOT NULL DEFAULT 'local',  -- local | syncing | synced | dirty
      synced_at       TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_cards_captured_at ON cards(captured_at DESC);
    CREATE INDEX IF NOT EXISTS idx_cards_name ON cards(name);
    CREATE INDEX IF NOT EXISTS idx_cards_listing_status ON cards(listing_status);
    CREATE INDEX IF NOT EXISTS idx_cards_sync_status ON cards(sync_status);
  `);
}

// ---------------------------------------------------------------------------
// Domain shape — what callers see / pass in. SQLite stores ints for booleans;
// the helpers below normalize that boundary.

export interface Card {
  id: string;
  captured_at: string;
  updated_at: string;

  name: string | null;
  set_name: string | null;
  set_code: string | null;
  number: string | null;
  total: string | null;
  rarity: string | null;
  foil: boolean;
  edition: string | null;
  language: string | null;
  condition: string | null;
  condition_hints: string | null;
  confidence: 'low' | 'medium' | 'high' | null;

  tcg_id: string | null;
  tcg_market: number | null;
  tcg_low: number | null;
  tcg_mid: number | null;
  tcg_high: number | null;
  tcg_url: string | null;
  cm_trend: number | null;
  cm_avg30: number | null;
  cm_low: number | null;
  cm_url: string | null;
  variant: string | null;

  user_price: number | null;
  notes: string | null;
  tags: string | null;

  listing_id: string | null;
  listing_url: string | null;
  listing_status: 'draft' | 'listed' | 'sold' | 'removed' | null;

  front_image: string | null;
  back_image: string | null;
  ref_image_url: string | null;
  thumb_uri: string | null;

  sync_status: 'local' | 'syncing' | 'synced' | 'dirty';
  synced_at: string | null;
}

type Row = Record<string, any>;

function rowToCard(r: Row): Card {
  return {
    ...r,
    foil: !!r.foil,
  } as Card;
}

export interface CardInput extends Partial<Omit<Card, 'id' | 'captured_at' | 'updated_at' | 'sync_status'>> {
  id?: string;
}

export async function insertCard(input: CardInput): Promise<Card> {
  const db = await getDb();
  const now = new Date().toISOString();
  const id = input.id ?? cardId();
  await db.runAsync(
    `INSERT INTO cards (
      id, captured_at, updated_at,
      name, set_name, set_code, number, total, rarity, foil, edition, language,
      condition, condition_hints, confidence, identify_raw,
      tcg_id, tcg_market, tcg_low, tcg_mid, tcg_high, tcg_url,
      cm_trend, cm_avg30, cm_low, cm_url, variant, pricing_raw,
      user_price, notes, tags,
      listing_id, listing_url, listing_status,
      front_image, back_image, ref_image_url, thumb_uri,
      sync_status, synced_at
    ) VALUES (
      ?, ?, ?,
      ?, ?, ?, ?, ?, ?, ?, ?, ?,
      ?, ?, ?, ?,
      ?, ?, ?, ?, ?, ?,
      ?, ?, ?, ?, ?, ?,
      ?, ?, ?,
      ?, ?, ?,
      ?, ?, ?, ?,
      ?, ?
    )`,
    [
      id, now, now,
      input.name ?? null, input.set_name ?? null, input.set_code ?? null, input.number ?? null, input.total ?? null, input.rarity ?? null, input.foil ? 1 : 0, input.edition ?? null, input.language ?? null,
      input.condition ?? null, input.condition_hints ?? null, input.confidence ?? null, (input as any).identify_raw ?? null,
      input.tcg_id ?? null, input.tcg_market ?? null, input.tcg_low ?? null, input.tcg_mid ?? null, input.tcg_high ?? null, input.tcg_url ?? null,
      input.cm_trend ?? null, input.cm_avg30 ?? null, input.cm_low ?? null, input.cm_url ?? null, input.variant ?? null, (input as any).pricing_raw ?? null,
      input.user_price ?? null, input.notes ?? null, input.tags ?? null,
      input.listing_id ?? null, input.listing_url ?? null, input.listing_status ?? null,
      input.front_image ?? null, input.back_image ?? null, input.ref_image_url ?? null, input.thumb_uri ?? null,
      'local', null,
    ],
  );
  return (await getCard(id))!;
}

export async function getCard(id: string): Promise<Card | null> {
  const db = await getDb();
  const row = await db.getFirstAsync<Row>('SELECT * FROM cards WHERE id = ?', [id]);
  return row ? rowToCard(row) : null;
}

export async function listCards(opts: { search?: string; limit?: number; status?: Card['listing_status']; foilOnly?: boolean } = {}): Promise<Card[]> {
  const db = await getDb();
  const where: string[] = [];
  const args: any[] = [];
  if (opts.search) {
    const q = `%${opts.search.toLowerCase()}%`;
    where.push('(LOWER(name) LIKE ? OR LOWER(set_name) LIKE ? OR LOWER(number) LIKE ? OR LOWER(tags) LIKE ?)');
    args.push(q, q, q, q);
  }
  if (opts.status) { where.push('listing_status = ?'); args.push(opts.status); }
  if (opts.foilOnly) { where.push('foil = 1'); }
  const whereSql = where.length ? `WHERE ${where.join(' AND ')}` : '';
  const limitSql = opts.limit ? `LIMIT ${opts.limit}` : '';
  const rows = await db.getAllAsync<Row>(`SELECT * FROM cards ${whereSql} ORDER BY captured_at DESC ${limitSql}`, args);
  return rows.map(rowToCard);
}

export async function updateCard(id: string, patch: Partial<Card>): Promise<Card | null> {
  const db = await getDb();
  const fields = Object.keys(patch).filter((k) => k !== 'id' && k !== 'captured_at');
  if (!fields.length) return getCard(id);
  const set = fields.map((f) => `${f} = ?`).join(', ');
  const args = fields.map((f) => {
    const v = (patch as any)[f];
    if (typeof v === 'boolean') return v ? 1 : 0;
    return v;
  });
  args.push(new Date().toISOString());
  args.push(id);
  await db.runAsync(`UPDATE cards SET ${set}, updated_at = ?, sync_status = 'dirty' WHERE id = ?`, args);
  return getCard(id);
}

export async function deleteCard(id: string): Promise<void> {
  const db = await getDb();
  await db.runAsync('DELETE FROM cards WHERE id = ?', [id]);
}

export async function countCards(): Promise<{ total: number; listed: number; drafts: number; portfolioValue: number }> {
  const db = await getDb();
  const r = await db.getFirstAsync<Row>(`
    SELECT
      COUNT(*) as total,
      SUM(CASE WHEN listing_status = 'listed' THEN 1 ELSE 0 END) as listed,
      SUM(CASE WHEN listing_status = 'draft' OR listing_status IS NULL THEN 1 ELSE 0 END) as drafts,
      COALESCE(SUM(COALESCE(user_price, tcg_market, 0)), 0) as portfolioValue
    FROM cards
  `);
  return {
    total: r?.total ?? 0,
    listed: r?.listed ?? 0,
    drafts: r?.drafts ?? 0,
    portfolioValue: r?.portfolioValue ?? 0,
  };
}

function cardId(): string {
  return 'card_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 8);
}
