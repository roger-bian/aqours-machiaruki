"""Decide where the freeform Japanese text breaks into lines, and re-home the
material the source filed under the wrong heading.

An entry's content leaves it by one of three routes: `lines` (stays in its own
field), `extra` (→ その他) and `to_holidays` (営業時間 → 定休日, for closure days
the source wrote into its opening-hours text). All three count toward
reconstructing the source text, which is what keeps a move from becoming a loss.

Two tiers, in order (see `display_lines_for`):

1. `display_lines.json` - reviewed entries keyed by a hash of the *normalized*
   text. `verified` means "committed, therefore read in the diff".
2. `auto_lines` below - one line per author break, URLs isolated, no judgement.

Tier 1 exists because the decision is semantic, not mechanical. Four rounds of
rules could not settle whether `富士急沼津店` is a branch of モスバーガー or
whether `やま弥` is the actual name of 駿陽荘 - and Japanese puts the descriptor
before the name about as often as after (`旅館 浜の家` vs `グランマ シーサイド
店`), so ordering rules don't help either. Nothing about a line break is
unknowable from the source, so there is no `manual` tier here.

**The key hashes the normalized text, not the raw - the opposite of
`app/hours.py`, for the opposite reason.** `hours.py` memoizes raw -> schedule,
where cosmetics are irrelevant to the output, so hashing raw keeps its key
independent of `description.py`'s choices. This module memoizes text -> lines,
where the cosmetics *are* the output, so the key belongs on its actual input.
Key on raw instead and a new substitution in `description.py` leaves every entry
still *matching* while the string it describes has changed - silently stale,
with the frontend rendering these lines rather than the text column. Keyed on
normalized text the same edit is a key miss: auto tier, `unverified_lines`
rises, the データ更新 toast says so.
"""
import hashlib
import json
import os
import re

from app.description import normalize_address, normalize_holidays, normalize_hours

FIELDS = ('name', 'address', 'hours', 'holidays')

_OVERRIDES_PATH = os.path.join(os.path.dirname(__file__), 'display_lines.json')

# keys carrying human-review context only; stripped before the entry reaches
# the DB so they don't ride along in every API response
_REVIEW_KEYS = ('_field', '_names', '_raw', '_text', '_comment', '_duplicate')

URL = re.compile(r'https?://\S+')

# what normalize_holidays() invents when the source carries no 定休日 label
# at all - a claim of "no closing days" the source never made
HOLIDAYS_PLACEHOLDER = 'なし'

# whitespace in any of the forms the source uses: ASCII, ideographic (U+3000)
# and no-break (U+00A0). The last one is not collapsible HTML whitespace, so
# `第一生命保険\xa0 \xa0沼津支社` renders three visible spaces until it is
# normalized here.
_HORIZONTAL = re.compile(r'[^\S\n]+')
_ANY_SPACE = re.compile(r'\s+')

# characters a reviewed entry may drop between lines. Whitespace because a break
# replaces it; the three commas because that is what the rules being retired did
# (`textLines.ts` consumed the `、` it broke on) and dropping it keeps a comma
# off the end of a line.
SKIPPABLE = frozenset(' \t\r\n　\xa0、,，')

# U+FF01 ！ and U+FF1F ？ are excluded from the full-width sweep: the first is
# Love Live branding (`ラブライブ！サンシャイン!!`, which officially mixes the
# two widths) and the second is left with it for consistency.
_KEEP_FULLWIDTH = frozenset('！？')


def _load_overrides():
    if not os.path.exists(_OVERRIDES_PATH):
        return {}
    with open(_OVERRIDES_PATH, encoding='utf-8') as f:
        return json.load(f)


OVERRIDES = _load_overrides()


def _to_halfwidth(text):
    out = []
    for c in text:
        code = ord(c)
        if 0xFF01 <= code <= 0xFF5E and c not in _KEEP_FULLWIDTH:
            out.append(chr(code - 0xFEE0))
        elif c == '㈱':
            out.append('(株)')
        else:
            out.append(c)
    return ''.join(out)


