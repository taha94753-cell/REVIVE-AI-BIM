// Hand-drawn SVG charts. No chart library: every mark is placed from project data.
export const DPM = 30.4375;
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const lin = (d0, d1, r0, r1) => v => r0 + (v - d0) * (r1 - r0) / ((d1 - d0) || 1);
const trunc = (s, n) => (s.length > n ? s.slice(0, n - 1) + '\u2026' : s);
const svg = (w, h, label, body) => `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(label)}">${body}</svg>`;

// Entry animations are CSS classes (see app.css "chart motion"): gx/gxr grow sideways, gy grows up,
// pp pops in, dr draws a line, fd fades. The controller turns them off while a slider is dragged.
let ANIM = true;
export function animate(on) { ANIM = !!on; }
// Class only: the caller puts the stagger delay (--d) in the element's own style attribute.
const A = cls => ANIM ? ` class="${cls}"` : '';
const AC = (cls, extra) => ` class="${ANIM ? cls + ' ' : ''}${extra}"`;
const tip = t => ` data-tip="${esc(t)}"`;
const sgn = v => `${v > 0 ? '+' : ''}${Number(v).toFixed(1)}`;

function hexMix(a, b, t) {
  const p = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
  const [x, y] = [p(a), p(b)];
  return '#' + x.map((v, i) => Math.round(v + (y[i] - v) * t).toString(16).padStart(2, '0')).join('');
}

export const riskColor = level => ({ high: 'var(--crit)', medium: 'var(--watch)', low: 'var(--go)', complete: 'var(--concrete)' }[level] || 'var(--chalk-3)');

// ---------------------------------------------------------------- SHAP waterfall
export function waterfall(el, expl, final) {
  const rows = [{ label: 'Average project in the data', v: expl.base_value, kind: 'base' },
    ...expl.contributions.map(c => ({ label: c.label, value: c.value, v: c.shap, kind: 'c' })),
    { label: 'This project', v: final, kind: 'total' }];
  let cur = 0;
  const segs = rows.map(r => {
    if (r.kind === 'base') { cur = r.v; return [0, r.v]; }
    if (r.kind === 'total') return [0, r.v];
    const s = [cur, cur + r.v]; cur += r.v; return s;
  });
  // Zoom the axis onto the contributions; base and total bars get an axis break when 0 is off-scale.
  const pts = segs.slice(1, -1).flat().concat([expl.base_value, final]);
  let lo = Math.min(...pts), hi = Math.max(...pts);
  const pad = Math.max(2, (hi - lo) * 0.18);
  lo -= pad; hi += pad * 0.4;
  if (lo < 0 && Math.min(...pts) >= 0) lo = Math.min(lo, 0);
  const W = 760, L = 300, R = 64, rh = 40, H = rows.length * rh + 34;
  const x = lin(lo, hi, L, W - R);
  const broken = lo > 0;
  segs[0] = [lo, segs[0][1]]; segs[segs.length - 1] = [lo, segs[segs.length - 1][1]];
  let b = broken ? "" : `<line x1="${x(0)}" x2="${x(0)}" y1="2" y2="${H - 26}" style="stroke:var(--line-strong)"/>`;
  rows.forEach((r, i) => {
    const [a, e] = segs[i], y = i * rh + 6;
    const color = r.kind === 'base' ? 'var(--chalk-3)' : r.kind === 'total' ? 'var(--chalk)' : r.v > 0 ? 'var(--risk)' : 'var(--go)';
    b += `<text x="${L - 14}" y="${y + 15}" text-anchor="end" class="wf-label">${esc(trunc(r.label, 40))}</text>`;
    if (r.value) b += `<text x="${L - 14}" y="${y + 31}" text-anchor="end" class="wf-sub">${esc(trunc(r.value, 42))}</text>`;
    const x0 = x(Math.min(a, e)), w = Math.max(2, Math.abs(x(e) - x(a)));
    const t = r.kind === 'c' ? `${r.label}${r.value ? ` = ${r.value}` : ''}\n${sgn(r.v)} percentage points ${r.v > 0 ? 'pushes the overrun up' : 'pulls the overrun down'}`
      : r.kind === 'base' ? `Average forecast across the training data: ${r.v.toFixed(1)}%` : `This project's forecast: ${r.v.toFixed(1)}%`;
    b += `<rect x="${x0}" y="${y + 6}" width="${w}" height="20" rx="1.5"${A(r.kind === 'c' && r.v < 0 ? 'gxr' : 'gx', i * 70)} style="fill:${color};--d:${ANIM ? i * 70 : 0}ms"${tip(t)}/>`;
    const right = r.kind !== 'c' || r.v >= 0;
    const txt = r.kind === 'c' ? `${r.v > 0 ? '+' : ''}${r.v.toFixed(1)}` : `${r.v.toFixed(1)}%`;
    b += `<text x="${right ? x(Math.max(a, e)) + 6 : x(Math.min(a, e)) - 6}" y="${y + 21}" text-anchor="${right ? 'start' : 'end'}" class="wf-num">${txt}</text>`;
    if (r.kind !== 'total' && i < rows.length - 2) b += `<line x1="${x(e)}" x2="${x(e)}" y1="${y + 26}" y2="${y + rh + 6}" style="stroke:var(--chalk-3);stroke-dasharray:2 3"/>`;
  });
  b += `<text x="${(L + W - R) / 2}" y="${H - 6}" text-anchor="middle" class="ax">Time overrun, percentage points${broken ? ' (axis starts at ' + Math.round(lo) + ')' : ''}</text>`;
  el.innerHTML = svg(W, H, 'TreeSHAP contributions to the forecast', b);
}

// ---------------------------------------------------------------- forecast range
export function rangeBar(el, { value, lo, hi, bands }) {
  const max = Math.max(100, Math.ceil((hi + 10) / 25) * 25), min = Math.min(0, Math.floor((lo - 5) / 10) * 10);
  const W = 440, H = 66, x = lin(min, max, 8, W - 8);
  let b = '', prev = min;
  bands.forEach(bd => {
    const end = Math.min(bd.max, max);
    if (end > prev) b += `<rect x="${x(prev)}" y="24" width="${x(end) - x(prev)}" height="8" style="fill:${bd.color};opacity:.4"/>`;
    prev = Math.max(prev, end);
  });
  b += `<rect x="${x(lo)}" y="17" width="${Math.max(2, x(hi) - x(lo))}" height="22" style="fill:rgba(230,238,241,.12);stroke:var(--chalk-2)"/>`;
  b += `<line x1="${x(value)}" x2="${x(value)}" y1="10" y2="46" style="stroke:var(--chalk);stroke-width:3"/>`;
  for (let t = Math.ceil(min / 25) * 25; t <= max; t += 25) b += `<text x="${x(t)}" y="62" text-anchor="middle" class="ax">${t}%</text>`;
  el.innerHTML = svg(W, H, `Forecast ${value}%, 80% range ${lo}% to ${hi}%`, b);
}

// ---------------------------------------------------------------- health dial
export function dial(el, score) {
  const cx = 70, cy = 66, r = 54, a = Math.PI * (1 - Math.max(0, Math.min(100, score)) / 100);
  const color = score >= 75 ? 'var(--go)' : score >= 60 ? 'var(--watch)' : score >= 40 ? 'var(--risk)' : 'var(--crit)';
  const ex = cx + r * Math.cos(a), ey = cy - r * Math.sin(a);
  const b = `<path d="M${cx - r} ${cy} A${r} ${r} 0 0 1 ${cx + r} ${cy}" style="fill:none;stroke:var(--ink-600);stroke-width:10"/>
    <path d="M${cx - r} ${cy} A${r} ${r} 0 0 1 ${ex.toFixed(2)} ${ey.toFixed(2)}" style="fill:none;stroke:${color};stroke-width:10"/>
    <text x="${cx}" y="${cy - 4}" text-anchor="middle" style="fill:var(--chalk);font:700 34px var(--display)">${Math.round(score)}</text>`;
  el.innerHTML = svg(140, 74, `Health score ${Math.round(score)} of 100`, b);
}

