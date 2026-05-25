/**
 * Trading API client for managing existing listings and Best Offers.
 *
 *   - GetMyeBaySelling   -> list active seller items
 *   - GetItem            -> single listing detail (photos, title, price)
 *   - ReviseFixedPriceItem
 *       * replace PictureDetails (the #1 revenue lever — 128/128 active
 *         listings currently fail Cassini photo gates)
 *       * update StartPrice
 *       * update Title
 *   - GetBestOffers      -> open Best Offers across the seller's listings
 *   - RespondToBestOffer -> Accept / Decline / Counter
 *
 * Shares OAuth + XML helpers with ./ebay.ts.
 */
import {
  EbayApiError,
  EbayAuthError,
  type EbayErrorInfo,
  findAllTags,
  findTag,
  getAccessToken,
  NS,
  parseErrors,
  TRADING_ENDPOINT,
  tradingHeaders,
  xmlEscape,
} from './ebay';
import { getEbayCredentials } from '../settings';

// ---------------------------------------------------------------------------
// Shared call wrapper

async function tradingCall(callName: string, body: string): Promise<string> {
  const creds = await getEbayCredentials();
  if (!creds) throw new EbayAuthError('No eBay credentials configured.');
  // Force a fresh token check so a stale one doesn't burn a request.
  await getAccessToken();
  const res = await fetch(TRADING_ENDPOINT, {
    method: 'POST',
    headers: tradingHeaders(callName, creds),
    body,
  });
  const text = await res.text();
  if (!res.ok) {
    throw new EbayApiError(
      `${callName} HTTP ${res.status}`,
      String(res.status),
      text.slice(0, 600),
    );
  }
  const ack = findTag(text, 'Ack') ?? '';
  if (ack !== 'Success' && ack !== 'Warning') {
    const errs = parseErrors(text);
    const first = errs[0];
    throw new EbayApiError(
      first?.short || `${callName} failed`,
      first?.code,
      first?.long || text.slice(0, 600),
    );
  }
  return text;
}

async function envelope(callName: string, inner: string): Promise<string> {
  const token = await getAccessToken();
  return `<?xml version="1.0" encoding="utf-8"?>
<${callName}Request xmlns="${NS}">
  <RequesterCredentials><eBayAuthToken>${xmlEscape(token)}</eBayAuthToken></RequesterCredentials>
  ${inner}
</${callName}Request>`;
}

// ---------------------------------------------------------------------------
// GetMyeBaySelling

export interface ListingSummary {
  item_id: string;
  title: string;
  price: number | null;
  currency: string;
  quantity: number;
  quantity_sold: number;
  watch_count: number | null;
  view_count: number | null;
  picture_url: string | null;        // gallery thumb
  picture_count: number;             // total photos on the listing (when reported)
  view_url: string;
  start_time: string | null;         // ISO
  time_left: string | null;          // eBay duration token e.g. "P29DT5H..."
  best_offer_count: number;
  listing_type: string;
}

/**
 * Returns active listings sorted by time left (newest first when sorting by
 * StartTime, but we want the seller to see what's about to expire — TimeLeft
 * ascending puts those at the top).
 */
export async function getMyListings(
  opts: { page?: number; perPage?: number } = {},
): Promise<{ listings: ListingSummary[]; total: number; pages: number; page: number }> {
  const page = Math.max(1, opts.page ?? 1);
  const perPage = Math.min(200, Math.max(25, opts.perPage ?? 100));

  const body = await envelope('GetMyeBaySelling', `
    <ActiveList>
      <Sort>TimeLeft</Sort>
      <Pagination>
        <EntriesPerPage>${perPage}</EntriesPerPage>
        <PageNumber>${page}</PageNumber>
      </Pagination>
      <Include>true</Include>
    </ActiveList>
    <DetailLevel>ReturnAll</DetailLevel>
  `);

  const xml = await tradingCall('GetMyeBaySelling', body);
  const activeBlock = findTag(xml, 'ActiveList') ?? xml;
  const items = findAllTags(activeBlock, 'Item').map(parseListingSummary).filter(Boolean) as ListingSummary[];
  const paginationResult = findTag(activeBlock, 'PaginationResult');
  const total = paginationResult ? parseInt(findTag(paginationResult, 'TotalNumberOfEntries') ?? '0', 10) || 0 : items.length;
  const pages = paginationResult ? parseInt(findTag(paginationResult, 'TotalNumberOfPages') ?? '1', 10) || 1 : 1;
  return { listings: items, total, pages, page };
}

