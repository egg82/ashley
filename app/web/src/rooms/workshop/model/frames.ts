// What a person types to add a framed piece (a `site` or `video`): one address, and for a video where it starts, made
// into the body the server checks (`ashley.workshop.embed`). The server judges the address; this only shapes the body.
import type { PieceKind } from '../../../api/types';

type Format = PieceKind['format'];

export function isFramed(format: Format): boolean {
  return format === 'site' || format === 'video';
}

/** A start typed as seconds, `m:ss` or `h:mm:ss`, in seconds; empty is 0; null when it is none of those. */
export function parseStart(text: string): number | null {
  const t = text.trim();
  if (!t) return 0;
  const parts = t.split(':');
  if (parts.length > 3 || !parts.every((p) => /^\d+$/.test(p))) return null;
  const nums = parts.map(Number);
  if (nums.slice(1).some((n) => n > 59)) return null;
  return nums.reduce((total, n) => total * 60 + n, 0);
}

/** The body of a framed piece: a site's address alone, a video's JSON object with `start` only when it is not 0. */
export function framedBody(format: Format, url: string, start: number): string {
  const address = url.trim();
  if (format !== 'video') return address;
  return JSON.stringify(start > 0 ? { url: address, start } : { url: address });
}
