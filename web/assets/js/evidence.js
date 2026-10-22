// Extension-of-time evidence pack: renders /api/projects/{id}/evidence as an A4 document to print or save as PDF.
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const num = (v, d = 0) => (v == null || Number.isNaN(Number(v)) ? '—' : Number(v).toLocaleString('en', { maximumFractionDigits: d, minimumFractionDigits: d }));
const pct = (v, d = 0) => (v == null ? '—' : `${v > 0 ? '+' : ''}${Number(v).toFixed(d)}%`);
const day = s => (s ? String(s).slice(0, 10) : '—');
const BAND = { 'On track': '#1E9E62', Watch: '#B98A00', 'At risk': '#D9631E', Critical: '#C8283F' };
const CAT = { client: '#2D6FD1', neutral: '#7A8492', contractor: '#D9931E', unexplained: '#B9C0C8' };

$('#print').addEventListener('click', () => window.print());

async function load() {
  const pid = location.pathname.split('/').filter(Boolean).pop();
  const res = await fetch(`/api/projects/${encodeURIComponent(pid)}/evidence`, { credentials: 'same-origin' });
  if (res.status === 401) { location.href = '/?next=app#start'; return; }
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `HTTP ${res.status}`);
  render(await res.json());
}

function timeline(hist, warn) {
  if (!hist.length) return '<p class="muted">No forecasts recorded yet.</p>';
  const W = 720, H = 230, L = 52, R = 16, T = 14, B = 34;
  const ys = hist.map(h => h.time_overrun_pct);
  const ymax = Math.max(60, Math.ceil((Math.max(...ys) + 10) / 20) * 20), ymin = Math.min(0, Math.floor(Math.min(...ys) / 10) * 10);
  const x = e => L + (W - L - R) * Math.max(0, Math.min(100, e)) / 100;
  const y = v => T + (H - T - B) * (1 - (v - ymin) / (ymax - ymin || 1));
  let b = '';
  [[ymin, 10, '#E8F6EE'], [10, 30, '#FBF4DC'], [30, 50, '#FCEBDD'], [50, ymax, '#F9E1E5']].forEach(([a, c, col]) => {
    if (c > ymin && a < ymax) b += `<rect x="${L}" y="${y(Math.min(c, ymax))}" width="${W - L - R}" height="${y(Math.max(a, ymin)) - y(Math.min(c, ymax))}" fill="${col}"/>`;
  });
  for (let v = ymin; v <= ymax; v += 20) b += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="#D5DAE0" stroke-width=".6"/><text x="${L - 6}" y="${y(v) + 4}" text-anchor="end" class="ax">${v}%</text>`;
  for (let e = 0; e <= 100; e += 25) b += `<text x="${x(e)}" y="${H - 12}" text-anchor="middle" class="ax">${e}%</text>`;
  b += `<text x="${(L + W - R) / 2}" y="${H}" text-anchor="middle" class="ax">Contract time elapsed</text>`;
  b += `<line x1="${x(100)}" x2="${x(100)}" y1="${T}" y2="${H - B}" stroke="#20262E" stroke-dasharray="4 3"/><text x="${x(100) - 4}" y="${T + 10}" text-anchor="end" class="ax strong">Contract completion</text>`;
  b += `<polyline fill="none" stroke="#20262E" stroke-width="2" points="${hist.map(h => `${x(h.elapsed_pct)},${y(h.time_overrun_pct)}`).join(' ')}"/>`;
  hist.forEach(h => { b += `<circle cx="${x(h.elapsed_pct)}" cy="${y(h.time_overrun_pct)}" r="4.5" fill="${BAND[h.band] || '#20262E'}" stroke="#fff" stroke-width="1.5"/>`; });
  if (warn.warned) {
    const wx = x(warn.elapsed_pct);
    b += `<line x1="${wx}" x2="${wx}" y1="${T}" y2="${H - B}" stroke="#C8283F" stroke-width="1.5"/>`;
    b += `<line x1="${wx}" x2="${x(100)}" y1="${T + 26}" y2="${T + 26}" stroke="#C8283F" stroke-width="1.5" marker-end="url(#arr)"/>`;
    b += `<text x="${(wx + x(100)) / 2}" y="${T + 20}" text-anchor="middle" class="ax warn">${num(warn.days_before_completion)} days of warning</text>`;
  }
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Forecast overrun at each update"><defs><marker id="arr" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L8 4L0 8z" fill="#C8283F"/></marker></defs>${b}</svg>`;
}

