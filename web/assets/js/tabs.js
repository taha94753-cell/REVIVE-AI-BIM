// Tab motion shared by every page (landing, workspace, phone). Motion (web/vendor/motion/motion.js, the
// engine behind Framer Motion, loaded before this module) moves everything:
//   plate(el, tab)      slide and resize a highlight under a tab, measured from the tab itself
//   segs(root)          every .seg group gets a thumb that follows aria-pressed / -checked / -selected
//   enter(panel, dir)   a panel arrives from the side its tab sits on, its blocks settle in order
//   roving(list, tabs)  arrow keys, Home and End move between tabs, so a tab list is one tab stop
// Under prefers-reduced-motion plates jump and panels only fade.
const M = globalThis.Motion;
export const REDUCED = matchMedia('(prefers-reduced-motion: reduce)').matches;
export const EASE = [0.22, 1, 0.36, 1];
export const SPRING = { type: 'spring', stiffness: 520, damping: 42 };
const NOW = { duration: 0 };

const last = v => (Array.isArray(v) ? v[v.length - 1] : v);
const px = v => (typeof v === 'number' ? `${v}px` : v);

/** Motion's animate(), or the end state at once when motion is reduced or the library did not load. */
export function to(el, keyframes, opts = SPRING) {
  if (!el) return null;
  if (M) return M.animate(el, keyframes, REDUCED ? NOW : opts);
  for (const node of el instanceof Element ? [el] : el) {
    const k = Object.fromEntries(Object.entries(keyframes).map(([p, v]) => [p, last(v)]));
    if ('x' in k || 'y' in k) node.style.transform = `translate(${px(k.x ?? 0)}, ${px(k.y ?? 0)})`;
    for (const p of ['width', 'height', 'opacity', 'filter']) if (p in k) node.style[p] = px(k[p]);
  }
  return null;
}

/** Highlight `tab`: the plate takes the tab's measured box (first placement and hidden lists snap). */
export function plate(el, tab, { instant = false } = {}) {
  if (!el || !tab || !tab.offsetWidth) return;
  const box = { x: tab.offsetLeft, y: tab.offsetTop, width: tab.offsetWidth, height: tab.offsetHeight, opacity: 1 };
  to(el, box, instant || !el.dataset.placed ? NOW : SPRING);
  el.dataset.placed = '1';
}

const ON = ':scope > button[aria-pressed="true"], :scope > button[aria-checked="true"], :scope > button[aria-selected="true"]';

/** Give every .seg group a sliding thumb. It follows the aria state the page already sets, so callers change nothing. */
export function segs(root = document) {
  root.querySelectorAll('.seg').forEach(seg => {
    if (seg.__thumb) return;
    const thumb = document.createElement('b');
    thumb.className = 'seg-thumb';
    thumb.setAttribute('aria-hidden', 'true');
    seg.__thumb = thumb;
    seg.classList.add('has-thumb');
    const sync = () => {
      if (!thumb.isConnected) seg.prepend(thumb);          // groups that re-render their buttons lose it
      const on = seg.querySelector(ON);
      if (on && on.offsetWidth) plate(thumb, on);
      else { thumb.style.opacity = '0'; delete thumb.dataset.placed; }
    };
    new MutationObserver(sync).observe(seg, { subtree: true, childList: true, attributes: true,
      attributeFilter: ['aria-pressed', 'aria-checked', 'aria-selected'] });
    new ResizeObserver(sync).observe(seg);                  // also fires when a hidden group appears
    sync();
  });
}

/** Bring a panel in from the side its tab sits on (dir -1, 0 or 1), then settle its blocks in order. */
export function enter(panel, dir = 0, { distance = 32, blur = 0, duration = 0.34, stagger = 0.04, items } = {}) {
  if (!panel || !M) return;
  const run = (panel.__run = (panel.__run || 0) + 1);
  const blocks = items || [...panel.children].filter(k => !k.hidden);
  const clean = () => {                                     // leave no transform behind (sticky children, fixed overlays)
    if (panel.__run !== run) return;
    for (const el of [panel, ...blocks]) { el.style.transform = ''; el.style.filter = ''; el.style.opacity = ''; }
  };
  if (REDUCED) { M.animate(panel, { opacity: [0, 1] }, { duration: 0.15 }).finished.then(clean, clean); return; }
  const from = { opacity: [0, 1], x: [dir * distance, 0] };
  if (blur) from.filter = [`blur(${blur}px)`, 'blur(0px)'];
  M.animate(panel, from, { duration, ease: EASE });
  M.animate(blocks, { opacity: [0, 1], y: [14, 0] }, { duration: duration + 0.12, ease: EASE, delay: M.stagger(stagger, { startDelay: 0.04 }) })
    .finished.then(clean, clean);
}

/** Arrow keys, Home and End move focus along a tab list; activate(tab) runs for lists that switch on focus. */
export function roving(list, tabs, { activate } = {}) {
  list.addEventListener('keydown', e => {
    const all = tabs().filter(t => !t.hidden && t.offsetParent !== null);
    const i = all.indexOf(document.activeElement);
    const j = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: all.length - 1 }[e.key];
    if (i < 0 || j == null) return;
    e.preventDefault();
    const t = all[(j + all.length) % all.length];
    t.focus();
    activate?.(t);
  });
}
