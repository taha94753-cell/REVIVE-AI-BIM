// REVIVE dashboard controller: form -> /api/predict -> /api/recovery -> twin, charts, impact.
// conn.js keeps the link to the Python server healthy, live.js carries phone updates,
// fx.js does the motion, charts.js draws every chart as SVG.
import * as C from './charts.js';
import * as fx from './fx.js';
import { api, post, del, upload, rawFetch, ping, onConnChange, noteFailure, waitForServer, heartbeat, setProject } from './conn.js';
import { LiveChannel } from './live.js';
import { enter, plate, roving, segs, to } from './tabs.js';
import { tilt } from './tilt.js';

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const S = {
  bimConnected: false, wxPinned: false, gate: 'G25', filter: 'all', query: '', band: null, mode: 'risk', sched: 'forecast',
  t: 0, playing: false, sourceId: null, evGate: 'G25', seq: 0, booted: false, livePid: null, devices: 0, presenceAt: 0,
  project: null, projects: [], tab: 'projects', wsSort: 'recent', wsQuery: '', delay: null,
};
const COL = { high: '#FF5468', medium: '#F5D547', low: '#34D399', complete: '#8E98A3', ghost: '#B4BCC6', mark: '#FF4FA3', idle: '#3A434F', progress: '#FFB81C', unlinked: '#4A5462' };
const REDUCED = fx.REDUCED;
const HINT = { award: 'Known at contract award', q1: 'Events in the first quarter of contract time', evm25: 'Earned value when 25% of contract time has passed', evm50: 'Earned value at the halfway point' };
const toast = fx.toast;
let tips;

const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const fmt = {
  pct: (v, d = 0) => v == null ? '\u2014' : `${v > 0 ? '+' : ''}${Number(v).toFixed(d)}%`,
  pkr: v => v == null ? '\u2014' : Math.abs(v) >= 1e6 ? `PKR ${(v / 1e6).toFixed(1)} M` : Math.abs(v) >= 1e3 ? `PKR ${Math.round(v / 1e3)}k` : `PKR ${Math.round(v)}`,
  num: (v, d = 0) => v == null ? '\u2014' : Number(v).toLocaleString('en', { maximumFractionDigits: d, minimumFractionDigits: d }),
  mo: d => (d / C.DPM).toFixed(1),
};

/** Network failures are shown by the connection banner; everything else gets a toast. */
function report(e) {
  if (e?.network) { noteFailure(); return; }
  console.error(e);
  toast(e?.message || String(e), 'error');
}

// ================================================================== form
function buildForm() {
  const host = $('#form-groups');
  host.innerHTML = S.schema.groups.map((g, i) => `
    <fieldset data-stage="${g.stage}">
      <legend><span class="step">${i + 1}</span>${esc(g.title)} <small>${esc(HINT[g.stage] || '')}</small></legend>
      <div class="fields">${g.fields.map(fieldHtml).join('')}</div>
    </fieldset>`).join('');
  $$('#form-groups input, #form-groups select').forEach(el => el.addEventListener('input', () => {
    if (S.sourceId) { S.sourceId = null; $('#source-note').textContent = 'Edited: scored as a new project.'; }
    syncWhatIf();
    if ($('#auto-run').checked && S.prediction) scheduleRun(el.tagName === 'SELECT' ? 150 : 550, { base: true });
  }));
}

function fieldHtml(f) {
  const id = `f-${f.key}`;
  const tag = f.bim ? '<span class="from-bim">from BIM</span>' : '';
  const unit = f.unit ? ` <span class="unit">(${esc(f.unit)})</span>` : '';
  const control = f.kind === 'number'
    ? `<input id="${id}" name="${f.key}" type="number" inputmode="decimal" min="${f.min ?? ''}" max="${f.max ?? ''}" step="${f.step ?? 'any'}" placeholder="Not known">`
    : `<select id="${id}" name="${f.key}"><option value="">Not known</option>${f.options.map(o => `<option>${esc(o)}</option>`).join('')}</select>`;
  return `<div class="field"><label for="${id}">${esc(f.label)}${unit}${tag}</label>${control}${f.help ? `<p class="help">${esc(f.help)}</p>` : ''}</div>`;
}

const allFields = () => S.schema.groups.flatMap(g => g.fields);
const field = key => allFields().find(f => f.key === key);

function readForm() {
  const out = {};
  allFields().forEach(f => {
    const v = $(`#f-${f.key}`).value;
    out[f.key] = v === '' ? null : f.kind === 'number' ? Number(v) : v;
  });
  return out;
}

function fillForm(inputs) {
  allFields().forEach(f => {
    const el = $(`#f-${f.key}`), v = inputs[f.key];
    el.value = v == null ? '' : String(v);
  });
  syncWhatIf();
}

function setGate(g) {
  S.gate = g;
  $$('#gate-switch button').forEach(b => b.setAttribute('aria-checked', String(b.dataset.gate === g)));
  const stages = S.schema.gates[g].stages;
  $$('#form-groups fieldset').forEach(fs => { fs.hidden = !stages.includes(fs.dataset.stage); });
  buildWhatIf();
}

// ================================================================== what-if sliders
function whatIfDefs() {
  const cp = S.gate === 'G50' ? '50' : '25';
  return [
    { key: `spi_${cp}`, label: `SPI at ${cp}% of contract time`, min: 0.4, max: 1.3, step: 0.01, hint: 'below 1.0 = behind programme' },
    { key: `cpi_${cp}`, label: `CPI at ${cp}% of contract time`, min: 0.4, max: 1.3, step: 0.01, hint: 'below 1.0 = over budget' },
    { key: 'late_payments_q1', label: 'IPCs paid more than 30 days late, first quarter', ordinal: true },
    { key: 'material_events_q1', label: 'Material shortages that stopped work, first quarter', ordinal: true },
    { key: 'variations_q1', label: 'Variation orders, first quarter', ordinal: true },
  ].filter(d => field(d.key));
}

function buildWhatIf() {
  if (!S.schema) return;
  const defs = whatIfDefs();
  $('#whatif-sliders').innerHTML = defs.map(d => {
    const f = field(d.key);
    const [mn, mx, st] = d.ordinal ? [0, f.options.length - 1, 1] : [d.min, d.max, d.step];
    return `<div class="wi" data-key="${d.key}"><div class="wi-top"><label for="wi-${d.key}">${esc(d.label)}</label><output id="wo-${d.key}"></output></div>
      <input type="range" id="wi-${d.key}" min="${mn}" max="${mx}" step="${st}" data-ordinal="${d.ordinal ? 1 : 0}">
      ${d.ordinal ? `<div class="ticks">${f.options.map(o => `<span>${esc(o)}</span>`).join('')}</div>` : `<div class="ticks"><span>${mn}</span><span>${esc(d.hint)}</span><span>${mx}</span></div>`}</div>`;
  }).join('');
  $$('#whatif-sliders input[type=range]').forEach(r => {
    r.addEventListener('pointerdown', () => C.animate(false));
    r.addEventListener('input', () => onWhatIf(r));
    r.addEventListener('change', () => { C.animate(true); });
  });
  syncWhatIf();
}

function syncWhatIf() {
  if (!S.schema) return;
  whatIfDefs().forEach(d => {
    const r = $(`#wi-${d.key}`), o = $(`#wo-${d.key}`), el = $(`#f-${d.key}`);
    if (!r || !el) return;
    const f = field(d.key);
    if (d.ordinal) {
      const i = f.options.indexOf(el.value);
      r.value = i < 0 ? 0 : i;
      r.classList.toggle('unset', i < 0);
      o.textContent = i < 0 ? 'not known' : el.value;
    } else {
      r.value = el.value === '' ? 1 : el.value;
      r.classList.toggle('unset', el.value === '');
      o.textContent = el.value === '' ? 'not known' : Number(el.value).toFixed(2);
    }
    paintRange(r);
  });
}

function paintRange(r) {
  const p = (r.value - r.min) / ((r.max - r.min) || 1);
  r.style.setProperty('--p', `${(p * 100).toFixed(1)}%`);
}

function onWhatIf(r) {
  const key = r.id.slice(3), f = field(key), el = $(`#f-${key}`);
  el.value = r.dataset.ordinal === '1' ? f.options[Number(r.value)] : Number(r.value).toFixed(2);
  r.classList.remove('unset');
  $(`#wo-${key}`).textContent = r.dataset.ordinal === '1' ? el.value : Number(r.value).toFixed(2);
  paintRange(r);
  if (S.sourceId) { S.sourceId = null; }
  $('#source-note').textContent = 'What-if scenario: the sliders changed the inputs. "Back to the entered values" undoes it.';
  scheduleRun(90, { quick: true });
}

// ================================================================== forecast
let runTimer = null;
function scheduleRun(ms, opts) { clearTimeout(runTimer); runTimer = setTimeout(() => runForecast(opts), ms); }

/** opts.quick: slider drag (no entry animations, no weather refresh). opts.base: these inputs become the what-if reset point. */
async function runForecast(opts = {}) {
  const seq = ++S.seq, btn = $('#run-btn');
  if (!opts.quick) { btn.disabled = true; btn.textContent = 'Forecasting'; }
  $('#result').classList.add('busy');
  try {
    S.inputs = readForm();
    if (!opts.quick || !S.baseInputs) S.baseInputs = { ...S.inputs };  // slider runs keep the reset point
    if (!opts.keepElapsed) S.elapsedPct = null;
    const pred = await post('/predict', { inputs: S.inputs, gate: S.gate, source_project_id: S.sourceId });
    if (seq !== S.seq) return;
    S.prevPrediction = S.prediction;
    S.prediction = pred;
    C.animate(!opts.quick);
    renderResult();
    await runRecovery({ seq, quick: opts.quick });
    if (!opts.quick) syncWeatherToProvince();
  } catch (e) { report(e); }
  finally {
    C.animate(true);
    if (seq === S.seq) { btn.disabled = false; btn.textContent = 'Run forecast'; $('#result').classList.remove('busy'); }
  }
}

// ================================================================== instrument cluster
const riskZones = () => [{ to: 30, color: 'var(--go)' }, { to: 60, color: 'var(--watch)' }, { to: 100, color: 'var(--crit)' }];
const bandZones = () => S.schema.risk_bands.map(b => ({ to: b.max, color: b.color }));
const numOr = v => (v === '' || v == null || !Number.isFinite(Number(v)) ? null : Number(v));

/** The cluster before any forecast: needles at rest, an empty frame. */
function renderClusterIdle() {
  C.gauge($('#g-overrun'), { value: 0, max: 100, zones: bandZones(), color: 'var(--chalk-3)', label: 'Time overrun', text: '\u2014', sub: '% over contract time' });
  C.gauge($('#g-risk'), { value: 0, max: 100, zones: riskZones(), color: 'var(--chalk-3)', label: 'High-risk chance', text: '\u2014', sub: 'of a >40% overrun' });
  C.building($('#cl-building'), { done: 0, color: 'var(--chalk-3)', callouts: [] });
  $('#telltales').innerHTML = '';
}

/** Gauges, building and warning lights for a forecast. k runs 0 to 1 while the needles sweep. */
function drawCluster(p, v, prob, health) {
  const band = p.band, inp = S.inputs || {}, g50 = p.gate === 'G50';
  C.gauge($('#g-overrun'), { value: v, max: 100, zones: bandZones(), color: band.color, label: 'Time overrun', text: fmt.pct(v),
    sub: `80% range ${fmt.pct(p.time_interval_pct[0])} to ${fmt.pct(p.time_interval_pct[1])}` });
  const pc = Math.round(prob * 100);
  C.gauge($('#g-risk'), { value: pc, max: 100, zones: riskZones(), color: pc >= 60 ? 'var(--crit)' : pc >= 30 ? 'var(--watch)' : 'var(--go)',
    label: 'High-risk chance', text: `${pc}%`, sub: `of a >${p.high_risk_threshold_pct}% overrun` });
  $('#cl-health').textContent = Math.round(health);
  const hb = $('#cl-health-bar');
  hb.style.width = `${Math.max(0, Math.min(100, health))}%`;
  hb.style.background = health >= 75 ? 'var(--go)' : health >= 60 ? 'var(--watch)' : health >= 40 ? 'var(--risk)' : 'var(--crit)';
  return { band, inp, g50 };
}

function renderCluster(p) {
  const inp = S.inputs || {}, g50 = p.gate === 'G50';
  const spi = numOr(inp[g50 ? 'spi_50' : 'spi_25']), cpi = numOr(inp[g50 ? 'cpi_50' : 'cpi_25']), cert = numOr(inp[g50 ? 'cert_50' : 'cert_25']);
  const done = cert ?? (spi != null ? spi * (g50 ? 50 : 25) : (g50 ? 50 : 25));
  const tone = (x, good, warn) => x == null ? 'var(--chalk-3)' : x >= good ? 'var(--go)' : x >= warn ? 'var(--watch)' : 'var(--crit)';
  C.building($('#cl-building'), { done, color: p.band.color, callouts: [
    { label: 'Forecast finish', value: p.forecast_months ? `${fmt.num(p.forecast_months, 1)} months` : fmt.pct(p.time_overrun_pct), color: p.band.color },
    { label: `SPI at ${g50 ? 50 : 25}%`, value: spi == null ? 'not given' : spi.toFixed(2), color: tone(spi, 0.95, 0.85) },
    { label: 'Value certified', value: cert == null ? 'not given' : `${fmt.num(cert, 0)}% of contract`, color: 'var(--cyan)' },
    { label: `CPI at ${g50 ? 50 : 25}%`, value: cpi == null ? 'not given' : cpi.toFixed(2), color: tone(cpi, 0.95, 0.85) },
  ] });
  $('#cl-overrun-cap').textContent = p.planned_months ? `${fmt.num(p.planned_months, 1)} months planned` : 'Over the contract duration';
  $('#cl-risk-cap').textContent = `High risk: overrun above ${p.high_risk_threshold_pct}%`;
  $('#cl-band').textContent = p.band.name;
  $('#cl-band').style.setProperty('--c', p.band.color);
  $('#cl-gate').textContent = p.gate_label;
  const lights = [
    { k: 'Recovery', on: p.recovery_recommended, c: 'var(--mark)', t: p.recovery_recommended ? 'Recovery plan recommended' : 'No recovery trigger' },
    { k: 'Pace', on: spi != null && spi < 0.9, c: 'var(--crit)', t: spi == null ? 'SPI not given' : `SPI ${spi.toFixed(2)}` },
    { k: 'Cost', on: cpi != null && cpi < 0.9, c: 'var(--risk)', t: cpi == null ? 'CPI not given' : `CPI ${cpi.toFixed(2)}` },
    { k: 'Late IPCs', on: /[1-9]/.test(String(inp.late_payments_q1 || '')), c: 'var(--watch)', t: `IPCs paid late: ${inp.late_payments_q1 || 'not given'}` },
    { k: 'Blanks', on: p.missing_inputs.length > 0, c: 'var(--chalk-2)', t: `${p.missing_inputs.length} answers left blank` },
  ];
  $('#telltales').innerHTML = lights.map(l => `<li class="${l.on ? 'on' : ''}" style="--c:${l.c}" data-tip="${esc(l.t)}"><i></i>${esc(l.k)}</li>`).join('');
  const acts = p.actions || [];
  $('#actions-card').hidden = !acts.length;
  $('#acts').innerHTML = acts.map(a => `<li><span class="owner o-${esc(a.owner)}">${esc(a.owner_label)}</span>
    <b>${esc(a.reason)}</b><span class="adds">+${a.adds_pct_points.toFixed(1)} pts</span><p>${esc(a.action)}</p></li>`).join('');
}

