// Interactive figures of trinh-bay.html, drawn from window.PRES (media/presentation.js). No external libraries.
(() => {
  const P = window.PRES;
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const $ = (id) => document.getElementById(id);

  // One or more series on a canvas; series = [{y, color, width, dash}], x spacing 1/fs seconds.
  function plot(canvas, series, opt = {}) {
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth, h = canvas.clientHeight;
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    const g = canvas.getContext('2d');
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    const pad = { l: 8, r: 8, t: 8, b: opt.axis ? 20 : 8 };
    let lo = Infinity, hi = -Infinity;
    series.forEach((s) => s.y.forEach((v) => { if (v < lo) lo = v; if (v > hi) hi = v; }));
    if (opt.lo !== undefined) lo = opt.lo;
    if (opt.hi !== undefined) hi = opt.hi;
    const span = hi - lo || 1;
    const n = Math.max(...series.map((s) => s.y.length));
    const X = (i) => pad.l + (w - pad.l - pad.r) * i / Math.max(n - 1, 1);
    const Y = (v) => pad.t + (h - pad.t - pad.b) * (1 - (v - lo) / span);
    if (opt.axis) {
      g.fillStyle = css('--muted'); g.font = '11px system-ui, sans-serif';
      const seconds = n / (opt.fs || P.fs);
      for (let s = 0; s <= seconds; s += opt.tick || 2) {
        g.fillText(s + ' s', X(s * (opt.fs || P.fs)) - 6, h - 5);
      }
    }
    series.forEach((s) => {
      g.beginPath();
      g.lineWidth = s.width || 1.6; g.strokeStyle = s.color; g.setLineDash(s.dash || []);
      s.y.forEach((v, i) => (i ? g.lineTo(X(i), Y(v)) : g.moveTo(X(i), Y(v))));
      g.stroke();
    });
    g.setLineDash([]);
  }

  // ---- PhysioMix: one forward pass, stage by stage
  const MIX_STAGES = [
    { key: 'noise', title: '1 · Đầu vào: nhiễu ngẫu nhiên z + lệnh', text: 'Mạng nhận 1200 số ngẫu nhiên (z) và lệnh: kiểu người (ở đây ngón tay), nhịp 72 nhịp/phút, độ không đều, biên độ. Nhiễu giúp mỗi lần vẽ ra một sóng khác nhau.' },
    { key: 'phase', title: '2 · Dựng nhịp tim', text: 'Từ nhịp và độ không đều, mạng dựng dãy thời điểm các nhịp đập (khoảng cách giữa các nhịp dao động nhẹ như người thật). Đường răng cưa là “đang ở đâu trong nhịp” (0 → 1).' },
    { key: 'harmonics', title: '3 · Sáu sóng sin hài', text: 'Mỗi nhịp được ghép từ 6 sóng sin (tần số 1×, 2×, … 6× nhịp tim). Mạng nơ-ron học biên độ và pha của từng sóng: chính là “hình dạng” của một nhịp mạch.' },
    { key: 'pulse', title: '4 · Ghép thành nhịp mạch', text: 'Cộng 6 sóng hài lại, nhân với độ mạnh của từng nhịp (nhịp đến sau quãng nghỉ dài thì mạnh hơn một chút).' },
    { key: 'residual', title: '5 · Mạng TCN thêm chi tiết', text: '8 khối tích chập giãn (TCN, nhìn được tới ~6 giây) thêm phần chi tiết nhỏ mà 6 sóng sin không tả được. Phần này bị giới hạn ở ±0,15 để không lấn át nhịp mạch.' },
    { key: 'summed', title: '6 · Cộng tất cả (+ chuyển động)', text: 'Nhịp mạch + chi tiết + một thành phần chuyển động (cổ tay vung khi đi/chạy; với ngón tay khi nghỉ gần như bằng 0).' },
    { key: 'output', title: '7 · Lọc 0,5–8 Hz và chuẩn hoá', text: 'Lọc giống hệt cách đã lọc dữ liệu thật, đưa về khoảng 0–1. Đây là sóng gửi tới DAC/LED.' },
  ];
  function drawMix(i) {
    const s = MIX_STAGES[i], m = P.physiomix;
    $('mix-title').textContent = s.title; $('mix-text').textContent = s.text;
    $('mix-step').value = i;
    const palette = [css('--s1'), css('--s2'), css('--s3'), css('--s5'), css('--s4'), css('--ai')];
    let series;
    if (s.key === 'harmonics') series = m.harmonics.map((y, k) => ({ y, color: palette[k % palette.length], width: 1.2 }));
    else series = [{ y: m[s.key], color: s.key === 'output' ? css('--accent') : css('--ai'), width: s.key === 'noise' ? .8 : 1.8 }];
    plot($('mix-canvas'), series, { axis: true });
    document.querySelectorAll('#mix-dots button').forEach((b, k) => b.classList.toggle('on', k === i));
  }

  // ---- PhysioFlow: noise -> waveform over the Heun steps
  let flowTimer = null;
  function drawFlow(i) {
    const f = P.physioflow.frames[i], n = P.physioflow.frames.length - 1;
    $('flow-step').value = i;
    $('flow-label').textContent = i === n ? `Xong: sóng hoàn chỉnh (bước ${n}/${n})` : `Bước ${i}/${n} · độ nhiễu còn lại t = ${f.t.toFixed(2)}`;
    plot($('flow-canvas'), [{ y: f.x, color: css('--s2'), width: 1.2 }], { axis: true });
    plot($('flow-clean'), [{ y: f.clean, color: css('--accent'), width: 1.8 }], { axis: true });
  }
  function playFlow() {
    const btn = $('flow-play');
    if (flowTimer) { clearInterval(flowTimer); flowTimer = null; btn.textContent = '▶ Chạy'; return; }
    btn.textContent = '❚❚ Dừng';
    let i = 0; drawFlow(0);
    flowTimer = setInterval(() => {
      i += 1;
      if (i >= P.physioflow.frames.length) { clearInterval(flowTimer); flowTimer = null; btn.textContent = '▶ Chạy'; return; }
      drawFlow(i);
    }, 450);
  }

  // ---- Critic: score histogram real vs generated
  function drawCritic() {
    const c = P.critic, canvas = $('critic-canvas');
    if (!canvas) return;
    const all = c.real.concat(c.fake), lo = Math.min(...all), hi = Math.max(...all), bins = 16;
    const hist = (v) => { const h = new Array(bins).fill(0); v.forEach((x) => { h[Math.min(bins - 1, Math.floor((x - lo) / (hi - lo + 1e-9) * bins))] += 1; }); return h; };
    const hr = hist(c.real), hf = hist(c.fake), top = Math.max(...hr, ...hf);
    const dpr = window.devicePixelRatio || 1, w = canvas.clientWidth, h = canvas.clientHeight;
    canvas.width = w * dpr; canvas.height = h * dpr;
    const g = canvas.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, h);
    const bw = (w - 20) / bins;
    [[hr, css('--real'), 0], [hf, css('--ai'), bw / 2]].forEach(([hh, color, off]) => {
      g.fillStyle = color; g.globalAlpha = .75;
      hh.forEach((v, k) => { const bh = (h - 30) * v / top; g.fillRect(10 + k * bw + off, h - 20 - bh, bw / 2 - 1, bh); });
    });
    g.globalAlpha = 1; g.fillStyle = css('--muted'); g.font = '11px system-ui, sans-serif';
    g.fillText('điểm thấp = “giả”', 10, h - 5); g.fillText('điểm cao = “thật”', w - 100, h - 5);
    const auc = c.real.reduce((s, r) => s + c.fake.reduce((t, f) => t + (r > f ? 1 : r === f ? .5 : 0), 0), 0) / (c.real.length * c.fake.length);
    $('critic-auc').textContent = (auc * 100).toFixed(0) + '%';
  }

  // ---- Training snapshots
  const DOMAIN_VI = { gxu_finger: 'ngón tay', wrist: 'cổ tay khi tập', wrist_daily: 'cổ tay đời thường' };
  function drawSnap() {
    const name = $('snap-model').value, snap = P.snapshots[name], i = +$('snap-step').value;
    $('snap-step').max = snap.steps.length - 1;
    $('snap-label').textContent = `Bước train ${snap.steps[i].toLocaleString('vi-VN')} / ${snap.steps[snap.steps.length - 1].toLocaleString('vi-VN')}`;
    const box = $('snap-panels');
    if (box.children.length !== snap.domains.length) {
      box.innerHTML = '';
      snap.domains.forEach((d) => {
        const fig = document.createElement('figure');
        const cap = document.createElement('figcaption'); cap.textContent = DOMAIN_VI[d] || d;
        const cv = document.createElement('canvas'); cv.className = 'wave short';
        fig.append(cap, cv); box.append(fig);
      });
    }
    snap.domains.forEach((d, k) => plot(box.children[k].querySelector('canvas'), [{ y: snap.signals[i][k], color: css('--ai'), width: 1.6 }], { axis: true, tick: 2 }));
    if (snap.curve) {
      const step = snap.steps[i];
      const ys = snap.curve.map((r) => r.S_real + .5 * r.C);
      plot($('snap-curve'), [{ y: ys, color: css('--s3'), width: 1.8 }], {});
      const done = snap.curve.filter((r) => r.step <= step).length;
      $('snap-curve-label').textContent = done ? `Điểm chọn checkpoint (thấp = tốt) tại bước ${snap.curve[done - 1].step}: ${ys[done - 1].toFixed(3)}` : 'Điểm validation bắt đầu được tính từ bước 1000';
    }
  }
  let snapTimer = null;
  function playSnap() {
    const btn = $('snap-play');
    if (snapTimer) { clearInterval(snapTimer); snapTimer = null; btn.textContent = '▶ Chạy'; return; }
    btn.textContent = '❚❚ Dừng';
    const s = $('snap-step');
    s.value = 0; drawSnap();
    snapTimer = setInterval(() => {
      if (+s.value >= +s.max) { clearInterval(snapTimer); snapTimer = null; btn.textContent = '▶ Chạy'; return; }
      s.value = +s.value + 1; drawSnap();
    }, 220);
  }

  function init() {
    if (!P) return;
    const dots = $('mix-dots');
    MIX_STAGES.forEach((s, k) => {
      const b = document.createElement('button'); b.type = 'button'; b.textContent = k + 1;
      b.setAttribute('aria-label', s.title); b.addEventListener('click', () => drawMix(k)); dots.append(b);
    });
    $('mix-step').max = MIX_STAGES.length - 1;
    $('mix-step').addEventListener('input', (e) => drawMix(+e.target.value));
    $('mix-prev').addEventListener('click', () => drawMix(Math.max(0, +$('mix-step').value - 1)));
    $('mix-next').addEventListener('click', () => drawMix(Math.min(MIX_STAGES.length - 1, +$('mix-step').value + 1)));
    plot($('real-canvas'), [{ y: P.real_example, color: css('--real'), width: 1.6 }], { axis: true });
    $('flow-step').max = P.physioflow.frames.length - 1;
    $('flow-step').addEventListener('input', (e) => drawFlow(+e.target.value));
    $('flow-play').addEventListener('click', playFlow);
    const names = Object.keys(P.snapshots || {});
    if (names.length) {
      const sel = $('snap-model');
      names.forEach((n) => { const o = document.createElement('option'); o.value = n; o.textContent = n; sel.append(o); });
      sel.addEventListener('change', () => { $('snap-step').value = 0; $('snap-panels').innerHTML = ''; drawSnap(); });
      $('snap-step').addEventListener('input', drawSnap);
      $('snap-play').addEventListener('click', playSnap);
      $('snap-box').hidden = false; $('snap-missing').hidden = true;
    }
    const redraw = () => { drawMix(+$('mix-step').value); drawFlow(+$('flow-step').value); drawCritic(); if (names.length) drawSnap(); plot($('real-canvas'), [{ y: P.real_example, color: css('--real'), width: 1.6 }], { axis: true }); };
    redraw();
    window.addEventListener('resize', redraw);
    $('theme').addEventListener('click', () => setTimeout(redraw, 0));
  }
  document.addEventListener('DOMContentLoaded', init);
})();