// ---------------------------------------------------------------- Gantt
export function gantt(el, acts, marks) {
  const W = 1100, L = 250, R = 24, rh = 25, top = 38, H = top + acts.length * rh + 34;
  const maxD = Math.max(...acts.flatMap(a => [a.forecast[1], a.recovered[1], a.baseline[1]]), ...marks.map(m => m.day)) * 1.03;
  const x = lin(0, maxD, L, W - R);
  let b = '';
  const step = maxD / DPM > 24 ? 6 : 3;
  for (let m = 0; m * DPM <= maxD; m += step) {
    b += `<line x1="${x(m * DPM)}" x2="${x(m * DPM)}" y1="${top - 6}" y2="${H - 30}" class="gl"/>`;
    b += `<text x="${x(m * DPM)}" y="${H - 12}" text-anchor="middle" class="ax">Month ${m}</text>`;
  }
  acts.forEach((a, i) => {
    const y = top + i * rh;
    b += `<text x="${L - 12}" y="${y + 15}" text-anchor="end" class="axl">${esc(trunc(a.name, 34))}</text>`;
    const tt = `${a.id} ${a.name}\nBaseline: day ${Math.round(a.baseline[0])} to ${Math.round(a.baseline[1])}\nForecast: day ${Math.round(a.forecast[0])} to ${Math.round(a.forecast[1])} (${a.status}${a.risk_level !== 'complete' ? `, ${a.risk_level} risk` : ''})` +
      (a.crash_days > 0 ? `\nRecovery: ${a.crash_days} days faster, ${a.crash_method}` : '') + (a.critical ? '\nOn the critical path' : '');
    b += `<g${tip(tt)}><rect x="${L}" y="${y}" width="${W - R - L}" height="${rh - 2}" class="hit"/>`;
    b += `<rect x="${x(a.baseline[0])}" y="${y + 3}" width="${Math.max(1.5, x(a.baseline[1]) - x(a.baseline[0]))}" height="4"${A('gx')} style="fill:var(--chalk-3);--d:${i * 22}ms"/>`;
    b += `<rect x="${x(a.forecast[0])}" y="${y + 8}" width="${Math.max(1.5, x(a.forecast[1]) - x(a.forecast[0]))}" height="7"${A('gx')} style="fill:${riskColor(a.risk_level)};--d:${120 + i * 22}ms"/>`;
    if (Math.abs(a.recovered[1] - a.forecast[1]) > 0.5)
      b += `<rect x="${x(a.recovered[0])}" y="${y + 16}" width="${Math.max(1.5, x(a.recovered[1]) - x(a.recovered[0]))}" height="5"${A('gx')} style="fill:var(--mark);--d:${260 + i * 22}ms"/>`;
    b += '</g>';
  });
  marks.forEach((m, i) => {
    b += `<line x1="${x(m.day)}" x2="${x(m.day)}" y1="${top - 8}" y2="${H - 30}" style="stroke:${m.color};stroke-width:1.5;stroke-dasharray:${m.dash || 'none'}"/>`;
    const nearEnd = x(m.day) > W - 140;
    b += `<text x="${x(m.day) + (nearEnd ? -4 : 4)}" y="${12 + (i % 2) * 14}" text-anchor="${nearEnd ? 'end' : 'start'}" style="fill:${m.color};font-size:12px">${esc(m.label)}</text>`;
  });
  const lg = [['Baseline', 'var(--chalk-3)'], ['Forecast (colour = risk)', 'var(--risk)'], ['Recovered', 'var(--mark)']];
  lg.forEach(([t, c], i) => { b += `<rect x="${10 + i * 150}" y="${H - 22}" width="14" height="6" style="fill:${c}"/><text x="${30 + i * 150}" y="${H - 15}" class="ax">${t}</text>`; });
  el.innerHTML = svg(W, H, 'Baseline, forecast and recovered schedule', b);
}

// ---------------------------------------------------------------- time-cost curve
export function curve(el, pts, optimum) {
  if (!pts.length) { el.innerHTML = '<p class="fine">No curve: the forecast already meets the target.</p>'; return; }
  const W = 580, H = 320, L = 64, R = 20, T = 20, B = 46;
  const xs = pts.map(p => p.finish_day / DPM), ys = pts.flatMap(p => [p.crash_cost_pkr, p.ld_pkr, p.total_pkr]).map(v => v / 1e6);
  const x = lin(Math.min(...xs), Math.max(...xs), L, W - R), y = lin(0, Math.max(...ys) * 1.08, H - B, T);
  let b = '';
  const ymax = Math.max(...ys) * 1.08, ystep = Math.pow(10, Math.floor(Math.log10(ymax || 1))) * (ymax / Math.pow(10, Math.floor(Math.log10(ymax || 1))) > 5 ? 2 : 1);
  for (let v = 0; v <= ymax; v += ystep) b += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" class="gl"/><text x="${L - 8}" y="${y(v) + 4}" text-anchor="end" class="ax">${v.toFixed(0)}</text>`;
  const line = (key, style, cls, d) => `<path d="${pts.map((p, i) => `${i ? 'L' : 'M'}${x(p.finish_day / DPM).toFixed(1)} ${y(p[key] / 1e6).toFixed(1)}`).join(' ')}" pathLength="1"${cls ? A(cls) : ''} style="fill:none;${style};--d:${d}ms"/>`;
  b += line('ld_pkr', 'stroke:var(--risk);stroke-width:2;stroke-dasharray:5 4', 'fd', 300);
  b += line('crash_cost_pkr', 'stroke:var(--mark);stroke-width:2.5', 'dr', 150);
  b += line('total_pkr', 'stroke:var(--chalk);stroke-width:2.5', 'dr', 0);
  pts.forEach(p => {
    const t = `Finish month ${(p.finish_day / DPM).toFixed(1)}\nCrash cost PKR ${(p.crash_cost_pkr / 1e6).toFixed(2)} M\nLiquidated damages PKR ${(p.ld_pkr / 1e6).toFixed(2)} M\nTotal PKR ${(p.total_pkr / 1e6).toFixed(2)} M`;
    b += `<circle cx="${x(p.finish_day / DPM).toFixed(1)}" cy="${y(p.total_pkr / 1e6).toFixed(1)}" r="9" class="hit"${tip(t)}/>`;
  });
  if (optimum) {
    const ox = x(optimum.day / DPM), oy = y(optimum.total / 1e6);
    b += `<circle cx="${ox}" cy="${oy}" r="6"${A('pp')} style="fill:var(--ink-900);stroke:var(--chalk);stroke-width:2.5;--d:900ms"/>`;
    b += `<text x="${ox + (ox > W / 2 ? -10 : 10)}" y="${oy - 12}" text-anchor="${ox > W / 2 ? 'end' : 'start'}" style="fill:var(--chalk);font:600 14px var(--display)">Optimum: month ${(optimum.day / DPM).toFixed(1)}</text>`;
  }
  [...new Set(xs.map(v => Math.round(v)))].filter((v, i, arr) => i % Math.ceil(arr.length / 6) === 0)
    .forEach(v => { b += `<text x="${x(v)}" y="${H - B + 18}" text-anchor="middle" class="ax">${v}</text>`; });
  b += `<text x="${(L + W - R) / 2}" y="${H - 6}" text-anchor="middle" class="ax">Completion month</text>`;
  b += `<text x="14" y="${T + (H - B - T) / 2}" transform="rotate(-90 14 ${T + (H - B - T) / 2})" text-anchor="middle" class="ax">PKR million</text>`;
  const lg = [['Total', 'var(--chalk)'], ['Crash cost', 'var(--mark)'], ['Liquidated damages', 'var(--risk)']];
  lg.forEach(([t, c], i) => { b += `<rect x="${L + 10 + i * 118}" y="${T - 2}" width="14" height="3" style="fill:${c}"/><text x="${L + 30 + i * 118}" y="${T + 3}" class="ax">${t}</text>`; });
  el.innerHTML = svg(W, H, 'Cost of finishing earlier', b);
}

