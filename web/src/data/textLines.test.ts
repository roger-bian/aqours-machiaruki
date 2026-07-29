import { describe, expect, it } from 'vitest';
import { toDisplayLines } from './textLines';

// Inputs are real strings from the live KML, already through the pipeline's
// `<br>` -> space conversion (pipeline/app/description.py), which is the form
// the panel receives them in.
describe('toDisplayLines', () => {
  describe('the 10-character threshold on a parenthetical', () => {
    it('keeps a short qualifier inline', () => {
      // 最終入館16:00 is 9 characters
      expect(toDisplayLines('9:00～17:00（最終入館16:00）')).toEqual(['9:00～17:00（最終入館16:00）']);
      expect(toDisplayLines('土曜・日曜10:00～16:00(L.O.15:30)')).toEqual([
        '土曜・日曜10:00～16:00(L.O.15:30)',
      ]);
    });

    it('breaks before a longer one', () => {
      // 木曜日は14:00まで is 11
      expect(toDisplayLines('10:00～20:00（木曜日は14:00まで）')).toEqual([
        '10:00～20:00',
        '（木曜日は14:00まで）',
      ]);
    });

    it('breaks at exactly 10, the boundary', () => {
      const inside = '土曜日・日曜日を除く';
      expect(inside).toHaveLength(10);
      expect(toDisplayLines(`祝日の翌日（${inside}）`)).toEqual(['祝日の翌日', `（${inside}）`]);
    });
  });

  describe('breaking after a closing bracket', () => {
    it('breaks when a digit follows', () => {
      expect(toDisplayLines('平日（※祝日を除く）10:00～20:00')).toEqual([
        '平日（※祝日を除く）',
        '10:00～20:00',
      ]);
    });

    it('does not break when a non-comma symbol follows', () => {
      expect(toDisplayLines('(不定休)・日（スタンプは7:30～11:30、奥駿河湾日曜市にて設置）')).toEqual([
        '(不定休)・日',
        '（スタンプは7:30～11:30、奥駿河湾日曜市にて設置）',
      ]);
    });

    it('breaks when a comma follows, dropping the comma', () => {
      expect(toDisplayLines('平日11:00〜14:30（L.O.）、土日祝10:30〜14:30（L.O.）')).toEqual([
        '平日11:00〜14:30（L.O.）',
        '土日祝10:30〜14:30（L.O.）',
      ]);
    });
  });

  describe('commas', () => {
    it('breaks on one outside brackets', () => {
      expect(toDisplayLines('※土・日・祝日は、昼11:30～14:30(L.O.)')).toEqual([
        '※土・日・祝日は',
        '昼11:30～14:30(L.O.)',
      ]);
    });

    it('leaves one inside brackets alone', () => {
      expect(toDisplayLines('月曜日（月曜が祝日の場合、火曜日休み）')).toEqual([
        '月曜日',
        '（月曜が祝日の場合、火曜日休み）',
      ]);
    });
  });

  describe('a parenthetical is atomic', () => {
    it('does not split on a space inside it', () => {
      // this used to render as `（6月～9月` / `10:00～20:00）` - the whitespace
      // rule cut straight through the brackets
      expect(toDisplayLines('10:00～19:00 （6月～9月 10:00～20:00）')).toEqual([
        '10:00～19:00',
        '（6月～9月 10:00～20:00）',
      ]);
    });
  });

  describe('text that does not parse', () => {
    it('leaves an unclosed bracket as a single line, losing nothing', () => {
      expect(toDisplayLines('10:00～18:00（土曜は休み')).toEqual(['10:00～18:00（土曜は休み']);
    });

    it('returns nothing for empty or separator-only input', () => {
      expect(toDisplayLines('')).toEqual([]);
      expect(toDisplayLines('  、 ')).toEqual([]);
    });

    it('keeps a URL intact', () => {
      expect(toDisplayLines('年中無休（年末年始を除く） https://www.deep-heda.com')).toEqual([
        '年中無休（年末年始を除く）',
        'https://www.deep-heda.com',
      ]);
    });
  });

  describe('breakOnWhitespace: false, used for the location name', () => {
    it('keeps spaces inline', () => {
      const opts = { breakOnWhitespace: false };
      expect(toDisplayLines('三交イン 沼津駅前', opts)).toEqual(['三交イン 沼津駅前']);
      expect(toDisplayLines('食堂・ひもの販売　あじや', opts)).toEqual(['食堂・ひもの販売　あじや']);
    });

    it('still breaks at a long parenthetical and at a comma', () => {
      expect(toDisplayLines('ゲーマーズ沼津店（スタンプは2階レジ横に設置）', { breakOnWhitespace: false })).toEqual([
        'ゲーマーズ沼津店',
        '（スタンプは2階レジ横に設置）',
      ]);
    });
  });

  describe('the longest entry in the corpus', () => {
    it('breaks 沼津市歴史民俗資料館 into one clause per line', () => {
      const text =
        '9:00～16:00 休館日／毎週月曜日（祝日は開館）、毎月最終の平日、祝日の翌日（土曜日・日曜日を除く）、年末年始（12月29日～1月3日） 入館料／無料（※ただし御用邸記念公園への入園料大人100円、小・中学生50円が必要です）';
      expect(toDisplayLines(text)).toEqual([
        '9:00～16:00',
        '休館日／毎週月曜日（祝日は開館）',
        '毎月最終の平日',
        '祝日の翌日',
        '（土曜日・日曜日を除く）',
        '年末年始',
        '（12月29日～1月3日）',
        '入館料／無料',
        '（※ただし御用邸記念公園への入園料大人100円、小・中学生50円が必要です）',
      ]);
    });
  });
});
