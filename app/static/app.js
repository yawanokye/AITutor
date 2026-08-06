const state = {
  config: null,
  sessionId: localStorage.getItem('aiTutorSessionId') || crypto.randomUUID(),
  imageFile: null,
  imagePreviewUrl: null,
  visualImageUrl: null,
  boardAttachmentBlob: null,
  boardAttachmentUrl: null,
  boardContext: '',
  mediaRecorder: null,
  audioChunks: [],
  recordingStream: null,
  lastAnswer: '',
  lastAudioUrl: null,
  chatLog: [],
  visualPlan: null,
  visualIndex: 0,
  tool: 'pointer',
  strokes: [],
  redoStrokes: [],
  currentStroke: null,
  canvasCssWidth: 1,
  canvasCssHeight: 1,
  lessonQuestionSnapshot: null,
  lessonQuestionAnswer: '',
  lessonQuestionAudioUrl: null,
  activeLessonContext: null
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
const visualViewport = el('visualViewport');
const visualContent = el('visualContent');
const drawingCanvas = el('drawingCanvas');
const drawingContext = drawingCanvas.getContext('2d');

function setStatus(text, busy = false) {
  composerStatus.textContent = text;
  sendButton.disabled = busy;
  recordButton.disabled = busy;
}

function escapeHtml(value) {
  return String(value ?? '')
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
  article.innerHTML = `<div class="message-avatar">T</div><div class="message-content"><div class="message-label">AI Tutor</div><div class="message-body">Thinking and preparing a visual explanation…</div></div>`;
  messages.appendChild(article);
  scrollMessages();
}

function hideTyping() {
  el('typingMessage')?.remove();
}

async function apiJson(url, options = {}) {
  const response = await fetch(url, { ...options, cache: options.cache || 'no-store' });
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
    el('statusText').textContent = config.text_ai_enabled ? 'Institutional tutor connected' : 'Demonstration mode';
    el('modeNote').textContent = config.text_ai_enabled
      ? `${config.text_provider === 'deepseek' ? 'DeepSeek text tutoring' : 'OpenAI text tutoring'} • course controls enabled`
      : 'Add an AI provider key on Render';
    el('visualRequested').disabled = !config.visual_plan_enabled;
    if (!config.visual_plan_enabled) el('visualRequested').checked = false;
    if (!config.openai_enabled) el('autoSpeak').checked = false;
  } catch (error) {
    el('connectionDot').classList.add('offline');
    setStatus(error.message);
  }
}

async function loadMaterials() {
  try {
    const classId = el('materialScope')?.value || el('classSelect')?.value || '';
    const list = el('materialList');
    if (!classId) {
      if (list) list.innerHTML = '<div class="material-item">Select a course to view only that lecturer-owned course repository.</div>';
      return;
    }
    const data = await apiJson(`/api/materials?class_id=${encodeURIComponent(classId)}`);
    list.innerHTML = data.materials.length
      ? data.materials.map(item => `<div class="material-item"><strong>${escapeHtml(item.source)}</strong><br><small>${escapeHtml((item.material_type || 'course').replace('_', ' '))} · ${item.chunks} extracts · course-private</small></div>`).join('')
      : '<div class="material-item">No approved materials are available for this scope.</div>';
  } catch (error) {
    el('materialStatus').textContent = error.message;
  }
}
window.aiTutorLoadMaterials = loadMaterials;

function detachComposerImage() {
  const payload = { file: state.imageFile, url: state.imagePreviewUrl };
  state.imageFile = null;
  state.imagePreviewUrl = null;
  el('imageInput').value = '';
  el('imagePreview').src = '';
  el('imagePreviewWrap').classList.add('hidden');
  updateAttachmentTray();
  return payload;
}

function detachBoardAttachment() {
  const payload = {
    blob: state.boardAttachmentBlob,
    url: state.boardAttachmentUrl,
    context: state.boardContext
  };
  state.boardAttachmentBlob = null;
  state.boardAttachmentUrl = null;
  state.boardContext = '';
  el('boardAttachmentBar').classList.add('hidden');
  updateAttachmentTray();
  return payload;
}

async function sendQuestion() {
  const text = question.value.trim();
  if (!text && !state.imageFile && !state.boardAttachmentBlob) {
    setStatus('Enter a question, attach an image, or attach the whiteboard.');
    return;
  }

  const imagePayload = detachComposerImage();
  const boardPayload = detachBoardAttachment();
  const displayText = text || (boardPayload.blob ? 'Please explain the part I marked on the whiteboard.' : 'Please explain the attached image.');
  addMessage('user', displayText);
  question.value = '';
  setStatus('Preparing your explanation and visual board…', true);
  showTyping();

  const form = new FormData();
  form.append('message', text);
  form.append('session_id', state.sessionId);
  form.append('level', el('level').value);
  form.append('tutor_mode', el('tutorMode').value);
  form.append('course', el('course').value.trim());
  form.append('class_id', el('classSelect')?.value || '');
  form.append('learning_outcome', el('outcomeSelect')?.value || '');
  form.append('weekly_topic', el('weekSelect')?.value || '');
  form.append('delivery_mode', el('deliveryMode')?.value || 'standard');
  form.append('visual_requested', String(el('visualRequested').checked));
  form.append('visual_preference', el('visualPreference').value);
  form.append('board_context', boardPayload.context || '');
  if (imagePayload.file) form.append('image', imagePayload.file, imagePayload.file.name);
  if (boardPayload.blob) form.append('board_image', boardPayload.blob, 'whiteboard.png');

  try {
    const data = await apiJson('/api/chat', { method: 'POST', body: form });
    state.sessionId = data.session_id;
    localStorage.setItem('aiTutorSessionId', state.sessionId);
    window.aiTutorPersistCurrentCourseMemory?.();
    hideTyping();
    addMessage('assistant', data.answer, data.sources || []);
    state.lastAnswer = data.answer;
    el('replayButton').disabled = false;

    const visualImageUrl = imagePayload.url || boardPayload.url || null;
    renderVisual(data.visual, visualImageUrl);
    if (!data.visual || data.visual.kind !== 'image_annotation') {
      if (visualImageUrl) URL.revokeObjectURL(visualImageUrl);
    }

    setStatus(data.visual && data.visual.kind !== 'none' ? 'Answer and visual explanation ready' : 'Answer ready');
    if (window.innerWidth <= 960 && data.visual && data.visual.kind !== 'none') setMobileView('visual');
    if (el('autoSpeak').checked && state.config?.openai_enabled && el('deliveryMode')?.value !== 'text_only') await speakText(data.answer);
  } catch (error) {
    hideTyping();
    if (imagePayload.url) URL.revokeObjectURL(imagePayload.url);
    if (boardPayload.url) URL.revokeObjectURL(boardPayload.url);
    addMessage('assistant', `I could not complete that request. ${error.message}`);
    setStatus(error.message);
  } finally {
    sendButton.disabled = false;
    recordButton.disabled = false;
  }
}