// ---------------------------------------------------------------- predicted vs actual
export function scatter(el, pts) {
  const W = 460, H = 400, L = 54, B = 46, T = 14, R = 16;
  const vals = pts.flatMap(p => [p.actual, p.predicted]);
  const lo = Math.min(-10, Math.floor(Math.min(...vals) / 10) * 10), hi = Math.max(60, Math.ceil(Math.max(...vals) / 10) * 10);
  const x = lin(lo, hi, L, W - R), y = lin(lo, hi, H - B, T);
  let b = '';
  for (let v = Math.ceil(lo / 25) * 25; v <= hi; v += 25) {
    b += `<line x1="${x(v)}" x2="${x(v)}" y1="${T}" y2="${H - B}" class="gl"/><line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" class="gl"/>`;
    b += `<text x="${x(v)}" y="${H - B + 16}" text-anchor="middle" class="ax">${v}</text><text x="${L - 8}" y="${y(v) + 4}" text-anchor="end" class="ax">${v}</text>`;
  }
  b += `<line x1="${x(lo)}" y1="${y(lo)}" x2="${x(hi)}" y2="${y(hi)}" style="stroke:var(--chalk-2);stroke-dasharray:4 4"/>`;
  pts.forEach((p, i) => {
    const done = p.status === 'Completed';
    const t = `Actual ${p.actual.toFixed(1)}%, out-of-fold forecast ${p.predicted.toFixed(1)}%\nError ${sgn(p.predicted - p.actual)} pts. ${done ? 'Completed project' : p.hypothetical ? 'Hypothetical scenario' : 'Ongoing project (reported forecast)'}`;
    b += `<circle cx="${x(p.actual).toFixed(1)}" cy="${y(p.predicted).toFixed(1)}" r="4"${A('pp', Math.min(700, i * 5))} style="${done ? 'fill:var(--chalk)' : 'fill:none;stroke:' + (p.hypothetical ? 'var(--mark)' : 'var(--chalk-2)') + ';stroke-width:1.5'};--d:${Math.min(700, i * 5)}ms"${tip(t)}/>`;
  });
  b += `<text x="${(L + W - R) / 2}" y="${H - 8}" text-anchor="middle" class="ax">Actual time overrun (%)</text>`;
  b += `<text x="14" y="${(T + H - B) / 2}" transform="rotate(-90 14 ${(T + H - B) / 2})" text-anchor="middle" class="ax">Out-of-fold forecast (%)</text>`;
  el.innerHTML = svg(W, H, 'Cross-validated forecast against actual overrun', b) +
    '<p class="fine">Filled: completed projects. Hollow: ongoing projects (pink = hypothetical scenarios), whose "actual" is a reported forecast.</p>';
}

// ---------------------------------------------------------------- SHAP beeswarm
export function beeswarm(el, swarm, n = 10) {
  const rows = swarm.slice(0, n);
  const W = 720, L = 250, R = 20, rh = 34, T = 10, H = T + rows.length * rh + 44;
  const m = Math.max(...rows.flatMap(r => r.points.map(p => Math.abs(p[0])))) * 1.05 || 1;
  const x = lin(-m, m, L, W - R);
  let b = `<line x1="${x(0)}" x2="${x(0)}" y1="${T}" y2="${H - 40}" style="stroke:var(--line-strong)"/>`;
  rows.forEach((r, i) => {
    const cy = T + i * rh + rh / 2;
    b += `<text x="${L - 12}" y="${cy + 4}" text-anchor="end" class="axl">${esc(trunc(r.label, 36))}</text>`;
    const bins = {};
    [...r.points].sort((a, c) => a[0] - c[0]).forEach(([s, v]) => {
      const px = x(s), k = Math.round(px / 4); bins[k] = (bins[k] || 0) + 1;
      const n2 = bins[k], off = (n2 % 2 ? 1 : -1) * Math.floor(n2 / 2) * 3.2;
      const col = v == null ? 'rgba(111,140,156,.55)' : hexMix('#6CB2FF', '#F28C38', v);
      b += `<circle cx="${px.toFixed(1)}" cy="${(cy + Math.max(-13, Math.min(13, off))).toFixed(1)}" r="2.6"${A('fd')} style="fill:${col};--d:${i * 60}ms"/>`;
    });
  });
  b += `<text x="${(L + W - R) / 2}" y="${H - 22}" text-anchor="middle" class="ax">Effect on forecast time overrun (percentage points)</text>`;
  b += `<rect x="${L}" y="${H - 12}" width="60" height="6" style="fill:#6CB2FF"/><text x="${L + 66}" y="${H - 6}" class="ax">low value</text>`;
  b += `<rect x="${L + 150}" y="${H - 12}" width="60" height="6" style="fill:#F28C38"/><text x="${L + 216}" y="${H - 6}" class="ax">high value</text>`;
  el.innerHTML = svg(W, H, 'TreeSHAP beeswarm of the main drivers', b);
}

// ---------------------------------------------------------------- horizontal bars
export function hbars(el, items, { max = 1, label, value, color, text }) {
  const W = 720, L = 330, R = 70, rh = 27, H = items.length * rh + 8;
  const x = lin(0, max, L, W - R);
  let b = '';
  items.forEach((it, i) => {
    const y = i * rh + 4;
    b += `<text x="${L - 12}" y="${y + 15}" text-anchor="end" class="axl">${esc(trunc(label(it), 46))}</text>`;
    b += `<rect x="${L}" y="${y + 5}" width="${Math.max(1, x(value(it)) - L)}" height="13"${A('gx')} style="fill:${color(it)};--d:${i * 45}ms"${tip(`${label(it)}: ${text(it)}`)}/>`;
    b += `<text x="${x(value(it)) + 6}" y="${y + 16}" class="axl">${esc(text(it))}</text>`;
  });
  el.innerHTML = svg(W, H, 'Ranking', b);
}