function parseListingSummary(xml: string): ListingSummary | null {
  const item_id = findTag(xml, 'ItemID');
  if (!item_id) return null;
  const sellingStatus = findTag(xml, 'SellingStatus') ?? '';
  const listingDetails = findTag(xml, 'ListingDetails') ?? '';
  const pictureDetails = findTag(xml, 'PictureDetails') ?? '';
  const currentPrice = findTag(sellingStatus, 'CurrentPrice');
  return {
    item_id,
    title: findTag(xml, 'Title') ?? '(untitled)',
    price: currentPrice ? parseFloat(currentPrice) : null,
    currency: extractAttr(sellingStatus, 'CurrentPrice', 'currencyID') ?? 'USD',
    quantity: parseInt(findTag(xml, 'Quantity') ?? '1', 10) || 1,
    quantity_sold: parseInt(findTag(sellingStatus, 'QuantitySold') ?? '0', 10) || 0,
    watch_count: parseIntOrNull(findTag(xml, 'WatchCount')),
    view_count: parseIntOrNull(findTag(xml, 'HitCount')),
    picture_url: findTag(pictureDetails, 'GalleryURL') ?? findTag(pictureDetails, 'PictureURL'),
    picture_count: findAllTags(pictureDetails, 'PictureURL').length,
    view_url: findTag(listingDetails, 'ViewItemURL') ?? `https://www.ebay.com/itm/${item_id}`,
    start_time: findTag(listingDetails, 'StartTime'),
    time_left: findTag(xml, 'TimeLeft'),
    best_offer_count: parseInt(findTag(sellingStatus, 'BestOfferCount') ?? '0', 10) || 0,
    listing_type: findTag(xml, 'ListingType') ?? 'FixedPriceItem',
  };
}

function parseIntOrNull(s: string | null): number | null {
  if (s == null) return null;
  const n = parseInt(s, 10);
  return Number.isFinite(n) ? n : null;
}

function extractAttr(xml: string, tag: string, attr: string): string | null {
  const re = new RegExp(`<${tag}[^>]*\\b${attr}="([^"]*)"`, 'i');
  const m = xml.match(re);
  return m ? m[1] : null;
}

// ---------------------------------------------------------------------------
// GetItem — full detail for one listing

export interface ListingDetail {
  item_id: string;
  title: string;
  description_html: string | null;
  price: number | null;
  currency: string;
  quantity: number;
  quantity_available: number;
  quantity_sold: number;
  condition_id: string | null;
  condition_label: string | null;
  category_id: string | null;
  category_name: string | null;
  picture_urls: string[];           // ordered, includes the gallery first
  view_url: string;
  watch_count: number | null;
  view_count: number | null;
  best_offer_enabled: boolean;
  free_shipping: boolean;
  listing_type: string;
  start_time: string | null;
  time_left: string | null;
}

