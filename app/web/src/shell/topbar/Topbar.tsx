// The top bar: her home dock, the bearing nav, the motion switch, the minimap and who is signed in.
import type { Person } from '../../api/types';
import { motion, toggleMotion } from '../motion';
import type { RoomId } from '../rooms';
import { Account } from './Account';
import { BearingNav } from './BearingNav';
import { Minimap } from './Minimap';

export function Topbar({ current, person }: { current: RoomId; person: Person }) {
  return (
    <header class="topbar">
      <a class="home" href="/" aria-label="Ashley"><span data-dock-home /></a>
      <BearingNav current={current} />
      <div class="spacer" />
      <button class="btn sm motion-toggle" type="button" aria-pressed={motion.value === 'reduced'} onClick={toggleMotion}>
        {motion.value === 'reduced' ? 'Motion: reduced' : 'Motion: full'}
      </button>
      <Minimap />
      <Account person={person} />
    </header>
  );
}
