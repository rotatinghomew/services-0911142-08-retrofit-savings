const state = {context: null, current: null};
const element = identifier => document.getElementById(identifier);

async function request(path, body) {
  const response = await fetch(path, body === undefined ? {} : {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
  });
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || '请求失败');
  return value;
}

function message(value, error = false) {
  element('status').textContent = value;
  element('status').className = error ? 'error' : '';
}

async function guarded(action) {
  try { await action(); } catch (error) { message(error.message, true); }
}

function selected() {
  const selection = {};
  for (const control of state.context.product.options) selection[control[0]] = element('select-' + control[0]).value;
  return {revision: element('revision').value, selection};
}

function renderControls() {
  const revision = element('revision').value || state.context.default_revision;
  element('revision').replaceChildren();
  for (const dataset of state.context.datasets) {
    const option = document.createElement('option');
    option.value = dataset.revision;
    option.textContent = dataset.label + ' · ' + dataset.revision.slice(0, 9);
    element('revision').append(option);
  }
  element('revision').value = revision;
  if (!element('revision').value) element('revision').value = state.context.default_revision;
  if (element('controls').children.length) return;
  for (const [key, labelText, choices] of state.context.product.options) {
    const label = document.createElement('label');
    label.textContent = labelText;
    const select = document.createElement('select');
    select.id = 'select-' + key;
    for (const choice of choices) {
      const option = document.createElement('option');
      option.value = choice;
      option.textContent = choice;
      select.append(option);
    }
    select.value = state.context.product.selection[key];
    label.append(select);
    element('controls').append(label);
  }
}

function displayValue(value) {
  if (value === null || value === undefined) return '未观测';
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(4);
  return typeof value === 'object' ? JSON.stringify(value) : String(value);
}

function drawChart(series) {
  const canvas = element('chart');
  const context = canvas.getContext('2d');
  context.clearRect(0, 0, canvas.width, canvas.height);
  const values = series.filter(point => typeof point.y === 'number' && Number.isFinite(point.y));
  context.font = '12px sans-serif';
  if (!values.length) { context.fillText('该范围没有可定量的描述值', 30, 50); return; }
  const low = Math.min(0, ...values.map(point => point.y));
  const high = Math.max(1, ...values.map(point => point.y));
  const scale = value => 250 - (value - low) / (high - low || 1) * 210;
  context.strokeStyle = '#90a5ad';
  context.beginPath(); context.moveTo(45, 20); context.lineTo(45, 250); context.lineTo(940, 250); context.stroke();
  context.fillStyle = '#0a7168';
  const scatter = values.every(point => typeof point.x === 'number');
  const minimumX = scatter ? Math.min(...values.map(point => point.x)) : 0;
  const maximumX = scatter ? Math.max(...values.map(point => point.x)) : 1;
  values.forEach((point, index) => {
    const position = scatter ? 60 + (point.x - minimumX) / (maximumX - minimumX || 1) * 850 : 55 + index * 875 / values.length;
    if (scatter) {
      context.beginPath(); context.arc(position, scale(point.y), 3.5, 0, Math.PI * 2); context.fill();
    } else {
      context.fillRect(position, Math.min(scale(point.y), scale(0)), Math.max(3, 800 / values.length), Math.max(1, Math.abs(scale(point.y) - scale(0))));
    }
    if (values.length < 12) context.fillText(point.label, position, 275);
  });
  context.fillStyle = '#29434e';
  context.fillText(high.toFixed(2), 0, 45); context.fillText(low.toFixed(2), 0, 250);
  context.fillText(scatter ? '所选资料的数值坐标（仅为原始描述）' : '按表中顺序展示描述值；缺测不绘制为零', 50, 20);
}

