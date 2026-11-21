// A service's settings in the words of what she does. Home Assistant's: why they exist, then lists, look-ups, the things
// that need the person's word, the calendars the hallway screen shows and the cameras she may look through; a kind that
// declares only the cameras (Bambuddy) gets that section alone. Each section edits the stored settings through the draft; the page saves them whole.
import { Why } from './Why';
import { CalendarsSection } from './CalendarsSection';
import { CamerasSection } from './CamerasSection';
import { ListsSection } from './ListsSection';
import { LookupsSection } from './LookupsSection';
import { NeedWordSection } from './NeedWordSection';
import { house, loadHouse, settings } from './state';

export function HaSettings({ id }: { id: number }) {
  const read = house.value;
  const catalogue = read.state === 'ready' ? read.catalogue : null;
  const ofHouse = settings.value?.settings.some((s) => s.key === 'household_reads') ?? false;
  return (
    <>
      {ofHouse && <Why />}
      {read.state === 'loading' && <p class="meta">Asking the service what it has…</p>}
      {read.state === 'unavailable' && (
        <div class="dc-act">
          <span class="unk">it isn’t answering, so names show as saved</span>
          <button class="btn sm ghost" type="button" onClick={() => void loadHouse(id)}>Try again</button>
        </div>
      )}
      {ofHouse && (
        <>
          <ListsSection house={catalogue} />
          <LookupsSection house={catalogue} />
          <NeedWordSection house={catalogue} />
          <CalendarsSection house={catalogue} />
        </>
      )}
      <CamerasSection house={catalogue} />
    </>
  );
}
