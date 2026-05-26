/**
 * eBay Trading API client — OAuth refresh, picture upload, AddFixedPriceItem.
 *
 * Mirrors the Python pipeline in ../../promote.py / ../../repricing_agent.py:
 *   - OAuth refresh via identity/v1/oauth2/token
 *   - Trading API calls posted to https://api.ebay.com/ws/api.dll
 *   - SiteID 0 (eBay US), CompatibilityLevel 967
 *
 * IMPORTANT: this hits PRODUCTION. The caller is expected to put a
 * confirmation in front of createListing().
 */
import * as FileSystem from 'expo-file-system/legacy';

import type { Card } from '../db';
import { getEbayCredentials, type EbayCredentials } from '../settings';

// ---------------------------------------------------------------------------
// Constants

const OAUTH_URL    = 'https://api.ebay.com/identity/v1/oauth2/token';
const TRADING_URL  = 'https://api.ebay.com/ws/api.dll';
const COMPAT_LEVEL = '967';
const SITE_ID_US   = '0';

// Scopes needed for selling. Picture upload + AddFixedPriceItem use the
// classic Trading API which authenticates via the same user OAuth access
// token (passed in the SOAP body as <eBayAuthToken>).
const SCOPES = [
  'https://api.ebay.com/oauth/api_scope',
  'https://api.ebay.com/oauth/api_scope/sell.inventory',
  'https://api.ebay.com/oauth/api_scope/sell.account',
  'https://api.ebay.com/oauth/api_scope/sell.fulfillment',
  'https://api.ebay.com/oauth/api_scope/sell.marketing',
].join(' ');

// Condition mapping. eBay Trading Card Game category 183454 accepts these.
// https://developer.ebay.com/devzone/finding/CallRef/Enums/conditionIdList.html
export const CONDITION_OPTIONS = [
  { label: 'Near Mint',  ebay_id: '1000', hint: 'Brand-new / sealed-grade' },
  { label: 'Excellent',  ebay_id: '2750', hint: 'Like new, no wear' },
  { label: 'Good',       ebay_id: '4000', hint: 'Minor edge / surface wear' },
  { label: 'Light Play', ebay_id: '5000', hint: 'Visible play wear' },
  { label: 'Heavy Play', ebay_id: '6000', hint: 'Significant wear' },
  { label: 'Poor',       ebay_id: '7000', hint: 'Damaged but identifiable' },
] as const;

export type ConditionLabel = (typeof CONDITION_OPTIONS)[number]['label'];

export const DURATIONS = [
  { label: '7 days',  value: 'Days_7'  },
  { label: '10 days', value: 'Days_10' },
  { label: '30 days', value: 'Days_30' },
  { label: 'GTC (Good Til Cancelled)', value: 'GTC' },
] as const;

export type DurationValue = (typeof DURATIONS)[number]['value'];

// ---------------------------------------------------------------------------
// OAuth — refresh-token grant. Cache the access token in memory for ~1h.

interface TokenCache {
  token: string;
  expires_at: number; // epoch ms
}

let _tokenCache: TokenCache | null = null;

export class EbayAuthError extends Error {
  constructor(message: string, public status?: number, public body?: string) {
    super(message);
    this.name = 'EbayAuthError';
  }
}

export class EbayApiError extends Error {
  constructor(message: string, public code?: string, public longMessage?: string) {
    super(message);
    this.name = 'EbayApiError';
  }
}

function b64encode(s: string): string {
  // React Native (Hermes) ships `global.btoa` for ASCII strings, which is all
  // we need — client_id:client_secret is ASCII.
  // eslint-disable-next-line no-undef
  if (typeof (global as any).btoa === 'function') return (global as any).btoa(s);
  // Fallback (should not be reached on RN, but kept for safety in web tests).
  const buf: any = (global as any).Buffer;
  if (buf) return buf.from(s, 'utf-8').toString('base64');
  throw new Error('No base64 encoder available');
}

/**
 * Fetch (or refresh) a user OAuth access token.
 *
 * Pass `preloadedCreds` when the caller already read `getEbayCredentials()`
 * — avoids a redundant AsyncStorage round-trip on the hot path. `force=true`
 * bypasses the in-memory cache and runs the refresh-token grant unconditionally.
 */