function render(result, heading) {
  state.current = result;
  element('summary').replaceChildren();
  for (const [label, value] of Object.entries(result.view.summary)) {
    const card = document.createElement('article');
    const title = document.createElement('span'); title.textContent = label;
    const amount = document.createElement('strong'); amount.textContent = displayValue(value);
    card.append(title, amount); element('summary').append(card);
  }
  element('notes').replaceChildren();
  for (const note of result.view.notes) {
    const paragraph = document.createElement('p'); paragraph.textContent = note; element('notes').append(paragraph);
  }
  const rows = result.view.rows;
  const fields = rows.length ? Object.keys(rows[0]) : [];
  const header = document.createElement('tr');
  for (const field of fields) { const cell = document.createElement('th'); cell.textContent = field; header.append(cell); }
  element('columns').replaceChildren(header); element('rows').replaceChildren();
  for (const row of rows) {
    const line = document.createElement('tr'); line.tabIndex = 0;
    for (const field of fields) { const cell = document.createElement('td'); cell.textContent = displayValue(row[field]); line.append(cell); }
    line.onclick = () => { element('details').textContent = JSON.stringify(row, null, 2); };
    line.onkeydown = event => { if (event.key === 'Enter') line.click(); };
    element('rows').append(line);
  }
  drawChart(result.view.series);
  element('details').textContent = JSON.stringify({revision: result.revision, selection: result.selection,
    history: result.view.history || null}, null, 2);
  message((heading || '已更新描述') + ' · 数据 ' + result.revision.slice(0, 12));
}

async function refresh() {
  state.context = await request('/api/context');
  renderControls();
  element('archive').replaceChildren();
  for (const notebook of state.context.notebooks) {
    const button = document.createElement('button'); button.textContent = notebook.title + ' #' + notebook.id;
    button.onclick = () => guarded(async () => {
      const saved = await request('/api/notebooks/' + notebook.id);
      element('revision').value = saved.revision;
      for (const [key, value] of Object.entries(saved.selection)) {
        const control = element('select-' + key); if (control) control.value = value;
      }
      render(saved.result, '已读取保存的描述，不随新数据变化');
    });
    element('archive').append(button);
  }
}

element('inspect').onclick = () => guarded(async () => render(await request('/api/explore', selected())));
element('save').onclick = () => guarded(async () => {
  const saved = await request('/api/notebooks', {...selected(), title: element('title').value});
  await refresh(); render(saved.result, '已保存记录 #' + saved.id);
});
element('raw').onclick = () => guarded(async () => {
  const revision = state.current ? state.current.revision : element('revision').value;
  element('details').textContent = JSON.stringify(await request('/api/data?revision=' + encodeURIComponent(revision)), null, 2);
});
element('upload').onchange = () => guarded(async () => {
  const file = element('upload').files[0]; if (!file) return;
  const data = JSON.parse(await file.text());
  const uploaded = await request('/api/datasets', {label: file.name, data});
  await refresh(); element('revision').value = uploaded.revision;
  render(await request('/api/explore', selected()), '已导入独立数据版本');
});
element('export').onclick = () => guarded(async () => {
  if (!state.current) throw new Error('请先查看一个范围');
  const data = await request('/api/data?revision=' + encodeURIComponent(state.current.revision));
  const blob = new Blob([JSON.stringify({description: state.current, data}, null, 2)], {type: 'application/json'});
  const url = URL.createObjectURL(blob); const link = document.createElement('a');
  link.href = url; link.download = 'analysis-' + state.current.revision.slice(0, 12) + '.json'; link.click();
  URL.revokeObjectURL(url);
});

/* ---------------- 节能核验视图 ---------------- */

const verifyState = {result: null, scenarios: []};

function fmt(value, digits = 1) {
  if (value === null || value === undefined) return '未观测';
  if (typeof value !== 'number') return String(value);
  if (!Number.isFinite(value)) return '不可计算';
  return Math.abs(value) >= 1000 ? value.toLocaleString('zh-CN', {maximumFractionDigits: digits})
    : value.toFixed(digits);
}
function pct(value) { return value === null || value === undefined ? '不给出' : (value * 100).toFixed(1) + '%'; }

function card(label, value, hint = '') {
  const article = document.createElement('article');
  const title = document.createElement('span'); title.textContent = label;
  const amount = document.createElement('strong'); amount.textContent = value;
  article.append(title, amount);
  if (hint) { const small = document.createElement('small'); small.textContent = hint; article.append(small); }
  return article;
}

