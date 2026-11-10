// Whether the screen is at phone width: the breakpoint `workshop.css` collapses the grid to one column at.
import { useEffect, useState } from 'preact/hooks';

const QUERY = '(max-width: 760px)';

export function useNarrow(): boolean {
  const [narrow, setNarrow] = useState(() => matchMedia(QUERY).matches);
  useEffect(() => {
    const list = matchMedia(QUERY);
    const change = () => setNarrow(list.matches);
    change();
    list.addEventListener('change', change);
    return () => list.removeEventListener('change', change);
  }, []);
  return narrow;
}
