import { useEffect, useState } from 'react';
import { holidayNameInJst } from '../data/openStatus';

const PANEL_STYLE: React.CSSProperties = {
  position: 'fixed',
  bottom: 20,
  left: 10,
  zIndex: 900,
  backgroundColor: 'white',
  padding: '6px 10px',
  borderRadius: 8,
  boxShadow: '0 2px 8px rgba(0, 0, 0, 0.3)',
  fontSize: 14,
  fontVariantNumeric: 'tabular-nums',
  userSelect: 'none',
};

// Asia/Tokyo, not the device timezone - same reasoning as data/openStatus.ts:
// this clock is the one the open/closed rings are evaluated against, so it has
// to agree with them wherever the phone thinks it is. `weekday: 'short'` in
// ja-JP is the single kanji (火), which is what we want.
const JST_CLOCK = new Intl.DateTimeFormat('ja-JP', {
  timeZone: 'Asia/Tokyo',
  weekday: 'short',
  month: 'numeric',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hourCycle: 'h23',
});

function formatJst(at: Date): string {
  const p: Record<string, string> = {};
  for (const { type, value } of JST_CLOCK.formatToParts(at)) p[type] = value;
  // 祝日 is its own schedule category in the source text, so on a holiday the
  // rings follow the 'hol' hours rather than the weekday shown here - naming
  // the holiday is what makes that visible instead of looking like a bad parse.
  const holiday = holidayNameInJst(at);
  const label = holiday ? ` (${holiday})` : '';
  return `${p.weekday} ${p.month}/${p.day}${label} `
    + `${p.hour}:${p.minute}:${p.second}`;
}

// Ticks on its own second-resolution interval rather than reusing App.tsx's
// `now`: that one deliberately advances once a minute because every change
// re-runs the visible-locations memo and busts markerIcon's cache.
export function ClockPanel() {
  const [nowText, setNowText] = useState(() => formatJst(new Date()));

  useEffect(() => {
    const timer = setInterval(() => setNowText(formatJst(new Date())), 1000);
    return () => clearInterval(timer);
  }, []);

  return <div style={PANEL_STYLE}>{nowText}</div>;
}
