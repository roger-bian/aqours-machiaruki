"""Regenerate app/hours_parsed.json from the live KML.

Run from the pipeline directory (it needs the `aqours` virtualenv):
    python tools/gen_hours_overrides.py

Baseline is the rule-based parse; CORRECTIONS carries the hand-authored fixes
for entries where the rule tier is wrong (almost always because it strips a
parenthetical that actually contained schedule information).

Re-run to pick up new KML entries: existing keys keep whatever is already in
the committed file, so hand corrections survive regeneration.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.description import parse_description
from app.hours import DAYS, override_key, rule_based_parse
from app.kml import fetch_kml, load_placemarks

OUT = os.path.join(os.path.dirname(__file__), '..', 'app', 'hours_parsed.json')

# minutes-from-midnight helpers so the corrections read like the source text
def hm(h, m=0):
    return h * 60 + m


ALL = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun', 'hol']

CORRECTIONS = {
    # びゅうお - 10:00~20:00（木曜日は14:00まで）
    '80b8442da3f3c422': {
        'weekly': {**{d: [[hm(10), hm(20)]] for d in ALL},
                   'thu': [[hm(10), hm(14)]]},
        'notes': ['施設メンテナンスによる休館あり'],
        'irregular': True,
    },
    # 鮨庵さいとう 本店 - 11:30~14:00(土日祝は15:00) / 17:00~21:00
    'a8b0789b6bf997f1': {
        'weekly': {
            **{d: [[hm(11, 30), hm(14)], [hm(17), hm(21)]]
               for d in ['mon', 'tue', 'wed', 'fri']},
            'thu': [],
            **{d: [[hm(11, 30), hm(15)], [hm(17), hm(21)]]
               for d in ['sat', 'sun', 'hol']},
        },
    },
    # とりう - 昼11:30~14:30 夜17:30~20:00 / ※土・日・祝日は 夜17:00~19:30
    'd894d84a392ce8b1': {
        'weekly': {
            **{d: [[hm(11, 30), hm(14, 30)], [hm(17, 30), hm(20)]]
               for d in ['mon', 'tue', 'wed', 'fri']},
            'thu': [],
            **{d: [[hm(11, 30), hm(14, 30)], [hm(17), hm(19, 30)]]
               for d in ['sat', 'sun', 'hol']},
        },
    },
    # 伊豆箱根バス - 9:30~18:00 / 土9:30~17:00, 昼休み13:00~14:00 subtracted
    '18da802ee597cb35': {
        'weekly': {
            **{d: [[hm(9, 30), hm(13)], [hm(14), hm(18)]]
               for d in ['mon', 'tue', 'wed', 'fri']},
            'sat': [[hm(9, 30), hm(13)], [hm(14), hm(17)]],
            'thu': [], 'sun': [], 'hol': [],
        },
        'notes': ['昼休み 13:00～14:00'],
    },
    # 沼津市歴史民俗資料館 - 休館日 is buried in the 営業時間 field, so the
    # rule tier sees no 定休日 at all and marks it open every day
    '9db95676b7fbbd0d': {
        'weekly': {**{d: [[hm(9), hm(16)]] for d in ALL}, 'mon': []},
        'closed': ['mon'],
        'closed_dates': ['12-29', '12-30', '12-31', '01-01', '01-02', '01-03'],
        'hol_overrides_closed': True,          # （祝日は開館）
        'closed_after_hol': True,              # 祝日の翌日（土曜日・日曜日を除く）
        'closed_last_weekday': True,           # 毎月最終の平日
        'notes': ['月曜が祝日の場合は開館', '毎月最終の平日、祝日の翌日は休館'],
        'irregular': True,
    },
    # 沼津市芹沢光治良記念館 - 年末年始 sits on line 3 of 定休日
    'd021663ada668fb8': {
        'closed_dates': ['12-29', '12-30', '12-31', '01-01', '01-02', '01-03'],
        'hol_overrides_closed': True,          # （休日にあたるときはその翌日）
        'closed_after_hol': True,              # 休日の翌日（土曜日・日曜日・休日を除く）
        'notes': ['月曜が祝日の場合は翌日休館', '祝日の翌日も休館（土日祝を除く）'],
    },
    # 三交イン 沼津駅前 - a hotel; the Description carries no 営業時間 label at
    # all, so this asserts local knowledge the source does not state
    '0400985ee078138b': {
        'weekly': {d: [[0, 1440]] for d in ALL},
        'always_open': True,
        'confidence': 'manual',
        '_comment': 'hotel front desk; no 営業時間 in the KML',
    },
    # ほさか - （6月～9月 10:00～20:00）; the schema has no seasonal dimension,
    # so the base hours stand and the variation is a note
    '442d475ebf3b0b21': {
        'notes': ['6月～9月は10:00～20:00'],
    },
    # おさかな食堂やまや - ※予約により変更あり
    'da915735c22360df': {
        'notes': ['予約により変更あり'],
    },
    # 欧蘭陀館 - 月曜日(祝日の場合は翌日); the notes stay because a grey calendar
    # cell says only *that* a day is shut, never why
    '3041e474bf0261a7': {
        'hol_overrides_closed': True,
        'hol_defers_closed': True,
        'notes': ['月曜が祝日の場合は翌日休み'],
    },
    # 焼きそば ゆきちゃん - 月曜日（月曜が祝日の場合、火曜日休み）
    '9ed683f9642a59fe': {
        'hol_overrides_closed': True,
        'hol_defers_closed': True,
        'notes': ['月曜が祝日の場合は火曜休み'],
    },
    # 沼津ラクーンよしもと劇場 - 土日祝 open at 11:30 and close at 公演終了時間,
    # which is not a time. A null end says "open, close not stated"; leaving the
    # days empty instead made them indistinguishable from a day the source never
    # mentioned, so every 土日祝 read as closed against the very text above it.
    # Inventing an end is not an option either - it would have the ring claim
    # まもなく閉店 at a time nobody wrote down.
    'fad7f41f61d1de24': {
        'weekly': {'mon': [[900, 1080]], 'tue': [[900, 1080]],
                   'wed': [[900, 1080]], 'thu': [[900, 1080]],
                   'fri': [[900, 1080]],
                   'sat': [[690, None]], 'sun': [[690, None]],
                   'hol': [[690, None]]},
        'notes': ['土日祝は11:30から公演終了時間まで（公演により変動）',
                  '休館日あり'],
        'irregular': True,
    },
}


def _dump(obj):
    """json.dump with indent, but leaf arrays kept on one line.

    Default indenting explodes `[[600, 840]]` across six lines, which buries
    the one value a reviewer is actually checking. Placeholders are swapped in
    before dumping and swapped back after, so no regex ever runs over the
    real JSON.
    """
    stash = {}

    def compact(node):
        if isinstance(node, dict):
            return {k: compact(v) for k, v in node.items()}
        if isinstance(node, list):
            if all(not isinstance(x, (dict, list)) for x in node) or all(
                    isinstance(x, list)
                    and all(isinstance(y, int) or y is None for y in x)
                    for x in node):
                token = f'\x00{len(stash)}\x00'
                stash[token] = json.dumps(node, ensure_ascii=False)
                return token
            return [compact(x) for x in node]
        return node

    text = json.dumps(compact(obj), ensure_ascii=False, indent=1)
    for token, literal in stash.items():
        text = text.replace(json.dumps(token), literal)
    return text


def main():
    with tempfile.NamedTemporaryFile(suffix='.kml') as tmp:
        fetch_kml(tmp.name)
        placemarks = load_placemarks(tmp.name)

    existing = {}
    if os.path.exists(OUT):
        with open(OUT, encoding='utf-8') as f:
            existing = json.load(f)

    out, names = {}, {}
    for _, row in placemarks.iterrows():
        f = parse_description(row['Description'])
        key = override_key(f['raw_hours'], f['raw_holidays'])
        names.setdefault(key, []).append(row['Name'])
        if key in out:
            continue
        if key in existing:                      # keep hand-reviewed entries
            out[key] = existing[key]
            continue
        entry = rule_based_parse(f['raw_hours'], f['raw_holidays'])
        entry['confidence'] = 'verified'
        fix = CORRECTIONS.get(key)
        if fix:
            for k, v in fix.items():
                if k == 'weekly':
                    entry['weekly'] = {d: v.get(d, []) for d in DAYS}
                elif k == 'notes':
                    # replace, don't union: a hand-authored list is the
                    # complete set of caveats for that entry. Unioning kept
                    # the rule tier's auto-extracted parentheticals alongside
                    # a reworded correction saying the same thing, and the
                    # panel rendered both as separate ⚠ lines (set-union only
                    # dedupes byte-identical strings).
                    entry['notes'] = list(v)
                else:
                    entry[k] = v
        entry['_names'] = None                   # filled below
        entry['_raw_hours'] = f['raw_hours']
        entry['_raw_holidays'] = f['raw_holidays']
        out[key] = entry

    for key, entry in out.items():
        entry['_names'] = names[key]
        # stable field order so git diffs stay readable
        order = ['_names', '_raw_hours', '_raw_holidays', '_comment', 'weekly',
                 'closed', 'closed_nth', 'closed_dates', 'closed_last_weekday',
                 'hol_overrides_closed', 'hol_defers_closed', 'closed_after_hol',
                 'always_open', 'irregular', 'permanently_closed',
                 'confidence', 'notes']
        out[key] = {k: entry[k] for k in order if k in entry}

    with open(OUT, 'w', encoding='utf-8') as f:
        f.write(_dump(dict(sorted(out.items()))))
        f.write('\n')

    missing = set(CORRECTIONS) - set(out)
    print(f'wrote {len(out)} entries covering {sum(len(v) for v in names.values())} locations')
    if missing:
        print(f'!! CORRECTIONS keys not present in the KML: {missing}')


if __name__ == '__main__':
    main()
