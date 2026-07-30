"""Tests for app/display.py and the app/display_lines.json corpus.

`display_lines.json` is authored by judgement, not by a rule, so unlike
`hours_parsed.json` there is no rule baseline to diff against and therefore no
analogue of test_hours_golden.py's `divergent == set(CORRECTIONS)` - the
sharpest assertion there would degenerate to `divergent == all keys` here.

What replaces it is content preservation: an entry may only move whitespace
around and drop the commas it breaks on. `entry_problems` is that contract,
shared with tools/gen_display_overrides.py so the generator refuses to write
what this test would reject. It is what makes hand- or LLM-authored lines safe -
a paraphrase, a translation, a dropped 店 or a "fixed" typo all fail it.

Nothing here imports from tools/ (test_hours_golden.py does, which couples
`make test` to the generator's dependencies).
"""
import json
import os

import pytest

from app.description import parse_description
from app.display import (FIELDS, OVERRIDES, _REVIEW_KEYS, auto_lines,
                         build_display_json, dense, display_key,
                         display_lines_for, display_text_for, entry_problems,
                         no_break_candidate)
from app.hours import OVERRIDES as HOURS_OVERRIDES

# mirrors web/src/data/types.ts's DisplayJson - the frontend indexes these
# unconditionally, so a missing key is a runtime error in the panel
CONTRACT_KEYS = set(FIELDS) | {'extra', 'confidence'}

ENTRIES = sorted(OVERRIDES.items())


def _id(key, entry):
    names = entry['_names']
    extra = f'+{len(names) - 1}' if len(names) > 1 else ''
    return f"{entry['_field']}:{names[0]}{extra}"


IDS = [_id(k, e) for k, e in ENTRIES]


# --- the corpus ------------------------------------------------------------

@pytest.mark.parametrize('key,entry', ENTRIES, ids=IDS)
def test_entry_satisfies_the_content_contract(key, entry):
    """The headline test. Covers, per entry: the lines reconstruct the source
    text exactly (nothing paraphrased, invented, dropped or accidentally
    duplicated), each line is a contiguous run of the source's real characters,
    `_text` really is `display_text_for(_field, _raw)`, the key really addresses
    `_text`, every URL sits alone on its line, no line is empty or opens with
    orphaned punctuation, and the entry isn't a no-op the fast path handles."""
    assert entry_problems(key, entry) == []


@pytest.mark.parametrize('key,entry', ENTRIES, ids=IDS)
def test_entry_carries_only_known_keys(key, entry):
    allowed = set(_REVIEW_KEYS) | {'lines', 'extra', 'to_holidays',
                                  'confidence'}
    assert set(entry) <= allowed


def test_no_entry_is_auto():
    """`auto` is what the absence of an entry means, so it must never be
    committed - the same by-construction property hours_parsed.json has."""
    assert [k for k, e in ENTRIES if e['confidence'] != 'verified'] == []


def test_only_hours_entries_re_home_closure_days():
    """営業時間 → 定休日 is the only cross-field move, and only three locations
    need it: each writes its closures into the opening-hours text and carries no
    定休日 label at all, so 定休日 used to read なし directly above them."""
    movers = {k: e['_names'][0] for k, e in ENTRIES if e.get('to_holidays')}
    assert set(movers) == {'cb1ddb425ab60efd', '4ed0c3c91793cd27',
                           'dd05de311ee45434'}
    assert all(OVERRIDES[k]['_field'] == 'hours' for k in movers)


def test_only_the_expected_entry_declares_a_duplicate():
    """Duplication is sanctioned exactly once: a stamp-placement note fused with
    a schedule, which cannot leave 定休日 without taking the times with it. A
    second one appearing means something was copied rather than moved."""
    declared = {k for k, e in ENTRIES if e.get('_duplicate')}
    assert declared == {'be000163cf815822'}


# --- coverage, offline -----------------------------------------------------