function stack(totals, labels) {
  const keys = ['client', 'neutral', 'contractor', 'unexplained'], sum = keys.reduce((s, k) => s + (totals[k] || 0), 0);
  if (!sum) return '<p class="muted">No slip recorded between updates.</p>';
  return `<div class="stack">${keys.filter(k => totals[k]).map(k => `<i style="width:${(100 * totals[k] / sum).toFixed(2)}%;background:${CAT[k]}"></i>`).join('')}</div>
    <ul class="legend">${keys.map(k => `<li><i style="background:${CAT[k]}"></i>${esc(labels[k])}: <b>${num(totals[k], 1)} days</b></li>`).join('')}</ul>`;
}

function render(d) {
  const p = d.project, dl = d.delay || {}, w = d.early_warning || {}, f = d.forecast;
  document.title = `Evidence pack: ${p.name}`;
  const band = dl.delay_band || {};
  const fin = dl.finish_dates || {}, fd = dl.finish || {};
  const finishCell = (k, label) => `<div><dt>${label}</dt><dd>${fin[k] ? esc(fin[k]) : fd[k] != null ? `day ${num(fd[k])}` : '—'}</dd></div>`;
  $('#pack').innerHTML = `
  ${d.sample ? '<p class="sample">Sample data: this pack is built from the labelled sample project, not a real contract.</p>' : ''}
  <header class="head">
    <div><p class="kicker">Extension-of-time evidence pack</p><h1>${esc(p.name)}</h1>
      <p class="meta">${[p.code && `Contract ${esc(p.code)}`, p.client && `Client: ${esc(p.client)}`, p.location, p.project_type, p.province].filter(Boolean).join(' &middot; ')}</p></div>
    <dl class="tb"><div><dt>Prepared for</dt><dd>${esc(d.company)}</dd></div><div><dt>Prepared by</dt><dd>${esc(d.prepared_by)}</dd></div>
      <div><dt>Generated</dt><dd>${day(d.generated_at)}</dd></div><div><dt>Status date</dt><dd>${day(dl.status_date)}</dd></div></dl>
  </header>

  <section><h2>1. Summary</h2>
  ${dl.available ? `
    <dl class="kpis">
      <div><dt>Delay to date</dt><dd style="color:${esc(band.color || '#20262E')}">${num(dl.delay_days)} days</dd><small>${esc(band.name || '')}</small></div>
      <div><dt>SPI(t)</dt><dd>${num(dl.spi_t, 2)}</dd><small>earned schedule</small></div>
      <div><dt>Slip with client or weather events</dt><dd>${num(dl.excusable_days_indicative, 1)} days</dd><small>indicative, see section 3</small></div>
      <div><dt>Forecast overrun</dt><dd>${f ? pct(f.time_overrun_pct) : '—'}</dd><small>${f && f.interval ? `80% range ${pct(f.interval[0])} to ${pct(f.interval[1])}` : ''}</small></div>
    </dl>
    <dl class="fin"><div><dt>Planned completion</dt><dd>${esc(dl.planned_finish_date || '—')}</dd></div>
      ${finishCell('to_plan', 'If remaining work goes to plan')}${finishCell('current_pace', 'If the current pace continues')}${finishCell('ml_forecast', 'REVIVE forecast')}</dl>
    <p class="src">Status from: ${esc(dl.source || '')}.</p>`
    : `<p class="muted">${esc(dl.reason || 'No progress reading yet.')}</p>`}
  ${w.warned ? `<p class="callout warn"><b>Early warning.</b> ${esc(w.text)}${w.date ? ` Warning date: ${esc(w.date)}.` : ''}</p>` : `<p class="callout">${esc(w.text || '')}</p>`}
  ${d.notice ? `<p class="callout notice"><b>Notice.</b> ${esc(d.notice.text)} ${d.notice.days_left >= 0 ? `${d.notice.days_left} days left.` : `<b>${-d.notice.days_left} days overdue.</b>`}</p>` : ''}
  ${(dl.notes || []).map(n => `<p class="note">${esc(n)}</p>`).join('')}
  </section>

  <section><h2>2. Forecast history and early warning</h2>
    <div class="chart">${timeline(d.forecast_history || [], w)}</div>
    <p class="fine">Each point is one forecast (the saved assessment, then every site update), coloured by risk band. Bands: on track up to 10%, watch up to 30%, at risk up to 50%, critical above.</p>
  </section>

  <section><h2>3. Slip by window and its apportionment</h2>
    ${stack(d.apportionment || {}, d.category_labels || {})}
    <table><thead><tr><th>Window</th><th>Ends</th><th class="n">Time elapsed</th><th class="n">Slip (days)</th><th>Events reported</th><th class="n">Client</th><th class="n">Weather</th><th class="n">Contractor</th></tr></thead><tbody>
    ${(d.windows || []).map(x => `<tr${x.concurrent ? ' class="conc"' : ''}><td>${esc(x.label)}${x.concurrent ? ' <span class="tag">concurrent</span>' : ''}</td><td>${day(x.to)}</td>
      <td class="n">${num(x.elapsed_from)}% &rarr; ${num(x.elapsed_to)}%</td><td class="n">${num(x.slip_days, 1)}</td>
      <td>${x.label === 'Before monitoring' ? '<span class="muted">Up to the checkpoint assessment (survey answer bands, so counts are approximate):</span> ' : ''}${(x.events || []).map(e => `${num(e.count, x.label === 'Before monitoring' ? 1 : 0)} ${esc(e.label)}`).join(', ') || '—'}</td>
      <td class="n">${num(x.apportioned?.client, 1)}</td><td class="n">${num(x.apportioned?.neutral, 1)}</td><td class="n">${num(x.apportioned?.contractor, 1)}</td></tr>`).join('') || '<tr><td colspan="8" class="muted">No site updates yet: start the live site link to build this record.</td></tr>'}
    </tbody></table>
    <p class="fine">Slip in a window is the change in schedule variance (earned schedule) between two updates. Weather days count as days (neutral); the rest is shared by event count between client-side events (late IPCs, variations, design changes) and contractor-side events. Windows with both are concurrent and need the planner's review.</p>
  </section>

  ${(d.critical_activities_behind || []).length ? `<section><h2>4. Critical activities behind programme</h2>
    <table><thead><tr><th>Activity</th><th class="n">Planned</th><th class="n">Done</th><th class="n">Behind (days)</th></tr></thead><tbody>
    ${d.critical_activities_behind.map(a => `<tr><td><b>${esc(a.id)}</b> ${esc(a.name)}</td><td class="n">${num(a.planned_pct)}%</td><td class="n">${num(a.actual_pct)}%</td><td class="n">${num(a.behind_days, 1)}</td></tr>`).join('')}
    </tbody></table></section>` : ''}

  <section><h2>${(d.critical_activities_behind || []).length ? 5 : 4}. Contemporaneous site records</h2>
    <table class="log"><thead><tr><th>#</th><th>Date</th><th>Reported by</th><th>What was reported</th><th class="n">SPI</th><th class="n">Forecast</th></tr></thead><tbody>
    ${(d.site_records || []).map(r => `<tr><td>${r.no}</td><td>${day(r.at)}</td><td>${esc(r.reporter)}</td>
      <td>${(r.reported || []).map(esc).join('; ')}${r.note ? `<div class="nt">&ldquo;${esc(r.note)}&rdquo;</div>` : ''}</td>
      <td class="n">${num(r.spi, 2)}</td><td class="n"><span style="color:${BAND[r.band] || 'inherit'}">${pct(r.forecast_overrun_pct)}</span></td></tr>`).join('') || '<tr><td colspan="6" class="muted">No site records yet.</td></tr>'}
    </tbody></table></section>

  ${(d.actions || []).length ? `<section><h2>${(d.critical_activities_behind || []).length ? 6 : 5}. What is driving the forecast, and who acts</h2>
    <table><thead><tr><th>Owner</th><th>Driver</th><th class="n">Adds</th><th>Action this week</th></tr></thead><tbody>
    ${d.actions.map(a => `<tr><td>${esc(a.owner_label)}</td><td>${esc(a.reason)}</td><td class="n">+${num(a.adds_pct_points, 1)} pts</td><td>${esc(a.action)}</td></tr>`).join('')}
    </tbody></table></section>` : ''}

  <section class="sign"><h2>Method, limits and sign-off</h2>
    <p class="fine">${esc(dl.method || '')}</p>
    <p class="fine"><b>${esc(d.disclaimer)}</b></p>
    <div class="sig"><div><span>Prepared by (planning engineer)</span></div><div><span>Checked by (project manager)</span></div><div><span>Date</span></div></div>
  </section>
  <footer class="foot">REVIVE AI-BIM &middot; ${esc(p.name)} &middot; generated ${day(d.generated_at)}</footer>`;
}

load().catch(e => { $('#pack').innerHTML = `<p class="error">The evidence pack could not be built: ${esc(e.message)}</p>`; });
