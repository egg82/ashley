// Adding a file to a bench is the one write that is not JSON: the file's bytes are the body.
import type { CommandApplied, CommandRefused } from './types';

/** How an upload ended when the server did not take it as a piece: the status it answered with. */
export type Uploaded = { status: 200; applied: CommandApplied } | { status: 409; refused: CommandRefused } | { status: number };

/** Adds `file` to bench `id` as an image or file piece: its bytes are the body, its name and the type the browser
 * gave ride in headers (the name percent-encoded), never the URL. */
export async function uploadFile(id: number, file: File): Promise<Uploaded> {
  const response = await fetch(`/api/benches/${id}/files`, {
    method: 'POST',
    headers: { 'content-type': 'application/octet-stream', 'x-file-name': encodeURIComponent(file.name), 'x-file-type': file.type },
    body: file,
  });
  if (response.status === 200) return { status: 200, applied: (await response.json()) as CommandApplied };
  if (response.status === 409) return { status: 409, refused: (await response.json()) as CommandRefused };
  return { status: response.status };
}