// ---------------------------------------------------------------- live forecast trajectory
export function trajectory(el, pts, bands) {
  if (!pts.length) { el.innerHTML = ''; return; }
  const W = 660, H = 320, L = 52, R = 18, T = 16, B = 42;
  const ys = pts.flatMap(p => [p.lo, p.hi, p.y]);
  const y0 = Math.min(0, Math.floor(Math.min(...ys) / 10) * 10), y1 = Math.max(60, Math.ceil((Math.max(...ys) + 5) / 10) * 10);
  const x = lin(0, 100, L, W - R), y = lin(y0, y1, H - B, T);
  let b = '', prev = y0;
  bands.forEach(bd => {
    const top = Math.min(bd.max, y1);
    if (top > prev) b += `<rect x="${L}" y="${y(top)}" width="${W - R - L}" height="${y(prev) - y(top)}" style="fill:${bd.color};opacity:.07"/>`;
    prev = Math.max(prev, top);
  });
  for (let v = Math.ceil(y0 / 20) * 20; v <= y1; v += 20) b += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" class="gl"/><text x="${L - 8}" y="${y(v) + 4}" text-anchor="end" class="ax">${v}%</text>`;
  [0, 25, 50, 75, 100].forEach(v => { b += `<line x1="${x(v)}" x2="${x(v)}" y1="${T}" y2="${H - B}" class="gl"/><text x="${x(v)}" y="${H - B + 16}" text-anchor="middle" class="ax">${v}%</text>`; });
  b += `<text x="${(L + W - R) / 2}" y="${H - 6}" text-anchor="middle" class="ax">Contract time elapsed</text>`;
  if (pts.length > 1) {
    const top = pts.map(p => `${x(p.x).toFixed(1)},${y(p.hi).toFixed(1)}`), bot = [...pts].reverse().map(p => `${x(p.x).toFixed(1)},${y(p.lo).toFixed(1)}`);
    b += `<polygon points="${top.concat(bot).join(' ')}" style="fill:rgba(230,238,241,.09)"/>`;
    b += `<path d="${pts.map((p, i) => `${i ? 'L' : 'M'}${x(p.x).toFixed(1)} ${y(p.y).toFixed(1)}`).join(' ')}" pathLength="1"${A('dr')} style="fill:none;stroke:var(--chalk);stroke-width:2.5"/>`;
  } else {
    b += `<line x1="${x(pts[0].x)}" x2="${x(pts[0].x)}" y1="${y(pts[0].lo)}" y2="${y(pts[0].hi)}" style="stroke:rgba(230,238,241,.3);stroke-width:8"/>`;
  }
  pts.forEach((p, i) => {
    const last = i === pts.length - 1;
    const t = `${p.label ? p.label + '\n' : ''}${Math.round(p.x)}% of contract time: forecast ${p.y > 0 ? '+' : ''}${p.y.toFixed(1)}%\n80% range ${p.lo.toFixed(0)}% to ${p.hi.toFixed(0)}%`;
    if (last && ANIM) b += `<circle cx="${x(p.x).toFixed(1)}" cy="${y(p.y).toFixed(1)}" r="7" class="ripple" style="stroke:${p.color}"/>`;
    b += `<circle cx="${x(p.x).toFixed(1)}" cy="${y(p.y).toFixed(1)}" r="${last ? 7 : 4.5}"${AC(last ? 'pp' : 'fd', last ? 'traj-last' : '')} style="fill:${p.color};stroke:var(--ink-900);stroke-width:2;--d:${last ? 500 : i * 40}ms"${tip(t)}/>`;
  });
  const lp = pts[pts.length - 1];
  b += `<text x="${Math.min(x(lp.x) + 12, W - R - 4)}" y="${y(lp.y) - 12}" text-anchor="${x(lp.x) > W - 120 ? 'end' : 'start'}" style="fill:var(--chalk);font:600 18px var(--display)">${lp.y > 0 ? '+' : ''}${lp.y.toFixed(0)}%</text>`;
  el.innerHTML = svg(W, H, 'Forecast overrun after each site update', b);
}

// ---------------------------------------------------------------- Monte Carlo finish distribution
export function distribution(el, sim) {
  const e = sim.hist.edges_months, n = sim.hist.before.length;
  const W = 620, H = 250, L = 20, R = 20, T = 26, B = 40;
  const x = lin(e[0], e[e.length - 1], L, W - R);
  const ymax = Math.max(...sim.hist.before, ...sim.hist.after) * 1.1 || 1, y = lin(0, ymax, H - B, T);
  const area = (arr, style) => {
    let d = `M${x(e[0])} ${y(0)}`;
    arr.forEach((v, i) => { d += ` L${x((e[i] + e[i + 1]) / 2).toFixed(1)} ${y(v).toFixed(1)}`; });
    return `<path d="${d} L${x(e[n])} ${y(0)} Z"${A('gy')} style="${style}"/>`;
  };
  let b = area(sim.hist.before, 'fill:rgba(242,140,56,.35);stroke:var(--risk);stroke-width:1.5');
  b += area(sim.hist.after, 'fill:rgba(255,79,163,.35);stroke:var(--mark);stroke-width:1.5');
  const dl = sim.deadline_day / DPM;
  b += `<line x1="${x(dl)}" x2="${x(dl)}" y1="${T - 10}" y2="${H - B}" style="stroke:var(--go);stroke-width:2;stroke-dasharray:5 4"/><text x="${x(dl) + 5}" y="${T - 12}" style="fill:var(--go);font-size:12px">Target</text>`;
  [['p80_before_day', 'P80 now', 'var(--risk)'], ['p80_after_day', 'P80 with plan', 'var(--mark)']].forEach(([k, lab, c], i) => {
    const px = x(sim[k] / DPM);
    b += `<line x1="${px}" x2="${px}" y1="${T + 6 + i * 14}" y2="${H - B}" style="stroke:${c};stroke-width:1.5"/><text x="${px + 4}" y="${T + 14 + i * 14}" style="fill:${c};font-size:12px">${lab}</text>`;
  });
  const step = Math.max(1, Math.round((e[e.length - 1] - e[0]) / 8));
  for (let m = Math.ceil(e[0]); m <= e[e.length - 1]; m += step) b += `<text x="${x(m)}" y="${H - B + 16}" text-anchor="middle" class="ax">${m}</text>`;
  b += `<text x="${(L + W - R) / 2}" y="${H - 6}" text-anchor="middle" class="ax">Completion month (${sim.samples.toLocaleString('en')} simulated finishes)</text>`;
  el.innerHTML = svg(W, H, 'Distribution of simulated completion dates', b);
}

// ---------------------------------------------------------------- live weather strip
export function weatherStrip(el, w) {
  const days = [...w.past, ...w.forecast], n = days.length;
  if (!n) { el.innerHTML = ''; return; }
  const W = 660, H = 150, L = 8, R = 8, T = 20, B = 34, bw = (W - L - R) / n;
  const y = lin(0, Math.max(20, ...days.map(d => d.rain_mm || 0)), H - B, T);
  const tx = L + w.past.length * bw;
  let b = `<rect x="${tx}" y="${T - 16}" width="${W - R - tx}" height="${H - B - T + 16}" style="fill:rgba(230,238,241,.05)"/>`;
  b += `<line x1="${tx}" x2="${tx}" y1="${T - 16}" y2="${H - B}" style="stroke:var(--chalk-2);stroke-dasharray:3 3"/>`;
  b += `<text x="${tx + 5}" y="${T - 5}" class="ax">Today and forecast</text><text x="${tx - 5}" y="${T - 5}" text-anchor="end" class="ax">Observed</text>`;
  days.forEach((d, i) => {
    const x0 = L + i * bw + 1.5, wv = Math.max(1, bw - 3), rain = d.rain_mm || 0;
    const tip = `${d.date}: ${rain.toFixed(1)} mm rain, ${d.tmax ?? '-'} / ${d.tmin ?? '-'} \u00b0C, wind ${d.wind_kmh ?? '-'} km/h${d.lost ? '. Likely lost: ' + d.reasons.join(', ') : ''}`;
    b += `<g data-tip="${esc(tip)}"><rect x="${x0}" y="${T - 16}" width="${wv}" height="${H - B - T + 16}" class="hit"/><rect x="${x0}" y="${y(rain)}" width="${wv}" height="${Math.max(0.5, y(0) - y(rain))}"${A('gy')} style="fill:${d.lost ? 'var(--crit)' : '#6CB2FF'};--d:${i * 18}ms"/>`;
    if (d.lost) b += `<rect x="${x0}" y="${H - B + 4}" width="${wv}" height="5" style="fill:var(--crit)"/>`;
    b += '</g>';
    if (i % 4 === 0) b += `<text x="${x0 + wv / 2}" y="${H - 8}" text-anchor="middle" class="ax">${d.date.slice(5)}</text>`;
  });
  el.innerHTML = svg(W, H, 'Daily rainfall with likely lost days marked, observed and forecast', b);
}