export async function getListing(itemId: string): Promise<ListingDetail> {
  if (!itemId) throw new Error('itemId required');
  const body = await envelope('GetItem', `
    <ItemID>${xmlEscape(itemId)}</ItemID>
    <DetailLevel>ReturnAll</DetailLevel>
    <IncludeWatchCount>true</IncludeWatchCount>
  `);
  const xml = await tradingCall('GetItem', body);
  const item = findTag(xml, 'Item') ?? xml;
  const sellingStatus = findTag(item, 'SellingStatus') ?? '';
  const listingDetails = findTag(item, 'ListingDetails') ?? '';
  const pictureDetails = findTag(item, 'PictureDetails') ?? '';
  const shippingDetails = findTag(item, 'ShippingDetails') ?? '';
  const primaryCategory = findTag(item, 'PrimaryCategory') ?? '';
  const currentPrice = findTag(sellingStatus, 'CurrentPrice') ?? findTag(item, 'StartPrice');

  // Picture URLs: PictureDetails > PictureURL has 0..N entries.
  let picture_urls = findAllTags(pictureDetails, 'PictureURL');
  const gallery = findTag(pictureDetails, 'GalleryURL');
  if (gallery && !picture_urls.includes(gallery)) picture_urls = [gallery, ...picture_urls];

  const shippingOption = findTag(shippingDetails, 'ShippingServiceOptions') ?? '';
  const freeShipFlag = findTag(shippingOption, 'FreeShipping') === 'true';

  return {
    item_id: findTag(item, 'ItemID') ?? itemId,
    title: findTag(item, 'Title') ?? '(untitled)',
    description_html: findTag(item, 'Description'),
    price: currentPrice ? parseFloat(currentPrice) : null,
    currency: extractAttr(sellingStatus, 'CurrentPrice', 'currencyID') ?? 'USD',
    quantity: parseInt(findTag(item, 'Quantity') ?? '1', 10) || 1,
    quantity_available: parseInt(findTag(sellingStatus, 'QuantityAvailable') ?? findTag(item, 'Quantity') ?? '1', 10) || 1,
    quantity_sold: parseInt(findTag(sellingStatus, 'QuantitySold') ?? '0', 10) || 0,
    condition_id: findTag(item, 'ConditionID'),
    condition_label: findTag(item, 'ConditionDisplayName'),
    category_id: findTag(primaryCategory, 'CategoryID'),
    category_name: findTag(primaryCategory, 'CategoryName'),
    picture_urls,
    view_url: findTag(listingDetails, 'ViewItemURL') ?? `https://www.ebay.com/itm/${itemId}`,
    watch_count: parseIntOrNull(findTag(item, 'WatchCount')),
    view_count: parseIntOrNull(findTag(item, 'HitCount')),
    best_offer_enabled: findTag(item, 'BestOfferEnabled') === 'true',
    free_shipping: freeShipFlag,
    listing_type: findTag(item, 'ListingType') ?? 'FixedPriceItem',
    start_time: findTag(listingDetails, 'StartTime'),
    time_left: findTag(item, 'TimeLeft'),
  };
}

// ---------------------------------------------------------------------------
// ReviseFixedPriceItem — partial updates

export interface ReviseResult {
  item_id: string;
  warnings: EbayErrorInfo[];
}

/**
 * Replace the entire picture gallery on a live listing.
 * Caller is expected to have already uploaded each local file via
 * `uploadImage()` from ./ebay.ts and pass the resulting eBay-hosted URLs.
 */
export async function revisePictures(itemId: string, pictureUrls: string[]): Promise<ReviseResult> {
  if (!itemId) throw new Error('itemId required');
  if (pictureUrls.length === 0) throw new Error('At least one picture URL is required');
  if (pictureUrls.length > 24) throw new Error('eBay allows max 24 pictures per listing');

  const pictureBlock = `<PictureDetails>${pictureUrls
    .map((u) => `<PictureURL>${xmlEscape(u)}</PictureURL>`)
    .join('')}</PictureDetails>`;

  const inner = `<Item>
    <ItemID>${xmlEscape(itemId)}</ItemID>
    ${pictureBlock}
  </Item>`;

  const body = await envelope('ReviseFixedPriceItem', inner);
  const xml = await tradingCall('ReviseFixedPriceItem', body);
  const ack = findTag(xml, 'Ack') ?? '';
  return {
    item_id: findTag(xml, 'ItemID') ?? itemId,
    warnings: ack === 'Warning' ? parseErrors(xml) : [],
  };
}

