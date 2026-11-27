// SkillProof onboarding assistant widget: streaming chat over Server-Sent Events.
(function () {
  const root = document.getElementById('ai');
  if (!root) return;
  const $ = (s, r = root) => r.querySelector(s);
  const body = $('[data-ai-body]'), form = $('[data-ai-form]'), input = form.elements.q;
  const chips = $('[data-ai-chips]'), modeEl = $('[data-ai-mode]'), sendBtn = $('button', form);
  let t = {};
  try { t = JSON.parse(root.dataset.i18n); } catch (e) {}
  const KEY = 'sp-ai-' + root.dataset.lang;
  let history = [];
  let busy = false;

  // ---- safe, minimal formatting: escape HTML, then allow **bold** and [text](/internal-path)
  const esc = s => s.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const format = text => esc(text)
    .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
    .replace(/\[([^\]]+)\]\((\/(?!\/)[^\s)]*)\)/g, '<a href="$2">$1</a>');

  const add = (role, text) => {
    const div = document.createElement('div');
    div.className = 'ai-msg ' + (role === 'user' ? 'me' : 'bot');
    div.innerHTML = format(text);
    body.appendChild(div);
    body.scrollTop = body.scrollHeight;
    return div;
  };
  const save = () => { try { sessionStorage.setItem(KEY, JSON.stringify(history.slice(-24))); } catch (e) {} };

  // restore this tab's conversation
  try { history = JSON.parse(sessionStorage.getItem(KEY)) || []; } catch (e) { history = []; }
  history.forEach(m => add(m.role, m.content));
  if (history.length) chips.hidden = true;

  // ---- open / close
  const open = () => {
    document.body.classList.add('ai-open');
    setTimeout(() => input.focus(), 50);
    try { sessionStorage.setItem('sp-ai-open', '1'); } catch (e) {}
  };
  const close = () => {
    document.body.classList.remove('ai-open');
    try { sessionStorage.removeItem('sp-ai-open'); } catch (e) {}
    $('[data-ai-open]').focus();
  };
  document.querySelectorAll('[data-ai-open]').forEach(b => b.addEventListener('click', open));
  $('[data-ai-close]').addEventListener('click', close);
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && document.body.classList.contains('ai-open')) close(); });
  try { if (sessionStorage.getItem('sp-ai-open') && innerWidth > 760) open(); } catch (e) {}

  $('[data-ai-reset]').addEventListener('click', () => {
    if (history.length && !confirm(t.reset || 'Start a new conversation?')) return;
    history = []; save();
    body.querySelectorAll('.ai-msg:not([data-ai-welcome])').forEach(n => n.remove());
    chips.hidden = false;
    input.focus();
  });

  // ---- input behaviour: Enter sends, Shift+Enter adds a line, auto-grow
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); }
  });
  input.addEventListener('input', () => { input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight, 120) + 'px'; });
  chips.addEventListener('click', e => {
    const b = e.target.closest('[data-ai-chip]');
    if (b) { input.value = b.textContent.trim(); form.requestSubmit(); }
  });

  const setMode = mode => { if (mode && t[mode]) modeEl.textContent = t[mode]; };

  form.addEventListener('submit', async e => {
    e.preventDefault();
    const q = input.value.trim();
    if (!q || busy) return;
    busy = true; sendBtn.disabled = true; chips.hidden = true;
    input.value = ''; input.style.height = 'auto';
    add('user', q);
    history.push({ role: 'user', content: q }); save();

    const bubble = add('bot', '');
    bubble.innerHTML = '<span class="ai-typing"><i></i><i></i><i></i></span>';
    let answer = '';
    try {
      const res = await fetch(root.dataset.endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': root.dataset.csrf },
        body: JSON.stringify({ messages: history, page: location.pathname }),
      });
      if (!res.ok || !res.body) {
        let msg = t.error;
        try { msg = (await res.json()).error || msg; } catch (err) {}
        throw new Error(msg);
      }
      const reader = res.body.getReader(), dec = new TextDecoder();
      let buf = '';
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let i;
        while ((i = buf.indexOf('\n\n')) >= 0) {
          const line = buf.slice(0, i).replace(/^data: /, '');
          buf = buf.slice(i + 2);
          let ev;
          try { ev = JSON.parse(line); } catch (err) { continue; }
          if (ev.mode) setMode(ev.mode);
          if (ev.t) {
            answer += ev.t;
            bubble.innerHTML = format(answer);
            body.scrollTop = body.scrollHeight;
          }
        }
      }
      if (!answer) throw new Error(t.error);
      history.push({ role: 'assistant', content: answer }); save();
    } catch (err) {
      bubble.textContent = (err && err.message) || t.error;
      history.pop(); save();  // let the user retry the same question
      input.value = q;
    } finally {
      busy = false; sendBtn.disabled = false; input.focus();
    }
  });
})();