// ---------------------------------------------------------------- band donut (portfolio)
export function donut(el, segs, { center = '', sub = '', active = null } = {}) {
  const total = segs.reduce((t, s) => t + s.value, 0) || 1, r = 64, cx = 90, cy = 90;
  let acc = 0, b = `<circle cx="${cx}" cy="${cy}" r="${r}" style="fill:none;stroke:var(--ink-700);stroke-width:20"/>`;
  segs.forEach((s, i) => {
    const len = 100 * s.value / total, gap = segs.length > 1 && s.value ? 0.6 : 0;
    if (s.value) {
      b += `<circle cx="${cx}" cy="${cy}" r="${r}" pathLength="100" transform="rotate(-90 ${cx} ${cy})" data-band="${esc(s.key)}"
        class="seg-arc${active && active !== s.key ? ' dim' : ''}${ANIM ? ' arc' : ''}" style="fill:none;stroke:${s.color};stroke-width:${active === s.key ? 26 : 20};stroke-dasharray:${Math.max(0, len - gap).toFixed(2)} ${(100 - len + gap).toFixed(2)};stroke-dashoffset:${(-acc).toFixed(2)};--d:${i * 120}ms"
        ${tip(`${s.label}: ${s.value} project${s.value === 1 ? '' : 's'} (${Math.round(100 * s.value / total)}%)\nClick to filter`)}/>`;
    }
    acc += len;
  });
  b += `<text x="${cx}" y="${cy + 4}" text-anchor="middle" style="fill:var(--chalk);font:700 40px var(--display)">${esc(center)}</text>`;
  b += `<text x="${cx}" y="${cy + 24}" text-anchor="middle" class="ax">${esc(sub)}</text>`;
  el.innerHTML = svg(180, 180, 'Projects by forecast risk band', b);
}

// ---------------------------------------------------------------- portfolio risk map (SPI vs forecast)
export function riskMap(el, rows, bands, { isDim = () => false, selected = null } = {}) {
  const W = 640, H = 360, L = 50, R = 16, T = 14, B = 44;
  const pts = rows.filter(r => r.spi != null && r.predicted_time_overrun_pct != null);
  const ymax = Math.min(150, Math.max(60, Math.ceil(Math.max(...pts.map(p => p.predicted_time_overrun_pct), 0) / 10) * 10 + 10));
  const ymin = Math.min(-10, Math.floor(Math.min(...pts.map(p => p.predicted_time_overrun_pct), 0) / 10) * 10);
  const xs = pts.map(p => p.spi), xmin = Math.min(0.5, Math.floor(Math.min(...xs, 1) * 10) / 10), xmax = Math.max(1.2, Math.ceil(Math.max(...xs, 1) * 10) / 10);
  const x = lin(xmin, xmax, L, W - R), y = lin(ymin, ymax, H - B, T);
  let b = '', prev = ymin;
  bands.forEach(bd => {
    const top = Math.min(bd.max, ymax);
    if (top > prev) b += `<rect x="${L}" y="${y(top)}" width="${W - R - L}" height="${y(prev) - y(top)}" style="fill:${bd.color};opacity:.06"/>` +
      `<text x="${W - R - 6}" y="${y(top) + 14}" text-anchor="end" class="ax" style="fill:${bd.color};opacity:.85">${esc(bd.name)}</text>`;
    prev = Math.max(prev, top);
  });
  for (let v = Math.ceil(ymin / 25) * 25; v <= ymax; v += 25) b += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" class="gl"/><text x="${L - 8}" y="${y(v) + 4}" text-anchor="end" class="ax">${v}%</text>`;
  for (let v = Math.ceil(xmin * 10) / 10; v <= xmax + 1e-9; v += 0.1) b += `<text x="${x(v)}" y="${H - B + 16}" text-anchor="middle" class="ax">${v.toFixed(1)}</text>`;
  b += `<line x1="${x(1)}" x2="${x(1)}" y1="${T}" y2="${H - B}" style="stroke:var(--chalk-2);stroke-dasharray:4 4"/><text x="${x(1) - 6}" y="${T + 10}" text-anchor="end" class="ax">SPI 1.0 = on programme</text>`;
  b += `<circle cx="${L + 10}" cy="${T + 8}" r="4.5" style="fill:var(--chalk-2)"/><text x="${L + 19}" y="${T + 12}" class="ax">real project</text>` +
    `<circle cx="${L + 100}" cy="${T + 8}" r="4.5" style="fill:none;stroke:var(--chalk-2);stroke-width:1.8"/><text x="${L + 109}" y="${T + 12}" class="ax">hypothetical scenario</text>`;
  b += `<text x="${(L + W - R) / 2}" y="${H - 8}" text-anchor="middle" class="ax">SPI at the checkpoint (lower = further behind)</text>`;
  b += `<text x="13" y="${(T + H - B) / 2}" transform="rotate(-90 13 ${(T + H - B) / 2})" text-anchor="middle" class="ax">Cross-validated forecast overrun</text>`;
  const sorted = [...pts].sort((a, c) => (isDim(c) - isDim(a)));
  sorted.forEach((p, i) => {
    const c = p.band?.color || 'var(--chalk-3)', dim = isDim(p), sel = selected === p.project_id;
    const t = `${p.project_id}: ${p.project_type}, ${p.province}\n${p.status}, scored at ${p.gate === 'G50' ? '50%' : '25%'} of time\nSPI ${p.spi.toFixed(2)}, forecast ${sgn(p.predicted_time_overrun_pct)}%` +
      (p.status === 'Completed' && p.actual_time_overrun_pct != null ? `, actual ${sgn(p.actual_time_overrun_pct)}%` : '') + (p.hypothetical ? '\nHypothetical scenario' : '') + '\nClick to open in the assessment';
    const yy = y(Math.min(ymax, p.predicted_time_overrun_pct));
    b += `<circle cx="${x(p.spi).toFixed(1)}" cy="${yy.toFixed(1)}" r="${sel ? 8 : 5.5}" data-id="${esc(p.project_id)}"${AC('pp', 'pt' + (dim ? ' dim' : '') + (sel ? ' sel' : ''), Math.min(900, i * 6))}
      style="${p.hypothetical ? `fill:var(--ink-900);stroke:${c};stroke-width:2` : `fill:${c};stroke:var(--ink-900);stroke-width:1.2`};--d:${Math.min(900, i * 6)}ms"${tip(t)}/>`;
  });
  el.innerHTML = svg(W, H, 'Portfolio risk map: SPI against forecast overrun', b);
}