function renderResult() {
  const p = S.prediction, band = p.band, tr = p.training_record;
  const planned = p.planned_months, fc = p.forecast_months;
  const prev = S.prevPrediction && S.prevPrediction.gate === p.gate ? S.prevPrediction : null;
  const delta = prev ? p.time_overrun_pct - prev.time_overrun_pct : null;
  const shown = S.shown || {};
  $('#result-body').innerHTML = `
    <div class="result-head"><span class="chip" style="--c:${band.color}">${esc(band.name)}</span><span>${esc(p.gate_label)}</span></div>
    <div class="big-row"><p class="big" id="big" style="color:${shown.color || band.color}">${fmt.pct(shown.v ?? p.time_overrun_pct)}</p>
      ${delta != null && Math.abs(delta) >= 0.05 ? `<span class="delta ${delta > 0 ? 'up' : 'down'}" title="Change from the previous forecast">${delta > 0 ? '\u25B2' : '\u25BC'} ${Math.abs(delta).toFixed(1)} pts</span>` : ''}</div>
    <p class="big-cap">Forecast time overrun${planned ? `: ${fmt.num(planned, 1)} months planned, ${fmt.num(fc, 1)} forecast` : ''}. 80% range ${fmt.pct(p.time_interval_pct[0])} to ${fmt.pct(p.time_interval_pct[1])}.</p>
    <div id="range" class="chart"></div>
    <dl class="metrics">
      <div><dt>Project health score</dt><dd><div id="dial" class="chart"></div></dd></div>
      <div><dt>Chance of more than ${p.high_risk_threshold_pct}% overrun</dt><dd><span id="m-prob"></span><i class="meter"><b id="m-prob-bar" style="width:${Math.round((shown.prob ?? 0) * 100)}%"></b></i></dd></div>
      <div><dt>Forecast cost overrun</dt><dd><span id="m-cost"></span><small>range ${fmt.pct(p.cost_interval_pct[0])} to ${fmt.pct(p.cost_interval_pct[1])}</small></dd></div>
    </dl>
    ${p.recovery_recommended ? `<div class="triggers"><strong>Recovery plan recommended</strong><ul>${(p.recovery_triggers.length ? p.recovery_triggers : [`Forecast band is ${band.name}`]).map(t => `<li>${esc(t)}</li>`).join('')}</ul><a class="btn mark" href="#recover">See the recovery plan</a></div>`
      : '<p class="note">No recovery trigger: health score, SPI and CPI are within limits.</p>'}
    ${tr ? `<p class="note">${esc(tr.note)} Out-of-fold forecast: ${fmt.pct(tr.oof_time_overrun_pct, 1)}; recorded overrun: ${fmt.pct(tr.actual_time_overrun_pct, 1)}.</p>` : ''}
    ${p.missing_inputs.length ? `<p class="fine">${p.missing_inputs.length} answers left blank: ${esc(p.missing_inputs.slice(0, 4).join(', '))}${p.missing_inputs.length > 4 ? ' and others' : ''}.</p>` : ''}`;

  // animate from what was on screen to the new forecast
  const big = $('#big');
  requestAnimationFrame(() => { big.style.color = band.color; });
  const from = { v: shown.v ?? p.time_overrun_pct, lo: shown.lo ?? p.time_interval_pct[0], hi: shown.hi ?? p.time_interval_pct[1], h: shown.h ?? 0, prob: shown.prob ?? 0, cost: shown.cost ?? 0 };
  const to = { v: p.time_overrun_pct, lo: p.time_interval_pct[0], hi: p.time_interval_pct[1], h: p.health.score, prob: p.high_risk_probability, cost: p.cost_overrun_pct };
  S.shown = { ...to, color: band.color };
  const lerp = (a, b, k) => a + (b - a) * k;
  fx.tween('result', 0, 1, S.prevPrediction ? 650 : 900, k => {
    const v = lerp(from.v, to.v, k);
    big.textContent = fmt.pct(v);
    drawCluster(p, v, lerp(from.prob, to.prob, k), lerp(from.h, to.h, k));
    C.rangeBar($('#range'), { value: v, lo: lerp(from.lo, to.lo, k), hi: lerp(from.hi, to.hi, k), bands: S.schema.risk_bands });
    C.dial($('#dial'), lerp(from.h, to.h, k));
    $('#m-prob').textContent = `${Math.round(lerp(from.prob, to.prob, k) * 100)}%`;
    $('#m-cost').textContent = fmt.pct(lerp(from.cost, to.cost, k));
  });
  requestAnimationFrame(() => { const b = $('#m-prob-bar'); if (b) b.style.width = `${Math.round(to.prob * 100)}%`; });
  C.waterfall($('#waterfall'), p.explanation, p.time_overrun_pct);
  renderCluster(p);
  $('#whatif').hidden = false;
  $('#save-row').hidden = false;
  if (!$('#save-name').value || $('#save-name').dataset.auto === '1') { $('#save-name').value = S.presetName || ''; $('#save-name').dataset.auto = '1'; }
}

async function saveAssessment() {
  if (!S.project) { toast('Create or open a project first: assessments are saved to a project.', 'info', { action: { label: 'New project', run: openProjectModal } }); return; }
  const name = $('#save-name').value.trim() || S.project.name;
  try {
    const o = S.recovery?.optimisation;
    const res = await post('/assessments', { name, inputs: S.inputs, gate: S.prediction.gate,
      recovery: o ? { days_recovered: o.days_recovered, crash_cost_pkr: o.crash_cost_pkr, net_saving_pkr: o.net_saving_pkr } : null });
    const a = res.alert || {};
    toast(a.channel === 'email' ? `Saved to ${S.project.name}. Alert e-mailed to the team.` : a.channel === 'outbox' ? `Saved to ${S.project.name}. Alert written to the outbox (e-mail not configured).` : `Saved to ${S.project.name}.`, 'ok');
    S.project.inputs = { ...S.inputs }; S.project.has_inputs = true;
    loadProjects(); refreshDelay();
  } catch (e) { report(e); }
}

// ================================================================== recovery
function recoveryBody() {
  const p = S.prediction, num = id => { const v = $(id).value; return v === '' ? null : Number(v); };
  return { gate: p.gate, spi: S.inputs[p.gate === 'G50' ? 'spi_50' : 'spi_25'], time_overrun_pct: p.time_overrun_pct,
    high_risk_probability: p.high_risk_probability, rework: S.inputs.rework_q1,
    ld_per_day: num('#ld'), budget_pkr: num('#budget'), deadline_day: num('#deadline'), elapsed_pct: S.elapsedPct ?? null,
    weather_lost_offsets: $('#wx-apply').checked && S.weather?.available ? S.weather.lost_forecast_offsets : null };
}

async function runRecovery({ seq = null, quick = false } = {}) {
  if (!S.prediction) { toast('Run a forecast first.'); return; }
  try {
    const rec = await post('/recovery', recoveryBody());
    if (seq != null && seq !== S.seq) return;
    S.recovery = rec;
    C.animate(!quick);
    renderRecovery(); renderImpact(); setupTimeline(); paintTwin();
    if (S.portfolio) markRiskMap();
  } catch (e) { report(e); }
  finally { if (!quick) C.animate(true); }
}

function kpiCells(host, items) {
  host.innerHTML = items.map(([k, , , c], i) => `<div class="kpi" style="--d:${i * 80}ms"><dt>${k}</dt><dd class="${c || ''}" data-i="${i}"></dd></div>`).join('');
  items.forEach(([, v, f], i) => fx.countUp(host.querySelector(`dd[data-i="${i}"]`), v ?? 0, f, 900));
}

function renderRecovery() {
  const r = S.recovery, o = r.optimisation;
  $('#recover-intro').textContent = `A linear programme chooses which activities of the baseline schedule (${r.activities.length} activities, planned ${r.months.planned} months) to accelerate, so every day bought costs less than a day of liquidated damages.`;
  if (o.status !== 'Optimal') {
    $('#rec-summary').textContent = o.message; $('#rec-kpis').innerHTML = ''; return;
  }
  const late = o.days_late_before > 0;
  $('#rec-summary').textContent = !late
    ? `The forecast finish (month ${fmt.mo(o.forecast_finish_day)}) is within the target (month ${fmt.mo(o.deadline_day)}), so no acceleration is bought.`
    : o.plan.length === 0
      ? `The forecast finish is ${fmt.num(o.days_late_before)} days late, but every available acceleration costs more per day than the liquidated damages, so the cheapest plan is to accept the delay.`
      : `The forecast finish is month ${fmt.mo(o.forecast_finish_day)}, ${fmt.num(o.days_late_before)} days after the target. Accelerating ${o.plan.length} activities for ${fmt.pkr(o.crash_cost_pkr)} brings completion forward ${fmt.num(o.days_recovered)} days and cuts liquidated damages from ${fmt.pkr(o.ld_before_pkr)} to ${fmt.pkr(o.ld_after_pkr)}.`;
  if (r.weather) $('#rec-summary').textContent += ` Live weather: ${r.weather.lost_days_ahead} likely lost days in the forecast window add ${r.weather.finish_shift_days} days to the forecast finish${r.weather.affected.length ? ` through ${r.weather.affected.slice(0, 3).map(a => a.name.toLowerCase()).join(', ')}` : ''}.`;
  kpiCells($('#rec-kpis'), [
    ['Days recovered', o.days_recovered, v => fmt.num(v), 'mark'], ['Recovery cost', o.crash_cost_pkr, fmt.pkr],
    ['Liquidated damages avoided', o.ld_before_pkr - o.ld_after_pkr, fmt.pkr], ['Net saving', o.net_saving_pkr, fmt.pkr],
  ]);
  C.curve($('#curve'), r.curve, { day: o.recovered_finish_day, total: o.crash_cost_pkr + o.ld_after_pkr });
  $('#plan-table tbody').innerHTML = o.plan.length ? o.plan.map((p, i) => `<tr style="--d:${Math.min(400, i * 40)}ms"><td>${esc(p.name)}${p.on_critical_path ? ' <span class="tag" style="color:var(--chalk-2);border-color:var(--line-strong)">critical</span>' : ''}</td>
      <td class="muted">${esc(p.method)}</td><td class="n">${fmt.num(p.crashed_days, 1)}</td><td class="n">${fmt.pkr(p.cost_pkr)}</td></tr>`).join('')
    : '<tr><td colspan="4" class="muted">No activity is worth accelerating at these rates.</td></tr>';
  const marks = [
    { day: r.t0_day, label: 'Checkpoint', color: 'var(--chalk)' },
    { day: r.deadline_day, label: 'Target completion', color: 'var(--go)', dash: '5 4' },
    { day: r.forecast_finish_day, label: 'Forecast finish', color: 'var(--risk)' },
    { day: o.recovered_finish_day, label: 'Recovered finish', color: 'var(--mark)' },
  ];
  C.gantt($('#gantt'), r.activities, marks);
  const sim = r.simulation;
  $('#sim').hidden = !sim;
  if (sim) {
    $('#sim-big').innerHTML = `P80 finish month ${fmt.mo(sim.p80_before_day)} now, <span class="mark">month ${fmt.mo(sim.p80_after_day)}</span> with the plan`;
    $('#sim-note').textContent = `Chance of finishing by the target (month ${fmt.mo(sim.deadline_day)}): ${Math.round(sim.p_on_time_before * 100)}% now, ${Math.round(sim.p_on_time_after * 100)}% with the plan. P80 means 80% of simulated finishes fall on or before that month. ${sim.method}`;
    C.distribution($('#dist'), sim);
    const dr = sim.drivers || [];
    $('#drivers-wrap').hidden = !dr.length;
    $('#crit').innerHTML = dr.map(d => {
      const pc = Math.round(d.criticality * 100), c = pc >= 80 ? 'var(--crit)' : pc >= 40 ? 'var(--risk)' : 'var(--watch)';
      return `<li><span class="cn"><b>${esc(d.id)}</b> ${esc(d.name)}${d.crash_days > 0 ? `<em class="crash">plan: \u2212${fmt.num(d.crash_days, 1)} d</em>` : ''}</span>
        <i class="cbar"><b style="width:${pc}%;background:${c}"></b></i><span class="cp">${pc}%</span></li>`;
    }).join('');
  }
  $('#formulation').innerHTML = `<pre>${esc(o.formulation.objective)}\nsubject to\n  ${o.formulation.constraints.map(esc).join('\n  ')}\n\nSolver: ${esc(o.formulation.solver)}</pre>
    <p class="fine">d = forecast remaining duration (baseline scaled by k = ${r.duration_scale_k} so the schedule finish matches the ML forecast), c = crash cost per day, u = crash limit, LD = liquidated damages per day, D = target completion, t0 = day ${r.t0_day} (checkpoint). Work done by the checkpoint follows Earned Schedule: ES = SPI x t0 = day ${r.earned_schedule_day}.</p>`;
}

function renderImpact() {
  const s = S.recovery.sustainability, o = S.recovery.optimisation;
  const items = [
    ['Carbon avoided', s.co2_diesel_t_avoided, v => `${fmt.num(v, 1)} t`, `CO\u2082 from ${fmt.num(s.diesel_l_avoided)} litres of site diesel over ${fmt.num(s.days_recovered)} days`],
    ['Site overheads avoided', s.overheads_pkr_avoided, fmt.pkr, 'Time-related costs not incurred'],
    ['Net benefit of recovery', s.net_benefit_pkr, fmt.pkr, 'Damages and overheads avoided, less crash cost'],
    s.rework_carbon_at_risk_t == null
      ? ['Rework carbon at risk', null, () => '\u2014', 'Needs a BIM model to measure the structure']
      : ['Rework carbon at risk', s.rework_carbon_at_risk_t, v => `${fmt.num(v, 1)} t`, `${(s.rework_share * 100).toFixed(1)}% of ${fmt.num(s.structure_embodied_t)} t embodied in the structure`],
  ];
  $('#impact-figs').innerHTML = items.map(([k, , , sub], i) => `<div><dt>${k}</dt><dd><span data-i="${i}"></span><small>${sub}</small></dd></div>`).join('');
  items.forEach(([, v, f], i) => { const el = $(`#impact-figs span[data-i="${i}"]`); if (v == null) el.textContent = '\u2014'; else fx.countUp(el, v, f, 1100); });
  if (o.status === 'Optimal') C.costCompare($('#cost-compare'), o); else $('#cost-compare').innerHTML = '';
  $('#assumptions tbody').innerHTML = s.assumptions.map(a => `<tr><td>${esc(a.item)}</td><td class="n">${fmt.num(a.value, a.value < 10 ? 3 : 0)}</td><td>${esc(a.unit)}</td>
    <td>${a.verify ? '<span class="verify">Verify and cite (config.yaml)</span>' : '<span class="muted">Measured from the IFC model</span>'}</td></tr>`).join('');
}

// ================================================================== twin
function acts() { return Object.fromEntries((S.recovery?.activities || []).map(a => [a.id, a])); }