def test_every_live_name_hours_and_holidays_is_reviewed():
    """hours_parsed.json carries `_names` plus the raw 営業時間/定休日 for all 136
    locations, so three of the four fields can be checked for full coverage with
    no network. A miss here is not a failure of correctness - it renders on the
    auto tier - but it is the thing `unverified_lines` is counting, and it should
    be zero for the committed corpus."""
    missing = []
    for entry in HOURS_OVERRIDES.values():
        for field, raw in (('hours', entry['_raw_hours']),
                           ('holidays', entry['_raw_holidays'])):
            if display_lines_for(field, raw)['confidence'] != 'verified':
                missing.append((field, entry['_names'][0]))
        for name in entry['_names']:
            if display_lines_for('name', name)['confidence'] != 'verified':
                missing.append(('name', name))
    assert missing == []


def test_every_fixture_address_is_reviewed(placemarks):
    """The fixture is the only offline source of real 住所 values, which is why
    tools/gen_display_overrides.py unions its keys with the live KML's."""
    missing = []
    for _, row in placemarks.iterrows():
        raw = parse_description(row['Description'])['raw_address']
        if display_lines_for('address', raw)['confidence'] != 'verified':
            missing.append(row['Name'])
    assert missing == []


# --- display_text_for ------------------------------------------------------

def test_a_name_newline_and_a_space_normalize_to_the_same_text():
    """The <name> whitespace instability that produced phantom markers
    1411/1478: the same placemark has arrived both ways, so both must key
    identically or the reviewed entry stops matching on a whim."""
    with_newline = display_text_for('name', '海鮮丼と魚河岸定食\nかもめ丸')
    with_space = display_text_for('name', '海鮮丼と魚河岸定食 かもめ丸')
    assert with_newline == with_space == '海鮮丼と魚河岸定食 かもめ丸'


def test_a_name_loses_full_width_ascii_but_keeps_the_love_live_bang():
    assert display_text_for('name', 'ＣＢカレーキッチン') == 'CBカレーキッチン'
    assert display_text_for('name', '㈱千鳥観光汽船') == '(株) 千鳥観光汽船'
    # U+FF01 is the franchise's own styling, which officially mixes widths
    assert display_text_for('name', 'ラブライブ！サンシャイン!!') \
        == 'ラブライブ！サンシャイン!!'


def test_a_no_break_space_run_collapses():
    """Renders as three visible spaces until normalized - U+00A0 is not
    collapsible HTML whitespace."""
    assert display_text_for('name', '第一生命保険\xa0 \xa0沼津支社') \
        == '第一生命保険 沼津支社'


def test_a_source_br_survives_as_a_real_break_in_the_other_fields():
    """A <br> is the author's intended break and its position is stable, unlike
    <name> whitespace - so it is kept rather than flattened."""
    assert display_text_for('holidays', 'なし<br>https://example.com') \
        == 'なし\nhttps://example.com'
    assert '\n' in display_text_for('hours', '10:00～19:00<br>（6月～9月）')


@pytest.mark.parametrize('field', FIELDS)
def test_an_absent_field_still_produces_a_key(field):
    """A missing label must not raise; 定休日 additionally defaults to なし."""
    text = display_text_for(field, '')
    assert text == ('なし' if field == 'holidays' else '')
    assert len(display_key(field, text)) == 16


def test_the_key_is_field_scoped():
    """Editing 営業時間 must not invalidate the 定休日 lines of the same row."""
    assert display_key('hours', 'なし') != display_key('holidays', 'なし')


# --- the auto tier ---------------------------------------------------------

def test_the_auto_tier_isolates_a_url():
    """DetailPanel's link check is anchored on the whole line, so a URL sharing
    a line with other text silently stops being clickable."""
    assert auto_lines('なし\n年中無休 https://example.com/x') == [
        'なし', '年中無休', 'https://example.com/x']


def test_the_auto_tier_decides_nothing_else():
    text = 'カラオケ ラジオシティー 沼津駅北店'
    assert auto_lines(text) == [text]


def test_a_miss_falls_back_to_auto():
    result = display_lines_for('holidays', '毎週水曜日、ただし架空<br>https://x.example')
    assert result['confidence'] == 'auto'
    assert result['extra'] == []
    assert result['lines'] == ['毎週水曜日、ただし架空', 'https://x.example']