// ---------------------------------------------------------------- sparkline (live panel)
export function sparkline(el, vals, { color = 'var(--chalk)', lo = null, hi = null, fmt = v => v.toFixed(1), better = 'down' } = {}) {
  const v = vals.filter(n => n != null && !Number.isNaN(n));
  const W = 220, H = 56, P = 6;
  if (!v.length) { el.innerHTML = svg(W, H, 'No data yet', `<text x="${W / 2}" y="${H / 2 + 4}" text-anchor="middle" class="ax">waiting for the first update</text>`); return; }
  const mn = lo ?? Math.min(...v), mx = hi ?? Math.max(...v), span = (mx - mn) || 1;
  const x = i => P + (v.length === 1 ? (W - 2 * P) : i * (W - 2 * P) / (v.length - 1)), y = n => H - P - (n - mn) / span * (H - 2 * P);
  const d = v.map((n, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(n).toFixed(1)}`).join(' ');
  let b = v.length > 1 ? `<path d="${d} L${x(v.length - 1)} ${H} L${x(0)} ${H} Z" style="fill:${color};opacity:.1"/>` : '';
  b += `<path d="${d}" pathLength="1"${A('dr')} style="fill:none;stroke:${color};stroke-width:2"/>`;
  v.forEach((n, i) => { b += `<circle cx="${x(i).toFixed(1)}" cy="${y(n).toFixed(1)}" r="${i === v.length - 1 ? 4 : 2}"${i === v.length - 1 ? A('pp', 400) : ''} style="fill:${color};--d:400ms"${tip(`Update ${i + 1}: ${fmt(n)}`)}/>`; });
  el.innerHTML = svg(W, H, 'Trend across site updates', b);
}

// ---------------------------------------------------------------- cost of delay with and without the plan
export function costCompare(el, o) {
  const rows = [
    { label: 'Accept the delay', parts: [['Liquidated damages', o.ld_before_pkr, 'var(--risk)']] },
    { label: 'With the recovery plan', parts: [['Crash cost', o.crash_cost_pkr, 'var(--mark)'], ['Remaining damages', o.ld_after_pkr, 'var(--risk)']] },
  ];
  const tot = r => r.parts.reduce((t, p) => t + (p[1] || 0), 0);
  const max = Math.max(1, ...rows.map(tot));
  const W = 640, L = 190, R = 110, rh = 54, H = rows.length * rh + 26;
  const x = lin(0, max, L, W - R);
  const m = v => `PKR ${(v / 1e6).toFixed(1)} M`;
  let b = '';
  rows.forEach((r, i) => {
    const yy = i * rh + 8; let acc = 0;
    b += `<text x="${L - 12}" y="${yy + 22}" text-anchor="end" class="wf-label">${r.label}</text>`;
    r.parts.forEach(([lab, v, c], j) => {
      if (!v) return;
      b += `<rect x="${x(acc)}" y="${yy + 6}" width="${Math.max(2, x(acc + v) - x(acc))}" height="24" rx="1.5"${A('gx')} style="fill:${c};--d:${i * 250 + j * 200}ms"${tip(`${lab}: ${m(v)}`)}/>`;
      acc += v;
    });
    b += `<text x="${x(acc) + 8}" y="${yy + 24}" class="wf-num">${m(acc)}</text>`;
  });
  const save = tot(rows[0]) - tot(rows[1]);
  b += `<text x="${L}" y="${H - 4}" class="ax">${save > 0 ? `Crash cost and liquidated damages only: the plan saves ${m(save)}. Site overheads avoided come on top (Net benefit above).` : 'No saving: at these rates, accelerating costs more than the damages it avoids.'}</text>`;
  el.innerHTML = svg(W, H, 'Cost of the delay with and without the recovery plan', b);
}

// ================================================================ current delay sheet
// S-curve: planned share of work against time, with actual time (AT), earned schedule (ES) and the gap.
export function sCurve(el, d) {
  const W = 660, H = 340, L = 50, R = 20, T = 18, B = 44;
  const st = d.history.at(-1), ts = d.curve.t_pct, pv = d.curve.pv_pct;
  const xmax = Math.max(100, Math.ceil((Math.max(...d.history.map(h => h.at_pct)) + 8) / 10) * 10);
  const x = lin(0, xmax, L, W - R), y = lin(0, 100, H - B, T);
  let b = '';
  for (let v = 0; v <= 100; v += 25) b += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" class="gl"/><text x="${L - 8}" y="${y(v) + 4}" text-anchor="end" class="ax">${v}%</text>`;
  for (let v = 0; v <= xmax; v += 25) b += `<text x="${x(v)}" y="${H - B + 16}" text-anchor="middle" class="ax">${v}%</text>`;
  b += `<text x="${(L + W - R) / 2}" y="${H - 6}" text-anchor="middle" class="ax">Time, % of planned duration</text>`;
  const path = ts.map((t, i) => `${i ? 'L' : 'M'}${x(t).toFixed(1)} ${y(pv[i]).toFixed(1)}`).join(' ');
  b += `<path d="${path} L${x(ts.at(-1)).toFixed(1)} ${y(0)} L${x(0)} ${y(0)} Z" style="fill:url(#sc-fill)" ${A('fd')}/>`;
  b += `<defs><linearGradient id="sc-fill" x1="0" x2="0" y1="0" y2="1"><stop offset="0" style="stop-color:var(--cyan);stop-opacity:.22"/><stop offset="1" style="stop-color:var(--cyan);stop-opacity:0"/></linearGradient></defs>`;
  b += `<path d="${path}" pathLength="1"${A('dr')} style="fill:none;stroke:var(--cyan);stroke-width:2.5"/>`;
  // the gap: from ES to AT at the earned level
  const gy = y(st.ev_pct), late = st.at_pct - st.es_pct > 0.3;
  if (late) {
    b += `<rect x="${x(st.es_pct)}" y="${T}" width="${x(st.at_pct) - x(st.es_pct)}" height="${H - B - T}" style="fill:var(--crit);fill-opacity:.12;--d:600ms"${A('fd')}/>`;
    b += `<line x1="${x(st.es_pct)}" x2="${x(st.at_pct)}" y1="${gy}" y2="${gy}" style="stroke:var(--crit);stroke-width:3;--d:700ms"${A('gx')}/>`;
    b += `<text x="${(x(st.es_pct) + x(st.at_pct)) / 2}" y="${gy - 10}" text-anchor="middle" style="fill:var(--crit);font:600 16px var(--display)">${Math.round(d.delay_days)} days</text>`;
  }
  [[st.es_pct, 'ES', 'var(--watch)', 'Earned schedule: the plan reached this much work on this day'], [st.at_pct, 'AT', 'var(--chalk)', 'Actual time: the status date']].forEach(([v, lab, c, t], i) => {
    b += `<line x1="${x(v)}" x2="${x(v)}" y1="${T}" y2="${H - B}" style="stroke:${c};stroke-dasharray:4 4;stroke-width:1.5"/>`;
    b += `<text x="${x(v) + (i ? 6 : -6)}" y="${T + 14}" text-anchor="${i ? 'start' : 'end'}" style="fill:${c};font:600 14px var(--display)"${tip(t)}>${lab}</text>`;
  });
  d.history.forEach((h, i) => {
    const last = i === d.history.length - 1;
    b += `<circle cx="${x(h.at_pct).toFixed(1)}" cy="${y(h.ev_pct).toFixed(1)}" r="${last ? 7 : 4}"${AC('pp', last ? 'traj-last' : '')} style="fill:${last ? 'var(--amber)' : 'var(--chalk-2)'};stroke:var(--ink-900);stroke-width:2;--d:${400 + i * 60}ms"${tip(`${h.basis}\n${h.at_pct.toFixed(0)}% of time: ${h.ev_pct.toFixed(1)}% of work done (plan reached that on ${h.es_pct.toFixed(0)}%)`)}/>`;
  });
  el.innerHTML = svg(W, H, 'Planned progress curve with actual time and earned schedule', b);
}

// Three finish estimates against the planned finish.
export function finish3(el, d) {
  const rows = [['Planned', d.planned_days, 'var(--chalk-3)', 'Baseline completion'],
    ['Remaining work to plan', d.finish.to_plan, 'var(--watch)', 'Planned finish plus the delay to date'],
    ['Current pace continues', d.finish.current_pace, 'var(--risk)', 'Earned schedule forecast: planned duration / SPI(t)'],
    ['ML forecast', d.finish.ml_forecast, 'var(--mark)', 'REVIVE model forecast overrun applied to the planned duration']].filter(r => r[1] != null);
  const W = 660, L = 190, R = 90, T = 10, row = 46, H = T + rows.length * row + 30;
  const vmax = Math.max(...rows.map(r => r[1])) * 1.04, x = lin(0, vmax, L, W - R);
  let b = '';
  rows.forEach(([lab, v, c, t], i) => {
    const yy = T + i * row, late = v - d.planned_days;
    b += `<text x="${L - 12}" y="${yy + 22}" text-anchor="end" class="wf-label">${esc(lab)}</text>`;
    b += `<rect x="${L}" y="${yy + 8}" width="${Math.max(2, x(v) - L)}" height="20" rx="2"${A('gx')} style="fill:${c};opacity:${i ? .9 : .45};--d:${i * 110}ms"${tip(`${t}\nDay ${Math.round(v)}${i ? `, ${late >= 0 ? '+' : ''}${Math.round(late)} days` : ''}`)}/>`;
    b += `<text x="${x(v) + 8}" y="${yy + 23}" class="wf-num">${i ? `${late >= 0 ? '+' : ''}${Math.round(late)} d` : `day ${Math.round(v)}`}</text>`;
  });
  b += `<line x1="${x(d.planned_days)}" x2="${x(d.planned_days)}" y1="${T}" y2="${H - 24}" style="stroke:var(--chalk);stroke-dasharray:3 4;opacity:.6"/>`;
  b += `<text x="${x(d.planned_days)}" y="${H - 8}" text-anchor="middle" class="ax">planned completion</text>`;
  el.innerHTML = svg(W, H, 'Planned finish against three finish estimates', b);
}

// Slip in each window between site updates, split by the events reported in it.
export function windowsChart(el, wins, labels) {
  const cats = [['client', 'var(--watch)'], ['neutral', '#6CB2FF'], ['contractor', 'var(--risk)'], ['unexplained', 'var(--chalk-3)']];
  const W = 1200, H = 300, L = 54, R = 20, T = 26, B = 64;
  const vals = wins.map(w => w.slip_days), lo = Math.min(0, ...vals), hi = Math.max(5, ...vals) * 1.1;
  const y = lin(lo, hi, H - B, T), bw = Math.min(70, (W - L - R) / wins.length * 0.42);
  const cx = i => L + (i + 0.5) * (W - L - R) / wins.length;
  let b = '';
  const step = hi > 40 ? 20 : hi > 15 ? 5 : 2;
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) b += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" class="gl"${v === 0 ? ' style="stroke:var(--chalk-3)"' : ''}/><text x="${L - 8}" y="${y(v) + 4}" text-anchor="end" class="ax">${v}</text>`;
  b += `<text x="14" y="${(T + H - B) / 2}" transform="rotate(-90 14 ${(T + H - B) / 2})" text-anchor="middle" class="ax">days slipped</text>`;
  wins.forEach((w, i) => {
    const x0 = cx(i) - bw / 2;
    if (w.slip_days > 0) {
      let acc = 0;
      cats.forEach(([k, c]) => {
        const v = w.apportioned[k] || 0;
        if (v <= 0) return;
        b += `<rect x="${x0}" y="${y(acc + v)}" width="${bw}" height="${Math.max(0.5, y(acc) - y(acc + v))}"${A('gy')} style="fill:${c};--d:${i * 90}ms"${tip(`${w.label}: ${labels[k]} ${v.toFixed(1)} days\n${w.events.map(e => `${e.count} ${e.label}`).join(', ') || 'no events reported'}`)}/>`;
        acc += v;
      });
    } else if (w.slip_days < 0) {
      b += `<rect x="${x0}" y="${y(0)}" width="${bw}" height="${y(w.slip_days) - y(0)}"${A('gy')} style="fill:var(--go);opacity:.7;--d:${i * 90}ms"${tip(`${w.label}: recovered ${(-w.slip_days).toFixed(1)} days`)}/>`;
    }
    if (w.concurrent) b += `<text x="${cx(i)}" y="${y(Math.max(0, w.slip_days)) - 8}" text-anchor="middle" style="fill:var(--mark);font:600 12px var(--text)"${tip('Client-side and contractor-side events in the same window: concurrent delay')}>concurrent</text>`;
    b += `<text x="${cx(i)}" y="${H - B + 18}" text-anchor="middle" class="axl">${esc(w.label)}</text>`;
    b += `<text x="${cx(i)}" y="${H - B + 34}" text-anchor="middle" class="ax">${w.elapsed_from.toFixed(0)}\u2013${w.elapsed_to.toFixed(0)}% time</text>`;
    b += `<text x="${cx(i)}" y="${H - B + 50}" text-anchor="middle" class="ax" style="fill:${w.slip_days > 0 ? 'var(--chalk)' : 'var(--go)'}">${w.slip_days > 0 ? '+' : ''}${w.slip_days.toFixed(1)} d</text>`;
  });
  el.innerHTML = svg(W, H, 'Slip per window between site updates, apportioned to reported events', b);
}

