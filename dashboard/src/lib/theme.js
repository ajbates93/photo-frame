// Theme selection. Pure: the manual override lives in main.js.
const FALLBACK_SUNRISE = [7, 0];
const FALLBACK_SUNSET = [19, 0];

function onDay(day, [h, m]) {
  return new Date(day.getFullYear(), day.getMonth(), day.getDate(), h, m, 0, 0);
}

export function themeFor(now, sunrise, sunset) {
  const rise = sunrise || onDay(now, FALLBACK_SUNRISE);
  const set = sunset || onDay(now, FALLBACK_SUNSET);
  return now >= rise && now < set ? 'paper' : 'night';
}

// The next sunrise/sunset boundary strictly after `now`, given today's times.
// Tomorrow's sunrise is approximated by today's, shifted by a day.
export function nextBoundary(now, sunrise, sunset) {
  const rise = sunrise || onDay(now, FALLBACK_SUNRISE);
  const set = sunset || onDay(now, FALLBACK_SUNSET);
  const tomorrowRise = new Date(rise.getFullYear(), rise.getMonth(), rise.getDate() + 1,
    rise.getHours(), rise.getMinutes(), rise.getSeconds(), 0);
  return [rise, set, tomorrowRise].filter((d) => d > now).sort((a, b) => a - b)[0];
}