export async function revisePrice(itemId: string, price: number): Promise<ReviseResult> {
  if (!itemId) throw new Error('itemId required');
  if (!Number.isFinite(price) || price <= 0) throw new Error('price must be positive');
  const inner = `<Item>
    <ItemID>${xmlEscape(itemId)}</ItemID>
    <StartPrice>${price.toFixed(2)}</StartPrice>
  </Item>`;
  const body = await envelope('ReviseFixedPriceItem', inner);
  const xml = await tradingCall('ReviseFixedPriceItem', body);
  const ack = findTag(xml, 'Ack') ?? '';
  return {
    item_id: findTag(xml, 'ItemID') ?? itemId,
    warnings: ack === 'Warning' ? parseErrors(xml) : [],
  };
}

export async function reviseTitle(itemId: string, title: string): Promise<ReviseResult> {
  if (!itemId) throw new Error('itemId required');
  const t = title.trim().slice(0, 80);
  if (!t) throw new Error('title required');
  const inner = `<Item>
    <ItemID>${xmlEscape(itemId)}</ItemID>
    <Title>${xmlEscape(t)}</Title>
  </Item>`;
  const body = await envelope('ReviseFixedPriceItem', inner);
  const xml = await tradingCall('ReviseFixedPriceItem', body);
  const ack = findTag(xml, 'Ack') ?? '';
  return {
    item_id: findTag(xml, 'ItemID') ?? itemId,
    warnings: ack === 'Warning' ? parseErrors(xml) : [],
  };
}

// ---------------------------------------------------------------------------
// GetBestOffers

export interface BestOffer {
  best_offer_id: string;
  item_id: string;
  item_title: string;
  item_price: number | null;
  item_picture_url: string | null;
  buyer_user_id: string;
  buyer_message: string | null;
  offer_price: number;
  currency: string;
  quantity: number;
  expires_on: string | null;
  status: string;        // Pending | Accepted | Declined | Countered | Expired
  received_at: string | null;
}

export async function getBestOffers(): Promise<BestOffer[]> {
  // GetBestOffers without an ItemID returns offers across all listings.
  const body = await envelope('GetBestOffers', `
    <BestOfferStatus>Active</BestOfferStatus>
    <DetailLevel>ReturnAll</DetailLevel>
  `);
  const xml = await tradingCall('GetBestOffers', body);
  const out: BestOffer[] = [];
  const items = findAllTags(xml, 'Item');
  for (const itemBlock of items) {
    const item_id = findTag(itemBlock, 'ItemID') ?? '';
    const item_title = findTag(itemBlock, 'Title') ?? '(listing)';
    const item_price_raw = findTag(findTag(itemBlock, 'SellingStatus') ?? '', 'CurrentPrice');
    const item_price = item_price_raw ? parseFloat(item_price_raw) : null;
    const item_picture_url = findTag(findTag(itemBlock, 'PictureDetails') ?? '', 'GalleryURL')
      ?? findTag(findTag(itemBlock, 'PictureDetails') ?? '', 'PictureURL');
    const offers = findAllTags(itemBlock, 'BestOffer');
    for (const off of offers) {
      const status = findTag(off, 'Status') ?? 'Pending';
      if (status !== 'Pending') continue;
      const price = parseFloat(findTag(off, 'Price') ?? '0') || 0;
      const currency = extractAttr(off, 'Price', 'currencyID') ?? 'USD';
      out.push({
        best_offer_id: findTag(off, 'BestOfferID') ?? '',
        item_id,
        item_title,
        item_price,
        item_picture_url,
        buyer_user_id: findTag(findTag(off, 'Buyer') ?? '', 'UserID') ?? '(buyer)',
        buyer_message: findTag(off, 'BuyerMessage'),
        offer_price: price,
        currency,
        quantity: parseInt(findTag(off, 'Quantity') ?? '1', 10) || 1,
        expires_on: findTag(off, 'ExpirationTime'),
        status,
        received_at: findTag(off, 'ConvertedPrice') ? null : (findTag(off, 'ReceivedTime') ?? null),
      });
    }
  }
  return out;
}

