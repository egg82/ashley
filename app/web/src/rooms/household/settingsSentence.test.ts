import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { Draft } from './draft.ts';
import { localeGloss, sentenceOf } from './settingsSentence.ts';

const draft: Draft = { timezone: 'America/Denver', profile: '', locale: 'en-US', unit_system: 'imperial', clock: '24h', latitude: '', longitude: '' };
const spoken = (d: Draft) => sentenceOf(d).map((p) => ('words' in p ? p.words : `[${p.reads}]`)).join('');

test('six words are slots and each choice reads as what it means', () => {
  assert.equal(spoken(draft),
    'I keep time in [America/Denver], write [24-hour] times and use [feet and Fahrenheit]. I read and write [en-US]. The house is at latitude [] and longitude [].');
  assert.equal(sentenceOf(draft).filter((p) => 'slot' in p).length, 6);
});

test('metric and the 12-hour clock read in their own words, and typed text reads as typed', () => {
  const said = spoken({ ...draft, unit_system: 'metric', clock: '12h', latitude: '39.7', longitude: '-105' });
  assert.match(said, /write \[12-hour\] times and use \[metres and Celsius\]/);
  assert.match(said, /latitude \[39.7\] and longitude \[-105\]/);
});

test('a language tag is put in words, and one the browser cannot place has none', () => {
  assert.equal(localeGloss('en-US'), 'English, United States');
  assert.equal(localeGloss('fr'), 'French');
  assert.equal(localeGloss('not a tag'), null);
  assert.equal(localeGloss('xx-QQ'), null);
});
