/** How far a card is dragged sideways, in pixels, before letting go sends it away. */
export const SWIPE_PX = 96;

/** Whether a drag of `dx` pixels is a swipe away. */
export function swiped(dx: number): boolean {
  return Math.abs(dx) >= SWIPE_PX;
}
