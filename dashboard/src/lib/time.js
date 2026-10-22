const pad = (n) => String(n).padStart(2, '0');

function suffix(h) {
  return h < 12 ? 'am' : 'pm';
}

function hour12(h) {
  return h % 12 === 0 ? 12 : h % 12;
}

export function fmtTime(d) {
  const h = d.getHours();
  return `${hour12(h)}:${pad(d.getMinutes())}${suffix(h)}`;
}

export function fmtHour(h) {
  return `${hour12(h)}${suffix(h)}`;
}

export function fmtRange(a, b) {
  return `${fmtTime(a)}–${fmtTime(b)}`;
}

const DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
  'August', 'September', 'October', 'November', 'December'];

export function fmtDay(d) {
  return DAYS[d.getDay()];
}

export function fmtDate(d) {
  return `${d.getDate()} ${MONTHS[d.getMonth()]}`;
}

export function fmtCountdown(mins) {
  const total = Math.round(mins);
  if (total < 60) return `${total} min`;
  return `${Math.floor(total / 60)}h ${pad(total % 60)}`;
}

export function dayStart(d) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate(), 0, 0, 0, 0);
}

export function addDays(d, n) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate() + n, 0, 0, 0, 0);
}

// Wall-clock hours since local midnight of `day` (DST-safe: uses local fields).
export function hoursSinceDayStart(d, day) {
  const dayDiff = Math.round(
    (Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()) -
      Date.UTC(day.getFullYear(), day.getMonth(), day.getDate())) / 86400000,
  );
  return dayDiff * 24 + d.getHours() + d.getMinutes() / 60;
}