function verifyPayload() {
  const approvals = {};
  for (const control of document.querySelectorAll('.approval-toggle')) {
    approvals[control.dataset.adjustment] = control.checked;
  }
  const windowValue = {};
  const start = element('base-start').value; const stop = element('base-stop').value;
  if (start !== '') windowValue.start = Number(start);
  if (stop !== '') windowValue.stop = Number(stop);
  return {
    revision: element('revision').value,
    site: element('verify-site').value,
    assumptions: {
      baseline_window: windowValue,
      holdout_days: Number(element('holdout').value),
      approvals,
      scenario_label: element('scenario-label').value || '当前情景',
    },
  };
}

function renderVerdict(payload) {
  const v = payload.verification;
  const box = element('verdict');
  box.replaceChildren();
  const banner = document.createElement('div');
  banner.className = 'verdict ' + (v.comparable ? 'ok' : 'blocked');
  banner.innerHTML = '<strong>' + (v.comparable ? '可比较：整体节能率有效'
    : '停止给出整体节能率') + '</strong>';
  const sub = document.createElement('p');
  sub.textContent = v.comparable
    ? '全部覆盖率、留时段验证、外推范围与调整依据通过，整体节能率 ' + pct(v.overall_savings_rate)
    : '存在 ' + v.blocking_reasons.length + ' 项不可比较依据，下表段数据仍可用于线索排查，但不得汇总为整体节能率。';
  banner.append(sub);
  box.append(banner);
}

function renderTotals(payload) {
  const t = payload.verification.totals;
  const wrap = element('verify-totals');
  if (!t.computable) {
    wrap.replaceChildren(
      card('调整后反事实用量 kWh', '不可计算'),
      card('报告期实际用量 kWh', '不可计算'),
      card('节省量 kWh', '不可计算'),
      card('节省率', '不给出', '全部表段模型未建立'),
      card('节省量95%区间 kWh', '不可计算'),
      card('调整合计 kWh', '不可计算'),
    );
    return;
  }
  wrap.replaceChildren(
    card('调整后反事实用量 kWh', fmt(t.adjusted_counterfactual_kwh), '含已批准单独调整'),
    card('报告期实际用量 kWh', fmt(t.actual_kwh), '仅总表口径'),
    card('节省量 kWh', fmt(t.savings_kwh), '反事实 − 实际'),
    card('节省率', pct(payload.verification.overall_savings_rate), '阻断时不给出'),
    card('节省量95%区间 kWh', fmt(t.savings_ci95_kwh[0]) + ' ~ ' + fmt(t.savings_ci95_kwh[1])),
    card('调整合计 kWh', fmt(t.adjustment_kwh)),
  );
}

function renderBlockers(payload) {
  const v = payload.verification;
  const wrap = element('verify-blockers');
  wrap.replaceChildren();
  if (!v.blocking_reasons.length) {
    const ok = document.createElement('p'); ok.className = 'ok-text';
    ok.textContent = '无阻断项：覆盖率、留时段验证、外推范围与调整估计均满足可比较要求。';
    wrap.append(ok);
  } else {
    const list = document.createElement('ul');
    for (const reason of v.blocking_reasons) {
      const item = document.createElement('li');
      const scope = reason.meter_id ? '[' + reason.meter_id + '] ' : reason.adjustment ? '[' + reason.adjustment + '] ' : '';
      item.textContent = scope + reason.reason;
      list.append(item);
    }
    wrap.append(list);
  }
  const notes = element('verify-notes');
  notes.replaceChildren();
  for (const note of v.method_notes) {
    const p = document.createElement('p'); p.className = 'hint'; p.textContent = note; notes.append(p);
  }
}

function renderAssumptions(payload) {
  const v = payload.verification;
  const wrap = element('verify-assumptions');
  wrap.replaceChildren();
  const a = payload.assumptions;
  const lines = [
    ['情景名称', a.scenario_label],
    ['基准期窗口', JSON.stringify(a.baseline_window) + '（资料范围 ' + v.periods.baseline.start + '–' + v.periods.baseline.stop + '）'],
    ['留时段验证天数', a.holdout_days],
    ['情景指纹', payload.scenario_fingerprint.slice(0, 16) + '…（同数据+同假设可复现）'],
    ['数据版本', payload.revision.slice(0, 12) + '…'],
  ];
  const table = document.createElement('table');
  for (const [k, value] of lines) {
    const tr = document.createElement('tr');
    const th = document.createElement('th'); th.textContent = k;
    const td = document.createElement('td'); td.textContent = value;
    tr.append(th, td); table.append(tr);
  }
  wrap.append(table);
}

