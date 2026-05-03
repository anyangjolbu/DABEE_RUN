// app/web/static/js/admin/keywords.js
// 키워드·테마·블랙리스트 관리 페이지 로직.
// STEP-3B-13: tier 시스템 제거 → track(monitor/reference) 단일 분기로 통일.

let settings = {};

// 트랙 라벨 / CSS class
const TRACK_META = {
  monitor:   { label: '모니터', cls: 'monitor',   desc: 'SK하이닉스 직접 — 톤분석 + 텔레그램' },
  reference: { label: '참고',   cls: 'reference', desc: '경쟁사·업계 — 본문에 SK 등장 시 자동 승격' },
};

// ── 설정 로드 ──────────────────────────────────────────────
async function loadSettings() {
  const res = await adminFetch('/api/admin/settings');
  settings = await res.json();
  document.getElementById('schedInterval').value =
    settings.schedule_interval_minutes ?? settings.schedule_interval_min ?? 10;
  document.getElementById('expireHours').value =
    settings.article_expire_hours ?? 1;
  renderThemes();
  renderBlacklist('domainBlacklist', settings.domain_blacklist || [], 'domain_blacklist');
  renderBlacklist('titleBlacklist',  settings.title_blacklist  || [], 'title_blacklist');
}

// ── 테마 렌더링 ────────────────────────────────────────────
function renderThemes() {
  const container = document.getElementById('themeList');
  container.innerHTML = '';
  const themes = settings.search_themes || {};

  if (!Object.keys(themes).length) {
    container.innerHTML = '<p class="muted">테마가 없습니다. 추가 버튼을 눌러주세요.</p>';
    return;
  }

  Object.entries(themes).forEach(([id, theme]) => {
    const track = theme.track || 'monitor';
    const meta  = TRACK_META[track] || TRACK_META.monitor;

    const card = document.createElement('div');
    card.className = 'theme-card card';
    card.dataset.id = id;

    card.innerHTML = `
      <div class="theme-header">
        <span class="track-badge ${meta.cls}">${meta.label}</span>
        <input class="theme-label-input input-field" value="${escapeHtml(theme.label || '')}" data-id="${id}" />
        <select class="input-field track-select" data-id="${id}">
          <option value="monitor"   ${track==='monitor'?'selected':''}>모니터</option>
          <option value="reference" ${track==='reference'?'selected':''}>참고</option>
        </select>
        <button class="btn btn-danger btn-sm" data-del="${id}">삭제</button>
      </div>
      <div class="track-desc muted">${meta.desc}</div>
      <div class="chip-list" id="chips-${id}"></div>
    `;
    container.appendChild(card);

    renderKeywordChips(id, theme.keywords || []);

    // 라벨 변경
    card.querySelector('.theme-label-input').addEventListener('change', (e) => {
      settings.search_themes[e.target.dataset.id].label = e.target.value;
    });
    // 트랙 변경
    card.querySelector('.track-select').addEventListener('change', (e) => {
      const tid     = e.target.dataset.id;
      const newTrk  = e.target.value;
      const newMeta = TRACK_META[newTrk] || TRACK_META.monitor;
      settings.search_themes[tid].track = newTrk;
      const badge = card.querySelector('.track-badge');
      badge.className = `track-badge ${newMeta.cls}`;
      badge.textContent = newMeta.label;
      card.querySelector('.track-desc').textContent = newMeta.desc;
    });
    // 테마 삭제
    card.querySelector('[data-del]').addEventListener('click', (e) => {
      const tid = e.target.dataset.del;
      const label = settings.search_themes[tid]?.label || tid;
      if (confirm(`"${label}" 테마를 삭제하시겠습니까?`)) {
        delete settings.search_themes[tid];
        renderThemes();
      }
    });
  });
}

function renderKeywordChips(themeId, keywords) {
  const container = document.getElementById(`chips-${themeId}`);
  if (!container) return;
  container.innerHTML = '';

  keywords.forEach(kw => {
    const chip = document.createElement('span');
    chip.className = 'chip';
    chip.innerHTML = `${escapeHtml(kw)}<span class="chip-remove" data-kw="${escapeHtml(kw)}" data-theme="${themeId}">×</span>`;
    container.appendChild(chip);
  });

  // 입력창
  const input = document.createElement('input');
  input.className = 'chip-input';
  input.placeholder = '키워드 추가…';
  input.addEventListener('keydown', (e) => {
    if ((e.key === 'Enter' || e.key === ',') && input.value.trim()) {
      e.preventDefault();
      const kw = input.value.trim().replace(/,$/, '');
      const kws = settings.search_themes[themeId].keywords;
      if (kw && !kws.includes(kw)) {
        kws.push(kw);
        renderKeywordChips(themeId, kws);
      }
      input.value = '';
    }
  });
  container.appendChild(input);

  // 칩 제거 이벤트
  container.querySelectorAll('.chip-remove').forEach(btn => {
    btn.addEventListener('click', () => {
      const kw  = btn.dataset.kw;
      const tid = btn.dataset.theme;
      settings.search_themes[tid].keywords =
        settings.search_themes[tid].keywords.filter(k => k !== kw);
      renderKeywordChips(tid, settings.search_themes[tid].keywords);
    });
  });
}

// ── 블랙리스트 렌더링 ──────────────────────────────────────
function renderBlacklist(containerId, items, field) {
  const container = document.getElementById(containerId);
  container.innerHTML = '';

  items.forEach(item => {
    const chip = document.createElement('span');
    chip.className = 'chip';
    chip.innerHTML = `${escapeHtml(item)}<span class="chip-remove" data-item="${escapeHtml(item)}" data-field="${field}">×</span>`;
    container.appendChild(chip);
  });

  const input = document.createElement('input');
  input.className = 'chip-input';
  input.placeholder = '추가…';
  input.addEventListener('keydown', (e) => {
    if ((e.key === 'Enter' || e.key === ',') && input.value.trim()) {
      e.preventDefault();
      const val = input.value.trim().replace(/,$/, '');
      if (val && !settings[field].includes(val)) {
        settings[field].push(val);
        renderBlacklist(containerId, settings[field], field);
      }
      input.value = '';
    }
  });
  container.appendChild(input);

  container.querySelectorAll('.chip-remove').forEach(btn => {
    btn.addEventListener('click', () => {
      settings[btn.dataset.field] =
        settings[btn.dataset.field].filter(i => i !== btn.dataset.item);
      renderBlacklist(containerId, settings[btn.dataset.field], btn.dataset.field);
    });
  });
}

// ── 저장 ──────────────────────────────────────────────────
async function saveSettings() {
  const patch = {
    search_themes:              settings.search_themes,
    domain_blacklist:           settings.domain_blacklist,
    title_blacklist:            settings.title_blacklist,
    schedule_interval_minutes:  parseInt(document.getElementById('schedInterval').value) || 10,
    article_expire_hours:       parseInt(document.getElementById('expireHours').value)   || 1,
  };
  const res = await adminFetch('/api/admin/settings', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  });
  res.ok ? toast('저장 완료') : toast('저장 실패', 'err');
}

// ── 초기화 ────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  loadSettings();

  document.getElementById('saveBtn').addEventListener('click', saveSettings);

  document.getElementById('addThemeBtn').addEventListener('click', () => {
    const id = `theme_${Date.now()}`;
    settings.search_themes[id] = { label: '새 테마', track: 'reference', keywords: [] };
    renderThemes();
    const newCard = document.querySelector(`[data-id="${id}"]`);
    newCard?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    newCard?.querySelector('.theme-label-input')?.focus();
  });
});
