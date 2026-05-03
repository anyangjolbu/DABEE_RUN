// Public dashboard: hero sentiment, trend chart, article cards, section tabs.
// STEP 4A-2 (옵션 A): tone_classification 기반 배지/필터 + reason 노출
(function () {
  const LIMIT = 50;
  let offset = 0, total = 0, pending = false;
  let currentTab = 'all';
  let allArticles = [];

  // ── Helpers ──────────────────────────────────────────────
  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c =>
      ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]));
  }

  // 신규 분류 → CSS 클래스 / 배지 라벨
  function classMeta(a) {
    const track = a.track || 'monitor';
    const cls   = a.tone_classification || '';

    if (track === 'reference') {
      return { tag: 'reference', label: '참고', strip: 'reference' };
    }
    if (cls === '비우호') return { tag: 'hostile', label: '비우호', strip: 'hostile' };
    if (cls === '양호')   return { tag: 'normal',  label: '양호',  strip: 'normal'  };
    if (cls === '미분석') return { tag: 'unknown', label: '미분석', strip: 'unknown' };
    return { tag: '', label: '', strip: '' };
  }

  function timeAgo(dateStr) {
    if (!dateStr) return '';
    const d = new Date(dateStr);
    if (isNaN(d)) return '';
    const sec = Math.floor((Date.now() - d) / 1000);
    if (sec < 60)         return '방금';
    if (sec < 3600)       return `${Math.floor(sec / 60)}분 전`;
    if (sec < 86400)      return `${Math.floor(sec / 3600)}시간 전`;
    if (sec < 86400 * 7)  return `${Math.floor(sec / 86400)}일 전`;
    return `${d.getMonth() + 1}/${d.getDate()}`;
  }

  // ── Card builder ─────────────────────────────────────────
  function buildCard(a) {
    const meta    = classMeta(a);
    const link    = a.original_url || a.url || '#';
    const title   = a.title_clean || a.title || '';
    const press   = a.press || a.theme_label || '';
    const t       = timeAgo(a.pub_date || a.collected_at || '');
    const reason  = a.tone_reason || '';
    const summary = a.summary || a.description || '';

    const art = document.createElement('a');
    art.className = `card-article card-${meta.tag}`;
    art.href = link;
    art.target = '_blank';
    art.rel = 'noopener';

    const badgeHtml = meta.label
      ? `<span class="card-badge badge-${meta.tag}">${meta.label}</span>`
      : '';
    const summaryHtml = summary
      ? `<p class="card-summary">${esc(summary)}</p>`
      : '';
    const reasonHtml = (meta.tag === 'hostile' && reason)
      ? `<div class="card-reason">📌 ${esc(reason)}</div>`
      : '';
    const titleAttr = reason ? `title="${esc(reason)}"` : '';

    const footParts = [];
    if (press) footParts.push(`<span class="card-press">${esc(press)}</span>`);
    if (t)     footParts.push(`<span class="card-time">${t}</span>`);

    art.innerHTML = `
      <div class="card-inner">
        ${badgeHtml}
        <h4 class="card-title-text" ${titleAttr}>${esc(title)}</h4>
        ${summaryHtml}
        ${reasonHtml}
        <div class="card-foot">${footParts.join('<span class="card-dot">·</span>')}</div>
      </div>
      ${meta.strip ? `<div class="tone-strip ${meta.strip}"></div>` : ''}
    `;
    return art;
  }

  // ── Section tabs ─────────────────────────────────────────
  document.querySelectorAll('.section-tabs .tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.section-tabs .tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      currentTab = tab.dataset.tab;
      renderCards();
    });
  });

  function filterByTab(items) {
    if (currentTab === 'hostile')   return items.filter(a => a.tone_classification === '비우호' && (a.track || 'monitor') === 'monitor');
    if (currentTab === 'normal')    return items.filter(a => a.tone_classification === '양호'  && (a.track || 'monitor') === 'monitor');
    if (currentTab === 'reference') return items.filter(a => (a.track || 'monitor') === 'reference');
    return items;
  }

  function renderCards() {
    const grid = document.getElementById('cardsGrid');
    grid.innerHTML = '';
    const filtered = filterByTab(allArticles);
    if (!filtered.length) {
      grid.innerHTML = '<div class="muted" style="grid-column:1/-1;text-align:center;padding:40px;">기사가 없습니다.</div>';
      return;
    }
    filtered.forEach((a, i) => grid.appendChild(buildCard(a, i)));
    const more = document.getElementById('feedMore');
    if (more) more.style.display = offset < total ? 'block' : 'none';
  }

  // ── Load articles ────────────────────────────────────────
  async function load(reset = false) {
    if (pending) return;
    pending = true;
    if (reset) { offset = 0; allArticles = []; }
    try {
      const res  = await fetch(`/api/articles?limit=${LIMIT}&offset=${offset}`);
      const data = await res.json();
      total   = data.total;
      offset += data.items.length;
      allArticles = allArticles.concat(data.items);
      renderCards();
      /* sentiment 별도 API로 */
    } catch(e) { console.error('[dashboard] 로드 실패', e); }
    finally { pending = false; }
  }

  // 90초마다 서버 total 확인 — WS 이벤트 누락 대비
  setInterval(async () => {
    try {
      const res  = await fetch('/api/articles?limit=1&offset=0');
      const data = await res.json();
      if (total > 0 && data.total > total) load(true);
    } catch {}
  }, 90_000);

  document.getElementById('loadMoreBtn')?.addEventListener('click', () => load());
  document.getElementById('newAlertBtn')?.addEventListener('click', () => {
    document.getElementById('newAlert').classList.add('hidden');
    load(true);
  });

  // ── Sentiment computation (NSS, monitor 트랙 기준) ─────────
