// Renders gan-report.html from window.GAN_REPORT (gan-data.js, scripts/build_gan_report.py). Plain DOM + SVG.
(function () {
  "use strict";
  const R = window.GAN_REPORT;
  try { const saved = sessionStorage.getItem("theme"); if (saved) document.documentElement.dataset.theme = saved; } catch (e) { /* storage unavailable */ }
  const NS = "http://www.w3.org/2000/svg";
  const $ = (id) => document.getElementById(id);
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const fmt = (v, d = 3) => (v == null ? "—" : Number(v).toLocaleString("vi-VN", { maximumFractionDigits: d, minimumFractionDigits: d }));
  const tip = $("tip");
  const INC = "L3_rel_beat_lr_crop_r1w_motion_dom";
  const ROUNDS = { strict: "Vòng giám khảo nghiêm", flowgan: "Vòng PhysioFlow-GAN" };
  const SLOTS = { physiomix: "Khe PhysioMix · 6 miền, có điều kiện", lsm: "Khe LSM-GAN · BIDMC" };
  const SPLIT = { validation: "Validation (người chưa thấy, dùng để chọn)", test: "Test (người chưa thấy, mở một lần)" };
  const PURPLE = "rgba(124, 58, 237, 0.20)";
  const COLOR = {
    real: "--real", real_other_people: "--s4", physiomix_app: "--s3", lsm_app: "--hw", physioflow_app: "--s2",
    physioflow_sensor: "--rule", [INC + "_strict"]: "--warn", [INC + "_strict_quiet"]: "--bad",
    lsm_author_v3: "--s5", lsm_strict: "--warn", G1_flowgan: "--ai", G2_flowgan_lsm_bidmc: "--ai",
  };
  const group = (name) => { const m = /^(.+)_seed(\d+)$/.exec(name); return m ? m[1] : name; };
  const seedOf = (name) => { const m = /_seed(\d+)$/.exec(name); return m ? m[1] : null; };
  const colorOf = (name) => css(COLOR[group(name)] || "--accent");

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
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
  function box(svg, l = 48, b = 42) {
    if (!svg.dataset.h) svg.dataset.h = svg.getAttribute("viewBox").split(" ")[3];
    const h = Number(svg.dataset.h);
    const w = Math.max(280, Math.round(svg.getBoundingClientRect().width || 900));
    svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
    return { w, h, l, r: w - 16, t: 14, b: h - b };
  }
  function axes(svg, bx, x0, x1, y0, y1, xt, yt, xl, yl) {
    const X = (v) => bx.l + ((v - x0) / (x1 - x0)) * (bx.r - bx.l);
    const Y = (v) => bx.b - ((v - y0) / (y1 - y0)) * (bx.b - bx.t);
    yt.forEach((v) => {
      el("line", { x1: bx.l, x2: bx.r, y1: Y(v), y2: Y(v), class: "grid" }, svg);
      el("text", { x: bx.l - 6, y: Y(v) + 4, "text-anchor": "end" }, svg).textContent = yl ? yl(v) : v;
    });
    xt.forEach((v) => { el("text", { x: X(v), y: bx.b + 16, "text-anchor": "middle" }, svg).textContent = xl ? xl(v) : v; });
    el("line", { x1: bx.l, x2: bx.r, y1: bx.b, y2: bx.b, class: "axis" }, svg);
    return { X, Y };
  }
  function line(svg, pts, color, width = 1.6, extra = {}) {
    const d = pts.map(([x, y], i) => (i ? "L" : "M") + x.toFixed(1) + "," + y.toFixed(1)).join("");
    return el("path", { d, fill: "none", stroke: color, "stroke-width": width, "stroke-linejoin": "round", ...extra }, svg);
  }
  function segmented(container, items, current, onPick) {
    clear(container);
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
    clear(container);
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
  function missing(node, text) { clear(node); html("p", text, node, "callout"); }
  const ticks = (lo, hi, n) => { const s = (hi - lo) / n; return [...Array(n + 1).keys()].map((i) => +(lo + i * s).toFixed(6)); };

  // A 30 s strip, values 0..1 at fs, with artifact spans shaded purple.
  function strip(svg, values, spans, color, title) {
    clear(svg);
    const bx = box(svg, 34, 30);
    const fs = R.pack.fs, seconds = values.length / fs;
    const { X, Y } = axes(svg, bx, 0, seconds, -0.05, 1.05, [0, 5, 10, 15, 20, 25], [], null, null);
    (spans || []).forEach(([a, b]) => el("rect", { x: X(a), y: bx.t, width: Math.max(1, X(b) - X(a)), height: bx.b - bx.t, fill: PURPLE }, svg));
    line(svg, values.map((v, i) => [X(i / fs), Y(v)]), color, 1.2);
    el("text", { x: (bx.l + bx.r) / 2, y: 11, "text-anchor": "middle", style: "font-weight:600" }, svg).textContent = title;
    el("text", { x: bx.r, y: bx.b + 27, "text-anchor": "end" }, svg).textContent = "Thời gian (giây)";
    el("text", { x: 10, y: (bx.t + bx.b) / 2, transform: `rotate(-90 10 ${(bx.t + bx.b) / 2})`, "text-anchor": "middle" }, svg).textContent = "Biên độ";
  }

  // Grouped bars with optional error bars. groups: [label]; series: [{name, color, values:[v], err:[e]}].
  function bars(svg, groups, series, opts = {}) {
    clear(svg);
    const bx = box(svg, 52, opts.bottom || 46);
    const y0 = opts.y0 ?? 0, y1 = opts.y1 ?? Math.max(1e-9, ...series.flatMap((s) => s.values.map((v, i) => (v ?? 0) + ((s.err && s.err[i]) || 0)))) * 1.12;
    const { X, Y } = axes(svg, bx, 0, groups.length, y0, y1, [], opts.yticks || ticks(y0, y1, 5), null, opts.yl);
    const slot = (bx.r - bx.l) / groups.length, inner = slot * 0.8, w = inner / series.length;
    groups.forEach((g, gi) => {
      el("text", { x: X(gi + 0.5), y: bx.b + 16, "text-anchor": "middle" }, svg).textContent = g;
      series.forEach((s, si) => {
        const v = s.values[gi];
        if (v == null) return;
        const x = X(gi) + slot * 0.1 + si * w;
        const top = Y(Math.max(v, y0));
        const rect = el("rect", { x: x + 1, y: Math.min(top, Y(y0)), width: Math.max(1, w - 2), height: Math.abs(Y(y0) - top), fill: s.color, rx: 2 }, svg);
        const e = s.err ? s.err[gi] : null;
        hover(rect, `${s.name} · ${g}: ${fmt(v, opts.digits ?? 3)}${e ? " ± " + fmt(e, opts.digits ?? 3) : ""}`);
        if (e) {
          const cx = x + w / 2;
          line(svg, [[cx, Y(Math.min(y1, v + e))], [cx, Y(Math.max(y0, v - e))]], css("--ink"), 1.1);
          [v + e, v - e].forEach((t) => { if (t <= y1 && t >= y0) line(svg, [[cx - 3, Y(t)], [cx + 3, Y(t)]], css("--ink"), 1.1); });
        }
        if (opts.labels) el("text", { x: x + w / 2, y: top - 4, "text-anchor": "middle", style: "font-size:10px" }, svg).textContent = fmt(v, opts.digits ?? 0);
      });
    });
    if (opts.ref != null) line(svg, [[bx.l, Y(opts.ref)], [bx.r, Y(opts.ref)]], css("--ink"), 1, { "stroke-dasharray": "5 4" });
    if (opts.ylabel) el("text", { x: 12, y: (bx.t + bx.b) / 2, transform: `rotate(-90 12 ${(bx.t + bx.b) / 2})`, "text-anchor": "middle" }, svg).textContent = opts.ylabel;
  }

  // ---------- header ----------
  $("hero-meta").textContent = `Tạo lúc ${R.generated} · commit ${R.commit || "?"} · dữ liệu v3 ${R.pack.windows_sha256.slice(0, 12)}…`;
  $("footer-meta").textContent = `Dữ liệu trang: scripts/build_gan_report.py · ${R.generated} · vòng strict: ${R.strict ? R.strict.folder : "chưa có"} · vòng PhysioFlow-GAN: ${R.flowgan ? R.flowgan.folder : "chưa có"}`;
  const rounds = Object.keys(ROUNDS).filter((k) => R[k]);

  function entries(round, split, slot, kind = "strict") {
    const s = R[round] && R[round].splits[split] && R[round].splits[split][slot];
    return s && s[kind] ? s[kind] : null;
  }
  (function hero() {
    const cards = $("hero-cards");
    const total = R.table1.rows.reduce((a, d) => a + d.train.windows + d.validation.windows + d.test.windows, 0);
    card(cards, fmt(total, 0), "cửa sổ PPG 30 s (6 miền)");
    for (const round of rounds) {
      for (const slot of Object.keys(SLOTS)) {
        const e = entries(round, "validation", slot);
        if (!e) continue;
        const best = Object.entries(e).filter(([, v]) => v.kind !== "null").sort((a, b) => a[1].auc - b[1].auc)[0];
        card(cards, fmt(best[1].auc, 3), `AUC thấp nhất · ${SLOTS[slot].split(" · ")[0]} · ${ROUNDS[round]}: ${best[1].label}`);
      }
    }
    if (!rounds.length) card(cards, "—", "chưa có kết quả chấm");
  })();

  // ---------- decisions ----------
  (function decisions() {
    const box_ = $("decision-box");
    clear(box_);
    if (R.strict) {
      const d = R.strict.decision;
      const p = html("div", null, box_, "card");
      html("h3", ROUNDS.strict, p).style.marginTop = 0;
      const ul = html("ul", null, p, "small");
      html("li", `PhysioMix: ${d.physiomix.winner ? "thay bằng " + d.physiomix.winner : "giữ model trong app"} (AUC app ${fmt(d.physiomix.app_auc)}; đối chứng null ${fmt(d.physiomix.null_control.auc)} ${d.physiomix.null_control.valid ? "hợp lệ" : "KHÔNG hợp lệ"}).`, ul);
      Object.entries(d.physiomix.arms).forEach(([arm, v]) => {
        const failed = Object.entries(v.checks).filter(([, ok]) => !ok).map(([k]) => k);
        html("li", `${arm.replace(INC, "R9")}: AUC ${fmt(v.mean_auc)} (biên cần vượt ${fmt(v.margin)}), S_real ${fmt(v.S_real)}, C ${fmt(v.C)} → ${v.ship ? "đạt" : "không đạt: " + failed.join(", ")}`, ul);
      });
      html("li", `LSM-GAN: ${d.lsm.winner ? "thay bằng " + d.lsm.winner : "giữ model trong app"} (AUC app ${fmt(d.lsm.app_auc)}; ứng viên ${d.lsm.candidate} ${fmt(d.lsm.arms[d.lsm.candidate].mean_auc)}; null ${fmt(d.lsm.null_control.auc)}).`, ul);
    }
    if (R.flowgan) {
      const d = R.flowgan.decision;
      const p = html("div", null, box_, "card");
      html("h3", ROUNDS.flowgan, p).style.marginTop = 0;
      const ul = html("ul", null, p, "small");
      for (const slot of Object.keys(SLOTS)) {
        const v = d[slot];
        const failed = Object.entries(v.checks).filter(([, ok]) => !ok).map(([k]) => k);
        html("li", `${SLOTS[slot]}: ${v.arm} AUC ${fmt(v.mean_auc)} so với app ${fmt(v.app_auc)} (biên ${fmt(v.margin)}), C ${fmt(v.C)}, null ${fmt(v.null_control.auc)} → ${v.winner ? "THẮNG, seed " + v.ship_seed : "không thắng: " + failed.join(", ")}`, ul);
      }
    }
    if (!R.strict && !R.flowgan) missing(box_, "Chưa có quyết định: các vòng chấm chưa chạy xong.");
  })();

  // ---------- Table I ----------
  (function table1() {
    const t = $("table1");
    const head = html("tr", null, html("thead", null, t));
    ["Miền", "Nguồn dữ liệu", "Người train", "Người val", "Người test", "Cửa sổ train", "Cửa sổ val", "Cửa sổ test", "% train", "HR trung vị", "% AF"]
      .forEach((h, i) => html("th", h, head, i > 1 ? "num" : null));
    const body = html("tbody", null, t);
    R.table1.rows.forEach((d) => {
      const tr = html("tr", null, body);
      html("td", `${d.name} (${d.setting})`, tr);
      html("td", d.source, tr, "small");
      [d.train.people, d.validation.people, d.test.people, d.train.windows, d.validation.windows, d.test.windows].forEach((v) => html("td", fmt(v, 0), tr, "num"));
      html("td", fmt(d.train.share, 1) + "%", tr, "num");
      html("td", d.hr_median == null ? "—" : fmt(d.hr_median, 0), tr, "num");
      html("td", d.af_share == null ? "—" : fmt(d.af_share, 0) + "%", tr, "num");
    });
    const tr = html("tr", null, body);
    html("td", "Tổng", tr).style.fontWeight = 600; html("td", "", tr);
    const sum = (s, k) => R.table1.rows.reduce((a, d) => a + d[s][k], 0);
    ["train", "validation", "test"].forEach((s) => html("td", fmt(sum(s, "people"), 0), tr, "num"));
    ["train", "validation", "test"].forEach((s) => html("td", fmt(sum(s, "windows"), 0), tr, "num"));
    html("td", "100%", tr, "num"); html("td", "", tr); html("td", "", tr);
    // Judge sets actually used (sets.json of each round).
    const j = $("table1-judge");
    clear(j);
    for (const round of rounds) {
      for (const split of ["validation", "test"]) {
        for (const slot of Object.keys(SLOTS)) {
          const s = R[round].splits[split] && R[round].splits[split][slot];
          if (!s) continue;
          const c = s.sets.counts, p = s.sets.people;
          const n = (k) => Object.values(c[k] || {}).reduce((a, b) => a + b, 0);
          html("li", `${ROUNDS[round]} · ${split} · ${SLOTS[slot]}: giám khảo train trên ${fmt(n("train"), 0)} cửa sổ thật (${fmt(p.fit, 0)} người “fit”), dừng sớm theo ${fmt(n("inner"), 0)} cửa sổ của ${fmt(p.inner, 0)} người khác, chấm trên ${fmt(n("eval"), 0)} cửa sổ của người ${split}; mỗi nguồn giả có đúng số cửa sổ đó theo từng miền.`, j);
        }
      }
    }
    if (!j.children.length) html("li", "Chưa có sets.json của vòng chấm.", j);
  })();

  // ---------- Fig. 2 ----------
  (function fig2() {
    const wrap = $("fig2-real");
    clear(wrap);
    const cols = { af: "Cửa sổ AF (PERform AF)", non_af: "Cửa sổ không AF (PERform)" };
    const grid = html("div", null, wrap, "grid2");
    Object.entries(cols).forEach(([key, title]) => {
      const col = html("div", null, grid);
      html("div", title, col, "small muted");
      R.examples[key].forEach((e) => {
        const svg = el("svg", { class: "chart", viewBox: "0 0 600 120" }, col);
        if (e.missing) { el("text", { x: 20, y: 60 }, svg).textContent = `Không có cửa sổ nhóm ${e.group}`; return; }
        requestAnimationFrame(() => strip(svg, e.values, e.spans, css("--s2"), `${key === "af" ? "AF" : "Không AF"} · ${e.fraction}% artifact (nhóm ${e.group}) · ${R.domains[e.domain]}`));
      });
    });
    const syn = $("fig2-synthetic");
    clear(syn);
    if (!R.synthetic) { missing(syn, "Chưa sinh mẫu (chạy build_gan_report.py không có --no-synthetic)."); return; }
    const all = [["real", R.synthetic.examples_real], ...Object.entries(R.synthetic.examples)];
    all.forEach(([name, e]) => {
      const svg = el("svg", { class: "chart", viewBox: "0 0 900 120" }, syn);
      const label = name === "real" ? "Thật (validation)" : (R.synthetic.rows.six_domains.labels[name] || R.synthetic.rows.bidmc.labels[name]);
      const share = e.spans.reduce((a, [x, y]) => a + (y - x), 0) / 30 * 100;
      requestAnimationFrame(() => strip(svg, e.values, e.spans, name === "real" ? css("--real") : colorOf(name), `${label} · ${R.domains[e.domain]} · ${fmt(share, 1)}% bị luật SQI đánh dấu`));
    });
  })();

  // ---------- Fig. 3 ----------
  let fig3Split = "test", fig3Row = "six_domains";
  function fig3() {
    const q = R.quality, groups = q.groups;
    const c = q.cohort[fig3Split];
    bars($("fig3a"), groups, [
      { name: "AF", color: css("--s1"), values: groups.map((g) => c.af[g]) },
      { name: "Không AF", color: css("--s3"), values: groups.map((g) => c.non_af[g]) },
    ], { labels: true, digits: 0, ylabel: "Số cửa sổ" });
    legend($("fig3a-legend"), [[css("--s1"), "AF"], [css("--s3"), "Không AF"]]);
    const t = $("fig3-table");
    clear(t);
    const head = html("tr", null, html("thead", null, t));
    ["Miền", ...groups.map((g) => `${g} artifact`), "Artifact trung bình"].forEach((h, i) => html("th", h, head, i ? "num" : null));
    const body = html("tbody", null, t);
    Object.entries(q.per_domain).forEach(([d, bySplit]) => {
      const tr = html("tr", null, body);
      html("td", R.domains[d], tr);
      const counts = bySplit[fig3Split], n = groups.reduce((a, g) => a + counts[g], 0);
      groups.forEach((g) => html("td", n ? `${fmt(100 * counts[g] / n, 0)}% (${counts[g]})` : "—", tr, "num"));
      html("td", fmt(q.mean_fraction[d][fig3Split], 1) + "%", tr, "num");
    });
    const b = $("fig3b");
    if (!R.synthetic) { missing(b.parentNode.querySelector(".fig3b-note") || b.parentNode, "Chưa sinh mẫu."); return; }
    const shares = R.synthetic.artifacts[fig3Row];
    const names = Object.keys(shares);
    bars(b, groups, names.map((n) => ({ name: n === "real" ? "Thật" : R.synthetic.rows[fig3Row].labels[n], color: n === "real" ? css("--real") : colorOf(n), values: groups.map((g) => shares[n][g]) })),
      { y0: 0, y1: 100, yticks: [0, 25, 50, 75, 100], yl: (v) => v + "%", ylabel: "% cửa sổ", digits: 1 });
    legend($("fig3b-legend"), names.map((n) => [n === "real" ? css("--real") : colorOf(n), n === "real" ? "Thật" : R.synthetic.rows[fig3Row].labels[n]]));
  }
  segmented($("fig3-split"), [["train", "Train"], ["validation", "Validation"], ["test", "Test"]], fig3Split, (k) => { fig3Split = k; fig3(); });
  segmented($("fig3-row"), [["six_domains", "6 miền"], ["bidmc", "BIDMC"]], fig3Row, (k) => { fig3Row = k; fig3(); });

  // ---------- Table II ----------
  (function table2() {
    const wrap = $("table2-wrap");
    clear(wrap);
    if (!rounds.length) { missing(wrap, "Chưa có kết quả chấm (judges.json)."); return; }
    for (const slot of Object.keys(SLOTS)) {
      html("h3", SLOTS[slot], wrap);
      const tw = html("div", null, wrap, "tablewrap");
      const t = html("table", null, tw);
      const head = html("tr", null, html("thead", null, t));
      ["Nguồn", "Vòng", "AUC val ± SD", "Không phân biệt val", "Bal. acc val", "AUC test ± SD", "Không phân biệt test", "Bal. acc test", "AUC probe val"]
        .forEach((h, i) => html("th", h, head, i > 1 ? "num" : null));
      const body = html("tbody", null, t);
      const rows = [];
      for (const round of rounds) {
        const val = entries(round, "validation", slot);
        if (!val) continue;
        const test = entries(round, "test", slot) || {};
        const probe = entries(round, "validation", slot, "probe") || {};
        Object.entries(val).forEach(([g, v]) => rows.push({ g, round, v, t: test[g], p: probe[g] }));
      }
      const order = { null: 0, app: 1, reference: 2, arm: 3 };
      rows.sort((a, b) => order[a.v.kind] - order[b.v.kind] || a.v.auc - b.v.auc);
      const best = Math.min(...rows.filter((x) => x.v.kind !== "null").map((x) => x.v.auc));
      const bestTest = Math.min(...rows.filter((x) => x.v.kind !== "null" && x.t).map((x) => x.t.auc));
      rows.forEach(({ g, round, v, t: te, p }) => {
        const tr = html("tr", null, body);
        const name = html("td", v.label, tr);
        if (v.kind === "arm") name.appendChild(document.createTextNode(` · ${Object.keys(v.seeds).length} seed`));
        if (v.kind === "null") name.style.fontStyle = "italic";
        html("td", round === "strict" ? "strict" : "flow-GAN", tr, "small muted");
        const a = html("td", `${fmt(v.auc)} ± ${fmt(v.auc_sd)}`, tr, "num");
        if (v.auc === best) a.style.fontWeight = 700;
        html("td", fmt(v.indistinguishable, 1) + "%", tr, "num");
        html("td", fmt(v.balanced_accuracy, 1) + "%", tr, "num");
        const b = html("td", te ? `${fmt(te.auc)} ± ${fmt(te.auc_sd)}` : "—", tr, "num");
        if (te && te.auc === bestTest) b.style.fontWeight = 700;
        html("td", te ? fmt(te.indistinguishable, 1) + "%" : "—", tr, "num");
        html("td", te ? fmt(te.balanced_accuracy, 1) + "%" : "—", tr, "num");
        html("td", p ? fmt(p.auc) : "—", tr, "num");
      });
    }
  })();

  // ---------- Table III ----------
  (function table3() {
    const wrap = $("table3-wrap");
    clear(wrap);
    const runs = R.training.runs;
    if (!runs.length) { missing(wrap, "Chưa có training_execution.json."); return; }
    const byArm = {};
    runs.forEach((x) => { (byArm[x.arm] = byArm[x.arm] || []).push(x); });
    const t = html("table", null, html("div", null, wrap, "tablewrap"));
    const head = html("tr", null, html("thead", null, t));
    ["Arm", "Siêu tham số (giống nhau mọi seed)", "Seed", "Bước được chọn", "Tham số G", "Giờ train", "S_real", "C", "Điểm chọn", "Đạt cổng"]
      .forEach((h, i) => html("th", h, head, i > 1 ? "num" : null));
    const body = html("tbody", null, t);
    Object.entries(byArm).forEach(([arm, list]) => {
      list.sort((a, b) => a.seed - b.seed);
      list.forEach((x, i) => {
        const tr = html("tr", null, body);
        if (!i) {
          const a = html("td", x.label, tr); a.rowSpan = list.length;
          const cfg = Object.entries(x.config).map(([k, v]) => `${k}=${Array.isArray(v) ? v.join("+") : v}`).join(", ");
          const c = html("td", cfg || "(cấu hình tác giả, lsm_multiset/lsm_strict)", tr, "small"); c.rowSpan = list.length;
        }
        html("td", x.seed, tr, "num");
        html("td", fmt(x.best_step, 0), tr, "num");
        html("td", fmt(x.parameters, 0), tr, "num");
        html("td", fmt(x.hours, 2), tr, "num");
        html("td", fmt(x.S_real), tr, "num");
        html("td", fmt(x.C), tr, "num");
        html("td", fmt(x.selection), tr, "num");
        html("td", x.eligible == null ? "—" : x.eligible ? "có" : "không", tr, "num");
      });
    });
    const sig = runs.filter((x) => x.sensor_sigma);
    const s = $("table3-sigma");
    clear(s);
    if (!sig.length) { html("p", "Mức nhiễu cảm biến học được: chưa có checkpoint PhysioFlow-GAN.", s, "small muted"); return; }
    const t2 = html("table", null, html("div", null, s, "tablewrap"));
    const doms = Object.keys(sig[0].sensor_sigma);
    const h2 = html("tr", null, html("thead", null, t2));
    ["Arm · seed", ...doms.map((d) => R.domains[d] || d)].forEach((h, i) => html("th", h, h2, i ? "num" : null));
    const b2 = html("tbody", null, t2);
    sig.forEach((x) => {
      const tr = html("tr", null, b2);
      html("td", `${x.label} · ${x.seed}`, tr);
      doms.forEach((d) => html("td", fmt(x.sensor_sigma[d], 4), tr, "num"));
    });
  })();

  // ---------- Table IV (ablation) ----------
  (function table4() {
    const wrap = $("table4-wrap");
    clear(wrap);
    if (!rounds.length) { missing(wrap, "Chưa có kết quả chấm."); return; }
    const steps = {
      physiomix: [
        ["physiomix_app", "Mốc: PhysioMix trong app (critic đa thang)"],
        [INC + "_strict", "Chỉ đổi critic sang StrictCritic"],
        [INC + "_strict_quiet", "+ nhánh nhiễu thân lọc thấp và nhiễu đo"],
        ["physioflow_app", "Đổi họ mô hình: PhysioFlow 16 bước (không GAN)"],
        ["physioflow_sensor", "+ nhiễu cảm biến cố định 0,03"],
        ["G1_flowgan", "+ train đối kháng 4 bước, nhiễu học theo miền, neo chưng cất"],
      ],
      lsm: [
        ["lsm_app", "Mốc: LSM-GAN trong app"],
        ["lsm_author_v3", "Train lại topo tác giả trên view v3"],
        ["lsm_strict", "Critic nghiêm (LSM-GAN-S)"],
        ["physioflow_app", "PhysioFlow 16 bước nhắc bằng nhãn BIDMC"],
        ["physioflow_sensor", "+ nhiễu cảm biến cố định 0,03"],
        ["G2_flowgan_lsm_bidmc", "PhysioFlow-GAN chỉ train BIDMC + loss LSM"],
      ],
    };
    const runs = R.training.runs;
    const meanOf = (arm, k) => { const v = runs.filter((x) => x.arm === arm && x[k] != null).map((x) => x[k]); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };
    for (const slot of Object.keys(steps)) {
      html("h3", SLOTS[slot], wrap);
      const t = html("table", null, html("div", null, wrap, "tablewrap"));
      const head = html("tr", null, html("thead", null, t));
      ["Bước thay đổi", "Vòng", "AUC val", "Δ so với app", "AUC test", "S_real", "C"].forEach((h, i) => html("th", h, head, i > 1 ? "num" : null));
      const body = html("tbody", null, t);
      for (const [g, text] of steps[slot]) {
        for (const round of rounds) {
          const v = (entries(round, "validation", slot) || {})[g];
          if (!v) continue;
          const app = (entries(round, "validation", slot) || {})[slot + "_app"];
          const te = (entries(round, "test", slot) || {})[g];
          const tr = html("tr", null, body);
          html("td", text, tr);
          html("td", round === "strict" ? "strict" : "flow-GAN", tr, "small muted");
          html("td", fmt(v.auc), tr, "num");
          const d = app ? v.auc - app.auc : null;
          const cell = html("td", d == null ? "—" : (d > 0 ? "+" : "") + fmt(d), tr, "num");
          if (d != null && d < -0.02) cell.style.color = css("--rule");
          html("td", te ? fmt(te.auc) : "—", tr, "num");
          html("td", fmt(meanOf(g, "S_real")), tr, "num");
          html("td", fmt(meanOf(g, "C")), tr, "num");
        }
      }
    }
  })();

  // ---------- Fig. 6 ----------
  let f6Round = rounds[rounds.length - 1], f6Split = "validation", f6Kind = "strict";
  function fig6() {
    const svg = $("fig6"), lg = $("fig6-legend");
    const e = f6Round && entries(f6Round, f6Split, "physiomix", f6Kind);
    if (!e) { clear(svg); legend(lg, []); el("text", { x: 20, y: 40 }, svg).textContent = "Chưa có dữ liệu cho lựa chọn này."; return; }
    const doms = Object.keys(R.domains);
    const names = Object.keys(e).sort((a, b) => e[a].auc - e[b].auc);
    bars(svg, doms.map((d) => R.domains[d]), names.map((n) => ({
      name: e[n].label, color: colorOf(n),
      values: doms.map((d) => (e[n].per_domain[d] ? e[n].per_domain[d].auc : null)),
      err: doms.map((d) => (e[n].per_domain[d] ? e[n].per_domain[d].sd : null)),
    })), { y0: 0.3, y1: 1.0, yticks: [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0], ref: 0.5, ylabel: "AUC theo miền (0,5 = không tách được)" });
    legend(lg, names.map((n) => [colorOf(n), `${e[n].label} (${fmt(e[n].auc)})`]));
    const l = (entries(f6Round, f6Split, "lsm", f6Kind));
    const svgB = $("fig6-lsm"), lgB = $("fig6-lsm-legend");
    if (!l) { clear(svgB); legend(lgB, []); return; }
    const ln = Object.keys(l).sort((a, b) => l[a].auc - l[b].auc);
    bars(svgB, ln.map((n) => l[n].label), [{ name: "AUC", color: css("--accent"), values: ln.map((n) => l[n].auc), err: ln.map((n) => l[n].auc_sd) }],
      { y0: 0.3, y1: 1.0, yticks: [0.3, 0.5, 0.7, 0.9, 1.0], ref: 0.5, ylabel: "AUC BIDMC", bottom: 70 });
    [...svgB.querySelectorAll("rect")].forEach((r, i) => r.setAttribute("fill", colorOf(ln[i])));
    legend(lgB, []);
  }
  segmented($("fig6-round"), rounds.map((k) => [k, ROUNDS[k]]), f6Round, (k) => { f6Round = k; fig6(); });
  segmented($("fig6-split"), [["validation", "Validation"], ["test", "Test"]], f6Split, (k) => { f6Split = k; fig6(); });
  segmented($("fig6-kind"), [["strict", "Giám khảo nghiêm"], ["probe", "Probe nhỏ"]], f6Kind, (k) => { f6Kind = k; fig6(); });

  // ---------- Fig. 7 ----------
  const METRICS = {
    physiomix: [["checkpoint", "Điểm chọn checkpoint"], ["S_real", "S_real (MMD đặc trưng)"], ["C", "C (bám nhịp)"], ["Q_wrist", "Q cổ tay"], ["Q_bidmc", "Q BIDMC"]],
    lsm: [["selection", "Điểm chọn (LSM)"], ["acf_mmd2", "MMD² tự tương quan"], ["log_psd_mmd2", "MMD² phổ log"]],
  };
  let f7Family = "physiomix", f7Metric = "checkpoint";
  function fig7() {
    const svg = $("fig7"), lg = $("fig7-legend");
    clear(svg);
    const curves = R.training.curves;
    const arms = Object.keys(curves).filter((a) => (f7Family === "lsm") === a.startsWith("lsm"));
    const series = [];
    arms.forEach((arm) => Object.entries(curves[arm]).forEach(([seed, pts]) => {
      const p = pts.filter((x) => x[f7Metric] != null).map((x) => [x.step, x[f7Metric]]);
      if (p.length) series.push({ arm, seed, p });
    }));
    if (!series.length) { el("text", { x: 20, y: 40 }, svg).textContent = "Không có chỉ số này trong lịch sử train."; legend(lg, []); return; }
    const xs = series.flatMap((s) => s.p.map((q) => q[0])), ys = series.flatMap((s) => s.p.map((q) => q[1]));
    const x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    const pad = (y1 - y0) * 0.08 || 0.05;
    const bx = box(svg, 56, 42);
    const { X, Y } = axes(svg, bx, 0, x1, y0 - pad, y1 + pad, ticks(0, x1, 5).map(Math.round), ticks(y0 - pad, y1 + pad, 5), (v) => fmt(v, 0), (v) => fmt(v, 3));
    const dashes = ["", "6 3", "2 3"];
    const seeds = [...new Set(series.map((s) => s.seed))];
    series.forEach((s) => {
      const path = line(svg, s.p.map(([a, b]) => [X(a), Y(b)]), colorOf(s.arm), 1.6, { "stroke-dasharray": dashes[seeds.indexOf(s.seed) % 3] });
      hover(path, `${s.arm} seed ${s.seed}`);
      const run = R.training.runs.find((x) => x.arm === s.arm && String(x.seed) === s.seed);
      if (run && run.best_step != null) {
        const hit = s.p.reduce((a, q) => (Math.abs(q[0] - run.best_step) < Math.abs(a[0] - run.best_step) ? q : a));
        const dot = el("circle", { cx: X(hit[0]), cy: Y(hit[1]), r: 4, fill: colorOf(s.arm), stroke: css("--panel"), "stroke-width": 1.5 }, svg);
        hover(dot, `${s.arm} seed ${s.seed}: checkpoint chọn ở bước ${run.best_step}`);
      }
    });
    el("text", { x: bx.r, y: bx.b + 33, "text-anchor": "end" }, svg).textContent = "Bước train";
    legend(lg, [...arms.map((a) => [colorOf(a), R.training.runs.find((x) => x.arm === a).label]), ...seeds.map((s, i) => [css("--muted"), `seed ${s} (${["liền", "gạch", "chấm"][i % 3]})`])]);
  }
  function fig7Controls() {
    segmented($("fig7-metric"), METRICS[f7Family], f7Metric, (k) => { f7Metric = k; fig7(); });
  }
  segmented($("fig7-family"), [["physiomix", "Họ PhysioMix / PhysioFlow-GAN"], ["lsm", "Họ LSM-GAN"]], f7Family, (k) => { f7Family = k; f7Metric = METRICS[k][0][0]; fig7Controls(); fig7(); });
  fig7Controls();

  // ---------- Fig. 8 ----------
  let f8Slot = "physiomix";
  function fig8() {
    const svg = $("fig8a"), lg = $("fig8a-legend");
    clear(svg);
    const rows = [];
    for (const round of rounds) {
      const v = entries(round, "validation", f8Slot), t = entries(round, "test", f8Slot);
      if (!v || !t) continue;
      Object.keys(t).forEach((g) => { if (v[g]) rows.push({ g, round, v: v[g], t: t[g] }); });
    }
    if (!rows.length) { el("text", { x: 20, y: 40 }, svg).textContent = "Chưa có cả validation và test."; legend(lg, []); }
    else {
      svg.setAttribute("viewBox", `0 0 900 ${40 + rows.length * 26}`); delete svg.dataset.h;
      const bx = box(svg, 280, 30);
      const { X } = axes(svg, bx, 0.3, 1.0, 0, 1, [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0], [], (v) => fmt(v, 1), null);
      line(svg, [[X(0.5), bx.t], [X(0.5), bx.b]], css("--muted"), 1, { "stroke-dasharray": "4 4" });
      rows.forEach((x, i) => {
        const y = bx.t + 12 + i * 26;
        el("text", { x: bx.l - 8, y: y + 4, "text-anchor": "end" }, svg).textContent = `${x.v.label} · ${x.round === "strict" ? "strict" : "flow-GAN"}`;
        line(svg, [[X(x.v.auc), y], [X(x.t.auc), y]], colorOf(x.g), 2);
        const a = el("circle", { cx: X(x.v.auc), cy: y, r: 5, fill: css("--panel"), stroke: colorOf(x.g), "stroke-width": 2 }, svg);
        const b = el("circle", { cx: X(x.t.auc), cy: y, r: 5, fill: colorOf(x.g) }, svg);
        hover(a, `validation ${fmt(x.v.auc)}`); hover(b, `test ${fmt(x.t.auc)}`);
      });
      el("text", { x: bx.r, y: bx.b + 27, "text-anchor": "end" }, svg).textContent = "AUC giám khảo nghiêm";
      legend(lg, [[css("--muted"), "○ validation → ● test (người chưa thấy)"]]);
    }
    const c = $("fig8b"), lc = $("fig8b-legend");
    clear(c);
    const round = rounds[rounds.length - 1];
    const e = round && entries(round, "validation", f8Slot);
    if (!e) { legend(lc, []); return; }
    const names = Object.keys(e).filter((n) => e[n].curve.length);
    const steps = names.flatMap((n) => e[n].curve.map((p) => p[0]));
    if (!steps.length) { legend(lc, []); return; }
    const bx = box(c, 52, 42);
    const { X, Y } = axes(c, bx, 0, Math.max(...steps), 0.4, 1.0, ticks(0, Math.max(...steps), 4).map(Math.round), [0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0], (v) => fmt(v, 0), (v) => fmt(v, 1));
    names.forEach((n) => line(c, e[n].curve.map(([s, v]) => [X(s), Y(v)]), colorOf(n), 1.8));
    el("text", { x: bx.r, y: bx.b + 33, "text-anchor": "end" }, c).textContent = `Bước train giám khảo (${ROUNDS[round]}, AUC trên người “inner”)`;
    legend(lc, names.map((n) => [colorOf(n), e[n].label]));
  }
  segmented($("fig8-slot"), Object.entries(SLOTS), f8Slot, (k) => { f8Slot = k; fig8(); });

  // ---------- Fig. 9 ----------
  let f9Row = "six_domains", f9Feat = "amplitude";
  function fig9() {
    const wrap = $("fig9");
    clear(wrap);
    if (!R.synthetic) { missing(wrap, "Chưa sinh mẫu."); return; }
    const row = R.synthetic.rows[f9Row];
    const pts = row[f9Feat];
    const all = Object.values(pts).flat();
    Object.keys(pts).forEach((n) => {
      const cell = html("div", null, wrap, "card");
      cell.style.padding = "8px";
      html("div", `${row.labels[n]} (n=${row.counts[n]})`, cell, "small").style.textAlign = "center";
      const svg = el("svg", { class: "chart", viewBox: "0 0 220 220" }, cell);
      el("rect", { x: 1, y: 1, width: 218, height: 218, fill: "none", stroke: css("--line") }, svg);
      all.forEach(([x, y]) => el("circle", { cx: 8 + x * 204, cy: 212 - y * 204, r: 1.6, fill: css("--muted"), opacity: 0.18 }, svg));
      pts[n].forEach(([x, y]) => el("circle", { cx: 8 + x * 204, cy: 212 - y * 204, r: 2.2, fill: n === "real" ? css("--s1") : colorOf(n), opacity: 0.85 }, svg));
    });
  }
  segmented($("fig9-row"), [["six_domains", "6 miền (300 cửa sổ/nguồn)"], ["bidmc", "BIDMC (khe LSM)"]], f9Row, (k) => { f9Row = k; fig9(); });
  segmented($("fig9-feat"), [["amplitude", "Biên độ (như bài báo)"], ["spectral", "Phổ log + tự tương quan"]], f9Feat, (k) => { f9Feat = k; fig9(); });

  // ---------- static figure tabs (Fig. 4) ----------
  document.querySelectorAll("[data-tabs]").forEach((seg) => {
    seg.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
      seg.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
      document.querySelectorAll(`[data-tab-group="${seg.dataset.tabs}"]`).forEach((p) => { p.hidden = p.id !== b.dataset.target; });
    }));
  });

  $("theme").addEventListener("click", () => {
    const root = document.documentElement;
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    try { sessionStorage.setItem("theme", root.dataset.theme); } catch (e) { /* storage unavailable */ }
    location.reload();
  });
  function drawAll() { fig3(); fig6(); fig7(); fig8(); fig9(); }
  let pending = null;
  window.addEventListener("resize", () => { cancelAnimationFrame(pending); pending = requestAnimationFrame(drawAll); });
  drawAll();
})();