function activeLessonContext() {
  const plan = state.visualPlan || {};
  const classOption = el('classSelect')?.selectedOptions?.[0];
  const weeklyOption = el('weekSelect')?.selectedOptions?.[0];
  const outcomeOption = el('outcomeSelect')?.selectedOptions?.[0];
  const explicit = state.activeLessonContext || {};
  const lines = [
    `Course: ${explicit.course_name || classOption?.textContent?.trim() || el('course')?.value?.trim() || 'Independent learning'}`,
    `Selected weekly topic: ${explicit.weekly_topic || weeklyOption?.textContent?.trim() || 'Not selected'}`,
    `Selected section path: ${explicit.section_path || 'Not specified'}`,
    `Selected section: ${explicit.section_title || 'Not specified'}`,
    `Selected learning outcome: ${outcomeOption?.textContent?.trim() || 'Not selected'}`,
    `Visual title: ${plan.title || 'Current visual lesson'}`,
  ];
  if (plan.kind === 'slides') {
    const slide = plan.slides?.[state.visualIndex] || {};
    lines.push(`Active slide: ${slide.title || 'Current topic'}`);
    lines.push(`Slide position: ${state.visualIndex + 1} of ${Math.max(plan.slides?.length || 1, 1)}`);
    if (slide.explanation) lines.push(`Detailed explanation: ${slide.explanation}`);
    if (slide.speaker_note) lines.push(`Lecturer notes: ${slide.speaker_note}`);
    if ((slide.bullets || []).length) lines.push(`Key ideas: ${(slide.bullets || []).join(' | ')}`);
    if (slide.equation) lines.push(`Equation: ${slide.equation}`);
    if (slide.worked_example) lines.push(`Worked example: ${slide.worked_example}`);
  } else if (plan.kind === 'steps') {
    const step = plan.steps?.[state.visualIndex] || {};
    lines.push(`Active step: ${step.title || 'Current step'}`);
    lines.push(`Step position: ${state.visualIndex + 1} of ${Math.max(plan.steps?.length || 1, 1)}`);
    if (step.explanation) lines.push(`Explanation: ${step.explanation}`);
    if (step.narration) lines.push(`Narration: ${step.narration}`);
    if (step.equation) lines.push(`Equation: ${step.equation}`);
  }
  return lines.join('\n').slice(0, 18000);
}

function lessonQuestionContextLabel() {
  const plan = state.visualPlan || {};
  const weekly = el('weekSelect')?.selectedOptions?.[0]?.textContent?.trim();
  const current = plan.kind === 'slides'
    ? plan.slides?.[state.visualIndex]?.title
    : plan.kind === 'steps'
      ? plan.steps?.[state.visualIndex]?.title
      : plan.title;
  const explicit = state.activeLessonContext || {};
  return [explicit.weekly_topic || weekly, explicit.section_title || current].filter(Boolean).join(' • ') || 'Current lesson point';
}

function resetLessonQuestionDialog() {
  el('lessonQuestionStatus').textContent = '';
  el('lessonQuestionAnswer').classList.add('hidden');
  el('lessonQuestionAnswer').innerHTML = '';
  el('readLessonQuestionAnswer').classList.add('hidden');
  el('lessonQuestionAudio').pause();
  el('lessonQuestionAudio').classList.add('hidden');
  el('lessonQuestionAudio').removeAttribute('src');
  if (state.lessonQuestionAudioUrl) URL.revokeObjectURL(state.lessonQuestionAudioUrl);
  state.lessonQuestionAudioUrl = null;
  state.lessonQuestionAnswer = '';
}

function openLessonQuestionDialog(prompt = '') {
  resetLessonQuestionDialog();
  state.lessonQuestionSnapshot = window.aiTutorPauseForLessonQuestion?.() || { wasActive: false, wasPaused: false };
  el('lessonQuestionContext').innerHTML = `<strong>${escapeHtml(lessonQuestionContextLabel())}</strong><br><span>The presentation is paused at the exact point shown behind this window.</span>`;
  el('lessonQuestionText').value = String(prompt || '').trim();
  el('lessonQuestionDialog').showModal();
  setTimeout(() => el('lessonQuestionText').focus(), 30);
}

async function playLessonQuestionAnswer() {
  const text = state.lessonQuestionAnswer.trim();
  if (!text || !state.config?.openai_enabled) return;
  const audio = el('lessonQuestionAudio');
  el('lessonQuestionStatus').textContent = 'Preparing a brief spoken clarification…';
  try {
    const response = await fetch('/api/speech', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text.slice(0, 4096), voice: el('voice').value, style: 'guided_lecture', speed: 0.96 })
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.detail || 'Voice generation failed.');
    }
    const blob = await response.blob();
    if (state.lessonQuestionAudioUrl) URL.revokeObjectURL(state.lessonQuestionAudioUrl);
    state.lessonQuestionAudioUrl = URL.createObjectURL(blob);
    audio.src = state.lessonQuestionAudioUrl;
    audio.classList.remove('hidden');
    el('lessonQuestionStatus').textContent = 'The clarification is being read. The lesson remains paused.';
    await audio.play();
  } catch (error) {
    el('lessonQuestionStatus').textContent = error.message;
  }
}

