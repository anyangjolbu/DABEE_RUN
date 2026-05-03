// app/web/static/js/admin/keywords.js
// 키워드·테마·블랙리스트 관리 페이지 로직.

let settings = {};

// ── 설정 로드 ──────────────────────────────────────────────
async function loadSettings() {
  const res = await adminFetch('/api/admin/settings');
  settings = await res.json();
  document.getElementById('schedInterval').value = settings.schedule_interval_minutes ?? 10;
  document.getElementById('expireHours').value   = settings.article_expire_hours      ?? 1;
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
    const card = document.createElement('div');
    card.className = 'theme-card card';
    card.style.marginBottom = 'var(--space-3)';
    card.dataset.id = id;

    card.innerHTML = `
      <div class="theme-header">
        <span class="tier-badge t${theme.tier}">TIER ${theme.tier}</span>
        <input class="theme-label-input" value="${escapeHtml(theme.label)}" data-id="${id}" />
        <select class="input-field tier-select" style="width:80px;" data-id="${id}">
          <option value="1" ${theme.tier==1?'selected':''}>T1</option>
          <option value="2" ${theme.tier==2?'selected':''}>T2</option>
          <option value="3" ${theme.tier==3?'selected':''}>T3</option>
        </select>
        <label class="toggle" title="톤분석 활성화">
          <input type="checkbox" class="tone-toggle" data-id="${id}" ${theme.tone_analysis?'checked':''}/>
          <span class="toggle-track"></span>
        </label>
        <span class="muted" style="font-size:11px;">톤분석</span>
        <button class="btn btn-danger" style="padding:4px 10px;font-size:12px;margin-left:auto;" data-del="${id}">삭제</button>
      </div>
      <div class="chip-list" id="chips-${id}"></div>
    `;
    container.appendChild(card);

    renderKeywordChips(id, theme.keywords);

    // 라벨 변경
    card.querySelector('.theme-label-input').addEventListener('change', (e) => {
      settings.search_themes[e.target.dataset.id].label = e.target.value;
    });
    // 티어 변경
    card.querySelector('.tier-select').addEventListener('change', (e) => {
      const tid = e.target.dataset.id;
      settings.search_themes[tid].tier = parseInt(e.target.value);
      card.querySelector('.tier-badge').className = `tier-badge t${e.target.value}`;
      card.querySelector('.tier-badge').textContent = `TIER ${e.target.value}`;
    });
    // 톤분석 토글
    card.querySelector('.tone-toggle').addEventListener('change', (e) => {
      settings.search_themes[e.target.dataset.id].tone_analysis = e.target.checked;
    });
    // 테마 삭제
    card.querySelector('[data-del]').addEventListener('click', (e) => {
      const tid = e.target.dataset.del;
      const label = settings.search_themes[tid]?.label || tid;
      if (confirm(`"${label}" 테마를 삭제하시겠습니까?`)) {
        delete settings.search_themes[tid];
        renderThemes();
        renderBlacklist('domainBlacklist', settings.domain_blacklist || [], 'domain_blacklist');
        renderBlacklist('titleBlacklist',  settings.title_blacklist  || [], 'title_blacklist');
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
    settings.search_themes[id] = { label: '새 테마', tier: 3, keywords: [], tone_analysis: false };
    renderThemes();
    // 새 카드로 스크롤
    const newCard = document.querySelector(`[data-id="${id}"]`);
    newCard?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    newCard?.querySelector('.theme-label-input')?.focus();
  });
});