// NSS = (양호 - 비우호) / (양호 + 비우호) × 100, 범위 -100~+100
async function loadSentiment() {
  try {
    const res  = await fetch('/api/dashboard/sentiment?days=7');
    const data = await res.json();
    renderHero(data.today);
    renderTrendChart(data.trend);
  } catch(e) {
    console.error('[sentiment] 로드 실패', e);
  }
}

function renderHero(today) {
  const score = today.score;       // null 가능
  const n     = today.n;
  const good  = today.good;
  const bad   = today.bad;
  const unknown = today.unknown;
  const reliable = today.reliable;

  // 점수 표시 (null 또는 표본 부족 시 회색)
  const scoreEl = document.getElementById('heroScore');
  const trendScoreEl = document.getElementById('trendScore');
  if (score === null) {
    scoreEl.textContent = '—';
    trendScoreEl.textContent = '—';
    scoreEl.classList.add('low-confidence');
  } else {
    const sign = score > 0 ? '+' : '';
    scoreEl.textContent = sign + score;
    trendScoreEl.textContent = sign + score;
    if (!reliable) scoreEl.classList.add('low-confidence');
    else scoreEl.classList.remove('low-confidence');
  }

  // 분포 표기 (count 기반)
  const denom = good + bad + unknown || 1;
  const goodPct = Math.round(good / denom * 100);
  const badPct  = Math.round(bad  / denom * 100);
  const unkPct  = Math.max(0, 100 - goodPct - badPct);
  document.getElementById('heroGood').textContent = `${goodPct}%`;
  document.getElementById('heroWarn').textContent = `${badPct}%`;

  // Pill — 색상 구간 +20 / 0~+20 / 0 미만
  const pill = document.getElementById('heroPill');
  if (score === null || !reliable) {
    pill.textContent = `오늘의 톤: 표본 부족 (N=${n})`;
    pill.className = 'pill neutral';
  } else if (score >= 20) {
    pill.textContent = '오늘의 톤: 우호적';
    pill.className = 'pill positive';
  } else if (score >= 0) {
    pill.textContent = '오늘의 톤: 관망';
    pill.className = 'pill neutral';
  } else {
    pill.textContent = '오늘의 톤: 비우호 감지';
    pill.className = 'pill negative';
  }

  // Hero title
  const titleEl = document.getElementById('heroTitle');
  if (score === null) {
    titleEl.innerHTML = '오늘의 SK하이닉스 여론은<br><span class="accent">아직 분석 가능한 기사가 부족합니다</span>';
  } else if (score >= 20) {
    titleEl.innerHTML = '오늘의 SK하이닉스 여론은<br><span class="accent">우호 흐름이 우세합니다</span>';
  } else if (score >= 0) {
    titleEl.innerHTML = '오늘의 SK하이닉스 여론은<br><span class="accent">관망 국면입니다</span>';
  } else {
    titleEl.innerHTML = '오늘의 SK하이닉스 여론은<br><span class="accent">비우호 흐름이 감지됩니다</span>';
  }

  // Desc
  document.getElementById('heroDesc').textContent =
    `분석 ${n}건 (양호 ${good} · 비우호 ${bad}) · 미분석 ${unknown}건`;

  // Meta
  const now = new Date();
  const hh = String(now.getHours()).padStart(2, '0');
  const mm = String(now.getMinutes()).padStart(2, '0');
  document.getElementById('heroMeta').innerHTML =
    `<span>NSS = (양호−비우호)/(양호+비우호)×100</span>` +
    `<span>분석 ${n}건</span>` +
    `<span>업데이트 ${hh}:${mm} KST</span>`;

  document.getElementById('sumGood').textContent = `${goodPct}%`;
  document.getElementById('sumWarn').textContent = `${badPct}%`;
  document.getElementById('sumNeut').textContent = `${unkPct}%`;

  const today_kst = now.toLocaleDateString('ko-KR', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' });
  document.getElementById('sectionDate').textContent = today_kst;
}

// ── 7일 차트 (NSS 선 + 양호/비우호 막대 복합) ─────────────────
function renderTrendChart(trend) {
  // viewBox: 520 × 200, 중앙선 y=90 (=0점), 위 +100, 아래 -100
  const W = 520, H = 200, padX = 30, padY = 40;
  const innerH = H - padY * 2;       // 120
  const midY = H / 2;                 // 100 → 보정해서 90 (위 텍스트 공간)
  const zeroY = 90;                   // 0점 라인
  const topY = 40;                    // +100
  const botY = 140;                   // -100
  const range = botY - topY;          // 100

  function ys(score) {
    // -100 ~ +100 → botY ~ topY
    return zeroY - (score / 100) * (zeroY - topY);
  }
  function xs(i, n) {
    return padX + (i * (W - padX * 2) / Math.max(1, n - 1));
  }

  const svg = document.getElementById('trendChart');
  const barG  = svg.querySelector('#trend-bars');
  const ptG   = svg.querySelector('#trend-points');
  const lblG  = svg.querySelector('#trend-labels');
  const hovG  = svg.querySelector('#trend-hover');
  barG.innerHTML = ''; ptG.innerHTML = ''; lblG.innerHTML = ''; hovG.innerHTML = '';

  const tooltip = document.getElementById('trendTooltip');

  // 일별 카운트 최대값 (막대 높이 정규화)
  const maxCount = Math.max(1, ...trend.map(d => Math.max(d.good || 0, d.bad || 0)));
  const barMaxH = 35; // 막대 최대 높이

  // 1) 막대 (양호: 0선 위쪽 초록, 비우호: 0선 아래쪽 빨강)
  trend.forEach((d, i) => {
    const x = xs(i, trend.length);
    const barW = 14;
    if (d.good) {
      const h = (d.good / maxCount) * barMaxH;
      const r = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      r.setAttribute('x', x - barW / 2);
      r.setAttribute('y', zeroY - h);
      r.setAttribute('width', barW);
      r.setAttribute('height', h);
      r.setAttribute('fill', '#10B981');
      r.setAttribute('opacity', '0.4');
      r.setAttribute('rx', '2');
      barG.appendChild(r);
    }
    if (d.bad) {
      const h = (d.bad / maxCount) * barMaxH;
      const r = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      r.setAttribute('x', x - barW / 2);
      r.setAttribute('y', zeroY);
      r.setAttribute('width', barW);
      r.setAttribute('height', h);
      r.setAttribute('fill', '#DC2626');
      r.setAttribute('opacity', '0.45');
      r.setAttribute('rx', '2');
      barG.appendChild(r);
    }
  });

  // 2) NSS 선 — score=null 인 날은 끊어 그리기 (path를 여러 segment로)
  const segments = [];
  let cur = [];
  trend.forEach((d, i) => {
    if (d.score === null) {
      if (cur.length) { segments.push(cur); cur = []; }
    } else {
      cur.push([xs(i, trend.length), ys(d.score), i, d]);
    }
  });
  if (cur.length) segments.push(cur);

  let pathD = '';
  segments.forEach(seg => {
    if (!seg.length) return;
    pathD += ` M ${seg[0][0]} ${seg[0][1]}`;
    for (let i = 0; i < seg.length - 1; i++) {
      const [x0, y0] = seg[i], [x1, y1] = seg[i + 1];
      const cx = (x0 + x1) / 2;
      pathD += ` C ${cx} ${y0}, ${cx} ${y1}, ${x1} ${y1}`;
    }
  });
  svg.querySelector('#trend-line').setAttribute('d', pathD.trim());

  // 3) 점 + 날짜 레이블 + 호버 영역
  trend.forEach((d, i) => {
    const x = xs(i, trend.length);
    const isToday = i === trend.length - 1;
    
    // 날짜 라벨
    const dt = new Date(d.date);
    const lbl = `${dt.getMonth()+1}/${dt.getDate()}`;
    const txt = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    txt.setAttribute('x', x);
    txt.setAttribute('y', H - 8);
    txt.setAttribute('text-anchor', 'middle');
    txt.setAttribute('font-size', '10');
    txt.setAttribute('fill', isToday ? '#111' : '#9CA3AF');
    txt.setAttribute('font-weight', isToday ? '600' : '400');
    txt.textContent = lbl;
    lblG.appendChild(txt);

    // 점 (score 있을 때만)
    if (d.score !== null) {
      const c = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      const r = isToday ? 6 : 4;
      c.setAttribute('cx', x);
      c.setAttribute('cy', ys(d.score));
      c.setAttribute('r', r);
      c.setAttribute('fill', isToday ? '#2563EB' : '#fff');
      c.setAttribute('stroke', '#2563EB');
      c.setAttribute('stroke-width', '2');
      ptG.appendChild(c);
    }

    // 호버 영역 (투명한 큰 사각형)
    const hover = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    hover.setAttribute('x', x - 25);
    hover.setAttribute('y', 30);
    hover.setAttribute('width', 50);
    hover.setAttribute('height', 130);
    hover.setAttribute('fill', 'transparent');
    hover.style.cursor = 'pointer';
    hover.addEventListener('mouseenter', (ev) => {
      const sign = (d.score === null) ? '—' : (d.score > 0 ? '+' : '') + d.score;
      const reliable = d.n >= 5;
      tooltip.innerHTML = `
        <div class="tt-date">${d.date}</div>
        <div class="tt-score ${d.score === null ? 'na' : (d.score >= 20 ? 'pos' : d.score >= 0 ? 'neu' : 'neg')}">${sign}</div>
        <div class="tt-n">분석 ${d.n}건${reliable ? '' : ' (표본 부족)'}</div>
        <div class="tt-detail">양호 ${d.good} · 비우호 ${d.bad}${d.unknown ? ` · 미분석 ${d.unknown}` : ''}</div>
      `;
      tooltip.style.display = 'block';
      // 위치
      const rect = svg.getBoundingClientRect();
      const px = rect.left + (x / W) * rect.width;
      const py = rect.top + 30;
      tooltip.style.left = `${px}px`;
      tooltip.style.top  = `${py + window.scrollY}px`;
    });
    hover.addEventListener('mouseleave', () => {
      tooltip.style.display = 'none';
    });
    hovG.appendChild(hover);
  });
}

// 초기 로드 + 90초마다 갱신
loadSentiment();
setInterval(loadSentiment, 90_000);

// ── WebSocket events ─────────────────────────────────────
  window.addEventListener('dabee:pipeline', (e) => {
    if (e.detail.phase === 'done' && (e.detail.result?.new ?? 0) > 0) {
      load(true); // 신규 기사 자동 반영
    }
  });

  // ── Init ─────────────────────────────────────────────────
  load(true);
})();