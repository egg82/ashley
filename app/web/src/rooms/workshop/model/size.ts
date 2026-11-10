/** A file size as a person reads it: bytes below 1 KB, then KB, MB and GB to one decimal below ten. */
export function bytesText(bytes: number): string {
  if (bytes < 1000) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB'];
  let value = bytes / 1000;
  let unit = 0;
  while (value >= 1000 && unit < units.length - 1) {
    value /= 1000;
    unit += 1;
  }
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${units[unit]}`;
}

/** What a media type is called on a card: the part after the slash, upper-cased, with `plain` as `text`. */
export function typeText(mediaType: string): string {
  const sub = mediaType.split('/')[1] ?? mediaType;
  return sub === 'plain' ? 'TEXT' : sub.toUpperCase();
}
