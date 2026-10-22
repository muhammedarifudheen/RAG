import type { Attachment } from "@atlas/shared";

import { readAttachment } from "./api";
import type { StoredAttachment, StoredMessage } from "./chats";

export const MAX_FILES = 10;
const IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp", "image/gif"] as const;
type ImageType = (typeof IMAGE_TYPES)[number];
const MAX_IMAGE_SIDE = 1536;
const MAX_IMAGE_BYTES = 20_000_000;

// What goes along with one question, in all (the API's limits, with room to spare).
const SEND_TEXT_LIMIT = 380_000;
const SEND_IMAGES = 4;

export function isImage(file: File): boolean {
  return (IMAGE_TYPES as readonly string[]).includes(file.type);
}

/**
 * Reads a file for attaching. Images are scaled down in the browser and sent as
 * base64; anything else goes to the API, which returns its text (PDF, EPUB, HTML,
 * code, CSV…).
 */
export async function prepareAttachment(file: File): Promise<StoredAttachment> {
  if (isImage(file)) {
    if (file.size > MAX_IMAGE_BYTES) throw new Error(`${file.name} is larger than 20 MB.`);
    const { mime, data } = await shrinkImage(file);
    return { name: file.name, kind: "image", mime, data, size: file.size };
  }
  const read = await readAttachment(file);
  return {
    name: read.name,
    kind: "text",
    text: read.text,
    truncated: read.truncated,
    size: file.size,
  };
}

/** The image as base64 JPEG or PNG, at most MAX_IMAGE_SIDE pixels on its longer side. */
async function shrinkImage(file: File): Promise<{ mime: ImageType; data: string }> {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, MAX_IMAGE_SIDE / Math.max(bitmap.width, bitmap.height));
  // A small PNG or GIF is sent as it is (keeps transparency and sharp edges).
  if (scale === 1 && file.size < 1_500_000 && file.type !== "image/webp") {
    bitmap.close();
    return { mime: file.type as ImageType, data: await toBase64(file) };
  }
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext("2d")?.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  const url = canvas.toDataURL("image/jpeg", 0.86);
  return { mime: "image/jpeg", data: url.slice(url.indexOf(",") + 1) };
}

function toBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const url = String(reader.result);
      resolve(url.slice(url.indexOf(",") + 1));
    };
    reader.onerror = () => reject(reader.error ?? new Error("The file could not be read."));
    reader.readAsDataURL(blob);
  });
}

/** An attached image as something an <img> can show. */
export function imageSource(attachment: Attachment): string | null {
  return attachment.kind === "image" && attachment.data && attachment.mime
    ? `data:${attachment.mime};base64,${attachment.data}`
    : null;
}

/**
 * The files to send with a question: the new ones, then those attached earlier in
 * the conversation (newest first), so follow-ups can still refer to them, within
 * the limits on text and images.
 */
export function attachmentsToSend(
  earlier: StoredMessage[],
  current: StoredAttachment[],
): Attachment[] {
  const candidates: StoredAttachment[] = [...current];
  for (const message of [...earlier].reverse()) {
    if (message.role === "user" && message.attachments) candidates.push(...message.attachments);
  }
  const chosen: Attachment[] = [];
  let text = 0;
  let images = 0;
  for (const { size: _size, truncated: _truncated, ...attachment } of candidates) {
    if (attachment.kind === "image") {
      if (!attachment.data || images >= SEND_IMAGES) continue;
      images += 1;
    } else {
      const length = attachment.text?.length ?? 0;
      if (text + length > SEND_TEXT_LIMIT) continue;
      text += length;
    }
    chosen.push(attachment);
  }
  return chosen;
}

export function describeSize(bytes: number | undefined): string {
  if (!bytes) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
