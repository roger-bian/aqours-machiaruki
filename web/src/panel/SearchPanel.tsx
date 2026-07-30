import { useEffect, useMemo, useState } from 'react';
import type { Map as LeafletMap } from 'leaflet';
import type { Location } from '../data/types';
import { linesFor } from '../data/displayLines';
import { matchRange, numberMatchLength, searchLocations } from '../data/searchLocations';
import { Backdrop } from './Backdrop';

// same disc as map/LocateButton.tsx, in the corner Leaflet's zoom control used
// to hold - MapView passes zoomControl={false} now
const BUTTON_STYLE: React.CSSProperties = {
  position: 'fixed',
  top: 10,
  left: 10,
  zIndex: 900,
  width: 44,
  height: 44,
  borderRadius: '50%',
  backgroundColor: 'white',
  boxShadow: '0 2px 8px rgba(0, 0, 0, 0.3)',
  border: 'none',
  cursor: 'pointer',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  padding: 0,
};

const CARD_STYLE: React.CSSProperties = {
  position: 'fixed',
  top: '35%',
  left: '50%',
  transform: 'translate(-50%, -50%)',
  zIndex: 1000,
  backgroundColor: 'white',
  width: 300,
  maxWidth: '90vw',
  boxShadow: '0 4px 20px rgba(0, 0, 0, 0.3)',
  borderRadius: 8,
  padding: 12,
  fontSize: 14,
  // index.css hides overflow on html/body/#root, so a long list has to scroll
  // inside its own box - it can never fall back to page scroll
  maxHeight: '70vh',
  overflowY: 'auto',
};

// stacks above the search card rather than replacing it, so closing this
// returns to the bar with the query still in it
const OVERFLOW_STYLE: React.CSSProperties = {
  ...CARD_STYLE,
  top: '50%',
  zIndex: 1001,
  maxHeight: '70vh',
  overflowY: 'auto',
};

const INPUT_STYLE: React.CSSProperties = {
  width: '100%',
  boxSizing: 'border-box',
  border: '1px solid #d1d5db',
  borderRadius: 6,
  padding: '8px 10px',
  font: 'inherit',
};

// full width so the whole row is the tap target, matching DetailPanel's
// collapsible headers - this map is used one-handed while walking
const ROW_STYLE: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 8,
  width: '100%',
  boxSizing: 'border-box',
  border: 'none',
  borderRadius: 6,
  backgroundColor: 'transparent',
  padding: '8px 10px',
  font: 'inherit',
  textAlign: 'left',
  cursor: 'pointer',
  userSelect: 'none',
};

const MUTED = '#9ca3af';

// A fixed-width cell rather than shrink-to-fit, so 3, 42 and 136 all end on the
// same edge and the names start on one too - the column is invisible, but a
// ragged one is what a scanning eye notices. Wide enough for three digits,
// which is the whole range (ids are KML positions, ~136 of them).
const NUMBER_STYLE: React.CSSProperties = {
  width: '2.4em',
  flex: 'none',
  textAlign: 'right',
  fontVariantNumeric: 'tabular-nums',
  color: MUTED,
};

// One line per suggestion, clipped with an ellipsis rather than wrapped, so
// every row is the same height and five results always occupy the same box.
// `minWidth: 0` is what makes it work: a flex item's default `min-width: auto`
// refuses to shrink below its content, so the text would overflow the card
// instead of being clipped.
const NAME_STYLE: React.CSSProperties = {
  flex: 1,
  minWidth: 0,
  whiteSpace: 'nowrap',
  overflow: 'hidden',
  textOverflow: 'ellipsis',
};

/** Matches past this go behind the "…" row. */
const MAX_SUGGESTIONS = 5;

// street level, close enough to see the block the stamp is on - the same
// intent as SURROUNDINGS_ZOOM in map/LocateButton.tsx
const RESULT_ZOOM = 17;

/** `text` with the queried run in bold, or plain when nothing matched here -
 *  a row listed on the strength of the *other* spelling of its name has
 *  nothing to bold in the one being shown. */
function Highlighted({ text, range }: { text: string; range: [number, number] | null }) {
  if (!range) return text;
  return (
    <>
      {text.slice(0, range[0])}
      <b>{text.slice(range[0], range[1])}</b>
      {text.slice(range[1])}
    </>
  );
}

type RowProps = {
  location: Location;
  hidden: boolean;
  query: string;
  onPick: () => void;
};

/** One suggestion. Greyed with a 非表示 tag when the filters have taken this
 *  location's pin off the map - selecting it still opens its panel, there is
 *  just nothing to fly to visually. */
