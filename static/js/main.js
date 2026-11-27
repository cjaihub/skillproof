// SkillProof UI enhancements. Every page still works without JavaScript.
(function () {
  document.documentElement.classList.add('js');
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

  // ---- theme: light | dark | system (follows the device and updates live)
  const root = document.documentElement;
  const sysDark = window.matchMedia ? matchMedia('(prefers-color-scheme: dark)') : null;
  const applyTheme = pref => {
    const dark = pref === 'dark' || (pref === 'system' && sysDark && sysDark.matches);
    const changed = root.dataset.theme !== (dark ? 'dark' : 'light');
    root.dataset.themePref = pref;
    root.dataset.theme = dark ? 'dark' : 'light';
    if (changed) document.dispatchEvent(new Event('themechange'));
  };
  $$('[data-theme-set]').forEach(b => b.addEventListener('click', () => {
    const pref = b.dataset.themeSet;
    try { localStorage.setItem('sp-theme', pref); } catch (e) {}
    applyTheme(pref);
    b.closest('details')?.removeAttribute('open');
  }));
  sysDark?.addEventListener?.('change', () => { if (root.dataset.themePref === 'system') applyTheme('system'); });

  // ---- generic class toggles: data-toggle-class="#selector:class"
  $$('[data-toggle-class]').forEach(el => el.addEventListener('click', () => {
    const [sel, cls] = el.dataset.toggleClass.split(':');
    $(sel)?.classList.toggle(cls);
  }));
  document.addEventListener('keydown', e => { if (e.key === 'Escape') $('#app')?.classList.remove('nav-open'); });

  // ---- dropdowns: close on outside click / when another opens
  document.addEventListener('click', e => {
    $$('details.dropdown[open]').forEach(d => { if (!d.contains(e.target)) d.removeAttribute('open'); });
  });

  // ---- toasts
  $$('.toast').forEach((t, i) => {
    const close = () => { t.classList.add('hide'); setTimeout(() => t.remove(), 260); };
    $('.toast-x', t)?.addEventListener('click', close);
    if (!t.classList.contains('toast-error') && !t.classList.contains('toast-dev')) setTimeout(close, 5000 + i * 600);
  });

  // ---- confirmations
  $$('form[data-confirm]').forEach(f => f.addEventListener('submit', e => {
    if (!confirm(f.dataset.confirm)) e.preventDefault();
  }));
  $$('[data-autosubmit]').forEach(el => {
    el.dataset.initial = el.value;
    el.addEventListener('change', () => {
      if (el.dataset.confirmChange && !confirm(el.dataset.confirmChange)) { el.value = el.dataset.initial; return; }
      el.form.requestSubmit ? el.form.requestSubmit() : el.form.submit();
    });
  });

  // ---- character counters
  $$('textarea[data-count]').forEach(t => {
    const max = +t.dataset.count, c = document.createElement('small');
    c.className = 'counter muted';
    const upd = () => { c.textContent = `${t.value.length} / ${max}`; };
    t.after(c); t.addEventListener('input', upd); upd();
  });

  // ---- passwords: show/hide, strength meter, confirmation match
  $$('[data-pw-toggle]').forEach(b => b.addEventListener('click', () => {
    const inp = b.parentElement.querySelector('input');
    const show = inp.type === 'password';
    inp.type = show ? 'text' : 'password';
    b.innerHTML = `<svg class="i"><use href="#i-${show ? 'eye-off' : 'eye'}"/></svg>`;
    b.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
  }));
  const score = pw => {
    if (!pw) return 0;
    let s = 0;
    if (pw.length >= 8) s++;
    if (pw.length >= 12) s++;
    if (/[a-z]/i.test(pw) && /\d/.test(pw)) s++;
    if (/[^a-z0-9]/i.test(pw) || (/[a-z]/.test(pw) && /[A-Z]/.test(pw))) s++;
    return Math.max(1, Math.min(4, s));
  };
  $$('input[data-strength]').forEach(inp => {
    const label = inp.closest('label');
    const meter = $('.pw-meter', label), hint = $('.pw-hint', label);
    let words = ['Weak', 'Fair', 'Good', 'Strong', 'Use 8+ characters with letters and numbers.'];
    try { words = JSON.parse(inp.dataset.labels) || words; } catch (e) {}
    inp.addEventListener('input', () => {
      const s = score(inp.value);
      meter.dataset.score = s;
      const okRule = inp.value.length >= 8 && /[a-z]/i.test(inp.value) && /\d/.test(inp.value);
      hint.textContent = !inp.value ? words[4] : okRule ? words[s - 1] : words[s - 1] + ' · ' + words[4];
      inp.setCustomValidity(inp.value && !okRule ? words[4] : '');
    });
  });
  $$('input[data-match]').forEach(inp => {
    const other = inp.form.elements[inp.dataset.match];
    const check = () => inp.setCustomValidity(inp.value && inp.value !== other.value ? (inp.dataset.mismatch || 'Passwords do not match') : '');
    inp.addEventListener('input', check); other.addEventListener('input', check);
  });

  // ---- file size check
  $$('input[type=file][data-maxmb]').forEach(inp => inp.addEventListener('change', () => {
    const f = inp.files[0], max = +inp.dataset.maxmb;
    inp.setCustomValidity(f && f.size > max * 1024 * 1024 ? `File is larger than ${max} MB` : '');
    inp.reportValidity();
  }));

  // ---- registration wizard
  const wiz = $('[data-wizard]');
  if (wiz) {
    const steps = $$('.wizard-step', wiz), dots = $$('.stepper span', wiz);
    let cur = 0;
    const firstError = steps.findIndex(s => s.dataset.hasError === '1');
    const show = i => {
      cur = i;
      steps.forEach((s, j) => s.classList.toggle('current', j === i));
      dots.forEach((d, j) => d.classList.toggle('on', j <= i));
      const f = $('input:not([type=hidden]):not([type=radio]), select, textarea', steps[i]);
      if (f && i > 0) f.focus({ preventScroll: true });
    };
    const valid = i => $$('input, select, textarea', steps[i]).every(el => el.reportValidity());
    $$('[data-next]', wiz).forEach(b => b.addEventListener('click', () => { if (valid(cur)) show(cur + 1); }));
    $$('[data-prev]', wiz).forEach(b => b.addEventListener('click', () => show(cur - 1)));
    // role-dependent fields
    const syncRole = () => {
      const role = ($('input[name=role]:checked', wiz) || {}).value;
      $$('[data-role-only]', wiz).forEach(el => {
        const on = el.dataset.roleOnly.split(',').includes(role);
        el.hidden = !on;
        $$('input, select, textarea', el).forEach(i => { i.disabled = !on; });
      });
      $$('[data-role-text]', wiz).forEach(el => { el.textContent = JSON.parse(el.dataset.roleText)[role] || ''; });
    };
    $$('input[name=role]', wiz).forEach(r => r.addEventListener('change', syncRole));
    syncRole();
    show(firstError > -1 ? firstError : 0);
  }

  // ---- landing page step-by-step tour
  $$('[data-tour]').forEach(tour => {
    const tabs = $$('.tour-tab', tour), panels = $$('.tour-panel', tour), dots = $$('.tour-dots i', tour);
    const prev = $('[data-tour-prev]', tour), next = $('[data-tour-next]', tour), finish = $('[data-tour-finish]', tour);
    const bar = $('.tour-progress i', tour), label = $('span', next), n = panels.length;
    let cur = 0;
    const go = (i, focusTab) => {
      if (i < 0 || i >= n) return;
      const back = i < cur;
      cur = i;
      panels.forEach((p, j) => { p.classList.toggle('on', j === i); p.classList.toggle('from-left', j === i && back); });
      tabs.forEach((t, j) => {
        t.classList.toggle('on', j === i); t.classList.toggle('done', j < i);
        t.setAttribute('aria-selected', j === i ? 'true' : 'false'); t.tabIndex = j === i ? 0 : -1;
      });
      dots.forEach((d, j) => d.classList.toggle('on', j === i));
      bar.style.width = ((i + 1) / n * 100) + '%';
      prev.disabled = i === 0;
      next.hidden = i === n - 1;
      finish.hidden = i !== n - 1;
      const word = next.dataset.nextLabel || 'Next';
      if (i < n - 1) label.textContent = matchMedia('(max-width: 760px)').matches
        ? word : word + ': ' + $('.tour-label', tabs[i + 1]).textContent;
      if (focusTab) tabs[i].focus();
    };
    tabs.forEach((t, j) => t.addEventListener('click', () => go(j)));
    prev.addEventListener('click', () => go(cur - 1));
    next.addEventListener('click', () => go(cur + 1));
    // arrow keys move between steps (standard tabs pattern)
    tour.addEventListener('keydown', e => {
      const onTab = e.target.matches('.tour-tab'), fwd = document.dir === 'rtl' ? -1 : 1;
      if (e.key === 'ArrowRight') { e.preventDefault(); go(cur + fwd, onTab); }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); go(cur - fwd, onTab); }
      else if (onTab && e.key === 'Home') { e.preventDefault(); go(0, true); }
      else if (onTab && e.key === 'End') { e.preventDefault(); go(n - 1, true); }
    });
    // swipe left/right on touch screens
    let x0 = null;
    const vp = $('.tour-viewport', tour);
    vp.addEventListener('touchstart', e => { x0 = e.touches[0].clientX; }, { passive: true });
    vp.addEventListener('touchend', e => {
      if (x0 === null) return;
      const dx = e.changedTouches[0].clientX - x0;
      if (Math.abs(dx) > 50) go(cur + (dx < 0 ? 1 : -1) * (document.dir === 'rtl' ? -1 : 1));
      x0 = null;
    });
    go(0);
  });

  // ---- share link for one competence or the full report
  const areaSel = $('#share-area');
  if (areaSel) areaSel.addEventListener('change', () => {
    const out = $('#share-url');
    out.value = out.dataset.base + (areaSel.value ? '?area=' + encodeURIComponent(areaSel.value) : '');
  });

  // ---- long-running forms (AI reading): show progress and prevent double submits
  $$('form[data-busy]').forEach(f => f.addEventListener('submit', () => {
    const b = $('button:not([type=button])', f) || $('button', f);
    if (b) { b.disabled = true; b.innerHTML = '<span class="spinner"></span> ' + f.dataset.busy; }
  }));

  // ---- file drop zone: show chosen file name, highlight on drag
  $$('[data-dropzone]').forEach(z => {
    const inp = $('input[type=file]', z), name = $('[data-dz-name]', z);
    inp.addEventListener('change', () => { name.textContent = inp.files[0] ? inp.files[0].name : ''; z.classList.toggle('has-file', !!inp.files[0]); });
    ['dragenter', 'dragover'].forEach(ev => z.addEventListener(ev, e => { e.preventDefault(); z.classList.add('drag'); }));
    ['dragleave', 'drop'].forEach(ev => z.addEventListener(ev, () => z.classList.remove('drag')));
    z.addEventListener('drop', e => {
      e.preventDefault();
      if (e.dataTransfer.files.length) { inp.files = e.dataTransfer.files; inp.dispatchEvent(new Event('change')); }
    });
  });

  // ---- "select all" for suggestion lists
  $$('[data-check-all]').forEach(b => b.addEventListener('click', () => {
    $$(`input[name^="${b.dataset.checkAll}"]:not(:disabled)`).forEach(c => (c.checked = true));
  }));

  // ---- copy AI-suggested scores into the assessor form (assessor still reviews and saves)
  $$('[data-apply-scores]').forEach(b => b.addEventListener('click', () => {
    let crit = [];
    try { crit = JSON.parse(b.dataset.applyScores); } catch (e) {}
    crit.forEach(c => {
      const r = $(`#score-form input[name="score_${c.criterion}"][value="${c.suggested_score}"]`);
      if (r) r.checked = true;
    });
    $('#score-form')?.dispatchEvent(new Event('change', { bubbles: true }));
    $('#score-form')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }));

  // ---- skills test progress bar
  const tf = $('#test-form');
  if (tf) {
    const bar = $('#test-progress'), groups = new Set($$('input[type=radio]', tf).map(i => i.name)), texts = $$('textarea', tf);
    const upd = () => {
      const done = [...groups].filter(n => $(`input[name="${n}"]:checked`, tf)).length + texts.filter(t => t.value.trim().length >= 20).length;
      bar.style.width = (done / (groups.size + texts.length) * 100) + '%';
    };
    tf.addEventListener('input', upd); tf.addEventListener('change', upd); upd();
  }

  // ---- demo account quick-fill on login
  $$('[data-fill-email]').forEach(b => b.addEventListener('click', () => {
    const f = b.closest('form') || $('form.login-form');
    f.elements.email.value = b.dataset.fillEmail;
    f.elements.password.focus();
  }));

  // ---- copy & print
  $$('[data-copy]').forEach(b => b.addEventListener('click', async () => {
    const inp = $(b.dataset.copy);
    try { await navigator.clipboard.writeText(inp.value); } catch { inp.select(); document.execCommand('copy'); }
    const old = b.innerHTML; b.innerHTML = 'Copied ✓'; setTimeout(() => (b.innerHTML = old), 1800);
  }));
  $$('[data-print]').forEach(b => b.addEventListener('click', () => window.print()));

  // ---- bulk selection tables
  $$('[data-bulk]').forEach(form => {
    const boxes = () => $$('input[name=ids]', form);
    const bar = $('.bulkbar', form), count = $('[data-bulk-count]', form), all = $('[data-select-all]', form);
    const upd = () => {
      const n = boxes().filter(b => b.checked).length;
      bar?.classList.toggle('show', n > 0);
      if (count) count.textContent = n;
      if (all) all.checked = n && n === boxes().length;
    };
    all?.addEventListener('change', () => { boxes().forEach(b => (b.checked = all.checked)); upd(); });
    form.addEventListener('change', e => { if (e.target.name === 'ids') upd(); });
    upd();
  });

  // ---- live assessment score
  const sf = $('#score-form');
  if (sf) {
    const out = $('#score-total'), pass = +out.dataset.pass;
    const render = () => {
      const vals = $$('.criterion', sf).map(fs => $('input:checked', fs)).map(i => (i ? +i.value : null));
      const sum = vals.reduce((a, v) => a + (v || 0), 0);
      if (vals.some(v => v === null)) {
        out.className = 'score-total';
        out.innerHTML = `<span>Score every criterion</span><b>${sum}/20</b>`;
        return;
      }
      const ok = sum >= pass && Math.min(...vals) >= 2;
      out.className = 'score-total ' + (ok ? 'pass' : 'fail');
      out.innerHTML = `<span>${ok ? '✓ Will be verified' : 'Not yet verified' + (Math.min(...vals) < 2 ? ' (a criterion is below 2)' : '')}</span><b>${sum}/20</b>`;
    };
    sf.addEventListener('change', render); render();
  }
})();
