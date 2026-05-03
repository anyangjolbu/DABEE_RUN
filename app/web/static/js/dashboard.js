// app/web/static/js/dashboard.js
(function () {
  const phaseEl = document.getElementById('schedPhase');
  const cycleEl = document.getElementById('schedCycle');
  const nextEl  = document.getElementById('schedNext');
  const lastEl  = document.getElementById('schedLast');
  const logBox  = document.getElementById('logBox');
  const listEl  = document.getElementById('articleList');
  const totalEl = document.getElementById('articleTotal');

  // ── 스케줄러 상태 표시 ────────────────────────────────
  const phaseLabel = (p) => ({ idle: '대기', running: '실행 중', stopped: '정지' }[p] || p);
  function renderScheduler(s) {
    if (!s) return;
    phaseEl.textContent = phaseLabel(s.phase);
    cycleEl.textContent = s.cycle_count ?? 0;
    nextEl.textContent  = formatNextIn(s.next_in_sec);
    if (s.last_result) {
      const r = s.last_result;
      lastEl.textContent =
        `마지막 결과: 수집 ${r.collected} → 관련 ${r.relevant} → 신규 ${r.new}` +
        ` → 저장 ${r.saved} → 발송 ${r.sent_articles}건 (수신자 ${r.sent_total}회)`;
    }
  }
  function formatNextIn(sec) {
    if (sec == null) return '실행 중';
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  }

  window.addEventListener('dabee:scheduler', (e) => {
    renderScheduler(e.detail.data);
  });
  window.addEventListener('dabee:pipeline', (e) => {
    if (e.detail.phase === 'done') {
      // 사이클 끝나면 기사 목록 갱신
      loadArticles();
      // 스케줄러 상태도 재요청
      fetch('/api/scheduler').then(r => r.json()).then(renderScheduler);
    }
  });

  // 초기 로드
  fetch('/api/scheduler').then(r => r.json()).then(renderScheduler);

  // ── 실시간 로그 ───────────────────────────────────────
  window.addEventListener('dabee:log', (e) => {
    const { level, message } = e.detail;
    const line = document.createElement('div');
    line.className = `level-${level}`;
    line.textContent = message;
    logBox.appendChild(line);
    // 너무 많이 쌓이면 앞에서 제거
    while (logBox.childElementCount > 500) logBox.removeChild(logBox.firstChild);
    logBox.scrollTop = logBox.scrollHeight;
  });

  // ── 기사 목록 ─────────────────────────────────────────
  function loadArticles() {
    fetch('/api/articles?limit=20').then(r => r.json()).then(data => {
      totalEl.textContent = `(전체 ${data.total}건)`;
      listEl.innerHTML = '';
      if (!data.items.length) {
        listEl.innerHTML = '<div class="muted">아직 수집된 기사가 없습니다.</div>';
        return;
      }
      for (const a of data.items) {
        const div = document.createElement('div');
        div.className = 'item';
        const titleClean = a.title_clean || a.title || '';
        const link = a.original_url || a.url || '#';
        const meta = [];
        if (a.tier) meta.push(`<span class="tag tier-${a.tier}">TIER ${a.tier}</span>`);
        if (a.theme_label) meta.push(`<span class="tag">${a.theme_label}</span>`);
        if (a.press) meta.push(`<span class="tag">${a.press}</span>`);
        if (a.tone_level) meta.push(`<span class="tag">${a.tone_level}</span>`);
        if (a.pub_date)   meta.push(`<span>${a.pub_date.substring(0, 16).replace('T', ' ')}</span>`);
        div.innerHTML = `
          <div class="title"><a href="${link}" target="_blank" rel="noopener">${escapeHtml(titleClean)}</a></div>
          ${a.summary ? `<div class="summary">${escapeHtml(a.summary)}</div>` : ''}
          <div class="meta">${meta.join('')}</div>
        `;
        listEl.appendChild(div);
      }
    });
  }
  function escapeHtml(s) {
    return (s || '').replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
  }
  loadArticles();
  setInterval(loadArticles, 30000); // 30초마다 새로고침
})();
