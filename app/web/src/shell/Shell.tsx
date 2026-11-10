// The app: one field, her at the centre, rooms at bearings. Until a person is signed in and she has answered, the
// camera stays on the sign-in face; after that the path picks the room and a change of path flies there.
import { effect } from '@preact/signals';
import { useLocation } from 'preact-iso';
import { useEffect, useLayoutEffect, useRef } from 'preact/hooks';
import { closeLive, onResync, openLive } from '../session/live';
import { load, person, status } from '../session/session';
import { watchBuild } from '../session/watch';
import { loadingLines } from '../signin/LoadingLines';
import { reveal, revealed, unreveal } from '../signin/reveal';
import { World } from './field/World';
import { flying, flyTo, land } from './flight';
import { FollowHer } from './her/FollowHer';
import { pageMoved } from './her/moves';
import { TravellingMark } from './her/TravellingMark';
import { roomForPath, type RoomId } from './rooms';
import { Stage } from './Stage';
import { Topbar } from './topbar/Topbar';

effect(() => {
  document.documentElement.toggleAttribute('data-flying', flying.value);
});

effect(() => {
  if (status.value !== 'signed-in') return;
  const watcher = watchBuild();
  const unsubscribe = onResync(watcher.check);
  return () => {
    unsubscribe();
    watcher.stop();
  };
});

effect(() => {
  if (status.value === 'signed-in') openLive();
  else closeLive();
});

effect(() => {
  if (status.value === 'signed-in' && !revealed.peek()) void reveal(loadingLines().length);
  else if (status.value !== 'signed-in') unreveal();
});

/** Sends the camera to `target`: lands on the first one, flies to every one after. */
function useCamera(target: RoomId): void {
  const landed = useRef(false);
  useLayoutEffect(() => {
    document.documentElement.dataset.room = target;
    if (landed.current) flyTo(target);
    else land(target);
    landed.current = true;
  }, [target]);
}

export function Shell() {
  const { path } = useLocation();
  useEffect(() => void load(), []);
  useEffect(pageMoved, [path]);
  const who = person.value;
  const target: RoomId = status.value === 'signed-in' && revealed.value && who ? roomForPath(path).id : 'signin';
  useCamera(target);
  return (
    <>
      <World />
      {who && target !== 'signin' && <Topbar current={target} person={who} />}
      <Stage />
      {who && target !== 'signin' && <FollowHer />}
      <TravellingMark />
    </>
  );
}
