// Household, at bearing 020: the household's own settings, her persona in it and its pronunciation words, edited by any of its people.
import { useEffect, useLayoutEffect, useRef } from 'preact/hooks';
import { loadHousehold } from '../../household/household';
import { dockIn } from '../../shell/her/dock';
import { herRoomLeft } from '../../shell/her/state';
import { HouseholdPanel } from './HouseholdPanel';
import { Lexicon } from './Lexicon';
import { loadLexicon } from './lexiconWords';
import { PersonaPanel } from './PersonaPanel';

export function HouseholdRoom() {
  useEffect(() => {
    void loadLexicon();
    void loadHousehold();
    return herRoomLeft;
  }, []);
  const here = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const room = here.current?.closest('.room');
    if (room && !room.classList.contains('leaving')) dockIn(room, false);
  }, []);
  return (
    <div class="set" ref={here}>
      <div class="set-head">
        <h1>Household</h1>
        <span class="set-dock" data-dock />
      </div>
      <div class="set-grid">
        <div class="set-col">
          <PersonaPanel />
        </div>
        <div class="set-col">
          <HouseholdPanel />
          <Lexicon />
        </div>
      </div>
    </div>
  );
}
