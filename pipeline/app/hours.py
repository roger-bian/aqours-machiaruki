"""Turn the freeform Japanese `営業時間` / `定休日` text into a structured,
machine-checkable schedule the frontend can evaluate against a clock.

Three tiers, in order (see `parse_hours_holidays`):

1. `hours_parsed.json` - hand-reviewed entries keyed by a hash of the *raw*
   input text. `verified` means "the source text, structured correctly";
   `manual` means "local knowledge the source does not state" (currently just
   三交イン 沼津駅前, a hotel whose Description carries no 営業時間 label).
2. the rule-based parser below, tagged `auto`.

Tier 1 exists because the rule-based tier throws away *all* parentheticals as
noise - that is how it discards `（最終入園15:30）` and `(L.O.16:30)` - which
means it also throws away genuine schedule conditionals like
`（木曜日は14:00まで）`. Roughly six entries carry real hours inside parentheses.

Intervals are minutes from midnight (600 = 10:00), so the frontend compares
integers and never parses a time string.
"""
import hashlib
import json
import os
import re
import unicodedata

ORDER = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
DAYS = ORDER + ['hol']
JP2DAY = {'月': 'mon', '火': 'tue', '水': 'wed', '木': 'thu',
          '金': 'fri', '土': 'sat', '日': 'sun'}
KANJI_NUM = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
             '六': 6, '七': 7, '八': 8, '九': 9}

_OVERRIDES_PATH = os.path.join(os.path.dirname(__file__), 'hours_parsed.json')

# keys carrying human-review context only (raw text, location names); stripped
# before the entry reaches the DB so they don't ride along in every API response
_REVIEW_KEYS = ('_names', '_raw_hours', '_raw_holidays', '_comment')


def _load_overrides():
    if not os.path.exists(_OVERRIDES_PATH):
        return {}
    with open(_OVERRIDES_PATH, encoding='utf-8') as f:
        return json.load(f)


OVERRIDES = _load_overrides()


def override_key(raw_hours, raw_holidays):
    """Content-address the *raw* input, so identical source text always yields
    an identical parse. Two consequences worth knowing: locations whose text
    matches exactly share one entry (136 locations -> 125 keys), and a field
    that is absent still hashes fine (which is what makes the 三交イン manual
    entry stable across runs)."""
    payload = f'{raw_hours or ""}\x1f{raw_holidays or ""}'
    return hashlib.sha1(payload.encode('utf-8')).hexdigest()[:16]


# --- normalization ---------------------------------------------------------

def _normalize(s):
    if not s:
        return ''
    # input is the raw Description slice, so <br> is the line separator here
    s = re.sub(r'<br\s*/?>', '\n', s)
    # NFKC folds fullwidth digits/colons (１２：３４ -> 12:34) and the halfwidth
    # katakana middle dot (･ -> ・), both of which appear in this data
    s = unicodedata.normalize('NFKC', s)
    s = s.replace('　', ' ').replace('\xa0', ' ')
    for dash in '〜～ー－—':
        s = s.replace(dash, '~')
    return re.sub(r'[ \t]+', ' ', s)


def _strip_noise(s):
    """Drop trailing URLs, ※ annotations, and parentheticals. The parentheticals
    are overwhelmingly L.O./最終入園 noise; the handful that carry real schedule
    information are covered by hours_parsed.json instead."""
    s = re.sub(r'https?://\S+', '', s)
    # parentheticals before ※ notes: `平日（※祝日を除く）10:00~20:00` has a ※
    # *inside* the parens, and stripping ※-to-end-of-line first would swallow
    # the time range that follows the closing bracket
    s = re.sub(r'[（(][^）)]*[）)]', '', s)
    s = re.sub(r'※[^\n]*', '', s)
    return s.strip()


_DAYTOK = r'@(mon|tue|wed|thu|fri|sat|sun|hol)'


