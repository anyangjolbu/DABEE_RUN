// Public dashboard: hero sentiment, trend chart, article cards, section tabs.
// STEP 4A-2 (옵션 A): tone_classification 기반 배지/필터 + reason 노출
(function () {
  const LIMIT = 12;
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
    if (cls === '일반')   return { tag: 'normal',  label: '일반',  strip: 'normal'  };
    if (cls === '미분석') return { tag: 'unknown', label: '미분석', strip: 'unknown' };
    return { tag: '', label: '', strip: '' };
  }

  function timeStr(dateStr) {
    if (!dateStr) return '';
    const d = new Date(dateStr);
    const h = String(d.getHours()).padStart(2, '0');
    const m = String(d.getMinutes()).padStart(2, '0');
    return `${h}:${m}`;
  }

  // ── Card builder ─────────────────────────────────────────
  function buildCard(a) {
    const meta    = classMeta(a);
    const link    = a.original_url || a.url || '#';
    const title   = a.title_clean || a.title || '';
    const press   = a.press || a.theme_label || '';
    const t       = timeStr(a.pub_date || a.collected_at);
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
    if (currentTab === 'normal')    return items.filter(a => a.tone_classification === '일반'  && (a.track || 'monitor') === 'monitor');
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
      computeSentiment(allArticles);
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

  // ── Sentiment computation (monitor 트랙 기준) ─────────────
  function computeSentiment(items) {
    if (!items.length) return;

    // monitor 트랙만 인덱스 산정 대상
    const mon = items.filter(a => (a.track || 'monitor') === 'monitor');
    let hostile = 0, normal = 0, unknown = 0;
    mon.forEach(a => {
      const c = a.tone_classification;
      if (c === '비우호')      hostile++;
      else if (c === '일반')   normal++;
      else                     unknown++;
    });

    const denom = hostile + normal;  // 미분석 제외
    const score = denom > 0
      ? Math.round((normal / denom) * 100)
      : 50;

    const monT = mon.length || 1;
    const hostilePct = Math.round(hostile / monT * 100);
    const normalPct  = Math.round(normal  / monT * 100);
    const unknownPct = Math.max(0, 100 - hostilePct - normalPct);

    // Hero
    document.getElementById('heroScore').textContent = score;
    document.getElementById('heroGood').textContent  = `${normalPct}%`;
    document.getElementById('heroWarn').textContent  = `${hostilePct}%`;
    document.getElementById('trendScore').textContent = score;

    // Pill
    const pill = document.getElementById('heroPill');
    if (hostile === 0 && normal > 0) {
      pill.textContent = '오늘의 톤: 양호';
      pill.className = 'pill positive';
    } else if (hostile <= 1) {
      pill.textContent = '오늘의 톤: 관망';
      pill.className = 'pill neutral';
    } else {
      pill.textContent = '오늘의 톤: 비우호 감지';
      pill.className = 'pill negative';
    }

    // Hero title
    const titleEl = document.getElementById('heroTitle');
    if (hostile === 0) {
      titleEl.innerHTML = '오늘의 SK하이닉스 여론은<br><span class="accent">긍정 흐름이 우세합니다</span>';
    } else if (hostile <= 1) {
      titleEl.innerHTML = '오늘의 SK하이닉스 여론은<br><span class="accent">전반적으로 관망 국면입니다</span>';
    } else {
      titleEl.innerHTML = '오늘의 SK하이닉스 여론은<br><span class="accent">비우호 흐름이 감지됩니다</span>';
    }

    // Desc
    document.getElementById('heroDesc').textContent =
      `모니터 ${mon.length}건 · 일반 ${normal}건 · 비우호 ${hostile}건 · 미분석 ${unknown}건 (참고 ${items.length - mon.length}건 별도)`;

    // Meta
    const now = new Date();
    const hh = String(now.getHours()).padStart(2, '0');
    const mm = String(now.getMinutes()).padStart(2, '0');
    document.getElementById('heroMeta').innerHTML =
      `<span>전체 ${items.length}건</span>` +
      `<span>모니터 ${mon.length}건</span>` +
      `<span>비우호 ${hostile}건</span>` +
      `<span>업데이트 ${hh}:${mm} KST</span>`;

    // Summary boxes
    document.getElementById('sumGood').textContent = `${normalPct}%`;
    document.getElementById('sumWarn').textContent = `${hostilePct}%`;
    document.getElementById('sumNeut').textContent = `${unknownPct}%`;

    // Section date
    const today = now.toLocaleDateString('ko-KR', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' });
    document.getElementById('sectionDate').textContent = today;

    // Trend chart with today's score
    renderTrendChart(score);
  }

  // ── Trend chart ──────────────────────────────────────────
  // ⚠️ 7일치 트렌드는 백엔드 데이터가 없어서 today만 실제값. STEP 4B에서 백엔드 API 추가 예정.
  function renderTrendChart(todayScore) {
    const now = new Date();
    const data = [];
    for (let i = 6; i >= 0; i--) {
      const d = new Date(now);
      d.setDate(d.getDate() - i);
      const label = `${d.getMonth()+1}/${d.getDate()}`;
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
      load(true); // 신규 기사 자동 반영
    }
  });

  // ── Init ─────────────────────────────────────────────────
  load(true);
})();