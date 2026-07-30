/**
 * The frontend no longer decides where text breaks - pipeline/app/display.py
 * does, and pipeline/tests/test_display_golden.py is where the breaking rules
 * are pinned. All that is left here is the fallback for a row the pipeline
 * hasn't written yet, which is the only branch that can put a wrong thing on
 * screen.
 */
import { describe, expect, it } from 'vitest';
import { extraLines, linesFor } from './displayLines';
import type { DisplayJson, Location } from './types';

function location(display_json: DisplayJson | null): Location {
  return {
    id: 1,
    name: '海鮮丼と魚河岸定食 かもめ丸',
    lat: 35.1,
    lon: 138.8,
    member: '津島善子',
    address: '静岡県 沼津市 千本港町 101',
    hours: '平日11:00〜14:30（L.O.）',
    holidays: 'なし',
    hours_json: null,
    display_json,
    img_url: '',
    stamp: false,
    badge: false,
  };
}

const FULL: DisplayJson = {
  name: ['海鮮丼と魚河岸定食', 'かもめ丸'],
  address: ['静岡県沼津市千本港町101', '沼津みなと新鮮館前'],
  hours: ['平日11:00〜14:30（L.O.）'],
  holidays: ['なし'],
  extra: ['(スタンプは縁日コーナーに設置しています)'],
  confidence: 'verified',
};

describe('linesFor', () => {
  it('returns the reviewed lines when they exist', () => {
    expect(linesFor(location(FULL), 'name')).toEqual(['海鮮丼と魚河岸定食', 'かもめ丸']);
  });

  it('falls back to the raw column when display_json is null', () => {
    // the window between the ALTER TABLE and the first pipeline run - one
    // unbroken line, which CSS wraps, rather than a blank panel
    expect(linesFor(location(null), 'name')).toEqual(['海鮮丼と魚河岸定食 かもめ丸']);
    expect(linesFor(location(null), 'address')).toEqual(['静岡県 沼津市 千本港町 101']);
  });

  it('falls back when the field is present but empty', () => {
    const partial = { ...FULL, hours: [] };
    expect(linesFor(location(partial), 'hours')).toEqual(['平日11:00〜14:30（L.O.）']);
  });

  it('returns nothing rather than an empty line for absent text', () => {
    const loc = { ...location(null), hours: '' };
    expect(linesFor(loc, 'hours')).toEqual([]);
  });
});

describe('extraLines', () => {
  it('is the その他 section', () => {
    expect(extraLines(location(FULL))).toEqual(['(スタンプは縁日コーナーに設置しています)']);
  });

  it('is empty when there is no display_json, so the section stays hidden', () => {
    expect(extraLines(location(null))).toEqual([]);
  });
});
