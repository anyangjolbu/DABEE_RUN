// Public dashboard: hero sentiment, trend chart, article cards, section tabs.
(function () {
  const LIMIT = 12;
  let offset = 0, total = 0, pending = false;
  let currentTab = 'all';
  let allArticles = [];

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
    const h = String(d.getHours()).padStart(2, '0');
    const m = String(d.getMinutes()).padStart(2, '0');
    return `${h}:${m}`;
  }

  // ── Card builder ─────────────────────────────────────────
  function buildCard(a, idx) {
    const g = GRADS[idx % 8];
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
    if (currentTab === 'good') return items.filter(a => a.tone_level === '양호');
    if (currentTab === 'warn') return items.filter(a => a.tone_level === '경고');
    return items;
  }

  function renderCards() {
    const grid = document.getElementById('cardsGrid');
    grid.innerHTML = '';
    gradIdx = 0;
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
      computeSentiment(allArticles);
    } catch(e) { console.error('[dashboard] 로드 실패', e); }
    pending = false;
  }

  document.getElementById('loadMoreBtn')?.addEventListener('click', () => load());
  document.getElementById('newAlertBtn')?.addEventListener('click', () => {
    document.getElementById('newAlert').classList.add('hidden');
    load(true);
  });

  // ── Sentiment computation ────────────────────────────────
  function computeSentiment(items) {
    if (!items.length) return;
    let good = 0, warn = 0, watch = 0, neut = 0;
    items.forEach(a => {
      if (a.tone_level === '양호') good++;
      else if (a.tone_level === '경고') warn++;
      else if (a.tone_level === '주의') watch++;
      else neut++;
    });
    const t = items.length;
    const score = Math.round((good + 0.5 * (watch + neut)) / t * 100);
    const goodPct  = Math.round(good / t * 100);
    const warnPct  = Math.round(warn / t * 100);
    const neutPct  = 100 - goodPct - warnPct;

    // Hero
    document.getElementById('heroScore').textContent = score;
    document.getElementById('heroGood').textContent  = `${goodPct}%`;
    document.getElementById('heroWarn').textContent  = `${warnPct}%`;
    document.getElementById('trendScore').textContent = score;

    // Pill
    const pill = document.getElementById('heroPill');
    if (score >= 60) {
      pill.textContent = '오늘의 톤: 우호적';
      pill.className = 'pill positive';
    } else if (score >= 40) {
      pill.textContent = '오늘의 톤: 관망';
      pill.className = 'pill neutral';
    } else {
      pill.textContent = '오늘의 톤: 비우호';
      pill.className = 'pill negative';
    }

    // Hero title
    const titleEl = document.getElementById('heroTitle');
    if (score >= 60) {
      titleEl.innerHTML = '오늘의 SK하이닉스 여론은<br><span class="accent">긍정 흐름</span>이 우세합니다';
    } else if (score >= 40) {
      titleEl.innerHTML = '오늘의 SK하이닉스 여론은<br><span class="accent">관망 국면</span>입니다';
    } else {
      titleEl.innerHTML = '오늘의 SK하이닉스 여론은<br><span class="accent">비우호 흐름</span>이 감지됩니다';
    }

    // Desc
    document.getElementById('heroDesc').textContent =
      `총 ${t}건 분석 · 우호 ${goodPct}% · 비우호 ${warnPct}% · 중립 ${neutPct}%`;

    // Meta
    const now = new Date();
    const hh = String(now.getHours()).padStart(2, '0');
    const mm = String(now.getMinutes()).padStart(2, '0');
    document.getElementById('heroMeta').innerHTML =
      `<span>전체 기사 ${t}건</span>` +
      `<span>TIER 1 경고 ${items.filter(a => a.tier === 1 && a.tone_level === '경고').length}건</span>` +
      `<span>업데이트 ${hh}:${mm} KST</span>`;

    // Summary boxes
    document.getElementById('sumGood').textContent = `${goodPct}%`;
    document.getElementById('sumWarn').textContent = `${warnPct}%`;
    document.getElementById('sumNeut').textContent = `${neutPct}%`;

    // Section date
    const today = now.toLocaleDateString('ko-KR', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' });
    document.getElementById('sectionDate').textContent = today;

    // Trend chart with today's score
    renderTrendChart(score);
  }

  // ── Trend chart ──────────────────────────────────────────
  function renderTrendChart(todayScore) {
    // 7일치 dummy data — 오늘만 실제값
    const now = new Date();
    const data = [];
    for (let i = 6; i >= 0; i--) {
      const d = new Date(now);
      d.setDate(d.getDate() - i);
      const label = `${d.getMonth()+1}/${d.getDate()}`;
      // 최근으로 갈수록 today score 수렴
      const noise = i === 0 ? 0 : (Math.random() - 0.5) * 16;
      const base  = todayScore - i * 2;
      data.push({ date: label, score: Math.min(100, Math.max(5, Math.round(base + noise))) });
    }
    data[data.length - 1].score = todayScore;

    const W = 520, H = 160, padX = 20, padY = 20;
    const xs = i => padX + (i * (W - padX * 2) / (data.length - 1));
    const ys = v => padY + (1 - v / 100) * (H - padY * 2);
    const pts = data.map((d, i) => [xs(i), ys(d.score)]);

    let path = `M ${pts[0][0]} ${pts[0][1]}`;
    for (let i = 0; i < pts.length - 1; i++) {
      const [x0, y0] = pts[i], [x1, y1] = pts[i + 1];
      const cx = (x0 + x1) / 2;
      path += ` C ${cx} ${y0}, ${cx} ${y1}, ${x1} ${y1}`;
    }

    const svg = document.getElementById('trendChart');
    if (!svg) return;
    svg.querySelector('#trend-line').setAttribute('d', path);
    svg.querySelector('#trend-area').setAttribute('d',
      path + ` L ${pts.at(-1)[0]} ${H - padY} L ${pts[0][0]} ${H - padY} Z`);

    const gp = svg.querySelector('#trend-points');
    const gl = svg.querySelector('#trend-labels');
    gp.innerHTML = ''; gl.innerHTML = '';

    pts.forEach(([x, y], i) => {
      const last = i === pts.length - 1;
      const c = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      c.setAttribute('cx', x); c.setAttribute('cy', y); c.setAttribute('r', last ? 6 : 4);
      c.setAttribute('fill', last ? '#38BDF8' : '#2563EB');
      gp.appendChild(c);
      const txt = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      txt.setAttribute('x', x - 14); txt.setAttribute('y', H - 4);
      txt.setAttribute('font-size', '11'); txt.setAttribute('fill', '#6B7280');
      txt.textContent = data[i].date;
      gl.appendChild(txt);
    });
  }

  // ── WebSocket events ─────────────────────────────────────
  window.addEventListener('dabee:pipeline', (e) => {
    if (e.detail.phase === 'done' && (e.detail.result?.new ?? 0) > 0) {
      document.getElementById('newAlert')?.classList.remove('hidden');
    }
  });

  // ── Init ─────────────────────────────────────────────────
  load(true);
})();
