// The outside-actions route: what she did for the signed-in person with no OK.
import { answer } from './client';
import type { OutsideActionsResponse } from './types';

/** The person's outside actions, newest first, at most 100. */
export async function getOutsideActions(): Promise<OutsideActionsResponse> {
  return answer(await fetch('/api/outside-actions'), 200, 'GET /api/outside-actions');
}
