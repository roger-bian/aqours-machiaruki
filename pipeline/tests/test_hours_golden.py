"""Whole-corpus checks against app/hours_parsed.json.

That file is not just configuration - it carries `_raw_hours`/`_raw_holidays`
next to the expected parse for all 125 keys, which makes it a golden corpus for
free. These tests need no network, no database and no mocks, and they cover the
one thing the frontend actually depends on: that `hours_json` keeps its shape
and that the rule tier still reproduces the entries nobody hand-corrected.
"""
import re

import pytest

from app.hours import (
    DAYS,
    OVERRIDES,
    _REVIEW_KEYS,
    override_key,
    parse_hours_holidays,
    rule_based_parse,
)
from tools.gen_hours_overrides import CORRECTIONS

# every key the frontend's HoursJson type declares (web/src/data/types.ts)
CONTRACT_KEYS = {
    'weekly', 'closed', 'closed_nth', 'closed_dates', 'always_open',
    'irregular', 'permanently_closed', 'confidence', 'notes',
}

ENTRIES = sorted(OVERRIDES.items())
IDS = [f"{k}:{'/'.join(e['_names'])}" for k, e in ENTRIES]

# Days with no hours that are not a stated 定休日. Every one is a gap in the
# source text rather than a parse failure, which is why they are allowlisted
# instead of fixed - but a *new* gap means something broke, so the set is exact.
#
# The two `hol` gaps are resolved at read time rather than here:
# web/src/data/openStatus.ts falls back to the calendar weekday when the source
# never stated a 祝日 schedule, so 明治茶館's 定休日 月～金 closes a Tuesday
# holiday instead of voiding it. That fallback cannot live in this file - which
# weekday a holiday lands on depends on the year.
KNOWN_HOUR_GAPS = {
    # 平日・土曜 / 土・日曜日 - 祝日 is never mentioned
    '13d2caf1023bb54e': ['hol'],
    # 土曜・日曜 only, 定休日 月～金 - 祝日 is never mentioned
    'ebf2af2e0601b7e1': ['hol'],
    # 土日祝 run to 公演終了時間, which is not a time; those days stay empty
    # rather than inventing an end (see CORRECTIONS in gen_hours_overrides.py)
    'fad7f41f61d1de24': ['sat', 'sun', 'hol'],
}


@pytest.mark.parametrize('key,entry', ENTRIES, ids=IDS)
def test_every_entry_satisfies_the_frontend_contract(key, entry):
    """web/src/data/openStatus.ts indexes straight into this structure, so a
    missing key or a malformed interval surfaces as a wrong marker ring rather
    than an error."""
    assert CONTRACT_KEYS <= set(entry), CONTRACT_KEYS - set(entry)
    assert set(entry) <= CONTRACT_KEYS | set(_REVIEW_KEYS)
    assert entry['confidence'] in ('verified', 'manual')

    assert set(entry['closed']) <= set(DAYS)
    for rule in entry['closed_nth']:
        assert rule['day'] in DAYS
        assert all(isinstance(n, int) for n in rule['nth'])
    for date in entry['closed_dates']:
        assert re.fullmatch(r'\d{2}-\d{2}', date), date

    weekly = entry['weekly']
    if weekly is None:
        return
    assert set(weekly) == set(DAYS)
    for day, intervals in weekly.items():
        for start, end in intervals:
            assert isinstance(start, int) and isinstance(end, int)
            # an end past 1440 is an overnight shift; the frontend looks back a
            # day for those, so it must still be a same-day-plus-24h value
            assert 0 <= start < end <= 2880, (day, start, end)


@pytest.mark.parametrize('key,entry', ENTRIES, ids=IDS)
def test_key_matches_its_own_raw_text(key, entry):
    """The file is content-addressed on the raw source text. If the hash scheme
    changes, or someone edits `_raw_hours` by hand, every entry silently stops
    matching and quietly falls back to the rule tier."""
    assert override_key(entry['_raw_hours'], entry['_raw_holidays']) == key


