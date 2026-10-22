import '../css/views/photos.css';
import { photoCaption } from '../lib/captions.js';
import { createSlideshow } from '../ui/slideshow.js';
import { esc, setHtml } from '../ui/html.js';

const INTERVAL_MS = 8000;
const RAIL_HIDE_MS = 5000;

const SKELETON = '<div class="photos"><div class="ph-shade"></div><div class="ph-cap"></div></div>';

export function createPhotosView() {
  let q = null;
  let ctx = null;
  let slideshow = null;
  let photoKey = null;
  let current = null;
  let railTimer = null;
  let root = null;

  const $ = (sel) => q.querySelector(sel);

  function renderCaption() {
    const p = current;
    const c = p ? photoCaption(p.takenAt ? new Date(p.takenAt) : null, p.place, ctx.now()) : null;
    setHtml($('.ph-cap'), c
      ? `${c.kicker ? `<b>${esc(c.kicker)}</b>` : ''}${c.place ? `<span>${esc(c.place)}</span>` : ''}` : '');
  }

  function showRail() {
    clearTimeout(railTimer);
    railTimer = null;
    root.classList.remove('rail-hidden');
  }

  function armRail() {
    showRail();
    railTimer = setTimeout(() => {
      railTimer = null;
      root.classList.add('rail-hidden');
    }, RAIL_HIDE_MS);
  }

  // A tap while the rail is hidden brings it back and restarts the 5 s countdown.
  function onTap() { armRail(); }

  return {
    mount(el, c) {
      ctx = c;
      q = el;
      root = el.ownerDocument.documentElement;
      el.innerHTML = SKELETON;
      el.addEventListener('pointerdown', onTap);
      el.addEventListener('click', onTap);
      slideshow = createSlideshow($('.photos'), {
        intervalMs: INTERVAL_MS,
        onChange: (p) => { current = p; renderCaption(); },
      });
    },

    show(c) {
      if (c) ctx = c;
      slideshow.start();
      armRail();
    },

    hide() {
      slideshow.stop();
      showRail();
    },

    update(s, c) {
      ctx = c;
      const photos = s.photos || [];
      const key = photos.map((p) => p.id).join(',');
      if (key !== photoKey) {
        photoKey = key;
        slideshow.setPhotos(photos);
      }
    },
  };
}
