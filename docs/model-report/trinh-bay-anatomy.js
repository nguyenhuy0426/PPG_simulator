// Feature and learning figures of trinh-bay.html, drawn as SVG from window.ANATOMY (media/ppg-anatomy.js).
(() => {
  const D = window.ANATOMY;
  if (!D) return;
  const NS = 'http://www.w3.org/2000/svg';
  const vi = (v, d) => v.toLocaleString('vi-VN', { minimumFractionDigits: d, maximumFractionDigits: d });
  const pct = (v, d = 0) => `${vi(v * 100, d)} %`;

  function el(name, attrs, parent, text) {
    const node = document.createElementNS(NS, name);
    Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, v));
    if (text !== undefined) node.textContent = text;
    if (parent) parent.appendChild(node);
    return node;
  }

  function svg(id, w, h, label) {
    const host = document.getElementById(id);
    if (!host) return null;
    host.textContent = '';
    return el('svg', { viewBox: `0 0 ${w} ${h}`, role: 'img', 'aria-label': label }, host);
  }

  const line = (pts, x, y) => pts.map(([a, b], i) => `${i ? 'L' : 'M'}${x(a).toFixed(1)},${y(b).toFixed(1)}`).join('');
  const defs = (s) => {
    const m = el('marker', { id: `${s.parentNode.id}-ar`, viewBox: '0 0 10 10', refX: 5, refY: 5, markerWidth: 7, markerHeight: 7, orient: 'auto-start-reverse' }, el('defs', {}, s));
    el('path', { class: 'an-ah', d: 'M0,1 L9,5 L0,9 z' }, m);
    return `url(#${m.id})`;
  };
  const call = (s, x, y, tx, ty, title, sub, anchor = 'start') => {
    el('line', { class: 'an-lead', x1: x, y1: y, x2: tx, y2: ty }, s);
    const dy = anchor === 'start' ? 6 : -6;
    el('text', { class: 'an-t', x: tx + dy, y: ty + 4, 'text-anchor': anchor }, s, title);
    if (sub) el('text', { class: 'an-s', x: tx + dy, y: ty + 21, 'text-anchor': anchor }, s, sub);
  };

  function chips(id, items, f) {
    const host = document.getElementById(id);
    if (!host) return;
    host.textContent = '';
    items.forEach(([label, value]) => {
      const c = document.createElement('span');
      const b = document.createElement('b');
      b.textContent = value(f);
      c.append(`${label} `, b);
      host.appendChild(c);
    });
  }

  // One median beat with the judge's measurements drawn on it.
  function beat(a, cls) {
    const W = 1000, H = 430, m = { l: 30, r: 330, t: 26, b: 58 };
    const s = svg('an-beat', W, H, 'Một nhịp PPG: chân sóng, đỉnh tâm thu, khuyết mạch, thời gian lên, độ rộng và diện tích');
    if (!s) return;
    const arrow = defs(s), k = a.marks, f = a.features, T = a.beat_s;
    const x = (t) => m.l + t / T * (W - m.l - m.r), y = (v) => m.t + (1 - v) * (H - m.t - m.b);
    const pts = a.template.map((v, i) => [i / (a.template.length - 1) * T, v]);
    el('rect', { class: 'an-rise', x: x(k.t10), y: m.t, width: x(k.t90) - x(k.t10), height: H - m.t - m.b }, s);
    el('path', { class: `an-fill ${cls}`, d: `${line(pts, x, y)}L${x(T)},${y(0)}L${x(0)},${y(0)}Z` }, s);
    a.shapes.forEach((shape) => el('path', { class: `an-ghost ${cls}`, d: line(shape.map((v, i) => [i / (shape.length - 1) * T, v]), x, y) }, s));
    el('line', { class: 'axis', x1: m.l, x2: W - m.r, y1: y(0), y2: y(0) }, s);
    el('path', { class: `an-beatline ${cls}`, d: line(pts, x, y) }, s);
    el('line', { class: 'an-measure', x1: x(k.w_lo), x2: x(k.w_hi), y1: y(.5), y2: y(.5), 'marker-start': arrow, 'marker-end': arrow }, s);
    const yb = y(0) + 18;
    el('line', { class: 'an-measure', x1: x(0), x2: x(k.top), y1: yb, y2: yb, 'marker-start': arrow, 'marker-end': arrow }, s);
    el('text', { class: 'an-s', x: x(k.top) + 10, y: yb + 4 }, s, `Pha tâm thu: ${pct(f.systolic_fraction)} nhịp`);
    el('text', { class: 'an-s', x: x(T), y: yb + 28, 'text-anchor': 'end' }, s, `Một nhịp dài ${vi(T, 2)} giây`);
    el('text', { class: 'an-s', x: x(k.t10), y: m.t - 8 }, s, 'Thời gian lên');
    [[0, a.template[0]], [k.top, 1]].forEach(([t, v]) => el('circle', { class: `an-dot ${cls}`, cx: x(t), cy: y(v), r: 7 }, s));
    const tx = W - m.r + 26;
    call(s, x(k.top), y(1), tx, y(.97), 'Đỉnh tâm thu', 'Tim bóp, máu dồn ra mạch');
    call(s, x(0), y(a.template[0]), tx, H - m.b + 12, 'Chân sóng', 'Lúc một nhịp mới bắt đầu');
    call(s, x(k.w_hi), y(.5), tx, y(.68), `Độ rộng ở nửa chiều cao: ${vi(f.width_50_s, 3)} s`);
    call(s, x((k.t10 + k.t90) / 2), y(.82), tx, y(.82), `Thời gian lên: ${vi(f.rise_time_s, 3)} s`);
    if (k.notch !== null) {
      el('circle', { class: 'an-notch', cx: x(k.notch), cy: y(k.notch_y), r: 7 }, s);
      el('circle', { class: 'an-notch', cx: x(k.crest), cy: y(k.crest_y), r: 7 }, s);
      call(s, x(k.crest), y(k.crest_y), tx, y(.42), 'Khuyết mạch và đỉnh phụ', 'Van tim đóng; chỉ xem, không chấm');
    }
    call(s, x(T * .72), y(.1), tx, y(.17), `Diện tích dưới sóng: ${pct(f.area_fraction)}`);
  }

  // Ten seconds: beat timing and amplitude.
  function seq(a, cls) {
    const W = 1000, H = 260, m = { l: 14, r: 14, t: 42, b: 44 };
    const s = svg('an-seq', W, H, 'Chuỗi nhịp 10 giây: khoảng nhịp, biên độ và phần nhận ra nhịp');
    if (!s) return;
    const arrow = defs(s), n = a.wave.length;
    const x = (i) => m.l + i / (n - 1) * (W - m.l - m.r), y = (v) => m.t + (1 - v) * (H - m.t - m.b);
    el('path', { class: `an-wave ${cls}`, d: line(a.wave.map((v, i) => [i, v]), x, y) }, s);
    a.peaks.forEach((p) => el('circle', { class: `an-dot ${cls}`, cx: x(p), cy: y(a.wave[p]), r: 4 }, s));
    a.feet.forEach((p) => el('circle', { class: 'an-foot', cx: x(p), cy: y(a.wave[p]), r: 3.5 }, s));
    const i = Math.min(5, a.peaks.length - 2), p0 = a.peaks[i], p1 = a.peaks[i + 1];
    el('line', { class: 'an-measure', x1: x(p0), x2: x(p1), y1: 26, y2: 26, 'marker-start': arrow, 'marker-end': arrow }, s);
    el('text', { class: 'an-t', x: x(p1) + 10, y: 30 }, s, `Khoảng nhịp ${vi((p1 - p0) / D.fs, 2)} s → ${vi(a.features.rate_bpm, 0)} nhịp/phút`);
    const foot = a.feet.find((q) => q > p0 + 2 && q < p1 + 30);
    if (foot !== undefined) {
      el('line', { class: 'an-measure', x1: x(p1), x2: x(p1), y1: y(a.wave[p1]) + 8, y2: y(a.wave[foot]), 'marker-start': arrow, 'marker-end': arrow }, s);
      el('text', { class: 'an-t', x: x(p1) + 8, y: y(a.wave[foot]) + 14 }, s, 'Biên độ');
    }
    el('rect', { class: 'an-cover', x: x(a.feet[0]), y: H - 26, width: x(n - 1) - x(a.feet[0]), height: 8, rx: 4 }, s);
    el('text', { class: 'an-s', x: x(a.feet[0]), y: H - 6 }, s, `Nhận ra nhịp trên ${pct(a.features.beat_coverage)} thời gian của đoạn 30 giây`);
  }

  function sharp(a, cls) {
    const W = 480, H = 210, m = 12;
    const s = svg('an-sharp', W, H, 'Tốc độ thay đổi của sóng theo thời gian');
    if (!s) return;
    const d = a.diff.slice(0, D.fs * 5), hi = Math.max(...d.map(Math.abs));
    const x = (i) => m + i / (d.length - 1) * (W - 2 * m), y = (v) => H / 2 - v / hi * (H / 2 - 20);
    el('line', { class: 'axis', x1: m, x2: W - m, y1: y(0), y2: y(0) }, s);
    el('path', { class: `an-wave ${cls}`, d: line(d.map((v, i) => [i, v]), x, y) }, s);
    el('text', { class: 'an-s', x: m, y: 14 }, s, 'Sóng dâng nhanh');
    el('text', { class: 'an-s', x: m, y: H - 4 }, s, 'Sóng tụt');
  }

  function hist(a, cls) {
    const W = 480, H = 210, m = { l: 12, r: 12, t: 22, b: 28 };
    const s = svg('an-hist', W, H, 'Thời gian sóng ở từng mức cao thấp');
    if (!s) return;
    const hi = Math.max(...a.hist), w = (W - m.l - m.r) / a.hist.length;
    a.hist.forEach((v, i) => {
      const h = v / hi * (H - m.t - m.b);
      el('rect', { class: `an-bar ${cls}`, x: m.l + i * w + 1, y: H - m.b - h, width: w - 2, height: h }, s);
    });
    const mx = m.l + a.features.mean_level * (W - m.l - m.r);
    el('line', { class: 'an-mean', x1: mx, x2: mx, y1: 14, y2: H - m.b }, s);
    el('text', { class: 'an-s', x: mx + 6, y: 16 }, s, 'mức trung bình');
    el('text', { class: 'an-s', x: m.l, y: H - 8 }, s, 'đáy sóng');
    el('text', { class: 'an-s', x: W - m.r, y: H - 8, 'text-anchor': 'end' }, s, 'đỉnh sóng');
  }

  function spectrum(a, cls) {
    const W = 480, H = 230, m = { l: 12, r: 12, t: 26, b: 44 };
    const s = svg('an-spec', W, H, 'Phổ của sóng, năm dải tần được đo');
    if (!s) return;
    const x = (f) => m.l + f / 10 * (W - m.l - m.r);
    const y = (v) => m.t + Math.min(-10 * Math.log10(Math.max(v, 1e-4)), 40) / 40 * (H - m.t - m.b);
    [[.5, 1.5, '0,5–1,5', 'power_0.5-1.5 Hz'], [1.5, 3, '1,5–3', 'power_1.5-3 Hz'], [3, 5, '3–5', 'power_3-5 Hz'], [5, 8, '5–8', 'power_5-8 Hz'], [8, 10, '8+', 'power_8-20 Hz']].forEach(([lo, hi, t, k], i) => {
      el('rect', { class: `an-band b${i % 2}`, x: x(lo), y: m.t, width: x(hi) - x(lo), height: H - m.t - m.b }, s);
      el('text', { class: 'an-s', x: (x(lo) + x(hi)) / 2, y: H - m.b + 16, 'text-anchor': 'middle' }, s, t);
      el('text', { class: 'an-t', x: (x(lo) + x(hi)) / 2, y: H - m.b + 34, 'text-anchor': 'middle' }, s, pct(10 ** a.features[k], k === 'power_8-20 Hz' || k === 'power_5-8 Hz' ? 1 : 0));
    });
    el('path', { class: `an-wave ${cls}`, d: line(a.spectrum.map((v, i) => [i * a.spectrum_df, v]), x, y) }, s);
    const c = x(a.features.centroid_hz);
    el('line', { class: 'an-mean', x1: c, x2: c, y1: 16, y2: H - m.b }, s);
    el('text', { class: 'an-s', x: c + 6, y: 16 }, s, `trọng tâm phổ ${vi(a.features.centroid_hz, 1)} Hz`);
  }

  function acf(a, cls) {
    const W = 480, H = 210, m = { l: 12, r: 12, t: 22, b: 28 };
    const s = svg('an-acf', W, H, 'Tự tương quan: sóng giống chính nó sau bao lâu');
    if (!s) return;
    const n = a.acf.length, x = (i) => m.l + i / (n - 1) * (W - m.l - m.r), y = (v) => m.t + (1 - (v + 1) / 2) * (H - m.t - m.b);
    el('line', { class: 'axis', x1: m.l, x2: W - m.r, y1: y(0), y2: y(0) }, s);
    el('path', { class: `an-wave ${cls}`, d: line(a.acf.map((v, i) => [i, v]), x, y) }, s);
    const lag = Math.round(60 / a.features.rate_bpm * D.fs);
    el('circle', { class: `an-dot ${cls}`, cx: x(lag), cy: y(a.acf[lag]), r: 6 }, s);
    el('text', { class: 'an-t', x: x(lag) + 10, y: y(a.acf[lag]) - 8 }, s, `Lặp lại sau ${vi(lag / D.fs, 2)} s`);
    el('text', { class: 'an-s', x: W - m.r, y: H - 8, 'text-anchor': 'end' }, s, `${ACF_LABEL} giây`);
  }
  const ACF_LABEL = '0 → 3';

  const FEATURES = {
    'an-seq-chips': [['Độ đều (đỉnh tự tương quan)', (f) => vi(f.acf_peak, 2)], ['Lệch khoảng nhịp', (f) => pct(f.ibi_cv, 1)], ['Lệch biên độ', (f) => pct(f.amp_cv, 1)], ['Giống khuôn nhịp', (f) => vi(f.template_corr, 2)]],
    'an-sharp-chips': [['Độ sắc', (f) => vi(f.diff_std, 3)], ['Độ gợn', (f) => vi(f.diff2_std, 3)], ['Lên nhanh hơn xuống', (f) => vi(f.diff_skew, 2)]],
    'an-hist-chips': [['Độ lệch', (f) => vi(f.skew, 2)], ['Độ nhọn', (f) => vi(f.kurtosis, 2)], ['Mức trung bình', (f) => vi(f.mean_level, 2)]],
  };

  function anatomy(which) {
    const a = D.anatomy[which], cls = which === 'real' ? 'real' : 'gen';
    beat(a, cls); seq(a, cls); sharp(a, cls); hist(a, cls); spectrum(a, cls); acf(a, cls);
    Object.entries(FEATURES).forEach(([id, items]) => chips(id, items, a.features));
    document.querySelectorAll('[data-source]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.source === which)));
  }

  // Score over training steps, the chosen checkpoint marked. lower: the score improves downward.
  function steps(id, title, xs, series, chosen, lower) {
    const W = 400, H = 240, m = { l: 42, r: 14, t: 34, b: 30 };
    const s = svg(id, W, H, title);
    if (!s) return;
    const all = series.flatMap((r) => r.y), lo = Math.min(...all), hi = Math.max(...all), span = hi - lo;
    const x = (v) => m.l + v / xs[xs.length - 1] * (W - m.l - m.r);
    const y = (v) => m.t + (hi + span * .06 - v) / (span * 1.12) * (H - m.t - m.b);
    [lo, (lo + hi) / 2, hi].forEach((v) => {
      el('line', { class: 'grid', x1: m.l, x2: W - m.r, y1: y(v), y2: y(v) }, s);
      el('text', { x: m.l - 6, y: y(v) + 4, 'text-anchor': 'end' }, s, vi(v, 2));
    });
    [0, xs[xs.length - 1]].forEach((v) => el('text', { x: x(v), y: H - 10, 'text-anchor': v ? 'end' : 'start' }, s, v ? `bước ${vi(v, 0)}` : '0'));
    series.forEach((r) => el('path', { class: `an-step ${r.cls}`, d: line(xs.map((v, i) => [v, r.y[i]]), x, y) }, s));
    el('text', { class: 'an-s', x: m.l, y: 14 }, s, lower ? '↓ thấp hơn là giống thật hơn' : '↑ cao hơn là giống thật hơn');
    const r = series[0], i = xs.indexOf(chosen), last = xs.length - 1;
    el('circle', { class: 'an-chosen', cx: x(chosen), cy: y(r.y[i]), r: 6 }, s);
    const right = x(chosen) > W / 2;
    el('text', { class: 'an-t', x: x(chosen) + (right ? -9 : 9), y: y(r.y[i]) + (lower ? 20 : -10), 'text-anchor': right ? 'end' : 'start' }, s, `Chọn: bước ${vi(chosen, 0)}`);
    el('circle', { class: 'an-last', cx: x(xs[last]), cy: y(r.y[last]), r: 5 }, s);
    el('text', { class: 'an-s', x: x(xs[last]), y: y(r.y[last]) + (lower ? -11 : 19), 'text-anchor': 'end' }, s, 'bước cuối');
  }

  function wrist() {
    const L = D.learning.wrist, W = 1000, H = 280, panel = 560;
    const s = svg('ln-wrist', W, H, 'Sóng cổ tay ở bước được chọn và bước cuối, số đỉnh mỗi phút theo bước train');
    if (!s) return;
    L.frames.forEach((f, r) => {
      const oy = 8 + r * 136, n = f.wave.length, cls = r ? 'bad' : 'chosen';
      el('text', { class: 'an-t', x: 8, y: oy + 14 }, s, r ? `Bước cuối ${vi(f.step, 0)}: nhịp bị nhân đôi` : `Bước ${vi(f.step, 0)}: bước được chọn của lần train này`);
      el('path', { class: `an-wave ${cls}`, d: line(f.wave.map((v, i) => [i, v]), (i) => 8 + i / (n - 1) * (panel - 24), (v) => oy + 22 + (1 - v) * 102) }, s);
    });
    const m = { l: panel + 44, r: 14, t: 34, b: 30 };
    const last = L.steps[L.steps.length - 1];
    const x = (v) => m.l + v / last * (W - m.l - m.r), y = (v) => m.t + (170 - v) / 130 * (H - m.t - m.b);
    [40, 75, 170].forEach((v) => el('text', { x: m.l - 6, y: y(v) + 4, 'text-anchor': 'end' }, s, v));
    el('text', { class: 'an-s', x: m.l, y: 14 }, s, 'Số đỉnh mỗi phút trên sóng cổ tay');
    el('line', { class: 'an-command', x1: m.l, x2: W - m.r, y1: y(L.command_bpm), y2: y(L.command_bpm) }, s);
    el('text', { class: 'an-s', x: W - m.r, y: y(L.command_bpm) + 18, 'text-anchor': 'end' }, s, `Lệnh ${vi(L.command_bpm, 0)} nhịp/phút`);
    el('path', { class: 'an-step bad', d: line(L.steps.map((v, i) => [v, L.peaks[i]]), x, y) }, s);
    [0, last].forEach((v) => el('text', { x: x(v), y: H - 10, 'text-anchor': v ? 'end' : 'start' }, s, v ? `bước ${vi(v, 0)}` : '0'));
  }

  // Highest correlation of each generated window with any training window: 1 would be an exact copy.
  function copies() {
    const rows = Object.entries(D.copies), W = 1000, rowH = 66, top = 34, left = 160, right = 180, H = top + rows.length * rowH + 22;
    const s = svg('cp-chart', W, H, 'Độ giống đoạn train gần nhất, theo bộ dữ liệu, so với người thật chưa train');
    if (!s) return;
    const x = (v) => left + v * (W - left - right);
    [0, .25, .5, .75, 1].forEach((v) => {
      el('line', { class: 'grid', x1: x(v), x2: x(v), y1: top - 8, y2: H - 22 }, s);
      el('text', { x: x(v), y: top - 14, 'text-anchor': 'middle' }, s, vi(v, 2));
    });
    el('line', { class: 'an-copyline', x1: x(.99), x2: x(.99), y1: top - 8, y2: H - 22 }, s);
    el('text', { class: 'an-copytext', x: x(.99) + 8, y: top - 14 }, s, 'Vùng sao chép (> 0,99)');
    el('text', { x: W - 4, y: top + 6, 'text-anchor': 'end' }, s, 'đoạn > 0,99');
    const sources = [['real_unseen', 'real', 'Người thật chưa train'], ['round9', 'mix', 'PhysioMix'], ['physioflow', 'flow', 'PhysioFlow']];
    rows.forEach(([name, set], r) => {
      const cy = top + r * rowH + rowH / 2;
      el('text', { class: 'lab', x: left - 14, y: cy + 4, 'text-anchor': 'end' }, s, name);
      sources.forEach(([k, cls], j) => {
        const yy = cy + (j - 1) * 17, v = set[k];
        const g = el('g', {}, s);
        el('title', {}, g, `${name}, ${sources[j][2]}: trung vị ${vi(v.median, 2)}, 95 % đoạn dưới ${vi(v.p95, 2)}, ${pct(v.above_0_99, 1)} đoạn trên 0,99`);
        el('line', { class: `an-range ${cls}`, x1: x(v.median), x2: x(v.p95), y1: yy, y2: yy }, g);
        el('circle', { class: `an-pt ${cls}`, cx: x(v.median), cy: yy, r: 6 }, g);
        el('text', { class: 'an-s', x: W - 4, y: yy + 4, 'text-anchor': 'end' }, g, pct(v.above_0_99, 1));
      });
    });
  }

  // Share of the real people's waveform shapes the source also produces.
  function coverage() {
    const rows = Object.entries(D.coverage), W = 1000, H = 280, m = { l: 34, r: 8, t: 14, b: 48 };
    const s = svg('cp-cover', W, H, 'Độ phủ theo bộ dữ liệu');
    if (!s) return;
    const y = (v) => m.t + (1 - v) * (H - m.t - m.b), cw = (W - m.l - m.r) / rows.length;
    [0, .5, 1].forEach((v) => {
      el('line', { class: 'grid', x1: m.l, x2: W - m.r, y1: y(v), y2: y(v) }, s);
      el('text', { x: m.l - 6, y: y(v) + 4, 'text-anchor': 'end' }, s, pct(v));
    });
    rows.forEach(([name, set], r) => {
      [['real_other_people', 'real'], ['round9', 'mix'], ['physioflow', 'flow']].forEach(([k, cls], j) => {
        const w = 40, bx = m.l + r * cw + cw / 2 - 1.5 * w + j * w;
        el('rect', { class: `an-pt ${cls}`, x: bx + 2, y: y(set[k]), width: w - 4, height: y(0) - y(set[k]), rx: 3 }, s);
        el('text', { class: 'an-s', x: bx + w / 2, y: y(set[k]) - 5, 'text-anchor': 'middle' }, s, vi(set[k] * 100, 0));
      });
      el('text', { class: 'lab', x: m.l + r * cw + cw / 2, y: H - 22, 'text-anchor': 'middle' }, s, name);
      el('text', { class: 'an-s', x: m.l + r * cw + cw / 2, y: H - 4, 'text-anchor': 'middle' }, s, `${COVER_PEOPLE[name]} người`);
    });
  }
  const COVER_PEOPLE = { 'Ngón tay': 44, 'ICU lớn': 191, BIDMC: 14, 'Rung nhĩ': 4, 'Không rung nhĩ': 2, 'Cổ tay vận động': 4 };

  anatomy('real');
  document.querySelectorAll('[data-source]').forEach((b) => b.addEventListener('click', () => anatomy(b.dataset.source)));
  const L = D.learning;
  steps('ln-mix', 'Điểm PhysioMix theo bước train', L.app_mix.steps, [{ y: L.app_mix.score, cls: 'chosen' }], L.app_mix.best, true);
  steps('ln-flow', 'Điểm PhysioFlow theo bước train', L.app_flow.steps, [{ y: L.app_flow.score, cls: 'chosen' }], L.app_flow.best, true);
  const best = L.gan.steps[L.gan.mean.indexOf(Math.max(...L.gan.mean))];
  steps('ln-gan', 'Độ giống đặc trưng của APFT-GAN theo bước train', L.gan.steps, [{ y: L.gan.mean, cls: 'chosen' }], best, false);
  wrist();
  copies();
  coverage();
})();