def _tokenize_days(s):
    """Rewrite every weekday/holiday mention as an unambiguous @token.

    Order is load-bearing. `日` means both "Sunday" and the suffix in `曜日` and
    `1月1日`, and matching bare kanji first was the single biggest source of
    wrong parses when prototyping - `木曜日・第3水曜日` came out closed on
    Sunday. Consuming the long forms first removes the ambiguity entirely.
    """
    s = re.sub(r'(\d+)月(\d+)日', r'@date(\1-\2)', s)
    s = re.sub(r'元旦|元日', '@date(1-1)', s)
    # Compound day-words must be consumed whole, before any bare-kanji rule.
    # Otherwise the 日 inside 平日 / 土日 / 日祝 gets picked up as "Sunday" by
    # the enumeration rules below - `平日・土曜` became `平@sun・@sat`, silently
    # losing the weekdays and adding a Sunday that was never stated.
    s = s.replace('平日', '@wd')
    s = re.sub(r'土日祝日?', '@sat@sun@hol', s)
    s = re.sub(r'日祝日?', '@sun@hol', s)
    s = s.replace('土日', '@sat@sun')
    s = re.sub(r'祝祭日|祝日|祭日|祝', '@hol', s)
    s = re.sub(r'([月火水木金土日])曜日', lambda m: '@' + JP2DAY[m.group(1)], s)
    s = re.sub(r'([月火水木金土日])曜', lambda m: '@' + JP2DAY[m.group(1)], s)
    # bare kanji only inside an enumeration or range with other day tokens
    s = re.sub(
        r'([月火水木金土日])(?=\s*[・,、~]\s*(?:[月火水木金土日]|@(?:mon|tue|wed|thu|fri|sat|sun|hol)))',
        lambda m: '@' + JP2DAY[m.group(1)], s)
    # trailing member of an enumeration, e.g. the 土 in `月・火・木・金・土7:00~13:00`
    # (no separator follows it, so the rule above cannot see it). A digit may
    # follow directly, which is why this must not exclude digits - `1日`-style
    # dates are already consumed by the @date rule above.
    s = re.sub(r'(?<=[・,、~])([月火水木金土日])(?!曜)',
               lambda m: '@' + JP2DAY[m.group(1)], s)
    return s


def _days_in(s):
    """Expand @tokens (including `@mon~@fri` ranges) into a set of day keys."""
    out = set()
    for m in re.finditer(_DAYTOK + r'\s*~\s*' + _DAYTOK, s):
        a, b = m.group(1), m.group(2)
        if a in ORDER and b in ORDER:
            i, j = ORDER.index(a), ORDER.index(b)
            out |= set(ORDER[i:j + 1] if i <= j else ORDER[i:] + ORDER[:j + 1])
    rest = re.sub(_DAYTOK + r'\s*~\s*' + _DAYTOK, '', s)
    out |= {m.group(1) for m in re.finditer(_DAYTOK, rest)}
    if '@wd' in s:
        out |= {'mon', 'tue', 'wed', 'thu', 'fri'}
    return out


# --- hours -----------------------------------------------------------------

_TIME = r'(\d{1,2})\s*:\s*(\d{1,2})'
_RANGE = re.compile(_TIME + r'\s*~\s*' + _TIME)


def _all_day():
    return {d: [[0, 1440]] for d in DAYS}