function renderMeters(payload) {
  const wrap = element('verify-meters');
  wrap.replaceChildren();
  for (const meter of payload.verification.meters) {
    const block = document.createElement('details');
    const summary = document.createElement('summary');
    summary.textContent = meter.meter_id + ' · ' + meter.boundary +
      (meter.sub_of ? '（分表，隶属 ' + meter.sub_of + '）' : '（总表）') +
      ' — ' + (meter.model_status === 'fitted' ? '模型已建立' : '模型失败：' + meter.model_message);
    block.append(summary);
    if (meter.model_status !== 'fitted') {
      const p = document.createElement('p'); p.className = 'error-text'; p.textContent = meter.model_message;
      block.append(p);
      const cover = document.createElement('ul');
      const li = document.createElement('li');
      li.textContent = '基准期覆盖 ' + (meter.baseline_coverage.measured_share * 100).toFixed(1) +
        '%，报告期覆盖 ' + (meter.report_coverage.measured_share * 100).toFixed(1) + '%';
      cover.append(li); block.append(cover);
      wrap.append(block);
      continue;
    }
    const cards = document.createElement('div'); cards.className = 'mini-cards';
    cards.append(
      card('反事实 kWh', fmt(meter.counterfactual.total_kwh)),
      card('调整后反事实 kWh', fmt(meter.counterfactual.adjusted_total_kwh)),
      card('实际 kWh', fmt(meter.actual.observed_total_kwh)),
      card('节省量 kWh', fmt(meter.savings.kwh)),
      card('表段节省率', pct(meter.savings.rate)),
      card('节省标准差 kWh', fmt(meter.savings.std_kwh)),
    );
    block.append(cards);

    const diag = document.createElement('ul');
    const diagItems = [
      '留时段验证 CV：' + (meter.holdout.cv * 100).toFixed(1) + '%（限值 ' +
        (meter.holdout.limit_cv * 100).toFixed(0) + '%），' + (meter.holdout.passed ? '通过' : '未通过'),
      '残差标准差 ' + fmt(meter.residuals.sigma_kwh) + ' kWh，AR(1) 自相关 ' + meter.ar1_phi.toFixed(3) +
        '，异常残差 ' + meter.residuals.outliers.length + ' 个',
      '外推天数 ' + meter.counterfactual.extrapolated_days.length + ' / ' + meter.actual.calendar_days +
        '（' + (meter.counterfactual.extrapolation_ratio * 100).toFixed(1) + '%）',
      '基准期覆盖 ' + (meter.baseline_coverage.measured_share * 100).toFixed(1) +
        '%，报告期覆盖 ' + (meter.report_coverage.measured_share * 100).toFixed(1) + '%，' +
        '重置日 ' + JSON.stringify(meter.report_coverage.reset_days) + '，缺测日 ' + JSON.stringify(meter.report_coverage.missing_days),
    ];
    for (const text of diagItems) { const li = document.createElement('li'); li.textContent = text; diag.append(li); }
    block.append(diag);

    const coef = document.createElement('table');
    const head = document.createElement('tr');
    for (const h of ['模型项', '系数', '标准误']) { const th = document.createElement('th'); th.textContent = h; head.append(th); }
    coef.append(head);
    for (const item of meter.coefficients) {
      const tr = document.createElement('tr');
      tr.innerHTML = '<td>' + item.label + '</td><td>' + fmt(item.coefficient, 3) + '</td><td>' +
        fmt(item.std_error, 3) + '</td>';
      coef.append(tr);
    }
    block.append(coef);

    const daily = document.createElement('table');
    const dhead = document.createElement('tr');
    for (const h of ['日', '温度', '时长', '人数', '反事实', '实际', '参数σ', '过程σ', '外推']) {
      const th = document.createElement('th'); th.textContent = h; dhead.append(th);
    }
    daily.append(dhead);
    for (const row of meter.counterfactual.daily) {
      const tr = document.createElement('tr');
      tr.innerHTML = '<td>' + row.day + '</td><td>' + fmt(row.temperature, 2) + '</td><td>' +
        fmt(row.service_hours, 0) + '</td><td>' + fmt(row.users, 0) + '</td><td>' +
        fmt(row.counterfactual_kwh) + '</td><td>' + (row.observed ? fmt(row.actual_kwh) : '缺测') +
        '</td><td>' + fmt(row.param_std_kwh) + '</td><td>' + fmt(row.process_std_kwh) + '</td><td>' +
        (row.outside_support ? row.outside_terms.join(',') : '范围内') + '</td>';
      daily.append(tr);
    }
    block.append(daily);

    const meterRows = document.createElement('table');
    const mhead = document.createElement('tr');
    for (const h of ['日', '状态', '倍率', '表盘原始差分', '规范化 kWh']) {
      const th = document.createElement('th'); th.textContent = h; mhead.append(th);
    }
    meterRows.append(mhead);
    for (const row of meter.daily_metering) {
      const tr = document.createElement('tr');
      tr.innerHTML = '<td>' + row.day + '</td><td>' + row.status + '</td><td>' + row.multiplier +
        '</td><td>' + displayValue(row.raw_delta) + '</td><td>' + displayValue(row.kwh) + '</td>';
      meterRows.append(tr);
    }
    block.append(meterRows);
    wrap.append(block);
  }
}

