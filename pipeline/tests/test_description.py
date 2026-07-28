"""Tests for app/description.py - the parser for each placemark's Description
HTML blob. Pure string in, dict out, no dependencies at all.

The shapes here are taken from real entries in the live KML (see
tests/fixtures/sample.kml), including the ones that omit labels.
"""
from app.description import extract_img_url, parse_description

IMG = '<img src="https://mymaps.usercontent.google.com/hostedimage/m/*/TOKEN?fife=s16383" height="200" width="auto" />'

FULL = (
    f'{IMG}<br><br>メンバー／津島善子<br>住所／沼津市添地町72青秀ビル1階'
    '<br>営業時間／平日 11:00～20:00<br>土日祝 10:00～20:00<br>定休日／なし'
)


def test_all_four_labels():
    fields = parse_description(FULL)
    assert fields['member'] == '津島善子'
    assert fields['address'] == '沼津市添地町72青秀ビル1階'
    assert fields['hours'] == '平日 11:00～20:00 土日祝 10:00～20:00'
    assert fields['holidays'] == 'なし'


def test_result_always_carries_every_key():
    """app/main.py indexes all six unconditionally, so a missing label must
    produce an empty value rather than a KeyError."""
    assert set(parse_description('')) == {
        'member', 'address', 'hours', 'holidays', 'raw_hours', 'raw_holidays',
    }


def test_missing_member_label():
    """Some newer entries have no メンバー label. Fields are located by string
    position rather than by assuming a fixed set of neighbours, so the
    surrounding fields still slice correctly."""
    fields = parse_description(
        f'{IMG}<br><br>住所／沼津市大手町5-3-13<br>営業時間／10:00～19:00<br>定休日／なし')
    assert fields['member'] == ''
    assert fields['address'] == '沼津市大手町5-3-13'
    assert fields['hours'] == '10:00～19:00'


def test_missing_hours_label():
    """三交イン 沼津駅前, a hotel, carries no 営業時間 label at all. This is what
    app/hours.py's `manual` tier exists for, and the empty raw value still
    hashes to a stable override key."""
    fields = parse_description(
        f'{IMG}<br><br>メンバー／黒澤ルビィ<br>住所／沼津市大手町5丁目3番22号<br>定休日／なし')
    assert fields['hours'] == ''
    assert fields['raw_hours'] == ''
    assert fields['holidays'] == 'なし'


def test_absent_holidays_default_to_nashi():
    fields = parse_description('メンバー／高海千歌<br>営業時間／10:00～19:00')
    assert fields['holidays'] == 'なし'


def test_every_holiday_line_is_kept():
    """This used to be `.split('<br>')[0]`, which silently dropped the closure
    marker on the 8 shut shops - they kept showing as ordinary open locations."""
    fields = parse_description(
        '定休日／元旦<br> ※閉店により、終了しました。')
    assert '※閉店により、終了しました。' in fields['holidays']


def test_stamp_location_note_after_the_holidays_is_kept():
    fields = parse_description(
        '営業時間／10:00～20:00<br>定休日／なし<br>'
        '※スタンプは北側1階チケット販売所に設置してあります。')
    assert '※スタンプは北側1階チケット販売所に設置してあります。' in fields['holidays']


def test_raw_fields_are_not_normalized():
    """app/hours.py content-addresses the *raw* text, so normalizing it here
    would make every override key depend on this function's cosmetic choices."""
    fields = parse_description('営業時間／9：00　～　16：00<br>定休日／なし')
    assert fields['raw_hours'] == '9：00　～　16：00'
    # the display string is the normalized one
    assert fields['hours'] == '9:00～16:00'


def test_labels_out_of_source_order():
    """Fields are sliced between sorted label positions, not read in a fixed
    order, so an upstream reordering does not scramble them."""
    fields = parse_description('定休日／木曜日<br>メンバー／桜内梨子<br>住所／沼津市')
    assert fields['holidays'] == '木曜日'
    assert fields['member'] == '桜内梨子'
    assert fields['address'] == '沼津市'


def test_trailing_breaks_are_stripped_per_field():
    fields = parse_description('メンバー／松浦果南<br><br>住所／沼津市')
    assert fields['member'] == '松浦果南'


def test_extract_img_url():
    assert extract_img_url(FULL).endswith('?fife=s16383')


def test_extract_img_url_without_an_image():
    """Every placemark in the live export has one today, so this is the
    defensive path - cache_images() maps '' straight through."""
    assert extract_img_url('メンバー／小原鞠莉<br>住所／沼津市') == ''


def test_extract_img_url_takes_the_first_of_several():
    """A greedy `.*` used to run from the first src to the last ` height`,
    returning one merged non-URL - a broken <img src> in the detail panel rather
    than an error anywhere."""
    two = (
        '<img src="https://example.com/one.jpg" height="200" width="auto" />'
        '<img src="https://example.com/two.jpg" height="200" width="auto" />'
    )
    assert extract_img_url(two) == 'https://example.com/one.jpg'


def test_extract_img_url_never_spans_a_quote():
    assert '"' not in extract_img_url(FULL)
