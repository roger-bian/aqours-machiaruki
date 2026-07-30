/**
 * The search box is the only place a user reaches a marker by typing rather
 * than by recognising a pin, so a missed match is a location they cannot get
 * to. The cases worth pinning are the ones where the *same shop* is spelled two
 * ways in the row we search: the raw `name` column keeps the KML's spaces and
 * full-width ASCII, while `display_json.name` is pre-broken and half-widthed by
 * pipeline/app/display.py. Either spelling alone loses queries.
 */
import { describe, expect, it } from 'vitest';
import { matchRange, numberMatchLength, searchLocations } from './searchLocations';
import type { DisplayJson, Location } from './types';

function location(
  id: number,
  name: string,
  display_json: DisplayJson | null = null,
): Location {
  return {
    id,
    name,
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

function displayName(...lines: string[]): DisplayJson {
  return {
    name: lines,
    address: [],
    hours: [],
    holidays: [],
    extra: [],
    confidence: 'verified',
  };
}

const ids = (locs: Location[]) => locs.map((loc) => loc.id);

describe('searchLocations', () => {
  it('matches partway into the name, not just the start', () => {
    const locs = [location(1, '沼津港深海水族館'), location(2, '三津シーパラダイス')];
    expect(ids(searchLocations(locs, '水族館'))).toEqual([1]);
  });

  it('matches across the space the raw name carries', () => {
    // the pipeline breaks this one in two, but the KML writes it with a space
    const loc = location(1, '海鮮丼と魚河岸定食 かもめ丸', displayName('海鮮丼と魚河岸定食', 'かもめ丸'));
    expect(ids(searchLocations([loc], '定食かもめ'))).toEqual([1]);
    expect(ids(searchLocations([loc], '定食 かもめ'))).toEqual([1]);
  });

  it('matches across a break that consumed its separator', () => {
    // display.py may drop the character it broke on, so the joined display
    // lines are the only spelling a query spanning the break can hit
    const loc = location(1, 'グランマ、シーサイド店', displayName('グランマ', 'シーサイド店'));
    expect(ids(searchLocations([loc], 'グランマシーサイド'))).toEqual([1]);
  });

  it('folds full-width against half-width and upper against lower', () => {
    const loc = location(1, 'ＬＡＷＳＯＮ 沼津店', displayName('LAWSON 沼津店'));
    expect(ids(searchLocations([loc], 'lawson'))).toEqual([1]);
    expect(ids(searchLocations([loc], 'ＬＡＷ'))).toEqual([1]);
  });

  it('treats an all-digit query as a stamp-number prefix', () => {
    const locs = [location(1, 'あ'), location(12, 'い'), location(19, 'う'), location(2, 'え')];
    expect(ids(searchLocations(locs, '1'))).toEqual([1, 12, 19]);
    expect(ids(searchLocations(locs, '12'))).toEqual([12]);
  });

  it('ranks a name prefix above a name substring', () => {
    const locs = [
      location(3, '沼津港の店'), // 港 mid-string
      location(2, '港八十三番地'), // 港 at the start
    ];
    expect(ids(searchLocations(locs, '港'))).toEqual([2, 3]);
  });

  it('ranks a stamp-number hit above a name hit on the same digits', () => {
    const locs = [location(5, '沼津18番店'), location(1, '駅前ショップ')];
    expect(ids(searchLocations(locs, '1'))).toEqual([1, 5]);
  });

  it('lists a location once even when both spellings match', () => {
    const loc = location(1, 'かもめ丸', displayName('かもめ丸'));
    expect(ids(searchLocations([loc], 'かもめ'))).toEqual([1]);
  });

  it('falls back to the raw name when display_json is null', () => {
    // the window between the ALTER TABLE and the first pipeline run
    expect(ids(searchLocations([location(1, '沼津港深海水族館')], '深海'))).toEqual([1]);
  });

  it('returns nothing for an empty or whitespace-only query', () => {
    const locs = [location(1, '沼津港深海水族館')];
    expect(searchLocations(locs, '')).toEqual([]);
    expect(searchLocations(locs, '   ')).toEqual([]);
  });

  it('returns every match, leaving the 5-plus-overflow split to the caller', () => {
    const locs = Array.from({ length: 8 }, (_, i) => location(i + 1, `沼津 ${i + 1} 号店`));
    expect(searchLocations(locs, '沼津')).toHaveLength(8);
  });
});

/** The panel bolds this range, so an off-by-one is a visibly wrong highlight. */
describe('matchRange', () => {
  const slice = (text: string, query: string) => {
    const range = matchRange(text, query);
    return range ? text.slice(range[0], range[1]) : null;
  };

  it('locates the run as the user sees it, not as it was folded', () => {
    expect(slice('沼津港深海水族館', '深海')).toBe('深海');
    expect(matchRange('沼津港深海水族館', '深海')).toEqual([3, 5]);
  });

  it('spans the whitespace a match straddles, so the bold stays in one piece', () => {
    expect(slice('海鮮丼と魚河岸定食 かもめ丸', '定食かもめ')).toBe('定食 かもめ');
  });

  it('maps a width-folded match back onto the original characters', () => {
    // the query is half-width, the text full-width: the highlight has to land
    // on the full-width run that is actually on screen
    expect(slice('ＬＡＷＳＯＮ 沼津店', 'lawson')).toBe('ＬＡＷＳＯＮ');
  });

  it('is null when this spelling does not contain the query', () => {
    // the row can still be listed - searchLocations also reads the raw name
    expect(matchRange('かもめ丸', '海鮮丼')).toBeNull();
    expect(matchRange('かもめ丸', '  ')).toBeNull();
  });
});

describe('numberMatchLength', () => {
  it('counts the leading digits a stamp number matched', () => {
    expect(numberMatchLength(136, '1')).toBe(1);
    expect(numberMatchLength(136, '13')).toBe(2);
    expect(numberMatchLength(136, '136')).toBe(3);
  });

  it('is 0 when the digits are not a prefix, or the query is not digits', () => {
    expect(numberMatchLength(136, '36')).toBe(0);
    expect(numberMatchLength(136, '沼津')).toBe(0);
    expect(numberMatchLength(136, '')).toBe(0);
  });
});
