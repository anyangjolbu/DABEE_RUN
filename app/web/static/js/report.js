// app/web/static/js/report.js
// 일간 리포트 목록 + 날짜별 내용 아코디언.

(function () {
  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => (
      { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
  }

  async function loadReports() {
    const list   = document.getElementById('reportList');
    const emptyEl = document.getElementById('emptyMsg');

    try {
      const reports = await fetch('/api/reports').then(r => r.json());

      if (!reports.length) {
        if (emptyEl) emptyEl.style.display = 'block';
        return;
      }

      reports.forEach(r => {
        const card = document.createElement('div');
        card.className = 'report-card card';

        const sentAt = r.sent_at ? r.sent_at.substring(0, 16).replace('T', ' ') : '';
        const rcpt   = r.recipients_count != null ? `${r.recipients_count}명 수신` : '';

        card.innerHTML = `
          <div class="report-header" role="button" tabindex="0">
            <div class="report-header-left">
              <strong class="report-date">${esc(r.report_date)}</strong>
              <span class="muted report-meta">${sentAt ? `발송: ${sentAt}` : ''} ${rcpt ? `| ${rcpt}` : ''}</span>
            </div>
            <span class="report-chevron">▼</span>
          </div>
          <div class="report-body hidden">
            <div class="report-loading muted">불러오는 중…</div>
          </div>
        `;
        list.appendChild(card);

        const header = card.querySelector('.report-header');
        const body   = card.querySelector('.report-body');
        const chev   = card.querySelector('.report-chevron');
        let loaded   = false;

        const toggle = async () => {
          const isOpen = !body.classList.contains('hidden');
          if (isOpen) {
            body.classList.add('hidden');
            chev.textContent = '▼';
            return;
          }
          body.classList.remove('hidden');
          chev.textContent = '▲';
          if (loaded) return;
          loaded = true;
          try {
            const data = await fetch(`/api/reports/${r.report_date}`).then(res => res.json());
            if (data.body) {
              body.innerHTML = `<pre class="report-text">${esc(data.body)}</pre>`;
            } else {
              body.innerHTML = `<p class="muted" style="padding:16px;">(내용 없음)</p>`;
            }
          } catch {
            body.innerHTML = `<p class="muted" style="padding:16px;">불러오기 실패</p>`;
          }
        };

        header.addEventListener('click', toggle);
        header.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') toggle(); });
      });
    } catch (e) {
      console.error('[report] 로드 실패', e);
      if (list) list.innerHTML = '<div class="muted" style="text-align:center;padding:32px;">불러오기 실패</div>';
    }
  }

  document.addEventListener('DOMContentLoaded', loadReports);
})();
