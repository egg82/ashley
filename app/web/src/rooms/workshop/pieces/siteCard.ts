import type { BenchPiece } from '../../../api/types';

/** Whether a site piece is shown as a link card instead of a frame: only when the server measured that the site
 *  refuses to be framed. Not measured yet, or not measurable (`frameable` null), is framed as ever, since the page
 *  cannot tell a refused frame from a slow one. */
export function showsCard(site: BenchPiece['site']): boolean {
  return site !== null && site.frameable === false;
}
