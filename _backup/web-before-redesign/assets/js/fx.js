// Motion and feedback helpers shared by the dashboard: tweens, count-up numbers, scroll reveal,
// a single tooltip for every chart mark ([data-tip]), stacked toasts and the section scroll-spy.
// Everything respects prefers-reduced-motion.
export const REDUCED = matchMedia('(prefers-reduced-motion: reduce)').matches;
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

export const ease = {
  out: t => 1 - Math.pow(1 - t, 3),
  inOut: t => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2),
};

// ---------------------------------------------------------------- tween
const running = new Map();  // keys may be strings or elements
/** Animate a number from `from` to `to`, calling draw(value) each frame. Cancels a tween already
 *  running under the same key, so fast updates (slider drags) never fight each other. */
export function tween(key, from, to, dur, draw, fn = ease.out) {
  if (running.has(key)) cancelAnimationFrame(running.get(key));
  if (REDUCED || from == null || !Number.isFinite(from) || !Number.isFinite(to) || dur <= 0) { draw(to, 1); running.delete(key); return; }
  const t0 = performance.now();
  const step = now => {
    const p = Math.min(1, (now - t0) / dur);
    draw(from + (to - from) * fn(p), p);
    if (p < 1) running.set(key, requestAnimationFrame(step)); else running.delete(key);
  };
  running.set(key, requestAnimationFrame(step));
}

/** Count an element's number up (or down) to `to`, formatting each frame with fmt. */
export function countUp(el, to, fmt, dur = 900) {
  if (!el) return;
  const from = Number.isFinite(el._v) ? el._v : (to > 0 ? 0 : to);
  el._v = to;
  tween(el, from, to, dur, v => { el.textContent = fmt(v); });
}

// ---------------------------------------------------------------- reveal on scroll
let revealIO;
/** Fade-and-rise blocks marked .reveal the first time they scroll into view. */
export function reveal(root = document) {
  if (REDUCED || !('IntersectionObserver' in window)) { $$('.reveal', root).forEach(el => el.classList.add('in')); return; }
  revealIO ||= new IntersectionObserver(entries => entries.forEach(e => {
    if (e.isIntersecting) { e.target.classList.add('in'); revealIO.unobserve(e.target); }
  }), { rootMargin: '0px 0px -8% 0px', threshold: 0.06 });
  $$('.reveal:not(.in)', root).forEach(el => revealIO.observe(el));
}

/** Run fn once, when el first becomes visible (charts animate when the reader reaches them). */
export function whenVisible(el, fn) {
  if (!el) return;
  if (REDUCED || !('IntersectionObserver' in window)) { fn(); return; }
  const r = el.getBoundingClientRect();
  if (r.top < innerHeight && r.bottom > 0) { fn(); return; }
  const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) { io.disconnect(); fn(); } }, { threshold: 0.05 });
  io.observe(el);
}

// ---------------------------------------------------------------- tooltip for [data-tip]
export function tooltips() {
  const tipEl = document.createElement('div');
  tipEl.className = 'tip'; tipEl.setAttribute('role', 'tooltip');
  document.body.appendChild(tipEl);
  let cur = null;
  const place = (x, y) => {
    const w = tipEl.offsetWidth, h = tipEl.offsetHeight;
    let left = x + 14, top = y + 16;
    if (left + w > innerWidth - 8) left = x - w - 14;
    if (top + h > innerHeight - 8) top = y - h - 12;
    tipEl.style.transform = `translate(${Math.max(8, left)}px, ${Math.max(8, top)}px)`;
  };
  const show = (el, x, y) => {
    cur = el;
    tipEl.innerHTML = esc(el.getAttribute('data-tip')).replace(/\n/g, '<br>');
    tipEl.classList.add('on');
    place(x, y);
  };
  const hide = () => { cur = null; tipEl.classList.remove('on'); };
  document.addEventListener('pointerover', e => {
    const el = e.target.closest?.('[data-tip]');
    if (el && el !== cur) show(el, e.clientX, e.clientY);
    else if (!el && cur) hide();
  });
  document.addEventListener('pointermove', e => { if (cur) place(e.clientX, e.clientY); }, { passive: true });
  document.addEventListener('pointerdown', e => { if (cur && e.pointerType !== 'mouse') setTimeout(hide, 1800); });
  addEventListener('scroll', () => cur && hide(), { passive: true });
  return { show: (text, x, y) => { tipEl.innerHTML = esc(text).replace(/\n/g, '<br>'); tipEl.classList.add('on'); cur = tipEl; place(x, y); }, hide };
}

