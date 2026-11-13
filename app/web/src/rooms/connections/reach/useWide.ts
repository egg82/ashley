// Whether the screen is wide enough for the map; a phone is not, and gets the summary alone.
import { useEffect, useState } from 'preact/hooks';

const WIDE = '(min-width: 900px)';

export function useWide(): boolean {
  const [wide, setWide] = useState(() => matchMedia(WIDE).matches);
  useEffect(() => {
    const query = matchMedia(WIDE);
    const on = () => setWide(query.matches);
    query.addEventListener('change', on);
    return () => query.removeEventListener('change', on);
  }, []);
  return wide;
}
