// Home Assistant's settings in the words of what she does: why they exist, then lists, look-ups and the things that need
// the person's word. Each section edits the stored settings through the draft; the page saves them whole.
import { Why } from './Why';
import { ListsSection } from './ListsSection';
import { LookupsSection } from './LookupsSection';
import { NeedWordSection } from './NeedWordSection';
import { house, loadHouse } from './state';

export function HaSettings({ id }: { id: number }) {
  const read = house.value;
  const catalogue = read.state === 'ready' ? read.catalogue : null;
  return (
    <>
      <Why />
      {read.state === 'loading' && <p class="meta">Asking the house what it has…</p>}
      {read.state === 'unavailable' && (
        <div class="dc-act">
          <span class="unk">the house isn’t answering, so names show as saved</span>
          <button class="btn sm ghost" type="button" onClick={() => void loadHouse(id)}>Try again</button>
        </div>
      )}
      <ListsSection house={catalogue} />
      <LookupsSection house={catalogue} />
      <NeedWordSection house={catalogue} />
    </>
  );
}
