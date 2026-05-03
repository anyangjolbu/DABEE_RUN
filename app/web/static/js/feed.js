// app/web/static/js/feed.js
// 기사 피드: 필터, 페이지네이션, 실시간 신규 알림.

(function () {
  const LIMIT = 30;
  let offset  = 0;
  let total   = 0;
  let pending = false;
  const filters = { tier: '', theme: '', search: '', tone: '' };

  // ── 기사 로드 ────────────────────────────────────────────
  async function load(reset = false) {
    if (pending) return;
    pending = true;

    if (reset) {
      offset = 0;
      document.getElementById('articleList').innerHTML = '';
    }

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
        list.innerHTML = '<div class="muted" style="text-align:center;padding:32px;">검색 결과가 없습니다.</div>';
      }
      data.items.forEach(a => list.appendChild(buildCard(a)));

      const more = document.getElementById('feedMore');
      if (more) more.style.display = offset >= total ? 'none' : 'block';
    } catch (e) {
      console.error('[feed] 로드 실패', e);
    }
    pending = false;
  }

  // ── 카드 생성 ────────────────────────────────────────────
  function buildCard(a) {
    const div   = document.createElement('div');
    div.className = 'item';

    const title  = a.title_clean || a.title || '';
    const link   = a.original_url || a.url || '#';
    const date   = a.pub_date ? a.pub_date.substring(0, 16).replace('T', ' ') : '';

    const meta = [];
    if (a.tier)        meta.push(`<span class="tag tier-${a.tier}">TIER ${a.tier}</span>`);
    if (a.theme_label) meta.push(`<span class="tag">${esc(a.theme_label)}</span>`);
    if (a.press)       meta.push(`<span class="tag">${esc(a.press)}</span>`);
    if (a.tone_level)  meta.push(`<span class="tag tone-tag tone-${esc(a.tone_level)}">${esc(a.tone_level)}</span>`);
    if (date)          meta.push(`<span class="muted">${date}</span>`);

    div.innerHTML = `
      <div class="title">
        <a href="${esc(link)}" target="_blank" rel="noopener">${esc(title)}</a>
      </div>
      ${a.summary ? `<div class="summary">${esc(a.summary)}</div>` : ''}
      <div class="meta">${meta.join('')}</div>
    `;
    return div;
  }

  // ── 테마 드롭다운 ────────────────────────────────────────
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

  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => (
      { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
  }

  // ── 초기화 ───────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', () => {
    loadThemes();
    load();

    let searchTimer = null;

    document.getElementById('filterTier').addEventListener('change', (e) => {
      filters.tier = e.target.value; load(true);
    });
    document.getElementById('filterTheme').addEventListener('change', (e) => {
      filters.theme = e.target.value; load(true);
    });
    document.getElementById('filterTone').addEventListener('change', (e) => {
      filters.tone = e.target.value; load(true);
    });
    document.getElementById('filterSearch').addEventListener('input', (e) => {
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
    document.getElementById('loadMoreBtn').addEventListener('click', () => load());

    const newAlertBtn = document.getElementById('newAlertBtn');
    if (newAlertBtn) {
      newAlertBtn.addEventListener('click', () => {
        document.getElementById('newAlert').classList.add('hidden');
        load(true);
      });
    }
  });

  // ── WebSocket: 신규 기사 알림 ─────────────────────────────
  window.addEventListener('dabee:pipeline', (e) => {
    if (e.detail.phase === 'done' && (e.detail.result?.new ?? 0) > 0) {
      const alertEl = document.getElementById('newAlert');
      if (alertEl) alertEl.classList.remove('hidden');
    }
  });
})();
