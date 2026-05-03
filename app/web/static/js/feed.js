// Feed page: filter toolbar, card grid, pagination, new-article alert.
(function () {
  const LIMIT = 24;
  let offset = 0, total = 0, pending = false;
  const filters = { tier: '', theme: '', search: '', tone: '' };

  const GRADS = ['g1','g2','g3','g4','g5','g6','g7','g8'];
  let gradIdx = 0;

  // ── Helpers ──────────────────────────────────────────────
  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c =>
      ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]));
  }
  function toneClass(t) {
    if (t === '경고') return 'warn';
    if (t === '주의') return 'watch';
    if (t === '양호') return 'good';
    return '';
  }
  function timeStr(dateStr) {
    if (!dateStr) return '';
    const d = new Date(dateStr);
    return `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
  }

  // ── Card builder (matches dashboard card style) ──────────
  function buildCard(a) {
    const g = GRADS[gradIdx++ % 8];
    const tier = a.tier || 3;
    const tc = toneClass(a.tone_level);
    const link = a.original_url || a.url || '#';
    const title = a.title_clean || a.title || '';
    const press = a.press || a.theme_label || '';
    const t = timeStr(a.pub_date);

    const art = document.createElement('a');
    art.className = 'card-article';
    art.href = link;
    art.target = '_blank';
    art.rel = 'noopener';
    art.innerHTML = `
      <div class="thumb ${g}">
        <span class="thumb-tier ${tier === 1 ? 't1' : ''}">TIER ${tier}</span>
        ${t ? `<div class="thumb-time">${t}</div>` : ''}
        ${tc ? `<div class="tone-strip ${tc}"></div>` : ''}
      </div>
      <h4 class="card-title-text">${esc(title)}</h4>
      <div class="card-author">${esc(press)}</div>
    `;
    return art;
  }

  // ── Load ─────────────────────────────────────────────────
  async function load(reset = false) {
    if (pending) return;
    pending = true;
    if (reset) { offset = 0; gradIdx = 0; document.getElementById('articleList').innerHTML = ''; }

    const p = new URLSearchParams({ limit: LIMIT, offset });
    if (filters.tier)   p.set('tier',   filters.tier);
    if (filters.theme)  p.set('theme',  filters.theme);
    if (filters.search) p.set('search', filters.search);
    if (filters.tone)   p.set('tone',   filters.tone);

    try {
      const res  = await fetch(`/api/articles?${p}`);
      const data = await res.json();
      total   = data.total;
      offset += data.items.length;

      const countEl = document.getElementById('feedCount');
      if (countEl) countEl.textContent = `총 ${total.toLocaleString()}건`;

      const list = document.getElementById('articleList');
      if (!data.items.length && reset) {
        list.innerHTML = '<div class="muted" style="grid-column:1/-1;text-align:center;padding:40px;">검색 결과가 없습니다.</div>';
      }
      data.items.forEach(a => list.appendChild(buildCard(a)));

      const more = document.getElementById('feedMore');
      if (more) more.style.display = offset >= total ? 'none' : 'block';
    } catch(e) { console.error('[feed] 로드 실패', e); }
    pending = false;
  }

  // ── Themes dropdown ──────────────────────────────────────
  async function loadThemes() {
    try {
      const themes = await fetch('/api/themes').then(r => r.json());
      const sel = document.getElementById('filterTheme');
      themes.forEach(t => {
        const opt = document.createElement('option');
        opt.value = t.id;
        opt.textContent = `T${t.tier} ${t.label}`;
        sel.appendChild(opt);
      });
    } catch {}
  }

  // ── Init ─────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', () => {
    loadThemes();
    load();

    let searchTimer = null;

    document.getElementById('filterTier').addEventListener('change', e => {
      filters.tier = e.target.value; load(true);
    });
    document.getElementById('filterTheme').addEventListener('change', e => {
      filters.theme = e.target.value; load(true);
    });
    document.getElementById('filterTone').addEventListener('change', e => {
      filters.tone = e.target.value; load(true);
    });
    document.getElementById('filterSearch').addEventListener('input', e => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => { filters.search = e.target.value.trim(); load(true); }, 400);
    });
    document.getElementById('filterReset').addEventListener('click', () => {
      filters.tier = filters.theme = filters.search = filters.tone = '';
      ['filterTier','filterTheme','filterTone','filterSearch'].forEach(id => {
        document.getElementById(id).value = '';
      });
      load(true);
    });
    document.getElementById('loadMoreBtn')?.addEventListener('click', () => load());
    document.getElementById('newAlertBtn')?.addEventListener('click', () => {
      document.getElementById('newAlert').classList.add('hidden');
      load(true);
    });
  });

  // ── WebSocket: new article banner ────────────────────────
  window.addEventListener('dabee:pipeline', (e) => {
    if (e.detail.phase === 'done' && (e.detail.result?.new ?? 0) > 0) {
      document.getElementById('newAlert')?.classList.remove('hidden');
    }
  });
})();