async function submitLessonQuestion() {
  const text = el('lessonQuestionText').value.trim();
  if (!text) {
    el('lessonQuestionStatus').textContent = 'Enter the exact point you want the tutor to explain.';
    return;
  }
  const button = el('submitLessonQuestion');
  button.disabled = true;
  el('lessonQuestionStatus').textContent = 'Answering within the current lesson context…';
  const form = new FormData();
  form.append('message', text);
  form.append('session_id', state.sessionId);
  form.append('level', el('level').value);
  form.append('tutor_mode', el('tutorMode').value);
  form.append('course', el('course').value.trim());
  form.append('class_id', el('classSelect')?.value || '');
  form.append('learning_outcome', el('outcomeSelect')?.value || '');
  form.append('weekly_topic', el('weekSelect')?.value || '');
  form.append('delivery_mode', el('deliveryMode')?.value || 'standard');
  form.append('visual_requested', 'false');
  form.append('visual_preference', 'none');
  form.append('lesson_context', activeLessonContext());
  form.append('follow_up_during_lesson', 'true');
  try {
    const data = await apiJson('/api/chat', { method: 'POST', body: form });
    state.sessionId = data.session_id;
    localStorage.setItem('aiTutorSessionId', state.sessionId);
    state.lessonQuestionAnswer = data.answer;
    addMessage('user', text);
    addMessage('assistant', data.answer, data.sources || []);
    window.aiTutorPersistCurrentCourseMemory?.();
    const sources = (data.sources || []).length
      ? `<div class="source-chips">${data.sources.map(source => `<span class="source-chip">${escapeHtml(source)}</span>`).join('')}</div>`
      : '';
    el('lessonQuestionAnswer').innerHTML = `${renderMarkdown(data.answer)}${sources}`;
    el('lessonQuestionAnswer').classList.remove('hidden');
    el('lessonQuestionStatus').textContent = 'Clarification ready. Continue when the point is clear.';
    if (state.config?.openai_enabled && el('deliveryMode')?.value !== 'text_only') {
      el('readLessonQuestionAnswer').classList.remove('hidden');
      await playLessonQuestionAnswer();
    }
  } catch (error) {
    el('lessonQuestionStatus').textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

function continueLessonAfterQuestion() {
  const audio = el('lessonQuestionAudio');
  audio.pause();
  el('lessonQuestionDialog').close();
  window.aiTutorResumeAfterLessonQuestion?.(state.lessonQuestionSnapshot);
  state.lessonQuestionSnapshot = null;
  setStatus('Returning to the exact point in the lesson…');
}

async function askFollowUp(prompt) {
  openLessonQuestionDialog(prompt);
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
    setStatus('Reading the explanation aloud');
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
    const candidates = [
      'audio/webm;codecs=opus',
      'audio/webm',
      'audio/mp4;codecs=mp4a.40.2',
      'audio/mp4',
      'audio/ogg;codecs=opus',
      'audio/ogg'
    ];
    const preferred = candidates.find(type => MediaRecorder.isTypeSupported(type)) || '';
    state.mediaRecorder = new MediaRecorder(
      state.recordingStream,
      preferred ? { mimeType: preferred } : undefined
    );
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

  const mime = state.mediaRecorder?.mimeType || state.audioChunks[0]?.type || 'audio/webm';
  const blob = new Blob(state.audioChunks, { type: mime });
  if (!blob.size) {
    setStatus('No audio was captured.');
    return;
  }
  setStatus('Transcribing your voice…', true);
  const baseMime = mime.split(';', 1)[0].toLowerCase();
  const extensionByMime = {
    'audio/webm': 'webm',
    'video/webm': 'webm',
    'audio/mp4': 'm4a',
    'video/mp4': 'mp4',
    'audio/ogg': 'ogg',
    'application/ogg': 'ogg',
    'audio/wav': 'wav',
    'audio/x-wav': 'wav',
    'audio/mpeg': 'mp3',
    'audio/aac': 'aac',
    'audio/flac': 'flac'
  };
  const extension = extensionByMime[baseMime] || 'webm';
  const form = new FormData();
  form.append('audio', blob, `question.${extension}`);
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

function updateAttachmentTray() {
  const hasImage = Boolean(state.imageFile);
  const hasBoard = Boolean(state.boardAttachmentBlob);
  el('attachmentTray').classList.toggle('hidden', !hasImage && !hasBoard);
}

function previewImage(file) {
  if (!file) return;
  if (!['image/jpeg', 'image/png', 'image/webp', 'image/gif'].includes(file.type)) {
    setStatus('Select a JPG, PNG, WEBP or GIF image.');
    return;
  }
  if (state.config && file.size > state.config.max_image_mb * 1024 * 1024) {
    setStatus(`Images must be no larger than ${state.config.max_image_mb} MB.`);
    return;
  }
  if (state.imagePreviewUrl) URL.revokeObjectURL(state.imagePreviewUrl);
  state.imageFile = file;
  state.imagePreviewUrl = URL.createObjectURL(file);
  el('imagePreview').src = state.imagePreviewUrl;
  el('imagePreviewWrap').classList.remove('hidden');
  updateAttachmentTray();
  setStatus('Image attached. Ask the tutor to explain, check or highlight it.');
}

function clearImage() {
  if (state.imagePreviewUrl) URL.revokeObjectURL(state.imagePreviewUrl);
  state.imageFile = null;
  state.imagePreviewUrl = null;
  el('imageInput').value = '';
  el('imagePreview').src = '';
  el('imagePreviewWrap').classList.add('hidden');
  updateAttachmentTray();
}

function removeBoardAttachment() {
  if (state.boardAttachmentUrl) URL.revokeObjectURL(state.boardAttachmentUrl);
  state.boardAttachmentBlob = null;
  state.boardAttachmentUrl = null;
  state.boardContext = '';
  el('boardAttachmentBar').classList.add('hidden');
  updateAttachmentTray();
  setStatus('Whiteboard attachment removed.');
}

async function uploadMaterials() {
  const files = [...el('materialFiles').files];
  const adminKey = el('adminKey').value;
  const classId = el('materialScope')?.value || '';
  if (!files.length) {
    el('materialStatus').textContent = 'Select at least one file.';
    return;
  }
  if (!classId && !adminKey) {
    el('materialStatus').textContent = 'Enter the administrator key for institution-wide materials, or select a class you teach.';
    return;
  }
  const form = new FormData();
  form.append('admin_key', adminKey);
  form.append('class_id', classId);
  form.append('material_type', el('materialType')?.value || 'course');
  form.append('document_type', el('documentType')?.value || 'teaching_notes');
  files.forEach(file => form.append('files', file, file.name));
  el('materialStatus').textContent = 'Reading, scoping and indexing the materials…';
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

function downloadLessonPack() {
  if (!state.chatLog.length) {
    setStatus('There is no lesson content to save yet.');
    return;
  }
  const course = el('course')?.value || 'Independent learning';
  const outcome = el('outcomeSelect')?.value || 'Not selected';
  const week = el('weekSelect')?.value || 'Not selected';
  const transcript = state.chatLog.map(item => `${item.role === 'assistant' ? 'AI TUTOR' : 'LEARNER'}\n${item.text}`).join('\n\n');
  const html = `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${escapeHtml(course)} lesson pack</title><style>body{font-family:Arial,sans-serif;max-width:820px;margin:32px auto;padding:0 20px;line-height:1.55;color:#172b26}h1{color:#0b5d4b}.meta{background:#eef6f3;padding:16px;border-radius:12px}pre{white-space:pre-wrap;font-family:inherit}</style></head><body><h1>${escapeHtml(course)} lesson pack</h1><div class="meta"><strong>Learning outcome:</strong> ${escapeHtml(outcome)}<br><strong>Weekly topic:</strong> ${escapeHtml(week)}<br><strong>Saved:</strong> ${escapeHtml(new Date().toLocaleString())}</div><pre>${escapeHtml(transcript)}</pre><p><small>AI-generated learning support. Verify important content against approved course materials.</small></p></body></html>`;
  const blob = new Blob([html], { type: 'text/html' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `ai-tutor-lesson-pack-${new Date().toISOString().slice(0,10)}.html`;
  link.click();
  URL.revokeObjectURL(url);
  setStatus('Low-data lesson pack saved.');
}


function resetVisualBoard() {
  state.visualPlan = null;
  state.visualIndex = 0;
  if (state.visualImageUrl) URL.revokeObjectURL(state.visualImageUrl);
  state.visualImageUrl = null;
  clearInk(false);
  el('visualTitle').textContent = 'Live whiteboard';
  el('visualCaption').textContent = 'The board is interactive. Select Pen or Highlight to draw over the explanation.';
  el('readVisual').disabled = true;
  el('visualNavigation').classList.add('hidden');
  visualContent.innerHTML = `
    <div class="whiteboard-empty">
      <div class="empty-icon">✦</div>
      <h3>Your visual explanation will appear here</h3>
      <p>Ask for a worked calculation, graph, comparison table, labelled diagram, image explanation or short lesson slides.</p>
    </div>`;
}

async function clearChat() {
  if (window.aiTutorClearCurrentCourseMemory) {
    await window.aiTutorClearCurrentCourseMemory({ askConfirmation: false });
    return;
  }
  try { await fetch(`/api/session/${encodeURIComponent(state.sessionId)}`, { method: 'DELETE' }); } catch {}
  state.sessionId = crypto.randomUUID();
  localStorage.setItem('aiTutorSessionId', state.sessionId);
  state.chatLog = [];
  [...messages.querySelectorAll('.message:not(.welcome-message)')].forEach(node => node.remove());
  question.value = '';
  clearImage();
  removeBoardAttachment();
  resetVisualBoard();
  setStatus('New course conversation started.');
  setMobileView('chat');
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
  if (state.visualPlan) {
    lines.push('CURRENT VISUAL PLAN');
    lines.push(JSON.stringify(state.visualPlan, null, 2));
  }
  const blob = new Blob([lines.join('\n')], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `ai-tutor-chat-${new Date().toISOString().slice(0, 10)}.txt`;
  link.click();
  URL.revokeObjectURL(url);
}

function setMobileView(view) {
  const visual = view === 'visual';
  el('contentGrid').classList.toggle('mobile-show-visual', visual);
  el('showChatView').classList.toggle('active', !visual);
  el('showVisualView').classList.toggle('active', visual);
}

function setVisualImageUrl(url) {
  if (state.visualImageUrl && state.visualImageUrl !== url) URL.revokeObjectURL(state.visualImageUrl);
  state.visualImageUrl = url;
}

function cleanStudentPresentationText(value) {
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  if (!text) return '';
  const internal = [
    /\b(?:this|the|these)\s+(?:presentation|slide(?:s| deck)?|visual(?: explanation)?|whiteboard)\s+(?:is|are|has been|have been)\s+(?:linked|aligned|connected|based)\s+(?:to|with|on)\s+(?:the\s+)?detailed\s+(?:note|notes|teaching notes)\b/i,
    /\b(?:refer|return|go back)\s+to\s+(?:the\s+)?detailed\s+(?:note|notes|teaching notes)\b/i,
  ];
  return text.split(/(?<=[.!?])\s+/).filter(sentence => !internal.some(pattern => pattern.test(sentence))).join(' ').trim();
}

function cleanKeyIdea(value) {
  const prefix = /^\s*(?:(?:week|period|session|teaching\s+week|slide|section)\s*(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty)\s*[:.)\-–—]*\s*|\d+(?:\.\d+)*(?:\s*[:.)\-–—]\s*|\s+))/i;
  let text = cleanStudentPresentationText(value);
  let previous = null;
  while (text && text !== previous) { previous = text; text = text.replace(prefix, '').trim(); }
  return text;
}

function sanitisePresentationPlan(plan) {
  if (!plan || typeof plan !== 'object') return plan;
  const copy = typeof structuredClone === 'function' ? structuredClone(plan) : JSON.parse(JSON.stringify(plan));
  copy.title = cleanStudentPresentationText(copy.title);
  copy.caption = cleanStudentPresentationText(copy.caption);
  if (copy.kind === 'slides') {
    copy.slides = (copy.slides || []).map(slide => ({
      ...slide,
      title: cleanStudentPresentationText(slide.title),
      bullets: (slide.bullets || []).map(cleanKeyIdea).filter(Boolean),
      key_terms: (slide.key_terms || []).map(cleanKeyIdea).filter(Boolean),
      explanation: cleanStudentPresentationText(slide.explanation),
      worked_example: cleanStudentPresentationText(slide.worked_example),
      check_question: cleanStudentPresentationText(slide.check_question),
      speaker_note: cleanStudentPresentationText(slide.speaker_note),
    }));
  }
  return copy;
}

function renderVisual(plan, imageUrl = null) {
  plan = sanitisePresentationPlan(plan);
  state.visualPlan = plan || null;
  state.visualIndex = 0;
  clearInk(false);

  if (!plan || plan.kind === 'none') {
    if (imageUrl) URL.revokeObjectURL(imageUrl);
    setVisualImageUrl(null);
    el('visualTitle').textContent = plan?.title || 'Live whiteboard';
    el('visualCaption').textContent = plan?.caption || 'This answer did not need a separate visual. You can still draw on the board.';
    el('readVisual').disabled = true;
    el('visualNavigation').classList.add('hidden');
    visualContent.innerHTML = `
      <div class="whiteboard-empty compact-empty">
        <div class="empty-icon">✓</div>
        <h3>Written explanation ready</h3>
        <p>${escapeHtml(plan?.caption || 'Use the conversation panel for the full explanation.')}</p>
      </div>`;
    resizeDrawingCanvas();
    return;
  }

  if (plan.kind === 'image_annotation' && imageUrl) setVisualImageUrl(imageUrl);
  else {
    if (imageUrl) URL.revokeObjectURL(imageUrl);
    setVisualImageUrl(null);
  }

  el('visualTitle').textContent = plan.title || visualKindLabel(plan.kind);
  el('visualCaption').textContent = plan.caption || 'Use the visual with the written explanation.';
  el('readVisual').disabled = false;
  renderCurrentVisual();
}

function visualKindLabel(kind) {
  return {
    steps: 'Step-by-step working',
    graph: 'Graph',
    table: 'Comparison table',
    diagram: 'Labelled diagram',
    image_annotation: 'Image explanation',
    slides: 'Lesson slides'
  }[kind] || 'Visual explanation';
}

function renderCurrentVisual() {
  const plan = state.visualPlan;
  if (!plan) return;
  const pageCount = plan.kind === 'steps' ? Math.max(plan.steps?.length || 0, 1)
    : plan.kind === 'slides' ? Math.max(plan.slides?.length || 0, 1)
      : 1;
  state.visualIndex = Math.max(0, Math.min(state.visualIndex, pageCount - 1));

  if (plan.kind === 'steps') renderStep(plan);
  else if (plan.kind === 'graph') renderGraph(plan);
  else if (plan.kind === 'table') renderTable(plan);
  else if (plan.kind === 'diagram') renderDiagram(plan);
  else if (plan.kind === 'image_annotation') renderImageAnnotation(plan);
  else if (plan.kind === 'slides') renderSlide(plan);

  const showNavigation = pageCount > 1;
  el('visualNavigation').classList.toggle('hidden', !showNavigation);
  el('visualCounter').textContent = `${state.visualIndex + 1} of ${pageCount}`;
  el('previousVisual').disabled = state.visualIndex === 0;
  el('nextVisual').disabled = state.visualIndex >= pageCount - 1;
  if (window.MathJax?.typesetPromise) window.MathJax.typesetPromise([visualContent]).catch(() => {});
  requestAnimationFrame(resizeDrawingCanvas);
}


function splitTeachingSentences(text) {
  const clean = String(text || '').replace(/\s+/g, ' ').trim();
  if (!clean) return [];
  const matches = clean.match(/[^.!?]+(?:[.!?]+|$)/g) || [clean];
  return matches.map(item => item.trim()).filter(Boolean);
}

function teachingSentenceMarkup(text, section) {
  return splitTeachingSentences(text).map((sentence, index) =>
    `<span class="teaching-sentence" data-teach-section="${escapeHtml(section)}" data-teach-sentence="${index}">${escapeHtml(sentence)}</span>`
  ).join(' ');
}

function renderStep(plan) {
  const steps = plan.steps || [];
  const step = steps[state.visualIndex] || { title: plan.title || 'Working', explanation: plan.caption || '', equation: '' };
  const equation = step.equation
    ? `<div class="board-equation teaching-section" data-teach-section-block="equation">\[${escapeHtml(step.equation)}\]</div>`
    : '';
  const extraEquations = state.visualIndex === steps.length - 1 && plan.equations?.length
    ? `<div class="equation-stack teaching-section" data-teach-section-block="extra-equations">${plan.equations.map((eq, index) => `<div data-teach-equation="${index}">\[${escapeHtml(eq)}\]</div>`).join('')}</div>`
    : '';
  const learnerPrompt = step.learner_prompt
    ? `<div class="learner-prompt teaching-section" data-teach-section-block="learner-prompt"><strong>Your turn:</strong> ${teachingSentenceMarkup(step.learner_prompt, 'learner-prompt')}</div>`
    : '';
  visualContent.innerHTML = `
    <div class="step-board">
      <div class="step-number">${state.visualIndex + 1}</div>
      <div class="step-copy">
        <span class="board-kicker">Step ${state.visualIndex + 1}</span>
        <h3 class="teaching-section" data-teach-section-block="title">${escapeHtml(step.title || `Step ${state.visualIndex + 1}`)}</h3>
        <p class="teaching-section" data-teach-section-block="explanation">${teachingSentenceMarkup(step.narration || step.explanation || '', 'explanation')}</p>
        ${equation}${extraEquations}${learnerPrompt}
      </div>
    </div>`;
}

function renderGraph(plan) {
  const series = (plan.series || []).filter(item => item.points?.length);
  const allPoints = series.flatMap(item => item.points);
  if (!allPoints.length) {
    visualContent.innerHTML = '<div class="whiteboard-empty"><h3>No graph points were returned</h3></div>';
    return;
  }

  let minX = Math.min(...allPoints.map(point => Number(point.x)));
  let maxX = Math.max(...allPoints.map(point => Number(point.x)));
  let minY = Math.min(...allPoints.map(point => Number(point.y)));
  let maxY = Math.max(...allPoints.map(point => Number(point.y)));
  if (minX === maxX) { minX -= 1; maxX += 1; }
  if (minY === maxY) { minY -= 1; maxY += 1; }
  const xPad = (maxX - minX) * 0.08;
  const yPad = (maxY - minY) * 0.1;
  minX -= xPad; maxX += xPad; minY -= yPad; maxY += yPad;

  const width = 900, height = 560, left = 95, right = 45, top = 45, bottom = 80;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const px = value => left + ((value - minX) / (maxX - minX)) * plotWidth;
  const py = value => top + plotHeight - ((value - minY) / (maxY - minY)) * plotHeight;
  const palette = ['#0b5d4b', '#2e6b9e', '#a45d19', '#7d4e9b', '#b43d5a'];

  let grid = '';
  for (let index = 0; index <= 5; index += 1) {
    const gx = left + (plotWidth * index / 5);
    const gy = top + (plotHeight * index / 5);
    const xValue = minX + ((maxX - minX) * index / 5);
    const yValue = maxY - ((maxY - minY) * index / 5);
    grid += `<line x1="${gx}" y1="${top}" x2="${gx}" y2="${top + plotHeight}" class="graph-grid" />`;
    grid += `<line x1="${left}" y1="${gy}" x2="${left + plotWidth}" y2="${gy}" class="graph-grid" />`;
    grid += `<text x="${gx}" y="${top + plotHeight + 28}" class="axis-tick" text-anchor="middle">${formatNumber(xValue)}</text>`;
    grid += `<text x="${left - 15}" y="${gy + 5}" class="axis-tick" text-anchor="end">${formatNumber(yValue)}</text>`;
  }

  let plotted = '';
  let legend = '';
  series.forEach((item, index) => {
    const colour = palette[index % palette.length];
    const points = item.points.map(point => `${px(Number(point.x))},${py(Number(point.y))}`).join(' ');
    if (item.points.length > 1) plotted += `<polyline points="${points}" fill="none" stroke="${colour}" stroke-width="4" stroke-linejoin="round" stroke-linecap="round" />`;
    item.points.forEach(point => {
      const cx = px(Number(point.x));
      const cy = py(Number(point.y));
      plotted += `<circle cx="${cx}" cy="${cy}" r="7" fill="${colour}" stroke="white" stroke-width="3" />`;
      if (point.label) plotted += `<text x="${cx + 10}" y="${cy - 10}" class="point-label">${escapeHtml(point.label)}</text>`;
    });
    legend += `<span><i style="background:${colour}"></i>${escapeHtml(item.name || `Series ${index + 1}`)}</span>`;
  });

  visualContent.innerHTML = `
    <div class="graph-board">
      <svg class="graph-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(plan.title || 'Tutor graph')}">
        ${grid}
        <line x1="${left}" y1="${top + plotHeight}" x2="${left + plotWidth}" y2="${top + plotHeight}" class="graph-axis" />
        <line x1="${left}" y1="${top}" x2="${left}" y2="${top + plotHeight}" class="graph-axis" />
        ${plotted}
        <text x="${left + plotWidth / 2}" y="${height - 20}" class="axis-label" text-anchor="middle">${escapeHtml(plan.x_label || 'x')}</text>
        <text x="25" y="${top + plotHeight / 2}" class="axis-label" text-anchor="middle" transform="rotate(-90 25 ${top + plotHeight / 2})">${escapeHtml(plan.y_label || 'y')}</text>
      </svg>
      <div class="graph-legend">${legend}</div>
    </div>`;
}

function formatNumber(value) {
  if (!Number.isFinite(value)) return '';
  const absolute = Math.abs(value);
  if ((absolute > 0 && absolute < 0.01) || absolute >= 10000) return value.toExponential(2);
  return Number(value.toFixed(2)).toString();
}

function renderTable(plan) {
  const headers = plan.table_headers || [];
  const rows = plan.table_rows || [];
  visualContent.innerHTML = `
    <div class="table-board">
      <table>
        <thead><tr>${headers.map(header => `<th>${escapeHtml(header)}</th>`).join('')}</tr></thead>
        <tbody>${rows.map(row => `<tr>${row.map(cell => `<td>${escapeHtml(cell)}</td>`).join('')}</tr>`).join('')}</tbody>
      </table>
    </div>`;
}

function renderDiagram(plan) {
  const nodes = plan.nodes || [];
  const edges = plan.edges || [];
  const byId = new Map(nodes.map(node => [node.id, node]));
  let edgeMarkup = '';
  edges.forEach(edge => {
    const source = byId.get(edge.source);
    const target = byId.get(edge.target);
    if (!source || !target) return;
    const x1 = Number(source.x), y1 = Number(source.y), x2 = Number(target.x), y2 = Number(target.y);
    const midX = (x1 + x2) / 2, midY = (y1 + y2) / 2;
    edgeMarkup += `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" class="diagram-edge" marker-end="url(#arrow)" />`;
    if (edge.label) edgeMarkup += `<text x="${midX}" y="${midY - 10}" class="edge-label" text-anchor="middle">${escapeHtml(edge.label)}</text>`;
  });

  let nodeMarkup = '';
  nodes.forEach(node => {
    const x = Number(node.x), y = Number(node.y);
    if (node.shape === 'circle') {
      nodeMarkup += `<circle cx="${x}" cy="${y}" r="75" class="diagram-node" />`;
    } else {
      const radius = node.shape === 'pill' ? 50 : 18;
      nodeMarkup += `<rect x="${x - 100}" y="${y - 48}" width="200" height="96" rx="${radius}" class="diagram-node" />`;
    }
    nodeMarkup += `<foreignObject x="${x - 86}" y="${y - 35}" width="172" height="70"><div xmlns="http://www.w3.org/1999/xhtml" class="node-label">${escapeHtml(node.label)}</div></foreignObject>`;
  });

  visualContent.innerHTML = `
    <div class="diagram-board">
      <svg viewBox="0 0 1000 1000" class="diagram-svg" role="img" aria-label="${escapeHtml(plan.title || 'Labelled diagram')}">
        <defs><marker id="arrow" markerWidth="12" markerHeight="12" refX="10" refY="6" orient="auto"><path d="M0,0 L12,6 L0,12 z" class="arrow-head" /></marker></defs>
        ${edgeMarkup}${nodeMarkup}
      </svg>
    </div>`;
}

function renderImageAnnotation(plan) {
  if (!state.visualImageUrl) {
    visualContent.innerHTML = '<div class="whiteboard-empty"><h3>The image preview is no longer available</h3><p>Upload the image again to receive positioned highlights.</p></div>';
    return;
  }
  const annotations = plan.annotations || [];
  const boxes = annotations.map((item, index) => {
    const labelY = Math.max(Number(item.y) + 30, 35);
    return `
      <g class="annotation-group">
        <rect x="${item.x}" y="${item.y}" width="${item.width}" height="${item.height}" rx="12" class="annotation-box" />
        <rect x="${item.x}" y="${Math.max(Number(item.y) - 5, 0)}" width="${Math.min(Math.max(String(item.label).length * 15 + 55, 120), 500)}" height="42" rx="10" class="annotation-label-bg" />
        <text x="${Number(item.x) + 14}" y="${labelY}" class="annotation-label">${index + 1}. ${escapeHtml(item.label)}</text>
      </g>`;
  }).join('');
  visualContent.innerHTML = `
    <div class="annotation-board">
      <div class="annotation-stage">
        <div class="annotation-image-layer">
          <img src="${escapeHtml(state.visualImageUrl)}" alt="Uploaded learning image with tutor annotations" />
          <svg viewBox="0 0 1000 1000" preserveAspectRatio="none" aria-hidden="true">${boxes}</svg>
        </div>
      </div>
      <div class="annotation-key">${annotations.map((item, index) => `<span><b>${index + 1}</b>${escapeHtml(item.label)}</span>`).join('')}</div>
    </div>`;
}

function renderSlide(plan) {
  const slide = (plan.slides || [])[state.visualIndex] || { title: plan.title || 'Lesson', bullets: [], equation: '', explanation: '', worked_example: '', key_terms: [], check_question: '', speaker_note: '' };
  const clean = value => String(value || '').replace(/\s+/g, ' ').trim();
  const explanation = clean(slide.explanation);
  const speakerNote = clean(slide.speaker_note);
  const noteBlocks = [];
  if (explanation && speakerNote) {
    const explanationLower = explanation.toLowerCase();
    const speakerLower = speakerNote.toLowerCase();
    if (explanationLower.includes(speakerLower)) {
      noteBlocks.push({ key: 'explanation', title: 'Detailed teaching notes', text: explanation });
    } else if (speakerLower.includes(explanationLower)) {
      noteBlocks.push({ key: 'speaker-note', title: 'Detailed teaching notes', text: speakerNote });
    } else {
      noteBlocks.push({ key: 'explanation', title: 'Detailed teaching notes', text: explanation });
      noteBlocks.push({ key: 'speaker-note', title: 'Lecturer explanation', text: speakerNote });
    }
  } else if (explanation) {
    noteBlocks.push({ key: 'explanation', title: 'Detailed teaching notes', text: explanation });
  } else if (speakerNote) {
    noteBlocks.push({ key: 'speaker-note', title: 'Detailed teaching notes', text: speakerNote });
  }
  if (!noteBlocks.length && (slide.bullets || []).length) {
    noteBlocks.push({ key: 'explanation', title: 'Detailed teaching notes', text: (slide.bullets || []).join('. ') });
  }

  const transcript = noteBlocks.map(block => `
    <section class="lecture-note-block teaching-section" data-teach-section-block="${escapeHtml(block.key)}">
      <h4>${escapeHtml(block.title)}</h4>
      <p>${teachingSentenceMarkup(block.text, block.key)}</p>
    </section>`).join('');

  const bulletCards = (slide.bullets || []).map((item, index) => `
    <article class="lecture-popup lecture-concept-card teaching-section" data-lecture-cue="bullet-${index}" data-teach-section-block="bullet-${index}">
      <span class="lecture-popup-label">Key idea</span>
      <p>${teachingSentenceMarkup(item, `bullet-${index}`)}</p>
    </article>`).join('');

  const equation = slide.equation ? `
    <article class="lecture-popup lecture-equation-card teaching-section" data-lecture-cue="equation" data-teach-section-block="equation">
      <span class="lecture-popup-label">On the board</span>
      <div class="slide-equation">\[${escapeHtml(slide.equation)}\]</div>
    </article>` : '';

  const example = slide.worked_example ? `
    <article class="lecture-popup lecture-example-card teaching-section" data-lecture-cue="worked-example" data-teach-section-block="worked-example">
      <span class="lecture-popup-label">Worked example or application</span>
      <p>${teachingSentenceMarkup(slide.worked_example, 'worked-example')}</p>
    </article>` : '';

  const terms = (slide.key_terms || []).length ? `
    <article class="lecture-popup lecture-terms-card teaching-section" data-lecture-cue="key-terms" data-teach-section-block="key-terms">
      <span class="lecture-popup-label">Key terms</span>
      <div class="slide-key-terms">${slide.key_terms.map((item, index) => `<span data-teach-term="${index}">${escapeHtml(item)}</span>`).join('')}</div>
    </article>` : '';

  const check = slide.check_question ? `
    <article class="lecture-popup lecture-check-card teaching-section" data-lecture-cue="check-question" data-teach-section-block="check-question">
      <span class="lecture-popup-label">Pause and check your understanding</span>
      <p>${teachingSentenceMarkup(slide.check_question, 'check-question')}</p>
    </article>` : '';

  const speakerCue = '';

  visualContent.innerHTML = `
    <div class="lesson-slide detailed-slide guided-lecture-slide">
      <header class="lecture-slide-header">
        <span class="slide-number">Current topic</span>
        <h3 class="teaching-section" data-teach-section-block="title">${escapeHtml(slide.title)}</h3>
      </header>
      <div class="guided-lecture-layout">
        <div class="lecture-notes-panel" aria-label="Detailed teaching notes">
          ${transcript || '<p class="small-note">The detailed explanation will be presented here.</p>'}
        </div>
        <aside class="lecture-visual-stage" aria-label="Teaching points that appear during the explanation">
          <div class="lecture-stage-placeholder">Important ideas, examples and equations will appear here as the tutor explains them.</div>
          ${bulletCards}${equation}${example}${terms}${check}${speakerCue}
        </aside>
      </div>
    </div>`;
}

function visualPlanToSpeech(plan) {
  if (!plan) return '';
  const intro = [plan.title, plan.caption].filter(Boolean).join('. ');
  if (plan.kind === 'steps') {
    const step = plan.steps?.[state.visualIndex];
    return [intro, `Step ${state.visualIndex + 1}`, step?.title, step?.explanation, step?.equation].filter(Boolean).join('. ');
  }
  if (plan.kind === 'slides') {
    const slide = plan.slides?.[state.visualIndex];
    return [intro, slide?.title, ...(slide?.bullets || []), slide?.explanation, slide?.equation, slide?.worked_example, ...(slide?.key_terms || []), slide?.check_question, slide?.speaker_note].filter(Boolean).join('. ');
  }
  if (plan.kind === 'table') return [intro, 'The table compares the following headings', ...(plan.table_headers || [])].filter(Boolean).join('. ');
  if (plan.kind === 'graph') return [intro, `Horizontal axis: ${plan.x_label}`, `Vertical axis: ${plan.y_label}`, ...(plan.series || []).map(item => `Series: ${item.name}`)].filter(Boolean).join('. ');
  if (plan.kind === 'diagram') return [intro, 'The diagram contains', ...(plan.nodes || []).map(node => node.label)].filter(Boolean).join('. ');
  if (plan.kind === 'image_annotation') return [intro, ...(plan.annotations || []).map((item, index) => `Marker ${index + 1}: ${item.label}`)].filter(Boolean).join('. ');
  return intro;
}

function setBoardTool(tool) {
  state.tool = tool;
  document.querySelectorAll('.board-tool[data-tool]').forEach(button => button.classList.toggle('active', button.dataset.tool === tool));
  drawingCanvas.classList.toggle('ink-active', tool !== 'pointer');
  drawingCanvas.style.cursor = tool === 'pointer' ? 'default' : tool === 'eraser' ? 'cell' : 'crosshair';
}

function resizeDrawingCanvas() {
  const rect = visualViewport.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  state.canvasCssWidth = rect.width;
  state.canvasCssHeight = rect.height;
  drawingCanvas.width = Math.round(rect.width * ratio);
  drawingCanvas.height = Math.round(rect.height * ratio);
  drawingCanvas.style.width = `${rect.width}px`;
  drawingCanvas.style.height = `${rect.height}px`;
  drawingContext.setTransform(ratio, 0, 0, ratio, 0, 0);
  redrawStrokes();
}

function redrawStrokes() {
  drawingContext.clearRect(0, 0, state.canvasCssWidth, state.canvasCssHeight);
  [...state.strokes, ...(state.currentStroke ? [state.currentStroke] : [])].forEach(drawStroke);
  el('undoInk').disabled = state.strokes.length === 0;
  el('redoInk').disabled = state.redoStrokes.length === 0;
}

function drawStroke(stroke) {
  if (!stroke.points?.length) return;
  drawingContext.save();
  drawingContext.lineCap = 'round';
  drawingContext.lineJoin = 'round';
  drawingContext.lineWidth = stroke.width;
  if (stroke.tool === 'eraser') {
    drawingContext.globalCompositeOperation = 'destination-out';
    drawingContext.strokeStyle = 'rgba(0,0,0,1)';
  } else {
    drawingContext.globalCompositeOperation = 'source-over';
    drawingContext.strokeStyle = stroke.colour;
    drawingContext.globalAlpha = stroke.tool === 'highlighter' ? 0.28 : 1;
  }
  drawingContext.beginPath();
  stroke.points.forEach((point, index) => {
    const x = point.x * state.canvasCssWidth;
    const y = point.y * state.canvasCssHeight;
    if (index === 0) drawingContext.moveTo(x, y);
    else drawingContext.lineTo(x, y);
  });
  if (stroke.points.length === 1) {
    const point = stroke.points[0];
    drawingContext.lineTo(point.x * state.canvasCssWidth + 0.1, point.y * state.canvasCssHeight + 0.1);
  }
  drawingContext.stroke();
  drawingContext.restore();
}

function canvasPoint(event) {
  const rect = drawingCanvas.getBoundingClientRect();
  return {
    x: Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
    y: Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height))
  };
}

function startStroke(event) {
  if (state.tool === 'pointer') return;
  event.preventDefault();
  drawingCanvas.setPointerCapture(event.pointerId);
  const width = state.tool === 'highlighter' ? 20 : state.tool === 'eraser' ? 28 : 3.5;
  state.currentStroke = {
    tool: state.tool,
    colour: el('penColour').value,
    width,
    points: [canvasPoint(event)]
  };
  state.redoStrokes = [];
  redrawStrokes();
}

function continueStroke(event) {
  if (!state.currentStroke) return;
  event.preventDefault();
  state.currentStroke.points.push(canvasPoint(event));
  redrawStrokes();
}

function endStroke(event) {
  if (!state.currentStroke) return;
  event.preventDefault();
  state.currentStroke.points.push(canvasPoint(event));
  state.strokes.push(state.currentStroke);
  state.currentStroke = null;
  redrawStrokes();
}

function undoInk() {
  const stroke = state.strokes.pop();
  if (stroke) state.redoStrokes.push(stroke);
  redrawStrokes();
}

function redoInk() {
  const stroke = state.redoStrokes.pop();
  if (stroke) state.strokes.push(stroke);
  redrawStrokes();
}

function clearInk(updateStatus = true) {
  state.strokes = [];
  state.redoStrokes = [];
  state.currentStroke = null;
  redrawStrokes();
  if (updateStatus) setStatus('Learner ink cleared.');
}

async function captureBoardCanvas() {
  if (!window.html2canvas) throw new Error('The board capture library is still loading. Please try again.');
  return window.html2canvas(visualViewport, {
    backgroundColor: '#ffffff',
    scale: Math.min(window.devicePixelRatio || 1, 2),
    useCORS: true,
    logging: false
  });
}

async function downloadBoard() {
  try {
    setStatus('Preparing the whiteboard image…', true);
    const canvas = await captureBoardCanvas();
    const link = document.createElement('a');
    link.download = `ai-tutor-whiteboard-${new Date().toISOString().slice(0, 10)}.png`;
    link.href = canvas.toDataURL('image/png');
    link.click();
    setStatus('Whiteboard downloaded.');
  } catch (error) {
    setStatus(error.message);
  } finally {
    sendButton.disabled = false;
    recordButton.disabled = false;
  }
}

async function attachBoardToQuestion() {
  if (!state.visualPlan && !state.strokes.length) {
    setStatus('There is no visual or learner ink to attach yet.');
    return;
  }
  try {
    setStatus('Capturing the whiteboard…', true);
    const canvas = await captureBoardCanvas();
    const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png', 0.92));
    if (!blob) throw new Error('The whiteboard could not be captured.');
    if (state.boardAttachmentUrl) URL.revokeObjectURL(state.boardAttachmentUrl);
    state.boardAttachmentBlob = blob;
    state.boardAttachmentUrl = URL.createObjectURL(blob);
    state.boardContext = JSON.stringify({
      visual: state.visualPlan,
      visible_page: state.visualIndex + 1,
      learner_ink_strokes: state.strokes.length
    });
    el('boardAttachmentBar').classList.remove('hidden');
    updateAttachmentTray();
    if (!question.value.trim()) question.value = 'Please explain the part I marked on the whiteboard.';
    setMobileView('chat');
    question.focus();
    setStatus('Whiteboard attached to your next question.');
  } catch (error) {
    setStatus(error.message);
  } finally {
    sendButton.disabled = false;
    recordButton.disabled = false;
  }
}

async function toggleFullscreenBoard() {
  const card = el('visualCard');
  try {
    if (document.fullscreenElement === card) await document.exitFullscreen();
    else if (card.requestFullscreen) await card.requestFullscreen();
    else card.classList.toggle('board-expanded');
  } catch (error) {
    card.classList.toggle('board-expanded');
    setStatus(card.classList.contains('board-expanded') ? 'Whiteboard expanded.' : 'Whiteboard restored.');
  }
  setTimeout(resizeDrawingCanvas, 100);
}

sendButton.addEventListener('click', sendQuestion);
question.addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    sendQuestion();
  }
});
question.addEventListener('paste', event => {
  const imageItem = [...(event.clipboardData?.items || [])].find(item => item.type.startsWith('image/'));
  if (!imageItem) return;
  const file = imageItem.getAsFile();
  if (file) {
    event.preventDefault();
    previewImage(file);
  }
});
recordButton.addEventListener('click', toggleRecording);
el('imageInput').addEventListener('change', event => previewImage(event.target.files[0]));
el('removeImage').addEventListener('click', clearImage);
el('removeBoardAttachment').addEventListener('click', removeBoardAttachment);
el('uploadMaterials').addEventListener('click', uploadMaterials);
el('materialScope')?.addEventListener('change', loadMaterials);
el('clearChat').addEventListener('click', clearChat);
el('exportChat').addEventListener('click', exportChat);
el('downloadLessonPack').addEventListener('click', downloadLessonPack);
el('replayButton').addEventListener('click', () => state.lastAudioUrl ? audioPlayer.play() : speakText(state.lastAnswer));
el('readVisual').addEventListener('click', () => speakText(visualPlanToSpeech(state.visualPlan)));
el('previousVisual').addEventListener('click', () => { state.visualIndex -= 1; clearInk(false); renderCurrentVisual(); });
el('nextVisual').addEventListener('click', () => { state.visualIndex += 1; clearInk(false); renderCurrentVisual(); });
el('downloadBoard').addEventListener('click', downloadBoard);
el('attachBoard').addEventListener('click', attachBoardToQuestion);
el('fullscreenBoard').addEventListener('click', toggleFullscreenBoard);
el('undoInk').addEventListener('click', undoInk);
el('redoInk').addEventListener('click', redoInk);
el('clearInk').addEventListener('click', () => clearInk(true));
el('showChatView').addEventListener('click', () => setMobileView('chat'));
el('showVisualView').addEventListener('click', () => setMobileView('visual'));
el('showMemoryView')?.addEventListener('click', () => window.aiTutorOpenMemoryManager?.());
document.querySelectorAll('.board-tool[data-tool]').forEach(button => button.addEventListener('click', () => setBoardTool(button.dataset.tool)));
drawingCanvas.addEventListener('pointerdown', startStroke);
drawingCanvas.addEventListener('pointermove', continueStroke);
drawingCanvas.addEventListener('pointerup', endStroke);
drawingCanvas.addEventListener('pointercancel', endStroke);
document.querySelectorAll('.starter').forEach(button => button.addEventListener('click', () => {
  question.value = button.dataset.prompt;
  question.focus();
}));
document.querySelectorAll('[data-lesson-followup]').forEach(button => button.addEventListener('click', () => askFollowUp(button.dataset.lessonFollowup)));
el('openLessonQuestion')?.addEventListener('click', () => openLessonQuestionDialog(''));
el('submitLessonQuestion')?.addEventListener('click', submitLessonQuestion);
el('readLessonQuestionAnswer')?.addEventListener('click', playLessonQuestionAnswer);
el('continueLessonAfterQuestion')?.addEventListener('click', continueLessonAfterQuestion);
el('closeLessonQuestion')?.addEventListener('click', continueLessonAfterQuestion);
el('lessonQuestionText')?.addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); submitLessonQuestion(); }
});
el('lessonQuestionDialog')?.addEventListener('cancel', event => { event.preventDefault(); continueLessonAfterQuestion(); });
el('lessonQuestionAudio')?.addEventListener('ended', () => {
  el('lessonQuestionStatus').textContent = 'Clarification complete. Returning to the lesson…';
  if (state.lessonQuestionSnapshot?.wasActive) setTimeout(continueLessonAfterQuestion, 850);
});
el('repeatLastExplanation')?.addEventListener('click', () => state.lastAudioUrl ? audioPlayer.play() : (state.lastAnswer ? speakText(state.lastAnswer) : setStatus('No explanation is available to repeat.')));

