// Charts of trinh-bay.html, drawn as SVG from window.REPORT (media/report-data.js). No external libraries.
(() => {
  const R = window.REPORT && window.REPORT.physigpt;
  if (!R) return;
  const NS = 'http://www.w3.org/2000/svg';
  const vi = (v, d) => v.toLocaleString('vi-VN', { minimumFractionDigits: d, maximumFractionDigits: d });

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
    return el('svg', { viewBox: `0 0 ${w} ${h}`, role: 'img', 'aria-label': label }, host);
  }

  const path = (pts, x, y) => pts.map(([a, b], i) => `${i ? 'L' : 'M'}${x(a).toFixed(1)},${y(b).toFixed(1)}`).join('');

  // Held-out flow loss over training steps: stable phase, then the decay from the best step.
  function curve() {
    const W = 520, H = 300, m = { l: 52, r: 16, t: 16, b: 36 };
    const s = svg('pg-curve', W, H, 'Sai số học theo bước train: pha ổn định rồi pha giảm learning rate');
    if (!s) return;
    const all = [...R.curve.stable, ...R.curve.decay];
    const x0 = 0, x1 = Math.max(...all.map((p) => p[0]));
    const y0 = 0.055, y1 = 0.09;
    const x = (v) => m.l + (v - x0) / (x1 - x0) * (W - m.l - m.r);
    const y = (v) => m.t + (y1 - Math.min(Math.max(v, y0), y1)) / (y1 - y0) * (H - m.t - m.b);
    [0.06, 0.07, 0.08, 0.09].forEach((v) => {
      el('line', { class: 'grid', x1: m.l, x2: W - m.r, y1: y(v), y2: y(v) }, s);
      el('text', { x: m.l - 8, y: y(v) + 4, 'text-anchor': 'end' }, s, vi(v, 2));
    });
    [0, 5000, 10000, 15000, 20000, 25000].forEach((v) => el('text', { x: x(v), y: H - 12, 'text-anchor': 'middle' }, s, vi(v / 1000, 0) + 'k'));
    el('text', { x: W - m.r, y: H - 12 + 0, 'text-anchor': 'end', dy: -14 }, s, 'bước train');
    el('line', { class: 'ref', x1: m.l, x2: W - m.r, y1: y(R.base_valid_flow), y2: y(R.base_valid_flow) }, s);
    el('text', { class: 'ref-label', x: m.l + 6, y: y(R.base_valid_flow) + 16 }, s, `bản base tốt nhất ${vi(R.base_valid_flow, 4)}`);
    el('path', { class: 'stable', d: path(R.curve.stable.filter((p) => p[0] <= R.best_step), x, y) }, s);
    el('path', { class: 'decay', d: path(R.curve.decay, x, y) }, s);
    const end = R.curve.decay[R.curve.decay.length - 1];
    el('circle', { class: 'dot-large', cx: x(end[0]), cy: y(end[1]), r: 5 }, s);
    el('text', { class: 'val', x: x(end[0]) - 4, y: y(end[1]) - 30, 'text-anchor': 'end' }, s, `large ${vi(end[1], 4)}`);
    el('text', { x: x(9000), y: y(0.0725) }, s, 'learning rate cố định');
  }

  // Three real and three generated windows, first 10 s each.
  function waves() {
    const W = 520, H = 300, rows = 3, gap = 8, top = 22;
    const s = svg('pg-waves', W, H, 'Ba đoạn PPG thật và ba đoạn do PPG-physiGPT vẽ');
    if (!s) return;
    const n = R.waves.fs * 10, colW = (W - gap) / 2, rowH = (H - top - gap * (rows - 1)) / rows;
    [['Thật (người chưa train)', R.waves.real, 'real', 0], ['PPG-physiGPT large', R.waves.generated, 'gen', colW + gap]].forEach(([title, set, cls, ox]) => {
      el('text', { class: 'lab', x: ox + 4, y: 14 }, s, title);
      set.slice(0, rows).forEach((w, r) => {
        const seg = w.slice(0, n), oy = top + r * (rowH + gap);
        el('rect', { x: ox, y: oy, width: colW, height: rowH, rx: 8, fill: 'none', class: 'axis' }, s);
        const pts = seg.map((v, i) => [i, v]);
        el('path', { class: cls, d: path(pts, (i) => ox + 6 + i / (n - 1) * (colW - 12), (v) => oy + 6 + (1 - v) * (rowH - 12)) }, s);
      });
    });
  }

  // 1 - KS per feature: base (open), large (filled), real-vs-real reference (tick); sorted by the large gap.
  function features() {
    const rows = [...R.features].sort((a, b) => (a.large - a.real) - (b.large - b.real));
    const W = 1000, rowH = 26, top = 30, left = 250, right = 120, H = top + rows.length * rowH + 30;
    const s = svg('pg-features', W, H, 'Độ giống từng đặc trưng của bản base, bản large và mốc người thật');
    if (!s) return;
    const lo = 0.85, hi = 1;
    const x = (v) => left + (Math.max(v, lo) - lo) / (hi - lo) * (W - left - right);
    [0.85, 0.9, 0.95, 1].forEach((v) => {
      el('line', { class: 'grid', x1: x(v), x2: x(v), y1: top - 8, y2: H - 26 }, s);
      el('text', { x: x(v), y: top - 14, 'text-anchor': 'middle' }, s, vi(v, 2));
    });
    el('text', { x: W - 4, y: top - 14, 'text-anchor': 'end' }, s, 'thiếu so với thật');
    rows.forEach((f, i) => {
      const cy = top + i * rowH + rowH / 2;
      const g = el('g', { class: 'row' }, s);
      el('title', {}, g, `${f.label}: large ${vi(f.large, 3)}, base ${vi(f.base, 3)}, người thật ${vi(f.real, 3)}`);
      el('rect', { class: 'hit', x: 0, y: cy - rowH / 2, width: W, height: rowH, rx: 6 }, g);
      el('text', { class: 'lab', x: left - 14, y: cy + 4, 'text-anchor': 'end' }, g, f.label);
      el('line', { class: 'span', x1: x(Math.min(f.base, f.large, f.real)), x2: x(Math.max(f.base, f.large, f.real)), y1: cy, y2: cy }, g);
      el('line', { class: 'tick-real', x1: x(f.real), x2: x(f.real), y1: cy - 9, y2: cy + 9 }, g);
      el('circle', { class: 'dot-base', cx: x(f.base), cy, r: 5 }, g);
      el('circle', { class: 'dot-large', cx: x(f.large), cy, r: 6 }, g);
      const gap = f.large - f.real;
      el('text', { class: gap < -0.02 ? 'gap' : '', x: W - 4, y: cy + 4, 'text-anchor': 'end' }, g, gap < 0 ? `−${vi(-gap, 3)}` : 'đạt');
    });
  }

  curve();
  waves();
  features();
  const rel = document.getElementById('pg-rel');
  if (rel) rel.textContent = `${vi(R.relative * 100, 1)} %`;
  const hours = document.getElementById('pg-hours');
  if (hours) hours.textContent = `${vi(R.hours, 1)} giờ`;
})();