def _parse_hours(raw):
    """-> (weekly dict or None, always_open bool)"""
    s = _normalize(raw)
    if not s.strip():
        return None, False
    if '24時間' in s:
        return _all_day(), True
    body = _strip_noise(s)
    if not _RANGE.search(body):
        # `年中無休` as the *only* stated 営業時間 - all 8 such entries are
        # hotels, a ryokan, a karaoke box and a Ministop, and every one of them
        # also has an empty or `年中無休` 定休日, so round-the-clock is
        # consistent with the source rather than a guess
        if '年中無休' in body:
            return _all_day(), True
        return None, False

    body = _tokenize_days(body)
    weekly = {d: [] for d in DAYS}
    default = []
    for line in body.split('\n'):
        # walk range-by-range and treat the text since the previous range as
        # that range's scope prefix. Splitting the line on punctuation instead
        # would miss `月・火・木・金・土7:00~13:00 日・祝日9:00~13:30`, where two
        # differently-scoped segments are separated only by a space.
        cursor = 0
        for m in _RANGE.finditer(line):
            prefix = line[cursor:m.start()]
            cursor = m.end()
            # `昼休み13:00~14:00` is a midday *closure*, not an opening; the
            # rule tier drops it rather than inverting its meaning (the
            # override file models the split shift properly)
            if '昼休み' in prefix or '休憩' in prefix:
                continue
            start = int(m.group(1)) * 60 + int(m.group(2))
            end = int(m.group(3)) * 60 + int(m.group(4))
            if end <= start:
                end += 24 * 60
            scope = _days_in(prefix)
            if scope:
                for d in scope:
                    weekly[d].append([start, end])
            else:
                default.append([start, end])
    for d in DAYS:
        if not weekly[d]:
            weekly[d] = [list(r) for r in default]
    # 平日 in older Japanese usage means "not Sunday/holiday" - the six-day week
    # - so a source scoping hours to 平日 and 日祝 while never mentioning 土曜 is
    # stating Saturday inside the 平日 group, not omitting it. Two shops
    # (JEWELRY＆WATCH 市川, つじ写真館) are written that way, and their Saturdays
    # used to fall through the hole between 平日 and 日祝 - no hours, no stated
    # closure, so the ring called them closed. Guarded on 土 being genuinely
    # absent: an explicit 土 scope fills weekly['sat'] above, and a 土曜 定休日
    # empties it again in parse_hours_holidays.
    weekdays = [weekly[d] for d in ORDER[:5]]
    if ('@wd' in body and not weekly['sat']
            and (weekly['sun'] or weekly['hol'])
            and all(h and h == weekdays[0] for h in weekdays)):
        weekly['sat'] = [list(r) for r in weekdays[0]]
    return weekly, False


# --- closed days -----------------------------------------------------------

_NTH = re.compile(
    r'第([0-9一二三四五六七八九](?:[・,、]\s*第?[0-9一二三四五六七八九])*)\s*' + _DAYTOK)
_DATE = re.compile(r'@date\((\d+)-(\d+)\)')


def _parse_holidays(raw):
    """-> (closed set, nth rules, dates, irregular, permanently_closed, notes)"""
    s = _normalize(raw)
    notes = []
    permanently_closed = bool(re.search(r'閉店により|終了しました', s))

    head = _strip_noise(s.split('\n')[0])
    for caveat in re.findall(r'[（(]([^）)]*(?:休|不定)[^）)]*)[）)]', s):
        notes.append(caveat.strip())

    if not head or head == 'なし' or '年中無休' in head:
        return set(), [], [], False, permanently_closed, notes

    irregular = '不定休' in head or '臨時休' in head
    tokens = _tokenize_days(head)

    nth = []
    for m in _NTH.finditer(tokens):
        nums = [int(n) if n.isdigit() else KANJI_NUM[n]
                for n in re.findall(r'[0-9]|[一二三四五六七八九]', m.group(1))]
        nth.append({'day': m.group(2), 'nth': sorted(set(nums))})

    dates = [f'{int(m.group(1)):02d}-{int(m.group(2)):02d}'
             for m in _DATE.finditer(tokens)]

    # remove the nth clauses before reading plain weekday closures, so
    # `木曜日・第3水曜日` yields closed={thu} + nth=[wed@3], not closed={thu,wed}
    rest = _NTH.sub('', tokens)
    rest = _DATE.sub('', rest)
    closed = _days_in(rest)

    if irregular and not closed and not nth:
        return set(), [], dates, True, permanently_closed, notes
    return closed, nth, dates, irregular, permanently_closed, notes


# --- public ----------------------------------------------------------------

