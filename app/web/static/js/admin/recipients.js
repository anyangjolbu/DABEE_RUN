// app/web/static/js/admin/recipients.js
// 수신자 목록 조회, 추가, 수정, 삭제 로직.

let recipients = [];

// ── 목록 로드 ──────────────────────────────────────────────
async function loadRecipients() {
  const res = await adminFetch('/api/admin/recipients');
  recipients = await res.json();
  renderTable();
}

// ── 테이블 렌더링 ──────────────────────────────────────────
function renderTable() {
  const tbody = document.getElementById('recipientBody');
  tbody.innerHTML = '';

  if (!recipients.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="muted" style="text-align:center;padding:24px;">등록된 수신자가 없습니다.</td></tr>';
    return;
  }

  recipients.forEach(r => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td class="muted">${r.id}</td>
      <td><strong>${escapeHtml(r.name)}</strong></td>
      <td><code style="font-family:var(--font-mono);font-size:12px;">${escapeHtml(r.chat_id)}</code></td>
      <td>${escapeHtml(r.role || '—')}</td>
      <td>
        <div class="perm-grid">
          ${perm(r, 'receive_tier1_warn',  'T1경고')}
          ${perm(r, 'receive_tier1_watch', 'T1주의')}
          ${perm(r, 'receive_tier1_good',  'T1양호')}
          ${perm(r, 'receive_tier2',       'T2')}
          ${perm(r, 'receive_tier3',       'T3')}
          ${perm(r, 'receive_daily_report','일간')}
        </div>
      </td>
      <td>
        <label class="toggle">
          <input type="checkbox" class="enabled-toggle" data-id="${r.id}" ${r.enabled ? 'checked' : ''} />
          <span class="toggle-track"></span>
        </label>
      </td>
      <td>
        <button class="btn btn-danger" style="padding:4px 10px;font-size:12px;" data-del="${r.id}">삭제</button>
      </td>
    `;
    tbody.appendChild(tr);
  });

  // 활성화 토글
  tbody.querySelectorAll('.enabled-toggle').forEach(cb => {
    cb.addEventListener('change', async (e) => {
      const id = parseInt(e.target.dataset.id);
      await patch(id, { enabled: e.target.checked ? 1 : 0 });
      toast(e.target.checked ? '활성화됨' : '비활성화됨');
    });
  });

  // 권한 체크박스
  tbody.querySelectorAll('input[data-perm]').forEach(cb => {
    cb.addEventListener('change', async (e) => {
      const id    = parseInt(e.target.dataset.id);
      const field = e.target.dataset.perm;
      await patch(id, { [field]: e.target.checked ? 1 : 0 });
    });
  });

  // 삭제
  tbody.querySelectorAll('[data-del]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const id = parseInt(btn.dataset.del);
      const r  = recipients.find(x => x.id === id);
      if (!confirm(`"${r?.name}" 수신자를 삭제하시겠습니까?`)) return;
      const res = await adminFetch(`/api/admin/recipients/${id}`, { method: 'DELETE' });
      if (res.ok) { toast('삭제 완료'); loadRecipients(); }
      else         { toast('삭제 실패', 'err'); }
    });
  });
}

function perm(r, field, label) {
  return `<label class="perm-item">
    <input type="checkbox" data-perm="${field}" data-id="${r.id}" ${r[field] ? 'checked' : ''} />
    ${label}
  </label>`;
}

async function patch(id, body) {
  await adminFetch(`/api/admin/recipients/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

// ── 추가 모달 ──────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  loadRecipients();

  const modal     = document.getElementById('addModal');
  const addForm   = document.getElementById('addForm');

  document.getElementById('addBtn').addEventListener('click', () => {
    modal.classList.remove('hidden');
    document.getElementById('fChatId').focus();
  });
  document.getElementById('modalClose').addEventListener('click', () => {
    modal.classList.add('hidden');
    addForm.reset();
  });
  modal.addEventListener('click', (e) => {
    if (e.target === modal) { modal.classList.add('hidden'); addForm.reset(); }
  });

  addForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const submitBtn = addForm.querySelector('button[type=submit]');
    submitBtn.disabled = true;

    const data = {
      chat_id: document.getElementById('fChatId').value.trim(),
      name:    document.getElementById('fName').value.trim(),
      role:    document.getElementById('fRole').value.trim(),
      permissions: {
        receive_tier1_warn:   document.getElementById('pT1w').checked   ? 1 : 0,
        receive_tier1_watch:  document.getElementById('pT1wa').checked  ? 1 : 0,
        receive_tier1_good:   document.getElementById('pT1g').checked   ? 1 : 0,
        receive_tier2:        document.getElementById('pT2').checked    ? 1 : 0,
        receive_tier3:        document.getElementById('pT3').checked    ? 1 : 0,
        receive_daily_report: document.getElementById('pDaily').checked ? 1 : 0,
      },
    };

    const res = await adminFetch('/api/admin/recipients', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });

    submitBtn.disabled = false;
    if (res.ok) {
      toast('수신자 추가 완료');
      modal.classList.add('hidden');
      addForm.reset();
      loadRecipients();
    } else {
      const d = await res.json().catch(() => ({}));
      toast(d.detail || '추가 실패', 'err');
    }
  });
});