def _space_around_symbols(text):
    """A space where a reader expects one: around `&`, before `(`, after `)`.

    Name-only. The other three fields are full of parentheticals like
    `（最終入館16:00）` where inserting a space would visibly change the text.
    Skipped at the string edges, so `(有)大田呉服店` doesn't gain a leading
    space it would then have to lose again.
    """
    text = re.sub(r'\s*&\s*', ' & ', text)
    text = re.sub(r'(?<=[^\s(])\(', r' (', text)
    text = re.sub(r'\)(?=[^\s)])', r') ', text)
    return text


def _tidy_lines(text):
    """Collapse horizontal whitespace runs, drop blank lines, keep `\\n`."""
    lines = [_HORIZONTAL.sub(' ', line).strip() for line in text.split('\n')]
    return '\n'.join(line for line in lines if line)


def display_text_for(field, raw):
    """The exact string a reviewed entry's lines must reconstruct.

    Deliberately asymmetric per field, and the asymmetry tracks how stable each
    source is. A `<br>` in a `Description` *is* the author's intended break and
    its position is stable, so it survives as a real newline. `<name>`
    whitespace is the opposite: two placemarks carry a literal newline and one
    run emitted them space-joined - the lineage of phantom markers 1411/1478 -
    so every run of it collapses to one space here, before the hash, and both
    forms key identically.
    """
    if field == 'name':
        text = _space_around_symbols(_to_halfwidth(raw or ''))
        return _ANY_SPACE.sub(' ', text).strip()
    if field == 'address':
        return _tidy_lines(normalize_address(raw or '', br='\n'))
    if field == 'hours':
        return _tidy_lines(normalize_hours(raw or '', br='\n'))
    if field == 'holidays':
        return _tidy_lines(normalize_holidays(raw or '', br='\n'))
    raise ValueError(f'unknown field: {field}')


def display_key(field, text):
    """Content-address the normalized text. Field-scoped so editing 営業時間
    invalidates only its own lines, and so identical text dedupes within a field
    (35 locations share `なし` for 定休日, reviewed once)."""
    return hashlib.sha1(f'{field}\x1f{text}'.encode('utf-8')).hexdigest()[:16]


def no_break_candidate(text):
    """True when there is no decision to make: nowhere to break and nothing to
    move. Keeps ~90 no-op entries out of the override file, and keeps the rows
    they belong to out of the `unverified_lines` count forever."""
    return not (_ANY_SPACE.search(text) or URL.search(text)
                or any(c in text for c in '、,，（）()'))


def auto_lines(text):
    """The fallback: honour author breaks, isolate URLs, decide nothing else.

    URL isolation is not cosmetic - `DetailPanel`'s link check is anchored, so it
    only turns a line into an `<a>` when the whole line is the URL. Without this,
    a URL in un-reviewed 定休日 text stops being clickable.
    """
    out = []
    for segment in text.split('\n'):
        position = 0
        for match in URL.finditer(segment):
            before = segment[position:match.start()].strip()
            if before:
                out.append(before)
            out.append(match.group())
            position = match.end()
        rest = segment[position:].strip()
        if rest:
            out.append(rest)
    return out


def display_lines_for(field, raw):
    """Returns `{'lines', 'extra', 'to_holidays', 'confidence'}` - the field's
    own lines plus the two destinations content can be moved to."""
    text = display_text_for(field, raw)
    entry = OVERRIDES.get(display_key(field, text))
    if entry is not None:
        return {
            'lines': list(entry['lines']),
            'extra': list(entry.get('extra', [])),
            'to_holidays': list(entry.get('to_holidays', [])),
            'confidence': entry['confidence'],
        }
    if no_break_candidate(text):
        return {'lines': [text] if text else [], 'extra': [],
                'to_holidays': [], 'confidence': 'verified'}
    return {'lines': auto_lines(text), 'extra': [], 'to_holidays': [],
            'confidence': 'auto'}


def dense(text):
    """The text with every droppable character removed - what must survive."""
    return ''.join(c for c in text if c not in SKIPPABLE)