function SuggestionRow({ location, hidden, query, onPick }: RowProps) {
  const name = linesFor(location, 'name').join(' ');
  const digits = numberMatchLength(location.id, query);
  return (
    <button
      type="button"
      onClick={onPick}
      style={{ ...ROW_STYLE, ...(hidden ? { color: MUTED } : {}) }}
    >
      <span style={NUMBER_STYLE}>
        {/* a number hit is always a prefix, so the bold run starts at 0 */}
        <Highlighted text={String(location.id)} range={digits > 0 ? [0, digits] : null} />
      </span>
      {/* the ellipsis hides text, so the full name stays reachable on hover */}
      <span style={NAME_STYLE} title={name}>
        <Highlighted text={name} range={matchRange(name, query)} />
      </span>
      {hidden && <span style={{ fontSize: 11, color: MUTED }}>非表示</span>}
    </button>
  );
}

type Props = {
  /** every location, not the filtered subset MapView draws */
  locations: Location[];
  /** ids currently passing the filter panel */
  visibleIds: Set<number>;
  map: LeafletMap | null;
  onSelect: (id: number) => void;
};

/**
 * Name/stamp-number search behind the top-left magnifying glass.
 *
 * Lives here rather than inside MapContainer (where LocateButton sits and calls
 * useMap()) for two reasons: it needs the unfiltered `locations`, `visibleIds`
 * and `onSelect`, none of which MapView has, and a text input inside
 * `.leaflet-container` has its keyboard and scroll events eaten by Leaflet's
 * own handlers. It reaches the map through the ref App holds instead.
 */
export function SearchPanel({ locations, visibleIds, map, onSelect }: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [showOverflow, setShowOverflow] = useState(false);

  const matches = useMemo(() => searchLocations(locations, query), [locations, query]);
  const shown = matches.slice(0, MAX_SUGGESTIONS);
  const overflow = matches.slice(MAX_SUGGESTIONS);

  function close() {
    setOpen(false);
    setQuery('');
    setShowOverflow(false);
  }

  useEffect(() => {
    if (!open) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') close();
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [open]);

  // a query change can shrink the results out from under an open overflow list
  useEffect(() => {
    if (matches.length <= MAX_SUGGESTIONS) setShowOverflow(false);
  }, [matches.length]);

  function pick(location: Location) {
    map?.flyTo([location.lat, location.lon], RESULT_ZOOM);
    onSelect(location.id);
    // close first: this card and DetailPanel are both z-1000, so they must
    // never be on screen together
    close();
  }

  if (!open) {
    return (
      <button style={BUTTON_STYLE} onClick={() => setOpen(true)} aria-label="場所を検索">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#374151" strokeWidth="2">
          <circle cx="11" cy="11" r="7" />
          <path d="M16.5 16.5L21 21" strokeLinecap="round" />
        </svg>
      </button>
    );
  }

  return (
    <>
      <Backdrop onClose={close} />
      <div style={CARD_STYLE}>
        <input
          autoFocus
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="場所名・スタンプ番号"
          aria-label="場所を検索"
          style={INPUT_STYLE}
        />
        {query.trim() !== '' && matches.length === 0 && (
          <p style={{ padding: '8px 10px', color: MUTED }}>該当なし</p>
        )}
        {shown.map((loc) => (
          <SuggestionRow
            key={loc.id}
            location={loc}
            hidden={!visibleIds.has(loc.id)}
            query={query}
            onPick={() => pick(loc)}
          />
        ))}
        {overflow.length > 0 && (
          <button
            type="button"
            onClick={() => setShowOverflow(true)}
            style={{ ...ROW_STYLE, color: MUTED, justifyContent: 'center' }}
            aria-label={`残り${overflow.length}件を表示`}
          >
            …
          </button>
        )}
      </div>
      {showOverflow && (
        <div style={OVERFLOW_STYLE}>
          <button
            onClick={() => setShowOverflow(false)}
            style={{ float: 'right', border: 'none', background: 'none', fontSize: 16, cursor: 'pointer' }}
          >
            ✕
          </button>
          <div style={{ clear: 'both', color: MUTED, padding: '0 10px 4px' }}>
            残り{overflow.length}件
          </div>
          {overflow.map((loc) => (
            <SuggestionRow
              key={loc.id}
              location={loc}
              hidden={!visibleIds.has(loc.id)}
              query={query}
              onPick={() => pick(loc)}
            />
          ))}
        </div>
      )}
    </>
  );
}
