import { useState } from 'react';
import type { Location, OpenStatus } from '../data/types';
import { colorForMember } from '../data/memberColors';
import { RING_COLORS } from '../data/markerColors';
import { closingTimeFor, openStatusFor } from '../data/openStatus';
import { extraLines, linesFor } from '../data/displayLines';

const PANEL_STYLE: React.CSSProperties = {
  display: 'block',
  position: 'fixed',
  top: '50%',
  left: '50%',
  transform: 'translate(-50%, -50%)',
  zIndex: 1000,
  backgroundColor: 'white',
  width: 300,
  maxWidth: '90vw',
  maxHeight: '85vh',
  overflowY: 'auto',
  boxShadow: '0 4px 20px rgba(0, 0, 0, 0.3)',
  borderRadius: 8,
  padding: 16,
  whiteSpace: 'normal',
  textAlign: 'center',
};

const URL_PATTERN = /^https?:\/\//i;

// full width so the whole row is the tap target, not just the label text -
// this panel is mostly used one-handed on a phone
const TOGGLE_STYLE: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  width: '100%',
  boxSizing: 'border-box',
  border: 'none',
  borderRadius: 6,
  backgroundColor: '#f3f4f6',
  padding: '6px 10px',
  font: 'inherit',
  color: 'inherit',
  textAlign: 'left',
  cursor: 'pointer',
  userSelect: 'none',
};

/** One field, collapsed until its label is tapped. Each keeps its own state,
 *  so expanding one leaves the others alone. */
function CollapsibleField({ label, children }: { label: string; children: React.ReactNode }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div style={{ margin: '12px 0' }}>
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        aria-expanded={expanded}
        style={TOGGLE_STYLE}
      >
        <b>{label}</b>
        <span style={{ fontSize: 11 }}>{expanded ? '▲' : '▼'}</span>
      </button>
      {/* textAlign overrides the panel's centered default; the 10px gutter
          matches the header row's padding so both start on the same edge */}
      {expanded && (
        <div style={{ marginTop: 4, padding: '0 10px', textAlign: 'left' }}>{children}</div>
      )}
    </div>
  );
}

/** Pre-broken lines (see pipeline/app/display.py), bare URLs turned into links.
 *  The link check is anchored, so a URL has to occupy its whole line - which is
 *  an invariant of the override corpus, not a hope. */
function WordLines({ lines }: { lines: string[] }) {
  return (
    <>
      {lines.map((line, i) => (
        <span key={i}>
          {URL_PATTERN.test(line) ? (
            <a href={line} target="_blank" rel="noopener noreferrer">
              {line}
            </a>
          ) : (
            line
          )}
          <br />
        </span>
      ))}
    </>
  );
}

function AddressBody({ lines, query }: { lines: string[]; query: string }) {
  // the query keeps the untouched column value - line breaks are for reading
  // only, and rejoining them is lossy (a break consumes the comma it replaced)
  const mapsUrl = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`;
  return (
    <a href={mapsUrl} target="_blank" rel="noopener noreferrer">
      {lines.map((line, i) => (
        <span key={i}>
          {line}
          <br />
        </span>
      ))}
    </a>
  );
}

const STATUS_LABELS: Record<OpenStatus, string | null> = {
  open: '営業中',
  closing_soon: 'まもなく閉店',
  closed: '営業時間外',
  permanently_closed: '閉店しました',
  unknown: null,
};

/** The computed status sits directly above the Japanese text it was derived
 *  from, so a bad parse is visible during ordinary use rather than only when
 *  someone goes looking for it. */
function StatusBadge({ location, now }: { location: Location; now: Date }) {
  const status = openStatusFor(location.hours_json, now);
  const label = STATUS_LABELS[status];
  if (!label) return null;
  const closesAt = status === 'closing_soon' ? closingTimeFor(location.hours_json, now) : null;
  const notes = location.hours_json?.notes ?? [];
  return (
    <div style={{ marginTop: 10 }}>
      <span
        style={{
          display: 'inline-block',
          padding: '2px 10px',
          borderRadius: 999,
          fontSize: 13,
          fontWeight: 'bold',
          color: 'white',
          backgroundColor: RING_COLORS[status] ?? '#6b7280',
        }}
      >
        {label}{closesAt ? ` (${closesAt})` : ''}
      </span>
      {notes.map((note, i) => (
        <div
          key={i}
          style={{
            fontSize: 12,
            color: '#92400e',
            marginTop: 4,
            padding: '0 10px',
            textAlign: 'left',
          }}
        >
          ⚠️ {note}
        </div>
      ))}
    </div>
  );
}

type Props = {
  location: Location;
  now: Date;
  stampPending: boolean;
  badgePending: boolean;
  onToggleStamp: () => void;
  onToggleBadge: () => void;
  onClose: () => void;
};

export function DetailPanel({
  location,
  now,
  stampPending,
  badgePending,
  onToggleStamp,
  onToggleBadge,
  onClose,
}: Props) {
  const extras = extraLines(location);
  return (
    <div style={PANEL_STYLE}>
      <button
        onClick={onClose}
        style={{
          float: 'right',
          border: 'none',
          background: 'none',
          fontSize: 16,
          cursor: 'pointer',
        }}
      >
        ✕
      </button>
      <div style={{ clear: 'both' }}>
        <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, userSelect: 'none' }}>
          <input
            type="checkbox"
            checked={location.stamp}
            onChange={onToggleStamp}
            disabled={stampPending}
          />
          スタンプ
          {stampPending && <span className="spinner" />}
        </label>
        <br />
        <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, userSelect: 'none' }}>
          <input
            type="checkbox"
            checked={location.badge}
            onChange={onToggleBadge}
            disabled={badgePending}
          />
          缶バッジ
          {badgePending && <span className="spinner" />}
        </label>
      </div>
      {location.img_url && (
        <img
          src={location.img_url}
          style={{ width: '100%', marginTop: 10 }}
          onError={(e) => {
            e.currentTarget.style.display = 'none';
          }}
        />
      )}
      {location.member && (
        <p style={{ color: colorForMember(location.member), marginBottom: 0 }}>{location.member}</p>
      )}
      <h3
        style={{
          color: 'darkblue',
          overflowWrap: 'break-word',
          marginTop: 0,
          ...(location.hours_json?.permanently_closed
            ? { color: '#6b7280', textDecoration: 'line-through' }
            : {}),
        }}
      >
        <b>
          {linesFor(location, 'name').map((line, i) => (
            <span key={i}>
              {i > 0 && <br />}
              {line}
            </span>
          ))}
        </b>
      </h3>
      <StatusBadge location={location} now={now} />
      {/* keyed on the location: tapping a second marker keeps this panel
          mounted, and the fields must come back collapsed rather than
          inheriting the previous location's expanded state */}
      <div key={location.id}>
        <CollapsibleField label="住所">
          <AddressBody lines={linesFor(location, 'address')} query={location.address} />
        </CollapsibleField>
        <CollapsibleField label="営業時間">
          <WordLines lines={linesFor(location, 'hours')} />
        </CollapsibleField>
        <CollapsibleField label="定休日">
          <WordLines lines={linesFor(location, 'holidays')} />
        </CollapsibleField>
        {/* everything the source put in 営業時間/定休日/住所 that isn't a
            schedule or an address: parking, URLs, stamp placement, end-of-rally
            markers. Absent entirely for the ~2/3 of locations with none. */}
        {extras.length > 0 && (
          <CollapsibleField label="その他">
            <WordLines lines={extras} />
          </CollapsibleField>
        )}
      </div>
    </div>
  );
}
