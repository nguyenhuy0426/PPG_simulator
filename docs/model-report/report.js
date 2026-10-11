// Renders the model report from window.REPORT (data.js). Plain DOM + SVG; no network, no libraries.
(function () {
  "use strict";
  const R = window.REPORT;
  // The chosen theme is applied before any chart reads its colours.
  try { const saved = sessionStorage.getItem("theme"); if (saved) document.documentElement.dataset.theme = saved; } catch (e) { /* storage unavailable */ }
  const NS = "http://www.w3.org/2000/svg";
  const NAMES = {
    gxu_finger: "GXU ngón tay", perform_large: "PERform Large", bidmc: "BIDMC",
    perform_af: "PERform AF", perform_non_af: "PERform không AF", wrist: "Cổ tay vận động",
  };
  const DATA_INFO = {
    gxu_finger: ["148 người khỏe mạnh, đo ở ngón tay khi nghỉ và sau gắng sức", "Li S. et al., Mendeley Data (2026) · CC BY 4.0"],
    perform_large: ["Bệnh nhân ICU người lớn, nhiều nhóm bệnh", "MIMIC PERform Large (Charlton et al.) · PhysioNet"],
    bidmc: ["53 bệnh nhân ICU (46 dùng), ngón tay", "Pimentel et al., BIDMC 1.0.0 · ODC-By 1.0"],
    perform_af: ["Bệnh nhân ICU đang rung nhĩ (AF)", "MIMIC PERform AF (Charlton et al.) · PhysioNet"],
    perform_non_af: ["Bệnh nhân ICU nhịp xoang, đối chứng của AF", "MIMIC PERform AF (Charlton et al.) · PhysioNet"],
    wrist: ["PPG cổ tay khi đi bộ, chạy, đạp xe (8 người)", "Jarchi & Casson, Wrist PPG During Exercise 1.0.0 · PhysioNet"],
  };
  const SHORT = { gxu_finger: "GXU", perform_large: "PERform L", bidmc: "BIDMC", perform_af: "AF", perform_non_af: "không AF", wrist: "Cổ tay" };
  const STATE_NAMES = {
    bidmc: "BIDMC", perform_af: "AF", perform_non_af: "không AF", perform_large: "PERform Large",
    gxu_rest: "GXU nghỉ", gxu_post_exercise: "GXU sau gắng sức", wrist_exercise: "Cổ tay vận động",
  };
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const pct = (v) => (v == null ? "—" : Math.round(100 * v) + "%");
  const fmt = (v, d = 0) => (v == null ? "—" : Number(v).toLocaleString("vi-VN", { maximumFractionDigits: d, minimumFractionDigits: d }));
  const $ = (id) => document.getElementById(id);
  const tip = $("tip");

  function el(name, attrs = {}, parent) {
    const node = document.createElementNS(NS, name);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    if (parent) parent.appendChild(node);
    return node;
  }
  function html(tag, text, parent, cls) {
    const node = document.createElement(tag);
    if (text != null) node.textContent = text;
    if (cls) node.className = cls;
    if (parent) parent.appendChild(node);
    return node;
  }
  function hover(node, text) {
    node.addEventListener("mousemove", (e) => {
      tip.textContent = text; tip.style.opacity = 1;
      tip.style.left = e.clientX + 12 + "px"; tip.style.top = e.clientY + 12 + "px";
    });
    node.addEventListener("mouseleave", () => { tip.style.opacity = 0; });
  }
  function clear(svg) { while (svg.firstChild) svg.removeChild(svg.firstChild); }
  // Charts draw in CSS pixels: the viewBox follows the rendered width, so text keeps its size.
  function box(svg) {
    if (!svg.dataset.h) svg.dataset.h = svg.getAttribute("viewBox").split(" ")[3];
    const h = Number(svg.dataset.h);
    const w = Math.max(300, Math.round(svg.getBoundingClientRect().width || 900));
    svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
    return { w, h, l: 48, r: w - 28, t: 14, b: h - 42 };
  }
  function axes(svg, b, x0, x1, y0, y1, xt, yt, xl, yl) {
    const X = (v) => b.l + ((v - x0) / (x1 - x0)) * (b.r - b.l);
    const Y = (v) => b.b - ((v - y0) / (y1 - y0)) * (b.b - b.t);
    yt.forEach((v) => {
      el("line", { x1: b.l, x2: b.r, y1: Y(v), y2: Y(v), class: "grid" }, svg);
      el("text", { x: b.l - 6, y: Y(v) + 4, "text-anchor": "end" }, svg).textContent = yl ? yl(v) : v;
    });
    xt.forEach((v) => {
      el("text", { x: X(v), y: b.b + 16, "text-anchor": "middle" }, svg).textContent = xl ? xl(v) : v;
    });
    el("line", { x1: b.l, x2: b.r, y1: b.b, y2: b.b, class: "axis" }, svg);
    return { X, Y };
  }
  function path(svg, pts, color, width = 1.6, extra = {}) {
    const d = pts.map(([x, y], i) => (i ? "L" : "M") + x.toFixed(1) + "," + y.toFixed(1)).join("");
    return el("path", { d, fill: "none", stroke: color, "stroke-width": width, "stroke-linejoin": "round", ...extra }, svg);
  }
  function segmented(container, items, current, onPick) {
    container.textContent = "";
    items.forEach(([key, label]) => {
      const b = html("button", label, container);
      b.type = "button";
      if (key === current) b.classList.add("on");
      b.addEventListener("click", () => {
        [...container.children].forEach((c) => c.classList.remove("on"));
        b.classList.add("on");
        onPick(key);
      });
    });
  }
  function legend(container, items) {
    container.textContent = "";
    items.forEach(([color, label]) => {
      const s = html("span", null, container);
      const i = html("i", null, s); i.style.background = color;
      s.appendChild(document.createTextNode(label));
    });
  }
  function card(parent, num, label) {
    const c = html("div", null, parent, "card stat");
    html("div", num, c, "num"); html("div", label, c, "lbl");
  }

  // Waveform strip: values 0..1 at fs, drawn over `seconds`.
  function waveform(svg, series, seconds, label) {
    clear(svg);
    const b = box(svg);
    const ticks = [...Array(seconds + 1).keys()].filter((s) => s % (seconds > 12 ? 5 : 1) === 0);
    const step = 1.3;  // vertical room per strip, leaving a band for its label
    const { X, Y } = axes(svg, b, 0, seconds, -0.05, series.length * step - 0.1, ticks, [], null, null);
    series.forEach((s, k) => {
      const off = (series.length - 1 - k) * step;
      const n = Math.min(s.values.length, Math.round(seconds * s.fs));
      const pts = [];
      for (let i = 0; i < n; i++) pts.push([X(i / s.fs), Y(s.values[i] + off)]);
      path(svg, pts, s.color, 1.6);
      if (s.label) el("text", { x: b.l + 4, y: Y(off + 1.12), fill: s.color, style: "font-weight:600" }, svg).textContent = s.label;
    });
    el("text", { x: b.r, y: b.b + 33, "text-anchor": "end" }, svg).textContent = label || "giây";
  }

  // ---------- header ----------
  const pm = R.physiomix;
  $("hero-meta").textContent = `Tạo lúc ${R.generated} · commit ${R.commit || "?"} · model trong app: ${pm.variant} (seed ${pm.seed}, bước ${pm.best_step})`;
  $("nav-meta").textContent = `PhysioMix ${pm.variant.replace("physiomix_", "")}`;
  const trainPeople = Object.values(R.datasets).reduce((a, d) => a + d.train.people, 0);
  const windows = Object.values(R.datasets).reduce((a, d) => a + d.train.windows + d.validation.windows + d.test.windows, 0);
  $("pm-people").textContent = fmt(trainPeople);
  const hero = $("hero-cards");
  card(hero, "5", "thành phần tạo / đọc nhịp (2 là AI)");
  card(hero, "6", "tập dữ liệu PPG công khai");
  card(hero, fmt(windows), "cửa sổ 30 s đã xử lý");
  card(hero, fmt(trainPeople), "người dùng để train");
  $("pm-variant").textContent = `${pm.variant} · seed ${pm.seed}`;
  const pc = $("pm-cards");
  card(pc, fmt(pm.parameters), "tham số");
  card(pc, fmt(pm.latency_ms, 1) + " ms", "sinh 30 s trên 1 luồng CPU laptop");
  card(pc, `${pm.hr_support[0]}–${pm.hr_support[1]}`, "bpm điều khiển được");
  $("pm-arch").textContent = `LSM-GAN để so sánh: ${fmt(R.lsm.parameters)} tham số, ${fmt(R.lsm.latency_ms, 1)} ms. Thời gian đo trên laptop x86; chưa đo trên Pi.`;
  $("footer-meta").textContent = `Dữ liệu trang: scripts/build_model_report.py · ${R.generated} · commit ${R.commit || "?"} · checksum model ${pm.sha256.slice(0, 12)}…`;

  // ---------- compare sources ----------
  const CMP = { real: ["Thật (BIDMC)", "--real"], classic: ["Classic", "--s4"], gaussian: ["Gaussian đã fit", "--s3"], lsm: ["LSM-GAN", "--s2"], physiomix: ["PhysioMix", "--s1"] };
  function drawCompare(pick) {
    const keys = pick === "all" ? ["real", "physiomix", "lsm", "gaussian", "classic"] : ["real", pick];
    const series = keys.map((k) => R.compare.find((c) => c.key === k)).filter((c) => c && c.values.length)
      .map((c) => ({ values: c.values, fs: c.fs, color: css(CMP[c.key][1]), label: CMP[c.key][0] }));
    $("cmp-chart").dataset.h = 60 + 78 * series.length;
    waveform($("cmp-chart"), series, 10);
    $("cmp-note").textContent = pick === "all" ? "Tất cả, 10 s" : `${CMP[pick][0]} cạnh dữ liệu thật`;
  }
  let cmpPick = "all";
  segmented($("cmp-seg"), [["all", "Tất cả"], ["physiomix", "PhysioMix"], ["lsm", "LSM-GAN"], ["gaussian", "Gaussian"], ["classic", "Classic"]], cmpPick, (k) => { cmpPick = k; drawCompare(k); });

  // ---------- HR explorer ----------
  const HR = Object.keys(pm.strips.bidmc).map(Number).sort((a, b) => a - b);
  let hrDomain = "bidmc";
  function drawHr() {
    const hr = HR[Number($("hr-range").value)];
    const s = pm.strips[hrDomain][String(hr)];
    waveform($("hr-chart"), [{ values: s.values, fs: 40, color: css("--s1"), label: `${NAMES[hrDomain]} · yêu cầu ${hr} bpm` }], 10);
    const out = hr < pm.data_support[0] || hr > pm.data_support[1] ? " · ngoài vùng dữ liệu train (ngoại suy)" : "";
    $("hr-read").textContent = `${hr} bpm → đo lại ${s.measured == null ? "không đo được" : fmt(s.measured) + " bpm"}${out}`;
  }
  $("hr-range").max = HR.length - 1;
  $("hr-range").addEventListener("input", drawHr);
  segmented($("hr-dom"), Object.keys(NAMES).map((k) => [k, NAMES[k]]), hrDomain, (k) => { hrDomain = k; drawHr(); });

  const DOM_COLORS = { gxu_finger: "--s2", perform_large: "--s4", bidmc: "--real", perform_af: "--s3", perform_non_af: "--rule", wrist: "--s1" };
  function drawControl() {
    const svg = $("ctrl-chart"); clear(svg);
    const b = box(svg);
    const { X, Y } = axes(svg, b, 35, 185, 30, 190, HR, [40, 70, 100, 130, 160, 190], (v) => v, (v) => v);
    path(svg, [[X(35), Y(35)], [X(185), Y(185)]], css("--line"), 1.5, { "stroke-dasharray": "5 5" });
    el("rect", { x: X(pm.data_support[1]), y: b.t, width: X(185) - X(pm.data_support[1]), height: b.b - b.t, fill: css("--soft"), opacity: 0.6 }, svg);
    el("text", { x: X(pm.data_support[1]) + 6, y: b.t + 14 }, svg).textContent = "ngoài vùng train";
    Object.entries(pm.control).forEach(([dom, rows]) => {
      const color = css(DOM_COLORS[dom]);
      const pts = rows.filter((r) => r.measured != null).map((r) => [X(r.requested), Y(r.measured)]);
      path(svg, pts, color, 2);
      rows.forEach((r) => {
        if (r.measured == null) return;
        const c = el("circle", { cx: X(r.requested), cy: Y(r.measured), r: 4, fill: color }, svg);
        hover(c, `${NAMES[dom]}: yêu cầu ${r.requested} → đo ${fmt(r.measured)} bpm (khoảng ${fmt(r.lo)}–${fmt(r.hi)})`);
      });
    });
    el("text", { x: b.r, y: b.b + 33, "text-anchor": "end" }, svg).textContent = "bpm yêu cầu";
    el("text", { x: b.l + 4, y: b.t + 4 }, svg).textContent = "bpm đo lại";
    legend($("ctrl-legend"), Object.keys(NAMES).map((k) => [css(DOM_COLORS[k]), NAMES[k]]));
  }

  // ---------- data ----------
  (function drawDataTable() {
    const body = document.querySelector("#data-table tbody");
    Object.keys(NAMES).forEach((dom) => {
      const d = R.datasets[dom], tr = html("tr", null, body);
      html("td", NAMES[dom], tr).style.fontWeight = 600;
      html("td", DATA_INFO[dom][0], tr);
      ["train", "validation", "test"].forEach((s) => (html("td", fmt(d[s].people), tr).className = "num"));
      html("td", fmt(d.train.windows + d.validation.windows + d.test.windows), tr).className = "num";
      html("td", DATA_INFO[dom][1], tr, "small muted");
    });
  })();
  function drawReal(dom) {
    const series = R.real[dom].map((s, i) => ({ values: s.values, fs: 40, color: css("--real"), label: `Người ${i + 1}${s.measured ? " · ≈" + fmt(s.measured) + " bpm" : ""}` }));
    waveform($("real-chart"), series, 10);
  }
  let realDomain = "bidmc";
  segmented($("real-dom"), Object.keys(NAMES).map((k) => [k, NAMES[k]]), realDomain, (k) => { realDomain = k; drawReal(k); });

  // ---------- training ----------
  function drawRounds() {
    const svg = $("rounds-chart"); clear(svg);
    const b = { ...box(svg), l: 44 };
    const rounds = R.rounds.concat(R.targeted || []);
    const { X, Y } = axes(svg, b, -0.5, rounds.length - 0.5, 0.4, 0.7, [], [0.4, 0.5, 0.6, 0.7], null, (v) => v.toFixed(1));
    rounds.forEach((r, i) => {
      const color = r.shipped ? css("--s1") : css("--s4");
      el("line", { x1: X(i), x2: X(i), y1: Y(r.S_arm - r.sd), y2: Y(r.S_arm + r.sd), stroke: color, "stroke-width": 2 }, svg);
      const c = el("circle", { cx: X(i), cy: Y(r.S_arm), r: 6, fill: color }, svg);
      const wrist = r.wrist_Q != null ? ` · cổ tay Q ${fmt(r.wrist_Q, 3)} (trước ${fmt(r.incumbent_wrist_Q, 3)})` : "";
      hover(c, `${r.round}: ${r.change} · S_arm ${fmt(r.S_arm, 3)} ± ${fmt(r.sd, 3)}${wrist}${r.shipped ? " · đưa vào app" : ""}`);
      el("text", { x: X(i), y: b.b + 16, "text-anchor": "middle" }, svg).textContent = r.round;
    });
    el("text", { x: b.l + 4, y: b.t + 4 }, svg).textContent = "tím = đã đưa vào app · xám = không";
    $("rounds-note").textContent = (R.targeted || []).map((r) => `${r.round} (${r.change}) được chấm theo quy tắc riêng cho cổ tay: Q validation cổ tay ${fmt(r.wrist_Q, 3)} so với ${fmt(r.incumbent_wrist_Q, 3)}, chênh ${fmt(r.gap, 3)} ${r.gap > r.pooled_sd ? ">" : "<"} SD gộp ${fmt(r.pooled_sd, 3)} → ${r.shipped ? "đưa vào app" : "giữ model cũ"}; S_arm chỉ cần không kém hơn quá SD gộp.`).join(" ");
  }
  function drawTraining() {
    const svg = $("train-chart"); clear(svg);
    const b = box(svg);
    const seeds = Object.keys(R.training);
    const all = seeds.flatMap((s) => R.training[s]);
    const maxStep = Math.max(...all.map((p) => p.step));
    const lo = Math.min(...all.map((p) => p.score)), hi = Math.max(...all.map((p) => p.score));
    const ticks = [0, 5000, 10000, 15000, 20000].filter((v) => v <= maxStep);
    const { X, Y } = axes(svg, b, 0, maxStep, lo - 0.02, hi + 0.02, ticks, [lo, (lo + hi) / 2, hi].map((v) => +v.toFixed(2)), (v) => fmt(v), (v) => v.toFixed(2));
    const colors = [css("--s1"), css("--s2"), css("--s3")];
    seeds.forEach((s, i) => {
      const pts = R.training[s].map((p) => [X(p.step), Y(p.score)]);
      path(svg, pts, colors[i % 3], 1.8);
      const best = R.training[s].reduce((a, p) => (p.score < a.score ? p : a));
      const c = el("circle", { cx: X(best.step), cy: Y(best.score), r: 5, fill: colors[i % 3] }, svg);
      hover(c, `seed ${s}: tốt nhất ở bước ${fmt(best.step)} (điểm ${best.score.toFixed(3)})`);
    });
    el("text", { x: b.r, y: b.b + 33, "text-anchor": "end" }, svg).textContent = "bước train";
    legend($("train-legend"), seeds.map((s, i) => [colors[i % 3], `seed ${s}${Number(s) === pm.seed ? " (trong app)" : ""}`]));
  }

  // ---------- realism ----------
  const SOURCES = [["real_other_people", "Thật · người khác (trần)", "--real"], ["app", "PhysioMix (app)", "--s1"], ["round7", "PhysioMix vòng 7 (trước)", "--s4"], ["gaussian_shaper", "Gaussian cũ", "--s3"]];
  function drawBars(metric) {
    const svg = $("real-bars"); clear(svg);
    const b = box(svg);
    const doms = Object.keys(NAMES).filter((d) => R.realism[d]);
    const { Y } = axes(svg, b, 0, 1, 0, 1, [], [0, 0.25, 0.5, 0.75, 1], null, (v) => Math.round(v * 100) + "%");
    const group = (b.r - b.l) / doms.length, bw = Math.min(30, (group - 24) / SOURCES.length);
    doms.forEach((d, i) => {
      const x0 = b.l + i * group + (group - bw * SOURCES.length) / 2;
      SOURCES.forEach(([key, label, color], k) => {
        const v = R.realism[d][key] && R.realism[d][key][metric];
        if (v == null) return;
        const r = el("rect", { x: x0 + k * bw, y: Y(v), width: bw - 3, height: Math.max(1, Y(0) - Y(v)), rx: 3, fill: css(color) }, svg);
        hover(r, `${NAMES[d]} · ${label}: ${pct(v)}`);
        if (bw >= 22) el("text", { x: x0 + k * bw + (bw - 3) / 2, y: Y(v) - 4, "text-anchor": "middle", style: "font-size:10px" }, svg).textContent = pct(v);
      });
      const cx = b.l + i * group + group / 2;
      el("text", { x: cx, y: b.b + 16, "text-anchor": "middle", style: "font-weight:600" }, svg).textContent = SHORT[d];
      el("text", { x: cx, y: b.b + 30, "text-anchor": "middle" }, svg).textContent = `${R.realism[d].people} người`;
    });
    legend($("bars-legend"), SOURCES.map(([, label, color]) => [css(color), label]));
  }
  (function tradeoff() {
    const box = $("tradeoff");
    const doms = Object.keys(NAMES).filter((d) => R.realism[d] && R.realism[d].app && R.realism[d].round7);
    if (!doms.length) { box.remove(); return; }
    html("b", "Đánh đổi của model hiện tại so với vòng 7 (người chưa dùng): ", box);
    box.appendChild(document.createTextNode(doms.map((d) => {
      const a = R.realism[d].app, o = R.realism[d].round7;
      return `${SHORT[d]} độ phủ ${pct(o.coverage)}→${pct(a.coverage)}, không phân biệt được ${pct(o.indistinguishable)}→${pct(a.indistinguishable)}`;
    }).join("; ") + ". Cổ tay tốt lên rõ; các tập khác bị CNN tách thật/giả nhận ra dễ hơn. Quy tắc chọn (chỉ dùng validation) chấp nhận đánh đổi này vì điểm tổng S_arm vẫn trong độ lệch chuẩn giữa các seed."));
  })();
  let metric = "indistinguishable";
  segmented($("metric-seg"), [["fidelity", "Độ giống"], ["coverage", "Độ phủ"], ["indistinguishable", "Không phân biệt được"]], metric, (k) => { metric = k; drawBars(k); });

  // ---------- states ----------
  (function drawStates() {
    const cols = [["real_unseen", "Thật (người chưa dùng)"], ["app", "PhysioMix (app)"], ["round7", "Vòng 7 (trước)"], ["gaussian_shaper", "Gaussian cũ"]].filter(([k]) => R.following[k]);
    const head = document.querySelector("#state-table thead"), body = document.querySelector("#state-table tbody");
    const hr = html("tr", null, head);
    html("th", "Trạng thái yêu cầu", hr);
    cols.forEach(([, l]) => (html("th", l, hr).className = "num"));
    R.states.forEach((s) => {
      const tr = html("tr", null, body);
      html("td", STATE_NAMES[s] || s, tr);
      cols.forEach(([k]) => {
        const f = R.following[k];
        html("td", `${pct(f.accuracy[s])} · ${pct(f.motion[s])}`, tr).className = "num";
      });
    });
    const tr = html("tr", null, body);
    html("td", "Trung bình 7 trạng thái (đoán mò 14%)", tr).style.fontWeight = 600;
    cols.forEach(([k]) => (html("td", pct(R.following[k].balanced), tr).className = "num"));
    const f = R.following.app;
    $("swap-text").textContent = `Giữ nguyên nhiễu z, chỉ đổi lệnh trạng thái: ${pct(f.swap)} mẫu được CNN gọi đúng trạng thái mới, và mỗi nhiễu cho trung bình ${fmt(f.distinct, 1)}/7 câu trả lời khác nhau. Nếu model bỏ qua lệnh, mỗi nhiễu chỉ cho 1 câu trả lời. Vậy lệnh quyết định kiểu tín hiệu; nhiễu chỉ tạo khác biệt giữa các lần sinh (như người khác nhau).`;
  })();

  // ---------- RX ----------
  function drawRx() {
    const svg = $("rx-chart"); clear(svg);
    const b = box(svg);
    const { X, Y } = axes(svg, b, 30, 190, 30, 190, [40, 80, 120, 160], [40, 80, 120, 160], (v) => v, (v) => v);
    path(svg, [[X(30), Y(30)], [X(190), Y(190)]], css("--line"), 1.5, { "stroke-dasharray": "5 5" });
    R.rx.regular.forEach((r) => {
      if (r.measured == null) return;
      const c = el("circle", { cx: X(r.requested), cy: Y(r.measured), r: 5, fill: css("--rule") }, svg);
      hover(c, `phát ${r.requested} bpm → Nhịp RX ${fmt(r.measured, 1)} bpm`);
    });
    el("text", { x: b.r, y: b.b + 33, "text-anchor": "end" }, svg).textContent = "bpm trong tín hiệu";
    el("text", { x: b.l + 4, y: b.t + 4 }, svg).textContent = "Nhịp RX";
  }
  const rc = $("rx-cards");
  card(rc, pct(R.rx.noise_false_rate), "nhiễu thuần bị báo nhầm ra nhịp (200 mẫu)");
  card(rc, pct(R.rx.irregular_rated["0.2"]), "nhịp không đều (CV≈0,2) có số; còn lại báo “không rõ”");
  card(rc, pct(R.rx.irregular_rated["0.3"]), "nhịp rất không đều (CV≈0,3) có số");

  // ---------- nav + theme ----------
  const links = [...document.querySelectorAll("nav.toc a")];
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((e) => {
      if (e.isIntersecting) links.forEach((a) => a.classList.toggle("active", a.getAttribute("href") === "#" + e.target.id));
    });
  }, { rootMargin: "-30% 0px -60% 0px" });
  document.querySelectorAll("main section").forEach((s) => observer.observe(s));
  $("theme").addEventListener("click", () => {
    const root = document.documentElement;
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    try { sessionStorage.setItem("theme", root.dataset.theme); } catch (e) { /* storage unavailable */ }
    location.reload();  // charts take their colours when drawn
  });
  function drawAll() {
    drawCompare(cmpPick); drawHr(); drawControl(); drawReal(realDomain); drawRounds(); drawTraining(); drawBars(metric); drawRx();
  }
  let pending = null;
  window.addEventListener("resize", () => { cancelAnimationFrame(pending); pending = requestAnimationFrame(drawAll); });
  drawAll();
})();