def entry_problems(key, entry):
    """Every way a reviewed entry can be wrong, as a list of descriptions.

    This is the whole safety story for hand- or LLM-authored lines, so it is
    shared: `tests/test_display_golden.py` asserts it is empty for every
    committed entry, and `tools/gen_display_overrides.py` refuses to write an
    entry that fails it. An entry is only ever allowed to *move whitespace* and
    drop the commas it breaks on - never to paraphrase, translate, invent, or
    silently lose a 店.
    """
    problems = []
    field = entry.get('_field')
    if field not in FIELDS:
        return [f'unknown _field: {field!r}']

    text = entry['_text']
    lines = entry['lines']
    extra = entry.get('extra', [])
    # closure days written into the 営業時間 text belong under 定休日; they leave
    # this entry entirely, so they count toward reconstructing _text like any
    # other destination
    to_holidays = entry.get('to_holidays', [])
    outbound = lines + extra + to_holidays
    duplicated = entry.get('_duplicate', [])

    if display_text_for(field, entry['_raw']) != text:
        problems.append('_text is not display_text_for(_field, _raw)')
    if display_key(field, text) != key:
        problems.append('key does not match _text')
    if entry.get('confidence') != 'verified':
        problems.append(f'confidence is {entry.get("confidence")!r}')
    # 住所 carries stamp-placement notes too (`(スタンプは1Fロビーに設置して
    # あります)`), so it partitions like the other two. Only `name` never does.
    if extra and field == 'name':
        problems.append('name carries extra')
    if to_holidays and field != 'hours':
        problems.append(f'{field} carries to_holidays')
    if no_break_candidate(text):
        problems.append('no-break-candidate text needs no entry')

    # every line traceable to a contiguous run of the source's real characters:
    # no reordering inside a line, nothing inserted
    for line in outbound:
        if not line.strip():
            problems.append('empty line')
        elif line != line.strip():
            problems.append(f'untrimmed line: {line!r}')
        if line and line[0] in '）)、,，':
            problems.append(f'line starts with orphaned punctuation: {line!r}')
        if dense(line) not in dense(text):
            problems.append(f'line is not from the source text: {line!r}')

    # nothing lost and nothing duplicated by accident. Declared duplicates are
    # subtracted first; the one real case is a note that fuses stamp placement
    # with a schedule, so it has to appear in both the field and その他.
    observed = list(dense(''.join(outbound)))
    for line in duplicated:
        if line not in lines or line not in extra:
            problems.append(f'_duplicate not in both lines and extra: {line!r}')
        for c in dense(line):
            if c in observed:
                observed.remove(c)
    if sorted(observed) != sorted(dense(text)):
        problems.append('content does not reconstruct the source text')

    # DetailPanel's link check is anchored, so a URL sharing a line with other
    # text silently stops being clickable
    for url in URL.findall(text):
        if url not in outbound:
            problems.append(f'URL is not on a line of its own: {url}')

    return problems


def build_display_json(raw_by_field):
    """The `display_json` column value, from `{field: raw_text}`.

    `confidence` is the worst of the four fields, so one un-reviewed field marks
    the whole location for review. `extra` is concatenated in FIELDS order,
    which puts 営業時間's extras ahead of 定休日's.

    Closure days the source wrote into its 営業時間 text (`休館日／毎週月曜日…`,
    `ビル休館日／年末年始、点検日`) are re-homed into 定休日 through the 営業時間
    entry's `to_holidays`. Three locations state their closures only there and
    carry no 定休日 label at all, so the panel showed a 定休日 of `なし` -
    `normalize_holidays`'s own default, not the source's word - directly above an
    営業時間 listing the very closures it denied. That placeholder is dropped
    when real closure lines arrive; keeping both would only relocate the
    contradiction.
    """
    results = {f: display_lines_for(f, raw_by_field.get(f, '')) for f in FIELDS}
    moved = [line for f in FIELDS for line in results[f]['to_holidays']]

    out = {'extra': [], 'confidence': 'verified'}
    for field in FIELDS:
        out[field] = list(results[field]['lines'])
        out['extra'].extend(results[field]['extra'])
        if results[field]['confidence'] == 'auto':
            out['confidence'] = 'auto'
    if moved:
        if out['holidays'] == [HOLIDAYS_PLACEHOLDER]:
            out['holidays'] = []
        out['holidays'].extend(moved)
    return out
