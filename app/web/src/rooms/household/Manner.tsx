// How she talks in this household: the persona sections a household may replace, as cards. What her replies must carry and
// the rules that always hold are not offered here.
import { useEffect } from 'preact/hooks';
import { MannerCard } from './MannerCard';
import { loadPersona, persona, personaSaid, personaState } from './personaSections';

function Body() {
  const p = persona.value;
  if (personaState.value === 'failed' && !p) {
    return (
      <div class="devs-body">
        <span class="unk">couldn't read how she talks</span>
        <button class="btn sm ghost" type="button" onClick={() => void loadPersona()}>Try again</button>
      </div>
    );
  }
  if (!p) return <div class="devs-body"><span class="meta">Reading how she talks…</span></div>;
  const limits = { body: p.body_limit, note: p.note_limit };
  return (
    <>
      {p.sections.map((s) => <MannerCard key={`${s.section}:${s.persona_version}`} section={s} limits={limits} />)}
      {p.orphaned.length > 0 && (
        <p class="meta">Kept but no longer used, since this release changed those parts of her: {p.orphaned.join(', ')}</p>
      )}
    </>
  );
}

export function Manner() {
  useEffect(() => {
    void loadPersona();
    return () => void (personaSaid.value = null);
  }, []);
  return (
    <section class="hh-manner" aria-labelledby="hh-manner-h">
      <div class="hh-sec-head">
        <h2 id="hh-manner-h">Her manner</h2>
        <span class="meta">Her manner, her wit and her examples are this household's to change. What her replies must carry and the
          rules she keeps whatever anyone asks are not.</span>
      </div>
      <Body />
    </section>
  );
}
