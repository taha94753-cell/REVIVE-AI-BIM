// Glass panes for anything that floats over a 3D scene: the hero readout, the storey explorer's readout, tags and
// plan switch. A vanilla port of 21st.dev's "glass-card" (21st.dev/educalvolpz/glass-card): a frosted body inset from a
// refractive rim that bends what sits behind it, a chromatic edge, a pointer-tracked specular highlight with a sweep
// along the top edge, and a small lift on hover.
//   glass(el)            give one element the pane (it keeps its own children, padding and colours)
//   glassAll(root)       every [data-glass] under root; data-glass="dark" for a pane on the ink side
// Text contrast does not depend on the backdrop: the body tint is opaque enough (see .glass in landing.css) that
// ink on light panes and chalk on dark panes stay above 4.5:1 whatever the scene behind them shows.
const REDUCED = matchMedia('(prefers-reduced-motion: reduce)').matches;
const HOVER = matchMedia('(hover: hover) and (pointer: fine)');
const RIM_SHIFT = 6;                 // px the chromatic rim leans toward the pointer
const SPECULAR_BASE = [0.3, 0.28];   // where the highlight rests, as a fraction of the pane
const FILTER = 'revive-glass-bend';

// Only Chromium composites an SVG displacement inside backdrop-filter; elsewhere the rim keeps its blur and drops
// the bend instead of invalidating the whole declaration.
let bends = null;
function canBend() {
  if (bends !== null) return bends;
  const probe = `url(#${FILTER}) blur(2px)`;
  bends = !!(globalThis.CSS?.supports?.('backdrop-filter', probe) || CSS.supports?.('-webkit-backdrop-filter', probe));
  if (bends && !document.getElementById(FILTER)) {
    const ns = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('aria-hidden', 'true'); svg.setAttribute('focusable', 'false');
    svg.style.cssText = 'position:absolute;width:0;height:0;pointer-events:none';
    svg.innerHTML = `<defs><filter id="${FILTER}"><feTurbulence type="fractalNoise" baseFrequency="0.016 0.024" numOctaves="2" seed="7" result="n"/>`
      + '<feGaussianBlur in="n" stdDeviation="1.4" result="s"/><feDisplacementMap in="SourceGraphic" in2="s" scale="24" xChannelSelector="R" yChannelSelector="G"/></filter></defs>';
    document.body.appendChild(svg);
  }
  return bends;
}

const layer = (cls) => { const d = document.createElement('span'); d.className = `g-l ${cls}`; d.setAttribute('aria-hidden', 'true'); return d; };

/** Turn `el` into a glass pane. Safe to call twice. */
export function glass(el) {
  if (!el || el.dataset.glassed) return el;
  el.dataset.glassed = '1';
  el.classList.add('glass');
  if (el.dataset.glass === 'dark') el.classList.add('dark');
  if (canBend()) el.classList.add('bend');
  const light = layer('g-light');
  const rim = layer('g-chroma'), spec = layer('g-spec'), sweep = layer('g-sweep');
  light.append(rim, spec, sweep);
  el.prepend(layer('g-body'), layer('g-rim'), light, layer('g-ring'));
  if (REDUCED || !HOVER.matches) return el;

  // critically damped follow: light on glass settles, it never wobbles
  const cur = { sx: 0, sy: 0, wx: 0, rx: 0, ry: 0 }, goal = { ...cur };
  let raf = 0;
  const step = () => {
    let moving = false;
    for (const k in cur) { const d = goal[k] - cur[k]; cur[k] += d * 0.18; if (Math.abs(d) > 0.2) moving = true; else cur[k] = goal[k]; }
    spec.style.transform = `translate(${cur.sx}px, ${cur.sy}px)`;
    sweep.style.transform = `translateX(${cur.wx}px)`;
    rim.style.transform = `translate(${cur.rx}px, ${cur.ry}px)`;
    raf = moving ? requestAnimationFrame(step) : 0;
  };
  const kick = () => { if (!raf) raf = requestAnimationFrame(step); };
  el.addEventListener('pointermove', e => {
    const r = el.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    goal.sx = x - r.width * SPECULAR_BASE[0]; goal.sy = y - r.height * SPECULAR_BASE[1];
    goal.wx = x - r.width / 2;
    goal.rx = (x / r.width - 0.5) * RIM_SHIFT; goal.ry = (y / r.height - 0.5) * RIM_SHIFT;
    kick();
  });
  el.addEventListener('pointerleave', () => { for (const k in goal) goal[k] = 0; kick(); });
  return el;
}

export function glassAll(root = document) {
  root.querySelectorAll('[data-glass]').forEach(glass);
}

/** CSS-only panes (the workspace overlays) take their highlight position from --gx/--gy; one delegated listener
 *  updates them for whichever pane is under the pointer. */
export function trackGlass(selector) {
  if (REDUCED || !HOVER.matches) return;
  let el = null, x = 0, y = 0, raf = 0;
  document.addEventListener('pointermove', e => {
    el = e.target instanceof Element ? e.target.closest(selector) : null;
    if (!el) return;
    x = e.clientX; y = e.clientY;
    if (!raf) raf = requestAnimationFrame(() => {
      raf = 0;
      if (!el) return;
      const r = el.getBoundingClientRect();
      el.style.setProperty('--gx', `${x - r.left}px`); el.style.setProperty('--gy', `${y - r.top}px`);
    });
  }, { passive: true });
}
