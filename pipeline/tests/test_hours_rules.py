"""Unit tests for the rule tier in app/hours.py, one case per documented
footgun. These call the private helpers deliberately: they are the units that
actually broke while this parser was being written, and testing only the public
entry point would route almost everything through the override file instead.
"""
import pytest

from app.hours import (
    _days_in,
    _normalize,
    _parse_hours,
    _parse_holidays,
    _strip_noise,
    _tokenize_days,
    override_key,
    rule_based_parse,
)

WEEKDAYS = ['mon', 'tue', 'wed', 'thu', 'fri']


# --- day tokenization ------------------------------------------------------
# The module's own comment calls this "the single biggest source of wrong
# parses": 日 is both Sunday and the suffix in 曜日/1月1日, so compound words
# have to be consumed whole before any bare-kanji rule runs.

@pytest.mark.parametrize('text,expected', [
    # the regression: 平日 must be eaten before the bare-kanji rules, or the 日
    # inside it becomes Sunday and all five weekdays are silently lost
    ('平日・土曜', '@wd・@sat'),
    ('土日祝', '@sat@sun@hol'),
    ('土日祝日', '@sat@sun@hol'),
    ('日祝', '@sun@hol'),
    ('日祝日', '@sun@hol'),
    ('土日', '@sat@sun'),
    ('祝祭日', '@hol'),
    ('祭日', '@hol'),
    ('水曜日', '@wed'),
    ('土曜', '@sat'),
    ('月~金', '@mon~@fri'),
    # dates are consumed before day kanji, so the 日 in 1月1日 is not Sunday
    ('1月1日', '@date(1-1)'),
    ('元旦', '@date(1-1)'),
    # nth-week markers survive tokenization for _NTH to pick up later
    ('木曜日・第3水曜日', '@thu・第3@wed'),
    # the trailing 土 has no separator after it, so it needs its own rule
    ('月・火・木・金・土7:00~13:00', '@mon・@tue・@thu・@fri・@sat7:00~13:00'),
])
def test_tokenize_days(text, expected):
    assert _tokenize_days(text) == expected


@pytest.mark.parametrize('tokens,expected', [
    ('@mon~@fri', WEEKDAYS),
    # a range that wraps the end of the week
    ('@sat~@mon', ['sat', 'sun', 'mon']),
    ('@wd', WEEKDAYS),
    ('@wd・@sat', WEEKDAYS + ['sat']),
    ('@sun@hol', ['sun', 'hol']),
])
def test_days_in(tokens, expected):
    assert _days_in(tokens) == set(expected)


# --- normalization ---------------------------------------------------------

@pytest.mark.parametrize('text,expected', [
    # NFKC folds fullwidth digits and colons, which the source data uses freely
    ('１０：００~２０：００', '10:00~20:00'),
    ('9：00～16：00', '9:00~16:00'),
    # the three dash variants the source data actually uses (wave dash,
    # fullwidth tilde, prolonged sound mark) all collapse to ~, so one _RANGE
    # regex covers them. Note NFKC folds fullwidth － to ASCII - before the
    # dash loop runs, so a hyphen-joined range would yield no hours at all;
    # there are none upstream, and mapping - would break dates and addresses.
    ('10:00〜20:00', '10:00~20:00'),
    ('10:00～20:00', '10:00~20:00'),
    ('10:00ー20:00', '10:00~20:00'),
    # <br> is the line separator inside a Description slice
    ('a<br>b', 'a\nb'),
    ('a<br/>b', 'a\nb'),
    # halfwidth katakana middle dot, as in 第2･4火曜日
    ('第2･4火曜日', '第2・4火曜日'),
])
def test_normalize(text, expected):
    assert _normalize(text) == expected