@pytest.mark.parametrize('key,entry', ENTRIES, ids=IDS)
def test_lookup_round_trips_and_strips_review_keys(key, entry):
    parsed = parse_hours_holidays(entry['_raw_hours'], entry['_raw_holidays'])
    assert parsed == {k: v for k, v in entry.items() if k not in _REVIEW_KEYS}
    # `_names`/`_raw_*` are human-review context; they must not ride along into
    # the hours_json column and out through every API response
    assert not [k for k in parsed if k.startswith('_')]


def test_rule_tier_reproduces_all_but_the_hand_fixed_entries():
    """The sharpest invariant available here. The committed file was generated
    by the rule tier and then hand-corrected in 12 places, so the rule tier must
    still reproduce the other 113 exactly - and must still *fail* to reproduce
    those 12, otherwise a correction has gone stale and is overriding data that
    no longer needs it.
    """
    divergent = set()
    for key, entry in OVERRIDES.items():
        expected = {k: v for k, v in entry.items()
                    if k not in _REVIEW_KEYS and k != 'confidence'}
        actual = rule_based_parse(entry['_raw_hours'], entry['_raw_holidays'])
        del actual['confidence']  # 'auto' here vs 'verified'/'manual' there
        if actual != expected:
            divergent.add(key)

    assert divergent == set(CORRECTIONS)


@pytest.mark.parametrize('key,entry', ENTRIES, ids=IDS)
def test_no_new_day_lacks_hours_without_being_closed(key, entry):
    """Ported from the `python -m app.hours` review harness, whose `!!` flag
    marks a day with no hours that is not a stated 定休日 - usually a sign the
    day scope was misread. The remaining ones are gaps in the source text."""
    weekly = entry['weekly']
    gaps = [] if weekly is None else [
        d for d in DAYS if not weekly[d] and d not in entry['closed']
    ]
    assert gaps == KNOWN_HOUR_GAPS.get(key, [])


# 平日 in older Japanese usage covers Saturday (the six-day week), so a source
# scoping hours to 平日 and 日祝 while never naming 土曜 is stating Saturday, not
# omitting it. Narrow on purpose: the inference is only safe when 土 is absent
# *and* 日/祝 got their own scope, which is what says 平日 was meant as
# "everything else" rather than as literal Mon-Fri.
@pytest.mark.parametrize('hours,holidays,expected_sat', [
    # the two real shapes in the corpus (市川, つじ写真館)
    ('平日10:00～18:30<br>日・祝日10:00～18:00', '水曜日', [[600, 1110]]),
    ('平日　9:30～19:00<br> 日祝　9:30～18:00', '水曜日', [[570, 1140]]),
    # 土 stated separately - keeps that scope's hours, never the 平日 ones
    ('平日8:00～21:00<br>土・日曜日10:00～19:00', 'なし', [[600, 1140]]),
    # 土 named in the same group as 日祝 - already covered, must not be rewritten
    ('平日15:00～18:00<br>土日祝11:30～20:00', '', [[690, 1200]]),
    # no 日/祝 scope at all, so 平日 carries no "everything else" reading and
    # Saturday stays unstated rather than being invented
    ('平日10:00～18:00', '', []),
])
def test_weekday_scope_covers_saturday_only_when_it_is_unstated(
        hours, holidays, expected_sat):
    assert rule_based_parse(hours, holidays)['weekly']['sat'] == expected_sat


def test_a_saturday_closure_still_wins_over_the_weekday_reading():
    """The 平日 inference runs inside _parse_hours, before 定休日 is applied, so
    a stated 土曜 closure has to survive it - otherwise the rule would reopen a
    day the source explicitly shuts."""
    parsed = rule_based_parse('平日10:00～18:00<br>日祝10:00～17:00', '土曜日')
    assert 'sat' in parsed['closed']
    assert parsed['weekly']['sat'] == []
