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
KNOWN_HOUR_GAPS = {
    # 平日・土曜 / 土・日曜日 - 祝日 is never mentioned
    '13d2caf1023bb54e': ['hol'],
    # 平日 / 日・祝日 - 土曜 is never mentioned
    '2368d508bd03b7fd': ['sat'],
    # 平日 / 日祝 - 土曜 is never mentioned
    '84438587cb88a86e': ['sat'],
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
    day scope was misread. The five real ones are gaps in the source text."""
    weekly = entry['weekly']
    gaps = [] if weekly is None else [
        d for d in DAYS if not weekly[d] and d not in entry['closed']
    ]
    assert gaps == KNOWN_HOUR_GAPS.get(key, [])
