import re

# labels are not always all present in a given entry's Description (e.g. some
# newer entries have no member or business-hours label), so fields are located
# by position rather than assumed to sit adjacent to a fixed set of neighbors
FIELD_LABELS = ['メンバー／', '住所／', '営業時間／', '定休日／']


def parse_description(text):
    hits = sorted((text.find(label), label) for label in FIELD_LABELS if label in text)
    fields = {}
    for i, (pos, label) in enumerate(hits):
        start = pos + len(label)
        end = hits[i + 1][0] if i + 1 < len(hits) else len(text)
        fields[label] = re.sub('(<br>)+$', '', text[start:end]).strip()

    hours = fields.get('営業時間／', '')\
        .replace('　', '')\
        .replace('：', ':')\
        .replace('~', '～').replace(' ～ ', '～')\
        .replace('<br>', ' ')

    holidays = fields.get('定休日／', '').split('<br>')[0].strip() or 'なし'

    return {
        'member': fields.get('メンバー／', ''),
        'address': fields.get('住所／', '').replace('<br>', ' ').strip(),
        'hours': hours,
        'holidays': holidays,
    }


def extract_img_url(description):
    match = re.findall('<img src="(.*)" height', description)
    return match[0].strip() if match else ''
