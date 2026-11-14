// Glass highlight for the workspace overlays (inspector, legend, timeline, menus, dialogs). The panes themselves are
// CSS-only (end of workspace.css) because app.js rewrites their contents; this moves their highlight with the pointer.
const REDUCED = matchMedia('(prefers-reduced-motion: reduce)').matches;
const HOVER = matchMedia('(hover: hover) and (pointer: fine)');

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
