/**
 * KisanLink Assistant widget -- optional floating chat/voice button.
 *
 * Purely additive: this script checks /api/assistant/status on load. If the
 * backend hasn't been given ANTHROPIC_API_KEY / SARVAM_API_KEY, it renders
 * nothing at all -- the page looks and behaves exactly as it did before this
 * script was added. Nothing else on the page is touched.
 */
(function () {
  async function init() {
    let status;
    try {
      status = await fetch('/api/assistant/status').then((r) => r.json());
    } catch (e) {
      return; // backend unreachable / older build without this route -- stay silent
    }
    if (!status || (!status.chat_enabled && !status.voice_enabled)) return;

    injectWidget(status);
  }

  function injectWidget(status) {
    const style = document.createElement('style');
    style.textContent = `
      #kl-chat-btn {
        position: fixed; bottom: 24px; right: 24px; z-index: 9999;
        width: 56px; height: 56px; border-radius: 50%;
        background: #16241c; color: #fff; border: none;
        font-size: 24px; cursor: pointer; box-shadow: 0 4px 14px rgba(0,0,0,.25);
      }
      #kl-chat-panel {
        position: fixed; bottom: 92px; right: 24px; z-index: 9999;
        width: 340px; max-width: calc(100vw - 32px); height: 440px;
        background: #fff; border-radius: 12px; box-shadow: 0 8px 30px rgba(0,0,0,.3);
        display: none; flex-direction: column; overflow: hidden;
        font-family: Arial, sans-serif;
      }
      #kl-chat-panel.open { display: flex; }
      #kl-chat-head { background: #16241c; color: #fff; padding: 12px 16px; font-weight: 600; font-size: 15px; }
      #kl-chat-msgs { flex: 1; overflow-y: auto; padding: 12px; font-size: 14px; }
      #kl-chat-msgs .kl-msg { margin-bottom: 10px; line-height: 1.4; }
      #kl-chat-msgs .kl-user { text-align: right; color: #16241c; }
      #kl-chat-msgs .kl-bot { text-align: left; color: #2d6a4f; }
      #kl-chat-input-row { display: flex; border-top: 1px solid #e5e5e5; padding: 8px; gap: 6px; }
      #kl-chat-input { flex: 1; border: 1px solid #ccc; border-radius: 6px; padding: 8px; font-size: 14px; }
      #kl-chat-send, #kl-chat-mic { border: none; background: #2d6a4f; color: #fff; border-radius: 6px; padding: 8px 10px; cursor: pointer; font-size: 14px; }
      #kl-chat-mic.recording { background: #c0392b; }
    `;
    document.head.appendChild(style);

    const btn = document.createElement('button');
    btn.id = 'kl-chat-btn';
    btn.title = 'KisanLink Assistant';
    btn.textContent = '💬';
    document.body.appendChild(btn);

    const panel = document.createElement('div');
    panel.id = 'kl-chat-panel';
    panel.innerHTML = `
      <div id="kl-chat-head">KisanLink Assistant</div>
      <div id="kl-chat-msgs"></div>
      <div id="kl-chat-input-row">
        <input id="kl-chat-input" type="text" placeholder="Ask about prices, listings..." />
        ${status.voice_enabled ? '<button id="kl-chat-mic" title="Hold and speak">🎤</button>' : ''}
        <button id="kl-chat-send">Send</button>
      </div>
    `;
    document.body.appendChild(panel);

    const msgsEl = panel.querySelector('#kl-chat-msgs');
    const inputEl = panel.querySelector('#kl-chat-input');
    const sendBtn = panel.querySelector('#kl-chat-send');
    const micBtn = panel.querySelector('#kl-chat-mic');
    let history = [];

    btn.addEventListener('click', () => panel.classList.toggle('open'));

    function addMsg(role, text) {
      const div = document.createElement('div');
      div.className = 'kl-msg ' + (role === 'user' ? 'kl-user' : 'kl-bot');
      div.textContent = text;
      msgsEl.appendChild(div);
      msgsEl.scrollTop = msgsEl.scrollHeight;
    }

    async function sendText(text) {
      if (!text.trim()) return;
      addMsg('user', text);
      history.push({ role: 'user', content: text });
      inputEl.value = '';
      addMsg('bot', '...');
      const placeholder = msgsEl.lastChild;
      try {
        const res = await fetch('/api/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: text, history: history.slice(0, -1) }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Something went wrong');
        placeholder.textContent = data.reply;
        history.push({ role: 'assistant', content: data.reply });
      } catch (e) {
        placeholder.textContent = '⚠️ ' + e.message;
      }
    }

    sendBtn.addEventListener('click', () => sendText(inputEl.value));
    inputEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') sendText(inputEl.value);
    });

    if (micBtn) {
      // Press-and-hold to talk (like a voice-message button): mic starts on
      // press, stops on release. A min hold time avoids sending near-silent
      // fractions of a second from an accidental tap.
      const MIN_RECORD_MS = 400;
      // Peak volume (0-255 scale) below this over the whole recording means
      // the mic picked up essentially nothing -- a hardware/permission issue,
      // not a transcription problem, so we say so instead of guessing.
      const SILENCE_THRESHOLD = 8;
      let recorder, chunks = [], recording = false, startedAt = 0;
      let audioCtx, analyser, levelData, levelTimer, peakLevel = 0;

      function watchLevel() {
        analyser.getByteTimeDomainData(levelData);
        let maxDev = 0;
        for (let i = 0; i < levelData.length; i++) {
          maxDev = Math.max(maxDev, Math.abs(levelData[i] - 128));
        }
        peakLevel = Math.max(peakLevel, maxDev);
      }

      async function startRecording() {
        if (recording) return;
        try {
          const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
          chunks = [];
          peakLevel = 0;
          audioCtx = new (window.AudioContext || window.webkitAudioContext)();
          analyser = audioCtx.createAnalyser();
          audioCtx.createMediaStreamSource(stream).connect(analyser);
          levelData = new Uint8Array(analyser.fftSize);
          levelTimer = setInterval(watchLevel, 100);
          recorder = new MediaRecorder(stream);
          recorder.ondataavailable = (e) => chunks.push(e.data);
          recorder.onstop = async () => {
            stream.getTracks().forEach((t) => t.stop());
            clearInterval(levelTimer);
            audioCtx.close();
            const heldMs = Date.now() - startedAt;
            if (heldMs < MIN_RECORD_MS) {
              addMsg('bot', '⚠️ Hold the mic button while you speak, then release.');
              return;
            }
            if (peakLevel < SILENCE_THRESHOLD) {
              addMsg('bot', "⚠️ Didn't pick up any sound from your microphone -- check it isn't muted "
                + 'and that this site is using the right input device in your browser/OS mic settings.');
              return;
            }
            const blob = new Blob(chunks, { type: 'audio/webm' });
            const fd = new FormData();
            fd.append('audio', blob, 'voice.webm');
            addMsg('user', '🎤 (voice message)');
            addMsg('bot', '...');
            const placeholder = msgsEl.lastChild;
            try {
              const res = await fetch('/api/voice/chat', { method: 'POST', body: fd });
              const data = await res.json();
              if (!res.ok) throw new Error(data.detail || 'Voice request failed');
              placeholder.textContent = data.reply;
              if (data.audios && data.audios[0]) {
                const audio = new Audio('data:audio/wav;base64,' + data.audios[0]);
                audio.play().catch(() => {});
              }
            } catch (e) {
              placeholder.textContent = '⚠️ ' + e.message;
            }
          };
          recorder.start();
          startedAt = Date.now();
          recording = true;
          micBtn.classList.add('recording');
        } catch (e) {
          addMsg('bot', '⚠️ Microphone access denied or unavailable.');
        }
      }

      function stopRecording() {
        if (!recording) return;
        recorder.stop();
        recording = false;
        micBtn.classList.remove('recording');
      }

      micBtn.addEventListener('mousedown', startRecording);
      micBtn.addEventListener('touchstart', (e) => { e.preventDefault(); startRecording(); });
      micBtn.addEventListener('mouseup', stopRecording);
      micBtn.addEventListener('mouseleave', stopRecording);
      micBtn.addEventListener('touchend', (e) => { e.preventDefault(); stopRecording(); });
      micBtn.addEventListener('touchcancel', stopRecording);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
