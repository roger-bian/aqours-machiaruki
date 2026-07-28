import type { Location, OpenStatus } from '../data/types';
import { colorForMember } from '../data/memberColors';
import { RING_COLORS } from '../data/markerColors';
import { closingTimeFor, openStatusFor } from '../data/openStatus';

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

function LabeledField({ label, value }: { label: string; value: string }) {
  const words = value.split(/\s+/).filter(Boolean);
  return (
    <p>
      <b>[{label}]</b>
      <br />
      {words.map((word, i) => (
        <span key={i}>
          {URL_PATTERN.test(word) ? (
            <a href={word} target="_blank" rel="noopener noreferrer">
              {word}
            </a>
          ) : (
            word
          )}
          <br />
        </span>
      ))}
    </p>
  );
}

function AddressField({ label, value }: { label: string; value: string }) {
  const words = value.split(/\s+/).filter(Boolean);
  const mapsUrl = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(value)}`;
  return (
    <p>
      <b>[{label}]</b>
      <br />
      <a href={mapsUrl} target="_blank" rel="noopener noreferrer">
        {words.map((word, i) => (
          <span key={i}>
            {word}
            <br />
          </span>
        ))}
      </a>
    </p>
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
        <div key={i} style={{ fontSize: 12, color: '#92400e', marginTop: 4 }}>
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
        <b>{location.name}</b>
      </h3>
      <StatusBadge location={location} now={now} />
      <AddressField label="住所" value={location.address} />
      <LabeledField label="営業時間" value={location.hours} />
      <LabeledField label="定休日" value={location.holidays} />
    </div>
  );
}
