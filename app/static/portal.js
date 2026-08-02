(() => {
  'use strict';

  const TOKEN_KEY = 'aiTutorAccessToken';
  const CLASS_KEY = 'aiTutorSelectedClass';
  const originalFetch = window.fetch.bind(window);
  const state = {
    token: localStorage.getItem(TOKEN_KEY) || '',
    user: null,
    config: null,
    classes: [],
    authMode: 'login',
  };

  window.fetch = (input, init = {}) => {
    const url = typeof input === 'string' ? input : input?.url || '';
    const sameOriginApi = url.startsWith('/api/') || url.startsWith(location.origin + '/api/');
    if (!sameOriginApi || !state.token) return originalFetch(input, init);
    const headers = new Headers(init.headers || (typeof input !== 'string' ? input.headers : undefined) || {});
    if (!headers.has('Authorization')) headers.set('Authorization', `Bearer ${state.token}`);
    return originalFetch(input, { ...init, headers });
  };

  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>'"]/g, c => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#39;', '"':'&quot;' }[c]));
  const api = async (url, options = {}) => {
    const headers = new Headers(options.headers || {});
    if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
    const response = await fetch(url, { ...options, headers });
    let data = {};
    try { data = await response.json(); } catch {}
    if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
    return data;
  };
  const openDialog = id => { const dialog = $(id); if (dialog && !dialog.open) dialog.showModal(); };
  const closeDialog = id => { const dialog = $(id); if (dialog?.open) dialog.close(); };
  const setStatus = (id, text, kind = '') => { const node = $(id); if (!node) return; node.textContent = text || ''; node.className = `small-status ${kind}`.trim(); };
  const lines = value => String(value || '').split(/\r?\n/).map(item => item.trim()).filter(Boolean);

  function selectedClass() {
    const id = $('classSelect')?.value || '';
    return state.classes.find(item => item.id === id) || null;
  }

  function knowledgeLabel(mode) {
    return {
      course_only: 'Course materials only',
      course_plus_approved: 'Course materials + approved external sources',
      general: 'Course-first + general knowledge',
    }[mode] || 'General learning mode';
  }

  function applySelectedClass() {
    const classroom = selectedClass();
    const outcome = $('outcomeSelect');
    const week = $('weekSelect');
    const outcomeLabel = $('outcomeLabel');
    const weekLabel = $('weekLabel');
    if (!classroom) {
      $('knowledgeModeBadge').textContent = 'Independent learning • general mode';
      outcome.innerHTML = '<option value="">No selected outcome</option>';
      week.innerHTML = '<option value="">No selected weekly topic</option>';
      outcomeLabel.classList.add('hidden');
      weekLabel.classList.add('hidden');
      return;
    }
    $('course').value = classroom.subject || classroom.name;
    $('knowledgeModeBadge').textContent = `${classroom.name} • ${knowledgeLabel(classroom.knowledge_mode)}`;
    const outcomes = classroom.learning_outcomes || [];
    const weeks = classroom.weekly_topics || [];
    outcome.innerHTML = outcomes.length
      ? outcomes.map(item => `<option value="${esc(item)}">${esc(item)}</option>`).join('')
      : '<option value="">No learning outcomes configured</option>';
    week.innerHTML = weeks.length
      ? weeks.map(item => `<option value="${esc(item)}">${esc(item)}</option>`).join('')
      : '<option value="">No weekly topics configured</option>';
    outcomeLabel.classList.toggle('hidden', !outcomes.length);
    weekLabel.classList.toggle('hidden', !weeks.length);
    localStorage.setItem(CLASS_KEY, classroom.id);
  }
  window.aiTutorClassChanged = applySelectedClass;

  function fillClassSelectors() {
    const selected = localStorage.getItem(CLASS_KEY) || '';
    const options = state.classes.map(item => `<option value="${esc(item.id)}">${esc(item.name)}${item.subject ? ` • ${esc(item.subject)}` : ''}</option>`).join('');
    if ($('classSelect')) {
      $('classSelect').innerHTML = `<option value="">Independent learning</option>${options}`;
      if (state.classes.some(item => item.id === selected)) $('classSelect').value = selected;
    }
    const teacherClasses = state.user?.role === 'teacher' || state.user?.role === 'admin' ? state.classes : [];
    if ($('materialScope')) {
      $('materialScope').innerHTML = `<option value="">Institution-wide materials</option>${teacherClasses.map(item => `<option value="${esc(item.id)}">${esc(item.name)}</option>`).join('')}`;
      if (teacherClasses.some(item => item.id === selected)) $('materialScope').value = selected;
    }
    if ($('lessonVideoClass')) {
      $('lessonVideoClass').innerHTML = `<option value="">Select a class</option>${teacherClasses.map(item => `<option value="${esc(item.id)}">${esc(item.name)}</option>`).join('')}`;
      if (teacherClasses.some(item => item.id === selected)) $('lessonVideoClass').value = selected;
    }
    applySelectedClass();
    window.aiTutorLoadMaterials?.();
  }

  async function loadClasses() {
    if (!state.user) {
      state.classes = [];
      fillClassSelectors();
      return;
    }
    try { state.classes = await api('/api/classes'); }
    catch { state.classes = []; }
    fillClassSelectors();
  }

  function updateAccountUI() {
    const signedIn = Boolean(state.user);
    $('signedOutActions')?.classList.toggle('hidden', signedIn);
    $('signedInActions')?.classList.toggle('hidden', !signedIn);
    $('accountRoleBadge')?.classList.toggle('hidden', !signedIn);
    if (signedIn) {
      $('accountName').textContent = state.user.display_name;
      $('accountRoleBadge').textContent = state.user.role;
    }
    if ($('openLessonVideo')) {
      $('openLessonVideo').disabled = !signedIn;
      $('openLessonVideo').title = signedIn ? 'Open reusable lessons assigned to your classes' : 'Sign in to view class lessons';
    }
    const teacher = signedIn && ['teacher', 'admin'].includes(state.user.role);
    $('lessonVideoCreator')?.classList.toggle('hidden', !teacher);
  }

  async function loadConfig() {
    try {
      state.config = await api('/api/config');
      const provider = state.config.text_provider === 'deepseek' ? 'DeepSeek' : 'OpenAI';
      $('providerBadge').textContent = `${provider} ${state.config.default_text_model || ''} • institutional routing`;
    } catch {
      $('providerBadge').textContent = 'AI provider status unavailable';
    }
    updateAccountUI();
  }

  async function restoreUser() {
    if (!state.token) {
      updateAccountUI();
      await loadClasses();
      return;
    }
    try { state.user = await api('/api/auth/me'); }
    catch {
      state.token = '';
      state.user = null;
      localStorage.removeItem(TOKEN_KEY);
    }
    updateAccountUI();
    await loadClasses();
  }

  function setAuthMode(mode) {
    state.authMode = mode;
    const registering = mode === 'register';
    $('authTitle').textContent = registering ? 'Create account' : 'Sign in';
    $('submitAuth').textContent = registering ? 'Create account' : 'Sign in';
    $('showLogin').classList.toggle('active', !registering);
    $('showRegister').classList.toggle('active', registering);
    $('displayNameLabel').classList.toggle('hidden', !registering);
    $('roleLabel').classList.toggle('hidden', !registering);
    $('authPassword').autocomplete = registering ? 'new-password' : 'current-password';
    updateTeacherCodeVisibility();
    setStatus('authStatus', '');
  }

  function updateTeacherCodeVisibility() {
    const show = state.authMode === 'register' && $('authRole')?.value === 'teacher';
    $('teacherCodeLabel')?.classList.toggle('hidden', !show);
  }

  async function submitAuth(event) {
    event.preventDefault();
    setStatus('authStatus', 'Please wait…');
    const body = { email: $('authEmail').value.trim(), password: $('authPassword').value };
    let endpoint = '/api/auth/login';
    if (state.authMode === 'register') {
      endpoint = '/api/auth/register';
      Object.assign(body, {
        display_name: $('authDisplayName').value.trim(),
        role: $('authRole').value,
        teacher_invite_code: $('teacherInviteCode').value,
      });
    }
    try {
      const data = await api(endpoint, { method: 'POST', body: JSON.stringify(body) });
      state.token = data.access_token;
      state.user = data.user;
      localStorage.setItem(TOKEN_KEY, state.token);
      updateAccountUI();
      await loadClasses();
      closeDialog('authDialog');
      $('authForm').reset();
      setAuthMode('login');
    } catch (error) { setStatus('authStatus', error.message, 'error'); }
  }

  function summaryCards(summary) {
    return Object.entries(summary || {}).map(([key, value]) => `<div class="metric-card"><strong>${esc(value ?? '—')}</strong><span>${esc(key.replaceAll('_',' '))}</span></div>`).join('');
  }

  function renderRows(items, renderer, empty = 'No records yet.') {
    return items?.length ? `<div class="data-list">${items.map(renderer).join('')}</div>` : `<p class="small-note">${esc(empty)}</p>`;
  }

  function classProfileForm(item) {
    return `<details class="class-profile" data-profile="${esc(item.id)}"><summary>Configure course lock and outcomes</summary>
      <div class="profile-form">
        <label>Class name<input data-field="name" value="${esc(item.name)}"></label>
        <label>Subject<input data-field="subject" value="${esc(item.subject || '')}"></label>
        <label>Knowledge setting<select data-field="knowledge_mode">
          <option value="course_only" ${item.knowledge_mode === 'course_only' ? 'selected' : ''}>Course materials only</option>
          <option value="course_plus_approved" ${item.knowledge_mode === 'course_plus_approved' ? 'selected' : ''}>Course + approved external</option>
          <option value="general" ${item.knowledge_mode === 'general' ? 'selected' : ''}>Course-first + general knowledge</option>
        </select></label>
        <label>Learning outcomes, one per line<textarea data-field="learning_outcomes" rows="5">${esc((item.learning_outcomes || []).join('\n'))}</textarea></label>
        <label>Weekly topics, one per line<textarea data-field="weekly_topics" rows="5">${esc((item.weekly_topics || []).join('\n'))}</textarea></label>
        <label>Lecturer instructions<textarea data-field="tutor_instructions" rows="4">${esc(item.tutor_instructions || '')}</textarea></label>
        <button class="primary" type="button" data-save-profile="${esc(item.id)}">Save course profile</button>
        <div class="small-status" data-profile-status="${esc(item.id)}"></div>
      </div></details>`;
  }

  function renderDashboard(data) {
    const isTeacher = data.role === 'teacher';
    const classes = renderRows(data.classes, item => `<div class="data-row class-row"><div><strong>${esc(item.name)}</strong><br><small>${esc(item.subject || item.teacher_name || '')} • ${esc(knowledgeLabel(item.knowledge_mode))}</small></div><div><small>${isTeacher ? `${esc(item.student_count)} students` : esc(item.teacher_name)}</small>${isTeacher ? `<br><strong>${esc(item.join_code)}</strong>` : ''}</div></div>${isTeacher ? classProfileForm(item) : ''}`, 'No classes yet.');
    const weak = renderRows(data.weak_topics, item => `<div class="data-row"><span>${esc(item.topic)}</span><strong>${esc(item.average_score)}%</strong></div>`, 'No weak topics have been identified.');
    const mastery = renderRows(data.outcome_mastery, item => `<div class="data-row"><div><strong>${esc(item.outcome)}</strong><br><small>${esc(item.evidence_count)} evidence records • ${esc(item.status)}</small></div><strong>${esc(item.average_score)}%</strong></div>`, 'Outcome mastery will appear after scored practice or whiteboard checks.');
    const misconceptions = renderRows(data.common_misconceptions, item => `<div class="data-row"><span>${esc(item.misconception)}</span><strong>${esc(item.count)}</strong></div>`, 'No repeated misconceptions have been recorded.');
    const unanswered = renderRows(data.unanswered_questions, item => `<div class="data-row"><div><strong>${esc(item.question || item.topic)}</strong><br><small>${esc(item.student_name || '')} ${item.class_name ? '• '+esc(item.class_name) : ''}</small></div></div>`, 'All recent questions had approved grounding.');
    const interventions = isTeacher ? renderRows(data.interventions, item => `<div class="data-row"><div><strong>${esc(item.display_name)}</strong><br><small>${esc((item.reasons || []).join(' • '))}</small></div><strong>${item.average_score == null ? '—' : esc(item.average_score)+'%'}</strong></div>`, 'No students currently meet the intervention rules.') : '';
    const popular = renderRows(data.popular_questions, item => `<div class="data-row"><span>${esc(item.topic)}</span><strong>${esc(item.count)}</strong></div>`, 'No question patterns yet.');
    const activity = renderRows(data.recent_activity, item => `<div class="data-row"><div><strong>${esc(item.topic || item.event_type)}</strong><br><small>${esc(item.student_name || item.event_type)} ${item.created_at ? '• '+esc(new Date(item.created_at).toLocaleDateString()) : ''}</small></div><strong>${item.score == null ? '' : esc(item.score)+'%'}</strong></div>`, 'No learning activity yet.');
    const students = isTeacher ? renderRows(data.students, item => `<div class="data-row"><div><strong>${esc(item.display_name)}</strong><br><small>${esc(item.email)}</small></div><div><strong>${item.average_score == null ? '—' : esc(item.average_score)+'%'}</strong><br><small>${esc(item.activities)} activities</small></div></div>`, 'Students will appear after they join a class and use the tutor.') : '';
    const usage = renderRows(data.usage, item => `<div class="data-row"><div><strong>${esc(item.provider)} • ${esc(item.model)}</strong><br><small>${esc(item.input_tokens)} input, ${esc(item.output_tokens)} output tokens</small></div><strong>$${Number(item.estimated_cost_usd || 0).toFixed(4)}</strong></div>`, 'No recorded AI usage yet.');
    const classTool = isTeacher
      ? `<div class="class-tools"><input id="newClassName" placeholder="New class name"><input id="newClassSubject" placeholder="Subject"><button id="createClassButton" class="primary" type="button">Create class</button></div>`
      : `<div class="class-tools"><input id="joinClassCode" placeholder="Class join code"><button id="joinClassButton" class="primary" type="button">Join class</button></div>`;
    $('dashboardBody').innerHTML = `
      <div class="dashboard-summary">${summaryCards(data.summary)}</div>
      <div class="dashboard-grid institutional-dashboard">
        <section class="dashboard-section"><h3>${isTeacher ? 'Courses and controls' : 'My courses'}</h3>${classes}${classTool}</section>
        <section class="dashboard-section"><h3>Learning-outcome mastery</h3>${mastery}</section>
        <section class="dashboard-section"><h3>Topics needing attention</h3>${weak}</section>
        <section class="dashboard-section"><h3>Common misconceptions</h3>${misconceptions}</section>
        ${isTeacher ? `<section class="dashboard-section"><h3>Students needing intervention</h3>${interventions}</section>` : ''}
        ${isTeacher ? `<section class="dashboard-section"><h3>Questions needing more approved material</h3>${unanswered}</section>` : ''}
        ${isTeacher ? `<section class="dashboard-section"><h3>Frequently asked topics</h3>${popular}</section>` : ''}
        ${isTeacher ? `<section class="dashboard-section"><h3>Students</h3>${students}</section>` : ''}
        <section class="dashboard-section"><h3>Recent activity</h3>${activity}</section>
        <section class="dashboard-section"><h3>AI usage and estimated text cost</h3>${usage}</section>
      </div>`;
    $('createClassButton')?.addEventListener('click', createClass);
    $('joinClassButton')?.addEventListener('click', joinClass);
    document.querySelectorAll('[data-save-profile]').forEach(button => button.addEventListener('click', () => saveClassProfile(button.dataset.saveProfile)));
  }

  async function loadDashboard() {
    if (!state.user) return openDialog('authDialog');
    openDialog('dashboardDialog');
    $('dashboardBody').innerHTML = '<p>Loading dashboard…</p>';
    try { renderDashboard(await api('/api/dashboard')); }
    catch (error) { $('dashboardBody').innerHTML = `<p class="practice-feedback error">${esc(error.message)}</p>`; }
  }

  async function createClass() {
    const name = $('newClassName')?.value.trim();
    if (!name) return;
    try {
      await api('/api/classes', { method:'POST', body:JSON.stringify({
        name,
        subject:$('newClassSubject')?.value.trim() || $('course')?.value || '',
        knowledge_mode:'course_only', learning_outcomes:[], weekly_topics:[], tutor_instructions:'',
      }) });
      await loadClasses();
      await loadDashboard();
    } catch (error) { alert(error.message); }
  }

  async function saveClassProfile(classId) {
    const root = document.querySelector(`[data-profile="${CSS.escape(classId)}"]`);
    const status = root?.querySelector('[data-profile-status]');
    if (!root) return;
    if (status) status.textContent = 'Saving…';
    const get = field => root.querySelector(`[data-field="${field}"]`)?.value || '';
    try {
      await api(`/api/classes/${encodeURIComponent(classId)}/profile`, { method:'PATCH', body:JSON.stringify({
        name:get('name'), subject:get('subject'), knowledge_mode:get('knowledge_mode'),
        learning_outcomes:lines(get('learning_outcomes')), weekly_topics:lines(get('weekly_topics')),
        tutor_instructions:get('tutor_instructions'),
      }) });
      if (status) { status.textContent = 'Course profile saved.'; status.classList.add('success'); }
      await loadClasses();
    } catch (error) { if (status) { status.textContent = error.message; status.classList.add('error'); } }
  }

  async function joinClass() {
    const join_code = $('joinClassCode')?.value.trim();
    if (!join_code) return;
    try {
      await api('/api/classes/join', { method:'POST', body:JSON.stringify({ join_code }) });
      await loadClasses();
      await loadDashboard();
    } catch (error) { alert(error.message); }
  }

  function latestTutorAnswer() {
    const bodies = [...document.querySelectorAll('.message.assistant .message-body')];
    return bodies.at(-1)?.innerText?.trim() || '';
  }

  function renderVideoJob(job) {
    const playable = job.hosted_url || job.stream_url || job.download_url;
    const links = [
      job.hosted_url ? `<a href="${esc(job.hosted_url)}" target="_blank" rel="noopener">Open video</a>` : '',
      job.download_url ? `<a href="${esc(job.download_url)}" target="_blank" rel="noopener">Download video</a>` : '',
      job.status !== 'script_ready' && !playable ? `<button type="button" data-refresh-video="${esc(job.id)}">Refresh status</button>` : '',
    ].filter(Boolean).join('');
    return `<article class="video-job" data-video-job="${esc(job.id)}"><div class="video-job-head"><strong>${esc(job.title)}</strong><span class="role-badge">${esc(job.status)}</span></div><p>${esc(job.estimated_minutes)} minute reusable lesson • ${esc(job.provider)}</p>${links ? `<div class="video-links">${links}</div>` : ''}${job.script ? `<details><summary>Read or download the lesson script</summary><p>${esc(job.script)}</p></details>` : ''}</article>`;
  }

  async function loadVideos() {
    if (!state.user) return;
    try {
      const jobs = await api('/api/videos');
      $('lessonVideoList').innerHTML = jobs.length ? jobs.map(renderVideoJob).join('') : '<p class="small-note">No reusable lessons have been assigned yet.</p>';
      document.querySelectorAll('[data-refresh-video]').forEach(button => button.addEventListener('click', () => refreshVideo(button.dataset.refreshVideo)));
    } catch (error) { $('lessonVideoList').innerHTML = `<p class="practice-feedback error">${esc(error.message)}</p>`; }
  }

  async function refreshVideo(id) {
    try {
      const job = await api(`/api/video/${encodeURIComponent(id)}`);
      const node = document.querySelector(`[data-video-job="${CSS.escape(id)}"]`);
      if (node) node.outerHTML = renderVideoJob(job);
    } catch (error) { setStatus('lessonVideoStatus', error.message, 'error'); }
  }

  async function generateLessonVideo() {
    const topic = $('lessonVideoTopic').value.trim();
    const classId = $('lessonVideoClass').value;
    if (!classId) return setStatus('lessonVideoStatus', 'Select a class.', 'error');
    if (!topic) return setStatus('lessonVideoStatus', 'Enter a lesson topic.', 'error');
    const classroom = state.classes.find(item => item.id === classId);
    setStatus('lessonVideoStatus', 'DeepSeek is preparing one reusable script and slide set for the class…');
    $('generateLessonVideo').disabled = true;
    try {
      const job = await api('/api/video/generate', { method:'POST', body:JSON.stringify({
        topic, class_id:classId, course:classroom?.subject || classroom?.name || '',
        level:$('level')?.value || 'University', length:$('lessonVideoLength').value,
        use_current_answer:Boolean(latestTutorAnswer()), current_answer:latestTutorAnswer().slice(0,16000),
      }) });
      setStatus('lessonVideoStatus', job.video_id
        ? 'Reusable video submitted for rendering and shared with the class.'
        : 'Reusable script and slides are ready and shared with the class. Tavus is optional for MP4 rendering.', 'success');
      await loadVideos();
    } catch (error) { setStatus('lessonVideoStatus', error.message, 'error'); }
    finally { $('generateLessonVideo').disabled = false; }
  }

  function signOut() {
    state.token = '';
    state.user = null;
    state.classes = [];
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(CLASS_KEY);
    updateAccountUI();
    fillClassSelectors();
  }

  document.addEventListener('DOMContentLoaded', async () => {
    document.querySelectorAll('[data-close-dialog]').forEach(button => button.addEventListener('click', () => closeDialog(button.dataset.closeDialog)));
    $('openSignIn')?.addEventListener('click', () => { setAuthMode('login'); openDialog('authDialog'); });
    $('showLogin')?.addEventListener('click', () => setAuthMode('login'));
    $('showRegister')?.addEventListener('click', () => setAuthMode('register'));
    $('authRole')?.addEventListener('change', updateTeacherCodeVisibility);
    $('authForm')?.addEventListener('submit', submitAuth);
    $('signOutButton')?.addEventListener('click', signOut);
    $('openDashboard')?.addEventListener('click', loadDashboard);
    $('openLessonVideo')?.addEventListener('click', async () => {
      $('lessonVideoTopic').value = $('practiceTopic')?.value || $('weekSelect')?.value || $('course')?.value || '';
      openDialog('lessonVideoDialog');
      await loadVideos();
    });
    $('generateLessonVideo')?.addEventListener('click', generateLessonVideo);
    setAuthMode('login');
    await loadConfig();
    await restoreUser();
  });
})();
