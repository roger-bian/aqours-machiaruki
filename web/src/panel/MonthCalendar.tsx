import { useMemo, useState } from 'react';
import { RING_COLORS } from '../data/markerColors';
import { jstDateFor } from '../data/openStatus';
import {
  WEEKDAY_HEADERS,
  buildMonthGrid,
  dayName,
  monthLabel,
  monthOf,
  shiftMonth,
} from '../data/monthCalendar';
import type { CalendarDay } from '../data/monthCalendar';
import type { HoursJson } from '../data/types';

const GRID_STYLE: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(7, 1fr)',
  gap: 2,
  // digits have to line up in seven columns, the same reason ClockPanel and
  // SearchPanel set it
  fontVariantNumeric: 'tabular-nums',
};

// every cell carries a transparent border so the 不明 one can turn it visible
// without resizing the box, and box-shadow rather than an extra border marks
// today and 祝日 - same trick markerIcon uses to keep the disc its full diameter
const CELL_STYLE: React.CSSProperties = {
  boxSizing: 'border-box',
  border: '1px solid transparent',
  borderRadius: 4,
  height: 28,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  fontSize: 12,
};

const OPEN_STYLE: React.CSSProperties = {
  backgroundColor: RING_COLORS.open ?? '#22c55e',
  color: 'white',
  fontWeight: 'bold',
};

const CLOSED_STYLE: React.CSSProperties = {
  backgroundColor: '#e5e7eb',
  color: '#9ca3af',
};

const UNKNOWN_STYLE: React.CSSProperties = {
  borderColor: '#9ca3af',
  borderStyle: 'dashed',
  color: '#6b7280',
};

const TODAY_RING = 'inset 0 0 0 2px #2563eb';
const HOLIDAY_RULE = 'inset 0 -3px 0 #f59e0b';

// 日 red and 土 blue in the header is the ordinary Japanese calendar convention;
// the cells themselves are carrying openness, so it stays on this row only
const HEADER_COLORS: Record<number, string> = { 0: '#dc2626', 6: '#2563eb' };

const NOTE_STYLE: React.CSSProperties = {
  fontSize: 12,
  color: '#92400e',
  marginBottom: 6,
};

const NAV_BUTTON_STYLE: React.CSSProperties = {
  border: 'none',
  background: 'none',
  font: 'inherit',
  fontSize: 16,
  lineHeight: 1,
  padding: '2px 14px',
  cursor: 'pointer',
  color: '#374151',
};

function opennessStyle(day: CalendarDay): React.CSSProperties {
  if (day.openness === 'open') return OPEN_STYLE;
  if (day.openness === 'closed') return CLOSED_STYLE;
  return UNKNOWN_STYLE;
}

function Cell({ day, isToday }: { day: CalendarDay; isToday: boolean }) {
  const rings = [
    isToday ? TODAY_RING : null,
    day.holiday ? HOLIDAY_RULE : null,
  ].filter(Boolean);
  return (
    <div
      title={day.holiday ?? undefined}
      style={{
        ...CELL_STYLE,
        ...opennessStyle(day),
        ...(rings.length ? { boxShadow: rings.join(', ') } : {}),
      }}
    >
      {day.dayOfMonth}
    </div>
  );
}

function Swatch({ style, label }: { style: React.CSSProperties; label: string }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
      <span
        style={{
          ...style,
          boxSizing: 'border-box',
          width: 12,
          height: 12,
          borderRadius: 3,
          border: style.borderColor ? '1px dashed #9ca3af' : undefined,
        }}
      />
      {label}
    </span>
  );
}

type Props = {
  hours: HoursJson;
  now: Date;
};

/** Which days this month the location is open at all - the planning question the
 *  status badge cannot answer. Presentation only; every rule lives in
 *  data/monthCalendar.ts, which is where it can be tested. */
export function MonthCalendar({ hours, now }: Props) {
  const [shown, setShown] = useState(() => monthOf(now));
  // `now` ticks every 60s in App.tsx, but the grid itself is clock-free -
  // excluding it from the deps keeps a tick from rebuilding all ~30-42 days
  const grid = useMemo(
    () => buildMonthGrid(hours, shown.year, shown.month),
    [hours, shown.year, shown.month],
  );
  const today = jstDateFor(now);

  function step(delta: number) {
    setShown((prev) => shiftMonth(prev.year, prev.month, delta));
  }

  return (
    <div>
      {/* 不定休 means the closures were never written down, so the grid can only
          show the stated pattern. notes are not repeated here - StatusBadge
          already renders them a few rows above. */}
      {hours.irregular && (
        <div style={NOTE_STYLE}>⚠️ 不定休あり。記載のない休みがある場合があります</div>
      )}
      {grid.unknownDays.length > 0 && (
        <div style={NOTE_STYLE}>
          ⚠️ {grid.unknownDays.map(dayName).join('・')}の営業時間は記載がありません
        </div>
      )}

      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 6,
        }}
      >
        <button type="button" onClick={() => step(-1)} aria-label="前の月" style={NAV_BUTTON_STYLE}>
          ‹
        </button>
        <b style={{ fontVariantNumeric: 'tabular-nums' }}>{monthLabel(grid)}</b>
        <button type="button" onClick={() => step(1)} aria-label="次の月" style={NAV_BUTTON_STYLE}>
          ›
        </button>
      </div>

      <div style={{ ...GRID_STYLE, fontSize: 11, marginBottom: 2 }}>
        {WEEKDAY_HEADERS.map((label, i) => (
          <div key={label} style={{ textAlign: 'center', color: HEADER_COLORS[i] }}>
            {label}
          </div>
        ))}
      </div>

      <div style={GRID_STYLE}>
        {Array.from({ length: grid.leadingBlanks }, (_, i) => (
          <div key={`blank-${i}`} />
        ))}
        {grid.days.map((day) => (
          <Cell key={day.date} day={day} isToday={day.date === today} />
        ))}
      </div>

      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: 10,
          fontSize: 11,
          color: '#6b7280',
          marginTop: 6,
        }}
      >
        <Swatch style={OPEN_STYLE} label="営業" />
        <Swatch style={CLOSED_STYLE} label="休み" />
        {grid.unknownDays.length > 0 && <Swatch style={UNKNOWN_STYLE} label="不明" />}
      </div>
    </div>
  );
}
