// A picture of a bench she was given for an answer, under that answer: what she saw, as the person can see it. Opens
// full size in its own tab.
import type { ChatLook } from '../../api/types';

function of(look: ChatLook): string {
  return look.piece_id === null ? 'the whole bench' : `piece ${look.piece_id}`;
}

export function LookDetails({ look }: { look: ChatLook }) {
  if (!look.url) return <p class="look-none">She looked at {of(look)}; the picture cannot be shown.</p>;
  return (
    <figure class="look-seen">
      <a href={look.url} target="_blank" rel="noopener">
        <img src={look.url} alt={`What she saw: ${of(look)}`} loading="lazy" />
      </a>
      <figcaption>What she saw · {of(look)}</figcaption>
    </figure>
  );
}
