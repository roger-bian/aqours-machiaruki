"""Regenerate app/display_lines.json from the live KML plus the test fixture.

Run from the pipeline directory (it needs the `aqours` virtualenv):
    python tools/gen_display_overrides.py

Baseline is the auto tier - author breaks honoured, URLs isolated, nothing else
decided. Those stubs are then rewritten by hand/LLM: the whole point of the file
is the judgement calls, and the git diff is the review.

Re-run to pick up new KML text: existing keys keep whatever is already in the
committed file, so reviewed entries survive regeneration. An entry that fails
`entry_problems` is dropped rather than written, so a bad stub shows up as a
rising `unverified_lines` count instead of as a silently wrong `verified`.

Unlike tools/gen_hours_overrides.py this unions the keys of
tests/fixtures/sample.kml with the live KML's. The fixture is the only offline
source of real *addresses*, so tests/test_display_golden.py checks coverage
against it; building from the live KML alone would let an upstream text edit
delete the entry that check depends on and turn it red for a non-bug.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.description import parse_description
from app.display import (FIELDS, auto_lines, display_key, display_text_for,
                         entry_problems, no_break_candidate)
from app.kml import fetch_kml, load_placemarks

OUT = os.path.join(os.path.dirname(__file__), '..', 'app', 'display_lines.json')
FIXTURE = os.path.join(os.path.dirname(__file__), '..', 'tests', 'fixtures',
                       'sample.kml')

# stable field order so git diffs stay readable
ORDER = ['_field', '_names', '_raw', '_text', '_comment', '_duplicate',
         'lines', 'extra', 'to_holidays', 'confidence']

# the destination arrays are what a reviewer reads, so they stay exploded
# even though _dump would happily compact them onto one line
EXPLODE = ('lines', 'extra', 'to_holidays')


def _dump(obj):
    """json.dump with indent, but leaf arrays kept on one line except EXPLODE.

    Placeholders are swapped in before dumping and swapped back after, so no
    regex ever runs over the real JSON. Same trick as gen_hours_overrides.py,
    with the key-aware exception - compacting a nine-line `lines` array onto one
    ~200-character line would destroy the review surface this file exists for.
    """
    stash = {}

    def compact(node, key=None):
        if isinstance(node, dict):
            return {k: compact(v, k) for k, v in node.items()}
        if isinstance(node, list):
            if key in EXPLODE:
                return [compact(x) for x in node]
            if all(not isinstance(x, (dict, list)) for x in node):
                token = f'\x00{len(stash)}\x00'
                stash[token] = json.dumps(node, ensure_ascii=False)
                return token
            return [compact(x) for x in node]
        return node

    text = json.dumps(compact(obj), ensure_ascii=False, indent=1)
    for token, literal in stash.items():
        text = text.replace(json.dumps(token), literal)
    return text


def _raws_for(row):
    fields = parse_description(row['Description'])
    return {
        'name': row['Name'],
        'address': fields['raw_address'],
        'hours': fields['raw_hours'],
        'holidays': fields['raw_holidays'],
    }


def main():
    with tempfile.NamedTemporaryFile(suffix='.kml') as tmp:
        fetch_kml(tmp.name)
        live = load_placemarks(tmp.name)
    fixture = load_placemarks(FIXTURE)

    existing = {}
    if os.path.exists(OUT):
        with open(OUT, encoding='utf-8') as f:
            existing = json.load(f)

    out, names, seen_live, skipped = {}, {}, set(), []
    for placemarks, is_live in ((live, True), (fixture, False)):
        for _, row in placemarks.iterrows():
            raws = _raws_for(row)
            for field in FIELDS:
                text = display_text_for(field, raws[field])
                if no_break_candidate(text):
                    continue
                key = display_key(field, text)
                if is_live:
                    seen_live.add(key)
                names.setdefault(key, [])
                if row['Name'] not in names[key]:
                    names[key].append(row['Name'])
                if key in out:
                    continue
                if key in existing:              # keep reviewed entries
                    out[key] = existing[key]
                    continue
                entry = {'_field': field, '_names': None, '_raw': raws[field],
                         '_text': text, 'lines': auto_lines(text),
                         'confidence': 'verified'}
                if field in ('hours', 'holidays'):
                    entry['extra'] = []
                out[key] = entry

    for key, entry in out.items():
        entry['_names'] = names[key]
        out[key] = {k: entry[k] for k in ORDER if k in entry}

    for key in sorted(out):
        problems = entry_problems(key, out[key])
        if problems:
            skipped.append((key, out[key]['_names'], problems))
            del out[key]

    with open(OUT, 'w', encoding='utf-8') as f:
        f.write(_dump(dict(sorted(out.items()))))
        f.write('\n')

    stale = set(existing) - set(out)
    fixture_only = set(out) - seen_live
    print(f'wrote {len(out)} entries')
    for field in FIELDS:
        print(f'  {field}: {sum(1 for e in out.values() if e["_field"] == field)}')
    if fixture_only:
        print(f'   {len(fixture_only)} present only in the fixture, not the '
              f'live KML: {sorted(fixture_only)}')
    if stale:
        print(f'!! {len(stale)} committed keys no longer in either source '
              f'(upstream text changed?): {sorted(stale)}')
    for key, entry_names, problems in skipped:
        print(f'!! dropped {key} ({"/".join(entry_names)}): {problems}')


if __name__ == '__main__':
    main()
