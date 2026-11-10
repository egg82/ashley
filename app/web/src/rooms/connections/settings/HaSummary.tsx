// The line under Home Assistant's card, counted from what is stored, with the way into the settings. Nothing is shown
// until the settings are read, and nothing when they cannot be.
import { useEffect, useState } from 'preact/hooks';
import { getSettings } from '../../../api/connectionSettings';
import { summaryOf } from './summary';

export function HaSummary({ id }: { id: number }) {
  const [line, setLine] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    getSettings(id).then((s) => live && setLine(summaryOf(s.values))).catch(() => live && setLine(null));
    return () => { live = false; };
  }, [id]);
  return (
    <div class="cn-summary">
      {line && <span class="cn-blurb">{line}</span>}
      <a class="btn sm" href={`/connections/${id}/settings`}>Change</a>
    </div>
  );
}
