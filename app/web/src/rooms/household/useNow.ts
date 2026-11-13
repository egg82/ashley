import { useEffect, useState } from 'preact/hooks';

/** The current time, read again every `every` ms. */
export function useNow(every: number): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), every);
    return () => window.clearInterval(timer);
  }, [every]);
  return now;
}
