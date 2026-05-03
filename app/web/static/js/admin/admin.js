// app/web/static/js/admin/admin.js
// 모든 관리자 페이지 공통: API 헬퍼, 토스트, 로그아웃.

async function adminFetch(url, options = {}) {
  options.credentials = 'same-origin';
  const res = await fetch(url, options);
  if (res.status === 401) {
    location.href = '/admin/login';
  }
  return res;
}

let _toastWrap = null;
function toast(msg, type = 'ok') {
  if (!_toastWrap) {
    _toastWrap = document.createElement('div');
    _toastWrap.className = 'toast-wrap';
    document.body.appendChild(_toastWrap);
  }
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  _toastWrap.appendChild(el);
  setTimeout(() => el.remove(), 3000);
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

document.addEventListener('DOMContentLoaded', () => {
  const btn = document.getElementById('logoutBtn');
  if (btn) {
    btn.addEventListener('click', async () => {
      await adminFetch('/api/admin/logout', { method: 'POST' });
      location.href = '/admin/login';
    });
  }
});
