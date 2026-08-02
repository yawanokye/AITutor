const state = {
  config: null,
  sessionId: localStorage.getItem('aiTutorSessionId') || crypto.randomUUID(),
  imageFile: null,
  mediaRecorder: null,
  audioChunks: [],
  recordingStream: null,
  lastAnswer: '',
  lastAudioUrl: null,
  chatLog: []
};
localStorage.setItem('aiTutorSessionId', state.sessionId);

const el = id => document.getElementById(id);
const messages = el('messages');
const question = el('question');
const sendButton = el('sendButton');
const recordButton = el('recordButton');
const composerStatus = el('composerStatus');
const audioPlayer = el('audioPlayer');
const visualTutor = el('visualTutor');
const voiceWave = el('voiceWave');

function setStatus(text, busy = false) {
  composerStatus.textContent = text;
  sendButton.disabled = busy;
  recordButton.disabled = busy;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function renderMarkdown(text) {
  let html = escapeHtml(text);
  html = html.replace(/```([\s\S]*?)```/g, (_, code) => `<pre><code>${code.trim()}</code></pre>`);
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  html = html.replace(/^### (.*)$/gm, '<h3>$1</h3>');
  html = html.replace(/^## (.*)$/gm, '<h2>$1</h2>');
  html = html.replace(/^# (.*)$/gm, '<h2>$1</h2>');
  html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/^\s*[-•] (.*)$/gm, '<li>$1</li>');
  html = html.replace(/(<li>.*<\/li>\n?)+/g, match => `<ul>${match}</ul>`);
  html = html.replace(/^\s*(\d+)\. (.*)$/gm, '<li>$2</li>');
  html = html.replace(/\n{2,}/g, '</p><p>');
  html = html.replace(/\n/g, '<br>');
  if (!html.startsWith('<h') && !html.startsWith('<ul') && !html.startsWith('<pre')) html = `<p>${html}</p>`;
  return html;
}

function scrollMessages() {
  messages.scrollTo({ top: messages.scrollHeight, behavior: 'smooth' });
}

function addMessage(role, text, sources = []) {
  const article = document.createElement('article');
  article.className = `message ${role}`;
  const label = role === 'user' ? 'You' : 'AI Tutor';
  const avatar = role === 'user' ? 'Y' : 'T';
  const sourceHtml = sources.length
    ? `<div class="source-chips">${sources.map(s => `<span class="source-chip">${escapeHtml(s)}</span>`).join('')}</div>`
    : '';
  const actions = role === 'assistant'
    ? `<div class="message-actions"><button class="mini-button speak-message" type="button">🔊 Read aloud</button><button class="mini-button copy-message" type="button">Copy</button></div>`
    : '';

  article.innerHTML = `
    <div class="message-avatar">${avatar}</div>
    <div class="message-content">
      <div class="message-label">${label}</div>
      <div class="message-body">${renderMarkdown(text)}</div>
      ${sourceHtml}${actions}
    </div>`;
  article.dataset.rawText = text;
  messages.appendChild(article);

  article.querySelector('.speak-message')?.addEventListener('click', () => speakText(text));
  article.querySelector('.copy-message')?.addEventListener('click', async event => {
    await navigator.clipboard.writeText(text);
    event.target.textContent = 'Copied';
    setTimeout(() => event.target.textContent = 'Copy', 1200);
  });

  state.chatLog.push({ role, text, sources, at: new Date().toISOString() });
  scrollMessages();
  if (window.MathJax?.typesetPromise) window.MathJax.typesetPromise([article]).catch(() => {});
}

function showTyping() {
  const article = document.createElement('article');
  article.id = 'typingMessage';
  article.className = 'message assistant';
  article.innerHTML = `<div class="message-avatar">T</div><div class="message-content"><div class="message-label">AI Tutor</div><div class="message-body">Thinking carefully…</div></div>`;
  messages.appendChild(article);
  scrollMessages();
}

function hideTyping() {
  el('typingMessage')?.remove();
}

async function apiJson(url, options = {}) {
  const response = await fetch(url, options);
  let data;
  try { data = await response.json(); } catch { data = {}; }
  if (!response.ok) throw new Error(data.detail || `Request failed with status ${response.status}`);
  return data;
}

async function loadConfig() {
  try {
    const config = await apiJson('/api/config');
    state.config = config;
    document.title = config.app_name;
    el('appName').textContent = config.app_name;
    el('mobileAppName').textContent = config.app_name;
    const voiceSelect = el('voice');
    voiceSelect.innerHTML = config.voices.map(v => `<option value="${v}" ${v === config.default_voice ? 'selected' : ''}>${v[0].toUpperCase() + v.slice(1)}</option>`).join('');
    el('connectionDot').classList.add('online');
    el('statusText').textContent = config.openai_enabled ? 'AI services connected' : 'Demonstration mode';
    el('modeNote').textContent = config.openai_enabled ? 'Text, image and audio enabled' : 'Add an OpenAI API key on Render';
    if (!config.openai_enabled) el('autoSpeak').checked = false;
  } catch (error) {
    el('connectionDot').classList.add('offline');
    setStatus(error.message);
  }
}

async function loadMaterials() {
  try {
    const data = await apiJson('/api/materials');
    const list = el('materialList');
    list.innerHTML = data.materials.length
      ? data.materials.map(item => `<div class="material-item">${escapeHtml(item.source)} · ${item.chunks} extracts</div>`).join('')
      : '<div class="material-item">No course materials uploaded.</div>';
  } catch (error) {
    el('materialStatus').textContent = error.message;
  }
}

async function sendQuestion() {
  const text = question.value.trim();
  if (!text && !state.imageFile) {
    setStatus('Enter a question or attach an image.');
    return;
  }

  const displayText = text || 'Please explain the attached image.';
  addMessage('user', displayText);
  question.value = '';
  setStatus('Preparing your explanation…', true);
  showTyping();

  const form = new FormData();
  form.append('message', text);
  form.append('session_id', state.sessionId);
  form.append('level', el('level').value);
  form.append('tutor_mode', el('tutorMode').value);
  form.append('course', el('course').value.trim());
  if (state.imageFile) form.append('image', state.imageFile, state.imageFile.name);

  clearImage();
  try {
    const data = await apiJson('/api/chat', { method: 'POST', body: form });
    state.sessionId = data.session_id;
    localStorage.setItem('aiTutorSessionId', state.sessionId);
    hideTyping();
    addMessage('assistant', data.answer, data.sources || []);
    state.lastAnswer = data.answer;
    el('replayButton').disabled = false;
    setStatus('Ready');
    if (el('autoSpeak').checked && state.config?.openai_enabled) await speakText(data.answer);
  } catch (error) {
    hideTyping();
    addMessage('assistant', `I could not complete that request. ${error.message}`);
    setStatus(error.message);
  } finally {
    sendButton.disabled = false;
    recordButton.disabled = false;
  }
}

async function speakText(text) {
  if (!state.config?.openai_enabled) {
    setStatus('Voice output needs OPENAI_API_KEY to be configured.');
    return;
  }
  setStatus('Generating the tutor voice…', true);
  try {
    const response = await fetch('/api/speech', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, voice: el('voice').value })
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.detail || 'Voice generation failed.');
    }
    const blob = await response.blob();
    if (state.lastAudioUrl) URL.revokeObjectURL(state.lastAudioUrl);
    state.lastAudioUrl = URL.createObjectURL(blob);
    audioPlayer.src = state.lastAudioUrl;
    audioPlayer.hidden = false;
    await audioPlayer.play();
    setStatus('Reading the answer aloud');
  } catch (error) {
    setStatus(error.message);
  } finally {
    sendButton.disabled = false;
    recordButton.disabled = false;
  }
}

