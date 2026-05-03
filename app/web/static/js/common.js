// common.js — WebSocket connection + global event dispatch (all public pages).
(function () {
  let ws = null;

  // Update the LIVE nav indicator
  function setLive(running) {
    const liveEl = document.getElementById('navLive');
    if (!liveEl) return;
    liveEl.textContent = running ? '● 수집중' : 'LIVE';
  }

  function connect() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws`);

    ws.onopen = () => {
      console.log('[ws] connected');
      setLive(false);
    };

    ws.onmessage = (e) => {
      let payload;
      try { payload = JSON.parse(e.data); } catch { return; }

      window.dispatchEvent(new CustomEvent('dabee:' + payload.type, { detail: payload }));

      if (payload.type === 'scheduler') {
        setLive(payload.data?.phase === 'running');
      } else if (payload.type === 'pipeline') {
        setLive(payload.phase === 'start');
      }
    };

    ws.onclose = () => {
      console.log('[ws] disconnected, retry in 3s');
      setTimeout(connect, 3000);
    };

    ws.onerror = () => ws.close();
  }

  connect();
})();
