// Tiny dependency-free SVG charts. Usage:
// <div class="chart" data-chart='{"type":"line","labels":[...],"series":[{"name":"A","values":[...]}]}'></div>
// types: line (area), bar, hbar, donut
(function () {
  const NS = 'http://www.w3.org/2000/svg';
  const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const palette = () => ['--c1', '--c2', '--c3', '--c4', '--c5', '--c6'].map(css);
  const el = (tag, attrs = {}, parent) => {
    const n = document.createElementNS(NS, tag);
    for (const k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  };
  const niceMax = m => {
    if (m <= 4) return 4;
    const p = Math.pow(10, Math.floor(Math.log10(m)));
    return [1, 2, 2.5, 5, 10].map(x => x * p).find(x => x >= m) || m;
  };

  function tooltip(box) {
    let t = box.querySelector('.chart-tip');
    if (!t) { t = document.createElement('div'); t.className = 'chart-tip'; box.appendChild(t); }
    return {
      show(html, x, y) { t.innerHTML = html; t.style.left = x + 'px'; t.style.top = y + 'px'; t.classList.add('show'); },
      hide() { t.classList.remove('show'); },
    };
  }

  function legend(box, items, colors) {
    if (items.length < 2) return;
    const l = document.createElement('div');
    l.className = 'chart-legend';
    l.innerHTML = items.map((s, i) => `<span><i style="background:${colors[i % colors.length]}"></i>${s}</span>`).join('');
    box.appendChild(l);
  }

  function axes(svg, W, H, P, max, labels, step) {
    const g = el('g', { class: 'axis' }, svg);
    for (let i = 0; i <= 4; i++) {
      const y = P.t + (H - P.t - P.b) * (1 - i / 4);
      el('line', { x1: P.l, x2: W - P.r, y1: y, y2: y, class: 'gridline' }, g);
      el('text', { x: P.l - 8, y: y + 3, 'text-anchor': 'end' }, g).textContent = Math.round(max * i / 4);
    }
    const every = Math.ceil(labels.length / (W < 500 ? 4 : 7));
    labels.forEach((lab, i) => {
      if (i % every && i !== labels.length - 1) return;
      el('text', { x: P.l + step * i + (step / 2) * (svg.dataset.bar ? 1 : 0), y: H - 6, 'text-anchor': 'middle' }, g).textContent = lab;
    });
  }

  function line(box, d) {
    const W = Math.max(box.clientWidth, 280), H = 240, P = { t: 12, r: 12, b: 26, l: 34 };
    const colors = palette();
    const n = d.labels.length, max = niceMax(Math.max(1, ...d.series.flatMap(s => s.values)));
    const step = (W - P.l - P.r) / Math.max(1, n - 1);
    const X = i => P.l + step * i, Y = v => P.t + (H - P.t - P.b) * (1 - v / max);
    const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': d.title || 'Line chart' });
    box.appendChild(svg);
    axes(svg, W, H, P, max, d.labels, step);
    const defs = el('defs', {}, svg);
    d.series.forEach((s, si) => {
      const c = colors[si % colors.length], id = 'g' + Math.random().toString(36).slice(2);
      const lg = el('linearGradient', { id, x1: 0, x2: 0, y1: 0, y2: 1 }, defs);
      el('stop', { offset: '0%', 'stop-color': c, 'stop-opacity': si ? .12 : .28 }, lg);
      el('stop', { offset: '100%', 'stop-color': c, 'stop-opacity': 0 }, lg);
      const pts = s.values.map((v, i) => [X(i), Y(v)]);
      // smooth path (monotone-ish cubic)
      let path = `M${pts[0][0]},${pts[0][1]}`;
      for (let i = 1; i < pts.length; i++) {
        const [x0, y0] = pts[i - 1], [x1, y1] = pts[i], cx = (x0 + x1) / 2;
        path += ` C${cx},${y0} ${cx},${y1} ${x1},${y1}`;
      }
      el('path', { d: `${path} L${X(n - 1)},${Y(0)} L${X(0)},${Y(0)} Z`, fill: `url(#${id})` }, svg);
      el('path', { d: path, fill: 'none', stroke: c, 'stroke-width': 2.4, 'stroke-linecap': 'round' }, svg);
    });
    // hover
    const tip = tooltip(box), guide = el('line', { y1: P.t, y2: H - P.b, stroke: css('--line'), 'stroke-dasharray': '3 3', opacity: 0 }, svg);
    const dots = d.series.map((s, si) => el('circle', { r: 4.5, fill: css('--surface'), stroke: colors[si % colors.length], 'stroke-width': 2.4, opacity: 0 }, svg));
    const hit = el('rect', { x: P.l, y: P.t, width: W - P.l - P.r, height: H - P.t - P.b, class: 'hit' }, svg);
    const move = e => {
      const r = svg.getBoundingClientRect(), x = (e.clientX - r.left) * (W / r.width);
      const i = Math.max(0, Math.min(n - 1, Math.round((x - P.l) / step)));
      guide.setAttribute('x1', X(i)); guide.setAttribute('x2', X(i)); guide.setAttribute('opacity', 1);
      dots.forEach((dot, si) => { dot.setAttribute('cx', X(i)); dot.setAttribute('cy', Y(d.series[si].values[i])); dot.setAttribute('opacity', 1); });
      tip.show(`<b>${d.labels[i]}</b><br>` + d.series.map(s => `${s.name}: ${s.values[i]}`).join('<br>'),
        X(i) * r.width / W, Y(Math.max(...d.series.map(s => s.values[i]))) * r.height / H);
    };
    hit.addEventListener('mousemove', move);
    hit.addEventListener('mouseleave', () => { tip.hide(); guide.setAttribute('opacity', 0); dots.forEach(x => x.setAttribute('opacity', 0)); });
    legend(box, d.series.map(s => s.name), colors);
  }

  function bar(box, d) {
    const W = Math.max(box.clientWidth, 280), H = 220, P = { t: 12, r: 8, b: 26, l: 30 };
    const colors = palette(), vals = d.series[0].values, n = vals.length;
    const max = niceMax(Math.max(1, ...vals)), step = (W - P.l - P.r) / n, bw = Math.min(28, step * .62);
    const Y = v => P.t + (H - P.t - P.b) * (1 - v / max);
    const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': d.title || 'Bar chart', 'data-bar': 1 });
    box.appendChild(svg);
    axes(svg, W, H, P, max, d.labels, step);
    const tip = tooltip(box);
    vals.forEach((v, i) => {
      const x = P.l + step * i + (step - bw) / 2, y = Y(v), h = Math.max(v ? 2 : 0, Y(0) - y);
      const r = el('rect', { x, y: Y(0) - h, width: bw, height: h, rx: Math.min(6, bw / 3), fill: colors[0] }, svg);
      r.addEventListener('mouseenter', () => {
        r.setAttribute('opacity', .8);
        const b = svg.getBoundingClientRect();
        tip.show(`<b>${d.labels[i]}</b><br>${d.series[0].name}: ${v}`, (x + bw / 2) * b.width / W, (Y(0) - h) * b.height / H);
      });
      r.addEventListener('mouseleave', () => { r.setAttribute('opacity', 1); tip.hide(); });
    });
  }

  function hbar(box, d) {
    const colors = palette(), vals = d.series[0].values, max = Math.max(1, ...vals);
    box.style.minHeight = 0;
    box.innerHTML = d.labels.map((l, i) => `
      <div class="meter-row" style="margin-bottom:10px"><span class="small">${l}</span>
        <span class="meter"><i style="width:${(vals[i] / max * 100).toFixed(1)}%;background:${colors[i % colors.length]}"></i></span>
        <b class="small right">${vals[i]}</b></div>`).join('');
  }

  function donut(box, d) {
    const colors = d.colors ? d.colors.map(c => c.startsWith('--') ? css(c) : c) : palette();
    const vals = d.series[0].values, total = vals.reduce((a, b) => a + b, 0);
    const S = 170, R = 70, T = 22, C = 2 * Math.PI * R;
    const svg = el('svg', { viewBox: `0 0 ${S} ${S}`, role: 'img', 'aria-label': d.title || 'Donut chart' });
    box.appendChild(svg);
    el('circle', { cx: S / 2, cy: S / 2, r: R, fill: 'none', stroke: css('--line-2'), 'stroke-width': T }, svg);
    let off = 0;
    const tip = tooltip(box);
    vals.forEach((v, i) => {
      if (!v) return;
      const len = v / total * C;
      const arc = el('circle', { cx: S / 2, cy: S / 2, r: R, fill: 'none', stroke: colors[i % colors.length], 'stroke-width': T,
        'stroke-dasharray': `${Math.max(0, len - 2)} ${C}`, 'stroke-dashoffset': -off, transform: `rotate(-90 ${S / 2} ${S / 2})` }, svg);
      arc.addEventListener('mouseenter', () => tip.show(`<b>${d.labels[i]}</b>: ${v} (${Math.round(v / total * 100)}%)`, box.clientWidth / 2, 30));
      arc.addEventListener('mouseleave', () => tip.hide());
      off += len;
    });
    const t = el('text', { x: S / 2, y: S / 2 - 2, 'text-anchor': 'middle', 'font-size': 28, 'font-weight': 750, fill: css('--ink') }, svg);
    t.textContent = total;
    const s = el('text', { x: S / 2, y: S / 2 + 18, 'text-anchor': 'middle', 'font-size': 11, fill: css('--muted') }, svg);
    s.textContent = d.center || 'total';
    const leg = box.parentElement.querySelector('.donut-legend');
    if (leg) leg.innerHTML = d.labels.map((l, i) =>
      `<div><i style="background:${colors[i % colors.length]}"></i>${l}<b>${vals[i]}</b></div>`).join('');
  }

  const render = () => document.querySelectorAll('.chart[data-chart]').forEach(box => {
    let d;
    try { d = JSON.parse(box.dataset.chart); } catch (e) { return; }
    box.innerHTML = '';
    ({ line, bar, hbar, donut }[d.type] || line)(box, d);
  });
  render();
  let t;
  addEventListener('resize', () => { clearTimeout(t); t = setTimeout(render, 150); });
  document.addEventListener('themechange', render);
})();