// ---------------------------------------------------------------------------
// RespondToBestOffer

export type OfferAction = 'Accept' | 'Decline' | 'Counter';

export interface RespondOptions {
  item_id: string;
  best_offer_id: string;
  action: OfferAction;
  counter_price?: number;          // required when action === 'Counter'
  seller_response?: string;
}

// ---------------------------------------------------------------------------
// Generic (non-card) create-listing path.
//
// The card-specific createListing() in ./ebay.ts wraps a Card row from the
// local scanner DB. The quick-list flow lists arbitrary store inventory
// (sealed product, comics, retro games, etc.) where there is no Card, so we
// expose a parallel path that takes the full set of options directly.

export const GENERIC_CONDITIONS = [
  { label: 'New',                  ebay_id: '1000' },
  { label: 'New other',            ebay_id: '1500' },
  { label: 'Used — Excellent',     ebay_id: '4000' },
  { label: 'Used — Very Good',     ebay_id: '5000' },
  { label: 'Used — Good',          ebay_id: '6000' },
  { label: 'Used — Acceptable',    ebay_id: '7000' },
  { label: 'For parts / not working', ebay_id: '7000' },
] as const;

export type GenericConditionLabel = (typeof GENERIC_CONDITIONS)[number]['label'];

// Common harpua2001 store categories — short curated list keeps the picker
// fast on the field. Long-tail categories can fall back to "Other" with the
// category_id text field once added.
export const QUICK_LIST_CATEGORIES: { id: string; name: string }[] = [
  { id: '183454', name: 'Pokémon TCG Individual Cards' },
  { id: '183455', name: 'Pokémon TCG Sealed Booster Packs' },
  { id: '4189',   name: 'Pokémon TCG Sealed Booster Boxes' },
  { id: '218',    name: 'Sports Trading Cards — Singles' },
  { id: '215',    name: 'Sports Trading Cards — Sealed' },
  { id: '139973', name: 'Video Games' },
  { id: '171228', name: 'Video Game Consoles' },
];

export interface QuickListOptions {
  title: string;
  description: string;             // plain or HTML; we wrap with CDATA
  price: number;
  quantity: number;
  condition_label: GenericConditionLabel;
  category_id: string;
  duration: 'Days_7' | 'Days_10' | 'Days_30' | 'GTC';
  free_combined_shipping: boolean;
  picture_urls: string[];          // eBay-hosted URLs already (uploadImage first)
  best_offer_enabled: boolean;
}

export interface QuickListResult {
  item_id: string;
  view_url: string;
  fees_total: number | null;
  warnings: EbayErrorInfo[];
}

