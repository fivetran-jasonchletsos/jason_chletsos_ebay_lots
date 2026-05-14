/**
 * Image storage. Captures land in cache initially; on save we move them to
 * the permanent app document directory under cards/<id>/ so deleting a card
 * cleans up its assets in one shot.
 */
import * as FileSystem from 'expo-file-system/legacy';
import { manipulateAsync, SaveFormat } from 'expo-image-manipulator';

const CARDS_DIR = FileSystem.documentDirectory + 'cards/';

async function ensureDir(path: string) {
  const info = await FileSystem.getInfoAsync(path);
  if (!info.exists) await FileSystem.makeDirectoryAsync(path, { intermediates: true });
}

export async function ensureCardsDir() {
  await ensureDir(CARDS_DIR);
}

/**
 * Take a captured photo URI (from the camera, possibly in cache) and move
 * it to permanent storage. Also generates a thumbnail-quality version so
 * the inventory list stays smooth.
 */
export async function persistCardImages(cardId: string, frontUri: string, backUri?: string, quality: number = 0.85): Promise<{ front: string; back?: string; thumb: string }> {
  await ensureCardsDir();
  const dir = `${CARDS_DIR}${cardId}/`;
  await ensureDir(dir);

  // Full-size front
  const front = await processImage(frontUri, `${dir}front.jpg`, 1600, quality);
  // Thumbnail (for list view)
  const thumb = await processImage(frontUri, `${dir}thumb.jpg`, 400, 0.75);

  let back: string | undefined;
  if (backUri) back = await processImage(backUri, `${dir}back.jpg`, 1600, quality);

  return { front, back, thumb };
}

async function processImage(srcUri: string, destUri: string, maxDim: number, quality: number): Promise<string> {
  const result = await manipulateAsync(
    srcUri,
    [{ resize: { width: maxDim } }],
    { compress: quality, format: SaveFormat.JPEG },
  );
  await FileSystem.moveAsync({ from: result.uri, to: destUri });
  return destUri;
}

export async function deleteCardImages(cardId: string): Promise<void> {
  const dir = `${CARDS_DIR}${cardId}/`;
  try {
    await FileSystem.deleteAsync(dir, { idempotent: true });
  } catch (e) {
    console.warn('deleteCardImages', e);
  }
}
