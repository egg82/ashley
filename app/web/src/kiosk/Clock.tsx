// This screen's clock and date, which the screen keeps itself, written as the household writes them.
import { useEffect, useState } from 'preact/hooks';
import { hour, locale } from '../household/format';

function useNow(everyMs: number): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), everyMs);
    return () => clearInterval(timer);
  }, [everyMs]);
  return now;
}

export function Clock() {
  const now = useNow(10_000);
  const time = now.toLocaleTimeString(locale(), { hour: hour(), minute: '2-digit' });
  const date = now.toLocaleDateString(locale(), { weekday: 'long', day: 'numeric', month: 'long' });
  return (
    <div class="k-clock k-drift">
      <time class="k-time">{time}</time>
      <span class="k-date">{date}</span>
    </div>
  );
}
