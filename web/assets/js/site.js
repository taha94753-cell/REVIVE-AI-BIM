// Phone page for site staff: /site/<token>. The token is an unguessable link issued by the dashboard
// (it can be revoked there); no account is needed on the phone.
// - tells the dashboard this phone is connected (presence, every 15 s)
// - listens to the project's own stream, so the "now" line stays current
// - keeps an update that could not be sent (no signal) and sends it when the connection returns
import { segs } from './tabs.js';

const $ = s => document.querySelector(s);
const token = location.pathname.split('/').filter(Boolean).pop();
const API = `/api/site/${encodeURIComponent(token)}`;
const QKEY = `revive-queue-${token.slice(0, 12)}`;
const JSON_HDR = { 'Content-Type': 'application/json', 'X-Revive-Request': '1' };
const EVENTS = [
  ['late_payments', 'IPC paid more than 30 days late'], ['material_events', 'Material shortage stopped work'],
  ['variations', 'Variation order issued'], ['rfis', 'Design change or RFI'], ['weather_days', 'Working days lost to weather'],
];
const counts = Object.fromEntries(EVENTS.map(([k]) => [k, 0]));
const ratings = {};
let state = null, online = false;
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const pct = v => `${v > 0 ? '+' : ''}${Math.round(v)}%`;
const device = (() => {
  try { let d = localStorage.getItem('revive-device'); if (!d) { d = Math.random().toString(36).slice(2, 10); localStorage.setItem('revive-device', d); } return d; }
  catch { return Math.random().toString(36).slice(2, 10); }
})();
const label = /iPhone|iPad/.test(navigator.userAgent) ? 'An iPhone' : /Android/.test(navigator.userAgent) ? 'An Android phone' : 'A browser';
const buzz = p => { try { navigator.vibrate?.(p); } catch { /* not supported */ } };

function setConn(s, text) {
  const el = $('#site-conn');
  el.dataset.state = s;
  el.querySelector('span').textContent = text;
  online = s === 'online';
}

function renderEvents() {
  $('#events').innerHTML = EVENTS.map(([k, lab]) => `
    <div class="ev${counts[k] ? ' set' : ''}"><span>${lab}</span>
      <div class="stepper"><button type="button" data-k="${k}" data-d="-1" aria-label="One fewer">\u2212</button>
      <output>${counts[k]}</output><button type="button" data-k="${k}" data-d="1" aria-label="One more">+</button></div></div>`).join('');
  document.querySelectorAll('.stepper button').forEach(b => b.addEventListener('click', () => {
    counts[b.dataset.k] = Math.max(0, counts[b.dataset.k] + Number(b.dataset.d));
    buzz(8);
    renderEvents();
  }));
}

function renderRatings(st) {
  document.querySelectorAll('[data-rate]').forEach(el => {
    const key = el.dataset.rate;
    ratings[key] = ratings[key] ?? st[key];
    el.innerHTML = [1, 2, 3, 4, 5].map(v => `<button type="button" data-v="${v}" aria-pressed="${ratings[key] === v}">${v}</button>`).join('');
    el.querySelectorAll('button').forEach(b => b.addEventListener('click', () => { ratings[key] = Number(b.dataset.v); buzz(8); renderRatings(st); }));
  });
}

function renderNow(s, fresh = false) {
  $('#p-now').innerHTML = `<span class="chip" style="--c:${s.band.color}">${esc(s.band.name)}</span>
    <strong>${pct(s.time_overrun_pct)}</strong> forecast overrun at ${Math.round(s.elapsed_pct)}% of contract time`;
  if (fresh) { $('#p-now').classList.remove('flash-soft'); void $('#p-now').offsetWidth; $('#p-now').classList.add('flash-soft'); }
}

function setElapsedMin(e) {
  const r = $('#elapsed'), m = Math.ceil(e);
  r.min = m;
  if (Number(r.value) < m) r.value = m;
  $('#elapsed-out').textContent = `${r.value}%`;
}

