// Translate user-written text (marked data-tr) into the page language, with a cached server endpoint.
(function () {
  const bar = document.getElementById('tr-bar');
  if (!bar) return;
  const all = () => Array.from(document.querySelectorAll('[data-tr]')).filter(el => el.textContent.trim());
  // Only offer the bar when there is user text in the page itself (not just inside a closed menu)
  const visible = all().filter(el => !el.closest('details.dropdown'));
  if (!visible.length) return;

  let t = {};
  try { t = JSON.parse(bar.dataset.i18n); } catch (e) {}
  const lang = bar.dataset.lang;
  const btn = bar.querySelector('[data-tr-go]'), note = bar.querySelector('.tr-note');
  const AUTO = 'sp-autotr';
  let translated = false, busy = false;

  const setIdle = () => { note.textContent = t.note || ''; btn.textContent = translated ? t.orig : t.to; btn.disabled = false; };

  async function translate() {
    if (busy) return;
    if (translated) {  // back to original
      all().forEach(el => { if (el.dataset.orig !== undefined) { el.textContent = el.dataset.orig; el.classList.remove('is-tr'); el.removeAttribute('title'); } });
      translated = false;
      try { localStorage.removeItem(AUTO); } catch (e) {}
      setIdle();
      return;
    }
    busy = true; btn.disabled = true; btn.textContent = t.busy;
    const els = all();
    const texts = [...new Set(els.map(el => (el.dataset.orig ?? el.textContent).trim()))];
    const map = {};
    try {
      for (let i = 0; i < texts.length; i += 40) {
        const chunk = texts.slice(i, i + 40);
        const res = await fetch(bar.dataset.endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': bar.dataset.csrf },
          body: JSON.stringify({ texts: chunk, lang }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || res.statusText);
        chunk.forEach((src, j) => { map[src] = data.translations[j]; });
      }
      els.forEach(el => {
        const src = (el.dataset.orig ?? el.textContent).trim();
        if (map[src] && map[src] !== src) {
          if (el.dataset.orig === undefined) el.dataset.orig = el.textContent;
          el.textContent = map[src];
          el.classList.add('is-tr');
          el.title = t.done;
        }
      });
      translated = true;
      try { localStorage.setItem(AUTO, lang); } catch (e) {}
      setIdle();
    } catch (err) {
      note.textContent = err.message;
      btn.textContent = t.to; btn.disabled = false;
      try { localStorage.removeItem(AUTO); } catch (e) {}
    } finally { busy = false; }
  }

  btn.addEventListener('click', translate);
  bar.querySelector('[data-tr-close]').addEventListener('click', () => { bar.hidden = true; });
  setIdle();
  bar.hidden = false;
  // keep translating on later pages once the reader chose it for this language
  try { if (localStorage.getItem(AUTO) === lang) translate(); } catch (e) {}
})();
