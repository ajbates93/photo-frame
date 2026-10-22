import { dayStart, addDays } from '../src/lib/time.js';

const pad = (n) => String(n).padStart(2, '0');

// ISO 8601 with the local offset, e.g. 2026-10-22T09:00:00+01:00
export function iso(d) {
  const off = -d.getTimezoneOffset();
  const sign = off >= 0 ? '+' : '-';
  const a = Math.abs(off);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}` +
    `${sign}${pad(Math.floor(a / 60))}:${pad(a % 60)}`;
}

function at(day, hhmm) {
  const [h, m] = hhmm.split(':').map(Number);
  return new Date(day.getFullYear(), day.getMonth(), day.getDate(), h, m, 0, 0);
}

export function makeFixtureState(now) {
  const today = dayStart(now);
  const tomorrow = addDays(today, 1);
  let n = 0;
  const ev = (calendarId, title, day, from, to, extra = {}) => ({
    id: `e${++n}`,
    calendarId,
    title,
    start: iso(at(day, from)),
    end: iso(at(day, to)),
    allDay: false,
    location: null,
    travelMins: null,
    ...extra,
  });
  const allDay = (calendarId, title, day, days) => ({
    id: `e${++n}`,
    calendarId,
    title,
    start: iso(day),
    end: iso(addDays(day, days)),
    allDay: true,
    location: null,
    travelMins: null,
  });

  const events = [
    ev('alex', 'Gym', today, '06:30', '07:15'),
    ev('alex', 'Stand-up', today, '09:00', '09:30'),
    ev('alex', 'Client call', today, '11:30', '12:30', { location: 'Google Meet' }),
    ev('alex', 'Lunch with Tom', today, '13:00', '14:00', { location: 'Café on the corner' }),
    ev('family', 'School pick-up', today, '15:15', '15:45'),
    ev('family', 'Swimming lessons', today, '17:30', '18:15', { location: 'Leisure centre', travelMins: 20 }),
    ev('alex', "Parents' evening", today, '17:45', '19:00', { location: 'School' }),
    ev('family', 'Bins out', today, '19:00', '19:30'),
    allDay('family', 'Vicky away', tomorrow, 1),
    ev('alex', 'Design review', tomorrow, '10:00', '11:00', { location: 'Office' }),
    ev('alex', 'Dentist', tomorrow, '14:00', '14:45', { location: 'High Street' }),
    ev('family', "Dinner at Mum's", tomorrow, '18:30', '20:30'),
    allDay('family', 'Half term', addDays(today, 2), 3),
  ];

  const hourly = [
    ['10:00', 12, 'cloud', 10],
    ['12:00', 13, 'partly', 10],
    ['14:00', 14, 'cloud', 20],
    ['16:00', 12, 'rain', 70],
    ['18:00', 10, 'rain', 60],
    ['20:00', 9, 'cloud', 20],
  ].map(([t, temp, cond, rainPct]) => ({ time: iso(at(today, t)), temp, cond, rainPct }));

  const yearAgo = new Date(now.getFullYear() - 1, now.getMonth(), now.getDate(), 12, 0, 0, 0);
  const photo = (id, takenAt, place) => ({
    id,
    url: `/api/photos/${id}`,
    takenAt: takenAt ? iso(takenAt) : null,
    place,
    width: 1280,
    height: 800,
  });
  const photos = [
    photo('p1', addDays(today, -400), 'The Lakes'),
    photo('p2', yearAgo, 'Seaside'),
    photo('p3', addDays(today, -200), 'Garden'),
    photo('p4', null, null),
    photo('p5', addDays(today, -90), 'Mountains'),
    photo('p6', null, null),
    photo('p7', addDays(today, -30), 'Seaside'),
    photo('p8', addDays(today, -700), 'The Lakes'),
  ];

  const items = ['Milk', 'Eggs', 'Bin bags', 'Bread', 'Bananas', 'Coffee', 'Washing-up liquid']
    .map((text, i) => ({ id: `s${i + 1}`, text, checked: i === 1 || i === 3 }));

  const mins = (m) => iso(new Date(now.getTime() + m * 60000));
  const nextMonday = addDays(today, ((8 - today.getDay()) % 7) || 7);

  return {
    generatedAt: iso(now),
    timezone: 'Europe/London',
    people: [
      { id: 'alex', name: 'Alex', color: '#3c6fd1' },
      { id: 'vicky', name: 'Vicky', color: '#c2547f' },
    ],
    calendars: [
      { id: 'alex', label: 'Alex', color: '#3c6fd1' },
      { id: 'family', label: 'Family', color: '#d9772e' },
    ],
    events,
    weather: {
      location: 'Home',
      temp: 12,
      cond: 'partly',
      label: 'Cloudy',
      hi: 14,
      lo: 7,
      summary: 'Rain from 4pm. Take a coat for the school run.',
      sunrise: iso(at(today, '07:25')),
      sunset: iso(at(today, '18:10')),
      hourly,
    },
    photos,
    shopping: { items, syncedAt: iso(now), stale: false },
    tasks: [
      { id: 't1', title: 'Pick up Vinted order from garage', assignee: 'alex', due: iso(at(today, '18:00')), done: false },
      { id: 't2', title: 'Book car service', assignee: 'vicky', due: iso(at(tomorrow, '09:00')), done: false },
      { id: 't3', title: 'Water the plants', assignee: 'any', due: null, done: false },
    ],
    plugs: [
      { id: 'pl1', name: 'Lamp', room: 'Living room', on: true, reachable: true, confirm: false, hidden: false },
      { id: 'pl2', name: 'Reading lamp', room: 'Living room', on: false, reachable: true, confirm: false, hidden: false },
      { id: 'pl3', name: 'Desk lamp', room: 'Office', on: true, reachable: true, confirm: false, hidden: false },
      { id: 'pl4', name: 'Bedside lamp', room: 'Bedroom', on: false, reachable: true, confirm: false, hidden: false },
    ],
    speaker: {
      name: 'Kitchen speaker',
      reachable: true,
      playing: true,
      title: 'Morning Mix',
      artist: 'Various',
      volume: 40,
    },
    claude: {
      sessions: [
        { id: 'c1', project: 'photo-frame', state: 'waiting', since: mins(-4) },
        { id: 'c2', project: 'client-app', state: 'working', since: mins(-12) },
      ],
      usage: {
        plan: 'Max',
        session: { pct: 42, resetsAt: mins(78) },
        weekly: { pct: 61, resetsAt: iso(at(nextMonday, '09:00')) },
      },
    },
    screen: { mode: 'on' },
  };
}