async function load() {
  let r;
  try { r = await fetch(API, { cache: 'no-store' }); }
  catch { setConn('offline', 'No connection'); $('#p-name').textContent = 'Cannot reach REVIVE'; $('#p-sub').textContent = 'This phone must be on the same Wi-Fi or hotspot as the computer running REVIVE. Retrying.'; setTimeout(load, 4000); return; }
  if (!r.ok) { $('#p-name').textContent = 'This link is not valid'; $('#p-sub').textContent = 'It may have been replaced. Ask the project manager for the new QR code.'; $('#site-form').hidden = true; setConn('offline', 'Link not valid'); return; }
  const p = await r.json(), last = p.updates.at(-1);
  state = p.state;
  $('#p-name').textContent = p.name;
  $('#p-sub').textContent = `${p.updates.length} update${p.updates.length === 1 ? '' : 's'} so far. Last: ${last.created_at.replace('T', ' ')}.`;
  renderNow(last.summary);
  setElapsedMin(state.elapsed_pct);
  $('#elapsed').value = Math.ceil(state.elapsed_pct);
  $('#elapsed-out').textContent = `${$('#elapsed').value}%`;
  $('#spi').value = state.spi_now ?? '';
  $('#cpi').value = state.cpi_now ?? '';
  $('#cert').value = state.cert_now ?? '';
  try { $('#reporter').value = localStorage.getItem('revive-reporter') || ''; } catch { /* private mode */ }
  renderEvents(); renderRatings(state);
  setConn('online', 'Connected');
  loadWeather();
  presence();
  listen();
  flushQueue();
}

async function presence() {
  if (document.hidden) return;
  try {
    const r = await fetch(`${API}/presence`, { method: 'POST', headers: JSON_HDR, body: JSON.stringify({ device, label }) });
    if (r.ok) {
      const d = await r.json();
      setConn('online', 'Connected');
      $('#watchers').textContent = d.listeners ? `${d.listeners} dashboard${d.listeners === 1 ? '' : 's'} watching this project live.` : 'No dashboard is open right now; updates are saved and shown when one opens.';
    }
  } catch { setConn('offline', 'No connection'); }
}

function listen() {
  if (!('EventSource' in window)) return;
  const es = new EventSource(`${API}/stream`);
  es.onopen = () => { setConn('online', 'Connected'); flushQueue(); };
  es.onerror = () => setConn('offline', 'Reconnecting');
  es.addEventListener('update', e => {
    const m = JSON.parse(e.data);
    renderNow(m.update.summary, true);
    setElapsedMin(m.update.summary.elapsed_pct);
  });
}

async function loadWeather() {
  const none = 'Live weather unavailable. Enter weather days yourself.';
  try {
    const w = await (await fetch(`${API}/weather`)).json();
    if (!w.available) { $('#wx').textContent = none; return; }
    const n = w.suggested_lost_days;
    const list = w.suggested_days.map(d => `${d.date.slice(5)} ${d.reasons.join(', ')}`).join('; ');
    $('#wx').innerHTML = n
      ? `Live weather at ${esc(w.location.name)}: <strong>${n} likely lost day${n === 1 ? '' : 's'}</strong> since ${esc(w.since)} (${esc(list)}). Added below; change it if the site worked anyway.`
      : `Live weather at ${esc(w.location.name)}: no likely lost days since ${esc(w.since)}.`;
    if (n && counts.weather_days === 0) { counts.weather_days = n; renderEvents(); }
  } catch { $('#wx').textContent = none; }
}

