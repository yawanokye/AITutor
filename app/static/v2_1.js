(() => {
  'use strict';

  const WORKSPACE_KEY = 'anovladAiTutorWorkspaceV2_1';
  let restoringWorkspace = false;
  let persistTimer = null;
  let diagramDrag = null;

  Object.assign(state, {
    practice: null,
    teachingActive: false,
    teachingRunId: 0,
    teachingAbortController: null
  });

  function debouncePersist() {
    if (restoringWorkspace) return;
    clearTimeout(persistTimer);
    persistTimer = setTimeout(saveWorkspace, 250);
  }

  function saveWorkspace() {
    try {
      const visual = state.visualPlan?.kind === 'image_annotation' ? null : state.visualPlan;
      const payload = {
        version: '5.0.3',
        sessionId: state.sessionId,
        chatLog: state.chatLog.slice(-80),
        lastAnswer: state.lastAnswer,
        visualPlan: visual,
        visualIndex: state.visualIndex,
        strokes: state.strokes.slice(-250),
        settings: {
          course: el('course').value,
          classSelect: el('classSelect')?.value || '',
          outcomeSelect: el('outcomeSelect')?.value || '',
          weekSelect: el('weekSelect')?.value || '',
          deliveryMode: el('deliveryMode')?.value || 'standard',
          level: el('level').value,
          tutorMode: el('tutorMode').value,
          visualPreference: el('visualPreference').value,
          visualRequested: el('visualRequested').checked,
          autoSpeak: el('autoSpeak').checked,
          voice: el('voice').value
        },
        savedAt: new Date().toISOString()
      };
      localStorage.setItem(WORKSPACE_KEY, JSON.stringify(payload));
    } catch (error) {
      console.warn('Workspace could not be saved', error);
    }
  }

  function restoreSetting(id, value) {
    const control = el(id);
    if (!control || value === undefined || value === null) return;
    if (control.type === 'checkbox') control.checked = Boolean(value);
    else if ([...control.options || []].some(option => option.value === value)) control.value = value;
    else if (!control.options) control.value = value;
  }

  function restoreWorkspace() {
    const raw = localStorage.getItem(WORKSPACE_KEY);
    if (!raw) return;
    try {
      const saved = JSON.parse(raw);
      if (!saved || !Array.isArray(saved.chatLog)) return;
      restoringWorkspace = true;
      state.sessionId = saved.sessionId || state.sessionId;
      localStorage.setItem('aiTutorSessionId', state.sessionId);
      state.chatLog = [];
      [...messages.querySelectorAll('.message:not(.welcome-message)')].forEach(node => node.remove());
      saved.chatLog.forEach(item => addMessage(item.role, item.text, item.sources || []));
      state.lastAnswer = saved.lastAnswer || '';
      el('replayButton').disabled = !state.lastAnswer;
      const settings = saved.settings || {};
      restoreSetting('course', settings.course);
      restoreSetting('deliveryMode', settings.deliveryMode);
      window.aiTutorApplyDeliveryMode?.(settings.deliveryMode || 'standard');
      const restoreClassContext = () => {
        restoreSetting('classSelect', settings.classSelect);
        window.aiTutorClassChanged?.();
        setTimeout(() => {
          restoreSetting('outcomeSelect', settings.outcomeSelect);
          restoreSetting('weekSelect', settings.weekSelect);
        }, 120);
      };
      setTimeout(restoreClassContext, 600);
      setTimeout(restoreClassContext, 1400);
      restoreSetting('level', settings.level);
      restoreSetting('tutorMode', settings.tutorMode);
      restoreSetting('visualPreference', settings.visualPreference);
      restoreSetting('visualRequested', settings.visualRequested);
      restoreSetting('autoSpeak', settings.autoSpeak);
      const applyVoice = () => restoreSetting('voice', settings.voice);
      setTimeout(applyVoice, 700);
      if (saved.visualPlan) {
        renderVisual(saved.visualPlan, null);
        state.visualIndex = Math.max(0, Number(saved.visualIndex) || 0);
        renderCurrentVisual();
        state.strokes = Array.isArray(saved.strokes) ? saved.strokes : [];
        requestAnimationFrame(redrawStrokes);
      }
      if (saved.chatLog.length) setStatus('Previous learning session restored.');
    } catch (error) {
      console.warn('Saved workspace could not be restored', error);
      localStorage.removeItem(WORKSPACE_KEY);
    } finally {
      restoringWorkspace = false;
    }
  }

  const originalAddMessage = addMessage;
  addMessage = function enhancedAddMessage(role, text, sources = []) {
    originalAddMessage(role, text, sources);
    debouncePersist();
  };

  const originalRenderVisual = renderVisual;
  renderVisual = function enhancedRenderVisual(plan, imageUrl = null) {
    originalRenderVisual(plan, imageUrl);
    const available = Boolean(plan && plan.kind !== 'none');
    el('teachVisual').disabled = !available;
    el('editVisual').disabled = !['graph', 'table'].includes(plan?.kind);
    el('checkWork').disabled = !available && state.strokes.length === 0;
    debouncePersist();
  };

  const originalRenderCurrentVisual = renderCurrentVisual;
  renderCurrentVisual = function enhancedRenderCurrentVisual() {
    originalRenderCurrentVisual();
    el('editVisual').disabled = !['graph', 'table'].includes(state.visualPlan?.kind);
    debouncePersist();
  };

  function visualPageCount(plan) {
    if (!plan) return 0;
    if (plan.kind === 'steps') return Math.max(plan.steps?.length || 0, 1);
    if (plan.kind === 'slides') return Math.max(plan.slides?.length || 0, 1);
    return plan.kind === 'none' ? 0 : 1;
  }

  function currentVisualNarration(plan, includeIntro = false) {
    if (!plan) return '';
    const intro = includeIntro ? [plan.title, plan.caption].filter(Boolean).join('. ') : '';
    if (plan.kind === 'steps') {
      const step = plan.steps?.[state.visualIndex];
      return [intro, `Step ${state.visualIndex + 1}`, step?.title, step?.narration || step?.explanation, step?.equation, step?.learner_prompt].filter(Boolean).join('. ');
    }
    if (plan.kind === 'slides') {
      const slide = plan.slides?.[state.visualIndex];
      return [intro, slide?.title, ...(slide?.bullets || []), slide?.explanation, slide?.equation, slide?.worked_example, ...(slide?.key_terms || []), slide?.check_question, slide?.speaker_note].filter(Boolean).join('. ');
    }
    return [intro, visualPlanToSpeech(plan)].filter(Boolean).join('. ');
  }

  async function speakAndWait(text, runId) {
    if (!state.config?.openai_enabled) throw new Error('Voice output needs OPENAI_API_KEY to be configured.');
    state.teachingAbortController?.abort();
    const controller = new AbortController();
    state.teachingAbortController = controller;
    const response = await fetch('/api/speech', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, voice: el('voice').value }),
      signal: controller.signal
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.detail || 'Voice generation failed.');
    }
    const blob = await response.blob();
    if (runId !== state.teachingRunId) return;
    if (state.lastAudioUrl) URL.revokeObjectURL(state.lastAudioUrl);
    state.lastAudioUrl = URL.createObjectURL(blob);
    audioPlayer.src = state.lastAudioUrl;
    audioPlayer.hidden = false;
    await new Promise((resolve, reject) => {
      const finished = () => { cleanup(); resolve(); };
      const failed = () => { cleanup(); reject(new Error('Audio playback failed.')); };
      const cleanup = () => {
        audioPlayer.removeEventListener('ended', finished);
        audioPlayer.removeEventListener('error', failed);
      };
      audioPlayer.addEventListener('ended', finished, { once: true });
      audioPlayer.addEventListener('error', failed, { once: true });
      audioPlayer.play().catch(failed);
    });
  }

  async function startStepTeaching() {
    const plan = state.visualPlan;
    const count = visualPageCount(plan);
    if (!count) {
      setStatus('Create a visual explanation before starting guided narration.');
      return;
    }
    stopStepTeaching(false);
    state.teachingActive = true;
    const runId = ++state.teachingRunId;
    el('teachVisual').classList.add('hidden');
    el('stopTeaching').classList.remove('hidden');
    visualViewport.classList.add('teaching-mode');
    setStatus('Teaching the visual step by step…');
    try {
      for (let index = state.visualIndex; index < count; index += 1) {
        if (!state.teachingActive || runId !== state.teachingRunId) break;
        state.visualIndex = index;
        clearInk(false);
        renderCurrentVisual();
        visualContent.classList.add('teaching-focus');
        await speakAndWait(currentVisualNarration(plan, index === 0), runId);
        visualContent.classList.remove('teaching-focus');
      }
      if (state.teachingActive && runId === state.teachingRunId) setStatus('Visual lesson complete.');
    } catch (error) {
      if (error.name !== 'AbortError') setStatus(error.message);
    } finally {
      if (runId === state.teachingRunId) stopStepTeaching(false);
    }
  }

  function stopStepTeaching(updateStatus = true) {
    state.teachingActive = false;
    state.teachingRunId += 1;
    state.teachingAbortController?.abort();
    state.teachingAbortController = null;
    audioPlayer.pause();
    visualContent.classList.remove('teaching-focus');
    visualViewport.classList.remove('teaching-mode');
    el('teachVisual').classList.remove('hidden');
    el('stopTeaching').classList.add('hidden');
    if (updateStatus) setStatus('Step-by-step teaching stopped.');
  }

  function annotationClass(item) {
    const allowed = ['info', 'success', 'warning', 'error'];
    return allowed.includes(item?.severity) ? `severity-${item.severity}` : 'severity-info';
  }

  renderImageAnnotation = function enhancedImageAnnotation(plan) {
    if (!state.visualImageUrl) {
      visualContent.innerHTML = '<div class="whiteboard-empty"><h3>The image preview is no longer available</h3><p>Upload the image again to receive positioned highlights.</p></div>';
      return;
    }
    const annotations = plan.annotations || [];
    const boxes = annotations.map((item, index) => {
      const labelY = Math.max(Number(item.y) + 30, 35);
      return `
        <g class="annotation-group ${annotationClass(item)}">
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
        <div class="annotation-key">${annotations.map((item, index) => `<span class="${annotationClass(item)}"><b>${index + 1}</b>${escapeHtml(item.label)}</span>`).join('')}</div>
      </div>`;
  };

  renderDiagram = function editableDiagram(plan) {
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
    const nodeMarkup = nodes.map(node => {
      const shape = node.shape === 'circle'
        ? '<circle cx="0" cy="0" r="75" class="diagram-node" />'
        : `<rect x="-100" y="-48" width="200" height="96" rx="${node.shape === 'pill' ? 50 : 18}" class="diagram-node" />`;
      return `<g class="diagram-node-group" data-node-id="${escapeHtml(node.id)}" transform="translate(${Number(node.x)} ${Number(node.y)})">${shape}<foreignObject x="-86" y="-35" width="172" height="70"><div xmlns="http://www.w3.org/1999/xhtml" class="node-label">${escapeHtml(node.label)}</div></foreignObject></g>`;
    }).join('');
    visualContent.innerHTML = `
      <div class="diagram-board">
        <svg viewBox="0 0 1000 1000" class="diagram-svg" role="img" aria-label="${escapeHtml(plan.title || 'Labelled diagram')}">
          <defs><marker id="arrow" markerWidth="12" markerHeight="12" refX="10" refY="6" orient="auto"><path d="M0,0 L12,6 L0,12 z" class="arrow-head" /></marker></defs>
          ${edgeMarkup}${nodeMarkup}
        </svg>
      </div>`;
    visualContent.querySelectorAll('.diagram-node-group').forEach(group => {
      group.addEventListener('pointerdown', event => {
        if (state.tool !== 'pointer') return;
        event.preventDefault();
        diagramDrag = { id: group.dataset.nodeId };
        document.body.classList.add('dragging-diagram-node');
      });
    });
  };

  function svgPoint(event, svg) {
    const point = svg.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    const matrix = svg.getScreenCTM();
    return matrix ? point.matrixTransform(matrix.inverse()) : { x: 500, y: 500 };
  }

  window.addEventListener('pointermove', event => {
    if (!diagramDrag || state.visualPlan?.kind !== 'diagram') return;
    const svg = visualContent.querySelector('.diagram-svg');
    if (!svg) return;
    const point = svgPoint(event, svg);
    const node = state.visualPlan.nodes?.find(item => item.id === diagramDrag.id);
    if (!node) return;
    node.x = Math.max(80, Math.min(920, point.x));
    node.y = Math.max(80, Math.min(920, point.y));
    renderDiagram(state.visualPlan);
    debouncePersist();
  });
  window.addEventListener('pointerup', () => {
    if (!diagramDrag) return;
    diagramDrag = null;
    document.body.classList.remove('dragging-diagram-node');
    debouncePersist();
  });

  function parseCsvLine(line) {
    const values = [];
    let value = '';
    let quoted = false;
    for (let index = 0; index < line.length; index += 1) {
      const char = line[index];
      if (char === '"') {
        if (quoted && line[index + 1] === '"') { value += '"'; index += 1; }
        else quoted = !quoted;
      } else if (char === ',' && !quoted) {
        values.push(value.trim()); value = '';
      } else value += char;
    }
    values.push(value.trim());
    return values;
  }

  function csvEscape(value) {
    const text = String(value ?? '');
    return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
  }

  function openVisualEditor() {
    const plan = state.visualPlan;
    const dialog = el('visualEditorDialog');
    const area = el('visualEditorData');
    el('visualEditorError').textContent = '';
    if (plan?.kind === 'table') {
      el('visualEditorTitle').textContent = 'Edit table data';
      el('visualEditorHelp').textContent = 'The first row contains headings. Keep the same number of cells in each row.';
      area.value = [plan.table_headers, ...(plan.table_rows || [])].map(row => row.map(csvEscape).join(',')).join('\n');
    } else if (plan?.kind === 'graph') {
      el('visualEditorTitle').textContent = 'Edit graph data';
      el('visualEditorHelp').textContent = 'The first row is x followed by series names. Each next row contains an x value and one y value per series.';
      const series = plan.series || [];
      const xValues = [...new Set(series.flatMap(item => item.points || []).map(point => Number(point.x)))].sort((a, b) => a - b);
      const rows = [['x', ...series.map(item => item.name || 'Series')]];
      xValues.forEach(x => rows.push([x, ...series.map(item => item.points?.find(point => Number(point.x) === x)?.y ?? '')]));
      area.value = rows.map(row => row.map(csvEscape).join(',')).join('\n');
    } else {
      setStatus('Only graphs and tables currently have a data editor. Diagram nodes can be dragged directly.');
      return;
    }
    dialog.showModal();
  }

  function applyVisualEdit(event) {
    event.preventDefault();
    const lines = el('visualEditorData').value.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
    if (lines.length < 2) {
      el('visualEditorError').textContent = 'Enter a heading row and at least one data row.';
      return;
    }
    const rows = lines.map(parseCsvLine);
    try {
      if (state.visualPlan.kind === 'table') {
        const width = rows[0].length;
        if (!width || rows.slice(1).some(row => row.length !== width)) throw new Error('Every table row must contain the same number of cells.');
        state.visualPlan.table_headers = rows[0].slice(0, 8);
        state.visualPlan.table_rows = rows.slice(1, 13).map(row => row.slice(0, 8));
      } else if (state.visualPlan.kind === 'graph') {
        const headers = rows[0];
        if (headers.length < 2) throw new Error('Add at least one graph series after the x column.');
        const series = headers.slice(1, 6).map(name => ({ name: name || 'Series', points: [] }));
        rows.slice(1, 31).forEach((row, rowIndex) => {
          const x = Number(row[0]);
          if (!Number.isFinite(x)) throw new Error(`Row ${rowIndex + 2} has an invalid x value.`);
          series.forEach((item, index) => {
            const raw = row[index + 1];
            if (raw === undefined || raw === '') return;
            const y = Number(raw);
            if (!Number.isFinite(y)) throw new Error(`Row ${rowIndex + 2} has an invalid y value.`);
            item.points.push({ x, y, label: '' });
          });
        });
        if (!series.some(item => item.points.length)) throw new Error('Enter at least one numeric graph point.');
        state.visualPlan.series = series;
      }
      el('visualEditorDialog').close();
      clearInk(false);
      renderCurrentVisual();
      setStatus('Visual data updated.');
      debouncePersist();
    } catch (error) {
      el('visualEditorError').textContent = error.message;
    }
  }

  function practiceFeedback(html, tone = 'info') {
    const box = el('practiceFeedback');
    box.className = `practice-feedback ${tone}`;
    box.innerHTML = html;
  }

  function renderPracticeQuestion(data) {
    state.practice = {
      ...(state.practice || {}),
      id: data.practice_id,
      current: data,
      hint: data.hint || '',
      pendingNext: null,
      useBoard: Boolean(window.aiTutorGetSelectedClass?.()?.practice_whiteboard_required),
      boardRequired: Boolean(window.aiTutorGetSelectedClass?.()?.practice_whiteboard_required)
    };
    el('practicePanel').classList.remove('hidden');
    el('practiceTitle').textContent = data.title || 'Guided practice';
    el('practicePrompt').textContent = data.prompt;
    el('practiceDifficulty').textContent = (data.difficulty || 'standard').replace('_', ' ');
    el('practiceProgressText').textContent = `Question ${data.question_number} of ${data.question_count}`;
    el('practiceScore').textContent = `Score ${data.score || 0}%`;
    const percentage = Math.max(0, Math.min(100, ((data.question_number - 1) / data.question_count) * 100));
    el('practiceProgressBar').style.width = `${percentage}%`;
    el('practiceAnswer').value = '';
    el('checkPractice').textContent = 'Check answer';
    el('checkPractice').disabled = false;
    el('revealPractice').disabled = false;
    el('practiceFeedback').className = 'practice-feedback hidden';
    window.aiTutorPracticeBoard?.reset();
    if (state.practice.boardRequired) window.aiTutorPracticeBoard?.show(true); else window.aiTutorPracticeBoard?.hide();
    if (data.visual && data.visual.kind !== 'none') {
      renderVisual(data.visual, null);
    } else {
      clearInk(false);
    }
    setMobileView('chat');
    el('practiceAnswer').focus();
  }

  async function startPractice() {
    const topic = el('practiceTopic').value.trim() || el('course').value.trim() || question.value.trim();
    if (!topic) {
      setStatus('Enter a practice topic first.');
      el('practiceTopic').focus();
      return;
    }
    const form = new FormData();
    form.append('topic', topic);
    form.append('course', el('course').value.trim());
    form.append('level', el('level').value);
    form.append('question_count', el('practiceCount').value);
    form.append('class_id', el('classSelect')?.value || '');
    form.append('learning_outcome', el('outcomeSelect')?.value || '');
    form.append('weekly_topic', el('weekSelect')?.value || '');
    el('startPractice').disabled = true;
    setStatus('Creating a guided practice activity…', true);
    try {
      const data = await apiJson('/api/practice/start', { method: 'POST', body: form });
      renderPracticeQuestion(data);
      closeSidebar();
      setStatus('Practice activity ready.');
    } catch (error) {
      setStatus(error.message);
    } finally {
      el('startPractice').disabled = false;
      sendButton.disabled = false;
      recordButton.disabled = false;
    }
  }

  function closePractice() {
    state.practice = null;
    el('practicePanel').classList.add('hidden');
    window.aiTutorPracticeBoard?.hide();
    setStatus('Guided practice closed.');
  }

  async function practiceBoardBlob() {
    const practiceBlob = await window.aiTutorPracticeBoard?.toBlob?.();
    if (practiceBlob) return practiceBlob;
    if (!state.practice?.useBoard && state.strokes.length === 0) return null;
    const canvas = await captureBoardCanvas();
    return new Promise(resolve => canvas.toBlob(resolve, 'image/png', 0.92));
  }

  async function checkPracticeAnswer() {
    if (!state.practice) return;
    if (state.practice.pendingNext) {
      renderPracticeQuestion(state.practice.pendingNext);
      return;
    }
    const answer = el('practiceAnswer').value.trim();
    const practiceInk = Boolean(window.aiTutorPracticeBoard?.hasInk?.());
    if (state.practice.boardRequired && !practiceInk) {
      practiceFeedback('Your lecturer requires handwritten working on the practice whiteboard.', 'warning');
      window.aiTutorPracticeBoard?.show(true);
      return;
    }
    if (!answer && !practiceInk && !state.practice.useBoard && state.strokes.length === 0) {
      practiceFeedback('Type an answer or use the practice whiteboard first.', 'warning');
      return;
    }
    const form = new FormData();
    form.append('practice_id', state.practice.id);
    form.append('answer', answer);
    el('checkPractice').disabled = true;
    setStatus('Checking your answer…', true);
    try {
      const blob = await practiceBoardBlob();
      if (blob) form.append('board_image', blob, 'practice-whiteboard.png');
      const data = await apiJson('/api/practice/check', { method: 'POST', body: form });
      const tone = data.correct ? 'success' : 'warning';
      const hint = data.hint ? `<p><strong>Hint:</strong> ${escapeHtml(data.hint)}</p>` : '';
      practiceFeedback(`<strong>${data.correct ? 'Correct' : 'Try again'}</strong><p>${escapeHtml(data.feedback)}</p>${hint}`, tone);
      el('practiceScore').textContent = `Score ${data.total_score}%`;
      if (data.completed) {
        el('practiceProgressBar').style.width = '100%';
        el('practiceProgressText').textContent = 'Practice complete';
        el('checkPractice').disabled = true;
        el('revealPractice').disabled = true;
        practiceFeedback(`<strong>Practice complete</strong><p>${escapeHtml(data.feedback)}</p><p>Your final score is ${data.total_score}%.</p>`, 'success');
        setStatus('Practice activity complete.');
      } else if (data.correct && data.next_question) {
        state.practice.pendingNext = data.next_question;
        el('checkPractice').textContent = 'Next question';
        el('checkPractice').disabled = false;
        clearInk(false);
        window.aiTutorPracticeBoard?.reset();
        setStatus('Correct. Continue when ready.');
      } else {
        el('checkPractice').disabled = false;
        setStatus('Review the feedback and try again.');
      }
    } catch (error) {
      practiceFeedback(escapeHtml(error.message), 'error');
      el('checkPractice').disabled = false;
      setStatus(error.message);
    } finally {
      sendButton.disabled = false;
      recordButton.disabled = false;
    }
  }

  function showPracticeHint() {
    if (!state.practice) return;
    const hint = state.practice.hint || 'Break the question into smaller steps and identify what is known and what must be found.';
    practiceFeedback(`<strong>Hint</strong><p>${escapeHtml(hint)}</p>`, 'info');
  }

  function usePracticeWhiteboard() {
    if (!state.practice) return;
    state.practice.useBoard = true;
    window.aiTutorPracticeBoard?.show(Boolean(state.practice.boardRequired));
    window.aiTutorPracticeBoard?.setTool?.('pen');
    el('practiceWhiteboardWrap')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    setStatus('Write your response on the separate practice whiteboard, then select Check answer.');
  }

  async function revealPracticeSolution() {
    if (!state.practice) return;
    const form = new FormData();
    form.append('practice_id', state.practice.id);
    setStatus('Preparing the worked solution…', true);
    try {
      const data = await apiJson('/api/practice/reveal', { method: 'POST', body: form });
      practiceFeedback(`<strong>Expected answer</strong><p>${escapeHtml(data.expected_answer)}</p><strong>Explanation</strong><p>${escapeHtml(data.explanation)}</p>`, 'info');
      if (data.completed) {
        el('practiceProgressBar').style.width = '100%';
        el('practiceProgressText').textContent = 'Practice complete';
        el('checkPractice').disabled = true;
        el('revealPractice').disabled = true;
      } else if (data.next_question) {
        state.practice.pendingNext = data.next_question;
        el('checkPractice').textContent = 'Next question';
      }
      setStatus('Solution displayed. Review it before continuing.');
    } catch (error) {
      practiceFeedback(escapeHtml(error.message), 'error');
      setStatus(error.message);
    } finally {
      sendButton.disabled = false;
      recordButton.disabled = false;
    }
  }

  function workCheckMarkup(data) {
    const strengths = (data.strengths || []).map(item => `<li>${escapeHtml(item)}</li>`).join('');
    const corrections = (data.corrections || []).map(item => `<li>${escapeHtml(item)}</li>`).join('');
    const steps = (data.step_results || []).map(step => `
      <div class="step-assessment ${escapeHtml(step.status || 'unclear')}">
        <div><strong>Step ${Number(step.step_number) || 1}</strong><span>${escapeHtml((step.status || 'unclear').replace('_', ' '))}</span></div>
        <p>${escapeHtml(step.label || '')}</p>
        <small>${escapeHtml(step.feedback || '')}${step.correction ? ` Correction: ${escapeHtml(step.correction)}` : ''}</small>
      </div>`).join('');
    return `
      <div class="score-ring" style="--score:${Number(data.score) || 0}"><strong>${Number(data.score) || 0}%</strong><span>${escapeHtml((data.verdict || 'unclear').replace('_', ' '))}</span></div>
      <p>${escapeHtml(data.summary || '')}</p>
      ${data.first_error_step ? `<div class="first-error"><strong>First step needing correction:</strong> Step ${Number(data.first_error_step)}</div>` : '<div class="first-error success"><strong>No definite error point was identified.</strong></div>'}
      ${steps ? `<h3>Step-by-step assessment</h3><div class="step-assessment-list">${steps}</div>` : ''}
      ${strengths ? `<h3>What is working</h3><ul>${strengths}</ul>` : ''}
      ${corrections ? `<h3>Corrections required</h3><ul>${corrections}</ul>` : ''}
      ${data.next_step ? `<div class="next-step-box"><strong>Next step</strong><p>${escapeHtml(data.next_step)}</p></div>` : ''}`;
  }

  async function checkWhiteboardWork() {
    if (!state.visualPlan && state.strokes.length === 0) {
      setStatus('Write or display some working on the whiteboard first.');
      return;
    }
    setStatus('Checking the visible working…', true);
    try {
      const canvas = await captureBoardCanvas();
      const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png', 0.94));
      if (!blob) throw new Error('The whiteboard could not be captured.');
      const form = new FormData();
      const lastQuestion = [...state.chatLog].reverse().find(item => item.role === 'user')?.text || '';
      form.append('problem_context', lastQuestion);
      form.append('board_context', JSON.stringify({ visual: state.visualPlan, visible_page: state.visualIndex + 1, ink_strokes: state.strokes.length }));
      form.append('level', el('level').value);
      form.append('course', el('course').value.trim());
      form.append('class_id', el('classSelect')?.value || '');
      form.append('learning_outcome', el('outcomeSelect')?.value || '');
      form.append('weekly_topic', el('weekSelect')?.value || '');
      form.append('board_image', blob, 'whiteboard-check.png');
      const data = await apiJson('/api/work/check', { method: 'POST', body: form });
      el('workCheckBody').innerHTML = workCheckMarkup(data);
      el('workCheckDialog').showModal();
      const imageUrl = URL.createObjectURL(blob);
      renderVisual(data.visual, imageUrl);
      const summary = `Whiteboard check: ${data.score}%. ${data.summary}${data.next_step ? ` Next step: ${data.next_step}` : ''}`;
      addMessage('assistant', summary);
      setStatus('Whiteboard feedback ready.');
    } catch (error) {
      setStatus(error.message);
    } finally {
      sendButton.disabled = false;
      recordButton.disabled = false;
    }
  }

  el('teachVisual').addEventListener('click', startStepTeaching);
  el('stopTeaching').addEventListener('click', () => stopStepTeaching(true));
  el('checkWork').addEventListener('click', checkWhiteboardWork);
  el('editVisual').addEventListener('click', openVisualEditor);
  el('applyVisualEdit').addEventListener('click', applyVisualEdit);
  el('startPractice').addEventListener('click', startPractice);
  el('closePractice').addEventListener('click', closePractice);
  el('checkPractice').addEventListener('click', checkPracticeAnswer);
  el('practiceHint').addEventListener('click', showPracticeHint);
  el('practiceBoard').addEventListener('click', usePracticeWhiteboard);
  el('revealPractice').addEventListener('click', revealPracticeSolution);
  el('practiceAnswer').addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      checkPracticeAnswer();
    }
  });

  ['course', 'classSelect', 'outcomeSelect', 'weekSelect', 'deliveryMode', 'level', 'tutorMode', 'visualPreference', 'visualRequested', 'autoSpeak', 'voice'].forEach(id => {
    el(id)?.addEventListener('change', debouncePersist);
  });
  drawingCanvas.addEventListener('pointerup', () => {
    el('checkWork').disabled = !state.visualPlan && state.strokes.length === 0;
    debouncePersist();
  });
  el('undoInk').addEventListener('click', () => {
    el('checkWork').disabled = !state.visualPlan && state.strokes.length === 0;
    debouncePersist();
  });
  el('redoInk').addEventListener('click', () => {
    el('checkWork').disabled = !state.visualPlan && state.strokes.length === 0;
    debouncePersist();
  });
  el('clearInk').addEventListener('click', () => {
    el('checkWork').disabled = !state.visualPlan && state.strokes.length === 0;
    debouncePersist();
  });
  el('clearChat').addEventListener('click', () => {
    setTimeout(() => {
      localStorage.removeItem(WORKSPACE_KEY);
      state.practice = null;
      el('practicePanel').classList.add('hidden');
    }, 0);
  });
  window.addEventListener('beforeunload', saveWorkspace);

  el('teachVisual').disabled = true;
  el('editVisual').disabled = true;
  el('checkWork').disabled = true;
  setTimeout(restoreWorkspace, 80);
})();