function riskStyle(u, A) {
  const a = A[u.activity];
  if (!a) return { color: COL.unlinked, opacity: 0.3 };
  if (a.status === 'complete') return { color: COL.complete };
  const skin = u.ifc_class === 'IfcWall' || u.ifc_class === 'IfcCovering' || u.ifc_class.startsWith('IfcCurtainWall');
  return { color: COL[a.risk_level], glow: a.status === 'in progress' ? 0.3 : 0.08, opacity: skin ? 0.42 : 1 };
}

function styleFor(u, A) {
  if (S.mode === 'risk') return riskStyle(u, A);
  const a = A[u.activity];
  if (S.mode === 'recovery') {
    if (!a) return { color: COL.unlinked, opacity: 0.2 };
    if (a.crash_days > 0) return { color: COL.mark, glow: Math.min(0.55, 0.15 + a.crash_days / 40) };
    return a.status === 'complete' ? { color: COL.complete, opacity: 0.8 } : { color: COL.idle, opacity: 0.55 };
  }
  if (!a) return { color: COL.ghost, opacity: 0.05, edge: 0.06 };
  const [s, f] = a[S.sched];
  if (S.t < s) return { color: COL.ghost, opacity: 0.05, edge: 0.07 };
  if (S.t >= f) return { color: '#C4CBD2' };
  return { color: COL.progress, glow: 0.35 };
}

function paintTwin() {
  if (!S.twin) return;
  const A = acts();
  S.twin.paint(u => styleFor(u, A), { instant: S.playing || S.scrubbing });
  renderLegend();
}

function renderLegend() {
  const items = S.mode === 'risk'
    ? [['High risk', COL.high], ['Medium', COL.medium], ['Low', COL.low], ['Complete', COL.complete], ['Not linked', COL.unlinked]]
    : S.mode === 'recovery' ? [['Accelerated in the plan', COL.mark], ['Not accelerated', COL.idle], ['Complete', COL.complete]]
      : [['Not started', '#5C6673'], ['Under construction', COL.progress], ['Built', '#C4CBD2']];
  $('#legend').innerHTML = items.map(([t, c]) => `<span><i style="--c:${c}"></i>${t}</span>`).join('');
}

function setMode(m) {
  S.mode = m;
  $$('.hud-modes button').forEach(b => b.setAttribute('aria-selected', String(b.dataset.mode === m)));
  paintTwin();
}

function maxDay() {
  const r = S.recovery;
  return r ? Math.ceil(Math.max(r.forecast_finish_day, r.planned_finish_day) * 1.02) : 400;
}

function setupTimeline() {
  const r = S.recovery, max = maxDay(), sc = $('#scrub');
  sc.max = max;
  if (S.t > max) S.t = max;
  const marks = [[r.t0_day, 'Checkpoint', 'var(--chalk)'], [r.deadline_day, 'Target', 'var(--go)'],
    [r.forecast_finish_day, 'Forecast', 'var(--risk)'], [r.optimisation.recovered_finish_day ?? r.forecast_finish_day, 'Recovered', 'var(--mark)']];
  $('#marks').innerHTML = marks.map(([d, l, c]) => `<b style="left:${(100 * d / max).toFixed(2)}%;--c:${c}" data-l="${l}"></b>`).join('');
  updateReadout();
}

function updateReadout() {
  const sc = $('#scrub');
  sc.value = S.t;
  sc.style.setProperty('--p', `${(100 * S.t / (Number(sc.max) || 1)).toFixed(2)}%`);
  $('#readout').textContent = `Day ${Math.round(S.t)}, month ${fmt.mo(S.t)}`;
}

function togglePlay() {
  S.playing = !S.playing;
  $('#play').textContent = S.playing ? 'Pause' : 'Play';
  $('#play').classList.toggle('on', S.playing);
  if (!S.twin) return;
  if (S.playing) {
    if (S.mode !== 'build') setMode('build');
    if (S.t >= maxDay()) S.t = 0;
    S.twin.tick = dt => {
      S.t = Math.min(maxDay(), S.t + dt * maxDay() / 14);
      updateReadout(); paintTwin();
      if (S.t >= maxDay()) togglePlay();
    };
  } else S.twin.tick = null;
}

function renderInspector(u) {
  const box = $('#inspector');
  if (!u) { box.innerHTML = '<p class="muted">Select an element to see its activity, float and recovery.</p>'; return; }
  const a = acts()[u.activity];
  const row = (k, v) => `<dt>${k}</dt><dd>${v}</dd>`;
  box.innerHTML = `<h4>${esc(u.name)}</h4><p class="muted">${esc(u.ifc_class)} on ${esc(u.storey)}${u.material ? `, ${esc(u.material)}` : ''}</p>` + (a ? `<dl>
    ${row('Activity', `${esc(a.id)} ${esc(a.name)}`)}${row('Status', `${esc(a.status)}${a.pct_complete > 0 && a.pct_complete < 100 ? ` (${a.pct_complete}%)` : ''}`)}
    ${row('Planned', `day ${a.baseline[0]} to ${a.baseline[1]}`)}${row('Forecast finish', `day ${a.forecast[1]} (month ${fmt.mo(a.forecast[1])})`)}
    ${row('Recovered finish', `day ${a.recovered[1]}`)}${row('Total float', a.total_float == null ? '\u2014' : `${a.total_float} days${a.critical ? ', critical' : ''}`)}
    ${row('Risk', `<span class="chip" style="--c:${COL[a.risk_level]}">${esc(a.risk_level)}</span> ${a.status === 'complete' ? '' : `score ${a.risk_score}`}`)}
    ${row('Recovery', a.crash_days > 0 ? `${a.crash_days} days faster: ${esc(a.crash_method)}` : 'not accelerated')}</dl>`
    : '<p class="note">Not linked to a schedule activity. Give it a WBS_Code property (a Revit shared parameter) or add a storey and IFC-class rule in schedule.csv.</p>');
  fx.pulse(box, 'pop-in');
}

function hoverText(u) {
  const a = acts()[u.activity];
  return `${u.name}\n${u.ifc_class} on ${u.storey}` + (a ? `\n${a.id} ${a.name}: ${a.status}${a.status === 'complete' ? '' : `, ${a.risk_level} risk`}${a.crash_days > 0 ? `\nRecovery: ${a.crash_days} days faster` : ''}` : '\nNot linked to the schedule');
}

async function loadTwins() {
  $('#stage').classList.toggle('no-bim', !S.bimConnected);
  $('#bim-off').hidden = S.bimConnected;
  if (!S.bimConnected) {
    S.geom = null;
    if (S.twin) S.twin.clear();
    return;
  }
  try {
    const { Twin } = await import('./twin.js');
    S.geom = await api('/bim/geometry');
    if (!S.twin) {
      S.twin = new Twin($('#twin-canvas'));
      S.twin.onPick(u => { renderInspector(u); paintTwin(); });
      S.twin.onHover((u, x, y) => { if (u) tips.show(hoverText(u), x, y); else tips.hide(); });
    }
    S.twin.load(S.geom);
    paintTwin();
  } catch (e) {
    if (e?.network) { report(e); return; }
    console.error(e);
    $('#stage').insertAdjacentHTML('beforeend', `<div class="webgl-off">The 3D view could not start (${esc(e.message)}). Forecasts, recovery and evidence still work.</div>`);
  }
}

async function refreshBimSummary() {
  S.summary = await api('/bim/summary');
  const q = S.summary.quantities, sc = S.summary.schedule;
  S.bimConnected = !!S.summary.connected;
  $('#sched-summary').innerHTML = `${sc.demo ? '<span class="tag demo">demo</span> ' : ''}Baseline schedule <strong>${esc(sc.file)}</strong>: ${sc.activities} activities, ${fmt.num(sc.planned_months, 1)} months planned, ${sc.weather_sensitive} weather-sensitive.${S.project ? '' : ' Open a project to upload its own schedule.'}`;
  $('#bim-fill').textContent = S.bimConnected ? 'Fill size and duration from the BIM model and schedule' : 'Fill duration from the baseline schedule';
  $('#twin .twin-bar .twin-actions').hidden = !S.bimConnected;
  if (!S.bimConnected) {
    $('#bim-summary').textContent = 'No BIM model connected. Forecasts, recovery, live monitoring and reports run on the baseline schedule.';
    return;
  }
  $('#bim-summary').innerHTML = `<strong>${esc(q.file)}</strong>: ${fmt.num(q.elements)} elements, ${fmt.num(q.mapped_elements)} linked to ${sc.activities} schedule activities (${esc(q.mapping_source)}). ${q.storeys_above_ground} storeys, ${fmt.num(q.gross_floor_area_m2)} m\u00b2 floor area, ${fmt.num(q.concrete_m3)} m\u00b3 concrete.`;
}

async function uploadFile(kind, input) {
  const f = input.files[0];
  if (!f) return;
  if (!S.project) { toast('Open a project first: uploads belong to a project.'); input.value = ''; return; }
  const close = toast(kind === 'ifc' ? `Reading ${f.name}. Large models can take a minute.` : `Checking ${f.name}.`, 'info', { sticky: true });
  try {
    const d = await upload(kind === 'ifc' ? '/bim/upload' : '/schedule/upload', f);
    await afterFilesChanged();
    if (kind === 'ifc') {
      const q = S.summary.quantities;
      toast(`${f.name} loaded: ${q.mapped_elements} of ${q.elements} elements linked to the schedule.`, 'ok');
    } else {
      const rp = d.import_report || {};
      toast(`${f.name}: ${rp.activities} activities imported (${rp.format}). ${(rp.warnings || []).join(' ')}`, 'ok');
    }
  } catch (e) { report(e); }
  finally { close?.(); input.value = ''; }
}

async function afterFilesChanged() {
  await refreshBimSummary();
  await loadTwins();
  if (S.prediction) await runRecovery();
  refreshDelay(); loadProjects();
}

async function exportIfc() {
  if (!S.prediction) { toast('Run a forecast first.'); return; }
  try {
    const name = $('#save-name')?.value.trim() || S.project?.name || 'REVIVE assessment';
    const r = await rawFetch('/bim/export', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...recoveryBody(), project_name: name }) });
    if (!r.ok) throw new Error((await r.json()).detail);
    const blob = await r.blob(), a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = (r.headers.get('content-disposition') || '').split('filename=')[1]?.replace(/"/g, '') || 'revive_risk.ifc';
    a.click(); URL.revokeObjectURL(a.href);
    toast('IFC exported with Pset_REVIVE_Risk on every linked element. Open it in Revit, Navisworks or any IFC viewer.', 'ok');
  } catch (e) { report(e); }
}

// ================================================================== portfolio
async function loadPortfolio() {
  S.portfolio = await api('/portfolio');
  S.byId = Object.fromEntries(S.portfolio.dataset.map(r => [r.project_id, r]));
  renderOverview();
  renderPortfolio();
}

const bandColor = name => (S.schema.risk_bands.find(b => b.name === name) || {}).color || 'var(--chalk-3)';

function matches(r) {
  const q = S.query.toLowerCase();
  if (S.filter === 'ongoing' && r.status !== 'Still ongoing') return false;
  if (S.filter === 'completed' && r.status !== 'Completed') return false;
  if (S.filter === 'risk' && !['At risk', 'Critical'].includes(r.band?.name)) return false;
  if (S.band && r.band?.name !== S.band) return false;
  return !q || `${r.project_type} ${r.province} ${r.project_id}`.toLowerCase().includes(q);
}

function renderOverview() {
  const rows = S.portfolio.dataset, bands = S.schema.risk_bands;
  const counts = bands.map(b => ({ key: b.name, label: b.name, color: b.color, value: rows.filter(r => r.band?.name === b.name).length }));
  const risky = counts.filter(c => ['At risk', 'Critical'].includes(c.key)).reduce((t, c) => t + c.value, 0);
  const vals = rows.map(r => r.predicted_time_overrun_pct).filter(Number.isFinite).sort((a, b) => a - b);
  const med = vals.length ? (vals[Math.floor((vals.length - 1) / 2)] + vals[Math.ceil((vals.length - 1) / 2)]) / 2 : null;
  const done = rows.filter(r => r.status === 'Completed').length;
  const ov = $('#ov-kpis');
  const kp = [
    ['Projects in the dataset', rows.length, v => fmt.num(v), `${rows.filter(r => r.hypothetical).length} hypothetical, labelled`],
    ['Median forecast overrun', med, v => fmt.pct(v, 1), 'cross-validated, out-of-fold'],
    ['At risk or critical', risky, v => fmt.num(v), `${Math.round(100 * risky / Math.max(1, rows.length))}% of the portfolio`],
    ['Completed with an outcome', done, v => fmt.num(v), `${rows.length - done} still ongoing`],
  ];
  ov.innerHTML = kp.map(([k, , , sub], i) => `<div class="kpi" style="--d:${i * 90}ms"><dt>${k}</dt><dd data-i="${i}"></dd><small>${sub}</small></div>`).join('');
  fx.whenVisible(ov, () => kp.forEach(([, v, f], i) => fx.countUp(ov.querySelector(`dd[data-i="${i}"]`), v ?? 0, f, 1200)));
  S.bandCounts = counts;
  fx.whenVisible($('#donut'), () => renderDonut());
  $('#donut-legend').innerHTML = counts.map(c => `<li><button type="button" data-band="${esc(c.key)}" aria-pressed="false"><i style="--c:${c.color}"></i>${esc(c.label)}<b>${c.value}</b></button></li>`).join('');
  $$('#donut-legend button').forEach(b => b.addEventListener('click', () => toggleBand(b.dataset.band)));
  fx.whenVisible($('#riskmap'), () => renderRiskMap());
}

