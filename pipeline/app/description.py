import re

# labels are not always all present in a given entry's Description (e.g. some
# newer entries have no member or business-hours label), so fields are located
# by position rather than assumed to sit adjacent to a fixed set of neighbors
FIELD_LABELS = ['メンバー／', '住所／', '営業時間／', '定休日／']


def normalize_hours(text, br=' '):
    """The cosmetic pass over 営業時間. `br` is what a source `<br>` becomes: a
    space for the display column, a newline for `app/display.py`, which needs
    the author's break positions. One definition so the two can never drift."""
    return text\
        .replace('　', '')\
        .replace('：', ':')\
        .replace('~', '～').replace(' ～ ', '～')\
        .replace('<br>', br)


def normalize_holidays(text, br=' '):
    return text.replace('<br>', br).strip() or 'なし'


def normalize_address(text, br=' '):
    return text.replace('<br>', br).strip()


def parse_description(text):
    hits = sorted((text.find(label), label) for label in FIELD_LABELS if label in text)
    fields = {}
    for i, (pos, label) in enumerate(hits):
        start = pos + len(label)
        end = hits[i + 1][0] if i + 1 < len(hits) else len(text)
        fields[label] = re.sub('(<br>)+$', '', text[start:end]).strip()

    # the untouched slices, kept alongside the display strings because
    # app/hours.py content-addresses the *raw* text - normalizing first would
    # make the hash depend on this function's cosmetic choices
    raw_hours = fields.get('営業時間／', '')
    raw_holidays = fields.get('定休日／', '')

    raw_address = fields.get('住所／', '')

    hours = normalize_hours(raw_hours)

    # every line is kept: this used to be `.split('<br>')[0]`, which silently
    # dropped the `※閉店により、終了しました。` marker on the 8 closed shops and
    # the stamp-location notes on several others
    holidays = normalize_holidays(raw_holidays)

    return {
        'member': fields.get('メンバー／', ''),
        'address': normalize_address(raw_address),
        'hours': hours,
        'holidays': holidays,
        'raw_address': raw_address,
        'raw_hours': raw_hours,
        'raw_holidays': raw_holidays,
    }


def extract_img_url(description):
    # [^"]* rather than .* - the greedy version spanned from the first tag's src
    # to the last tag's ` height` when a Description carried two <img> tags,
    # producing one merged non-URL. Every entry has a single photo today, so this
    # never fired; it would have been a broken <img src> in the detail panel
    # rather than an error.
    match = re.search(r'<img src="([^"]*)" height', description)
    return match.group(1).strip() if match else ''
