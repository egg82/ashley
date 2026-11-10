// This screen's clock and date, which the screen keeps itself.
import { useEffect, useState } from 'preact/hooks';

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
  const time = now.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
  const date = now.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' });
  return (
    <div class="k-clock k-drift">
      <time class="k-time">{time}</time>
      <span class="k-date">{date}</span>
    </div>
  );
}
