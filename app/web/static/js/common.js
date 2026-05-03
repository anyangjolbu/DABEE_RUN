// app/web/static/js/common.js
// 모든 페이지 공통: WebSocket 연결, 헤더 상태 표시, 이벤트 디스패치.

(function () {
  const pill = document.getElementById('statusPill');
  const pillLabel = pill?.querySelector('.label');
  const setPill = (cls, text) => {
    if (!pill) return;
    pill.classList.remove('connected', 'running');
    if (cls) pill.classList.add(cls);
    if (pillLabel) pillLabel.textContent = text;
  };

  let ws = null;
  let reconnectTimer = null;

  function connect() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws`);

    ws.onopen = () => {
      setPill('connected', '대기중');
      console.log('[ws] connected');
    };

    ws.onmessage = (e) => {
      let payload;
      try { payload = JSON.parse(e.data); }
      catch { return; }

      // 글로벌 이벤트로 디스패치 → 각 페이지 JS가 listen
      window.dispatchEvent(new CustomEvent('dabee:' + payload.type, { detail: payload }));

      if (payload.type === 'scheduler') {
        const phase = payload.data?.phase;
        if (phase === 'running') setPill('running', '수집중');
        else if (phase === 'idle') setPill('connected', '대기중');
        else if (phase === 'stopped') setPill('', '정지');
      } else if (payload.type === 'pipeline') {
        if (payload.phase === 'start') setPill('running', '수집중');
        else if (payload.phase === 'done' || payload.phase === 'error') setPill('connected', '대기중');
      }
    };

    ws.onclose = () => {
      setPill('', '연결 끊김');
      console.log('[ws] disconnected, retry in 3s');
      reconnectTimer = setTimeout(connect, 3000);
    };

    ws.onerror = (e) => {
      console.warn('[ws] error', e);
      ws.close();
    };
  }

  connect();
})();