def test_text_with_nothing_to_decide_is_verified_without_an_entry():
    """~90 values are a single unbreakable token (`なし`, `水曜日`, most names).
    An entry for them would be a no-op, and counting them as un-reviewed would
    keep `unverified_lines` permanently non-zero."""
    assert no_break_candidate('なし')
    assert display_lines_for('holidays', 'なし') == {
        'lines': ['なし'], 'extra': [], 'to_holidays': [],
        'confidence': 'verified'}


def test_empty_text_produces_no_lines():
    assert display_lines_for('hours', '') == {
        'lines': [], 'extra': [], 'to_holidays': [], 'confidence': 'verified'}


# --- the column value ------------------------------------------------------

def test_build_display_json_matches_the_frontend_contract():
    value = build_display_json({'name': 'ゲーマーズ沼津店', 'address': '沼津市添地町72',
                                'hours': '11:00～20:00', 'holidays': 'なし'})
    assert set(value) == CONTRACT_KEYS
    assert all(isinstance(value[f], list) for f in FIELDS)
    assert value['confidence'] == 'verified'


def test_closure_days_move_from_hours_to_holidays():
    """The 歴史民俗資料館 case: four 休館日 clauses out of 営業時間, and the
    invented なし placeholder dropped rather than left contradicting them."""
    value = build_display_json({
        'name': '沼津市歴史民俗資料館', 'address': '沼津市下香貫島郷2802-1',
        'hours': '9:00～16:00<br>休館日／毎週月曜日（祝日は開館）、毎月最終の平日、'
                 '祝日の翌日（土曜日・日曜日を除く）、年末年始（12月29日～1月3日）'
                 '<br>入館料／無料（※ただし御用邸記念公園への入園料大人100円、'
                 '小・中学生50円が必要です）',
        'holidays': ''})
    assert value['hours'] == ['9:00～16:00']
    assert value['holidays'] == ['休館日／毎週月曜日（祝日は開館）', '毎月最終の平日',
                                 '祝日の翌日（土曜日・日曜日を除く）',
                                 '年末年始（12月29日～1月3日）']
    assert 'なし' not in value['holidays']
    assert value['extra'][0] == '入館料／無料'


def test_the_holidays_placeholder_survives_when_nothing_moves():
    """`なし` is only dropped to make room for real closure days."""
    value = build_display_json({'name': 'x', 'address': '', 'hours': '', 'holidays': ''})
    assert value['holidays'] == ['なし']


def test_one_unreviewed_field_marks_the_whole_location():
    value = build_display_json({'name': 'ゲーマーズ沼津店', 'address': '沼津市添地町72',
                                'hours': '架空 11:00～20:00、13:00～14:00',
                                'holidays': 'なし'})
    assert value['confidence'] == 'auto'


def test_extra_is_concatenated_across_fields():
    """Field order puts 営業時間's extras ahead of 定休日's. Both raw strings are
    real corpus values, so both resolve to reviewed entries - an invented
    combination would fall to the auto tier and contribute no extra at all."""
    raw = {'name': 'x', 'address': '',
           'hours': '平日10:00～18:45、土日祝10:00～18:00<br>https://twitter.com/hicreate1',
           'holidays': 'なし<br>※スタンプは1階 水口園茶店に設置してあります。'}
    value = build_display_json(raw)
    assert value['extra'] == ['https://twitter.com/hicreate1',
                              '※スタンプは1階 水口園茶店に設置してあります。']


def test_review_keys_never_reach_the_column():
    for entry in OVERRIDES.values():
        result = display_lines_for(entry['_field'], entry['_raw'])
        assert not [k for k in result if k.startswith('_')]


# --- the corpus file itself ------------------------------------------------

def test_the_corpus_is_sorted_and_stably_ordered():
    """Keeps the git diff - the actual review surface - readable."""
    path = os.path.join(os.path.dirname(__file__), '..', 'app',
                        'display_lines.json')
    with open(path, encoding='utf-8') as f:
        raw = json.load(f)
    assert list(raw) == sorted(raw)
    order = ['_field', '_names', '_raw', '_text', '_comment', '_duplicate',
             'lines', 'extra', 'to_holidays', 'confidence']
    for entry in raw.values():
        assert list(entry) == [k for k in order if k in entry]


def test_dense_drops_exactly_the_droppable_characters():
    assert dense('あ、 い\nう') == 'あいう'
