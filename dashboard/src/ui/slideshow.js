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

// The two <img> elements exist only while the slideshow runs (start() to stop()),
// so a hidden view holds none: at most two are in the document at any time.
export function createSlideshow(el, { intervalMs = 12000, onChange } = {}) {
  let imgs = null;
  let front = 0;
  let photos = [];
  let queue = [];
  let timer = null;
  let running = false;
  let paused = false;
  let shown = false;
  let token = 0;
  let loadTimer = null;

  function addImages() {
    imgs = [0, 1].map(() => {
      const im = document.createElement('img');
      im.alt = '';
      im.className = 'ss-img';
      im.addEventListener('error', () => im.classList.add('is-broken'));
      el.insertBefore(im, el.firstChild); // under any caption shade the caller adds
      return im;
    });
    front = 0;
  }

  function removeImages() {
    if (!imgs) return;
    imgs.forEach((im) => { im.removeAttribute('src'); im.remove(); });
    imgs = null;
  }

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
    if (!imgs) return;
    const photo = take();
    if (!photo) return;
    const mine = ++token;
    const back = imgs[1 - front];
    let done = false;
    const show = () => {
      if (done || mine !== token || !imgs) return;
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
    clearTimeout(loadTimer);
    loadTimer = setTimeout(show, LOAD_TIMEOUT_MS);
    // Lets a view show portrait photos whole instead of cropping them.
    back.classList.toggle('is-portrait', Number(photo.height) > Number(photo.width));
    back.src = photo.url;
  }

  function halt() {
    clearInterval(timer);
    clearTimeout(loadTimer);
    timer = null;
    loadTimer = null;
  }

  function resume() {
    if (!running || paused || timer) return;
    timer = setInterval(next, intervalMs);
    if (photos.length && !shown) next();
  }

  return {
    setPhotos(list) {
      photos = Array.isArray(list) ? list.filter((p) => p && p.url) : [];
      queue = [];
      if (!photos.length) {
        token += 1;
        shown = false;
        if (imgs) imgs.forEach((im) => { im.classList.remove('is-in'); im.removeAttribute('src'); });
        if (onChange) onChange(null);
        return;
      }
      if (timer && !shown) next();
    },
    start() {
      if (running) return;
      running = true;
      addImages();
      resume();
    },
    stop() {
      running = false;
      halt();
      token += 1;
      shown = false;
      removeImages();
      if (onChange) onChange(null);
    },
    // Paused (screen off): no timers run, the current photo stays; resumes where it left off.
    pause(on) {
      paused = !!on;
      if (paused) halt();
      else resume();
    },
  };
}
