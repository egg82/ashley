// Whether the room is on a phone's width, where the flow picture gives way to a ranked list.
import { useEffect, useState } from 'preact/hooks';

const QUERY = '(max-width: 720px)';

export function useNarrow(): boolean {
  const [narrow, setNarrow] = useState(() => matchMedia(QUERY).matches);
  useEffect(() => {
    const q = matchMedia(QUERY);
    const on = () => setNarrow(q.matches);
    q.addEventListener('change', on);
    return () => q.removeEventListener('change', on);
  }, []);
  return narrow;
}