export async function getAccessToken(
  force = false,
  preloadedCreds?: EbayCredentials,
): Promise<string> {
  if (!force && _tokenCache && _tokenCache.expires_at > Date.now() + 60_000) {
    return _tokenCache.token;
  }
  const creds = preloadedCreds ?? await getEbayCredentials();
  if (!creds) {
    throw new EbayAuthError(
      'No eBay credentials configured. Add your App ID, Cert ID, and refresh token in Settings.',
    );
  }
  const basic = b64encode(`${creds.client_id}:${creds.client_secret}`);
  const body =
    'grant_type=refresh_token' +
    '&refresh_token=' + encodeURIComponent(creds.refresh_token) +
    '&scope=' + encodeURIComponent(SCOPES);

  const res = await fetch(OAUTH_URL, {
    method: 'POST',
    headers: {
      'Authorization': `Basic ${basic}`,
      'Content-Type':  'application/x-www-form-urlencoded',
    },
    body,
  });
  const text = await res.text();
  if (!res.ok) {
    throw new EbayAuthError(
      `eBay OAuth failed (${res.status})`,
      res.status,
      text.slice(0, 400),
    );
  }
  let json: any;
  try { json = JSON.parse(text); } catch {
    throw new EbayAuthError('OAuth returned non-JSON body', res.status, text.slice(0, 400));
  }
  const token = json.access_token as string | undefined;
  const expiresIn = (json.expires_in as number | undefined) ?? 7200;
  if (!token) throw new EbayAuthError('OAuth response missing access_token', res.status, text.slice(0, 400));

  _tokenCache = {
    token,
    expires_at: Date.now() + (expiresIn - 60) * 1000, // refresh 60s early
  };
  return token;
}

export function clearTokenCache() {
  _tokenCache = null;
}

// ---------------------------------------------------------------------------
// Trading API helpers

/**
 * Build the Trading API request headers.
 *
 * eBay has signaled since 2024 that the legacy app-credentials triad
 * (X-EBAY-API-APP-NAME / DEV-NAME / CERT-NAME) plus the SOAP-body
 * `<RequesterCredentials><eBayAuthToken>` path is on a deprecation track in
 * favor of the IAF (Identity Auth Framework) header: a single user OAuth
 * access token sent in `X-EBAY-API-IAF-TOKEN`. We send both for now so the
 * call works on any eBay-side rollout state — the legacy headers can be
 * dropped once IAF is verified end-to-end in prod.
 */
export function tradingHeaders(
  callName: string,
  creds: EbayCredentials,
  accessToken?: string,
): Record<string, string> {
  const headers: Record<string, string> = {
    'X-EBAY-API-SITEID':              SITE_ID_US,
    'X-EBAY-API-COMPATIBILITY-LEVEL': COMPAT_LEVEL,
    'X-EBAY-API-CALL-NAME':           callName,
    'X-EBAY-API-APP-NAME':            creds.client_id,
    'X-EBAY-API-DEV-NAME':            creds.dev_id ?? '',
    'X-EBAY-API-CERT-NAME':           creds.client_secret,
    'Content-Type':                   'text/xml',
  };
  if (accessToken) {
    headers['X-EBAY-API-IAF-TOKEN'] = accessToken;
  }
  return headers;
}

