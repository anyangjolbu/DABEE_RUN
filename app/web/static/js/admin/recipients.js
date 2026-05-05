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
    tr.dataset.id = r.id;
    tr.innerHTML = `
      <td class="muted">${r.id}</td>
      <td><strong>${escapeHtml(r.name)}</strong></td>
      <td><code style="font-family:var(--font-mono);font-size:12px;">${escapeHtml(r.chat_id)}</code></td>
      <td>${escapeHtml(r.role || '—')}</td>
      <td>
        <div class="perm-grid">
          ${perm(r, 'receive_monitor',     'Monitor')}
          ${perm(r, 'receive_reference',   'Reference')}
          ${perm(r, 'receive_daily_report','Daily')}
        </div>
        <button class="btn btn-secondary perm-save"
                data-id="${r.id}"
                style="margin-top:8px;padding:4px 12px;font-size:12px;"
                disabled>저장</button>
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

  // 활성화 토글 (이건 즉시저장 유지)
  tbody.querySelectorAll('.enabled-toggle').forEach(cb => {
    cb.addEventListener('change', async (e) => {
      const id = parseInt(e.target.dataset.id);
      await patch(id, { enabled: e.target.checked ? 1 : 0 });
      toast(e.target.checked ? '활성화됨' : '비활성화됨');
    });
  });

  // STEP-3B-31: 권한 체크박스는 변경 추적만, 저장 버튼 클릭 시 일괄 PATCH
  tbody.querySelectorAll('input[data-perm]').forEach(cb => {
    cb.addEventListener('change', (e) => {
      const id  = parseInt(e.target.dataset.id);
      const tr  = e.target.closest('tr');
      const btn = tr.querySelector('.perm-save');
      const dirty = isPermDirty(tr, id);
      btn.disabled = !dirty;
      btn.classList.toggle('btn-primary',   dirty);
      btn.classList.toggle('btn-secondary', !dirty);
    });
  });

  // 저장 버튼
  tbody.querySelectorAll('.perm-save').forEach(btn => {
    btn.addEventListener('click', async () => {
      const id = parseInt(btn.dataset.id);
      const tr = btn.closest('tr');
      const body = {};
      tr.querySelectorAll('input[data-perm]').forEach(cb => {
        body[cb.dataset.perm] = cb.checked ? 1 : 0;
      });
      btn.disabled = true;
      btn.textContent = '저장 중...';
      const res = await adminFetch(`/api/admin/recipients/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      btn.textContent = '저장';
      if (res.ok) {
        toast('권한 저장 완료');
        // 로컬 캐시 갱신 → dirty 비교 기준 동기화
        const r = recipients.find(x => x.id === id);
        if (r) Object.assign(r, body);
        btn.classList.remove('btn-primary');
        btn.classList.add('btn-secondary');
        btn.disabled = true;
      } else {
        toast('저장 실패', 'err');
        btn.disabled = false;
      }
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

// STEP-3B-31: 권한 변경 여부 감지 (저장 버튼 활성화 토글용)
function isPermDirty(tr, id) {
  const r = recipients.find(x => x.id === id);
  if (!r) return false;
  const fields = ['receive_monitor', 'receive_reference', 'receive_daily_report'];
  for (const f of fields) {
    const cb = tr.querySelector(`input[data-perm="${f}"]`);
    if (!cb) continue;
    let cur = r[f];
    if (f === 'receive_monitor' && (cur === undefined || cur === null)) {
      cur = r.receive_tier1_warn ?? 1;
    }
    if (Boolean(cur) !== cb.checked) return true;
  }
  return false;
}

function perm(r, field, label) {
  // STEP-3B-27: receive_monitor 컬럼 없는 구 레코드는 receive_tier1_warn 값으로 표시
  let val = r[field];
  if (field === 'receive_monitor' && (val === undefined || val === null)) {
    val = r.receive_tier1_warn ?? 1;
  }
  return `<label class="perm-item">
    <input type="checkbox" data-perm="${field}" data-id="${r.id}" ${val ? 'checked' : ''} />
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
        receive_monitor:      document.getElementById('pMonitor').checked   ? 1 : 0,
        receive_reference:    document.getElementById('pReference').checked ? 1 : 0,
        receive_daily_report: document.getElementById('pDaily').checked     ? 1 : 0,
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