function showResult(d) {
  const s = d.update.summary;
  $('#site-result').innerHTML = `<div class="site-done"><svg viewBox="0 0 52 52" class="tick" aria-hidden="true"><circle cx="26" cy="26" r="24"/><path d="M14 27l8 8 16-17"/></svg>
      <div><p class="site-ok">Update received</p><p class="muted">${d.delivered_to} dashboard${d.delivered_to === 1 ? '' : 's'} updated live.</p></div></div>
    <p><span class="chip" style="--c:${s.band.color}">${esc(s.band.name)}</span> <strong class="site-big">${pct(s.time_overrun_pct)}</strong>
    forecast overrun${s.delta_pts != null ? ` <span class="${s.delta_pts > 0 ? 'up' : 'down'}">(${s.delta_pts > 0 ? '+' : ''}${s.delta_pts} points)</span>` : ''}.</p>
    ${s.drivers.length ? `<p class="muted">Pushing it up: ${esc(s.drivers.join(', '))}.</p>` : ''}
    ${s.days_recovered != null ? `<p class="muted">The recovery plan now recovers ${Math.round(s.days_recovered)} days.</p>` : ''}`;
  renderNow(s, true);
  setElapsedMin(s.elapsed_pct);
  buzz([30, 60, 30]);
  $('#site-result').scrollIntoView({ behavior: 'smooth' });
}

async function post(body) {
  const r = await fetch(`${API}/update`, { method: 'POST', headers: JSON_HDR, body: JSON.stringify(body) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) { const e = new Error(typeof d.detail === 'string' ? d.detail : 'Update rejected: check the numbers'); e.rejected = true; throw e; }
  return d;
}

function readQueue() { try { return JSON.parse(localStorage.getItem(QKEY) || '[]'); } catch { return []; } }
function writeQueue(q) { try { localStorage.setItem(QKEY, JSON.stringify(q)); } catch { /* private mode */ } renderQueue(); }
function renderQueue() {
  const q = readQueue();
  $('#queue-note').hidden = !q.length;
  $('#queue-note').textContent = q.length ? `${q.length} update${q.length === 1 ? '' : 's'} waiting for a connection. ${q.length === 1 ? 'It is' : 'They are'} sent automatically.` : '';
}

let flushing = false;
async function flushQueue() {
  if (flushing) return;
  const q = readQueue();
  if (!q.length) return;
  flushing = true;
  try {
    while (q.length) {
      const d = await post(q[0]);
      q.shift(); writeQueue(q);
      showResult(d);
    }
  } catch (e) {
    if (e.rejected) { q.shift(); writeQueue(q); $('#site-result').innerHTML = `<p class="site-err">A saved update was rejected: ${esc(e.message)}</p>`; }
  } finally { flushing = false; }
}

async function send(e) {
  e.preventDefault();
  const btn = $('#send'); btn.disabled = true; btn.textContent = 'Sending';
  const num = id => $(id).value === '' ? null : Number($(id).value);
  const body = { reporter: $('#reporter').value, note: $('#note').value, elapsed_pct: num('#elapsed'),
    spi: num('#spi'), cpi: num('#cpi'), cert: num('#cert'), events: { ...counts }, rework: $('#rework').value || null, ...ratings };
  try { localStorage.setItem('revive-reporter', body.reporter); } catch { /* private mode */ }
  const reset = () => { Object.keys(counts).forEach(k => { counts[k] = 0; }); $('#note').value = ''; renderEvents(); };
  try {
    showResult(await post(body));
    reset();
  } catch (err) {
    if (err.rejected) {
      $('#site-result').innerHTML = `<p class="site-err">${esc(err.message)}</p>`;
      buzz(200);
    } else {
      const q = readQueue(); q.push(body); writeQueue(q);
      setConn('offline', 'No connection');
      $('#site-result').innerHTML = '<p class="site-warn">No connection right now. The update is saved on this phone and will be sent as soon as REVIVE can be reached.</p>';
      reset();
    }
  } finally { btn.disabled = false; btn.textContent = 'Send site update'; }
}

segs();
$('#elapsed').addEventListener('input', e => { $('#elapsed-out').textContent = `${e.target.value}%`; });
$('#site-form').addEventListener('submit', send);
setInterval(presence, 15000);
setInterval(flushQueue, 5000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) { presence(); flushQueue(); } });
addEventListener('online', () => { presence(); flushQueue(); });
renderQueue();
load();
