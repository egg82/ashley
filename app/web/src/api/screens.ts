// A page's report of whether it is in the foreground (`session/screen.ts` makes them).
import { ApiError } from './client';

async function reportScreen(path: '/api/screens/visibility' | '/api/kiosk/screen', screen: string,
                            visible: boolean): Promise<void> {
  const response = await fetch(path, {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ screen, visible }),
  });
  if (response.status !== 204) throw new ApiError(response.status, `POST ${path}`);
}

/** Says whether this page, the signed-in person's, is in the foreground, for the screen opened under `screen`. */
export function reportVisibility(screen: string, visible: boolean): Promise<void> {
  return reportScreen('/api/screens/visibility', screen, visible);
}

/** `reportVisibility` for the paired kiosk, as its device. */
export function reportKioskVisibility(screen: string, visible: boolean): Promise<void> {
  return reportScreen('/api/kiosk/screen', screen, visible);
}
