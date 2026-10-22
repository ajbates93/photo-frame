import '../css/views/control.css';
import { icon } from '../ui/icons.js';
import { esc, setHtml } from '../ui/html.js';

const VOL_STEP = 10;
const clampVol = (v) => Math.max(0, Math.min(100, v));

const SKELETON = `
<div class="control">
  <h2>Control</h2>
  <div class="ctl-body">
    <div class="ctl-rooms"></div>
    <div class="ctl-speaker"></div>
  </div>
  <div class="sheet" hidden>
    <div class="sheet-back"></div>
    <div class="sheet-card" role="dialog" aria-modal="true">
      <h3 class="ctl-confirm-title"></h3>
      <div class="ctl-actions">
        <button type="button" class="ctl-btn sheet-close">Cancel</button>
        <button type="button" class="ctl-btn ctl-danger" data-confirm>Turn off</button>
      </div>
    </div>
  </div>
</div>`;

function roomsHtml(plugs) {
  const rooms = [];
  const byRoom = new Map();
  (plugs || []).filter((p) => !p.hidden).forEach((p) => {
    const room = p.room || 'Other';
    if (!byRoom.has(room)) { byRoom.set(room, []); rooms.push(room); }
    byRoom.get(room).push(p);
  });
  if (!rooms.length) return '<div class="ctl-empty">No devices</div>';
  return rooms.map((room) => `<div class="ctl-room" data-room="${esc(room)}"><div class="ctl-room-name">${esc(room)}</div><div class="ctl-plugs">`
    + byRoom.get(room).map((p) => `<button type="button" class="cplug${p.on ? ' on' : ''}${p.reachable ? '' : ' is-off'}" data-plug="${esc(p.id)}"${p.reachable ? '' : ' disabled'}>`
      + `${icon('bulb', 30)}<span class="cplug-name">${esc(p.name)}</span>`
      + `<span class="cplug-state">${p.reachable ? (p.on ? 'On' : 'Off') : 'Offline'}</span></button>`).join('')
    + '</div></div>').join('');
}

function speakerHtml(sp) {
  if (!sp) return '<div class="lbl">Speaker</div><div class="ctl-empty">Speaker unavailable</div>';
  const dis = sp.reachable ? '' : ' disabled';
  const vol = clampVol(Math.round(Number(sp.volume) || 0));
  const now = sp.reachable
    ? (sp.title ? `<div class="sp-title">${esc(sp.title)}</div>${sp.artist ? `<div class="sp-artist">${esc(sp.artist)}</div>` : ''}`
      : '<div class="sp-title sp-idle">Nothing playing</div>')
    : '<div class="sp-title sp-idle">Offline</div>';
  return `<div class="lbl">${esc(sp.name)}</div>${now}`
    + `<button type="button" class="sp-play" data-sp="${sp.playing ? 'pause' : 'play'}"${dis} aria-label="${sp.playing ? 'Pause' : 'Play'}">${icon(sp.playing ? 'pause' : 'play', 34)}</button>`
    + `<div class="sp-vol"><button type="button" class="sp-step" data-vol="-1"${dis} aria-label="Volume down">${icon('minus', 28)}</button>`
    + `<div class="sp-level"><div class="sp-bar"><i style="width:${vol}%"></i></div><span>${vol}%</span></div>`
    + `<button type="button" class="sp-step" data-vol="1"${dis} aria-label="Volume up">${icon('plus', 28)}</button></div>`;
}

export function createControlView() {
  let q = null;
  let ctx = null;
  let state = null;
  let pendingId = null;

  const $ = (sel) => q.querySelector(sel);

  function render() {
    if (!state || !q) return;
    setHtml($('.ctl-rooms'), roomsHtml(state.plugs));
    setHtml($('.ctl-speaker'), speakerHtml(state.speaker));
  }

  function closeSheet() {
    $('.sheet').hidden = true;
    pendingId = null;
  }

  function onClick(e) {
    const t = e.target;
    if (t.closest('.sheet-close') || t.closest('.sheet-back')) { closeSheet(); return; }
    if (t.closest('[data-confirm]')) {
      const id = pendingId;
      closeSheet();
      if (id) ctx.act('POST', `/api/plugs/${encodeURIComponent(id)}`, { on: false });
      return;
    }
    const plug = t.closest('[data-plug]');
    if (plug) {
      const p = ((state && state.plugs) || []).find((x) => x.id === plug.dataset.plug);
      if (!p || !p.reachable) return;
      if (p.on && p.confirm) {
        pendingId = p.id;
        setHtml($('.ctl-confirm-title'), `Turn off ${esc(p.name)}?`);
        $('.sheet').hidden = false;
        return;
      }
      ctx.act('POST', `/api/plugs/${encodeURIComponent(p.id)}`, { on: !p.on });
      return;
    }
    const sp = state && state.speaker;
    if (!sp || !sp.reachable) return;
    const play = t.closest('[data-sp]');
    if (play) { ctx.act('POST', '/api/speaker', { action: play.dataset.sp }); return; }
    const step = t.closest('[data-vol]');
    if (step) {
      const volume = clampVol((Number(sp.volume) || 0) + Number(step.dataset.vol) * VOL_STEP);
      ctx.act('POST', '/api/speaker', { action: 'volume', volume });
    }
  }

  return {
    mount(el, c) {
      ctx = c;
      q = el;
      el.innerHTML = SKELETON;
      el.addEventListener('click', onClick);
    },
    show(c) {
      if (c) ctx = c;
      closeSheet();
      render();
    },
    hide() { closeSheet(); },
    update(s, c) {
      ctx = c;
      state = s;
      render();
    },
  };
}