@pytest.mark.parametrize('text,expected', [
    # order is load-bearing: the ※ sits *inside* the parentheses, so stripping
    # ※-to-end-of-line first would swallow the range that follows them
    ('平日（※祝日を除く）10:00~20:00', '平日10:00~20:00'),
    # the parentheticals this is actually here to discard
    ('10:00~20:00（最終入園15:30）', '10:00~20:00'),
    ('11:00~14:00(L.O.16:30)', '11:00~14:00'),
    ('10:00~20:00 ※予約制', '10:00~20:00'),
    ('なし https://example.com/x', 'なし'),
])
def test_strip_noise(text, expected):
    assert _strip_noise(text) == expected


# --- hours -----------------------------------------------------------------

def test_24_hours_is_always_open():
    weekly, always_open = _parse_hours('24時間営業')
    assert always_open is True
    assert weekly == {d: [[0, 1440]] for d in WEEKDAYS + ['sat', 'sun', 'hol']}


def test_nennaimukyu_as_the_only_hours_is_always_open():
    """8 entries state only 年中無休 for 営業時間 - all hotels, a ryokan, a
    karaoke box and a Ministop, every one with an empty or 年中無休 定休日."""
    weekly, always_open = _parse_hours('年中無休')
    assert always_open is True
    assert weekly['mon'] == [[0, 1440]]


@pytest.mark.parametrize('text', ['', 'なし', '準備中'])
def test_no_time_range_yields_no_schedule(text):
    """`unknown` is a first-class outcome - inventing hours would be worse."""
    assert _parse_hours(text) == (None, False)


def test_times_are_minutes_from_midnight():
    weekly, _ = _parse_hours('10:00~20:00')
    assert weekly['mon'] == [[600, 1200]]


def test_shift_past_midnight_extends_beyond_1440():
    """11:00~26:00. The frontend looks back a day for end > 1440, so 01:00 still
    reads as open."""
    weekly, _ = _parse_hours('11:00~26:00')
    assert weekly['mon'] == [[660, 1560]]


def test_end_not_after_start_wraps_a_day():
    weekly, _ = _parse_hours('9:00~9:00')
    assert weekly['mon'] == [[540, 1980]]


def test_lunch_break_is_dropped_not_opened():
    """`昼休み13:00~14:00` is a midday *closure*. The rule tier drops it rather
    than inverting its meaning; the override file models the split shift."""
    weekly, _ = _parse_hours('11:30~14:00 昼休み13:00~14:00 17:00~21:00')
    assert weekly['mon'] == [[690, 840], [1020, 1260]]


def test_two_day_scopes_separated_only_by_a_space():
    """Day scope is the text *between* consecutive ranges, not a split on
    punctuation - these two scopes have only an ideographic space between them.
    水 is absent from the source, so it gets no hours."""
    weekly, _ = _parse_hours('月・火・木・金・土7:00~13:00　日・祝日9:00~13:30')
    assert weekly['mon'] == [[420, 780]]
    assert weekly['sat'] == [[420, 780]]
    assert weekly['sun'] == [[540, 810]]
    assert weekly['hol'] == [[540, 810]]
    assert weekly['wed'] == []


def test_scoped_lines_do_not_leak_into_each_other():
    weekly, _ = _parse_hours('平日 11:00～20:00<br>土日祝 10:00～20:00')
    assert weekly['mon'] == [[660, 1200]]
    assert weekly['sat'] == [[600, 1200]]
    assert weekly['hol'] == [[600, 1200]]


def test_unscoped_range_backfills_every_day():
    weekly, _ = _parse_hours('10:00~18:00')
    assert all(v == [[600, 1080]] for v in weekly.values())


# --- closed days -----------------------------------------------------------

@pytest.mark.parametrize('text', ['', 'なし', '年中無休'])
def test_no_stated_holidays(text):
    closed, nth, dates, irregular, perm, notes = _parse_holidays(text)
    assert (closed, nth, dates, irregular, perm, notes) == (set(), [], [], False, False, [])


def test_irregular_holidays_close_nothing_specific():
    """不定休 means "irregular holidays" - there is no schedule to extract, so
    the flag is set and no day is marked closed."""
    closed, nth, _, irregular, _, _ = _parse_holidays('不定休')
    assert irregular is True
    assert closed == set()
    assert nth == []


