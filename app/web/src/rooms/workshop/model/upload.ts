// Adding files to the open bench, one at a time: each is a piece once the server has judged and kept it. What was
// not taken says why in the bench's notice, and the others still go.
import { signal } from '@preact/signals';
import { ApiError } from '../../../api/client';
import { uploadFile } from '../../../api/upload';
import { notice, refresh, type Outcome, type UploadWhy } from './bench';
import { unreachable } from './benches';

/** How many files are on their way to the open bench. */
export const uploading = signal(0);

const BY_STATUS: Record<number, UploadWhy | 'closed'> = { 410: 'closed', 413: 'too_large', 415: 'unsupported', 422: 'empty' };

async function one(bench: number, file: File): Promise<Outcome> {
  try {
    const got = await uploadFile(bench, file);
    if (got.status === 200 && 'applied' in got) return { ok: true, piece: got.applied.piece_id };
    if (got.status === 409 && 'refused' in got) return { ok: false, why: got.refused.reason };
    const why = BY_STATUS[got.status];
    return { ok: false, why: why ?? 'failed' };
  } catch (error) {
    return { ok: false, why: error instanceof ApiError || !unreachable(error) ? 'failed' : 'unreachable' };
  }
}

export async function uploadAll(bench: number, files: readonly File[]): Promise<void> {
  uploading.value += files.length;
  for (const file of files) {
    const outcome = await one(bench, file);
    uploading.value -= 1;
    notice.value = outcome.ok ? null : outcome;
    await refresh();
  }
}