// Minimal XML escaper for user-supplied text fields.
export function xmlEscape(s: string | null | undefined): string {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

export const NS = 'urn:ebay:apis:eBLBaseComponents';
export const TRADING_ENDPOINT = TRADING_URL;

/**
 * Very small XML "find first tag" helper. The Trading API XML is shallow and
 * we only ever need a handful of fields, so we skip a real parser.
 */
export function findTag(xml: string, tag: string): string | null {
  const re = new RegExp(`<${tag}[^>]*>([\\s\\S]*?)<\\/${tag}>`, 'i');
  const m = xml.match(re);
  return m ? m[1].trim() : null;
}

export function findAllTags(xml: string, tag: string): string[] {
  const re = new RegExp(`<${tag}[^>]*>([\\s\\S]*?)<\\/${tag}>`, 'gi');
  const out: string[] = [];
  let m: RegExpExecArray | null;
  while ((m = re.exec(xml)) !== null) out.push(m[1].trim());
  return out;
}

/**
 * Depth-aware tag lookup. The default `findTag()` picks the *first*
 * occurrence of a tag anywhere in the document, which breaks for
 * multi-variation items (`<Quantity>` exists both inside `<Variation>` and at
 * the item level — the variation copy wins and you read the wrong quantity).
 *
 * `findTagAtDepth(xml, tag, parentTag)` scopes the search to the first
 * `<parentTag>...</parentTag>` block when supplied, or — if `parentTag` is
 * `null` — strips out every `<excludeIn>...</excludeIn>` block first and then
 * searches the remainder. Pass `excludeIn` to skip nested children, pass
 * `parentTag` to anchor on a wrapper.
 */
export function findTagAtDepth(
  xml: string,
  tag: string,
  opts: { parentTag?: string; excludeIn?: string } = {},
): string | null {
  let scope = xml;
  if (opts.parentTag) {
    const block = findTag(xml, opts.parentTag);
    if (block == null) return null;
    scope = block;
  }
  if (opts.excludeIn) {
    const stripRe = new RegExp(
      `<${opts.excludeIn}[^>]*>[\\s\\S]*?<\\/${opts.excludeIn}>`,
      'gi',
    );
    scope = scope.replace(stripRe, '');
  }
  return findTag(scope, tag);
}

/**
 * Parse the AddFixedPriceItem <Fees> block. eBay nests the amount inside the
 * outer wrapper using the same tag name:
 *   <Fees><Fee><Name>InsertionFee</Name><Fee currencyID="USD">0.30</Fee></Fee>...</Fees>
 * The inner amount-bearing <Fee> always carries a currencyID attribute, so
 * anchor on that to avoid summing wrapper bodies.
 */
export function parseFeesTotal(xml: string): number | null {
  const feesBlocks = findAllTags(xml, 'Fees');
  if (!feesBlocks.length) return null;
  const re = /<Fee\s+[^>]*currencyID="[^"]*"[^>]*>([\s\S]*?)<\/Fee>/gi;
  let total = 0;
  let matched = false;
  let m: RegExpExecArray | null;
  while ((m = re.exec(feesBlocks[0])) !== null) {
    const n = parseFloat(m[1].trim());
    if (Number.isFinite(n)) {
      total += n;
      matched = true;
    }
  }
  return matched ? total : 0;
}

export interface EbayErrorInfo {
  code: string;
  short: string;
  long: string;
  severity: string;
}

export function parseErrors(xml: string): EbayErrorInfo[] {
  const blocks = findAllTags(xml, 'Errors');
  return blocks.map((b) => ({
    code:     findTag(b, 'ErrorCode') ?? '',
    short:    findTag(b, 'ShortMessage') ?? '',
    long:     findTag(b, 'LongMessage') ?? '',
    severity: findTag(b, 'SeverityCode') ?? '',
  }));
}

/**
 * eBay returns `200 OK` + `<Ack>Failure</Ack>` for token-expiry errors — it
 * does *not* surface HTTP 401. The error codes vary across endpoints (932,
 * 16110, 21916984 are the most common); messaging isn't stable, so we stay
 * conservative: a positive match also requires either a known code or
 * `ErrorClassification=RequestError` with the long message mentioning
 * "token". On a hit we drop the cached access token so the next call
 * re-runs the refresh-token grant. Returns true when the cache was cleared.
 */
export function maybeClearStaleToken(rawXml: string, errs: EbayErrorInfo[]): boolean {
  const tokenCodes = new Set(['932', '16110', '21916984']);
  for (const e of errs) {
    if (tokenCodes.has(e.code)) {
      clearTokenCache();
      return true;
    }
  }
  const errorBlocks = findAllTags(rawXml, 'Errors');
  for (const block of errorBlocks) {
    const cls = (findTag(block, 'ErrorClassification') ?? '').toLowerCase();
    const long = (findTag(block, 'LongMessage') ?? '').toLowerCase();
    if (cls === 'requesterror' && long.includes('token')) {
      clearTokenCache();
      return true;
    }
  }
  return false;
}

