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
    const classroom = data.classroom || selectedClass();
    $('courseStructureStatus').textContent = documents.length
      ? `${documents.length} structured document${documents.length === 1 ? '' : 's'}. Select a subsection for a grounded AI lesson.`
      : 'The lecturer has not uploaded structured teaching documents for this course yet.';
    if (!documents.length) {
      list.innerHTML = '<div class="course-empty">No course outline, teaching notes or recommended readings have been uploaded.</div>';
      return;
    }
    const groups = ['course_outline', 'teaching_notes', 'recommended_reading'];
    list.innerHTML = groups.map(type => {
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
      add?.('assistant', data.answer, data.sources || []);
      render?.(data.visual, null);
      if ($('practiceTopic')) $('practiceTopic').value = data.section_title || data.title || '';
      $('courseStructureStatus').textContent = `Lesson ready: ${data.section_title || 'selected subsection'}`;
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
    const lecturer = signedIn && state.user.role === 'teacher';
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
        <label class="toggle-row"><input data-field="practice_whiteboard_required" type="checkbox" ${item.practice_whiteboard_required ? 'checked' : ''}><span>Require handwritten practice-whiteboard responses</span></label>
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

  function renderLecturerDashboard(data) {
    $('dashboardEyebrow').textContent = 'Teaching, enrolment and learning intelligence';
    $('dashboardTitle').textContent = 'Lecturer portal';
    const classes = data.classes?.length ? `<div class="lecturer-course-list">${data.classes.map(lecturerClassRow).join('')}</div>` : '<p class="small-note">Create your first course below.</p>';
    const weak = renderRows(data.weak_topics, item => `<div class="data-row"><span>${esc(item.topic)}</span><strong>${esc(item.average_score)}%</strong></div>`, 'No weak topics have been identified.');
    const mastery = renderRows(data.outcome_mastery, item => `<div class="data-row"><div><strong>${esc(item.outcome)}</strong><br><small>${esc(item.evidence_count)} evidence records • ${esc(item.status)}</small></div><strong>${esc(item.average_score)}%</strong></div>`, 'Mastery appears after assessed learning activity.');
    const students = renderRows(data.students, item => `<div class="data-row"><div><strong>${esc(item.display_name)}</strong><br><small>${esc(item.email)}</small></div><div><strong>${item.average_score == null ? '—' : esc(item.average_score)+'%'}</strong><br><small>${esc(item.activities)} activities</small></div></div>`, 'Students appear after using an enrolment code.');
    const unanswered = renderRows(data.unanswered_questions, item => `<div class="data-row"><div><strong>${esc(item.question || item.topic)}</strong><br><small>${esc(item.student_name || '')}</small></div></div>`, 'All recent questions had approved grounding.');
    $('dashboardBody').innerHTML = `<div class="dashboard-summary">${summaryCards(data.summary)}</div>${passwordCard()}<div class="dashboard-grid institutional-dashboard">
      <section class="dashboard-section full-span"><h3>Create a course</h3><div class="class-tools"><input id="newClassName" placeholder="Course or class name"><input id="newClassSubject" placeholder="Subject or course code"><button id="createClassButton" class="primary" type="button">Create course and enrolment code</button></div></section>
      <section class="dashboard-section full-span"><h3>My courses and student enrolment codes</h3>${classes}</section>
      <section class="dashboard-section"><h3>Learning-outcome mastery</h3>${mastery}</section>
      <section class="dashboard-section"><h3>Topics needing attention</h3>${weak}</section>
      <section class="dashboard-section"><h3>Students</h3>${students}</section>
      <section class="dashboard-section"><h3>Questions needing more approved material</h3>${unanswered}</section>
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
    $('dashboardEyebrow').textContent = 'Enrolment, courses and progress';
    $('dashboardTitle').textContent = 'Student portal';
    const classes = renderRows(data.classes, item => `<button class="student-course-card" type="button" data-select-course="${esc(item.id)}"><span><strong>${esc(item.name)}</strong><small>${esc(item.subject)} • Lecturer: ${esc(item.teacher_name)}</small></span><span>Open course ›</span></button>`, 'Enter a lecturer-provided enrolment code to join a course.');
    const mastery = renderRows(data.outcome_mastery, item => `<div class="data-row"><div><strong>${esc(item.outcome)}</strong><br><small>${esc(item.status)}</small></div><strong>${esc(item.average_score)}%</strong></div>`, 'No mastery evidence yet.');
    const weak = renderRows(data.weak_topics, item => `<div class="data-row"><span>${esc(item.topic)}</span><strong>${esc(item.average_score)}%</strong></div>`, 'No weak topics have been identified.');
    const activity = renderRows(data.recent_activity, item => `<div class="data-row"><div><strong>${esc(item.topic || item.event_type)}</strong><br><small>${item.created_at ? esc(new Date(item.created_at).toLocaleDateString()) : ''}</small></div><strong>${item.score == null ? '' : esc(item.score)+'%'}</strong></div>`, 'No learning activity yet.');
    $('dashboardBody').innerHTML = `<div class="dashboard-summary">${summaryCards(data.summary)}</div>${passwordCard()}<div class="dashboard-grid institutional-dashboard">
      <section class="dashboard-section full-span"><h3>Enrol in a course</h3><div class="class-tools"><input id="joinClassCode" placeholder="Enter lecturer enrolment code"><button id="joinClassButton" class="primary" type="button">Enrol</button></div></section>
      <section class="dashboard-section full-span"><h3>All enrolled courses (${esc(data.classes?.length || 0)})</h3><p class="small-note">Every course joined with a valid lecturer enrolment code is listed below.</p>${classes}</section>
      <section id="studentCourseContents" class="dashboard-section full-span hidden"><h3>Course contents</h3><div id="studentCourseContentsBody"></div></section>
      <section class="dashboard-section"><h3>Learning-outcome mastery</h3>${mastery}</section>
      <section class="dashboard-section"><h3>Topics to revisit</h3>${weak}</section>
      <section class="dashboard-section"><h3>Recent learning activity</h3>${activity}</section>
    </div>`;
    $('joinClassButton')?.addEventListener('click', joinClass);
    document.querySelectorAll('[data-select-course]').forEach(button => button.addEventListener('click', () => openStudentCourse(button.dataset.selectCourse)));
  }

  function wirePasswordChange() { $('changePortalPassword')?.addEventListener('click', changePassword); }
  function renderDashboard(data) {
    if (data.role === 'admin') renderAdminDashboard(data);
    else if (data.role === 'teacher') renderLecturerDashboard(data);
    else renderStudentDashboard(data);
    wirePasswordChange();
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
      container.innerHTML = docs.length ? docs.map(doc => `<div class="lecturer-document-row"><div><strong>${esc(doc.title || doc.filename)}</strong><small>${documentTypeLabel(doc.document_type)} • ${(doc.sections || []).length} subsections</small></div><button type="button" data-remove-inline-document="${esc(doc.id)}" data-class-id="${esc(classId)}">Remove</button></div>`).join('') : '<p class="small-note">No teaching documents have been uploaded.</p>';
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
    if (!documents.length) return '<p class="small-note">The lecturer has not uploaded structured teaching documents yet.</p>';
    return documents.map(doc => `<details class="course-document" open><summary><span><strong>${esc(doc.title || doc.filename)}</strong><small>${documentTypeLabel(doc.document_type)}</small></span></summary><div class="course-section-tree">${(doc.sections || []).map(section => `<button type="button" class="course-section-button" data-portal-teach-section="${esc(section.id)}" style="--section-level:${Math.max(1, Number(section.level) || 1)}"><span>${esc(section.title)}</span><small>${esc(section.section_path || '')}</small></button>`).join('')}</div></details>`).join('');
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
        learning_outcomes:[], weekly_topics:[], recommended_readings:[], tutor_instructions:'', practice_whiteboard_required:false,
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
        practice_whiteboard_required:Boolean(field('practice_whiteboard_required')?.checked),
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
