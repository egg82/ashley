// How full the notebook page is, against what the API lets the profile hold.

export interface Pen {
  /** 0 to 1. */
  fraction: number;
  /** In the last tenth of the page, or past it. */
  near: boolean;
}

export function penOf(length: number, limit: number): Pen {
  return { fraction: limit > 0 ? Math.min(1, length / limit) : 1, near: limit > 0 ? length >= limit * 0.9 : true };
}
