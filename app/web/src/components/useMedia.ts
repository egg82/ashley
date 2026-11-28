// Whether a media query matches, kept current as the screen changes.
import { useEffect, useState } from 'preact/hooks';

/** Phone width: at or below it the Desk's columns give way to one. */
export const PHONE = '(max-width: 760px)';

export function useMedia(query: string): boolean {
  const [matches, setMatches] = useState(() => matchMedia(query).matches);
  useEffect(() => {
    const list = matchMedia(query);
    const on = () => setMatches(list.matches);
    on();
    list.addEventListener('change', on);
    return () => list.removeEventListener('change', on);
  }, [query]);
  return matches;
}