def test_plain_weekday_closure():
    closed, *_ = _parse_holidays('木曜日')
    assert closed == {'thu'}


def test_weekday_range_closure():
    closed, *_ = _parse_holidays('月～金')
    assert closed == set(WEEKDAYS)


@pytest.mark.parametrize('text', ['第2・第4火曜日', '第二・第四火曜日', '第2･4火曜日'])
def test_nth_week_closure_in_every_notation(text):
    _, nth, *_ = _parse_holidays(text)
    assert nth == [{'day': 'tue', 'nth': [2, 4]}]


def test_nth_clause_does_not_also_close_the_weekday_outright():
    """`木曜日・第3水曜日` is closed every Thursday but only the 3rd Wednesday.
    The nth clauses are removed before plain weekdays are read, or Wednesday
    would be closed every week."""
    closed, nth, *_ = _parse_holidays('木曜日・第3水曜日')
    assert closed == {'thu'}
    assert nth == [{'day': 'wed', 'nth': [3]}]


def test_permanently_closed_marker():
    """The 8 shut shops are marked only by this sentence on a later line - which
    is why parse_description keeps every <br> line instead of just the first."""
    *_, perm, _ = _parse_holidays('元旦<br> ※閉店により、終了しました。')
    assert perm is True


def test_specific_dates_are_month_day_strings():
    _, _, dates, *_ = _parse_holidays('元旦')
    assert dates == ['01-01']


def test_date_range_captures_only_its_endpoints():
    """A rule-tier limitation, not a bug to route around here: `12月29日～1月3日`
    yields the two endpoints, not the days between. The four real 年末年始
    entries list all six dates explicitly in hours_parsed.json."""
    _, _, dates, *_ = _parse_holidays('12月29日～1月3日')
    assert dates == ['12-29', '01-03']


def test_parenthetical_caveats_become_notes():
    *_, notes = _parse_holidays('なし(施設メンテナンスによる休館あり)')
    assert notes == ['施設メンテナンスによる休館あり']


def test_only_the_first_line_is_read_for_closed_days():
    """Later lines carry URLs and stamp-location notes, not schedule."""
    closed, *_ = _parse_holidays('木曜日<br>https://example.com/<br>水曜日')
    assert closed == {'thu'}


# --- assembly --------------------------------------------------------------

def test_closed_day_loses_its_hours():
    parsed = rule_based_parse('10:00~18:00', '木曜日')
    assert parsed['weekly']['thu'] == []
    assert parsed['closed'] == ['thu']


def test_nth_closed_day_keeps_its_hours():
    """The day is only shut on some weeks, so the frontend still needs the hours
    to evaluate the others."""
    parsed = rule_based_parse('10:00~18:00', '第2・第4火曜日')
    assert parsed['weekly']['tue'] == [[600, 1080]]
    assert parsed['closed'] == []
    assert parsed['closed_nth'] == [{'day': 'tue', 'nth': [2, 4]}]


def test_rule_tier_is_tagged_auto():
    """This is what app/main.py counts as `unverified` and the frontend toast
    reports, so it must not drift."""
    assert rule_based_parse('10:00~18:00', 'なし')['confidence'] == 'auto'


# --- override key ----------------------------------------------------------

def test_key_separator_keeps_the_two_fields_distinct():
    """The \\x1f between them is why moving text from one field to the other
    changes the hash instead of colliding."""
    assert override_key('a', 'b') != override_key('ab', '')


def test_absent_and_empty_fields_hash_alike():
    """What makes the 三交イン entry (no 営業時間 label at all) stable."""
    assert override_key(None, 'なし') == override_key('', 'なし')


def test_key_is_stable_and_short():
    key = override_key('10:00~18:00', '木曜日')
    assert key == override_key('10:00~18:00', '木曜日')
    assert len(key) == 16