// ---------------------------------------------------------------- toasts
const ICON = { info: 'i', error: '!', ok: '\u2713', live: '\u25CF' };
/** Stacked toasts. opts.action = { label, run } adds a button; opts.sticky keeps it until closed. */
export function toast(msg, kind = 'info', opts = {}) {
  const host = $('#toasts');
  if (!host) return;
  const t = document.createElement('div');
  t.className = `toast2 ${kind}`;
  t.setAttribute('role', kind === 'error' ? 'alert' : 'status');
  t.innerHTML = `<b class="ti">${ICON[kind] || 'i'}</b><span>${esc(msg)}</span>${opts.action ? `<button type="button">${esc(opts.action.label)}</button>` : ''}<button type="button" class="x" aria-label="Dismiss">\u00d7</button><i class="bar"></i>`;
  const close = () => { t.classList.add('out'); setTimeout(() => t.remove(), 260); };
  if (opts.action) t.querySelector('button').addEventListener('click', () => { opts.action.run(); close(); });
  t.querySelector('.x').addEventListener('click', close);
  host.prepend(t);
  while (host.children.length > 4) host.lastElementChild.remove();
  requestAnimationFrame(() => t.classList.add('show'));
  const ms = opts.sticky ? 0 : (opts.ms || (kind === 'error' ? 8000 : 5200));
  if (ms) { t.style.setProperty('--ms', `${ms}ms`); setTimeout(close, ms); } else t.classList.add('sticky');
  return close;
}

// ---------------------------------------------------------------- nav scroll-spy + progress
export function scrollSpy() {
  const links = $$('.topbar nav a');
  const bar = $('#scroll-progress'), ind = $('#nav-ind');
  const sections = links.map(a => $(a.getAttribute('href'))).filter(Boolean);
  const setActive = id => {
    links.forEach(a => a.classList.toggle('active', a.getAttribute('href') === `#${id}`));
    const a = links.find(l => l.classList.contains('active'));
    if (ind) {
      if (!a) { ind.style.opacity = 0; return; }
      const nav = a.parentElement.getBoundingClientRect(), r = a.getBoundingClientRect();
      ind.style.opacity = 1;
      ind.style.transform = `translateX(${r.left - nav.left + a.parentElement.scrollLeft}px)`;
      ind.style.width = `${r.width}px`;
    }
  };
  let ticking = false;
  const onScroll = () => {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(() => {
      ticking = false;
      const h = document.documentElement;
      if (bar) bar.style.transform = `scaleX(${Math.min(1, h.scrollTop / Math.max(1, h.scrollHeight - h.clientHeight))})`;
      const mid = innerHeight * 0.35;
      let best = null;
      sections.forEach(s => { const r = s.getBoundingClientRect(); if (r.top <= mid && r.bottom > mid) best = s.id; });
      setActive(best);
    });
  };
  addEventListener('scroll', onScroll, { passive: true });
  addEventListener('resize', onScroll);
  onScroll();
}

/** "12 s ago", "4 min ago", "2 h ago" for an ISO timestamp (local time, as the server writes it). */
export function ago(iso) {
  if (!iso) return '';
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return '';
  const s = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (s < 5) return 'just now';
  if (s < 60) return `${s} s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

/** Briefly highlight an element (used when a value changes because of a live update). */
export function pulse(el, cls = 'pulse') {
  if (!el || REDUCED) return;
  el.classList.remove(cls); void el.offsetWidth; el.classList.add(cls);
}