// ---------------------------------------------------------------------------
// Picture Service — upload a local file to eBay's image host.
//
// UploadSiteHostedPictures is a multipart-form request: the first part is the
// XML envelope; the second part is the binary image bytes. The response
// contains <FullURL> which we then reference in AddFixedPriceItem.
//
// React Native's FormData can carry { uri, name, type } objects so we don't
// need to read the file into memory.

export interface UploadImageResult {
  full_url: string;
  picture_set_member_urls: string[]; // multiple sizes returned by eBay
}

export async function uploadImage(localUri: string): Promise<UploadImageResult> {
  const creds = await getEbayCredentials();
  if (!creds) throw new EbayAuthError('No eBay credentials configured.');
  const token = await getAccessToken();

  // Validate file exists. expo-file-system file:// URIs are what we use.
  const info = await FileSystem.getInfoAsync(localUri);
  if (!info.exists) throw new Error(`Image file not found: ${localUri}`);

  const xmlEnvelope = `<?xml version="1.0" encoding="utf-8"?>
<UploadSiteHostedPicturesRequest xmlns="${NS}">
  <RequesterCredentials><eBayAuthToken>${xmlEscape(token)}</eBayAuthToken></RequesterCredentials>
  <PictureName>harpua-scan</PictureName>
  <PictureSet>Standard</PictureSet>
</UploadSiteHostedPicturesRequest>`;

  const form = new FormData();
  // Part 1: the XML envelope. eBay expects this part to be named "XML
  // Payload" with the Trading XML as the value.
  form.append('XML Payload', xmlEnvelope);
  // Part 2: the binary image. The field name doesn't matter to eBay; it
  // picks up whichever non-XML part it finds.
  form.append('image', {
    uri: localUri,
    name: 'image.jpg',
    type: 'image/jpeg',
  } as any);

  const res = await fetch(TRADING_URL, {
    method: 'POST',
    headers: tradingHeaders('UploadSiteHostedPictures', creds, token),
    body: form as any,
  });
  const text = await res.text();
  if (!res.ok) {
    throw new EbayApiError(
      `Picture upload HTTP ${res.status}`,
      String(res.status),
      text.slice(0, 400),
    );
  }
  const ack = findTag(text, 'Ack');
  if (ack !== 'Success' && ack !== 'Warning') {
    const errs = parseErrors(text);
    const first = errs[0];
    throw new EbayApiError(
      first?.short || 'Picture upload failed',
      first?.code,
      first?.long || text.slice(0, 400),
    );
  }
  const fullUrl = findTag(text, 'FullURL');
  if (!fullUrl) throw new EbayApiError('Picture upload returned no FullURL', undefined, text.slice(0, 400));
  return {
    full_url: fullUrl,
    picture_set_member_urls: findAllTags(text, 'MemberURL'),
  };
}

// ---------------------------------------------------------------------------
// AddFixedPriceItem

export interface ListingOptions {
  title: string;
  description?: string;
  price: number;
  quantity: number;
  condition_label: ConditionLabel;
  duration: DurationValue;
  free_combined_shipping: boolean;
  /** eBay-hosted image URLs (from uploadImage). Pass an empty array to list without photos. */
  picture_urls: string[];
  /** eBay primary category. Defaults to "Pokémon Individual Cards" (183454). */
  category_id?: string;
}

export interface CreateListingResult {
  item_id: string;
  view_url: string;
  fees_total?: number | null;
  warnings: EbayErrorInfo[];
}

const DEFAULT_CATEGORY_ID = '183454'; // Pokémon TCG Individual Cards

function conditionIdFor(label: ConditionLabel): string {
  const opt = CONDITION_OPTIONS.find((o) => o.label === label);
  return opt?.ebay_id ?? '1000';
}

function buildDescription(card: Card, opts: ListingOptions): string {
  if (opts.description && opts.description.trim()) return opts.description;
  const lines: string[] = [];
  lines.push(`<h2>${xmlEscape(opts.title)}</h2>`);
  const meta: string[] = [];
  if (card.set_name) meta.push(`Set: ${xmlEscape(card.set_name)}`);
  if (card.number)   meta.push(`Number: ${xmlEscape(card.number)}`);
  if (card.rarity)   meta.push(`Rarity: ${xmlEscape(card.rarity)}`);
  if (card.foil)     meta.push('Holographic foil');
  if (meta.length) lines.push('<p>' + meta.join(' &middot; ') + '</p>');
  lines.push(`<p>Condition: ${xmlEscape(opts.condition_label)}</p>`);
  if (card.condition_hints) lines.push(`<p><em>${xmlEscape(card.condition_hints)}</em></p>`);
  if (card.notes) lines.push(`<p>${xmlEscape(card.notes)}</p>`);
  lines.push('<p>Ships in a top-loader with team-bag protection. Combined shipping available on multiple purchases.</p>');
  return lines.join('\n');
}

