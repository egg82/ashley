// What a command that didn't go through says on screen: what didn't happen, then what to do (`voice.md`).
import type { Outcome } from '../model/bench';

type Why = Extract<Outcome, { ok: false }>['why'];

const WHY: Record<Why, string> = {
  unknown_kind: "This page asked for a kind of piece the bench doesn't take. Nothing changed.",
  bad_title: 'Not saved. A title needs some words, and no more than the bench allows.',
  too_long: 'Not saved. That is longer than this kind of piece holds.',
  full: 'No room. This bench holds as many pieces as it can; archive or remove one first.',
  no_such_piece: "That piece isn't there any more.",
  bad_place: "That place isn't on the bench. Nothing moved.",
  stale_base: 'This changed while you were writing. Yours is kept beside it.',
  nothing_to_undo: 'Nothing to undo.',
  changed_since: "Can't undo that: the piece has changed since.",
  not_runnable: 'Only code can be run. Nothing ran.',
  bad_automation: "Not saved. That isn't an automation Home Assistant can read: one JSON object of alias, triggers, conditions, actions.",
  bad_site: "Not saved. A site is one https address and nothing else; a YouTube or Vimeo video is a video.",
  bad_video: 'Not saved. A video is {"url": …, "start": seconds}: a YouTube or Vimeo page, or an .mp4, .webm, .ogv, .m4v or .mov file.',
  not_installable: 'Only an automation can be installed. Nothing changed.',
  incomplete: 'It needs a name, a trigger and an action before it can be installed.',
  no_proposal: 'That proposal is gone or already installed. Nothing changed.',
  needs_person: 'Only you can install it. Nothing changed.',
  bad_body: "Not saved. A job's card is written by Ashley's job runner; to stop a job, use its Cancel button.",
  bad_wake: "Not saved. A wake rule is one JSON object of event, brief and tools.",
  bad_facts: 'Not saved. Facts are {"items": [{name, value, unit, source}]}: a unit of mm, deg, count, g, ml or min, a source of measured, datasheet, accepted, bound (with a tolerance) or guessed; a choice is {kind: "choice", name, label, value, source} with a source of stated, seen, datasheet, accepted or guessed.',
  bad_citation: 'Not saved. A choice taken from a photo or a page names that piece.',
  confirmed_measurement: 'Not saved. A confirmed number changes only with a new source or note saying where it came from.',
  not_video: 'Only a video can be played or paused. Nothing changed.',
  bad_reader: "Not saved. A reader's page comes from Ashley reading it; it isn't typed.",
  bad_recipe: "Not saved. A recipe is its page's recipe as Ashley read it; change its serves and keep the rest as it is.",
  not_reader: 'Only a page of text has a passage to highlight. Nothing changed.',
  bad_passage: 'That is not a passage of the page. Nothing changed.',
  bad_rows: "Those choices aren't on the piece any more. Nothing changed.",
  bad_cue: 'That is not a place in the video. Nothing changed.',
  bad_controls: "Not saved. A screen's buttons are a list of at most 12, each with a label, an action and a light or scene.",
  already_shown: 'The screen already has that. Nothing changed.',
  required: 'The screen keeps its conversation. Nothing changed.',
  bad_file: "Not saved. A file's content can't be changed; upload it again instead.",
  too_large: 'Not added. That file is larger than a bench takes.',
  unsupported: "Not added. A bench takes text, images, PDFs and zip files, and the file has to be what it says it is.",
  empty: 'Not added. That file is empty.',
  closed: 'This bench is closed. Nothing changed.',
  unreachable: "Can't reach Ashley. Nothing changed. Try again.",
  failed: "That didn't go through. Nothing changed. Try again.",
};

export function whyNot(why: Why): string {
  return WHY[why];
}
