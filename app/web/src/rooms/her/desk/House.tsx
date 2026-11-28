// The Desk's house column: who is home, what needs the person, and the household's lights and scenes, drawn from the
// shared parts over the person's own routes (`session/house.ts`).
import { attentionView } from '../../../components/parts/attentionView';
import { drawPart, type PartSources } from '../../../components/parts/registry';
import { houseAttention, houseControls, houseHome } from '../../../session/house';

const SOURCES: PartSources = { controls: houseControls, home: houseHome, attention: houseAttention, conversation: () => null };

export function House() {
  return (
    <div class="house">
      {drawPart('home', SOURCES)}
      {drawPart('attention', SOURCES)}
      {drawPart('controls', SOURCES)}
    </div>
  );
}

/** The house folded to one line: how many things need the person, else clear, else null when some could not be read. */
export function houseSummary(): string | null {
  const view = attentionView(houseAttention.attention.value);
  if (view.needs.length) return `${view.needs.length} need${view.needs.length === 1 ? 's' : ''} you`;
  return view.clear ? 'all clear' : null;
}