const sidebar = el('sidebar');
const backdrop = el('sidebarBackdrop');
function closeSidebar() { sidebar.classList.remove('open'); backdrop.classList.add('hidden'); }
el('menuButton').addEventListener('click', () => { sidebar.classList.add('open'); backdrop.classList.remove('hidden'); });
backdrop.addEventListener('click', closeSidebar);

const boardResizeObserver = new ResizeObserver(() => resizeDrawingCanvas());
boardResizeObserver.observe(visualViewport);
window.addEventListener('resize', resizeDrawingCanvas);
document.addEventListener('fullscreenchange', () => { el('visualCard')?.classList.remove('board-expanded'); setTimeout(resizeDrawingCanvas, 100); });

function applyDeliveryMode(mode = el('deliveryMode')?.value || 'standard') {
  document.body.classList.toggle('low-data-mode', mode === 'low_data');
  document.body.classList.toggle('text-only-mode', mode === 'text_only');
  if (mode === 'text_only') {
    el('visualRequested').checked = false;
    el('autoSpeak').checked = false;
    el('visualPreference').disabled = true;
  } else {
    el('visualPreference').disabled = false;
    if (mode === 'low_data') {
      el('autoSpeak').checked = false;
      el('visualRequested').checked = true;
      el('visualPreference').value = 'steps';
    }
  }
  window.dispatchEvent(new CustomEvent('ai-tutor-delivery-mode', { detail: { mode } }));
}
window.aiTutorApplyDeliveryMode = applyDeliveryMode;
window.aiTutorAddMessage = addMessage;
window.aiTutorRenderVisual = renderVisual;
window.aiTutorSetMobileView = setMobileView;
window.aiTutorSetStatus = setStatus;
window.aiTutorVisualPlanToSpeech = visualPlanToSpeech;
window.aiTutorAskFollowUp = askFollowUp;
window.aiTutorOpenLessonQuestion = openLessonQuestionDialog;
window.aiTutorSetActiveLessonContext = context => { state.activeLessonContext = context || null; window.aiTutorPersistCurrentCourseMemory?.(); };
window.aiTutorLastAnswer = () => state.lastAnswer;
el('deliveryMode')?.addEventListener('change', event => applyDeliveryMode(event.target.value));
el('classSelect')?.addEventListener('change', () => { window.aiTutorClassChanged?.(); loadMaterials(); });

setBoardTool('pointer');
loadConfig();
loadMaterials();
applyDeliveryMode();
requestAnimationFrame(resizeDrawingCanvas);