// ---------------------------------------------------------------- cockpit instruments
// An instrument-cluster gauge: a 260-degree dial with tick marks, coloured zones, a lit value arc and a needle,
// like a car's speedometer. zones: [{to, color}] in value units (the last one runs to max).
export function gauge(el, { value, min = 0, max = 100, zones = [], color = 'var(--amber)', label = '', text = null, sub = '', ticks = 5, size = 260 }) {
  const W = size, H = Math.round(size * 0.86), cx = W / 2, cy = W / 2, r = W * 0.40, sweep = 260, start = 90 + (360 - sweep) / 2;
  const v = Math.max(min, Math.min(max, Number.isFinite(value) ? value : min));
  const ang = t => (start + sweep * (t - min) / ((max - min) || 1)) * Math.PI / 180;
  const pt = (t, rr) => [cx + rr * Math.cos(ang(t)), cy + rr * Math.sin(ang(t))];
  const arc = (a, e, rr) => {
    const [x0, y0] = pt(a, rr), [x1, y1] = pt(e, rr);
    const large = (sweep * (e - a) / ((max - min) || 1)) > 180 ? 1 : 0;
    return `M${x0.toFixed(2)} ${y0.toFixed(2)} A${rr} ${rr} 0 ${large} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
  };
  let b = `<defs><filter id="glow-${el.id}" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="${(W / 70).toFixed(1)}" result="g"/><feMerge><feMergeNode in="g"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
    <radialGradient id="face-${el.id}"><stop offset="0" stop-color="#1B2027"/><stop offset=".72" stop-color="#0E1115"/><stop offset="1" stop-color="#07090B"/></radialGradient></defs>`;
  b += `<circle cx="${cx}" cy="${cy}" r="${r + W * 0.075}" style="fill:url(#face-${el.id});stroke:rgba(255,255,255,.06)"/>`;
  b += `<path d="${arc(min, max, r)}" style="fill:none;stroke:rgba(255,255,255,.07);stroke-width:${W * 0.05};stroke-linecap:round"/>`;
  let prev = min;
  for (const z of zones) {
    const e = Math.min(z.to ?? max, max);
    if (e > prev) b += `<path d="${arc(prev, e, r + W * 0.05)}" style="fill:none;stroke:${z.color};stroke-width:${W * 0.012};opacity:.75"/>`;
    prev = Math.max(prev, e);
  }
  for (let i = 0; i <= ticks * 4; i++) {
    const t = min + (max - min) * i / (ticks * 4), major = i % 4 === 0;
    const [x0, y0] = pt(t, r - W * (major ? 0.075 : 0.05)), [x1, y1] = pt(t, r - W * 0.03);
    b += `<line x1="${x0.toFixed(1)}" y1="${y0.toFixed(1)}" x2="${x1.toFixed(1)}" y2="${y1.toFixed(1)}" style="stroke:${major ? 'rgba(240,244,248,.7)' : 'rgba(240,244,248,.22)'};stroke-width:${major ? 2 : 1}"/>`;
    if (major && i > 0 && i < ticks * 4) {
      const [tx, ty] = pt(t, r - W * 0.14);
      b += `<text x="${tx.toFixed(1)}" y="${(ty + W * 0.016).toFixed(1)}" text-anchor="middle" class="g-tick">${Math.round(t)}</text>`;
    }
  }
  if (v > min) b += `<path d="${arc(min, v, r)}" filter="url(#glow-${el.id})" style="fill:none;stroke:${color};stroke-width:${W * 0.05};stroke-linecap:round"/>`;
  const [nx, ny] = pt(v, r - W * 0.02), [bx, by] = pt(v, -W * 0.05);
  b += `<line x1="${bx.toFixed(1)}" y1="${by.toFixed(1)}" x2="${nx.toFixed(1)}" y2="${ny.toFixed(1)}" style="stroke:${color};stroke-width:${W * 0.012};stroke-linecap:round" filter="url(#glow-${el.id})"/>`;
  b += `<circle cx="${cx}" cy="${cy}" r="${W * 0.035}" style="fill:#0B0E12;stroke:${color};stroke-width:2"/>`;
  b += `<text x="${cx}" y="${cy + W * 0.19}" text-anchor="middle" class="g-val">${esc(text ?? Math.round(v))}</text>`;
  if (sub) b += `<text x="${cx}" y="${cy + W * 0.275}" text-anchor="middle" class="g-sub">${esc(sub)}</text>`;
  if (label) b += `<text x="${cx}" y="${cy - W * 0.13}" text-anchor="middle" class="g-label">${esc(label)}</text>`;
  el.innerHTML = svg(W, H, `${label}: ${text ?? Math.round(v)}`, b);
}

// The building at the centre of the cluster, where a car dashboard shows the car: an isometric frame whose
// floors fill with the work done so far, tinted by the forecast band, with leader-line callouts for the readings.
export function building(el, { done = 0, color = 'var(--amber)', floors = 7, callouts = [] }) {
  // Isometric frame seen from its near corner (x = 0, y = 0): x runs right-down the front face, y left-down the side.
  const W = 520, H = 430, cx = 250, base = 386, fw = 150, fd = 92, fh = 34;
  const iso = (x, y, z) => [cx + (x - y) * 0.87, base - z + (x + y) * 0.5 - (fw + fd) * 0.5];
  const poly = pts => pts.map(p => p.map(n => n.toFixed(1)).join(',')).join(' ');
  const filled = Math.max(0, Math.min(floors, (done / 100) * floors)), top = floors * fh;
  let b = `<defs><linearGradient id="bf-${el.id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${color}" stop-opacity=".6"/><stop offset="1" stop-color="${color}" stop-opacity=".15"/></linearGradient>
    <radialGradient id="pad-${el.id}"><stop offset="0" stop-color="${color}" stop-opacity=".3"/><stop offset="1" stop-color="${color}" stop-opacity="0"/></radialGradient></defs>`;
  const g0 = iso(fw / 2, fd / 2, 0);
  b += `<ellipse cx="${g0[0].toFixed(1)}" cy="${(g0[1] + 6).toFixed(1)}" rx="235" ry="70" style="fill:url(#pad-${el.id})"/>`;
  for (let i = -3; i <= 6; i++) {          // setting-out grid on the ground
    const a = iso(i * 40 - 40, -60, 0), e = iso(i * 40 - 40, fd + 80, 0), c = iso(-80, i * 30 - 30, 0), d = iso(fw + 80, i * 30 - 30, 0);
    b += `<line x1="${a[0].toFixed(1)}" y1="${a[1].toFixed(1)}" x2="${e[0].toFixed(1)}" y2="${e[1].toFixed(1)}" class="b-grid"/><line x1="${c[0].toFixed(1)}" y1="${c[1].toFixed(1)}" x2="${d[0].toFixed(1)}" y2="${d[1].toFixed(1)}" class="b-grid"/>`;
  }
  // tower crane at the back corner (drawn first, so the frame hides the foot of its mast); the hook sits on the floor being built
  const H0 = top + 26, mx = fw * 0.55, my = fd + 26;
  const m0 = iso(mx, my, 0), m1 = iso(mx, my, H0), j0 = iso(mx, my + 34, H0), j1 = iso(mx, my - 150, H0);
  const hk = iso(mx, my - 112, H0), hb = iso(mx, my - 112, Math.min(H0 - 20, Math.max(filled * fh + 26, 40)));
  b += `<line x1="${m0[0].toFixed(1)}" y1="${m0[1].toFixed(1)}" x2="${m1[0].toFixed(1)}" y2="${(m1[1] - 16).toFixed(1)}" class="b-crane"/>`;
  b += `<line x1="${j0[0].toFixed(1)}" y1="${j0[1].toFixed(1)}" x2="${j1[0].toFixed(1)}" y2="${j1[1].toFixed(1)}" class="b-crane"/>`;
  b += `<line x1="${m1[0].toFixed(1)}" y1="${(m1[1] - 16).toFixed(1)}" x2="${j1[0].toFixed(1)}" y2="${j1[1].toFixed(1)}" class="b-cable"/>`;
  b += `<line x1="${hk[0].toFixed(1)}" y1="${hk[1].toFixed(1)}" x2="${hb[0].toFixed(1)}" y2="${hb[1].toFixed(1)}" class="b-cable"/><rect x="${(hb[0] - 7).toFixed(1)}" y="${hb[1].toFixed(1)}" width="14" height="9" class="b-load"/>`;
  for (let f = 0; f < floors; f++) {
    const z0 = f * fh, k = Math.max(0, Math.min(1, filled - f)), lit = k > 0;
    const front = [iso(0, 0, z0), iso(fw, 0, z0), iso(fw, 0, z0 + fh), iso(0, 0, z0 + fh)];
    const side = [iso(0, 0, z0), iso(0, fd, z0), iso(0, fd, z0 + fh), iso(0, 0, z0 + fh)];
    b += `<polygon points="${poly(front)}" class="b-face${lit ? ' lit' : ''}" style="${lit ? `fill:url(#bf-${el.id});opacity:${(0.4 + 0.6 * k).toFixed(2)}` : ''}"/>`;
    b += `<polygon points="${poly(side)}" class="b-side${lit ? ' lit' : ''}" style="${lit ? `fill:${color};opacity:${(0.12 + 0.25 * k).toFixed(2)}` : ''}"/>`;
    for (let c = 1; c < 5; c++) {
      const p = iso(fw * c / 5, 0, z0), q = iso(fw * c / 5, 0, z0 + fh);
      b += `<line x1="${p[0].toFixed(1)}" y1="${p[1].toFixed(1)}" x2="${q[0].toFixed(1)}" y2="${q[1].toFixed(1)}" class="b-col"/>`;
    }
    for (let c = 1; c < 3; c++) {
      const p = iso(0, fd * c / 3, z0), q = iso(0, fd * c / 3, z0 + fh);
      b += `<line x1="${p[0].toFixed(1)}" y1="${p[1].toFixed(1)}" x2="${q[0].toFixed(1)}" y2="${q[1].toFixed(1)}" class="b-col"/>`;
    }
    b += `<polyline points="${poly([iso(0, fd, z0 + fh), iso(0, 0, z0 + fh), iso(fw, 0, z0 + fh)])}" class="b-slab${lit ? ' lit' : ''}" style="${lit ? `stroke:${color};color:${color}` : ''}"/>`;
  }
  b += `<polygon points="${poly([iso(0, 0, top), iso(fw, 0, top), iso(fw, fd, top), iso(0, fd, top)])}" class="b-roof"/>`;
  // callouts: a dot on the frame, a leader line and the reading at the edge
  const anchors = [iso(fw * 0.5, 0, top * 0.86), iso(fw * 0.85, 0, top * 0.55), iso(0, fd * 0.6, top * 0.45), iso(fw * 0.7, 0, top * 0.15)];
  const slots = [[W - 14, 70], [W - 14, 205], [14, 150], [W - 14, 330]];
  callouts.slice(0, 4).forEach((c, i) => {
    const [ax, ay] = anchors[i], [sx, sy] = slots[i], left = sx < cx, elbow = left ? sx + 132 : sx - 132;
    b += `<polyline points="${ax.toFixed(1)},${ay.toFixed(1)} ${elbow},${sy} ${sx},${sy}" class="b-lead"${ANIM ? ` style="--d:${300 + i * 140}ms"` : ''}/>`;
    b += `<circle cx="${ax.toFixed(1)}" cy="${ay.toFixed(1)}" r="4.5" class="b-dot" style="fill:${c.color || 'var(--chalk)'}"/>`;
    b += `<text x="${sx}" y="${sy - 10}" text-anchor="${left ? 'start' : 'end'}" class="b-k">${esc(c.label)}</text>`;
    b += `<text x="${sx}" y="${sy + 16}" text-anchor="${left ? 'start' : 'end'}" class="b-v" style="fill:${c.color || 'var(--chalk)'}">${esc(c.value)}</text>`;
  });
  el.innerHTML = svg(W, H, `Work done ${Math.round(done)}%`, b);
}