export async function createQuickListing(opts: QuickListOptions): Promise<QuickListResult> {
  const cond = GENERIC_CONDITIONS.find((c) => c.label === opts.condition_label);
  const condId = cond?.ebay_id ?? '1000';
  const pictureBlock = opts.picture_urls.length
    ? `<PictureDetails>${opts.picture_urls.map((u) => `<PictureURL>${xmlEscape(u)}</PictureURL>`).join('')}</PictureDetails>`
    : '';
  const shippingCost = opts.free_combined_shipping ? '0.00' : '4.99';
  const shippingService = `
    <ShippingDetails>
      <ShippingType>Flat</ShippingType>
      <ShippingServiceOptions>
        <ShippingServicePriority>1</ShippingServicePriority>
        <ShippingService>USPSGroundAdvantage</ShippingService>
        <ShippingServiceCost>${shippingCost}</ShippingServiceCost>
        <FreeShipping>${opts.free_combined_shipping ? 'true' : 'false'}</FreeShipping>
      </ShippingServiceOptions>
    </ShippingDetails>`;
  const returnPolicy = `
    <ReturnPolicy>
      <ReturnsAcceptedOption>ReturnsAccepted</ReturnsAcceptedOption>
      <ReturnsWithinOption>Days_30</ReturnsWithinOption>
      <RefundOption>MoneyBack</RefundOption>
      <ShippingCostPaidByOption>Buyer</ShippingCostPaidByOption>
    </ReturnPolicy>`;
  const bestOfferBlock = opts.best_offer_enabled
    ? `<BestOfferDetails><BestOfferEnabled>true</BestOfferEnabled></BestOfferDetails>`
    : '';

  const inner = `<Item>
    <Title>${xmlEscape(opts.title.slice(0, 80))}</Title>
    <Description><![CDATA[${opts.description}]]></Description>
    <PrimaryCategory><CategoryID>${xmlEscape(opts.category_id)}</CategoryID></PrimaryCategory>
    <StartPrice>${opts.price.toFixed(2)}</StartPrice>
    <ConditionID>${condId}</ConditionID>
    <Country>US</Country>
    <Currency>USD</Currency>
    <DispatchTimeMax>1</DispatchTimeMax>
    <ListingDuration>${opts.duration}</ListingDuration>
    <ListingType>FixedPriceItem</ListingType>
    <Quantity>${Math.max(1, Math.floor(opts.quantity))}</Quantity>
    <Location>United States</Location>
    <Site>US</Site>
    ${bestOfferBlock}
    ${pictureBlock}
    ${shippingService}
    ${returnPolicy}
  </Item>`;
  const body = await envelope('AddFixedPriceItem', inner);
  const xml = await tradingCall('AddFixedPriceItem', body);
  const itemId = findTag(xml, 'ItemID');
  if (!itemId) throw new EbayApiError('eBay accepted the call but returned no ItemID');
  const feesRaw = findAllTags(xml, 'Fees');
  let feesTotal: number | null = null;
  if (feesRaw.length) {
    const amounts = findAllTags(feesRaw[0], 'Fee').map((s) => parseFloat(s)).filter((n) => Number.isFinite(n));
    if (amounts.length) feesTotal = amounts.reduce((a, b) => a + b, 0);
  }
  const ack = findTag(xml, 'Ack') ?? '';
  return {
    item_id: itemId,
    view_url: `https://www.ebay.com/itm/${itemId}`,
    fees_total: feesTotal,
    warnings: ack === 'Warning' ? parseErrors(xml) : [],
  };
}

// ---------------------------------------------------------------------------
// RespondToBestOffer

export async function respondToBestOffer(opts: RespondOptions): Promise<void> {
  if (!opts.item_id || !opts.best_offer_id) throw new Error('item_id and best_offer_id required');
  if (opts.action === 'Counter' && (!Number.isFinite(opts.counter_price ?? NaN) || (opts.counter_price ?? 0) <= 0)) {
    throw new Error('counter_price required for Counter action');
  }
  const counterBlock = opts.action === 'Counter'
    ? `<CounterOfferPrice currencyID="USD">${(opts.counter_price as number).toFixed(2)}</CounterOfferPrice>`
    : '';
  const messageBlock = opts.seller_response
    ? `<SellerResponse>${xmlEscape(opts.seller_response)}</SellerResponse>`
    : '';
  const inner = `<ItemID>${xmlEscape(opts.item_id)}</ItemID>
    <BestOfferID>${xmlEscape(opts.best_offer_id)}</BestOfferID>
    <Action>${opts.action}</Action>
    ${counterBlock}
    ${messageBlock}`;
  const body = await envelope('RespondToBestOffer', inner);
  await tradingCall('RespondToBestOffer', body);
}