function buildAddFixedPriceItemXml(token: string, card: Card, opts: ListingOptions): string {
  const categoryId = opts.category_id ?? DEFAULT_CATEGORY_ID;
  const condId = conditionIdFor(opts.condition_label);
  const desc = buildDescription(card, opts).replace(/]]>/g, ']]]]><![CDATA[>');

  const pictureBlock =
    opts.picture_urls.length > 0
      ? `<PictureDetails>${opts.picture_urls.map((u) => `<PictureURL>${xmlEscape(u)}</PictureURL>`).join('')}</PictureDetails>`
      : '';

  // Shipping: USPS Ground Advantage for combined orders, free shipping when
  // the toggle is on. Mirrors the store policy in promote.py listings.
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
      <CalculatedShippingDiscount>
        <DiscountProfileID>0</DiscountProfileID>
      </CalculatedShippingDiscount>
    </ShippingDetails>`;

  const returnPolicy = `
    <ReturnPolicy>
      <ReturnsAcceptedOption>ReturnsAccepted</ReturnsAcceptedOption>
      <ReturnsWithinOption>Days_30</ReturnsWithinOption>
      <RefundOption>MoneyBack</RefundOption>
      <ShippingCostPaidByOption>Buyer</ShippingCostPaidByOption>
    </ReturnPolicy>`;

  // The `<RequesterCredentials>` block duplicates what we now send in the
  // `X-EBAY-API-IAF-TOKEN` header. Keep it for now as belt + suspenders;
  // remove once IAF-only is verified end-to-end in prod.
  return `<?xml version="1.0" encoding="utf-8"?>
<AddFixedPriceItemRequest xmlns="${NS}">
  <RequesterCredentials><eBayAuthToken>${xmlEscape(token)}</eBayAuthToken></RequesterCredentials>
  <Item>
    <Title>${xmlEscape(opts.title.slice(0, 80))}</Title>
    <Description><![CDATA[${desc}]]></Description>
    <PrimaryCategory><CategoryID>${categoryId}</CategoryID></PrimaryCategory>
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
    ${pictureBlock}
    ${shippingService}
    ${returnPolicy}
  </Item>
</AddFixedPriceItemRequest>`;
}

export async function createListing(card: Card, opts: ListingOptions): Promise<CreateListingResult> {
  const creds = await getEbayCredentials();
  if (!creds) throw new EbayAuthError('No eBay credentials configured.');
  const token = await getAccessToken();

  const xml = buildAddFixedPriceItemXml(token, card, opts);
  const res = await fetch(TRADING_URL, {
    method: 'POST',
    headers: tradingHeaders('AddFixedPriceItem', creds, token),
    body: xml,
  });
  const text = await res.text();
  if (!res.ok) {
    throw new EbayApiError(
      `AddFixedPriceItem HTTP ${res.status}`,
      String(res.status),
      text.slice(0, 600),
    );
  }
  const ack = findTag(text, 'Ack') ?? '';
  const errs = parseErrors(text);
  if (ack !== 'Success' && ack !== 'Warning') {
    const first = errs[0];
    throw new EbayApiError(
      first?.short || 'eBay rejected the listing',
      first?.code,
      first?.long || text.slice(0, 600),
    );
  }
  const itemId = findTag(text, 'ItemID');
  if (!itemId) {
    throw new EbayApiError('eBay accepted the call but returned no ItemID', undefined, text.slice(0, 600));
  }
  const feesTotal = parseFeesTotal(text);
  return {
    item_id: itemId,
    view_url: `https://www.ebay.com/itm/${itemId}`,
    fees_total: feesTotal,
    warnings: ack === 'Warning' ? errs : [],
  };
}