function renderAdjustments(payload) {
  const wrap = element('verify-adjustments');
  wrap.replaceChildren();
  const intro = document.createElement('p');
  intro.className = 'hint';
  intro.textContent = '例行计量条件（倍率、换表重置、序列水平漂移）已在计量规范化与基线模型中处理，不在此台账；' +
    '下列均为需要业务判断的单独调整。勾选框为研究员的批准覆盖，运行核验后生效并留痕。';
  wrap.append(intro);
  const table = document.createElement('table');
  const head = document.createElement('tr');
  for (const h of ['调整编号', '类型', '窗口', '入账表段', '资料批准', '研究员批准', '日均影响', '累计影响', '状态依据']) {
    const th = document.createElement('th'); th.textContent = h; head.append(th);
  }
  table.append(head);
  const seen = new Set();
  for (const row of payload.verification.adjustment_ledger) {
    const key = row.adjustment + (row.meter_id || '');
    if (seen.has(key)) continue;
    seen.add(key);
    const tr = document.createElement('tr');
    const toggleId = 'approval-' + row.adjustment;
    tr.innerHTML = '<td>' + row.adjustment + '</td><td>' + row.kind_label + '</td><td>' + row.start +
      '–' + row.stop + '</td><td>' + (row.meter_id || '无对应表段') + '</td><td>' +
      (row.approved && row.basis === 'dataset' ? '是' : '否') + '</td><td></td><td>' +
      displayValue(row.daily_impact_kwh) + '</td><td>' + displayValue(row.total_impact_kwh) +
      '</td><td>' + row.note + '</td>';
    const toggleCell = tr.children[5];
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox'; checkbox.className = 'approval-toggle';
    checkbox.dataset.adjustment = row.adjustment;
    checkbox.checked = row.approved;
    toggleCell.append(checkbox);
    table.append(tr);
  }
  wrap.append(table);
}

function renderVerification(payload) {
  verifyState.result = payload;
  renderVerdict(payload);
  renderTotals(payload);
  renderBlockers(payload);
  renderAssumptions(payload);
  renderMeters(payload);
  renderAdjustments(payload);
  element('verify-json').textContent = JSON.stringify(payload, null, 2);
  message('节能核验完成 · 情景 ' + payload.assumptions.scenario_label +
    ' · 数据 ' + payload.revision.slice(0, 12));
}

function snapshotScenario(payload) {
  const t = payload.verification.totals;
  return {
    label: payload.assumptions.scenario_label,
    fingerprint: payload.scenario_fingerprint,
    assumptions: payload.assumptions,
    comparable: payload.verification.comparable,
    rate: payload.verification.overall_savings_rate,
    computable: payload.verification.totals.computable,
    totals: t,
    blockers: payload.verification.blocking_reasons,
  };
}