function renderDonut() {
  const risky = S.bandCounts.filter(c => ['At risk', 'Critical'].includes(c.key)).reduce((t, c) => t + c.value, 0);
  const active = S.band;
  const sel = active ? S.bandCounts.find(c => c.key === active) : null;
  C.donut($('#donut'), S.bandCounts, { center: String(sel ? sel.value : risky), sub: sel ? sel.label.toLowerCase() : 'at risk or critical', active });
  $$('#donut [data-band]').forEach(el => el.addEventListener('click', () => toggleBand(el.dataset.band)));
  $$('#donut-legend button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.band === active)));
}

function toggleBand(name) {
  S.band = S.band === name ? null : name;
  C.animate(false); renderDonut(); C.animate(true);
  renderPortfolio();
}

function renderRiskMap() {
  $('#riskmap').classList.remove('skeleton');
  C.riskMap($('#riskmap'), S.portfolio.dataset, S.schema.risk_bands, { isDim: r => !matches(r), selected: S.sourceId });
  $$('#riskmap .pt').forEach(c => c.addEventListener('click', () => loadProject(c.dataset.id)));
  S.mapDrawn = true;
}

function markRiskMap() {
  if (!S.mapDrawn) return;
  $$('#riskmap .pt').forEach(c => {
    const r = S.byId[c.dataset.id];
    c.classList.toggle('dim', !matches(r));
    c.classList.toggle('sel', c.dataset.id === S.sourceId);
  });
}

function renderPortfolio() {
  const rows = S.portfolio.dataset.filter(matches);
  const max = 120;
  $('#band-filter').hidden = !S.band;
  if (S.band) {
    $('#band-filter').innerHTML = `<span class="chip" style="--c:${bandColor(S.band)}">${esc(S.band)}</span><button type="button" aria-label="Clear the band filter">${fx.CLOSE}</button>`;
    $('#band-filter button').addEventListener('click', () => toggleBand(S.band));
  }
  const tb = $('#portfolio-table tbody');
  tb.innerHTML = rows.map((r, i) => `<tr data-id="${r.project_id}" tabindex="0" style="--d:${Math.min(500, i * 14)}ms">
    <td class="proj"><b>${esc(r.project_id)}${r.hypothetical ? '<span class="tag">hypothetical</span>' : ''}</b><small>${esc(r.project_type)}, ${esc(r.contract_value)}</small></td>
    <td>${esc(r.province)}</td><td>${esc(r.status)}</td><td>${r.gate === 'G50' ? '50%' : '25%'}</td><td class="n">${fmt.num(r.spi, 2)}</td>
    <td><div class="barcell" style="--c:${r.band?.color}"><span>${fmt.pct(r.predicted_time_overrun_pct)}</span><i style="width:${Math.max(0, Math.min(max, r.predicted_time_overrun_pct || 0)) / max * 140}px"></i><span class="chip" style="--c:${r.band?.color}">${esc(r.band?.name)}</span></div></td>
    <td class="n">${r.status === 'Completed' ? fmt.pct(r.actual_time_overrun_pct) : '<span class="muted">open</span>'}</td></tr>`).join('')
    || '<tr><td colspan="7" class="muted">No project matches these filters.</td></tr>';
  tb.classList.remove('rows-in'); void tb.offsetWidth; tb.classList.add('rows-in');
  $$('#portfolio-table tbody tr[data-id]').forEach(tr => {
    tr.addEventListener('click', () => loadProject(tr.dataset.id));
    tr.addEventListener('keydown', e => { if (e.key === 'Enter') loadProject(tr.dataset.id); });
    tr.addEventListener('mouseenter', () => { const c = $(`#riskmap .pt[data-id="${tr.dataset.id}"]`); c?.classList.add('hl'); });
    tr.addEventListener('mouseleave', () => { $$('#riskmap .pt.hl').forEach(c => c.classList.remove('hl')); });
  });
  markRiskMap();
  const hyp = S.portfolio.dataset.filter(r => r.hypothetical).length;
  $('#portfolio-note').textContent = `${rows.length} of ${S.portfolio.dataset.length} projects shown. ${hyp} records are hypothetical scenarios and are labelled. For ongoing projects the "actual" completion is still a forecast.`;
}

async function loadProject(id) {
  try {
    const d = await api(`/benchmark/${encodeURIComponent(id)}`);
    fillForm(d.inputs); S.sourceId = id; S.presetName = id; $('#save-name').dataset.auto = '1';
    setGate(d.inputs.spi_50 != null ? 'G50' : 'G25');
    $('#source-note').textContent = `Loaded benchmark record ${id} as a worked example. Editing any answer scores it as a new project.`;
    showTab('assess');
    await runForecast({ base: true });
  } catch (e) { report(e); }
}

function loadPreset(p) {
  fillForm(p.inputs); setGate(p.gate); S.sourceId = null; S.presetName = p.name; $('#save-name').dataset.auto = '1';
  $('#source-note').textContent = `Example: ${p.name}. ${p.summary} Illustrative inputs, not a dataset record.`;
}

// ================================================================== live site link
let channel;

async function loadLiveList(selectId = S.livePid) {
  try {
    const list = await api('/live');
    S.liveList = list;
    $('#live-select').innerHTML = '<option value="">a monitored project</option>' +
      list.map(p => `<option value="${p.id}">${esc(p.name)} (${p.updates} update${p.updates === 1 ? '' : 's'})</option>`).join('');
    if (selectId) $('#live-select').value = String(selectId);
    return list;
  } catch (e) { if (e?.network) noteFailure(); return []; }
}

async function startLive() {
  if (!S.project) { toast('Open a project first, then start its site link.'); return; }
  if (!S.prediction) { toast('Run a forecast first, then start monitoring it.'); return; }
  try {
    let p;
    try { p = await post('/live', { name: S.project.name, inputs: S.inputs, gate: S.prediction.gate, location: currentLocation() }); }
    catch (e) { if (e.status === 409) { await followLive(S.project.live_id || (await api(`/projects/${S.project.id}`)).live_id); return; } throw e; }
    S.project.live_id = p.id;
    await loadLiveList(p.id);
    await followLive(p.id);
    loadProjects();
    toast(`Monitoring "${p.name}". Scan the code with a phone to send a site update.`, 'live');
  } catch (e) { report(e); }
}

function chosenBase(urls) {
  const bases = urls.map(u => u.replace(/\/site\/[A-Za-z0-9_-]+$/, ''));
  const saved = localStorage.getItem('revive-base');
  return { bases, base: bases.includes(saved) ? saved : bases[0] };
}

function renderLinkCard() {
  const p = S.live, pid = p.id;
  const { bases, base } = chosenBase(p.site_urls || [p.site_url]);
  const url = `${base}${p.site_path}`;
  $('#live-link').hidden = false;
  $('#live-rotate').hidden = false;
  $('#live-qr').innerHTML = `<img src="/api/live/${pid}/qr.svg?base=${encodeURIComponent(base)}&v=${encodeURIComponent(p.site_path.slice(-6))}" alt="QR code linking to the site update page for ${esc(p.name)}">`;
  $('#live-url').href = url;
  $('#live-url').textContent = url;
  $('#live-open').href = p.site_path;
  $('#live-base-wrap').hidden = bases.length < 2;
  $('#live-base').innerHTML = bases.map(b => `<option${b === base ? ' selected' : ''}>${esc(b)}</option>`).join('');
}

async function rotateLink() {
  if (!S.project || !confirm('Revoke the current phone link? Phones using it stop working until they scan the new QR code.')) return;
  try {
    await post(`/projects/${S.project.id}/site-link`, {});
    await followLive(S.livePid);
    toast('New phone link issued. The old one no longer works.', 'ok');
  } catch (e) { report(e); }
}

async function followLive(pid, { apply = false } = {}) {
  if (!pid) {
    S.livePid = null; S.live = null; channel.follow(null);
    try { localStorage.removeItem('revive-follow'); } catch { /* private mode */ }
    $('#live-link').hidden = true; $('#live-board').hidden = true; $('#live-rotate').hidden = true;
    $('#live-start').hidden = false;
    renderFeed(); renderTrajectory(); renderPill();
    return;
  }
  const p = await api(`/live/${pid}`);
  S.live = p; S.livePid = Number(pid);
  try { localStorage.setItem('revive-follow', String(pid)); } catch { /* private mode */ }
  $('#live-select').value = String(pid);
  $('#live-start').hidden = true;
  channel.follow(pid, Math.max(0, ...p.updates.map(u => u.id)));
  p.updates.forEach(u => channel.markSeen(u.id));
  S.devices = p.site_devices || 0;
  S.presenceAt = S.devices ? Date.now() : 0;
  renderLinkCard(); renderFeed(); renderTrajectory(); renderBoard(); renderPresence(); renderPill();
  onLiveStatus(channel.status);
  if (p.location) { setLocation(p.location); S.wxPinned = true; loadWeather(); }
  if (apply && p.latest) await applyLatest(p.latest, p.name, p.updates.at(-1));
}

/** Put a monitored project's latest scored state on the dashboard. */
async function applyLatest(latest, name, upd) {
  ++S.seq;
  fillForm(latest.inputs); setGate(latest.prediction.gate);
  S.prevPrediction = S.prediction;
  Object.assign(S, { inputs: latest.inputs, baseInputs: { ...latest.inputs }, prediction: latest.prediction,
    elapsedPct: upd?.summary?.elapsed_pct ?? null, sourceId: null, presetName: name });
  $('#save-name').dataset.auto = '1';
  $('#source-note').textContent = upd ? `Live: latest update from ${upd.reporter} on "${name}".` : `Live project "${name}".`;
  renderResult();
  await runRecovery();
}

async function onLiveUpdate(msg) {
  if (!S.livePid) {
    if (msg.project_ref && msg.project_ref === S.project?.id) await followLive(msg.project_id);
    else { loadProjects(); toast(`${msg.update.reporter} sent an update on "${msg.project_name}".`, 'live', { action: { label: 'Open it', run: () => msg.project_ref && openProject(msg.project_ref, { tab: 'live' }) } }); return; }
  } else if (msg.project_id !== S.livePid) {
    loadLiveList(); loadProjects();
    toast(`${msg.update.reporter} sent an update on "${msg.project_name}" (${msg.update.summary.band.name}, ${fmt.pct(msg.update.summary.time_overrun_pct)}).`, 'live',
      { action: { label: 'Open it', run: () => msg.project_ref && openProject(msg.project_ref, { tab: 'live' }) } });
    return;
  }
  if (!S.live.updates.some(u => u.id === msg.update.id)) S.live.updates.push(msg.update);
  S.live.updates.sort((a, b) => a.id - b.id);
  renderFeed(true); renderTrajectory(); renderBoard(true);
  await applyLatest({ inputs: msg.inputs, prediction: msg.prediction }, msg.project_name, msg.update);
  const st = $('#stage'); st.classList.remove('flash'); void st.offsetWidth; st.classList.add('flash');
  fx.pulse($('#live-pill'), 'ping'); fx.pulse($('#result'), 'flash-soft');
  const s = msg.update.summary;
  toast(`${msg.update.reporter}: forecast now ${fmt.pct(s.time_overrun_pct)}${s.delta_pts != null ? ` (${s.delta_pts > 0 ? '+' : ''}${s.delta_pts} pts)` : ''}, ${s.band.name}.`, 'live',
    { action: { label: 'Show', run: () => showTab('live') } });
  loadLiveList(); loadProjects(); refreshDelay();
}

function onPresence(info) {
  if (info.project_id !== S.livePid) return;
  S.devices = info.devices; S.presenceAt = Date.now();
  if (info.first) toast(`${info.device} opened the site update page.`, 'live', { ms: 4000 });
  renderPresence(); renderPill();
}

function onLiveStatus(s) {
  const label = { live: 'Live', connecting: 'Connecting', reconnecting: 'Connection lost, reconnecting' }[s] || s;
  $('#live-dot').classList.toggle('on', s === 'live');
  $('#live-status').textContent = s === 'live' && S.live ? `Live: listening for site updates on "${S.live.name}"` : label;
  renderPill();
}

function renderPresence() {
  const fresh = S.devices > 0 && Date.now() - S.presenceAt < 50000;
  const el = $('#live-presence');
  el.classList.toggle('on', fresh);
  $('#live-presence-text').textContent = fresh
    ? `${S.devices} site phone${S.devices === 1 ? '' : 's'} connected, last seen ${fx.ago(new Date(S.presenceAt).toISOString())}`
    : 'No site phone connected yet: scan the code';
}

function renderPill() {
  const pill = $('#live-pill');
  pill.hidden = !S.livePid || !S.live;
  if (pill.hidden) return;
  const fresh = S.devices > 0 && Date.now() - S.presenceAt < 50000;
  pill.querySelector('.dot').classList.toggle('on', channel.status === 'live');
  $('#live-pill-text').textContent = `Live: ${S.live.name}${fresh ? `, ${S.devices} phone${S.devices === 1 ? '' : 's'}` : ''}`;
}

function renderBoard(fresh = false) {
  const ups = S.live?.updates || [];
  $('#live-board').hidden = !ups.length;
  if (!ups.length) return;
  const last = ups.at(-1).summary, prev = ups.length > 1 ? ups.at(-2).summary : null;
  $('#lb-name').textContent = S.live.name;
  const cells = [
    ['#lb-fc', '#sp-fc', ups.map(u => u.summary.time_overrun_pct), v => fmt.pct(v, 1), last.band.color, 'up'],
    ['#lb-hs', '#sp-hs', ups.map(u => u.summary.health), v => fmt.num(v, 0), '#6CB2FF', 'down'],
    ['#lb-spi', '#sp-spi', ups.map(u => u.summary.spi), v => fmt.num(v, 2), '#B4BCC6', 'down'],
    ['#lb-pot', '#sp-pot', ups.map(u => u.summary.p_on_time_after == null ? null : u.summary.p_on_time_after * 100), v => `${Math.round(v)}%`, '#FF4FA3', 'down'],
  ];
  cells.forEach(([dd, sp, vals, f, color]) => {
    const v = vals.at(-1), el = $(dd);
    if (v == null) el.textContent = '\u2014'; else fx.countUp(el, v, f, 900);
    C.sparkline($(sp), vals, { color, fmt: f });
    if (fresh) fx.pulse(el.parentElement, 'flash-soft');
  });
  const d = prev ? last.time_overrun_pct - prev.time_overrun_pct : null;
  $('#lb-fc').dataset.delta = d == null ? '' : `${d > 0 ? '\u25B2' : '\u25BC'} ${Math.abs(d).toFixed(1)}`;
  $('#lb-fc').classList.toggle('up', d > 0); $('#lb-fc').classList.toggle('down', d < 0);
  tickLabels();
}

function tickLabels() {
  const ups = S.live?.updates || [];
  if (ups.length) $('#lb-last').textContent = `${ups.length} update${ups.length === 1 ? '' : 's'}, last ${fx.ago(ups.at(-1).created_at)} by ${ups.at(-1).reporter}`;
  $$('#live-feed [data-at]').forEach(el => { el.textContent = fx.ago(el.dataset.at); });
  if (S.livePid) { renderPresence(); renderPill(); }
}

function renderFeed(fresh = false) {
  const ups = [...(S.live?.updates || [])].reverse();
  $('#live-feed').innerHTML = ups.map((u, i) => {
    const s = u.summary, d = s.delta_pts;
    const move = d == null ? '' : `<small class="${d > 0 ? 'up' : 'down'}">${d > 0 ? '+' : ''}${d} pts${s.band_before && s.band_before !== s.band.name ? `, ${esc(s.band_before)} to ${esc(s.band.name)}` : ''}</small>`;
    return `<li class="${fresh && i === 0 ? 'fresh' : ''}"><div class="feed-head"><b>${esc(u.reporter)}</b><span data-at="${esc(u.created_at)}">${fx.ago(u.created_at)}</span><span>${Math.round(s.elapsed_pct)}% of contract time</span></div>
      <p>${esc(u.changes.join(', '))}</p>${u.note ? `<p class="muted">\u201c${esc(u.note)}\u201d</p>` : ''}
      <p class="res"><span class="chip" style="--c:${s.band.color}">${esc(s.band.name)}</span><strong>${fmt.pct(s.time_overrun_pct)}</strong>${move}
      ${s.p80_before_day != null ? `<small class="muted">P80 finish month ${fmt.mo(s.p80_before_day)}, month ${fmt.mo(s.p80_after_day)} with the recovery plan</small>` : ''}</p></li>`;
  }).join('') || '<li class="muted">No monitored project yet. Run a forecast, then start monitoring.</li>';
}

function trajectoryPoints() {
  return (S.live?.updates || []).map(u => ({ x: u.summary.elapsed_pct, y: u.summary.time_overrun_pct,
    lo: u.summary.interval[0], hi: u.summary.interval[1], color: u.summary.band.color, label: `${u.reporter}, ${u.created_at.replace('T', ' ')}` }));
}

function renderTrajectory() {
  stopReplay();
  const pts = trajectoryPoints(), n = pts.length;
  C.trajectory($('#trajectory'), pts, S.schema.risk_bands);
  $('#replay').hidden = n < 2;
  $('#replay-card').hidden = true;
  const r = $('#replay-step');
  r.max = String(Math.max(0, n - 1)); r.value = r.max;
  $('#replay-label').textContent = n ? `Update ${n - 1} of ${n - 1}` : '';
  renderEarlyWarning();
}

// ---- Replay (from the REVIVE web app): step through the site updates and watch the forecast and the warning appear
let replayTimer = null;
function showReplayStep(i) {
  const ups = S.live?.updates || [], u = ups[i];
  if (!u) return;
  C.animate(false);
  C.trajectory($('#trajectory'), trajectoryPoints().slice(0, i + 1), S.schema.risk_bands);
  C.animate(true);
  $('#replay-step').value = String(i);
  $('#replay-label').textContent = i ? `Update ${i} of ${ups.length - 1}` : 'Monitoring start';
  const s = u.summary, first = ups.findIndex(x => ['At risk', 'Critical'].includes(x.summary?.band?.name));
  const card = $('#replay-card');
  card.hidden = false;
  card.innerHTML = `<div class="rc-head"><span class="chip" style="--c:${s.band.color}">${esc(s.band.name)}</span>
      <b>${fmt.pct(s.time_overrun_pct)}</b><span class="muted">${esc(u.created_at.slice(0, 10))} \u00b7 ${Math.round(s.elapsed_pct)}% of contract time \u00b7 ${esc(u.reporter)}</span></div>
    <p>${(Array.isArray(u.changes) ? u.changes : []).map(esc).join('; ') || 'No change reported'}</p>
    ${u.note ? `<p class="muted">\u201c${esc(u.note)}\u201d</p>` : ''}
    ${i === first ? '<p class="rc-warn">REVIVE raised the warning here.</p>' : ''}`;
}
function stopReplay() { clearInterval(replayTimer); replayTimer = null; const b = $('#replay-play'); if (b) b.textContent = 'Replay'; }
function toggleReplay() {
  if (replayTimer) { stopReplay(); return; }
  const n = (S.live?.updates || []).length;
  if (n < 2) return;
  let i = 0;
  $('#replay-play').textContent = 'Pause';
  showReplayStep(i);
  replayTimer = setInterval(() => { i += 1; if (i >= n) { stopReplay(); renderEarlyWarning(); return; } showReplayStep(i); }, fx.REDUCED ? 400 : 1100);
}

/** The first update whose forecast reached At risk or Critical, and how much contract time was left then. */
function renderEarlyWarning() {
  const el = $('#early-warn'), ups = S.live?.updates || [];
  const first = ups.find(u => ['At risk', 'Critical'].includes(u.summary?.band?.name));
  el.hidden = !first;
  if (!first) return;
  const months = Number(S.project?.details?.planned_months || S.project?.inputs?.planned_months || 0);
  const left = Math.max(0, 100 - first.summary.elapsed_pct);
  const days = months ? Math.round(left / 100 * months * C.DPM) : null;
  el.innerHTML = `<b>Early warning:</b> REVIVE first flagged this project as <b>${esc(first.summary.band.name)}</b> on ${esc(first.created_at.slice(0, 10))}, at ${Math.round(first.summary.elapsed_pct)}% of contract time${days != null ? `, <b>${days} days before the contract completion date</b>` : ''}.`;
}

async function copyLink() {
  const url = $('#live-url').textContent;
  try { await navigator.clipboard.writeText(url); toast('Link copied. Send it to the site engineer\u2019s phone.', 'ok'); }
  catch {
    const t = document.createElement('textarea'); t.value = url; document.body.appendChild(t); t.select();
    try { document.execCommand('copy'); toast('Link copied.', 'ok'); } catch { toast(url); }
    t.remove();
  }
}

// ================================================================== BIM connection and live weather
async function bimAction(path, msg) {
  if (!S.project) { toast('Open a project first: the model and schedule belong to a project.'); return; }
  try {
    await post(path, {});
    await afterFilesChanged();
    toast(msg, 'ok');
  } catch (e) { report(e); }
}

async function initWeather() {
  try {
    S.places = await api('/weather/places');
    $('#wx-loc').innerHTML = S.places.places.map(p => `<option>${esc(p.name)}</option>`).join('');
  } catch (e) { if (e?.network) throw e; /* weather is optional */ }
}

function currentLocation() {
  const p = S.places?.places.find(x => x.name === $('#wx-loc').value);
  return p ? { name: p.name, lat: p.lat, lon: p.lon } : null;
}

function setLocation(loc) {
  if (!loc || !S.places) return;
  if (!S.places.places.some(p => p.name === loc.name)) {
    S.places.places.push(loc);
    $('#wx-loc').insertAdjacentHTML('beforeend', `<option>${esc(loc.name)}</option>`);
  }
  $('#wx-loc').value = loc.name;
}

function syncWeatherToProvince() {
  if (!S.places) return;
  const city = S.places.province_default[S.inputs?.province];
  if (!S.wxPinned && city && city !== $('#wx-loc').value) { $('#wx-loc').value = city; loadWeather(); }
  else if (!S.weather) loadWeather();
}

async function loadWeather() {
  const loc = currentLocation();
  if (!loc) return;
  $('#wx-note').textContent = `Fetching live weather for ${loc.name}`;
  $('#wx-strip').classList.add('skeleton');
  try {
    S.weather = await api(`/weather?lat=${loc.lat}&lon=${loc.lon}&name=${encodeURIComponent(loc.name)}`);
  } catch (e) { S.weather = { available: false, reason: e.network ? 'The server is not reachable.' : e.message }; }
  $('#wx-strip').classList.remove('skeleton');
  renderWeather();
  if ($('#wx-apply').checked && S.prediction) runRecovery();
}

function renderWeather() {
  const w = S.weather;
  $('#wx-apply').disabled = !w?.available;
  if (!w?.available) {
    $('#wx-strip').innerHTML = '';
    $('#wx-note').textContent = w?.reason || 'Live weather unavailable.';
    return;
  }
  C.weatherStrip($('#wx-strip'), w);
  const r = w.rules;
  $('#wx-note').textContent = `${w.location.name}: ${w.lost_past} likely lost days in the last ${w.past.length}, ${w.lost_forecast} in the ${w.forecast.length}-day forecast. A day counts as lost at ${r.rain_mm} mm of rain, ${r.wind_kmh} km/h wind, ${r.heat_c} \u00b0C heat or ${r.cold_c} \u00b0C frost risk. Source: ${w.source}.`;
}

// ================================================================== evidence
function renderEvidence() {
  const card = S.card, g = card.gates;
  const lc = v => v.leave_company_out || null, f2 = x => (x == null ? '\u2014' : x.toFixed(2));
  $('#metrics').innerHTML = `<thead><tr><th>Checkpoint</th><th class="n">Time error</th><th class="n">Guessing the median</th><th class="n">R\u00b2</th><th class="n">R\u00b2, unseen company</th><th class="n">High-risk AUC</th><th class="n">AUC, unseen company</th><th class="n">Cost R\u00b2</th></tr></thead><tbody>` +
    Object.entries(g).map(([k, v]) => `<tr><td>${k === 'G50' ? 'At 50%' : 'At 25%'}</td><td class="n">${v.time_overrun.mae.mean.toFixed(1)} pts</td><td class="n">${v.time_overrun.baseline_median_mae.toFixed(1)} pts</td>
      <td class="n">${v.time_overrun.r2.mean.toFixed(2)}</td><td class="n">${f2(lc(v)?.time_overrun?.r2)}</td><td class="n">${v.high_risk.auc.mean.toFixed(2)}</td><td class="n">${f2(lc(v)?.high_risk_auc)}</td><td class="n">${v.cost_overrun.r2.mean.toFixed(2)}</td></tr>`).join('') + '</tbody>';
  $('#validation-note').textContent = `${card.validation} Trained ${card.trained_at.slice(0, 10)} on ${card.dataset.n_projects} real completed projects from ${(card.dataset.companies || []).length || 'several'} data sources, ${card.model === 'linear' ? 'with a sign-constrained linear model' : 'with XGBoost'} on ${card.feature_set === 'core' ? 'the core questions' : 'every answer'}. High risk means a time overrun above ${card.high_risk_threshold_pct}%.`;
  if (card.model_comparison) {
    $('#comparison').innerHTML = '<thead><tr><th>Checkpoint</th><th>Model</th><th class="n">Time error</th><th class="n">R\u00b2</th><th class="n">R\u00b2, unseen company</th><th class="n">AUC</th><th class="n">AUC, unseen company</th></tr></thead><tbody>' +
      card.model_comparison.map(m => `<tr${/production/.test(m.model) ? ' class="prod"' : ''}><td>${m.gate === 'G50' ? '50%' : '25%'}</td><td>${esc(m.model)}</td><td class="n">${m.time_MAE.toFixed(1)}</td><td class="n">${f2(m.time_R2)}</td><td class="n">${f2(m.loco_time_R2)}</td><td class="n">${f2(m.risk_AUC)}</td><td class="n">${f2(m.loco_risk_AUC)}</td></tr>`).join('') + '</tbody>';
  }
  if (card.sensitivity) {
    $('#sensitivity').innerHTML = '<thead><tr><th>Data used</th><th>At</th><th class="n">n</th><th class="n">Time error</th><th class="n">Median guess</th><th class="n">R\u00b2</th><th class="n">R\u00b2, unseen company</th><th class="n">AUC</th></tr></thead><tbody>' +
      card.sensitivity.map(s => `<tr><td>${esc(s.scope)}</td><td>${s.gate === 'G50' ? '50%' : '25%'}</td><td class="n">${s.n}</td><td class="n">${s.time_MAE.toFixed(1)}</td><td class="n">${s.baseline_MAE.toFixed(1)}</td><td class="n">${s.time_R2.toFixed(2)}</td><td class="n">${f2(s.loco_time_R2)}</td><td class="n">${f2(s.risk_AUC)}</td></tr>`).join('') + '</tbody>';
  }
  $('#excluded').innerHTML = Object.entries(card.excluded_for_leakage).map(([k, v]) => `<li><b>${esc(k)}</b>: ${esc(v)}</li>`).join('');
  const n = card.dataset.n_projects, G = card.gates, spiOnly = G.G25?.leave_company_out?.spi_only_linear?.r2;
  $('#limits').innerHTML = [
    `The model is trained on ${n} real completed projects from three contractors and a few external records: a pilot study, not a model for the whole industry. Hypothetical scenarios and ongoing projects are kept out of training and labelled wherever they appear.`,
    `For a company it has never seen, the time forecast explains about ${Math.round((G.G25?.leave_company_out?.time_overrun?.r2 ?? 0) * 100)}% of the variation at 25% and ${Math.round((G.G50?.leave_company_out?.time_overrun?.r2 ?? 0) * 100)}% at 50%. SPI alone transfers about as well${spiOnly != null ? ` (${spiOnly.toFixed(2)} at 25%)` : ''}: the other questions mainly give the forecast its reasons.`,
    `The cost forecast at 25% is barely better than the average (R\u00b2 ${G.G25?.cost_overrun?.r2?.mean?.toFixed(2)}); treat it as indicative. At 50% it is usable (R\u00b2 ${G.G50?.cost_overrun?.r2?.mean?.toFixed(2)}).`,
    'Contract and site information alone does not predict overrun in this data; the signal appears once first-quarter events and earned value are known. REVIVE therefore forecasts at 25% and 50% of contract time, not at award.',
    'SPI dominates the explanation. If SPI values were back-calculated from the final delay, performance is optimistic; the robustness table shows results without SPI and CPI.',
    'The recovery and digital twin use one linked case-study schedule. Crash rates, liquidated damages and carbon factors are inputs to verify for each real project.',
    'Performance is cross-validated. The next step is an external test on newly collected projects: python -m revive evaluate --file new.xlsx',
  ].map(t => `<li>${esc(t)}</li>`).join('');
  $$('[data-evgate]').forEach(el => {
    el.innerHTML = Object.keys(g).map(k => `<button type="button" data-g="${k}" aria-pressed="${k === S.evGate}">${k === 'G50' ? '50%' : '25%'}</button>`).join('');
    el.querySelectorAll('button').forEach(b => b.addEventListener('click', () => { S.evGate = b.dataset.g; renderEvidence(); renderInsightCharts(); }));
  });
}

function renderInsightCharts() {
  const ins = S.insights;
  if (!ins) return;
  if (ins.oof) fx.whenVisible($('#scatter'), () => C.scatter($('#scatter'), ins.oof[S.evGate]));
  if (ins.drivers) fx.whenVisible($('#beeswarm'), () => C.beeswarm($('#beeswarm'), ins.drivers[S.evGate].beeswarm));
  const famColor = { Client: '#6CB2FF', Contractor: '#E9C46A', 'Design & supervision': '#43C59E', External: '#F28C38' };
  fx.whenVisible($('#rii'), () => C.hbars($('#rii'), ins.rii, { max: 1, label: r => `${r.rank}. ${r.label}`, value: r => r.rii, color: r => famColor[r.family], text: r => r.rii.toFixed(2) }));
  const comp = ins.composition, fixed = { 'Hypothetical scenarios': '#FF4FA3', 'External sources': '#B4BCC6', Unlabelled: '#5C6673' }, spare = ['#6CB2FF', '#43C59E', '#E9C46A', '#F28C38'];
  const palette = comp.by_source.map((s, i) => fixed[s.label] || spare[i % spare.length]);
  const total = comp.by_source.reduce((s, x) => s + x.n, 0);
  $('#composition').innerHTML = `<div class="stack">${comp.by_source.map((s, i) => `<i style="width:${(100 * s.n / total).toFixed(2)}%;background:${palette[i]};--d:${i * 120}ms" data-tip="${esc(s.label)}: ${s.n} records"></i>`).join('')}</div>
    <ul class="stack-legend">${comp.by_source.map((s, i) => `<li><i style="--c:${palette[i]}"></i>${esc(s.label)}: ${s.n}</li>`).join('')}</ul>
    <p class="fine">${comp.n_with_outcome} records have a completion date. Median time overrun ${comp.median_time_overrun_pct}%, median cost overrun ${comp.median_cost_overrun_pct}%. ${Math.round(comp.share_over_10pct * 100)}% of projects overran by more than 10%, which is why REVIVE forecasts the size of the overrun rather than a yes/no delay label.</p>`;
}

// ================================================================== connection UI
function showConnState(state) {
  $('#conn').dataset.state = state;
  if (state === 'offline') {
    $('#status').textContent = 'Server not reachable';
    if (S.booted) { $('#conn-banner').hidden = false; S.wasOffline = true; }
  } else if (state === 'online') {
    $('#conn-banner').hidden = true;
    if (S.card) $('#status').textContent = 'Connected';
    if (S.booted && S.wasOffline) {
      S.wasOffline = false;
      toast('Reconnected to the REVIVE server.', 'ok');
      resync();
    }
  }
}

/** After the server comes back: pick up anything that happened while it was away. */
async function resync() {
  try {
    await loadLiveList();
    if (S.livePid) await followLive(S.livePid);
    channel.catchUp();
    if (S.prediction && !S.recovery) await runRecovery();
    if (!S.portfolio) await loadPortfolio();
    await loadProjects();
  } catch (e) { report(e); }
}

// ================================================================== tabs (hash routing: #delay, #assess, ...)
const TABS = ['projects', 'delay', 'assess', 'live', 'twin', 'recover', 'impact', 'portfolio', 'evidence'];
const TAB_HINT = { projects: 'Every project and where it stands', delay: 'How late the project is today', assess: 'Where it is heading, and why',
  live: 'Phone updates from site', twin: 'The forecast on the building', recover: 'The cheapest way back', impact: 'Time, cost and carbon',
  portfolio: 'The survey projects', evidence: 'How far the numbers can be trusted' };

/** Previous and next sheet at the foot of each sheet: the workflow reads in order without the rail. */
function sheetNav() {
  const name = id => $(`#tab-${id} span`)?.textContent || id;
  TABS.forEach((id, i) => {
    const sec = $(`#${id}`); if (!sec || sec.querySelector('.sheet-nav')) return;
    const prev = TABS[i - 1], next = TABS[i + 1];
    const link = (t, dir) => `<a class="sn-${dir}" href="#${t}"><small>${dir === 'next' ? 'Next' : 'Back'}</small><b>${esc(name(t))}</b><span>${esc(TAB_HINT[t])}</span></a>`;
    sec.insertAdjacentHTML('beforeend', `<nav class="sheet-nav" aria-label="Sheets">${prev ? link(prev, 'prev') : '<span></span>'}${next ? link(next, 'next') : ''}</nav>`);
  });
}
const NEEDS_PROJECT = new Set(['delay', 'live']);

function showTab(id, { push = true } = {}) {
  if (!TABS.includes(id)) id = 'projects';
  const dir = Math.sign(TABS.indexOf(id) - TABS.indexOf(S.tab)), changed = S.tab !== id || !S.tabShown;
  S.tab = id; S.tabShown = true;
  $$('.tabpanel').forEach(sec => { sec.hidden = sec.id !== id; });
  $$('#tabs a').forEach(a => { const on = a.dataset.tab === id; a.setAttribute('aria-selected', String(on)); a.tabIndex = on ? 0 : -1; });
  moveTabInd();
  const panel = $(`#${id}`);
  if (changed) {               // the sheet arrives from the side its tab sits on; blocks that reveal on scroll keep their own entrance
    enter(panel, dir, { items: [...panel.children].filter(k => !k.hidden && !k.classList.contains('reveal')) });
    playTabMotion(id);
  }
  if (push && location.hash !== `#${id}`) history.replaceState(null, '', `#${id}`);
  scrollTo({ top: 0, behavior: 'instant' in document.documentElement.style ? 'instant' : 'auto' });
  if (id === 'delay') refreshDelay();
  if (id === 'projects') loadProjects();
  if (NEEDS_PROJECT.has(id) && !S.project) renderNoProject(id);
  fx.reveal(panel);
}

/** Replay the sheet-tab motion: the active icon redraws, the indicator bar bumps and the REVIVE mark turns. */
function playTabMotion(id) {
  if (fx.REDUCED) return;
  const restart = (el, cls) => { if (!el) return; el.classList.remove(cls); void el.getBoundingClientRect(); el.classList.add(cls); };
  $$('#tabs a.go').forEach(a => a.classList.remove('go'));
  restart($(`#tabs a[data-tab="${id}"]`), 'go');
  restart($('#tab-ind'), 'bump');
  restart($('.tabs-mark .rv'), 'rv-go');
}

/** The tab bar: a ghost plate follows the pointer, arrow keys walk the tabs (Enter or Space opens one,
 *  so arrowing past a sheet never fetches it), and the lamp under the selected tab fills as the sheet scrolls. */
function wireTabBar() {
  const nav = $('#tabs'), ghost = $('#tab-hover'), tabs = () => $$('#tabs a[role=tab]');
  nav.addEventListener('pointerover', e => {
    const a = e.target.closest('a[role=tab]');
    if (!a || a.getAttribute('aria-selected') === 'true') { to(ghost, { opacity: 0 }, { duration: 0.15 }); return; }
    const first = ghost.style.opacity !== '1';
    plate(ghost, a, { instant: first });
    if (first) to(ghost, { opacity: [0, 1] }, { duration: 0.18 });
  });
  nav.addEventListener('pointerleave', () => to(ghost, { opacity: 0 }, { duration: 0.2 }));
  roving(nav, tabs);
  nav.addEventListener('keydown', e => { if (e.key === ' ' && e.target.matches('a[role=tab]')) { e.preventDefault(); e.target.click(); } });
  globalThis.Motion?.scroll(p => $('#tab-ind').style.setProperty('--read', p.toFixed(3)));
}

function moveTabInd({ instant = false } = {}) {
  const a = $('#tabs a[aria-selected="true"]');
  if (!a) return;
  plate($('#tab-ind'), a, { instant });
  a.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
}

// a frame with one bay still to build: the empty state's drawing (decorative)
const EMPTY_ART = `<svg class="es-art" viewBox="0 0 120 72" aria-hidden="true"><path class="g" d="M4 66h112"/><path d="M20 66V18M50 66V18M80 66V42M20 42h60M20 18h30"/><path class="todo" d="M80 42V18M50 18h30M80 18h20M100 18v48M80 42h20"/><path class="arc" d="M60 14c4-8 12-11 22-11"/><path class="arc" d="M78 0l4 3-3.5 4"/></svg>`;

function renderNoProject(id) {
  if (id === 'delay') {
    $('#delay-body').hidden = true;
    $('#delay-empty').hidden = false;
    $('#delay-empty').innerHTML = `${EMPTY_ART}<h3>Open a project to see its current delay</h3><p class="muted">The current delay is measured from a project's baseline schedule and its site reports.</p>
      <ol class="es-steps"><li><b>Choose or create a project</b><span>or load the labelled sample</span></li><li><b>Add the baseline</b><span>P6 .xer, MS Project or CSV</span></li><li><b>Send a site update</b><span>from the phone link on Live site</span></li></ol>
      <div class="actions"><a class="btn primary" href="#projects">Choose a project</a><button type="button" class="btn ghost" data-act="new">New project</button></div>`;
    $('#delay-empty [data-act=new]').addEventListener('click', openProjectModal);
  }
}

function setTitleblocks() {
  $$('.tb-proj').forEach(el => { el.textContent = S.project ? S.project.name : 'Quick assessment'; });
  $$('.pack-link').forEach(a => { a.hidden = !S.project; if (S.project) a.href = `/evidence/${S.project.id}`; });
}

// ================================================================== workspace (company projects)
async function loadProjects() {
  try {
    S.projects = await api('/projects');
    renderCards(); renderSwitcher(); renderWsKpis();
    if (S.project) {
      const fresh = S.projects.find(p => p.id === S.project.id);
      if (fresh) Object.assign(S.project, fresh);
    }
  } catch (e) { if (e?.status !== 401) report(e); }
}

function delayBand(p) { return p.delay?.available ? p.delay.delay_band : null; }

function renderWsKpis() {
  const ps = S.projects, live = ps.filter(p => p.live_id).length;
  const late = ps.filter(p => p.delay?.available && p.delay.delay_days > 0.5);
  const crit = ps.filter(p => ['Critical slip', 'Significant slip'].includes(delayBand(p)?.name)).length;
  const worst = late.reduce((m, p) => Math.max(m, p.delay.delay_days), 0);
  const items = [
    ['Projects', ps.length, v => fmt.num(v), `${live} on the live site link`],
    ['Behind programme now', late.length, v => fmt.num(v), `${crit} significantly or critically`],
    ['Largest delay to date', worst, v => `${fmt.num(v)} d`, 'days, from the latest site data'],
    ['Forecast at risk or critical', ps.filter(p => ['At risk', 'Critical'].includes(p.forecast?.band?.name)).length, v => fmt.num(v), 'machine-learning forecast'],
  ];
  const el = $('#ws-kpis');
  el.innerHTML = items.map(([k, , , sub], i) => `<div class="kpi" style="--d:${i * 70}ms"><dt>${k}</dt><dd data-i="${i}"></dd><small>${sub}</small></div>`).join('');
  items.forEach(([, v, f], i) => fx.countUp(el.querySelector(`dd[data-i="${i}"]`), v ?? 0, f, 900));
}

function cardMatches(p) {
  const q = S.wsQuery.toLowerCase();
  return !q || `${p.name} ${p.client || ''} ${p.location?.name || ''} ${p.code || ''}`.toLowerCase().includes(q);
}

function renderCards() {
  const host = $('#cards');
  let ps = S.projects.filter(cardMatches);
  if (S.wsSort === 'delay') ps = [...ps].sort((a, b) => (b.delay?.delay_days ?? -1) - (a.delay?.delay_days ?? -1));
  if (S.wsSort === 'name') ps = [...ps].sort((a, b) => a.name.localeCompare(b.name));
  const newCard = `<button type="button" class="card new" data-new><span class="plus" aria-hidden="true"></span><b>New project</b><small>Details, baseline schedule, optional BIM model</small></button>`;
  const sample = S.projects.length ? '' : `<button type="button" class="card new sample" data-sample><span class="plus alt" aria-hidden="true"></span><b>Load a sample project</b><small>A worked example with three site updates, so every sheet has data. Labelled as sample data.</small></button>`;
  host.innerHTML = ps.map((p, i) => {
    const db = delayBand(p), f = p.forecast, d = p.delay || {};
    const days = d.available ? d.delay_days : null;
    return `<article class="card proj-card${S.project?.id === p.id ? ' current' : ''}" style="--d:${Math.min(600, i * 60)}ms;--c:${db?.color || 'var(--chalk-3)'}" data-id="${p.id}" tabindex="0" data-tilt>
      <header data-z="20"><span class="code">${esc(p.code || `P-${String(p.id).padStart(3, '0')}`)}</span>${p.live_id ? '<span class="livetag"><i></i>Live</span>' : ''}</header>
      <h3 data-z="45">${esc(p.name)}</h3>
      <p class="meta" data-z="30">${esc([p.client, p.location?.name, p.details?.project_type].filter(Boolean).join(' \u00b7 ') || 'No details yet')}</p>
      <div class="cg" data-z="55">
        <div><small>Delay to date</small><b class="dd">${days == null ? '\u2014' : `${days > 0 ? '+' : ''}${fmt.num(days)} d`}</b>${db ? `<span class="chip" style="--c:${db.color}">${esc(db.name)}</span>` : '<span class="chip muted-chip">not measured</span>'}</div>
        <div><small>Forecast overrun</small><b>${f?.time_overrun_pct == null ? '\u2014' : fmt.pct(f.time_overrun_pct)}</b>${f?.band ? `<span class="chip" style="--c:${f.band.color}">${esc(f.band.name)}</span>` : '<span class="chip muted-chip">no forecast</span>'}</div>
      </div>
      <div class="spark chart" data-spark="${p.id}" data-z="35"></div>
      <footer data-z="15"><span>${d.status_date ? `Status ${esc(d.status_date)}` : 'No status yet'}</span><span>${p.schedule === 'uploaded' ? 'Own schedule' : 'Demo schedule'}${p.ifc_mode === 'file' ? ' \u00b7 IFC' : p.ifc_mode === 'demo' ? ' \u00b7 demo IFC' : ''}</span></footer>
      ${S.user?.role === 'admin' ? `<button type="button" class="card-x" data-del="${p.id}" aria-label="Delete ${esc(p.name)}">${fx.CLOSE}</button>` : ''}
    </article>`;
  }).join('') + newCard + sample;
  host.classList.remove('in'); void host.offsetWidth; host.classList.add('in');
  ps.forEach(p => {
    const h = p.delay?.history;
    if (h && h.length > 1) C.sparkline(host.querySelector(`[data-spark="${p.id}"]`), h, { color: p.delay.delay_band?.color || 'var(--chalk)', fmt: v => `${v.toFixed(0)} d` });
  });
  host.querySelectorAll('.proj-card').forEach(c => {
    const open = () => openProject(Number(c.dataset.id), { tab: 'delay' });
    c.addEventListener('click', e => { if (!e.target.closest('[data-del]')) open(); });
    c.addEventListener('keydown', e => { if (e.key === 'Enter') open(); });
    c.addEventListener('pointermove', e => {           // a light that follows the pointer across the card
      const r = c.getBoundingClientRect();
      c.style.setProperty('--mx', `${e.clientX - r.left}px`); c.style.setProperty('--my', `${e.clientY - r.top}px`);
    });
  });
  host.querySelectorAll('[data-del]').forEach(b => b.addEventListener('click', () => deleteProject(Number(b.dataset.del))));
  host.querySelector('[data-new]').addEventListener('click', openProjectModal);
  host.querySelector('[data-sample]')?.addEventListener('click', loadSampleProject);
}

function renderSwitcher() {
  const menu = $('#proj-menu');
  menu.innerHTML = `<a href="#projects" class="mi-all">All projects</a>` +
    S.projects.map(p => `<button type="button" role="option" data-id="${p.id}" aria-selected="${S.project?.id === p.id}"><i style="--c:${delayBand(p)?.color || 'var(--chalk-3)'}"></i>${esc(p.name)}${p.live_id ? '<em>live</em>' : ''}</button>`).join('') +
    `<button type="button" class="mi-new" data-new>+ New project</button>`;
  menu.querySelectorAll('[data-id]').forEach(b => b.addEventListener('click', () => { closeMenus(); openProject(Number(b.dataset.id)); }));
  menu.querySelector('[data-new]').addEventListener('click', () => { closeMenus(); openProjectModal(); });
  menu.querySelector('.mi-all').addEventListener('click', closeMenus);
  $('#proj-name').textContent = S.project ? S.project.name : (S.projects.length ? 'Choose a project' : 'No projects yet');
}

async function openProject(id, { tab = null } = {}) {
  try {
    const p = await api(`/projects/${id}`);
    S.project = p; setProject(p.id);
    try { localStorage.setItem('revive-project', String(p.id)); } catch { /* private mode */ }
    renderSwitcher(); setTitleblocks();
    $$('.proj-card').forEach(c => c.classList.toggle('current', Number(c.dataset.id) === p.id));
    // forecast form: the project's saved inputs, else what its details already tell us
    S.sourceId = null; S.presetName = p.name; $('#save-name').value = p.name; $('#save-name').dataset.auto = '1';
    if (p.location) { setLocation(p.location); S.wxPinned = true; }
    await refreshBimSummary();
    loadTwins();
    if (p.live_id) {
      // monitored: the dashboard shows the latest scored site update, not the starting assessment
      await followLive(p.live_id, { apply: true }).catch(report);
    } else if (p.inputs) {
      fillForm(p.inputs);
      setGate(p.gate || (p.inputs.spi_50 != null ? 'G50' : 'G25'));
      $('#source-note').textContent = `${p.name}: the latest saved answers. Edit them and press Save to project to keep a new assessment.`;
      runForecast({ base: true });
    } else {
      fillForm({ ...Object.fromEntries(allFields().map(f => [f.key, null])), ...(p.details || {}) });
      setGate('G25');
      S.prediction = null; S.recovery = null;
      $('#result-body').innerHTML = `<p class="empty">New project. Fill in what you know at the checkpoint (SPI and the first-quarter events matter most), then press <b>Run forecast</b> and <b>Save to project</b>.</p>`;
      $('#source-note').textContent = `${p.name}: filled from the project details.`;
    }
    if (!p.live_id) await followLive(null);
    if (location.hash === '#projects' || !location.hash || tab) showTab(tab || 'delay');
    else showTab(location.hash.slice(1), { push: false });
  } catch (e) {
    if (e?.status === 404) { try { localStorage.removeItem('revive-project'); } catch { /* */ } showTab('projects'); return; }
    report(e);
  }
}

async function deleteProject(id) {
  const p = S.projects.find(x => x.id === id);
  if (!p || !confirm(`Delete "${p.name}"? Its schedule, model, assessments, site link and history are removed for good.`)) return;
  try {
    await del(`/projects/${id}`);
    if (S.project?.id === id) { S.project = null; setProject(null); followLive(null); setTitleblocks(); }
    toast(`Deleted "${p.name}".`, 'ok');
    await loadProjects();
  } catch (e) { report(e); }
}

/** A worked example so every sheet has data: a preset, an assessment and three site updates. */
async function loadSampleProject() {
  const pre = S.presets[0], close = toast('Building the sample project', 'info', { sticky: true });
  try {
    const start = new Date(Date.now() - 1000 * 86400 * 30.44 * 7).toISOString().slice(0, 10);
    const city = (S.places?.places || []).find(x => pre.name.includes(x.name));
    const p = await post('/projects', { name: `Sample: ${pre.name}`, client: 'Sample data', code: 'SAMPLE-01', start_date: start,
      location: city ? { name: city.name, lat: city.lat, lon: city.lon } : null,
      details: { province: pre.inputs.province, project_type: pre.inputs.project_type, planned_months: pre.inputs.planned_months || 18 },
      inputs: pre.inputs, gate: pre.gate });
    setProject(p.id);
    await post('/assessments', { name: `${pre.name} at 25%`, inputs: pre.inputs, gate: pre.gate });
    const lp = await post('/live', { name: p.name, inputs: pre.inputs, gate: pre.gate });
    const tok = lp.site_path.split('/').pop();
    // six fortnightly site updates, written the way a site engineer reports them (all labelled sample data)
    const ups = [
      { elapsed_pct: 29, spi: 0.88, events: { late_payments: 1 }, note: 'Sample: IPC-3 certified 41 days ago, still unpaid. Concrete pours slowed to save cash.' },
      { elapsed_pct: 33, spi: 0.86, events: { weather_days: 3, rfis: 1 }, note: 'Sample: three days of rain stopped the second-floor slab pour. RFI-12 on beam reinforcement still open.' },
      { elapsed_pct: 37, spi: 0.83, events: { material_events: 1 }, note: 'Sample: 16 mm rebar shortage at the supplier, columns on grid C waited five days.' },
      { elapsed_pct: 41, spi: 0.81, events: { variations: 1, late_payments: 1 }, note: 'Sample: VO-2 (extra lift shaft) instructed without a time extension. IPC-4 now 35 days late.' },
      { elapsed_pct: 45, spi: 0.80, cpi: 0.93, events: { rfis: 2 }, note: 'Sample: revised MEP drawings issued; two RFIs raised on sleeve positions.' },
      { elapsed_pct: 49, spi: 0.79, cpi: 0.92, events: { weather_days: 2 }, note: 'Sample: dust storm, crane stood down two days. Night shift on blockwork started.' }];
    for (const u of ups) await post(`/site/${tok}/update`, { reporter: 'Sample: site engineer', ...u });
    await loadProjects();
    await openProject(p.id, { tab: 'delay' });
    toast('Sample project ready. Everything in it is labelled sample data.', 'ok');
  } catch (e) { report(e); }
  finally { close?.(); }
}

// ================================================================== new-project dialog
const PM_STEPS = ['details', 'schedule', 'bim'];
let pmStep = 'details';

function fillSelect(sel, opts, blank = 'Not set') {
  $(sel).innerHTML = `<option value="">${blank}</option>` + opts.map(o => `<option>${esc(o)}</option>`).join('');
}

function openProjectModal() {
  const f = k => field(k)?.options || [];
  fillSelect('#pm-type', f('project_type')); fillSelect('#pm-province', f('province')); fillSelect('#pm-value', f('contract_value'));
  $('#pm-city').innerHTML = (S.places?.places || []).map(p => `<option>${esc(p.name)}</option>`).join('');
  $('#pm-form').reset(); $('#pm-err').textContent = ''; $('#pm-sched-name').textContent = ''; $('#pm-ifc-name').textContent = '';
  $('#pm-ifc-drop').hidden = true;
  pmGo('details');
  $('#project-modal').showModal();
  setTimeout(() => $('#pm-name').focus(), 60);
}

function pmGo(step) {
  const dir = Math.sign(PM_STEPS.indexOf(step) - PM_STEPS.indexOf(pmStep));
  pmStep = step;
  $$('.pm-tabs button').forEach(b => b.setAttribute('aria-selected', String(b.dataset.pt === step)));
  $$('.pm-panel').forEach(p => { p.hidden = p.dataset.pp !== step; });
  enter($(`.pm-panel[data-pp="${step}"]`), dir, { distance: 24, duration: 0.28 });
  const i = PM_STEPS.indexOf(step);
  $('#pm-back').hidden = i === 0;
  $('#pm-next').hidden = i === PM_STEPS.length - 1;
}

async function createProject(e) {
  e.preventDefault();
  const name = $('#pm-name').value.trim();
  if (!name) { pmGo('details'); $('#pm-err').textContent = 'Give the project a name.'; $('#pm-name').focus(); return; }
  const city = (S.places?.places || []).find(p => p.name === $('#pm-city').value);
  const details = Object.fromEntries([['project_type', $('#pm-type').value], ['province', $('#pm-province').value],
    ['contract_value', $('#pm-value').value], ['planned_months', $('#pm-months').value ? Number($('#pm-months').value) : null]].filter(([, v]) => v));
  const btn = $('#pm-create'); btn.disabled = true; btn.textContent = 'Creating';
  try {
    const p = await post('/projects', { name, client: $('#pm-client').value || null, code: $('#pm-code').value || null,
      start_date: $('#pm-start').value || null, details, location: city ? { name: city.name, lat: city.lat, lon: city.lon } : null });
    setProject(p.id);
    const sched = $('#pm-sched').files[0], mode = $('input[name=pm-bim]:checked').value, ifc = $('#pm-ifc').files[0];
    const warn = [];
    if (sched) { btn.textContent = 'Importing the schedule'; try { await upload('/schedule/upload', sched); } catch (err) { warn.push(err.message); } }
    if (mode === 'file' && ifc) { btn.textContent = 'Reading the IFC model'; try { await upload('/bim/upload', ifc); } catch (err) { warn.push(err.message); } }
    else if (mode === 'none') await post('/bim/disconnect', {});
    $('#project-modal').close();
    await loadProjects();
    await openProject(p.id, { tab: 'assess' });
    toast(warn.length ? `Project created, but: ${warn.join(' ')}` : `"${p.name}" created. Fill in the forecast answers you know.`, warn.length ? 'error' : 'ok');
  } catch (err) { $('#pm-err').textContent = err.message; }
  finally { btn.disabled = false; btn.textContent = 'Create project'; }
}

function wireDrop(dropSel, inputSel, nameSel) {
  const drop = $(dropSel), input = $(inputSel);
  const show = () => { $(nameSel).textContent = input.files[0] ? `${input.files[0].name} (${(input.files[0].size / 1048576).toFixed(1)} MB)` : ''; drop.classList.toggle('has', !!input.files[0]); };
  input.addEventListener('change', show);
  ['dragenter', 'dragover'].forEach(t => drop.addEventListener(t, e => { e.preventDefault(); drop.classList.add('over'); }));
  ['dragleave', 'drop'].forEach(t => drop.addEventListener(t, () => drop.classList.remove('over')));
  drop.addEventListener('drop', e => { e.preventDefault(); if (e.dataTransfer.files[0]) { input.files = e.dataTransfer.files; show(); } });
}

// ================================================================== team and account
async function openTeam() {
  closeMenus();
  try {
    const t = await api('/team');
    $('#team-list').innerHTML = t.members.map(m => `<li><span class="av">${esc(initials(m.name))}</span><div><b>${esc(m.name)}</b><small>${esc(m.email)}</small></div>
      <span class="role ${m.role}">${m.role}</span>${S.user.role === 'admin' && m.id !== t.you ? `<button type="button" class="linkbtn" data-rm="${m.id}">Remove</button>` : ''}</li>`).join('');
    $$('#team-list [data-rm]').forEach(b => b.addEventListener('click', async () => {
      if (!confirm('Remove this person? They are signed out at once.')) return;
      try { await del(`/team/${b.dataset.rm}`); openTeam(); } catch (e) { report(e); }
    }));
    $('#tm-form').hidden = S.user.role !== 'admin';
    if (!$('#team-modal').open) $('#team-modal').showModal();
  } catch (e) { report(e); }
}

async function addMember(e) {
  e.preventDefault();
  try {
    await post('/team', { name: $('#tm-name').value, email: $('#tm-email').value, password: $('#tm-pass').value, role: $('#tm-role').value });
    $('#tm-form').reset();
    toast('Added. Share the temporary password privately and ask them to change it.', 'ok');
    openTeam();
  } catch (err) { report(err); }
}

const initials = n => String(n || '?').split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join('') || '?';

async function signOut() {
  try { await post('/auth/logout', {}); } catch { /* signing out anyway */ }
  try { localStorage.removeItem('revive-project'); localStorage.removeItem('revive-follow'); } catch { /* */ }
  location.href = '/';
}

function closeMenus() {
  ['#proj-menu', '#user-menu'].forEach(m => { $(m).hidden = true; });
  $('#proj-btn').setAttribute('aria-expanded', 'false'); $('#user-btn').setAttribute('aria-expanded', 'false');
}

function toggleMenu(btn, menu) {
  const open = $(menu).hidden;
  closeMenus();
  $(menu).hidden = !open; $(btn).setAttribute('aria-expanded', String(open));
}

// ================================================================== current delay sheet
let delayTimer = null;
function refreshDelay() {
  clearTimeout(delayTimer);
  delayTimer = setTimeout(loadDelay, 120);
}

async function loadDelay() {
  if (!S.project) { renderNoProject('delay'); return; }
  if (S.tab !== 'delay' && !S.booted) return;
  try {
    S.delay = await api(`/projects/${S.project.id}/delay`);
    if (S.tab === 'delay') renderDelay();
  } catch (e) { report(e); }
}

/** A thin meter under a figure: the value as a bar, its reference as a tick, and the gap between them in the
 *  delay band's colour, so a lag is seen before it is read. Values are fractions of the bar (0..1). */
function meter(m, colour) {
  if (!m || !Number.isFinite(m.v)) return '';
  const c = x => Math.max(0, Math.min(1, x)) * 100;
  const v = c(m.v), r = m.ref == null ? null : c(m.ref);
  const gap = r == null ? '' : `<em style="left:${Math.min(v, r)}%;width:${Math.abs(r - v)}%"></em><b style="left:${r}%"></b>`;
  return `<span class="meter" style="--c:${esc(colour || 'var(--chalk-2)')}" role="img" aria-label="${esc(m.label || '')}"><i style="width:${v}%"></i>${gap}</span>`;
}

function renderDelay() {
  const d = S.delay;
  setTitleblocks();
  if (!d?.available) {
    $('#delay-body').hidden = true; $('#delay-empty').hidden = false;
    $('#delay-empty').innerHTML = `${EMPTY_ART}<h3>No progress reading yet</h3><p class="muted">${esc(d?.reason || '')}</p>
      <div class="actions"><a class="btn primary" href="#assess">Enter the checkpoint answers</a><a class="btn ghost" href="#live">Start the site link</a><button type="button" class="btn ghost" data-act="prog">Enter activity progress</button></div>`;
    $('#delay-empty [data-act=prog]').addEventListener('click', () => { $('#delay-body').hidden = false; $('#delay-empty').hidden = true; openProgress(); });
    return;
  }
  $('#delay-empty').hidden = true; $('#delay-body').hidden = false;
  const b = d.delay_band, st = d.status;
  $('#dl-band').style.setProperty('--c', b.color); $('#dl-band').textContent = b.name;
  const big = $('#dl-days');
  big.style.color = b.color;
  fx.countUp(big, d.delay_days, v => `${v > 0.05 ? "+" : ""}${Math.round(v)}`, 1100);
  big.dataset.unit = Math.abs(d.delay_days) === 1 ? 'day' : 'days';
  $('#dl-cap').innerHTML = d.delay_days > 0.5
    ? `behind programme at the status date, ${b.pct_of_duration}% of the planned duration. If the remaining work goes to plan, completion moves from day ${fmt.num(d.planned_days)} to day ${fmt.num(d.finish.to_plan)}${d.finish_dates.to_plan ? ` (${esc(d.finish_dates.to_plan)})` : ''}.`
    : d.delay_days < -0.5 ? `ahead of programme at the status date.` : `on programme at the status date.`;
  $('#dl-source').innerHTML = `<b>Status ${esc(d.status_date || '')}</b> &middot; ${esc(d.source)}${d.days_since_status != null ? ` &middot; ${d.days_since_status === 0 ? 'today' : `${d.days_since_status} days ago`}` : ''}`;
  const span = d.planned_days || 1;
  const k = [
    ['Actual time', st.at, v => `day ${fmt.num(v)}`, `${fmt.num(st.elapsed_pct, 0)}% of contract time`, { v: st.at / span }],
    ['Earned schedule', st.es, v => `day ${fmt.num(v)}`, `work done matches the plan on this day`, { v: st.es / span, ref: st.at / span, label: 'earned day against today' }],
    ['SPI(t)', st.spi_t ?? 0, v => fmt.num(v, 2), st.spi_t < 1 ? 'time efficiency, below 1 = slipping' : 'time efficiency', { v: (st.spi_t ?? 0) / 1.25, ref: 1 / 1.25, label: 'SPI against 1.0' }],
    ['Work done', st.ev * 100, v => `${fmt.num(v, 1)}%`, `planned ${fmt.num(st.pv * 100, 1)}% by now`, { v: st.ev, ref: st.pv, label: 'work done against planned' }],
  ];
  if (d.cost_overrun_to_date_pct != null) k.push(['Cost to date', d.cost_overrun_to_date_pct, v => fmt.pct(v, 1), `CPI ${fmt.num(d.cpi, 2)}: spend against value of work done`]);
  if (d.calendar) k.push(['Estimated delay today', d.calendar.estimated_delay_today_days, v => `${fmt.num(v)} d`, `calendar is at ${fmt.num(d.calendar.elapsed_today_pct, 0)}% of contract time`]);
  $('#dl-kpis').innerHTML = k.map(([t, , , sub, m], i) => `<div class="kpi" style="--d:${i * 70}ms"><dt>${t}</dt><dd data-i="${i}"></dd><small>${esc(sub)}</small>${meter(m, b.color)}</div>`).join('');
  k.forEach(([, v, f], i) => fx.countUp($(`#dl-kpis dd[data-i="${i}"]`), v ?? 0, f, 900));
  $('#dl-notes').innerHTML = d.notes.map(n => `<p class="note warn">${esc(n)}</p>`).join('');
  C.sCurve($('#scurve'), d);
  C.finish3($('#finish3'), d);
  const wins = d.windows || [];
  $('#win-note').textContent = wins.length ? `${wins.length} windows, from the site updates` : '';
  if (wins.length) C.windowsChart($('#windows'), wins, d.category_labels); else $('#windows').innerHTML = '<p class="fine">Windows appear once the project is on the live site link: each site update closes a window.</p>';
  renderApportionment(d);
  $('#dl-acts tbody').innerHTML = d.activities.length ? d.activities.map((a, i) => `<tr style="--d:${i * 30}ms" class="${a.late ? 'late' : ''}">
      <td><b>${esc(a.id)}</b> ${esc(a.name)}${a.critical ? ' <span class="tag crit">critical</span>' : ''}</td>
      <td class="n">${fmt.num(a.planned_pct, 0)}%</td><td class="n">${fmt.num(a.actual_pct, 0)}%</td>
      <td class="n">${a.behind_days > 0.05 ? `<span class="behind" style="--w:${Math.min(100, a.behind_days * 4)}%">${fmt.num(a.behind_days, 1)} d</span>` : '<span class="muted">on plan</span>'}</td>
      <td class="n">${a.total_float == null ? '\u2014' : `${fmt.num(a.total_float, 0)} d`}</td></tr>`).join('')
    : '<tr><td colspan="5" class="muted">No activity was due to have started by the status date.</td></tr>';
  $('#dl-method').innerHTML = `<p>${esc(d.method)}</p><ul class="plain">
    <li><b>Planned progress</b>: CPM early-start baseline (${d.schedule_activities} activities, ${fmt.num(d.planned_days)} days), work weighted by duration.</li>
    <li><b>Earned schedule</b>: the day on which the plan reached the work actually done. Delay to date = actual time minus earned schedule, then confirmed by re-networking the remaining work from the status date.</li>
    <li><b>Windows</b>: slip between consecutive site updates. Weather days count as days; the rest is shared by event count between client-side and contractor-side events. This flags delay worth an extension-of-time notice; it is not a forensic delay analysis (SCL Protocol, AACE 29R-03).</li>
    ${d.contract_days !== d.planned_days ? `<li><b>Calendar</b>: schedule days are scaled by ${d.day_scale} to the ${fmt.num(d.contract_days)}-day contract duration to give dates. Upload the project's own schedule to remove the scaling.</li>` : ''}</ul>`;
  $('#prog-note').classList.toggle('on', d.source.startsWith('Activity'));
}

function renderApportionment(d) {
  const a = d.apportionment || {}, labs = d.category_labels || {};
  const cats = [['client', 'var(--watch)'], ['neutral', '#6CB2FF'], ['contractor', 'var(--risk)'], ['unexplained', 'var(--chalk-3)']];
  const total = cats.reduce((t, [k]) => t + (a[k] || 0), 0);
  if (!total) { $('#appo').innerHTML = ''; return; }
  $('#appo').innerHTML = `<div class="stack tall">${cats.map(([k, c], i) => a[k] ? `<i style="width:${(100 * a[k] / total).toFixed(2)}%;background:${c};--d:${i * 120}ms" data-tip="${esc(labs[k])}: ${fmt.num(a[k], 1)} days"></i>` : '').join('')}</div>
    <ul class="stack-legend four">${cats.map(([k, c]) => `<li><i style="--c:${c}"></i>${esc(labs[k])}<b>${fmt.num(a[k] || 0, 1)} d</b></li>`).join('')}</ul>
    <p class="fine">Gross slip ${fmt.num(total, 1)} days${a.recovered ? `, of which ${fmt.num(a.recovered, 1)} days were recovered in later windows` : ''}. Indicatively excusable (client-side and weather): <b>${fmt.num(d.excusable_days_indicative, 1)} days</b>.</p>`;
}

async function openProgress() {
  if (!S.project) return;
  try {
    const r = await api(`/projects/${S.project.id}/activities`);
    const at = S.delay?.status?.at ?? 0;
    const due = r.activities.filter(a => a.es <= Math.max(at, r.planned_days * 0.05) * 1.15 || a.pct != null);
    $('#prog-date').value = r.progress?.as_of || new Date().toISOString().slice(0, 10);
    $('#prog-elapsed').value = r.progress?.elapsed_pct ?? Math.round(S.delay?.status?.elapsed_pct ?? 25);
    $('#prog-list').innerHTML = due.map(a => {
      const v = a.pct ?? '';
      return `<label class="prog-row"><span><b>${esc(a.id)}</b> ${esc(a.name)}${a.critical ? ' <span class="tag crit">critical</span>' : ''}<small>planned day ${fmt.num(a.es)} to ${fmt.num(a.ef)}</small></span>
        <input type="range" min="0" max="100" step="5" value="${v === '' ? 0 : v}" data-id="${esc(a.id)}" class="${v === '' ? 'unset' : ''}"><output>${v === '' ? 'as planned' : `${v}%`}</output></label>`;
    }).join('') || '<p class="muted">No activity is due yet.</p>';
    $$('#prog-list input').forEach(i => {
      i.style.setProperty('--p', `${i.value}%`);
      i.addEventListener('input', () => { i.classList.remove('unset'); i.nextElementSibling.textContent = `${i.value}%`; i.style.setProperty('--p', `${i.value}%`); });
    });
    $('#prog-form').hidden = false;
    $('#prog-form').scrollIntoView({ behavior: REDUCED ? 'auto' : 'smooth', block: 'nearest' });
  } catch (e) { report(e); }
}

async function saveProgress(e) {
  e.preventDefault();
  const acts = Object.fromEntries($$('#prog-list input:not(.unset)').map(i => [i.dataset.id, Number(i.value)]));
  if (!Object.keys(acts).length) { toast('Move at least one slider: activities left "as planned" are assumed on plan.'); return; }
  try {
    S.delay = await post(`/projects/${S.project.id}/progress`, { as_of: $('#prog-date').value, elapsed_pct: Number($('#prog-elapsed').value), activities: acts });
    renderDelay(); loadProjects();
    toast('Current delay re-measured from activity progress.', 'ok');
  } catch (err) { report(err); }
}

async function clearProgress() {
  try {
    S.delay = await post(`/projects/${S.project.id}/progress`, { activities: {} });
    $('#prog-form').hidden = true; renderDelay(); loadProjects();
  } catch (err) { report(err); }
}

// ================================================================== wiring
function wire() {
  $('#replay-play').addEventListener('click', toggleReplay);
  $('#replay-step').addEventListener('input', e => { stopReplay(); showReplayStep(Number(e.target.value)); });
  $('#assess-form').addEventListener('submit', e => { e.preventDefault(); runForecast({ base: true }); });
  $$('#gate-switch button').forEach(b => b.addEventListener('click', () => { setGate(b.dataset.gate); if ($('#auto-run').checked && S.prediction) scheduleRun(100, { base: true }); }));
  $('#preset-select').addEventListener('change', e => {
    const p = S.presets.find(x => x.id === e.target.value);
    if (p) { loadPreset(p); runForecast({ base: true }); }
  });
  $('#bim-fill').addEventListener('click', () => {
    const a = S.summary?.autofill || {};
    Object.entries(a).forEach(([k, v]) => { if (v != null) $(`#f-${k}`).value = v; });
    toast(S.bimConnected ? `Filled from the BIM model and schedule: ${a.floor_area_m2} m\u00b2, ${a.storeys} storeys, ${a.planned_months} months.`
      : `Filled from the baseline schedule: ${a.planned_months} months.`, 'ok');
    if ($('#auto-run').checked && S.prediction) scheduleRun(100, { base: true });
  });
  $('#whatif-reset').addEventListener('click', () => {
    if (!S.baseInputs) return;
    fillForm(S.baseInputs);
    $('#source-note').textContent = 'Back to the entered values.';
    runForecast({ base: true });
  });
  $('#save-btn').addEventListener('click', saveAssessment);
  $('#save-name').addEventListener('input', e => { e.target.dataset.auto = '0'; });
  $$('#filters button').forEach(b => b.addEventListener('click', () => {
    S.filter = b.dataset.f;
    $$('#filters button').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
    renderPortfolio();
  }));
  $('#search').addEventListener('input', e => { S.query = e.target.value; renderPortfolio(); });
  $$('.hud-modes button').forEach(b => b.addEventListener('click', () => setMode(b.dataset.mode)));
  $('#scrub').addEventListener('input', e => { S.t = Number(e.target.value); S.scrubbing = true; if (S.mode !== 'build') setMode('build'); updateReadout(); paintTwin(); });
  $('#scrub').addEventListener('change', () => { S.scrubbing = false; });
  $('#play').addEventListener('click', togglePlay);
  $$('#sched-switch button').forEach(b => b.addEventListener('click', () => {
    S.sched = b.dataset.s;
    $$('#sched-switch button').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
    if (S.mode !== 'build') setMode('build'); else paintTwin();
  }));
  $('#rec-form').addEventListener('submit', e => { e.preventDefault(); runRecovery(); });
  $('#ifc-file').addEventListener('change', e => uploadFile('ifc', e.target));
  $('#ifc-file-2').addEventListener('change', e => uploadFile('ifc', e.target));
  $('#sched-file').addEventListener('change', e => uploadFile('schedule', e.target));
  $('#bim-demo').addEventListener('click', () => bimAction('/bim/demo', 'Demo BIM model connected to this project.'));
  $('#bim-demo-2').addEventListener('click', () => bimAction('/bim/demo', 'Demo BIM model connected to this project.'));
  $('#bim-disconnect').addEventListener('click', () => bimAction('/bim/disconnect', 'BIM model disconnected. Everything else keeps running on the baseline schedule.'));
  $('#reset-sched').addEventListener('click', () => bimAction('/schedule/reset', 'Back on the demo baseline schedule.'));
  $('#wx-loc').addEventListener('change', () => { S.wxPinned = true; loadWeather(); });
  $('#wx-apply').addEventListener('change', () => { if (S.prediction) runRecovery(); });
  $('#export-ifc').addEventListener('click', exportIfc);
  $('#live-start').addEventListener('click', startLive);
  $('#live-rotate').addEventListener('click', rotateLink);
  $('#live-base').addEventListener('change', e => { try { localStorage.setItem('revive-base', e.target.value); } catch { /* private mode */ } renderLinkCard(); });
  $('#live-copy').addEventListener('click', copyLink);
  // shell
  sheetNav();
  addEventListener('hashchange', () => { const id = location.hash.slice(1); if (TABS.includes(id)) showTab(id, { push: false }); });
  addEventListener('resize', () => moveTabInd({ instant: true }));
  wireTabBar();
  segs();
  tilt();
  $('#proj-btn').addEventListener('click', e => { e.stopPropagation(); toggleMenu('#proj-btn', '#proj-menu'); });
  $('#user-btn').addEventListener('click', e => { e.stopPropagation(); toggleMenu('#user-btn', '#user-menu'); });
  document.addEventListener('click', e => { if (!e.target.closest('.menu')) closeMenus(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeMenus(); });
  $('#signout').addEventListener('click', signOut);
  $('#team-open').addEventListener('click', openTeam);
  $('#tm-close').addEventListener('click', () => $('#team-modal').close());
  $('#tm-form').addEventListener('submit', addMember);
  $('#new-project').addEventListener('click', openProjectModal);
  $('#ws-search').addEventListener('input', e => { S.wsQuery = e.target.value; renderCards(); });
  $$('#ws-sort button').forEach(b => b.addEventListener('click', () => {
    S.wsSort = b.dataset.s; $$('#ws-sort button').forEach(x => x.setAttribute('aria-pressed', String(x === b))); renderCards();
  }));
  $('#pm-close').addEventListener('click', () => $('#project-modal').close());
  $$('.pm-tabs button').forEach(b => b.addEventListener('click', () => pmGo(b.dataset.pt)));
  $('#pm-next').addEventListener('click', () => pmGo(PM_STEPS[PM_STEPS.indexOf(pmStep) + 1]));
  $('#pm-back').addEventListener('click', () => pmGo(PM_STEPS[PM_STEPS.indexOf(pmStep) - 1]));
  $('#pm-form').addEventListener('submit', createProject);
  $$('input[name=pm-bim]').forEach(r => r.addEventListener('change', () => { $('#pm-ifc-drop').hidden = $('input[name=pm-bim]:checked').value !== 'file'; }));
  $('#pm-province').addEventListener('change', e => { const c = S.places?.province_default?.[e.target.value]; if (c) $('#pm-city').value = c; });
  wireDrop('#pm-sched-drop', '#pm-sched', '#pm-sched-name');
  wireDrop('#pm-ifc-drop', '#pm-ifc', '#pm-ifc-name');
  $('#prog-open').addEventListener('click', openProgress);
  $('#prog-form').addEventListener('submit', saveProgress);
  $('#prog-clear').addEventListener('click', clearProgress);
}

// ================================================================== init
async function init() {
  const [me, schema, card, presets] = await Promise.all([api('/auth/me'), api('/schema'), api('/model-card'), api('/presets')]);
  Object.assign(S, { user: me.user, schema, card, presets });
  $('#user-initials').textContent = initials(me.user.name);
  $('#user-company').textContent = me.user.company_name;
  $('#user-email').textContent = `${me.user.name} \u00b7 ${me.user.email} \u00b7 ${me.user.role}`;
  $('#ws-company').textContent = me.user.company_name;
  $('#foot-company').textContent = `Workspace: ${me.user.company_name}`;
  $('#ld').value = schema.optimizer.default_ld_per_day_pkr;
  $('#status').textContent = 'Connected';
  buildForm();
  renderClusterIdle();
  await initWeather();
  $('#preset-select').innerHTML = '<option value="">Choose</option>' + presets.map(p => `<option value="${p.id}">${esc(p.name)}</option>`).join('');
  renderEvidence();
  loadPortfolio().catch(report);
  api('/insights').then(ins => { S.insights = ins; renderInsightCharts(); }).catch(report);
  await loadProjects();
  channel.start();
  await loadLiveList();
  const remembered = Number(localStorage.getItem('revive-project'));
  const hash = location.hash.slice(1);
  if (remembered && S.projects.some(p => p.id === remembered)) await openProject(remembered, { tab: TABS.includes(hash) && hash !== 'projects' ? hash : null });
  else {
    await refreshBimSummary(); loadTwins();
    loadPreset(presets[0]); $('#preset-select').value = presets[0].id;
    runForecast({ base: true });
    showTab(TABS.includes(hash) ? hash : 'projects', { push: false });
  }
  S.booted = true;
}

async function boot() {
  tips = fx.tooltips();
  channel = new LiveChannel({ onUpdate: onLiveUpdate, onPresence, onProject: () => { loadLiveList(); loadProjects(); }, onStatus: onLiveStatus });
  wire();
  onConnChange(showConnState);
  setInterval(tickLabels, 1000);
  if (!(await ping())) {
    $('#conn-overlay').hidden = false;
    $('#status').textContent = 'Waiting for the server';
    await waitForServer(n => { $('#conn-try').textContent = `Attempt ${n}: no answer yet. Retrying automatically; this page continues by itself.`; });
    $('#conn-overlay').hidden = true;
  }
  heartbeat();
  for (;;) {
    try { await init(); break; }
    catch (e) {
      if (e?.status === 401) return;              // conn.js is already taking the user to sign in
      if (e?.network) {
        $('#conn-overlay').hidden = false;
        await waitForServer(n => { $('#conn-try').textContent = `Lost the server during start-up. Attempt ${n}, retrying.`; });
        $('#conn-overlay').hidden = true;
        continue;
      }
      console.error(e);
      $('#status').textContent = 'Dashboard error';
      toast(`The dashboard hit an error while starting: ${e.message}. Reload the page; if it repeats run "python -m revive doctor".`, 'error', { sticky: true });
      break;
    }
  }
}

boot();
