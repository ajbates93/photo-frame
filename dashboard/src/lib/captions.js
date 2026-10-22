const MONTHS = ['JANUARY', 'FEBRUARY', 'MARCH', 'APRIL', 'MAY', 'JUNE', 'JULY',
  'AUGUST', 'SEPTEMBER', 'OCTOBER', 'NOVEMBER', 'DECEMBER'];

const ago = (n) => `${n} ${n === 1 ? 'YEAR' : 'YEARS'} AGO`;

export function photoCaption(takenAt, place, now) {
  if (!takenAt && !place) return null;
  if (!takenAt) return { kicker: null, place };
  let years = now.getFullYear() - takenAt.getFullYear();
  const sameDay = takenAt.getMonth() === now.getMonth() && takenAt.getDate() === now.getDate();
  if (!sameDay && (now.getMonth() < takenAt.getMonth()
    || (now.getMonth() === takenAt.getMonth() && now.getDate() < takenAt.getDate()))) years -= 1;
  let kicker;
  if (years >= 1 && sameDay) kicker = `ON THIS DAY · ${ago(years)}`;
  else if (years >= 1) kicker = ago(years);
  else kicker = `${MONTHS[takenAt.getMonth()]} ${takenAt.getFullYear()}`;
  return { kicker, place: place || null };
}