function setSpeaking(active) {
  visualTutor.classList.toggle('speaking', active);
  voiceWave.classList.toggle('speaking', active);
}
audioPlayer.addEventListener('play', () => setSpeaking(true));
audioPlayer.addEventListener('pause', () => setSpeaking(false));
audioPlayer.addEventListener('ended', () => { setSpeaking(false); setStatus('Ready'); });

async function toggleRecording() {
  if (state.mediaRecorder?.state === 'recording') {
    state.mediaRecorder.stop();
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    setStatus('This browser does not support microphone recording.');
    return;
  }
  if (!state.config?.openai_enabled) {
    setStatus('Audio transcription needs OPENAI_API_KEY to be configured.');
    return;
  }

  try {
    state.recordingStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const preferred = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : '';
    state.mediaRecorder = new MediaRecorder(state.recordingStream, preferred ? { mimeType: preferred } : undefined);
    state.audioChunks = [];
    state.mediaRecorder.addEventListener('dataavailable', event => { if (event.data.size) state.audioChunks.push(event.data); });
    state.mediaRecorder.addEventListener('stop', transcribeRecording);
    state.mediaRecorder.start();
    recordButton.classList.add('recording');
    el('recordIcon').textContent = '■';
    el('recordLabel').textContent = 'Stop';
    setStatus('Recording your question…');
  } catch (error) {
    setStatus(`Microphone access failed. ${error.message}`);
  }
}

