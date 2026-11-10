// The rail: where she learned the selected fact, as far as the API knows it, and what each "who can hear it" ring
// means. A conversation from before the channel was recorded has no "where": an unknown, never a guess.
import type { MemoryFact } from '../../api/types';
import { Vis } from '../../components/FactParts';
import { moment, sourceLabel, whereLabel } from './facts';

function Source({ fact }: { fact: MemoryFact }) {
  const s = fact.source;
  const where = whereLabel(s);
  return (
    <dl class="src-facts">
      <dt>Conversation</dt>
      <dd>{sourceLabel(s)}</dd>
      <dt>Started</dt>
      <dd>{moment(s.started_at)}</dd>
      <dt>You</dt>
      <dd>{s.took_part ? 'took part' : "weren't in it"}</dd>
      <dt>Where</dt>
      <dd>{where ?? <span class="unk">not recorded</span>}</dd>
    </dl>
  );
}

export function Rail({ fact }: { fact: MemoryFact }) {
  return (
    <aside class="mem-rail">
      <div class="panel src-panel">
        <div class="ph"><span class="src-dock" data-dock /><h3>Where she learned it</h3></div>
        <div class="src-body">
          <div class="src-of">{fact.text}</div>
          <Source fact={fact} />
        </div>
      </div>
      <div class="panel">
        <div class="ph"><h3>Who can hear it</h3></div>
        <div class="legend">
          <Vis v="shared" /><span class="meta">anyone she's talking to</span>
          <Vis v="discreet" /><span class="meta">only if asked by name</span>
          <Vis v="members" /><span class="meta">any of you, when no one else can hear</span>
          <Vis v="private" /><span class="meta">only you</span>
        </div>
      </div>
    </aside>
  );
}
