// SkillProof: small progressive enhancements. Every page works without JS.
(function () {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

  // Mobile nav
  $$('[data-toggle="nav"]').forEach(b => b.addEventListener('click', () => $('#nav').classList.toggle('open')));

  // Dismiss flash messages (auto-hide success after 6s)
  $$('.flash').forEach(f => {
    $('.flash-x', f)?.addEventListener('click', () => f.remove());
    if (f.classList.contains('flash-success')) setTimeout(() => f.classList.add('fade'), 6000);
  });

  // Confirm destructive actions
  $$('form[data-confirm]').forEach(f => f.addEventListener('submit', e => {
    if (!confirm(f.dataset.confirm)) e.preventDefault();
  }));

  // Auto-submit selects/checkboxes
  $$('[data-autosubmit]').forEach(el => {
    el.dataset.initial = el.value;
    el.addEventListener('change', () => {
      if (el.dataset.confirmChange && !confirm(el.dataset.confirmChange)) { el.value = el.dataset.initial; return; }
      el.form.submit();
    });
  });

  // Character counters
  $$('textarea[data-count]').forEach(t => {
    const max = +t.dataset.count, c = document.createElement('small');
    c.className = 'counter muted';
    const upd = () => { c.textContent = `${t.value.length} / ${max}`; };
    t.after(c); t.addEventListener('input', upd); upd();
  });

  // Password confirmation match
  $$('input[data-match]').forEach(inp => {
    const other = inp.form.elements[inp.dataset.match];
    const check = () => inp.setCustomValidity(inp.value && inp.value !== other.value ? 'Passwords do not match' : '');
    inp.addEventListener('input', check); other.addEventListener('input', check);
  });

  // File size check before upload
  $$('input[type=file][data-maxmb]').forEach(inp => inp.addEventListener('change', () => {
    const f = inp.files[0], max = +inp.dataset.maxmb;
    inp.setCustomValidity(f && f.size > max * 1024 * 1024 ? `File is larger than ${max} MB` : '');
    inp.reportValidity();
  }));

  // Show organisation field for employers on registration
  const org = $('.org-field');
  if (org) $$('input[name=role]').forEach(r => r.addEventListener('change', () => { org.hidden = r.value !== 'employer' || !r.checked; }));

  // Copy share link
  $$('[data-copy]').forEach(b => b.addEventListener('click', async () => {
    const inp = $(b.dataset.copy);
    try { await navigator.clipboard.writeText(inp.value); } catch { inp.select(); document.execCommand('copy'); }
    const old = b.textContent; b.textContent = 'Copied ✓'; setTimeout(() => (b.textContent = old), 1800);
  }));

  $$('[data-print]').forEach(b => b.addEventListener('click', () => window.print()));

  // Live score total on the assessment form
  const sf = $('#score-form');
  if (sf) {
    const out = $('#score-total'), pass = +out.dataset.pass;
    sf.addEventListener('change', () => {
      const vals = $$('.score', sf).map(fs => $('input:checked', fs)).map(i => (i ? +i.value : null));
      if (vals.some(v => v === null)) { out.innerHTML = `Total: <b>${vals.reduce((a, v) => a + (v || 0), 0)}</b>/20 (score every criterion)`; out.className = 'score-total'; return; }
      const total = vals.reduce((a, b) => a + b, 0), ok = total >= pass && Math.min(...vals) >= 2;
      out.innerHTML = `Total: <b>${total}</b>/20 → <b>${ok ? 'Verified' : 'Not yet verified'}</b>`;
      out.className = 'score-total ' + (ok ? 'pass' : 'fail');
    });
  }
})();