async function transcribeRecording() {
  recordButton.classList.remove('recording');
  el('recordIcon').textContent = '🎙';
  el('recordLabel').textContent = 'Record';
  state.recordingStream?.getTracks().forEach(track => track.stop());

  const mime = state.mediaRecorder?.mimeType || 'audio/webm';
  const blob = new Blob(state.audioChunks, { type: mime });
  if (!blob.size) {
    setStatus('No audio was captured.');
    return;
  }
  setStatus('Transcribing your voice…', true);
  const form = new FormData();
  form.append('audio', blob, 'question.webm');
  try {
    const data = await apiJson('/api/transcribe', { method: 'POST', body: form });
    question.value = [question.value.trim(), data.text].filter(Boolean).join(' ');
    question.focus();
    setStatus('Voice question transcribed. Review it, then ask the tutor.');
  } catch (error) {
    setStatus(error.message);
  } finally {
    sendButton.disabled = false;
    recordButton.disabled = false;
  }
}

function previewImage(file) {
  if (!file) return;
  if (!file.type.startsWith('image/')) {
    setStatus('Select a JPG, PNG, WEBP or GIF image.');
    return;
  }
  if (state.config && file.size > state.config.max_image_mb * 1024 * 1024) {
    setStatus(`Images must be no larger than ${state.config.max_image_mb} MB.`);
    return;
  }
  state.imageFile = file;
  el('imagePreview').src = URL.createObjectURL(file);
  el('imagePreviewWrap').classList.remove('hidden');
  setStatus('Image attached. Add a question or ask the tutor to explain it.');
}

function clearImage() {
  state.imageFile = null;
  el('imageInput').value = '';
  const image = el('imagePreview');
  if (image.src) URL.revokeObjectURL(image.src);
  image.src = '';
  el('imagePreviewWrap').classList.add('hidden');
}

async function uploadMaterials() {
  const files = [...el('materialFiles').files];
  const adminKey = el('adminKey').value;
  if (!adminKey || !files.length) {
    el('materialStatus').textContent = 'Enter the administrator key and select at least one file.';
    return;
  }
  const form = new FormData();
  form.append('admin_key', adminKey);
  files.forEach(file => form.append('files', file, file.name));
  el('materialStatus').textContent = 'Reading and indexing the materials…';
  try {
    const data = await apiJson('/api/materials/upload', { method: 'POST', body: form });
    const uploaded = data.uploaded.map(item => `${item.source} (${item.chunks} extracts)`).join(', ');
    const errors = data.errors.map(item => `${item.source}: ${item.error}`).join('; ');
    el('materialStatus').textContent = [uploaded && `Uploaded: ${uploaded}`, errors && `Issues: ${errors}`].filter(Boolean).join(' ');
    el('materialFiles').value = '';
    await loadMaterials();
  } catch (error) {
    el('materialStatus').textContent = error.message;
  }
}

async function clearChat() {
  try { await fetch(`/api/session/${encodeURIComponent(state.sessionId)}`, { method: 'DELETE' }); } catch {}
  state.sessionId = crypto.randomUUID();
  localStorage.setItem('aiTutorSessionId', state.sessionId);
  state.chatLog = [];
  [...messages.querySelectorAll('.message:not(.welcome-message)')].forEach(node => node.remove());
  question.value = '';
  clearImage();
  setStatus('New conversation started.');
}

function exportChat() {
  if (!state.chatLog.length) {
    setStatus('There is no conversation to export yet.');
    return;
  }
  const lines = [state.config?.app_name || 'AI Tutor', `Exported: ${new Date().toLocaleString()}`, ''];
  state.chatLog.forEach(item => {
    lines.push(item.role === 'user' ? 'STUDENT' : 'AI TUTOR');
    lines.push(item.text);
    if (item.sources?.length) lines.push(`Sources: ${item.sources.join(', ')}`);
    lines.push('');
  });
  const blob = new Blob([lines.join('\n')], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `ai-tutor-chat-${new Date().toISOString().slice(0, 10)}.txt`;
  link.click();
  URL.revokeObjectURL(url);
}

sendButton.addEventListener('click', sendQuestion);
question.addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    sendQuestion();
  }
});
recordButton.addEventListener('click', toggleRecording);
el('imageInput').addEventListener('change', event => previewImage(event.target.files[0]));
el('removeImage').addEventListener('click', clearImage);
el('uploadMaterials').addEventListener('click', uploadMaterials);
el('clearChat').addEventListener('click', clearChat);
el('exportChat').addEventListener('click', exportChat);
el('replayButton').addEventListener('click', () => state.lastAudioUrl ? audioPlayer.play() : speakText(state.lastAnswer));
document.querySelectorAll('.starter').forEach(button => button.addEventListener('click', () => {
  question.value = button.dataset.prompt;
  question.focus();
}));

const sidebar = el('sidebar');
const backdrop = el('sidebarBackdrop');
function closeSidebar() { sidebar.classList.remove('open'); backdrop.classList.add('hidden'); }
el('menuButton').addEventListener('click', () => { sidebar.classList.add('open'); backdrop.classList.remove('hidden'); });
backdrop.addEventListener('click', closeSidebar);

loadConfig();
loadMaterials();
