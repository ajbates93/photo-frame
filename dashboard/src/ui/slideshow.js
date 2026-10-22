// Photo slideshow, ported from Wes Bos's dashboard (MIT; see NOTICE.md).
// Trimmed to a two-<img> cross-fade; the caller renders captions via onChange.
const LOAD_TIMEOUT_MS = 2500;

function shuffle(a) {
  for (let i = a.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

function onThisDay(p, now) {
  if (!p.takenAt) return false;
  const d = new Date(p.takenAt);
  return d.getMonth() === now.getMonth() && d.getDate() === now.getDate()
    && d.getFullYear() < now.getFullYear();
}

export function createSlideshow(el, { intervalMs = 12000, onChange } = {}) {
  const imgs = [0, 1].map(() => {
    const im = document.createElement('img');
    im.alt = '';
    im.className = 'ss-img';
    im.addEventListener('error', () => im.classList.add('is-broken'));
    el.appendChild(im);
    return im;
  });
  let front = 0;
  let photos = [];
  let queue = [];
  let timer = null;
  let shown = false;
  let token = 0;

  function take() {
    if (!queue.length) {
      const now = new Date();
      // On-this-day photos come first in a fresh cycle.
      queue = shuffle(photos.slice())
        .sort((a, b) => (onThisDay(b, now) ? 1 : 0) - (onThisDay(a, now) ? 1 : 0));
    }
    return queue.shift() || null;
  }

  function next() {
    const photo = take();
    if (!photo) return;
    const mine = ++token;
    const back = imgs[1 - front];
    let done = false;
    const show = () => {
      if (done || mine !== token) return;
      done = true;
      back.classList.remove('is-broken');
      back.classList.add('is-in');
      imgs[front].classList.remove('is-in');
      front = 1 - front;
      shown = true;
      if (onChange) onChange(photo);
    };
    back.addEventListener('load', show, { once: true });
    back.addEventListener('error', show, { once: true });
    setTimeout(show, LOAD_TIMEOUT_MS);
    back.src = photo.url;
  }

  function restart() {
    clearInterval(timer);
    timer = setInterval(next, intervalMs);
  }

  return {
    setPhotos(list) {
      photos = Array.isArray(list) ? list.filter((p) => p && p.url) : [];
      queue = [];
      if (!photos.length) {
        token += 1;
        shown = false;
        imgs.forEach((im) => { im.classList.remove('is-in'); im.removeAttribute('src'); });
        if (onChange) onChange(null);
        return;
      }
      if (timer && !shown) next();
    },
    start() {
      if (timer) return;
      restart();
      if (photos.length && !shown) next();
    },
    stop() {
      clearInterval(timer);
      timer = null;
    },
  };
}
