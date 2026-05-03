// Report page: accordion list of daily reports.
(function () {
  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c =>
      ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]));
  }

  async function loadReports() {
    const list    = document.getElementById('reportList');
    const emptyEl = document.getElementById('emptyMsg');
    try {
      const reports = await fetch('/api/reports').then(r => r.json());
      if (!reports.length) { if (emptyEl) emptyEl.style.display = 'block'; return; }

      reports.forEach(r => {
        const card = document.createElement('div');
        card.className = 'report-card';

        const rcpt = r.recipients_count != null ? `${r.recipients_count}명 수신` : '';

        card.innerHTML = `
          <div class="report-card-head" role="button" tabindex="0" aria-expanded="false">
            <span class="report-date">${esc(r.report_date)}</span>
            <span class="report-count">${rcpt}</span>
            <span class="report-chevron">▾</span>
          </div>
          <div class="report-body"></div>
        `;
        list.appendChild(card);

        const head = card.querySelector('.report-card-head');
        const body = card.querySelector('.report-body');
        let loaded = false;

        const toggle = async () => {
          const open = card.classList.toggle('open');
          head.setAttribute('aria-expanded', open);
          if (!open || loaded) return;
          loaded = true;
          body.textContent = '불러오는 중…';
          try {
            const data = await fetch(`/api/reports/${r.report_date}`).then(res => res.json());
            body.textContent = data.body || '(내용 없음)';
          } catch {
            body.textContent = '불러오기 실패';
          }
        };

        head.addEventListener('click', toggle);
        head.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') toggle(); });
      });
    } catch(e) {
      console.error('[report] 로드 실패', e);
      if (list) list.innerHTML = '<div class="muted" style="text-align:center;padding:40px;">불러오기 실패</div>';
    }
  }

  document.addEventListener('DOMContentLoaded', loadReports);
})();
