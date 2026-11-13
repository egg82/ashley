// Household, at bearing 020: the household's own settings read back as a sentence, where and when the house is, what she
// always knows about it, her manner in it, its pronunciation words and, for an admin, its people.
import { useEffect, useLayoutEffect, useRef } from 'preact/hooks';
import { household, householdSaid, householdState, loadHousehold } from '../../household/household';
import { person } from '../../session/session';
import { dockIn } from '../../shell/her/dock';
import { herRoomLeft } from '../../shell/her/state';
import { Lexicon } from './Lexicon';
import { loadLexicon } from './lexiconWords';
import { Manner } from './Manner';
import { Notebook } from './Notebook';
import { PeoplePanel } from './PeoplePanel';
import { SayLine } from './SayLine';
import { SaveBar } from './SaveBar';
import { Sentence } from './Sentence';
import { Where } from './Where';

function Down() {
  const unavailable = householdState.value === 'unavailable';
  return (
    <div class="panel set-down hh-down" role="alert">
      <div class="set-down-says">
        <b>{unavailable ? "Can't reach her right now." : "The household didn't load."}</b>
        <button class="btn" type="button" onClick={() => void loadHousehold()}>Try again</button>
      </div>
    </div>
  );
}

function Reading() {
  const failed = householdState.value === 'failed' || householdState.value === 'unavailable';
  if (household.value) return <Sentence />;
  return failed ? <Down /> : <span class="meta">Reading the household…</span>;
}

function Cards() {
  return (
    <div class="hh-grid">
      <div class="hh-col">
        <div class="hh-o1"><Reading /></div>
        <div class="hh-o4"><Notebook /></div>
        <div class="hh-o5"><Manner /></div>
      </div>
      <div class="hh-col">
        <div class="hh-o2"><Where /></div>
        <div class="hh-o3"><SayLine /></div>
        <div class="hh-o6"><Lexicon /></div>
        {person.value?.admin && <div class="hh-o7"><PeoplePanel /></div>}
      </div>
    </div>
  );
}

export function HouseholdRoom() {
  useEffect(() => {
    void loadLexicon();
    void loadHousehold();
    return () => {
      householdSaid.value = null;
      herRoomLeft();
    };
  }, []);
  const here = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const room = here.current?.closest('.room');
    if (room && !room.classList.contains('leaving')) dockIn(room, false);
  }, []);
  return (
    <div class="set hh" ref={here}>
      <div class="set-head">
        <h1>Household</h1>
        <span class="set-dock" data-dock />
      </div>
      {householdState.value === 'unavailable' && !household.value ? <Down /> : <Cards />}
      <SaveBar />
    </div>
  );
}