function renderCompare() {
  const grid = element('compare-grid');
  grid.replaceChildren();
  if (verifyState.scenarios.length < 2) {
    const p = document.createElement('p'); p.className = 'hint';
    p.textContent = '当前已固定 ' + verifyState.scenarios.length + ' 个情景，再运行一次不同假设即可并排。';
    grid.append(p);
    return;
  }
  const pair = verifyState.scenarios.slice(-2);
  const numericOrNa = getter => s => (s.computable ? getter(s) : '不可计算');
  const rows = [
    ['情景名称', s => s.label],
    ['情景指纹', s => s.fingerprint.slice(0, 16) + '…'],
    ['基准期窗口', s => JSON.stringify(s.assumptions.baseline_window)],
    ['留时段天数', s => s.assumptions.holdout_days],
    ['批准覆盖', s => JSON.stringify(s.assumptions.approvals)],
    ['可比较', s => s.comparable ? '是' : '否（停止给出整体节能率）'],
    ['整体节能率', s => pct(s.rate)],
    ['调整后反事实 kWh', numericOrNa(s => fmt(s.totals.adjusted_counterfactual_kwh))],
    ['实际 kWh', numericOrNa(s => fmt(s.totals.actual_kwh))],
    ['节省量 kWh', numericOrNa(s => fmt(s.totals.savings_kwh))],
    ['节省95%区间', numericOrNa(s => fmt(s.totals.savings_ci95_kwh[0]) + ' ~ ' + fmt(s.totals.savings_ci95_kwh[1]))],
    ['阻断项', s => String(s.blockers.map(b => b.reason).join('；') || '无')],
  ];
  const table = document.createElement('table');
  for (const [label, getter] of rows) {
    const tr = document.createElement('tr');
    const th = document.createElement('th'); th.textContent = label;
    const a = document.createElement('td'); a.textContent = getter(pair[0]);
    const b = document.createElement('td'); b.textContent = getter(pair[1]);
    tr.append(th, a, b); table.append(tr);
  }
  grid.append(table);
}

function initVerifyControls() {
  const select = element('verify-site');
  if (!select.children.length) {
    const siteOption = state.context.product.options.find(option => option[0] === 'site');
    for (const choice of siteOption[2]) {
      const option = document.createElement('option');
      option.value = choice; option.textContent = choice;
      select.append(option);
    }
    select.value = state.context.product.selection.site;
  }
}

async function refreshVerifyArchive() {
  const archive = element('verify-archive');
  archive.replaceChildren();
  for (const item of state.context.verifications || []) {
    const button = document.createElement('button');
    button.textContent = item.title + ' #' + item.id;
    button.onclick = () => guarded(async () => {
      const saved = await request('/api/verifications/' + item.id);
      const payload = {
        revision: saved.revision, site: saved.site, assumptions: saved.assumptions,
        scenario_fingerprint: saved.fingerprint, verification: saved.result,
      };
      element('revision').value = saved.revision;
      element('verify-site').value = saved.site;
      renderVerification(payload);
    });
    archive.append(button);
  }
}

element('verify-run').onclick = () => guarded(async () => {
  const payload = await request('/api/verify', verifyPayload());
  renderVerification(payload);
  verifyState.scenarios.push(snapshotScenario(payload));
  renderCompare();
});
element('compare-toggle').onclick = () => {
  const panel = element('compare-panel');
  panel.hidden = !panel.hidden;
  element('compare-toggle').textContent = panel.hidden ? '开启并排情景复核' : '收起并排情景复核';
};
element('verify-save').onclick = () => guarded(async () => {
  if (!verifyState.result) throw new Error('请先运行一次节能核验');
  const body = {...verifyPayload(), title: element('verify-title').value};
  const saved = await request('/api/verifications', body);
  await refresh();
  await refreshVerifyArchive();
  message('已保存核验情景 #' + saved.id);
});

for (const tab of document.querySelectorAll('.tab')) {
  tab.onclick = () => {
    document.querySelectorAll('.tab').forEach(item => item.classList.toggle('active', item === tab));
    element('view-browse').hidden = tab.dataset.view !== 'browse';
    element('view-verify').hidden = tab.dataset.view !== 'verify';
    if (tab.dataset.view === 'verify') initVerifyControls();
  };
}

guarded(async () => { await refresh(); render(await request('/api/explore', selected())); initVerifyControls(); refreshVerifyArchive(); });
