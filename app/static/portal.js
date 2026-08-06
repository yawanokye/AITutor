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
    courseStructure: null,
    lastDashboard: null,
  };
  let assessmentMediaRecorder = null;
  let assessmentMediaStream = null;
  let assessmentAudioChunks = [];
  let assessmentRecordButton = null;

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
    const response = await fetch(url, { ...options, headers, cache: options.cache || 'no-store' });
    let data = {};
    try { data = await response.json(); } catch {}
    if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
    return data;
  };
  const openDialog = id => { const dialog = $(id); if (dialog && !dialog.open) dialog.showModal(); };
  const closeDialog = id => { const dialog = $(id); if (dialog?.open) dialog.close(); };
  const setStatus = (id, text, kind = '') => { const node = $(id); if (!node) return; node.textContent = text || ''; node.className = `small-status ${kind}`.trim(); };
  const lines = value => String(value || '').split(/\r?\n/).map(item => item.trim()).filter(Boolean);
  const copyText = async (text, button) => {
    try {
      await navigator.clipboard.writeText(text);
      const previous = button?.textContent;
      if (button) button.textContent = 'Copied';
      setTimeout(() => { if (button) button.textContent = previous; }, 1200);
    } catch { window.prompt('Copy this value', text); }
  };

  function selectedClass() {
    const id = $('classSelect')?.value || '';
    return state.classes.find(item => item.id === id) || null;
  }
  window.aiTutorGetSelectedClass = selectedClass;

  function knowledgeLabel(mode) {
    return {
      course_only: 'Course materials only',
      course_plus_approved: 'Course materials plus approved readings',
      general: 'Course-first plus general knowledge',
    }[mode] || 'General learning mode';
  }

  function documentTypeLabel(type) {
    return {
      teaching_notes: 'Teaching notes',
      course_outline: 'Detailed course outline',
      recommended_reading: 'Recommended reading',
    }[type] || 'Course document';
  }

  async function loadCourseStructure(classId = '') {
    const panel = $('courseNavigatorPanel');
    const list = $('courseStructureList');
    if (!panel || !list) return;
    if (!classId || !state.user) {
      panel.classList.add('hidden');
      list.innerHTML = '';
      state.courseStructure = null;
      return;
    }
    panel.classList.remove('hidden');
    $('courseStructureStatus').textContent = 'Loading structured course contents…';
    list.innerHTML = '<p class="small-note">Loading teaching notes, outline and readings…</p>';
    try {
      const data = await api(`/api/classes/${encodeURIComponent(classId)}/course-structure`);
      state.courseStructure = data;
      renderCourseStructure(data);
    } catch (error) {
      state.courseStructure = null;
      $('courseStructureStatus').textContent = error.message;
      list.innerHTML = `<p class="practice-feedback error">${esc(error.message)}</p>`;
    }
  }

  function renderCourseStructure(data) {
    const list = $('courseStructureList');
    const documents = data.documents || [];
    const weeklyPlan = data.weekly_plan || [];
    const classroom = data.classroom || selectedClass();
    const sourceMessage = documents.length
      ? `${documents.length} structured document${documents.length === 1 ? '' : 's'} available.`
      : weeklyPlan.length
        ? "No detailed teaching note is uploaded yet. The tutor will build complete lessons from the lecturer's course plan, objectives and expected outcomes."
        : 'The lecturer has not yet added a course plan or teaching material.';
    $('courseStructureStatus').textContent = `${sourceMessage} Select a week, section or subsection to begin teaching.`;

    const weeklyMarkup = weeklyPlan.length ? `<section class="weekly-plan-group"><h3>Week-by-week course activities</h3><p class="small-note">Open a week or subunit for a detailed, step-by-step AI lesson.</p><div class="weekly-plan-list">${weeklyPlan.map((week, index) => `<article class="weekly-plan-item"><button class="weekly-plan-button" type="button" data-teach-section="${esc(week.id)}"><span class="week-number">${index + 1}</span><span><strong>${esc(week.title)}</strong><small>${week.generated ? 'Lesson generated from course objectives and expected outcomes' : esc(week.section_path || '')}</small></span><span>Open ›</span></button>${(week.subunits || []).length ? `<div class="weekly-subunits">${week.subunits.map(item => typeof item === 'string' ? `<span>${esc(item)}</span>` : `<button type="button" class="course-section-button compact" data-teach-section="${esc(item.id)}"><span>${esc(item.title)}</span><small>${esc(item.section_path || '')}</small></button>`).join('')}</div>` : ''}</article>`).join('')}</div></section>` : '';

    const groups = ['course_outline', 'teaching_notes', 'recommended_reading'];
    const documentsMarkup = groups.map(type => {
      const items = documents.filter(doc => doc.document_type === type);
      if (!items.length) return '';
      return `<section class="document-group"><h3>${documentTypeLabel(type)}</h3>${items.map(doc => {
        const sections = (doc.sections || []).map(section => `
          <button class="course-section-button" type="button" data-teach-section="${esc(section.id)}" style="--section-level:${Math.max(1, Number(section.level) || 1)}">
            <span>${esc(section.title)}</span><small>${esc(section.section_path || '')}</small>
          </button>`).join('');
        const deleteButton = state.user?.role === 'teacher'
          ? `<button class="document-delete" type="button" data-delete-document="${esc(doc.id)}" data-class-id="${esc(classroom?.id || '')}">Remove</button>` : '';
        return `<details class="course-document" ${type === 'course_outline' ? 'open' : ''}><summary><span><strong>${esc(doc.title || doc.filename)}</strong><small>${esc(doc.filename)}</small></span>${deleteButton}</summary><div class="course-section-tree">${sections || '<p class="small-note">No subsections were detected.</p>'}</div></details>`;
      }).join('')}</section>`;
    }).join('');
    list.innerHTML = weeklyMarkup + documentsMarkup || '<div class="course-empty">No structured course content is available yet.</div>';
    list.querySelectorAll('[data-teach-section]').forEach(button => button.addEventListener('click', () => teachSection(button.dataset.teachSection, button)));
    list.querySelectorAll('[data-delete-document]').forEach(button => button.addEventListener('click', event => {
      event.preventDefault(); event.stopPropagation(); deleteDocument(button.dataset.classId, button.dataset.deleteDocument, button);
    }));
  }


  async function teachSection(sectionId, button) {
    if (!sectionId) return;
    const original = button?.innerHTML;
    if (button) { button.disabled = true; button.innerHTML = '<span>Preparing detailed lesson…</span>'; }
    $('courseStructureStatus').textContent = 'The AI Tutor is preparing a detailed lesson from the selected subsection and approved readings…';
    try {
      const data = await api(`/api/course/sections/${encodeURIComponent(sectionId)}/teach`, {
        method: 'POST',
        body: JSON.stringify({
          level: $('level')?.value || 'University',
          detail: $('sectionDetail')?.value || 'detailed',
        }),
      });
      const add = window.aiTutorAddMessage || window.addMessage;
      const render = window.aiTutorRenderVisual || window.renderVisual;
      window.aiTutorSetActiveLessonContext?.({
        class_id: selectedClass()?.id || '',
        course_name: selectedClass()?.name || selectedClass()?.subject || '',
        section_id: sectionId,
        section_title: data.section_title || data.title || '',
        section_path: data.section_path || '',
        weekly_topic: (() => {
          const parts = (data.section_path || '').split(/\s*[>›/]\s*/).filter(Boolean);
          return parts.find(part => /^(?:week|period|session|teaching\s+week)\b/i.test(part)) || parts[0] || data.section_title || '';
        })(),
      });
      add?.('assistant', data.answer, data.sources || []);
      render?.(data.visual, null);
      if ($('practiceTopic')) $('practiceTopic').value = data.section_title || data.title || '';
      if (window.aiTutorSetPracticeResponseMode) window.aiTutorSetPracticeResponseMode(data.practice_response_mode || 'student_choice');
      $('courseStructureStatus').textContent = `Lesson ready: ${data.section_path || data.section_title || 'selected subsection'}${data.generated_from_outcomes ? ' • developed from the course objectives and expected outcomes' : ''}`;
      window.aiTutorSetMobileView?.('visual');
    } catch (error) {
      $('courseStructureStatus').textContent = error.message;
    } finally {
      if (button) { button.disabled = false; button.innerHTML = original; }
    }
  }

  async function deleteDocument(classId, documentId, button = null) {
    if (!classId || !documentId) return;
    if (!confirm('Permanently delete this course document, all subsections and every indexed extract?')) return;
    const previous = button?.textContent || 'Remove';
    if (button) { button.disabled = true; button.textContent = 'Deleting…'; }
    try {
      const result = await api(`/api/classes/${encodeURIComponent(classId)}/documents/${encodeURIComponent(documentId)}`, { method: 'DELETE' });
      document.querySelectorAll(`[data-delete-document="${CSS.escape(documentId)}"], [data-remove-inline-document="${CSS.escape(documentId)}"]`).forEach(node => node.closest('.course-document, .lecturer-document-row')?.remove());
      await loadCourseStructure(classId);
      await loadLecturerDocumentSummary(classId);
      await window.aiTutorLoadMaterials?.();
      const status = document.querySelector(`[data-document-manager="${CSS.escape(classId)}"] [data-course-document-status]`);
      if (status) { status.textContent = `Document deleted. ${Number(result.deleted_chunks || 0)} indexed extract(s) removed.`; status.className = 'small-status success'; }
    } catch (error) {
      alert(error.message);
      if (button) { button.disabled = false; button.textContent = previous; }
    }
  }

  function applySelectedClass() {
    const classroom = selectedClass();
    window.aiTutorBeginCourseSwitch?.(classroom?.id || 'independent', classroom ? `${classroom.name}${classroom.subject ? ` • ${classroom.subject}` : ''}` : 'Independent learning');
    window.aiTutorSelectedClass = classroom;
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
      loadCourseStructure('');
      window.aiTutorPracticeBoard?.hide();
      window.aiTutorFinishCourseSwitch?.();
      return;
    }
    $('course').value = classroom.subject || classroom.name;
    $('knowledgeModeBadge').textContent = `${classroom.name} • ${knowledgeLabel(classroom.knowledge_mode)}`;
    const outcomes = classroom.learning_outcomes || [];
    const weeks = classroom.weekly_topics || [];
    outcome.innerHTML = outcomes.length ? outcomes.map(item => `<option value="${esc(item)}">${esc(item)}</option>`).join('') : '<option value="">No learning outcomes configured</option>';
    week.innerHTML = weeks.length ? weeks.map(item => `<option value="${esc(item)}">${esc(item)}</option>`).join('') : '<option value="">No weekly topics configured</option>';
    outcomeLabel.classList.toggle('hidden', !outcomes.length);
    weekLabel.classList.toggle('hidden', !weeks.length);
    localStorage.setItem(CLASS_KEY, classroom.id);
    loadCourseStructure(classroom.id);
    window.aiTutorFinishCourseSwitch?.();
  }
  window.aiTutorClassChanged = applySelectedClass;

  function fillClassSelectors() {
    const selected = localStorage.getItem(CLASS_KEY) || '';
    const options = state.classes.map(item => `<option value="${esc(item.id)}">${esc(item.name)}${item.subject ? ` • ${esc(item.subject)}` : ''}</option>`).join('');
    if ($('classSelect')) {
      const placeholder = state.user?.role === 'student' ? 'Select an enrolled course' : 'Independent learning';
      $('classSelect').innerHTML = `<option value="">${placeholder}</option>${options}`;
      if (state.classes.some(item => item.id === selected)) $('classSelect').value = selected;
      else if (state.user?.role === 'student' && state.classes.length) $('classSelect').value = state.classes[0].id;
    }
    const lecturerClasses = state.user?.role === 'teacher' ? state.classes : [];
    if ($('materialScope')) {
      $('materialScope').innerHTML = `<option value="">Select a course</option>${lecturerClasses.map(item => `<option value="${esc(item.id)}">${esc(item.name)}</option>`).join('')}`;
      if (lecturerClasses.some(item => item.id === selected)) $('materialScope').value = selected;
    }
    if ($('lessonVideoClass')) {
      $('lessonVideoClass').innerHTML = `<option value="">Select a class</option>${lecturerClasses.map(item => `<option value="${esc(item.id)}">${esc(item.name)}</option>`).join('')}`;
      if (lecturerClasses.some(item => item.id === selected)) $('lessonVideoClass').value = selected;
    }
    applySelectedClass();
    window.aiTutorLoadMaterials?.();
  }

  async function loadClasses() {
    if (!state.user) { state.classes = []; fillClassSelectors(); return; }
    try { state.classes = await api('/api/classes'); } catch { state.classes = []; }
    fillClassSelectors();
  }

  function portalLabel(role) {
    return role === 'admin' ? 'Administrator portal' : role === 'teacher' ? 'Lecturer portal' : 'Student portal';
  }

  function updateAccountUI() {
    const signedIn = Boolean(state.user);
    $('signedOutActions')?.classList.toggle('hidden', signedIn);
    $('signedInActions')?.classList.toggle('hidden', !signedIn);
    $('accountRoleBadge')?.classList.toggle('hidden', !signedIn);
    if (signedIn) {
      $('accountName').textContent = state.user.display_name;
      $('accountRoleBadge').textContent = state.user.role === 'teacher' ? 'lecturer' : state.user.role;
      $('openDashboard').textContent = portalLabel(state.user.role);
    } else if ($('openDashboard')) $('openDashboard').textContent = 'Portal';
    const role = state.user?.role || 'guest';
    document.body.dataset.userRole = role;
    document.body.classList.toggle('student-interface', role === 'student');
    document.body.classList.toggle('lecturer-interface', role === 'teacher');
    document.body.classList.toggle('admin-interface', role === 'admin');
    document.querySelectorAll('.student-memory-action').forEach(node => node.classList.toggle('hidden', role !== 'student'));
    const lecturer = signedIn && state.user.role === 'teacher';
    if ($('openDashboard') && role === 'student') $('openDashboard').textContent = 'My courses';
    if ($('courseSettingsTitle')) $('courseSettingsTitle').textContent = role === 'student' ? 'Current course' : 'Learning settings';
    $('courseMaterialsPanel')?.classList.toggle('hidden', !lecturer);
    $('lessonVideoCreator')?.classList.toggle('hidden', !lecturer);
    if ($('openLessonVideo')) {
      $('openLessonVideo').disabled = !signedIn;
      $('openLessonVideo').title = signedIn ? 'Open reusable lessons assigned to your courses' : 'Sign in to view course lessons';
    }
  }

  async function loadConfig() {
    try {
      state.config = await api('/api/config');
      const provider = state.config.text_provider === 'deepseek' ? 'DeepSeek' : 'OpenAI';
      $('providerBadge').textContent = `${provider} ${state.config.default_text_model || ''} • institutional routing`;
    } catch { $('providerBadge').textContent = 'AI provider status unavailable'; }
    updateAccountUI();
  }

  async function restoreUser() {
    if (!state.token) { updateAccountUI(); await loadClasses(); return; }
    try { state.user = await api('/api/auth/me'); }
    catch { state.token = ''; state.user = null; localStorage.removeItem(TOKEN_KEY); }
    updateAccountUI();
    await loadClasses();
    if (state.user?.must_change_password) setTimeout(loadDashboard, 250);
  }

  function setAuthMode(mode) {
    state.authMode = mode;
    const registering = mode === 'register';
    const bootstrap = mode === 'bootstrap';
    const roleLabels = {
      admin_login: 'Administrator sign in',
      teacher_login: 'Lecturer sign in',
      student_login: 'Student sign in'
    };
    $('authTitle').textContent = bootstrap ? 'Create first administrator' : registering ? 'Create student account' : (roleLabels[mode] || 'Sign in');
    $('submitAuth').textContent = bootstrap ? 'Create administrator' : registering ? 'Create student account' : (roleLabels[mode] || 'Sign in');
    $('showAdminLogin').classList.toggle('active', mode === 'admin_login');
    $('showLecturerLogin').classList.toggle('active', mode === 'teacher_login');
    $('showStudentLogin').classList.toggle('active', mode === 'student_login');
    $('showRegister').classList.toggle('active', registering);
    $('showAdminSetup').classList.toggle('active', bootstrap);
    $('displayNameLabel').classList.toggle('hidden', !(registering || bootstrap));
    $('adminBootstrapKeyLabel').classList.toggle('hidden', !bootstrap);
    $('authPassword').minLength = bootstrap ? 10 : 8;
    $('authPassword').autocomplete = (registering || bootstrap) ? 'new-password' : 'current-password';
    $('authHelp').textContent = bootstrap
      ? 'This works only before the first administrator account is created and requires the ADMIN_KEY stored in Render.'
      : registering
        ? 'Create a student account, then enrol in courses using codes supplied by lecturers.'
        : mode === 'admin_login'
          ? 'Administrators sign in with an administrator account. The first administrator creates lecturer accounts.'
          : mode === 'teacher_login'
            ? 'Lecturers sign in with the email address and temporary or updated password supplied by an administrator.'
            : 'Students sign in with their registered account, then open courses they have enrolled in.';
    setStatus('authStatus', '');
  }

  async function submitAuth(event) {
    event.preventDefault();
    setStatus('authStatus', 'Please wait…');
    let endpoint = '/api/auth/login';
    let body = { email: $('authEmail').value.trim(), password: $('authPassword').value };
    if (state.authMode === 'register') {
      endpoint = '/api/auth/register';
      body = { ...body, display_name: $('authDisplayName').value.trim(), role: 'student', teacher_invite_code: '' };
    } else if (state.authMode === 'bootstrap') {
      endpoint = '/api/admin/bootstrap';
      body = { ...body, display_name: $('authDisplayName').value.trim(), admin_key: $('adminBootstrapKey').value };
    }
    try {
      const data = await api(endpoint, { method: 'POST', body: JSON.stringify(body) });
      const expectedRole = { admin_login: 'admin', teacher_login: 'teacher', student_login: 'student' }[state.authMode];
      if (expectedRole && data.user?.role !== expectedRole) {
        const actual = data.user?.role === 'teacher' ? 'lecturer' : (data.user?.role || 'different');
        const expected = expectedRole === 'teacher' ? 'lecturer' : expectedRole;
        throw new Error(`This is a ${actual} account. Use ${expected} sign in.`);
      }
      state.token = data.access_token;
      state.user = data.user;
      localStorage.setItem(TOKEN_KEY, state.token);
      updateAccountUI();
      await loadClasses();
      closeDialog('authDialog');
      $('authForm').reset();
      setAuthMode('student_login');
      await loadDashboard();
    } catch (error) { setStatus('authStatus', error.message, 'error'); }
  }

  function summaryCards(summary) {
    return Object.entries(summary || {}).map(([key, value]) => `<div class="metric-card"><strong>${esc(value ?? '—')}</strong><span>${esc(key.replaceAll('_',' '))}</span></div>`).join('');
  }
  function renderRows(items, renderer, empty = 'No records yet.') {
    return items?.length ? `<div class="data-list">${items.map(renderer).join('')}</div>` : `<p class="small-note">${esc(empty)}</p>`;
  }
  function passwordCard() {
    if (!state.user?.must_change_password) return '';
    return `<section class="dashboard-section password-change-card"><h3>Change temporary password</h3><p>Your administrator created this account with a temporary password. Change it before continuing.</p><label>Current temporary password<input id="currentPortalPassword" type="password"></label><label>New password<input id="newPortalPassword" type="password" minlength="10"></label><button id="changePortalPassword" class="primary" type="button">Change password</button><div id="passwordChangeStatus" class="small-status"></div></section>`;
  }

  function classProfileForm(item) {
    return `<details class="class-profile" data-profile="${esc(item.id)}"><summary>Configure course, outcomes, readings and practice</summary>
      <div class="profile-form">
        <label>Course name<input data-field="name" value="${esc(item.name)}"></label>
        <label>Subject<input data-field="subject" value="${esc(item.subject || '')}"></label>
        <label>Knowledge setting<select data-field="knowledge_mode">
          <option value="course_only" ${item.knowledge_mode === 'course_only' ? 'selected' : ''}>Course materials only</option>
          <option value="course_plus_approved" ${item.knowledge_mode === 'course_plus_approved' ? 'selected' : ''}>Course plus approved readings</option>
          <option value="general" ${item.knowledge_mode === 'general' ? 'selected' : ''}>Course-first plus general knowledge</option>
        </select></label>
        <label>Course objectives, one per line<textarea data-field="learning_outcomes" rows="6">${esc((item.learning_outcomes || []).join('\n'))}</textarea></label>
        <label>Topics or weekly sections, one per line<textarea data-field="weekly_topics" rows="6">${esc((item.weekly_topics || []).join('\n'))}</textarea></label>
        <label>Recommended reading list, one per line<textarea data-field="recommended_readings" rows="6">${esc((item.recommended_readings || []).join('\n'))}</textarea></label>
        <label>Lecturer instructions to the AI Tutor<textarea data-field="tutor_instructions" rows="5">${esc(item.tutor_instructions || '')}</textarea></label>
        <label>Required practice-response format<select data-field="practice_response_mode">
          <option value="student_choice" ${(item.practice_response_mode || 'student_choice') === 'student_choice' ? 'selected' : ''}>Student chooses typing, voice or whiteboard</option>
          <option value="typed" ${item.practice_response_mode === 'typed' ? 'selected' : ''}>Typed response only</option>
          <option value="voice" ${item.practice_response_mode === 'voice' ? 'selected' : ''}>Recorded voice response only</option>
          <option value="whiteboard" ${(item.practice_response_mode === 'whiteboard' || item.practice_whiteboard_required) ? 'selected' : ''}>Handwritten whiteboard response only</option>
        </select><small>Every generated practice question follows this setting until you change it.</small></label>
        <fieldset class="policy-fieldset"><legend>Learning cycle and academic integrity</legend>
          <label class="check-row"><input data-field="diagnostics_required" type="checkbox" ${item.diagnostics_required !== false ? 'checked' : ''}> Require an entry diagnostic</label>
          <label class="check-row"><input data-field="spaced_revision_enabled" type="checkbox" ${item.spaced_revision_enabled !== false ? 'checked' : ''}> Schedule spaced revision automatically</label>
          <label>Mastery pass mark<input data-field="mastery_pass_mark" type="number" min="40" max="95" value="${esc(item.mastery_pass_mark || 70)}"></label>
          <label class="check-row"><input data-field="direct_answers_allowed" type="checkbox" ${item.direct_answers_allowed !== false ? 'checked' : ''}> Permit direct answers during ordinary learning</label>
          <label class="check-row"><input data-field="hints_allowed" type="checkbox" ${item.hints_allowed !== false ? 'checked' : ''}> Permit hints</label>
          <label>Assignment assistance<select data-field="assignment_help_mode"><option value="teach_only" ${item.assignment_help_mode === 'teach_only' ? 'selected' : ''}>Teach concepts only</option><option value="guided" ${(item.assignment_help_mode || 'guided') === 'guided' ? 'selected' : ''}>Guided help after a student attempt</option><option value="allowed" ${item.assignment_help_mode === 'allowed' ? 'selected' : ''}>Full learning assistance</option></select></label>
          <label>Integrity mode<select data-field="integrity_mode"><option value="learning" ${(item.integrity_mode || 'learning') === 'learning' ? 'selected' : ''}>Normal learning</option><option value="hint_only" ${item.integrity_mode === 'hint_only' ? 'selected' : ''}>Hints and guiding questions only</option><option value="assessment_restricted" ${item.integrity_mode === 'assessment_restricted' ? 'selected' : ''}>Assessment restricted</option></select></label>
        </fieldset>
        <div class="profile-actions"><button class="primary" type="button" data-save-profile="${esc(item.id)}">Save course profile</button><button class="secondary" type="button" data-select-course="${esc(item.id)}">Open course</button></div>
        <div class="small-status" data-profile-status="${esc(item.id)}"></div>
      </div></details>`;
  }

  function lecturerClassRow(item) {
    return `<article class="lecturer-course-card"><div class="course-card-head"><div><strong>${esc(item.name)}</strong><small>${esc(item.subject || '')} • ${esc(item.student_count)} enrolled</small></div><div class="join-code-box"><span>Student enrolment code</span><strong>${esc(item.join_code)}</strong><div><button type="button" data-copy-code="${esc(item.join_code)}">Copy</button><button type="button" data-regenerate-code="${esc(item.id)}">Regenerate</button></div></div></div>
      ${classProfileForm(item)}
      <details class="lecturer-document-manager" data-document-manager="${esc(item.id)}"><summary>Upload and manage teaching documents</summary>
        <div class="lecturer-document-form">
          <label>Document category<select data-course-document-type><option value="teaching_notes">Teaching notes</option><option value="course_outline">Detailed course outline</option><option value="recommended_reading">Recommended reading material</option></select></label>
          <label class="file-button"><input data-course-document-files type="file" multiple accept=".pdf,.docx,.txt,.md,.csv"><span>Select documents</span></label>
          <button class="primary" type="button" data-upload-course-documents="${esc(item.id)}">Upload and structure</button>
          <div class="small-status" data-course-document-status></div>
          <div class="lecturer-document-list" data-course-documents="${esc(item.id)}"><p class="small-note">Open this panel to load current documents.</p></div>
        </div>
      </details>
    </article>`;
  }

  function adminMaterialRows(items) {
    if (!items?.length) return '<p class="small-note">No administrator documents have been uploaded.</p>';
    return `<div class="data-list">${items.map(item => `<div class="data-row admin-material-row"><div><strong>${esc(item.source)}</strong><br><small>${esc((item.material_type || 'course').replaceAll('_', ' '))} • ${esc(item.chunks)} indexed extracts • private administrator repository</small></div><button class="danger-ghost" type="button" data-delete-admin-material="${esc(item.source_id || '')}">Delete</button></div>`).join('')}</div>`;
  }

  async function loadAdminMaterials() {
    const container = $('adminMaterialList');
    if (!container) return;
    container.innerHTML = '<p class="small-note">Loading administrator documents…</p>';
    try {
      const data = await api('/api/admin/materials');
      container.innerHTML = adminMaterialRows(data.materials || []);
      container.querySelectorAll('[data-delete-admin-material]').forEach(button => button.addEventListener('click', () => deleteAdminMaterial(button.dataset.deleteAdminMaterial, button)));
    } catch (error) { container.innerHTML = `<p class="practice-feedback error">${esc(error.message)}</p>`; }
  }

  async function uploadAdminMaterials() {
    const files = [...($('adminMaterialFiles')?.files || [])];
    const status = $('adminMaterialStatus');
    if (!files.length) return setStatus('adminMaterialStatus', 'Select at least one administrator document.', 'error');
    const form = new FormData();
    form.append('document_type', $('adminMaterialType')?.value || 'teaching_notes');
    files.forEach(file => form.append('files', file, file.name));
    setStatus('adminMaterialStatus', 'Uploading to the private administrator repository…');
    const button = $('uploadAdminMaterials');
    if (button) button.disabled = true;
    try {
      const result = await api('/api/materials/upload', { method: 'POST', body: form });
      const uploaded = result.uploaded || [];
      const errors = result.errors || [];
      setStatus('adminMaterialStatus', `${uploaded.length} document${uploaded.length === 1 ? '' : 's'} uploaded.${errors.length ? ` ${errors.length} issue(s).` : ''}`, errors.length ? 'warning' : 'success');
      if ($('adminMaterialFiles')) $('adminMaterialFiles').value = '';
      await loadAdminMaterials();
    } catch (error) { setStatus('adminMaterialStatus', error.message, 'error'); }
    finally { if (button) button.disabled = false; }
  }

  async function deleteAdminMaterial(sourceId, button = null) {
    if (!sourceId || !confirm('Permanently delete this private administrator document and all indexed extracts?')) return;
    const row = button?.closest('.admin-material-row');
    const previous = button?.textContent || 'Delete';
    if (button) { button.disabled = true; button.textContent = 'Deleting…'; }
    try {
      const result = await api(`/api/admin/materials?source_id=${encodeURIComponent(sourceId)}`, { method: 'DELETE' });
      row?.remove();
      setStatus('adminMaterialStatus', `Administrator document deleted. ${Number(result.deleted_chunks || 0)} indexed extract(s) removed.`, 'success');
      await loadAdminMaterials();
    } catch (error) {
      if (button) { button.disabled = false; button.textContent = previous; }
      setStatus('adminMaterialStatus', error.message, 'error');
    }
  }

  function renderAdminDashboard(data) {
    $('dashboardEyebrow').textContent = 'Institutional account control';
    $('dashboardTitle').textContent = 'Administrator portal';
    const lecturers = renderRows(data.lecturers, item => `<div class="data-row lecturer-account-row"><div><strong>${esc(item.display_name)}</strong><br><small>${esc(item.email)}${item.must_change_password ? ' • temporary password pending' : ''}</small></div><div class="row-actions"><span class="role-badge ${item.active ? '' : 'inactive'}">${item.active ? 'Active' : 'Inactive'}</span><button type="button" data-toggle-user="${esc(item.id)}" data-active="${item.active ? 'false' : 'true'}">${item.active ? 'Deactivate' : 'Activate'}</button><button type="button" data-reset-user="${esc(item.id)}">Reset password</button></div></div>`, 'No lecturer accounts have been created.');
    const classes = renderRows(data.classes, item => `<div class="data-row"><div><strong>${esc(item.name)}</strong><br><small>${esc(item.subject)} • ${esc(item.teacher_name)}</small></div><strong>${esc(item.student_count)} students</strong></div>`, 'No courses have been created.');
    const students = renderRows(data.students?.slice(0, 200), item => `<div class="data-row"><div><strong>${esc(item.display_name)}</strong><br><small>${esc(item.email)}</small></div><span class="role-badge ${item.active ? '' : 'inactive'}">${item.active ? 'Active' : 'Inactive'}</span></div>`, 'No student accounts yet.');
    const usage = renderRows(data.usage, item => `<div class="data-row"><div><strong>${esc(item.provider)} • ${esc(item.model)}</strong><br><small>${esc(item.input_tokens)} input, ${esc(item.output_tokens)} output tokens</small></div><strong>$${Number(item.estimated_cost_usd || 0).toFixed(4)}</strong></div>`, 'No AI usage yet.');
    $('dashboardBody').innerHTML = `<div class="dashboard-summary">${summaryCards(data.summary)}</div>${passwordCard()}<div class="dashboard-grid institutional-dashboard">
      <section class="dashboard-section admin-create-lecturer"><h3>Create lecturer account</h3><div class="class-tools vertical"><label>Lecturer full name<input id="newLecturerName" placeholder="Full name"></label><label>Institutional email<input id="newLecturerEmail" type="email" placeholder="name@institution.edu"></label><label>Temporary password, optional<input id="newLecturerPassword" type="text" placeholder="Leave blank to generate securely"></label><button id="createLecturerButton" class="primary" type="button">Create lecturer account</button><div id="lecturerCreateStatus" class="small-status"></div><div id="temporaryCredential" class="temporary-credential hidden"></div></div></section>
      <section class="dashboard-section"><h3>Lecturer accounts</h3>${lecturers}</section>
      <section class="dashboard-section"><h3>Courses across the institution</h3>${classes}</section>
      <section class="dashboard-section"><h3>Student accounts</h3>${students}</section>
      <section class="dashboard-section full-span admin-document-repository"><h3>Administrator document repository</h3><p class="small-note">Documents uploaded here are private to administrators. They are not shown to lecturers or students and are not automatically used in any lecturer's course.</p><div class="class-tools"><label>Document category<select id="adminMaterialType"><option value="teaching_notes">Institutional teaching resource</option><option value="course_outline">Institutional course outline</option><option value="recommended_reading">Institutional recommended reading</option></select></label><label class="file-button"><input id="adminMaterialFiles" type="file" multiple accept=".pdf,.docx,.txt,.md,.csv"><span>Select administrator documents</span></label><button id="uploadAdminMaterials" class="primary" type="button">Upload privately</button></div><div id="adminMaterialStatus" class="small-status"></div><div id="adminMaterialList"><p class="small-note">Loading administrator documents…</p></div></section>
      <section class="dashboard-section"><h3>AI usage and estimated cost</h3>${usage}</section>
    </div>`;
    $('createLecturerButton')?.addEventListener('click', createLecturer);
    $('uploadAdminMaterials')?.addEventListener('click', uploadAdminMaterials);
    loadAdminMaterials();
    document.querySelectorAll('[data-toggle-user]').forEach(button => button.addEventListener('click', () => toggleUser(button.dataset.toggleUser, button.dataset.active === 'true')));
    document.querySelectorAll('[data-reset-user]').forEach(button => button.addEventListener('click', () => resetUserPassword(button.dataset.resetUser)));
  }

  function localDateTimeValue(value) {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    const pad = number => String(number).padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth()+1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
  }

  function assessmentQuestionEditor(question, index) {
    const id = esc(question.id || `q${index+1}`);
    const optionText = (question.options || []).join('\n');
    return `<article class="assessment-question-editor" data-assessment-question="${id}">
      <header><strong>Question ${index+1}</strong><span>${esc(question.difficulty || 'standard')}</span></header>
      <div class="assessment-editor-grid">
        <label>Question type<select data-q-field="question_type">${['multiple_choice','short_answer','essay','calculation','case_study','oral','whiteboard','upload'].map(value=>`<option value="${value}" ${question.question_type===value?'selected':''}>${value.replaceAll('_',' ')}</option>`).join('')}</select></label>
        <label>Response method<select data-q-field="response_mode">${['typed','voice','whiteboard','upload','student_choice'].map(value=>`<option value="${value}" ${question.response_mode===value?'selected':''}>${value.replaceAll('_',' ')}</option>`).join('')}</select></label>
        <label>Difficulty<select data-q-field="difficulty">${['foundation','standard','challenge'].map(value=>`<option value="${value}" ${question.difficulty===value?'selected':''}>${value}</option>`).join('')}</select></label>
        <label>Points<input data-q-field="points" type="number" min="0.1" max="100" step="0.5" value="${esc(question.points || 1)}"></label>
        <label>Question learning outcome<input data-q-field="learning_outcome" value="${esc(question.learning_outcome || '')}" placeholder="Outcome measured by this question"></label>
        <label>Question topic<input data-q-field="topic" value="${esc(question.topic || '')}" placeholder="Topic measured by this question"></label>
      </div>
      <label>Question prompt<textarea data-q-field="prompt" rows="3">${esc(question.prompt || '')}</textarea></label>
      <label>Options, one per line<textarea data-q-field="options" rows="3">${esc(optionText)}</textarea></label>
      <label>Expected answer<textarea data-q-field="expected_answer" rows="3">${esc(question.expected_answer || '')}</textarea></label>
      <label>Marking guide<textarea data-q-field="marking_guide" rows="3">${esc(question.marking_guide || '')}</textarea></label>
      <label>Hint<textarea data-q-field="hint" rows="2">${esc(question.hint || '')}</textarea></label>
      <label>Feedback explanation<textarea data-q-field="explanation" rows="2">${esc(question.explanation || '')}</textarea></label>
    </article>`;
  }

  function assessmentEditor(item) {
    const settings = item.settings || {};
    return `<details class="assessment-editor" data-assessment-editor="${esc(item.id)}"><summary>Review, edit and configure</summary>
      <div class="assessment-editor-body">
        <label>Title<input data-a-field="title" value="${esc(item.title)}"></label>
        <div class="assessment-editor-grid">
          <label>Assessment type<select data-a-field="assessment_type">${['diagnostic','practice','quiz','assignment','mastery_check'].map(value=>`<option value="${value}" ${item.assessment_type===value?'selected':''}>${value.replaceAll('_',' ')}</option>`).join('')}</select></label>
          <label>Topic<input data-a-field="topic" value="${esc(item.topic || '')}"></label>
          <label>Learning outcome<input data-a-field="learning_outcome" value="${esc(item.learning_outcome || '')}"></label>
          <label>Due date and time<input data-a-field="due_at" type="datetime-local" value="${localDateTimeValue(item.due_at)}"></label>
          <label>Attempts allowed<input data-a-setting="attempts_allowed" type="number" min="1" max="10" value="${esc(settings.attempts_allowed || 1)}"></label>
          <label>Pass mark<input data-a-setting="pass_mark" type="number" min="0" max="100" value="${esc(settings.pass_mark ?? 70)}"></label>
          <label>Integrity mode<select data-a-setting="integrity_mode">${['learning','hint_only','graded','exam'].map(value=>`<option value="${value}" ${settings.integrity_mode===value?'selected':''}>${value.replaceAll('_',' ')}</option>`).join('')}</select></label>
        </div>
        <label>Instructions<textarea data-a-field="instructions" rows="3">${esc(item.instructions || '')}</textarea></label>
        <div class="assessment-setting-toggles">
          <label><input data-a-setting="hints_allowed" type="checkbox" ${settings.hints_allowed!==false?'checked':''}> Allow hints</label>
          <label><input data-a-setting="reveal_answers" type="checkbox" ${settings.reveal_answers!==false?'checked':''}> Reveal answers after submission</label>
          <label><input data-a-setting="contributes_to_mastery" type="checkbox" ${settings.contributes_to_mastery!==false?'checked':''}> Count towards mastery</label>
          <label><input data-a-setting="deadline_enforced" type="checkbox" ${settings.deadline_enforced?'checked':''}> Enforce deadline</label>
        </div>
        <div class="assessment-question-editor-list">${(item.questions || []).map(assessmentQuestionEditor).join('')}</div>
        <div class="inline-actions"><button class="primary" type="button" data-save-assessment="${esc(item.id)}">Save assessment changes</button><span data-assessment-save-status="${esc(item.id)}" class="small-status"></span></div>
      </div>
    </details>`;
  }

  function assessmentRow(item, lecturer = false) {
    const status = `<span class="role-badge">${esc(item.status)}</span>`;
    const due = item.due_at ? `<small>Due ${esc(new Date(item.due_at).toLocaleString())}</small>` : '';
    const actions = lecturer
      ? `<div class="inline-actions">${item.status === 'draft' ? `<button type="button" data-publish-assessment="${esc(item.id)}">Publish</button>` : ''}<button class="danger-ghost" type="button" data-delete-assessment="${esc(item.id)}">Delete</button></div>`
      : `<button class="primary" type="button" data-start-assessment="${esc(item.id)}">${item.assessment_type === 'diagnostic' ? 'Start diagnostic' : 'Start assessment'}</button>`;
    return `<article class="assessment-card"><div class="assessment-card-summary"><div><strong>${esc(item.title)}</strong><p>${esc(item.topic || item.learning_outcome || item.assessment_type)}</p>${due}</div>${status}${actions}</div>${lecturer ? assessmentEditor(item) : ''}</article>`;
  }

  function renderLecturerAssessments(data) {
    const assessments = data.assessments || [];
    const classOptions = (data.classes || []).map(item => `<option value="${esc(item.id)}">${esc(item.name)}</option>`).join('');
    return `<section class="dashboard-section full-span assessment-manager"><h3>Assessment and question bank</h3><p class="small-note">Generate a draft, edit every question and marking guide, configure attempts and integrity rules, then publish it.</p><div class="assessment-draft-form"><label>Course<select id="assessmentClass">${classOptions}</select></label><label>Type<select id="assessmentType"><option value="diagnostic">Entry diagnostic</option><option value="practice">Practice</option><option value="quiz">Quiz</option><option value="assignment">Assignment</option><option value="mastery_check">Mastery check</option></select></label><label>Topic<input id="assessmentTopic" placeholder="Topic or unit"></label><label>Learning outcome<input id="assessmentOutcome" placeholder="Outcome to assess"></label><label>Questions<input id="assessmentCount" type="number" min="2" max="20" value="5"></label><label>Difficulty<select id="assessmentDifficulty"><option value="mixed">Mixed</option><option value="foundation">Foundation</option><option value="standard">Standard</option><option value="challenge">Challenge</option></select></label><label>Attempts<input id="assessmentAttempts" type="number" min="1" max="10" value="2"></label><label>Pass mark<input id="assessmentPassMark" type="number" min="0" max="100" value="70"></label><label><input id="assessmentHintsAllowed" type="checkbox" checked> Allow hints</label><label><input id="assessmentRevealAnswers" type="checkbox" checked> Reveal answers after submission</label><button id="generateAssessmentDraft" class="primary" type="button">Generate editable draft</button></div><div id="assessmentStatus" class="small-status"></div><div class="assessment-list">${assessments.length ? assessments.map(item => assessmentRow(item, true)).join('') : '<p class="small-note">No assessments have been created.</p>'}</div></section>`;
  }

  function readAssessmentEditor(id) {
    const item = state.lastDashboard?.assessments?.find(row => row.id === id);
    const root = document.querySelector(`[data-assessment-editor="${CSS.escape(id)}"]`);
    if (!item || !root) return null;
    const field = name => root.querySelector(`[data-a-field="${name}"]`);
    const setting = name => root.querySelector(`[data-a-setting="${name}"]`);
    const questions = [...root.querySelectorAll('[data-assessment-question]')].map((node, index) => {
      const q = name => node.querySelector(`[data-q-field="${name}"]`);
      return {
        id: node.dataset.assessmentQuestion || `q${index+1}`,
        question_type: q('question_type')?.value || 'short_answer',
        prompt: q('prompt')?.value.trim() || `Question ${index+1}`,
        options: lines(q('options')?.value),
        expected_answer: q('expected_answer')?.value.trim() || '',
        marking_guide: q('marking_guide')?.value.trim() || '',
        hint: q('hint')?.value.trim() || '',
        explanation: q('explanation')?.value.trim() || '',
        difficulty: q('difficulty')?.value || 'standard',
        points: Number(q('points')?.value || 1),
        response_mode: q('response_mode')?.value || 'typed',
        learning_outcome: q('learning_outcome')?.value.trim() || '',
        topic: q('topic')?.value.trim() || '',
      };
    });
    return {
      title: field('title')?.value.trim() || item.title,
      assessment_type: field('assessment_type')?.value || item.assessment_type,
      topic: field('topic')?.value.trim() || '', learning_outcome: field('learning_outcome')?.value.trim() || '',
      instructions: field('instructions')?.value.trim() || '', questions,
      settings: {
        attempts_allowed:Number(setting('attempts_allowed')?.value || 1),
        hints_allowed:Boolean(setting('hints_allowed')?.checked), reveal_answers:Boolean(setting('reveal_answers')?.checked),
        pass_mark:Number(setting('pass_mark')?.value || 70), contributes_to_mastery:Boolean(setting('contributes_to_mastery')?.checked),
        integrity_mode:setting('integrity_mode')?.value || 'learning', deadline_enforced:Boolean(setting('deadline_enforced')?.checked),
      },
      status:item.status || 'draft', due_at:field('due_at')?.value ? new Date(field('due_at').value).toISOString() : '',
    };
  }

  async function saveAssessment(id, reload = true) {
    const payload = readAssessmentEditor(id);
    if (!payload) return null;
    const status = document.querySelector(`[data-assessment-save-status="${CSS.escape(id)}"]`);
    if (status) status.textContent = 'Saving…';
    try {
      const saved = await api(`/api/assessments/${encodeURIComponent(id)}`, {method:'PATCH', body:JSON.stringify(payload)});
      if (status) { status.textContent = 'Assessment saved.'; status.className = 'small-status success'; }
      if (reload) await loadDashboard();
      return saved;
    } catch (error) {
      if (status) { status.textContent = error.message; status.className = 'small-status error'; }
      throw error;
    }
  }

  async function generateAssessmentDraft() {
    const classId = $('assessmentClass')?.value;
    if (!classId) return setStatus('assessmentStatus', 'Select a course.', 'error');
    setStatus('assessmentStatus', 'Generating a lecturer-editable draft…');
    try {
      const created = await api(`/api/classes/${encodeURIComponent(classId)}/assessments/draft`, { method:'POST', body:JSON.stringify({ assessment_type:$('assessmentType').value, topic:$('assessmentTopic').value.trim(), learning_outcome:$('assessmentOutcome').value.trim(), question_count:Number($('assessmentCount').value || 5), difficulty:$('assessmentDifficulty').value }) });
      await api(`/api/assessments/${encodeURIComponent(created.id)}`, {method:'PATCH', body:JSON.stringify({
        ...created,
        settings:{...(created.settings || {}), attempts_allowed:Number($('assessmentAttempts')?.value || 2), pass_mark:Number($('assessmentPassMark')?.value || 70), hints_allowed:Boolean($('assessmentHintsAllowed')?.checked), reveal_answers:Boolean($('assessmentRevealAnswers')?.checked), contributes_to_mastery:true},
        status:'draft'
      })});
      setStatus('assessmentStatus', 'Draft created. Open it below to edit questions and marking guides before publishing.', 'success');
      await loadDashboard();
    } catch (error) { setStatus('assessmentStatus', error.message, 'error'); }
  }

  async function publishAssessment(id) {
    const item = state.lastDashboard?.assessments?.find(row => row.id === id);
    if (!item) return;
    try {
      const edited = readAssessmentEditor(id) || item;
      await api(`/api/assessments/${encodeURIComponent(id)}`, { method:'PATCH', body:JSON.stringify({ ...edited, status:'published', settings:edited.settings || item.settings || {} }) });
      await loadDashboard();
    } catch (error) { alert(error.message); }
  }

  async function deleteAssessment(id) {
    if (!confirm('Delete this assessment and its saved attempts?')) return;
    try { await api(`/api/assessments/${encodeURIComponent(id)}`, { method:'DELETE' }); await loadDashboard(); }
    catch (error) { alert(error.message); }
  }

  function questionInput(question, index) {
    const qid = esc(question.id || `q${index+1}`);
    if (question.question_type === 'multiple_choice' && question.options?.length) {
      return `<div class="assessment-options">${question.options.map(option => `<label><input type="radio" name="assessment-${qid}" value="${esc(option)}"> ${esc(option)}</label>`).join('')}</div>`;
    }
    const mode = question.response_mode || (question.question_type === 'oral' ? 'voice' : question.question_type === 'whiteboard' ? 'whiteboard' : question.question_type === 'upload' ? 'upload' : 'typed');
    if (mode === 'voice' || question.question_type === 'oral') {
      return `<div class="assessment-multimodal-response"><textarea data-assessment-answer="${qid}" data-response-mode="voice" rows="5" placeholder="Your recorded response will be transcribed here. You may correct obvious transcription errors before submission."></textarea><div class="inline-actions"><button type="button" data-assessment-record="${qid}">🎙 Record oral response</button><span data-assessment-record-status="${qid}" class="small-status"></span></div></div>`;
    }
    if (mode === 'whiteboard' || question.question_type === 'whiteboard') {
      return `<div class="assessment-multimodal-response"><textarea data-assessment-answer="${qid}" data-response-mode="whiteboard" rows="5" placeholder="The extracted handwriting and workings will appear here."></textarea><label class="file-button"><input type="file" data-assessment-file="${qid}" data-response-mode="whiteboard" accept="image/jpeg,image/png,image/webp,image/gif"><span>Photograph or upload handwritten response</span></label><span data-assessment-file-status="${qid}" class="small-status"></span><p class="small-note">You may write on the full-screen practice whiteboard, download or photograph the work, then attach it here.</p></div>`;
    }
    if (mode === 'upload' || question.question_type === 'upload') {
      return `<div class="assessment-multimodal-response"><textarea data-assessment-answer="${qid}" data-response-mode="upload" rows="5" placeholder="Readable content extracted from the uploaded response will appear here."></textarea><label class="file-button"><input type="file" data-assessment-file="${qid}" data-response-mode="upload" accept=".pdf,.docx,.txt,.md,.csv,image/jpeg,image/png,image/webp"><span>Upload response file</span></label><span data-assessment-file-status="${qid}" class="small-status"></span></div>`;
    }
    return `<textarea data-assessment-answer="${qid}" data-response-mode="typed" rows="5" placeholder="Enter your response."></textarea>`;
  }

  function assessmentRecordingMime() {
    const choices = ['audio/webm;codecs=opus','audio/webm','audio/mp4','audio/ogg;codecs=opus'];
    return choices.find(value => window.MediaRecorder?.isTypeSupported?.(value)) || '';
  }

  async function toggleAssessmentRecording(button) {
    if (assessmentMediaRecorder?.state === 'recording') {
      assessmentMediaRecorder.stop();
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) return alert('Audio recording is not supported in this browser.');
    try {
      assessmentMediaStream = await navigator.mediaDevices.getUserMedia({audio:true});
      const mimeType = assessmentRecordingMime();
      assessmentAudioChunks = [];
      assessmentRecordButton = button;
      assessmentMediaRecorder = mimeType ? new MediaRecorder(assessmentMediaStream,{mimeType}) : new MediaRecorder(assessmentMediaStream);
      const qid = button.dataset.assessmentRecord;
      const status = document.querySelector(`[data-assessment-record-status="${CSS.escape(qid)}"]`);
      assessmentMediaRecorder.addEventListener('dataavailable', event => { if (event.data?.size) assessmentAudioChunks.push(event.data); });
      assessmentMediaRecorder.addEventListener('stop', async () => {
        button.disabled = true; button.textContent = 'Transcribing…';
        assessmentMediaStream?.getTracks().forEach(track=>track.stop());
        try {
          const blob = new Blob(assessmentAudioChunks,{type:assessmentMediaRecorder.mimeType || 'audio/webm'});
          const extension = blob.type.includes('mp4') ? 'm4a' : blob.type.includes('ogg') ? 'ogg' : 'webm';
          const form = new FormData(); form.append('file',blob,`oral-response.${extension}`); form.append('response_mode','voice');
          const data = await api('/api/assessment/response/extract',{method:'POST',body:form});
          const target = document.querySelector(`[data-assessment-answer="${CSS.escape(qid)}"]`);
          if (target) target.value = data.text || '';
          if (status) { status.textContent='Oral response transcribed. Review it before submission.'; status.className='small-status success'; }
        } catch (error) { if(status){status.textContent=error.message;status.className='small-status error';} }
        finally { button.disabled=false; button.textContent='🎙 Record oral response'; assessmentMediaRecorder=null; assessmentRecordButton=null; }
      },{once:true});
      assessmentMediaRecorder.start();
      button.textContent='■ Stop recording';
      if (status) { status.textContent='Recording… speak clearly.'; status.className='small-status'; }
    } catch (error) { alert(error.message || 'Microphone access was not granted.'); }
  }

  async function extractAssessmentFile(input) {
    const file = input.files?.[0]; if (!file) return;
    const qid = input.dataset.assessmentFile;
    const status = document.querySelector(`[data-assessment-file-status="${CSS.escape(qid)}"]`);
    if (status) { status.textContent='Reading response…'; status.className='small-status'; }
    try {
      const form = new FormData(); form.append('file',file,file.name); form.append('response_mode',input.dataset.responseMode || 'upload');
      const data = await api('/api/assessment/response/extract',{method:'POST',body:form});
      const target = document.querySelector(`[data-assessment-answer="${CSS.escape(qid)}"]`);
      if (target) target.value = data.text || '';
      if (status) { status.textContent='Response extracted. Review the text before submission.'; status.className='small-status success'; }
    } catch (error) { if(status){status.textContent=error.message;status.className='small-status error';} }
  }

  async function startPersistentAssessment(id) {
    try {
      const data = await api(`/api/assessments/${encodeURIComponent(id)}/start`, { method:'POST' });
      const workspace = $('assessmentWorkspace');
      workspace.classList.remove('hidden');
      workspace.dataset.attemptId = data.attempt_id;
      workspace.dataset.assessmentId = id;
      workspace.innerHTML = `<h3>${esc(data.assessment.title)}</h3><p>${esc(data.assessment.instructions || '')}</p><div class="assessment-questions">${(data.assessment.questions || []).map((question,index) => `<article class="assessment-question"><header><strong>${index+1}. ${esc(question.prompt)}</strong><span>${esc(question.difficulty || 'standard')}</span></header>${questionInput(question,index)}${question.hint ? `<details><summary>Hint</summary><p>${esc(question.hint)}</p></details>` : ''}</article>`).join('')}</div><div class="assessment-submit-row"><button id="submitPersistentAssessment" class="primary" type="button">Submit assessment</button><span id="assessmentAttemptStatus" class="small-status"></span></div>`;
      $('submitPersistentAssessment').addEventListener('click', submitPersistentAssessment);
      workspace.querySelectorAll('[data-assessment-record]').forEach(button => button.addEventListener('click', () => toggleAssessmentRecording(button)));
      workspace.querySelectorAll('[data-assessment-file]').forEach(input => input.addEventListener('change', () => extractAssessmentFile(input)));
      workspace.scrollIntoView({ behavior:'smooth', block:'start' });
    } catch (error) { alert(error.message); }
  }

  async function submitPersistentAssessment() {
    const workspace = $('assessmentWorkspace');
    const responses = [];
    workspace.querySelectorAll('[data-assessment-answer]').forEach(node => responses.push({ question_id:node.dataset.assessmentAnswer, answer:node.value.trim(), mode:node.dataset.responseMode || 'typed' }));
    workspace.querySelectorAll('.assessment-options').forEach(group => { const selected=group.querySelector('input:checked'); const qid=group.querySelector('input')?.name?.replace('assessment-','') || ''; responses.push({question_id:qid, answer:selected?.value || '', mode:'typed'}); });
    setStatus('assessmentAttemptStatus', 'Submitting and marking…');
    try {
      const data = await api(`/api/assessment-attempts/${encodeURIComponent(workspace.dataset.attemptId)}/submit`, { method:'POST', body:JSON.stringify({responses, hints_used:0}) });
      workspace.innerHTML = `<div class="assessment-result ${data.passed ? 'pass' : 'review'}"><h3>${data.passed ? 'Assessment completed' : 'Further learning recommended'}</h3><strong class="assessment-score">${esc(Math.round(data.score))}%</strong><p>${esc(data.feedback?.summary || '')}</p>${(data.feedback?.misconceptions || []).length ? `<h4>Concepts to revisit</h4><ul>${data.feedback.misconceptions.map(item=>`<li>${esc(item)}</li>`).join('')}</ul>`:''}<p><strong>Next:</strong> ${esc(data.next_action?.label || 'Continue with the recommended course activity.')}</p></div>`;
      await loadClasses();
    } catch (error) { setStatus('assessmentAttemptStatus', error.message, 'error'); }
  }

  async function completeReview(id) {
    try { await api(`/api/revision/${encodeURIComponent(id)}/complete`, {method:'POST'}); await loadDashboard(); }
    catch (error) { alert(error.message); }
  }

  async function saveStudentNote(type='note', classId='', sectionId='') {
    const title = window.prompt(type === 'bookmark' ? 'Bookmark title' : 'Note title', type === 'bookmark' ? 'Saved lesson' : 'My note');
    if (title === null) return;
    const content = type === 'bookmark' ? (window.aiTutorLastAnswer?.() || '') : window.prompt('Write your note') || '';
    try { await api('/api/student/notes', {method:'POST', body:JSON.stringify({class_id:classId || $('classSelect')?.value || '', section_id:sectionId, note_type:type, title, content, metadata:{saved_from:'student_portal'}})}); await loadDashboard(); }
    catch (error) { alert(error.message); }
  }

  async function deleteStudentNote(id) {
    try { await api(`/api/student/notes/${encodeURIComponent(id)}`, {method:'DELETE'}); await loadDashboard(); }
    catch (error) { alert(error.message); }
  }

  async function openRemediation(item) {
    const classId = item.class_id || $('classSelect')?.value || '';
    if (!classId) return alert('Open the relevant course first.');
    try {
      const data = await api('/api/remediation', {method:'POST', body:JSON.stringify({class_id:classId, topic:item.topic || '', learning_outcome:item.learning_outcome || '', misconception:item.metadata?.last_misconception || `Current mastery is ${item.mastery_score}%`, previous_answer:''})});
      closeDialog('dashboardDialog');
      window.aiTutorAddMessage?.('assistant', `# ${data.title}\n\n${data.diagnosis}\n\n## Rebuild the prerequisite\n${data.prerequisite}\n\n## Explanation\n${data.explanation}\n\n## Worked example\n${data.worked_example}\n\n## Try again\n${data.retry_question}`, data.sources || []);
      window.aiTutorRenderVisual?.(data.visual, null);
    } catch (error) { alert(error.message); }
  }

  function applyAccessibility(mode = '') {
    const keyByMode = {large:'aiTutorLargeText',contrast:'aiTutorHighContrast',reading:'aiTutorReadingFriendly'};
    const classByMode = {large:'large-text',contrast:'high-contrast',reading:'reading-friendly'};
    if (mode && keyByMode[mode]) {
      const next = !document.body.classList.contains(classByMode[mode]);
      document.body.classList.toggle(classByMode[mode], next);
      localStorage.setItem(keyByMode[mode], String(next));
      return;
    }
    document.body.classList.toggle('large-text', localStorage.getItem('aiTutorLargeText') === 'true');
    document.body.classList.toggle('high-contrast', localStorage.getItem('aiTutorHighContrast') === 'true');
    document.body.classList.toggle('reading-friendly', localStorage.getItem('aiTutorReadingFriendly') === 'true');
  }

  async function beginScheduledReview(id) {
    const item = state.lastDashboard?.reviews_due?.find(row => row.id === id);
    if (!item) return;
    selectCourse(item.class_id);
    closeDialog('dashboardDialog');
    const topic = item.topic || item.learning_outcome || 'this course topic';
    window.aiTutorAskFollowUp?.(`Give me a short retrieval-practice activity on ${topic}. Ask me to recall the idea before showing any explanation. After I respond, diagnose gaps, give one corrective example and ask me to try again.`);
  }

  function continueRecommendedCourse(classId, topic = '') {
    selectCourse(classId);
    closeDialog('dashboardDialog');
    if (topic) window.aiTutorAskFollowUp?.(`Continue my recommended learning pathway by teaching ${topic}. Begin with a quick prerequisite check, teach it step by step, pause to test me, and finish with a short practice question.`);
  }


  async function openMasteryCertificate(classId) {
    try {
      const response = await fetch(`/api/student/certificate/${encodeURIComponent(classId)}`, {cache:'no-store'});
      if (!response.ok) {
        let detail='Certificate could not be prepared.'; try {detail=(await response.json()).detail || detail;} catch {}
        throw new Error(detail);
      }
      const blob = await response.blob(); const url=URL.createObjectURL(blob); window.open(url,'_blank','noopener'); setTimeout(()=>URL.revokeObjectURL(url),60000);
    } catch (error) { alert(error.message); }
  }

  async function downloadRevisionSheet(format = 'html') {
    const classId = $('classSelect')?.value || '';
    const path = format === 'docx' ? '/api/student/revision-sheet.docx' : '/api/student/revision-sheet';
    try {
      const response = await fetch(`${path}?class_id=${encodeURIComponent(classId)}`, {cache:'no-store'});
      if (!response.ok) {
        let detail = 'Revision sheet could not be prepared.';
        try { detail = (await response.json()).detail || detail; } catch {}
        throw new Error(detail);
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      if (format === 'docx') {
        const link = document.createElement('a'); link.href = url; link.download = 'ai-tutor-revision-sheet.docx'; link.click();
        setTimeout(() => URL.revokeObjectURL(url), 2000);
      } else {
        window.open(url, '_blank', 'noopener');
        setTimeout(() => URL.revokeObjectURL(url), 60000);
      }
    } catch (error) { alert(error.message); }
  }

  function wireCompleteLearningActions() {
    $('generateAssessmentDraft')?.addEventListener('click', generateAssessmentDraft);
    document.querySelectorAll('[data-save-assessment]').forEach(button => button.addEventListener('click', () => saveAssessment(button.dataset.saveAssessment)));
    document.querySelectorAll('[data-publish-assessment]').forEach(button => button.addEventListener('click', () => publishAssessment(button.dataset.publishAssessment)));
    document.querySelectorAll('[data-delete-assessment]').forEach(button => button.addEventListener('click', () => deleteAssessment(button.dataset.deleteAssessment)));
    document.querySelectorAll('[data-start-assessment]').forEach(button => button.addEventListener('click', () => startPersistentAssessment(button.dataset.startAssessment)));
    document.querySelectorAll('[data-complete-review]').forEach(button => button.addEventListener('click', () => completeReview(button.dataset.completeReview)));
    document.querySelectorAll('[data-review-now]').forEach(button => button.addEventListener('click', () => beginScheduledReview(button.dataset.reviewNow)));
    document.querySelectorAll('[data-next-course]').forEach(button => button.addEventListener('click', () => continueRecommendedCourse(button.dataset.nextCourse, button.dataset.nextTopic || '')));
    document.querySelectorAll('[data-delete-note]').forEach(button => button.addEventListener('click', () => deleteStudentNote(button.dataset.deleteNote)));
    document.querySelectorAll('[data-remediate]').forEach(button => button.addEventListener('click', () => { const item=state.lastDashboard?.mastery_records?.find(row=>row.mastery_key===button.dataset.remediate && (!button.dataset.remediateClass || row.class_id===button.dataset.remediateClass)); if(item) openRemediation(item); }));
    $('saveQuickNote')?.addEventListener('click', () => saveStudentNote('note'));
    $('saveBookmark')?.addEventListener('click', () => saveStudentNote('bookmark'));
    $('downloadRevisionSheet')?.addEventListener('click', () => downloadRevisionSheet('html'));
    $('downloadRevisionDocx')?.addEventListener('click', () => downloadRevisionSheet('docx'));
    document.querySelectorAll('[data-accessibility]').forEach(button => button.addEventListener('click', () => applyAccessibility(button.dataset.accessibility)));
    document.querySelectorAll('[data-certificate-course]').forEach(button => button.addEventListener('click', () => openMasteryCertificate(button.dataset.certificateCourse)));
  }


  function courseName(data, classId) {
    const row = (data.classes || []).find(item => item.id === classId);
    return row?.name || row?.subject || 'Course';
  }

  function masteryStatusLabel(status) {
    return {not_started:'Not started',needs_foundation:'Needs foundation',developing:'Developing',competent:'Competent',mastered:'Mastered'}[status] || status || 'Not started';
  }

  function nextActionCard(data) {
    const action = data.next_recommended_action || {};
    if (!action.label) return '<div class="next-action-card"><span class="eyebrow">Recommended next</span><h3>Open a course to begin learning</h3><p>Your diagnostic and activity history will shape the next recommendation.</p></div>';
    let button = '';
    if (action.type === 'diagnostic' && action.assessment_id) button = `<button class="primary" type="button" data-start-assessment="${esc(action.assessment_id)}">Start diagnostic</button>`;
    else if (action.type === 'revision' && action.id) button = `<button class="primary" type="button" data-review-now="${esc(action.id)}">Start review</button>`;
    else if (action.class_id) button = `<button class="primary" type="button" data-next-course="${esc(action.class_id)}" data-next-topic="${esc(action.topic || '')}">Continue learning</button>`;
    return `<div class="next-action-card"><span class="eyebrow">Recommended next</span><h3>${esc(action.label)}</h3><p>The recommendation is based on diagnostics, current mastery and scheduled review.</p>${button}</div>`;
  }

  function renderStudentAssessments(data) {
    const rows = (data.assessments || []).filter(item => item.status === 'published');
    return rows.length ? rows.map(item => `<div class="student-assessment-row"><div><strong>${esc(item.title)}</strong><small>${esc(courseName(data,item.class_id))} • ${esc(item.assessment_type.replaceAll('_',' '))}${item.due_at ? ` • Due ${esc(new Date(item.due_at).toLocaleDateString())}` : ''}</small></div><button class="primary" type="button" data-start-assessment="${esc(item.id)}">${item.assessment_type==='diagnostic'?'Start diagnostic':'Open'}</button></div>`).join('') : '<p class="small-note">No published assessment is waiting.</p>';
  }

  function renderReviews(data) {
    const rows = data.reviews_due || [];
    return rows.length ? rows.map(item => `<div class="review-due-row"><div><strong>${esc(item.topic || item.learning_outcome || 'Course review')}</strong><small>${esc(courseName(data,item.class_id))} • ${item.overdue ? 'Due now' : `Scheduled ${esc(new Date(item.due_at).toLocaleDateString())}`}</small></div><div class="inline-actions"><button class="primary" type="button" data-review-now="${esc(item.id)}">Review now</button><button type="button" data-complete-review="${esc(item.id)}">Mark reviewed</button></div></div>`).join('') : '<p class="small-note">Nothing is due for spaced review.</p>';
  }

  function renderLearningPaths(data) {
    const paths = data.learning_paths || [];
    if (!paths.length) return '<p class="small-note">Your pathway appears after you enrol in a course.</p>';
    return paths.map(path => `<article class="learning-path-card"><header><strong>${esc(courseName(data,path.class_id))}</strong><span>${path.milestones?.competent_or_better || 0}/${path.milestones?.total_items || 0} competent</span></header><ol>${(path.items || []).slice(0,12).map(item=>`<li class="path-${esc(item.status)} ${item.recommended?'recommended':''}"><span>${esc(item.title)}</span><strong>${esc(masteryStatusLabel(item.status))}${item.mastery_score ? ` • ${esc(item.mastery_score)}%` : ''}</strong></li>`).join('') || '<li>Course outcomes are being prepared.</li>'}</ol></article>`).join('');
  }

  function renderMasteryRecords(data) {
    const rows = data.mastery_records || [];
    if (!rows.length) return '<p class="small-note">Complete a diagnostic or practice activity to create mastery evidence.</p>';
    return rows.slice(0,30).map(item => `<div class="mastery-record"><div><strong>${esc(item.topic || item.learning_outcome || item.mastery_key)}</strong><small>${esc(courseName(data,item.class_id))} • ${esc(masteryStatusLabel(item.status))} • ${esc(item.evidence_count || 0)} evidence record(s)</small><div class="mastery-meter"><span style="width:${Math.max(0,Math.min(100,Number(item.mastery_score||0)))}%"></span></div></div><div><strong>${esc(Math.round(item.mastery_score || 0))}%</strong>${Number(item.mastery_score||0)<70 ? `<button type="button" data-remediate="${esc(item.mastery_key)}" data-remediate-class="${esc(item.class_id)}">Remedial lesson</button>` : ''}</div></div>`).join('');
  }

  function renderStudentNotes(data) {
    const notes = data.notes || [];
    const list = notes.length ? notes.slice(0,20).map(item=>`<article class="student-note-card"><div><span class="role-badge">${esc(item.note_type.replaceAll('_',' '))}</span><strong>${esc(item.title || 'Saved note')}</strong></div><p>${esc(item.content || '').slice(0,420)}</p><button class="danger-ghost" type="button" data-delete-note="${esc(item.id)}">Delete</button></article>`).join('') : '<p class="small-note">Save notes and bookmarks while studying. They remain private to your account.</p>';
    return `<div class="note-actions"><button id="saveQuickNote" type="button">Add note</button><button id="saveBookmark" type="button">Bookmark latest explanation</button><button id="downloadRevisionSheet" type="button">Open revision sheet</button><button id="downloadRevisionDocx" type="button">Download revision DOCX</button></div><div class="student-note-list">${list}</div>`;
  }

  function renderLecturerDashboard(data) {
    $('dashboardEyebrow').textContent = 'Teaching, assessment and learning intelligence';
    $('dashboardTitle').textContent = 'Lecturer portal';
    const classes = data.classes?.length ? `<div class="lecturer-course-list">${data.classes.map(lecturerClassRow).join('')}</div>` : '<p class="small-note">Create your first course below.</p>';
    const weak = renderRows(data.weak_topics, item => `<div class="data-row"><span>${esc(item.topic)}</span><strong>${esc(item.average_score)}%</strong></div>`, 'No weak topics have been identified.');
    const mastery = renderRows(data.outcome_mastery, item => `<div class="data-row"><div><strong>${esc(item.outcome)}</strong><br><small>${esc(item.evidence_count)} evidence records • ${esc(item.status)}</small></div><strong>${esc(item.average_score)}%</strong></div>`, 'Mastery appears after assessed learning activity.');
    const students = renderRows(data.students, item => `<div class="data-row"><div><strong>${esc(item.display_name)}</strong><br><small>${esc(item.email)}</small></div><div><strong>${item.average_score == null ? '—' : esc(item.average_score)+'%'}</strong><br><small>${esc(item.activities)} activities</small></div></div>`, 'Students appear after using an enrolment code.');
    const unanswered = renderRows(data.unanswered_questions, item => `<div class="data-row"><div><strong>${esc(item.question || item.topic)}</strong><br><small>${esc(item.student_name || '')}</small></div></div>`, 'All recent questions had approved grounding.');
    const misconceptions = renderRows(data.common_misconceptions, item => `<div class="data-row"><div><strong>${esc(item.misconception || item.topic || 'Misconception')}</strong><br><small>${esc(item.count || item.evidence_count || 1)} occurrence(s)</small></div></div>`, 'No recurring misconception has been detected.');
    const interventions = renderRows(data.interventions, item => `<div class="intervention-row"><div><strong>${esc(item.student_name || item.display_name || 'Student support case')}</strong><small>${esc((item.reasons || []).join(' • ') || item.reason || 'Learning support recommended')}</small><p>${esc(item.recommended_action || 'Review the learner evidence and assign a remedial activity.')}</p></div>${item.average_score != null ? `<strong>${esc(Math.round(item.average_score))}%</strong>` : ''}</div>`, 'No student currently meets the intervention threshold.');
    $('dashboardBody').innerHTML = `<div class="dashboard-summary">${summaryCards(data.summary)}</div>${passwordCard()}<div class="dashboard-grid institutional-dashboard">
      <section class="dashboard-section full-span"><h3>Create a course</h3><div class="class-tools"><input id="newClassName" placeholder="Course or class name"><input id="newClassSubject" placeholder="Subject or course code"><button id="createClassButton" class="primary" type="button">Create course and enrolment code</button></div></section>
      <section class="dashboard-section full-span"><h3>My courses and student enrolment codes</h3>${classes}</section>
      ${renderLecturerAssessments(data)}
      <section class="dashboard-section full-span"><h3>Students needing intervention</h3><p class="small-note">The list combines low mastery, repeated misconceptions and weak assessed performance.</p>${interventions}</section>
      <section class="dashboard-section"><h3>Learning-outcome mastery</h3>${mastery}</section>
      <section class="dashboard-section"><h3>Topics needing attention</h3>${weak}</section>
      <section class="dashboard-section"><h3>Common misconceptions</h3>${misconceptions}</section>
      <section class="dashboard-section"><h3>Students</h3>${students}</section>
      <section class="dashboard-section"><h3>Questions needing more approved material</h3>${unanswered}</section>
      <section class="dashboard-section"><h3>Spaced-revision backlog</h3><strong class="large-metric">${esc(data.revision_backlog || 0)}</strong><p class="small-note">Overdue review items across your courses.</p></section>
    </div>`;
    $('createClassButton')?.addEventListener('click', createClass);
    document.querySelectorAll('[data-save-profile]').forEach(button => button.addEventListener('click', () => saveClassProfile(button.dataset.saveProfile)));
    document.querySelectorAll('[data-copy-code]').forEach(button => button.addEventListener('click', () => copyText(button.dataset.copyCode, button)));
    document.querySelectorAll('[data-regenerate-code]').forEach(button => button.addEventListener('click', () => regenerateCode(button.dataset.regenerateCode)));
    document.querySelectorAll('[data-select-course]').forEach(button => button.addEventListener('click', () => selectCourse(button.dataset.selectCourse)));
    document.querySelectorAll('[data-upload-course-documents]').forEach(button => button.addEventListener('click', () => uploadCourseDocuments(button.dataset.uploadCourseDocuments, button)));
    document.querySelectorAll('[data-document-manager]').forEach(details => details.addEventListener('toggle', () => { if (details.open) loadLecturerDocumentSummary(details.dataset.documentManager); }));
  }

  function renderStudentDashboard(data) {
    $('dashboardEyebrow').textContent = 'Your personalised learning home';
    $('dashboardTitle').textContent = 'Student portal';
    const classes = renderRows(data.classes, item => `<button class="student-course-card" type="button" data-select-course="${esc(item.id)}"><span><strong>${esc(item.name)}</strong><small>${esc(item.subject)} • Lecturer: ${esc(item.teacher_name)}</small></span><span>Open course ›</span></button>`, 'Enter a lecturer-provided enrolment code to join a course.');
    const activity = renderRows(data.recent_activity, item => `<div class="data-row"><div><strong>${esc(item.topic || item.event_type)}</strong><br><small>${item.created_at ? esc(new Date(item.created_at).toLocaleDateString()) : ''}</small></div><strong>${item.score == null ? '' : esc(item.score)+'%'}</strong></div>`, 'No learning activity yet.');
    const milestones = data.milestones || {};
    const certificates = (milestones.certificate_courses || []).map(item => `<button type="button" data-certificate-course="${esc(item.class_id)}">Mastery certificate: ${esc(item.course_name)}</button>`).join('');
    const weeklyGoal = Number(milestones.weekly_goal || 3);
    const weeklyDone = Number(milestones.weekly_activities || 0);
    $('dashboardBody').innerHTML = `${nextActionCard(data)}<div class="student-milestones"><div><strong>${esc(milestones.courses_started || 0)}</strong><span>Courses</span></div><div><strong>${esc(milestones.competent_or_better || 0)}</strong><span>Competent outcomes</span></div><div><strong>${esc(milestones.mastered_outcomes || 0)}</strong><span>Mastered outcomes</span></div><div><strong>${esc(milestones.learning_streak_days || 0)}</strong><span>Day learning streak</span></div></div><div class="weekly-goal-card"><div><strong>Weekly learning goal</strong><span>${esc(weeklyDone)} of ${esc(weeklyGoal)} activities</span></div><div class="mastery-meter"><span style="width:${Math.min(100,(weeklyDone/Math.max(1,weeklyGoal))*100)}%"></span></div>${certificates ? `<div class="certificate-actions">${certificates}</div>` : ''}</div>${passwordCard()}<div class="dashboard-grid institutional-dashboard student-learning-home">
      <section class="dashboard-section full-span"><h3>Enrol in a course</h3><div class="class-tools"><input id="joinClassCode" placeholder="Enter lecturer enrolment code"><button id="joinClassButton" class="primary" type="button">Enrol</button></div></section>
      <section class="dashboard-section full-span"><h3>My enrolled courses (${esc(data.classes?.length || 0)})</h3>${classes}</section>
      <section id="studentCourseContents" class="dashboard-section full-span hidden"><h3>Course contents</h3><div id="studentCourseContentsBody"></div></section>
      <section class="dashboard-section full-span"><h3>Diagnostics and assessments</h3>${renderStudentAssessments(data)}<div id="assessmentWorkspace" class="assessment-workspace hidden"></div></section>
      <section class="dashboard-section full-span"><h3>Due for review</h3><p class="small-note">Short retrieval activities are scheduled after learning so important ideas are not forgotten.</p>${renderReviews(data)}</section>
      <section class="dashboard-section full-span"><h3>My personalised pathways</h3>${renderLearningPaths(data)}</section>
      <section class="dashboard-section full-span"><h3>Outcome mastery and remediation</h3>${renderMasteryRecords(data)}</section>
      <section class="dashboard-section"><h3>Recent learning activity</h3>${activity}</section>
      <section class="dashboard-section"><h3>My notes and bookmarks</h3>${renderStudentNotes(data)}</section>
      <section class="dashboard-section"><h3>Reading and accessibility</h3><div class="accessibility-actions"><button type="button" data-accessibility="large">Larger text</button><button type="button" data-accessibility="reading">Reading-friendly font</button><button type="button" data-accessibility="contrast">High contrast</button></div><p class="small-note">Low-data and text-only delivery remain available in the course settings.</p></section>
    </div>`;
    $('joinClassButton')?.addEventListener('click', joinClass);
    document.querySelectorAll('[data-select-course]').forEach(button => button.addEventListener('click', () => openStudentCourse(button.dataset.selectCourse)));
  }

  function wirePasswordChange() { $('changePortalPassword')?.addEventListener('click', changePassword); }
  function renderDashboard(data) {
    state.lastDashboard = data;
    if (data.role === 'admin') renderAdminDashboard(data);
    else if (data.role === 'teacher') renderLecturerDashboard(data);
    else renderStudentDashboard(data);
    wirePasswordChange();
    wireCompleteLearningActions();
  }

  async function loadDashboard() {
    if (!state.user) return openDialog('authDialog');
    openDialog('dashboardDialog');
    $('dashboardBody').innerHTML = '<p>Loading portal…</p>';
    try { renderDashboard(await api('/api/dashboard')); }
    catch (error) { $('dashboardBody').innerHTML = `<p class="practice-feedback error">${esc(error.message)}</p>`; }
  }

  async function createLecturer() {
    const display_name = $('newLecturerName')?.value.trim();
    const email = $('newLecturerEmail')?.value.trim();
    if (!display_name || !email) return setStatus('lecturerCreateStatus', 'Enter the lecturer name and institutional email.', 'error');
    setStatus('lecturerCreateStatus', 'Creating lecturer account…');
    try {
      const data = await api('/api/admin/lecturers', { method: 'POST', body: JSON.stringify({ display_name, email, temporary_password: $('newLecturerPassword')?.value || '' }) });
      const card = $('temporaryCredential');
      card.classList.remove('hidden');
      card.innerHTML = `<strong>Lecturer account created</strong><p>Email: <b>${esc(data.user.email)}</b></p><p>Temporary password: <code>${esc(data.temporary_password)}</code></p><button id="copyLecturerCredentials" type="button">Copy credentials</button><p class="small-note">Share this securely. The lecturer must change the password after first sign-in.</p>`;
      $('copyLecturerCredentials').addEventListener('click', event => copyText(`Email: ${data.user.email}\nTemporary password: ${data.temporary_password}`, event.currentTarget));
      setStatus('lecturerCreateStatus', 'Account created successfully.', 'success');
    } catch (error) { setStatus('lecturerCreateStatus', error.message, 'error'); }
  }

  async function toggleUser(userId, active) {
    try { await api(`/api/admin/users/${encodeURIComponent(userId)}/status`, { method: 'PATCH', body: JSON.stringify({ active }) }); await loadDashboard(); }
    catch (error) { alert(error.message); }
  }
  async function resetUserPassword(userId) {
    if (!confirm('Reset this lecturer password and require a change at next sign-in?')) return;
    try {
      const data = await api(`/api/admin/users/${encodeURIComponent(userId)}/reset-password`, { method: 'POST' });
      window.prompt('Copy the new temporary password and share it securely', data.temporary_password);
      await loadDashboard();
    } catch (error) { alert(error.message); }
  }
  async function changePassword() {
    const current_password = $('currentPortalPassword')?.value || '';
    const new_password = $('newPortalPassword')?.value || '';
    try {
      await api('/api/auth/change-password', { method: 'POST', body: JSON.stringify({ current_password, new_password }) });
      state.user.must_change_password = false;
      setStatus('passwordChangeStatus', 'Password changed successfully.', 'success');
      await loadDashboard();
    } catch (error) { setStatus('passwordChangeStatus', error.message, 'error'); }
  }

  async function loadLecturerDocumentSummary(classId) {
    const container = document.querySelector(`[data-course-documents="${CSS.escape(classId)}"]`);
    if (!container) return;
    container.innerHTML = '<p class="small-note">Loading course documents…</p>';
    try {
      const data = await api(`/api/classes/${encodeURIComponent(classId)}/course-structure`);
      const docs = data.documents || [];
      container.innerHTML = docs.length ? docs.map(doc => {
        const needsRefresh = doc.document_type === 'course_outline'
          && !(doc.weekly_topics || []).length
          && !(doc.sections || []).some(section => /^week\s+\d+/i.test(String(section.title || '')));
        return `<div class="lecturer-document-row"><div><strong>${esc(doc.title || doc.filename)}</strong><small>${documentTypeLabel(doc.document_type)} • ${(doc.sections || []).length} sections</small>${needsRefresh ? '<small class="document-refresh-warning">Re-upload this outline once to rebuild its week-by-week topics and subtopics.</small>' : ''}</div><button type="button" data-remove-inline-document="${esc(doc.id)}" data-class-id="${esc(classId)}">Remove</button></div>`;
      }).join('') : '<p class="small-note">No teaching documents have been uploaded.</p>';
      container.querySelectorAll('[data-remove-inline-document]').forEach(button => button.addEventListener('click', async () => {
        await deleteDocument(button.dataset.classId, button.dataset.removeInlineDocument, button);
        await loadLecturerDocumentSummary(classId);
      }));
    } catch (error) { container.innerHTML = `<p class="practice-feedback error">${esc(error.message)}</p>`; }
  }

  async function uploadCourseDocuments(classId, button) {
    const manager = button.closest('[data-document-manager]');
    const files = [...(manager?.querySelector('[data-course-document-files]')?.files || [])];
    const status = manager?.querySelector('[data-course-document-status]');
    const documentType = manager?.querySelector('[data-course-document-type]')?.value || 'teaching_notes';
    if (!files.length) { if (status) { status.textContent = 'Select at least one document.'; status.className = 'small-status error'; } return; }
    const form = new FormData();
    form.append('class_id', classId);
    form.append('document_type', documentType);
    files.forEach(file => form.append('files', file, file.name));
    button.disabled = true;
    if (status) { status.textContent = 'Reading headings, objectives, subsections and references…'; status.className = 'small-status'; }
    try {
      const result = await api('/api/materials/upload', { method: 'POST', body: form });
      const uploaded = result.uploaded || [];
      const errors = result.errors || [];
      if (status) {
        status.textContent = `${uploaded.length} document${uploaded.length === 1 ? '' : 's'} structured.${errors.length ? ` ${errors.length} issue(s) require attention.` : ''}`;
        status.className = `small-status ${errors.length ? 'warning' : 'success'}`;
      }
      const fileInput = manager?.querySelector('[data-course-document-files]');
      if (fileInput) fileInput.value = '';
      await loadClasses();
      await loadLecturerDocumentSummary(classId);
      if (selectedClass()?.id === classId) await loadCourseStructure(classId);
    } catch (error) { if (status) { status.textContent = error.message; status.className = 'small-status error'; } }
    finally { button.disabled = false; }
  }

  function portalDocumentTree(data) {
    const documents = data.documents || [];
    const weeklyPlan = data.weekly_plan || [];
    const weekSectionIds = new Set();
    weeklyPlan.forEach(item => {
      if (item.id) weekSectionIds.add(String(item.id));
      (item.subunits || []).forEach(subunit => {
        if (typeof subunit === 'object' && subunit?.id) weekSectionIds.add(String(subunit.id));
      });
    });

    const legacyOutlineNeedsRefresh = documents.some(doc => doc.document_type === 'course_outline'
      && !(doc.weekly_topics || []).length
      && !(doc.sections || []).some(section => /^week\s+\d+/i.test(String(section.title || ''))));
    const refreshNotice = legacyOutlineNeedsRefresh ? '<div class="course-structure-warning"><strong>The course outline needs restructuring.</strong><span>The lecturer should re-upload the same outline once so its weeks, topics and subtopics can be displayed correctly.</span></div>' : '';

    const weekly = weeklyPlan.length ? `
      <section class="student-weekly-plan">
        <div class="student-content-heading">
          <div><span class="eyebrow">Course learning path</span><h3>Week-by-week topics and activities</h3></div>
          <p>Choose a week or one of its subtopics for a detailed AI-guided lesson.</p>
        </div>
        ${weeklyPlan.map(item => {
          const subunits = item.subunits || [];
          const preparation = item.preparation || [];
          return `<article class="weekly-plan-card">
            <button type="button" class="student-course-card compact" data-portal-teach-section="${esc(item.id)}">
              <span><strong>${esc(item.title)}</strong><small>${item.generated ? 'Prepared from course objectives and expected outcomes' : `${subunits.length} subtopic${subunits.length === 1 ? '' : 's'}`}</small></span>
              <span>Start lesson ›</span>
            </button>
            ${subunits.length ? `<div class="weekly-plan-subunits"><p class="weekly-plan-label">Topics and subtopics</p>${subunits.map(subunit => typeof subunit === 'string'
              ? `<span>${esc(subunit)}</span>`
              : `<button type="button" class="course-section-button" data-portal-teach-section="${esc(subunit.id)}"><span>${esc(subunit.title)}</span><small>Open this subtopic</small></button>`).join('')}</div>` : ''}
            ${preparation.length ? `<details class="weekly-preparation"><summary>Student preparation and activities</summary><ul>${preparation.map(item => `<li>${esc(item)}</li>`).join('')}</ul></details>` : ''}
          </article>`;
        }).join('')}
      </section>` : '';

    const noiseTitle = title => {
      const clean = String(title || '').trim();
      return !clean
        || /^complete document$/i.test(clean)
        || /^supporting table\s+\d+$/i.test(clean)
        || /^table\s+\d+$/i.test(clean)
        || /^4(?:\.0)?\s+course outline:?$/i.test(clean)
        || /^20\d{2}\s*\/\s*20\d{2}.*semester$/i.test(clean);
    };

    const docs = documents.map(doc => {
      const sections = (doc.sections || []).filter(section => !weekSectionIds.has(String(section.id)) && !noiseTitle(section.title));
      if (!sections.length && doc.document_type === 'course_outline' && weeklyPlan.length) return '';
      return `<details class="course-document" ${doc.document_type === 'course_outline' ? 'open' : ''}>
        <summary><span><strong>${esc(doc.title || doc.filename)}</strong><small>${documentTypeLabel(doc.document_type)}</small></span></summary>
        <div class="course-section-tree">${sections.length ? sections.map(section => `<button type="button" class="course-section-button" data-portal-teach-section="${esc(section.id)}" style="--section-level:${Math.max(1, Number(section.level) || 1)}"><span>${esc(section.title)}</span><small>${esc(section.section_path || '')}</small></button>`).join('') : '<p class="small-note">The week-by-week outline is displayed above.</p>'}</div>
      </details>`;
    }).join('');

    if (!weekly && !docs) return '<p class="small-note">No course plan or teaching material has been uploaded. Ask the lecturer to add course objectives or a course outline.</p>';
    return refreshNotice + weekly + docs;
  }



  async function openStudentCourse(classId) {
    localStorage.setItem(CLASS_KEY, classId);
    if ($('classSelect')) $('classSelect').value = classId;
    applySelectedClass();
    const panel = $('studentCourseContents');
    const body = $('studentCourseContentsBody');
    panel?.classList.remove('hidden');
    if (body) body.innerHTML = '<p>Loading structured course contents…</p>';
    try {
      const data = await api(`/api/classes/${encodeURIComponent(classId)}/course-structure`);
      if (body) body.innerHTML = portalDocumentTree(data);
      body?.querySelectorAll('[data-portal-teach-section]').forEach(button => button.addEventListener('click', async () => {
        closeDialog('dashboardDialog');
        await teachSection(button.dataset.portalTeachSection, null);
      }));
      panel?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (error) { if (body) body.innerHTML = `<p class="practice-feedback error">${esc(error.message)}</p>`; }
  }

  async function createClass() {
    const name = $('newClassName')?.value.trim();
    if (!name) return;
    try {
      const classroom = await api('/api/classes', { method:'POST', body:JSON.stringify({
        name, subject:$('newClassSubject')?.value.trim() || $('course')?.value || '', knowledge_mode:'course_only',
        learning_outcomes:[], weekly_topics:[], recommended_readings:[], tutor_instructions:'', practice_whiteboard_required:false, practice_response_mode:'student_choice',
        diagnostics_required:true, spaced_revision_enabled:true, mastery_pass_mark:70, direct_answers_allowed:true, hints_allowed:true, assignment_help_mode:'guided', integrity_mode:'learning',
      }) });
      await loadClasses();
      localStorage.setItem(CLASS_KEY, classroom.id);
      await loadDashboard();
    } catch (error) { alert(error.message); }
  }

  async function saveClassProfile(classId) {
    const root = document.querySelector(`[data-profile="${CSS.escape(classId)}"]`);
    const status = root?.querySelector('[data-profile-status]');
    if (!root) return;
    if (status) status.textContent = 'Saving…';
    const field = name => root.querySelector(`[data-field="${name}"]`);
    try {
      await api(`/api/classes/${encodeURIComponent(classId)}/profile`, { method:'PATCH', body:JSON.stringify({
        name:field('name')?.value || '', subject:field('subject')?.value || '', knowledge_mode:field('knowledge_mode')?.value || 'course_only',
        learning_outcomes:lines(field('learning_outcomes')?.value), weekly_topics:lines(field('weekly_topics')?.value),
        recommended_readings:lines(field('recommended_readings')?.value), tutor_instructions:field('tutor_instructions')?.value || '',
        practice_whiteboard_required:(field('practice_response_mode')?.value === 'whiteboard'),
        practice_response_mode:field('practice_response_mode')?.value || 'student_choice',
        diagnostics_required:Boolean(field('diagnostics_required')?.checked),
        spaced_revision_enabled:Boolean(field('spaced_revision_enabled')?.checked),
        mastery_pass_mark:Number(field('mastery_pass_mark')?.value || 70),
        direct_answers_allowed:Boolean(field('direct_answers_allowed')?.checked),
        hints_allowed:Boolean(field('hints_allowed')?.checked),
        assignment_help_mode:field('assignment_help_mode')?.value || 'guided',
        integrity_mode:field('integrity_mode')?.value || 'learning',
      }) });
      if (status) { status.textContent = 'Course profile saved.'; status.className = 'small-status success'; }
      await loadClasses();
    } catch (error) { if (status) { status.textContent = error.message; status.className = 'small-status error'; } }
  }

  async function regenerateCode(classId) {
    if (!confirm('Generate a new enrolment code? The previous code will stop working.')) return;
    try { await api(`/api/classes/${encodeURIComponent(classId)}/regenerate-code`, { method:'POST' }); await loadClasses(); await loadDashboard(); }
    catch (error) { alert(error.message); }
  }

  async function joinClass() {
    const join_code = $('joinClassCode')?.value.trim();
    if (!join_code) return;
    try { const classroom = await api('/api/classes/join', { method:'POST', body:JSON.stringify({ join_code }) }); await loadClasses(); selectCourse(classroom.id); closeDialog('dashboardDialog'); }
    catch (error) { alert(error.message); }
  }

  function selectCourse(classId) {
    localStorage.setItem(CLASS_KEY, classId);
    if ($('classSelect')) $('classSelect').value = classId;
    applySelectedClass();
    closeDialog('dashboardDialog');
    document.querySelector('.sidebar')?.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function latestTutorAnswer() { return [...document.querySelectorAll('.message.assistant .message-body')].at(-1)?.innerText?.trim() || ''; }
  function renderVideoJob(job) {
    const playable = job.hosted_url || job.stream_url || job.download_url;
    const links = [job.hosted_url ? `<a href="${esc(job.hosted_url)}" target="_blank" rel="noopener">Open video</a>` : '', job.download_url ? `<a href="${esc(job.download_url)}" target="_blank" rel="noopener">Download video</a>` : '', job.status !== 'script_ready' && !playable ? `<button type="button" data-refresh-video="${esc(job.id)}">Refresh status</button>` : ''].filter(Boolean).join('');
    return `<article class="video-job" data-video-job="${esc(job.id)}"><div class="video-job-head"><strong>${esc(job.title)}</strong><span class="role-badge">${esc(job.status)}</span></div><p>${esc(job.estimated_minutes)} minute reusable lesson • ${esc(job.provider)}</p>${links ? `<div class="video-links">${links}</div>` : ''}${job.script ? `<details><summary>Read the detailed lesson script</summary><p>${esc(job.script)}</p></details>` : ''}</article>`;
  }
  async function loadVideos() {
    if (!state.user) return;
    try { const jobs = await api('/api/videos'); $('lessonVideoList').innerHTML = jobs.length ? jobs.map(renderVideoJob).join('') : '<p class="small-note">No reusable lessons have been assigned yet.</p>'; document.querySelectorAll('[data-refresh-video]').forEach(button => button.addEventListener('click', () => refreshVideo(button.dataset.refreshVideo))); }
    catch (error) { $('lessonVideoList').innerHTML = `<p class="practice-feedback error">${esc(error.message)}</p>`; }
  }
  async function refreshVideo(id) { try { const job = await api(`/api/video/${encodeURIComponent(id)}`); const node = document.querySelector(`[data-video-job="${CSS.escape(id)}"]`); if (node) node.outerHTML = renderVideoJob(job); } catch (error) { setStatus('lessonVideoStatus', error.message, 'error'); } }
  async function generateLessonVideo() {
    const topic = $('lessonVideoTopic').value.trim(); const classId = $('lessonVideoClass').value;
    if (!classId) return setStatus('lessonVideoStatus', 'Select a course.', 'error');
    if (!topic) return setStatus('lessonVideoStatus', 'Enter a lesson topic.', 'error');
    const classroom = state.classes.find(item => item.id === classId);
    setStatus('lessonVideoStatus', 'Preparing a detailed reusable script and slide lesson…'); $('generateLessonVideo').disabled = true;
    try {
      const job = await api('/api/video/generate', { method:'POST', body:JSON.stringify({ topic, class_id:classId, course:classroom?.subject || classroom?.name || '', level:$('level')?.value || 'University', length:$('lessonVideoLength').value, use_current_answer:Boolean(latestTutorAnswer()), current_answer:latestTutorAnswer().slice(0,16000) }) });
      setStatus('lessonVideoStatus', job.video_id ? 'Reusable video submitted and shared with the course.' : 'Detailed script and slides are ready and shared with the course.', 'success'); await loadVideos();
    } catch (error) { setStatus('lessonVideoStatus', error.message, 'error'); } finally { $('generateLessonVideo').disabled = false; }
  }

  function signOut() {
    state.token = ''; state.user = null; state.classes = []; state.courseStructure = null;
    localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(CLASS_KEY);
    updateAccountUI(); fillClassSelectors();
  }

  document.addEventListener('DOMContentLoaded', async () => {
    applyAccessibility();
    document.querySelectorAll('[data-close-dialog]').forEach(button => button.addEventListener('click', () => closeDialog(button.dataset.closeDialog)));
    $('openSignIn')?.addEventListener('click', () => { setAuthMode('student_login'); openDialog('authDialog'); });
    $('showAdminLogin')?.addEventListener('click', () => setAuthMode('admin_login'));
    $('showLecturerLogin')?.addEventListener('click', () => setAuthMode('teacher_login'));
    $('showStudentLogin')?.addEventListener('click', () => setAuthMode('student_login'));
    $('showRegister')?.addEventListener('click', () => setAuthMode('register'));
    $('showAdminSetup')?.addEventListener('click', () => setAuthMode('bootstrap'));
    $('authForm')?.addEventListener('submit', submitAuth);
    $('signOutButton')?.addEventListener('click', signOut);
    $('openDashboard')?.addEventListener('click', loadDashboard);
    $('refreshCourseStructure')?.addEventListener('click', () => loadCourseStructure(selectedClass()?.id || ''));
    $('openLessonVideo')?.addEventListener('click', async () => { $('lessonVideoTopic').value = $('practiceTopic')?.value || $('weekSelect')?.value || $('course')?.value || ''; openDialog('lessonVideoDialog'); await loadVideos(); });
    $('generateLessonVideo')?.addEventListener('click', generateLessonVideo);
    setAuthMode('student_login'); await loadConfig(); await restoreUser();
  });

  window.aiTutorPortalState = state;
})();