def rule_based_parse(raw_hours, raw_holidays):
    weekly, always_open = _parse_hours(raw_hours)
    closed, nth, dates, irregular, perm, notes = _parse_holidays(raw_holidays)

    if weekly is not None:
        # a full-day closure empties that day; nth closures must NOT, since the
        # day is only shut on some weeks and the frontend needs the hours to
        # evaluate the other ones
        for d in closed:
            weekly[d] = []

    return {
        'weekly': weekly,
        'closed': sorted(closed),
        'closed_nth': nth,
        'closed_dates': sorted(set(dates)),
        # Where a closure goes when it collides with a 祝日, plus the one monthly
        # closure the schema had no room for. All three are override tier only:
        # the rule tier reads a plain `火曜日` as shutting every Tuesday, holiday
        # or not, which is what the text says, and moving or adding a closure off
        # a phrase buried in a parenthetical is a judgement call - same reasoning
        # as a null interval end.
        #   hol_overrides_closed - `月曜日（祝日は開館）`: the holiday is open
        #   hol_defers_closed    - `月曜日（祝日の場合は翌日）`: and the closure
        #                          moves to the next day that is not a holiday
        #   closed_after_hol     - `祝日の翌日（土曜日・日曜日を除く）`: the day
        #                          after any holiday is shut
        #   closed_last_weekday  - `毎月最終の平日`: the last Mon-Fri of a month
        'hol_overrides_closed': False,
        'hol_defers_closed': False,
        'closed_after_hol': False,
        'closed_last_weekday': False,
        'always_open': always_open,
        'irregular': irregular,
        'permanently_closed': perm,
        'confidence': 'auto',
        'notes': notes,
    }


def parse_hours_holidays(raw_hours, raw_holidays):
    """Entry point. Returns a structured schedule dict, always with the same
    keys regardless of which tier produced it."""
    entry = OVERRIDES.get(override_key(raw_hours, raw_holidays))
    if entry is not None:
        return {k: v for k, v in entry.items() if k not in _REVIEW_KEYS}
    return rule_based_parse(raw_hours, raw_holidays)


if __name__ == '__main__':
    # Review harness: parse the live KML and print every entry next to its raw
    # text, so a human can eyeball the hard cases. There is no test suite in
    # this repo; this is the substitute. Run: python -m app.hours
    import tempfile

    from app.description import parse_description
    from app.kml import fetch_kml, load_placemarks

    with tempfile.NamedTemporaryFile(suffix='.kml') as tmp:
        fetch_kml(tmp.name)
        placemarks = load_placemarks(tmp.name)

    seen, rows = {}, []
    for _, row in placemarks.iterrows():
        f = parse_description(row['Description'])
        key = override_key(f['raw_hours'], f['raw_holidays'])
        seen.setdefault(key, []).append(row['Name'])
        rows.append((row['Name'], f, key, parse_hours_holidays(
            f['raw_hours'], f['raw_holidays'])))

    for name, f, key, p in rows:
        gaps = [d for d in DAYS
                if p['weekly'] and not p['weekly'][d] and d not in p['closed']]
        print(f"\n■ {name}  [{key}] {p['confidence']}")
        print(f"   営業時間 {f['raw_hours']!r}")
        print(f"   定休日   {f['raw_holidays']!r}")
        print(f"   → closed={p['closed']} nth={p['closed_nth']} "
              f"dates={p['closed_dates']} irregular={p['irregular']} "
              f"perm={p['permanently_closed']}")
        print(f"     weekly={p['weekly']}")
        if gaps:
            print(f"     !! no hours for {gaps} yet not a stated 定休日")

    tally = {
        'locations': len(rows),
        'distinct keys': len(seen),
        'always_open': sum(1 for *_, p in rows if p['always_open']),
        'permanently_closed': sum(1 for *_, p in rows if p['permanently_closed']),
        'irregular': sum(1 for *_, p in rows if p['irregular']),
        'no hours at all': sum(1 for *_, p in rows if p['weekly'] is None),
        'from overrides': sum(1 for *_, p in rows if p['confidence'] != 'auto'),
    }
    print('\n' + '\n'.join(f'{k:>20}: {v}' for k, v in tally.items()))
