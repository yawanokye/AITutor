(() => {
  'use strict';

  const COURSE_MEMORY_KEY = 'anovladAiTutorCourseMemoriesV5_5';
  let restoringWorkspace = false;
  let persistTimer = null;
  let diagramDrag = null;
  let practiceRecorder = null;
  let practiceStream = null;
  let practiceAudioChunks = [];
  let practiceAudioBlob = null;
  let practiceAudioUrl = '';
  let practiceRecordingRunId = 0;
  let pendingCourseMemory = null;
  let initialCourseMemoryRestore = true;

  Object.assign(state, {
    practice: null,
    teachingActive: false,
    teachingPaused: false,
    teachingRunId: 0,
    teachingAbortController: null,
    currentCourseMemoryKey: localStorage.getItem('aiTutorSelectedClass') || 'independent',
    currentCourseMemoryName: 'Independent learning',
  });

  function readCourseMemories() {
    try {
      const parsed = JSON.parse(localStorage.getItem(COURSE_MEMORY_KEY) || '{}');
      return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
    } catch {
      return {};
    }
  }

  function writeCourseMemories(memories) {
    try { localStorage.setItem(COURSE_MEMORY_KEY, JSON.stringify(memories)); }
    catch (error) { console.warn('Course chat memories could not be saved', error); }
  }

  function debouncePersist() {
    if (restoringWorkspace) return;
    clearTimeout(persistTimer);
    persistTimer = setTimeout(saveWorkspace, 250);
  }

  function currentCourseName() {
    const selected = el('classSelect')?.selectedOptions?.[0]?.textContent?.trim();
    return selected && !/independent learning|select an enrolled course/i.test(selected)
      ? selected
      : el('course')?.value?.trim() || 'Independent learning';
  }

  function workspacePayload() {
    const visual = state.visualPlan?.kind === 'image_annotation' ? null : state.visualPlan;
    return {
      version: '5.5.0',
      courseKey: state.currentCourseMemoryKey,
      courseName: state.currentCourseMemoryName || currentCourseName(),
      sessionId: state.sessionId,
      chatLog: state.chatLog.slice(-60),
      lastAnswer: state.lastAnswer,
      activeLessonContext: state.activeLessonContext || null,
      visualPlan: visual,
      visualIndex: state.visualIndex,
      strokes: state.strokes.slice(-250),
      settings: {
        outcomeSelect: el('outcomeSelect')?.value || '',
        weekSelect: el('weekSelect')?.value || '',
        deliveryMode: el('deliveryMode')?.value || 'standard',
        level: el('level').value,
        tutorMode: el('tutorMode').value,
        visualPreference: el('visualPreference').value,
        visualRequested: el('visualRequested').checked,
        autoSpeak: el('autoSpeak').checked,
        voice: el('voice').value,
      },
      savedAt: new Date().toISOString(),
    };
  }

  function saveWorkspace() {
    if (restoringWorkspace || !state.currentCourseMemoryKey) return;
    const memories = readCourseMemories();
    memories[state.currentCourseMemoryKey] = workspacePayload();
    writeCourseMemories(memories);
    localStorage.setItem('aiTutorSessionId', state.sessionId);
  }

  function restoreSetting(id, value) {
    const control = el(id);
    if (!control || value === undefined || value === null) return;
    if (control.type === 'checkbox') control.checked = Boolean(value);
    else if ([...control.options || []].some(option => option.value === value)) control.value = value;
    else if (!control.options) control.value = value;
  }

  function clearWorkspaceDisplay(sessionId = crypto.randomUUID()) {
    restoringWorkspace = true;
    state.sessionId = sessionId;
    localStorage.setItem('aiTutorSessionId', state.sessionId);
    state.chatLog = [];
    state.lastAnswer = '';
    state.activeLessonContext = null;
    state.visualPlan = null;
    state.visualIndex = 0;
    state.strokes = [];
    state.redoStrokes = [];
    [...messages.querySelectorAll('.message:not(.welcome-message)')].forEach(node => node.remove());
    el('replayButton').disabled = true;
    question.value = '';
    clearImage();
    removeBoardAttachment();
    resetVisualBoard();
    el('practicePanel')?.classList.add('hidden');
    state.practice = null;
    restoringWorkspace = false;
  }

  function restoreWorkspacePayload(saved) {
    if (!saved) return;
    try {
      restoringWorkspace = true;
      state.sessionId = saved.sessionId || state.sessionId;
      localStorage.setItem('aiTutorSessionId', state.sessionId);
      state.chatLog = [];
      [...messages.querySelectorAll('.message:not(.welcome-message)')].forEach(node => node.remove());
      (saved.chatLog || []).forEach(item => addMessage(item.role, item.text, item.sources || []));
      state.lastAnswer = saved.lastAnswer || '';
      state.activeLessonContext = saved.activeLessonContext || null;
      el('replayButton').disabled = !state.lastAnswer;
      const settings = saved.settings || {};
      restoreSetting('outcomeSelect', settings.outcomeSelect);
      restoreSetting('weekSelect', settings.weekSelect);
      restoreSetting('deliveryMode', settings.deliveryMode);
      window.aiTutorApplyDeliveryMode?.(settings.deliveryMode || 'standard');
      restoreSetting('level', settings.level);
      restoreSetting('tutorMode', settings.tutorMode);
      restoreSetting('visualPreference', settings.visualPreference);
      restoreSetting('visualRequested', settings.visualRequested);
      restoreSetting('autoSpeak', settings.autoSpeak);
      restoreSetting('voice', settings.voice);
      if (saved.visualPlan) {
        renderVisual(saved.visualPlan, null);
        state.visualIndex = Math.max(0, Number(saved.visualIndex) || 0);
        renderCurrentVisual();
        state.strokes = Array.isArray(saved.strokes) ? saved.strokes : [];
        requestAnimationFrame(redrawStrokes);
      }
      if ((saved.chatLog || []).length) setStatus(`${saved.courseName || 'Course'} conversation restored.`);
      else setStatus('Course workspace ready.');
    } catch (error) {
      console.warn('Course workspace could not be restored', error);
    } finally {
      restoringWorkspace = false;
    }
  }

  function beginCourseSwitch(nextKey, nextName = '') {
    const key = String(nextKey || 'independent');
    if (!initialCourseMemoryRestore && key === state.currentCourseMemoryKey) {
      pendingCourseMemory = null;
      return;
    }
    if (!initialCourseMemoryRestore) saveWorkspace();
    const memories = readCourseMemories();
    pendingCourseMemory = memories[key] || null;
    state.currentCourseMemoryKey = key;
    state.currentCourseMemoryName = String(nextName || pendingCourseMemory?.courseName || (key === 'independent' ? 'Independent learning' : 'Course'));
    clearWorkspaceDisplay(pendingCourseMemory?.sessionId || crypto.randomUUID());
  }

  function finishCourseSwitch() {
    if (pendingCourseMemory) restoreWorkspacePayload(pendingCourseMemory);
    else setStatus('A separate course conversation is ready.');
    pendingCourseMemory = null;
    initialCourseMemoryRestore = false;
    renderMemoryManager();
  }

  async function deleteServerSession(sessionId) {
    if (!sessionId) return;
    try { await fetch(`/api/session/${encodeURIComponent(sessionId)}`, { method: 'DELETE', cache: 'no-store' }); }
    catch (error) { console.warn('Server course memory could not be cleared', error); }
  }

  async function clearCurrentCourseMemory({ askConfirmation = true } = {}) {
    const name = currentCourseName();
    if (askConfirmation && !confirm(`Clear the tutor conversation memory for ${name}? Assessment scores, mastery, notes and enrolment will remain.`)) return;
    const oldSession = state.sessionId;
    const memories = readCourseMemories();
    delete memories[state.currentCourseMemoryKey];
    writeCourseMemories(memories);
    await deleteServerSession(oldSession);
    clearWorkspaceDisplay(crypto.randomUUID());
    setStatus(`A fresh conversation has started for ${name}.`);
    renderMemoryManager();
  }

  async function clearAllCourseMemories() {
    if (!confirm('Clear tutor conversation memory for every course? Assessment scores, mastery, notes and enrolments will remain.')) return;
    const memories = readCourseMemories();
    await Promise.all(Object.values(memories).map(memory => deleteServerSession(memory?.sessionId)));
    localStorage.removeItem(COURSE_MEMORY_KEY);
    clearWorkspaceDisplay(crypto.randomUUID());
    setStatus('All course chat memories have been cleared.');
    renderMemoryManager();
  }

  function courseNameForMemory(key, memory) {
    const classroom = window.aiTutorPortalState?.classes?.find(item => item.id === key);
    return classroom ? `${classroom.name}${classroom.subject ? ` • ${classroom.subject}` : ''}` : memory?.courseName || (key === 'independent' ? 'Independent learning' : 'Course');
  }

  function renderMemoryManager() {
    const dialog = el('learningMemoryDialog');
    if (!dialog) return;
    const memories = readCourseMemories();
    const current = memories[state.currentCourseMemoryKey];
    el('memoryCurrentCourse').innerHTML = `<strong>Current course: ${escapeHtml(currentCourseName())}</strong><br><span>${current?.chatLog?.length || state.chatLog.length || 0} saved message(s) in this course conversation.</span>`;
    const keys = new Set([
      ...Object.keys(memories),
      ...(window.aiTutorPortalState?.classes || []).map(item => item.id),
    ]);
    el('memoryCourseList').innerHTML = [...keys].map(key => {
      const memory = memories[key];
      const count = memory?.chatLog?.length || 0;
      const saved = memory?.savedAt ? new Date(memory.savedAt).toLocaleString() : 'No conversation saved';
      return `<article class="memory-course-item"><div><strong>${escapeHtml(courseNameForMemory(key, memory))}</strong><small>${count} message(s) • ${escapeHtml(saved)}</small></div><span class="role-badge">${key === state.currentCourseMemoryKey ? 'current' : (count ? 'saved' : 'empty')}</span></article>`;
    }).join('') || '<p class="small-note">No course conversations have been saved yet.</p>';
  }

  function openMemoryManager() {
    saveWorkspace();
    renderMemoryManager();
    el('learningMemoryDialog')?.showModal();
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

  function narrationSentences(text) {
    const clean = String(text || '').replace(/\s+/g, ' ').trim();
    if (!clean) return [];
    return (clean.match(/[^.!?]+(?:[.!?]+|$)/g) || [clean]).map(item => item.trim()).filter(Boolean);
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

  function normalisedLectureText(text) {
    return String(text || '').replace(/\s+/g, ' ').trim();
  }

  function lectureSentenceGroups(text, maxWords = 42) {
    const sentences = narrationSentences(text);
    const groups = [];
    let current = [];
    let words = 0;
    sentences.forEach((sentence, sentenceIndex) => {
      const count = sentence.split(/\s+/).filter(Boolean).length;
      if (current.length && words + count > maxWords) {
        groups.push(current);
        current = [];
        words = 0;
      }
      current.push({ sentence, sentenceIndex });
      words += count;
    });
    if (current.length) groups.push(current);
    return groups;
  }

  function slideDetailedTexts(slide) {
    const explanation = normalisedLectureText(slide?.explanation);
    const speakerNote = normalisedLectureText(slide?.speaker_note);
    if (!speakerNote) return [{ key: 'explanation', text: explanation }].filter(item => item.text);
    if (!explanation) return [{ key: 'speaker-note', text: speakerNote }];
    const a = explanation.toLowerCase();
    const b = speakerNote.toLowerCase();
    if (a.includes(b)) return [{ key: 'explanation', text: explanation }];
    if (b.includes(a)) return [{ key: 'speaker-note', text: speakerNote }];
    return [
      { key: 'explanation', text: explanation },
      { key: 'speaker-note', text: speakerNote },
    ];
  }

  function naturalList(items) {
    const clean = (items || []).map(normalisedLectureText).filter(Boolean);
    if (!clean.length) return '';
    if (clean.length === 1) return clean[0];
    if (clean.length === 2) return `${clean[0]}, and ${clean[1]}`;
    return `${clean.slice(0, -1).join(', ')}, and ${clean.at(-1)}`;
  }

  function visualTeachingBeats(plan, index, includeIntro = false) {
    const beats = [];
    const push = (text, selector = '', cue = '', pauseWeight = 0.25) => {
      const clean = normalisedLectureText(text);
      if (clean) beats.push({ text: clean, selector, cue, pauseWeight });
    };

    if (includeIntro) {
      push(
        `Welcome to this guided explanation of ${plan.title || 'the topic'}. ${plan.caption || ''}`,
        '',
        '',
        0.55,
      );
    }

    if (plan.kind === 'steps') {
      const step = plan.steps?.[index] || {};
      push(`Let us work through step ${index + 1}, ${step.title || 'the next stage'}.`, '[data-teach-section-block="title"]', '', 0.35);
      lectureSentenceGroups(step.narration || step.explanation, 1).forEach(group => {
        const first = group[0]?.sentenceIndex ?? 0;
        push(
          group.map(item => item.sentence).join(' '),
          `[data-teach-section="explanation"][data-teach-sentence="${first}"]`,
          '',
          0.25,
        );
      });
      if (step.equation) {
        push('Now focus on the expression shown on the board. Notice what each symbol represents and how it connects to the step we have just discussed.', '[data-teach-section-block="equation"]', 'equation', 0.45);
      }
      if (step.learner_prompt) {
        push(`Before we continue, think about this. ${step.learner_prompt}`, '[data-teach-section-block="learner-prompt"]', 'learner-prompt', 0.9);
      }
      return beats;
    }

    if (plan.kind === 'slides') {
      const slide = plan.slides?.[index] || {};
      push(`Let us now consider ${slide.title || `section ${index + 1}`}.`, '[data-teach-section-block="title"]', '', 0.35);

      (slide.bullets || []).forEach((bullet, bulletIndex) => {
        const lead = bulletIndex === 0 ? 'The first idea to keep in view is' : bulletIndex === (slide.bullets || []).length - 1 ? 'A final organising idea is' : 'Another important idea is';
        push(`${lead} ${bullet}.`, `[data-teach-section="bullet-${bulletIndex}"][data-teach-sentence="0"]`, `bullet-${bulletIndex}`, 0.18);
      });

      slideDetailedTexts(slide).forEach(block => {
        lectureSentenceGroups(block.text, 1).forEach(group => {
          const first = group[0]?.sentenceIndex ?? 0;
          push(
            group.map(item => item.sentence).join(' '),
            `[data-teach-section="${block.key}"][data-teach-sentence="${first}"]`,
            block.key === 'speaker-note' ? 'speaker-note' : '',
            0.24,
          );
        });
      });

      if (slide.equation) {
        push(
          'Now look at the equation or expression that has appeared on the slide. Read it together with the explanation, and pay attention to how each part supports the concept.',
          '[data-teach-section-block="equation"]',
          'equation',
          0.48,
        );
      }

      if (slide.worked_example) {
        push('Let us apply the idea in a worked example.', '[data-teach-section-block="worked-example"]', 'worked-example', 0.25);
        lectureSentenceGroups(slide.worked_example, 1).forEach(group => {
          const first = group[0]?.sentenceIndex ?? 0;
          push(
            group.map(item => item.sentence).join(' '),
            `[data-teach-section="worked-example"][data-teach-sentence="${first}"]`,
            'worked-example',
            0.32,
          );
        });
      }

      if ((slide.key_terms || []).length) {
        push(
          `Keep these terms in mind as you review the explanation: ${naturalList(slide.key_terms)}.`,
          '[data-teach-section-block="key-terms"]',
          'key-terms',
          0.32,
        );
      }

      if (slide.check_question) {
        push(
          `Before moving on, pause and consider this question. ${slide.check_question}`,
          '[data-teach-section-block="check-question"]',
          'check-question',
          0.9,
        );
      }
      return beats;
    }

    push(visualPlanToSpeech(plan), '', '', 0.3);
    return beats;
  }

  function chunkLectureBeats(beats, maxCharacters = 3600) {
    const chunks = [];
    let current = [];
    let length = 0;
    beats.forEach(beat => {
      const nextLength = beat.text.length + (current.length ? 1 : 0);
      if (current.length && length + nextLength > maxCharacters) {
        chunks.push(current);
        current = [];
        length = 0;
      }
      current.push(beat);
      length += beat.text.length + (current.length > 1 ? 1 : 0);
    });
    if (current.length) chunks.push(current);
    return chunks;
  }

  function prepareGuidedLectureDisplay() {
    visualContent.classList.add('guided-lecture-active');
    visualContent.classList.remove('lecture-has-cue');
    visualContent.querySelectorAll('[data-lecture-cue]').forEach(node => {
      node.classList.remove('lecture-revealed', 'lecture-current-cue');
    });
    visualContent.querySelectorAll('.teaching-sentence').forEach(node => {
      node.classList.remove('lecture-spoken');
    });
  }

  function revealTeachingCue(cue) {
    if (!cue) return;
    visualContent.classList.add('lecture-has-cue');
    visualContent.querySelectorAll(`[data-lecture-cue="${CSS.escape(cue)}"]`).forEach(node => {
      node.classList.add('lecture-revealed');
    });
  }

  function clearTeachingHighlight() {
    visualContent.querySelectorAll('.teaching-current, .teaching-section-current, .lecture-current-cue').forEach(node => {
      node.classList.remove('teaching-current', 'teaching-section-current', 'lecture-current-cue');
    });
  }

  function highlightTeachingBeat(beat) {
    clearTeachingHighlight();
    revealTeachingCue(beat?.cue || '');
    if (!beat?.selector) return;
    const node = visualContent.querySelector(beat.selector);
    if (!node) return;
    node.classList.add('teaching-current', 'lecture-spoken');
    const section = node.closest('.teaching-section');
    section?.classList.add('teaching-section-current');
    if (beat.cue) {
      visualContent.querySelectorAll(`[data-lecture-cue="${CSS.escape(beat.cue)}"]`).forEach(cueNode => cueNode.classList.add('lecture-current-cue'));
    }
    node.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' });
  }

  async function waitForTeachingResume(runId) {
    while (state.teachingPaused && state.teachingActive && runId === state.teachingRunId) {
      await new Promise(resolve => setTimeout(resolve, 120));
    }
  }

  async function pacedDelay(milliseconds, runId) {
    let remaining = milliseconds;
    while (remaining > 0 && state.teachingActive && runId === state.teachingRunId) {
      await waitForTeachingResume(runId);
      const slice = Math.min(remaining, 120);
      await new Promise(resolve => setTimeout(resolve, slice));
      remaining -= slice;
    }
  }

  function lectureBeatWeight(beat) {
    const words = beat.text.split(/\s+/).filter(Boolean).length;
    return Math.max(4, words) + Math.max(0, Number(beat.pauseWeight || 0)) * 5;
  }

  async function requestLectureAudio(text, runId) {
    if (!state.config?.openai_enabled) throw new Error('Voice output needs OPENAI_API_KEY to be configured.');
    await waitForTeachingResume(runId);
    state.teachingAbortController?.abort();
    const controller = new AbortController();
    state.teachingAbortController = controller;
    const response = await fetch('/api/speech', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text: String(text || '').slice(0, 4050),
        voice: el('voice').value,
        style: 'guided_lecture',
        speed: 0.94,
      }),
      signal: controller.signal,
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.detail || 'Voice generation failed.');
    }
    return response.blob();
  }

  async function playLectureChunk(beats, runId, sectionLabel) {
    const text = beats.map(beat => beat.text).join(' ');
    const blob = await requestLectureAudio(text, runId);
    if (runId !== state.teachingRunId || !state.teachingActive) return;
    if (state.lastAudioUrl) URL.revokeObjectURL(state.lastAudioUrl);
    state.lastAudioUrl = URL.createObjectURL(blob);
    audioPlayer.src = state.lastAudioUrl;
    audioPlayer.hidden = false;

    await new Promise((resolve, reject) => {
      let activeIndex = -1;
      let monitor = null;
      const weights = beats.map(lectureBeatWeight);
      const totalWeight = Math.max(weights.reduce((sum, value) => sum + value, 0), 1);
      const starts = [];
      let running = 0;
      weights.forEach(value => {
        starts.push(running / totalWeight);
        running += value;
      });

      const updateBeat = () => {
        const duration = Number.isFinite(audioPlayer.duration) && audioPlayer.duration > 0
          ? audioPlayer.duration
          : Math.max(text.split(/\s+/).length / 2.45, 1);
        const ratio = Math.max(0, Math.min(1, audioPlayer.currentTime / duration));
        let nextIndex = 0;
        for (let index = 0; index < starts.length; index += 1) {
          if (ratio + 0.002 >= starts[index]) nextIndex = index;
          else break;
        }
        if (nextIndex !== activeIndex) {
          activeIndex = nextIndex;
          highlightTeachingBeat(beats[activeIndex]);
          setStatus(`${sectionLabel}, explaining part ${activeIndex + 1} of ${beats.length}…`);
        }
      };

      const cleanup = () => {
        if (monitor) clearInterval(monitor);
        audioPlayer.removeEventListener('ended', finished);
        audioPlayer.removeEventListener('error', failed);
        audioPlayer.removeEventListener('loadedmetadata', updateBeat);
        audioPlayer.removeEventListener('timeupdate', updateBeat);
      };
      const finished = () => {
        beats.forEach(beat => revealTeachingCue(beat.cue));
        if (beats.length) highlightTeachingBeat(beats.at(-1));
        cleanup();
        resolve();
      };
      const failed = () => {
        cleanup();
        reject(new Error('Audio playback failed.'));
      };

      audioPlayer.addEventListener('ended', finished, { once: true });
      audioPlayer.addEventListener('error', failed, { once: true });
      audioPlayer.addEventListener('loadedmetadata', updateBeat);
      audioPlayer.addEventListener('timeupdate', updateBeat);
      monitor = setInterval(() => {
        if (runId !== state.teachingRunId || !state.teachingActive) {
          cleanup();
          resolve();
          return;
        }
        if (state.teachingPaused && !audioPlayer.paused) audioPlayer.pause();
        if (!state.teachingPaused && audioPlayer.paused && !audioPlayer.ended) audioPlayer.play().catch(() => {});
        updateBeat();
      }, 100);
      updateBeat();
      audioPlayer.play().catch(failed);
    });
  }

  async function startStepTeaching() {
    const plan = state.visualPlan;
    const count = visualPageCount(plan);
    if (!count) {
      setStatus('Create a visual explanation before starting guided teaching.');
      return;
    }
    stopStepTeaching(false);
    state.teachingActive = true;
    state.teachingPaused = false;
    const runId = ++state.teachingRunId;
    el('teachVisual').classList.add('hidden');
    el('pauseTeaching')?.classList.remove('hidden');
    el('pauseTeaching').textContent = 'Ⅱ Pause';
    el('stopTeaching').classList.remove('hidden');
    visualViewport.classList.add('teaching-mode');
    setStatus('Preparing a guided lecture from the detailed notes…');
    try {
      for (let index = state.visualIndex; index < count; index += 1) {
        if (!state.teachingActive || runId !== state.teachingRunId) break;
        state.visualIndex = index;
        clearInk(false);
        renderCurrentVisual();
        prepareGuidedLectureDisplay();
        visualContent.classList.add('teaching-focus');
        const beats = visualTeachingBeats(plan, index, index === 0);
        const chunks = chunkLectureBeats(beats);
        for (let chunkIndex = 0; chunkIndex < chunks.length; chunkIndex += 1) {
          if (!state.teachingActive || runId !== state.teachingRunId) break;
          await waitForTeachingResume(runId);
          await playLectureChunk(
            chunks[chunkIndex],
            runId,
            `Teaching section ${index + 1} of ${count}`,
          );
          await pacedDelay(chunkIndex < chunks.length - 1 ? 280 : 480, runId);
        }
        clearTeachingHighlight();
        visualContent.classList.remove('teaching-focus');
        await pacedDelay(520, runId);
      }
      if (state.teachingActive && runId === state.teachingRunId) setStatus('Guided lecture complete. You may replay any section or continue with practice.');
    } catch (error) {
      if (error.name !== 'AbortError') setStatus(error.message);
    } finally {
      if (runId === state.teachingRunId) stopStepTeaching(false);
    }
  }

  function toggleTeachingPause() {
    if (!state.teachingActive) return;
    state.teachingPaused = !state.teachingPaused;
    const button = el('pauseTeaching');
    if (state.teachingPaused) {
      audioPlayer.pause();
      button.textContent = '▶ Resume';
      setStatus('Teaching paused.');
    } else {
      if (audioPlayer.src && !audioPlayer.ended) audioPlayer.play().catch(() => {});
      button.textContent = 'Ⅱ Pause';
      setStatus('Teaching resumed.');
    }
  }

  function stopStepTeaching(updateStatus = true) {
    state.teachingActive = false;
    state.teachingPaused = false;
    state.teachingRunId += 1;
    state.teachingAbortController?.abort();
    state.teachingAbortController = null;
    audioPlayer.pause();
    clearTeachingHighlight();
    visualContent.classList.remove('teaching-focus', 'guided-lecture-active', 'lecture-has-cue');
    visualViewport.classList.remove('teaching-mode');
    el('teachVisual').classList.remove('hidden');
    el('pauseTeaching')?.classList.add('hidden');
    if (el('pauseTeaching')) el('pauseTeaching').textContent = 'Ⅱ Pause';
    el('stopTeaching').classList.add('hidden');
    if (updateStatus) setStatus('Step-by-step teaching stopped.');
  }

  function pauseForLessonQuestion() {
    const snapshot = {
      wasActive: Boolean(state.teachingActive),
      wasPaused: Boolean(state.teachingPaused),
      runId: state.teachingRunId,
      visualIndex: state.visualIndex,
      audioTime: Number(audioPlayer.currentTime || 0),
    };
    if (state.teachingActive) {
      state.teachingPaused = true;
      audioPlayer.pause();
      if (el('pauseTeaching')) el('pauseTeaching').textContent = '▶ Resume';
      setStatus('Lesson paused for your question.');
    }
    return snapshot;
  }

  function resumeAfterLessonQuestion(snapshot) {
    if (!snapshot?.wasActive) {
      setStatus('Clarification complete.');
      return;
    }
    if (!state.teachingActive || snapshot.runId !== state.teachingRunId) {
      setStatus('The previous lesson run has ended. Select Teach like a lecturer to begin again.');
      return;
    }
    state.visualIndex = snapshot.visualIndex;
    state.teachingPaused = Boolean(snapshot.wasPaused);
    if (el('pauseTeaching')) el('pauseTeaching').textContent = state.teachingPaused ? '▶ Resume' : 'Ⅱ Pause';
    if (!state.teachingPaused && audioPlayer.src && !audioPlayer.ended) {
      if (Number.isFinite(snapshot.audioTime)) audioPlayer.currentTime = snapshot.audioTime;
      audioPlayer.play().catch(() => {});
      setStatus('Lesson resumed from the exact point where you paused.');
    } else {
      setStatus('Lesson remains paused at the same point.');
    }
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

  function practiceMimeType() {
    const options = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus', 'audio/ogg'];
    return options.find(type => window.MediaRecorder?.isTypeSupported?.(type)) || '';
  }

  function practiceAudioFilename(blob) {
    const type = String(blob?.type || '').toLowerCase();
    if (type.includes('mp4') || type.includes('m4a')) return 'practice-response.m4a';
    if (type.includes('ogg')) return 'practice-response.ogg';
    if (type.includes('mpeg') || type.includes('mp3')) return 'practice-response.mp3';
    if (type.includes('wav')) return 'practice-response.wav';
    return 'practice-response.webm';
  }

  function clearPracticeRecording(stopTracks = true) {
    practiceRecordingRunId += 1;
    if (practiceRecorder?.state === 'recording') practiceRecorder.stop();
    practiceRecorder = null;
    if (stopTracks) practiceStream?.getTracks?.().forEach(track => track.stop());
    practiceStream = null;
    practiceAudioChunks = [];
    practiceAudioBlob = null;
    if (practiceAudioUrl) URL.revokeObjectURL(practiceAudioUrl);
    practiceAudioUrl = '';
    const preview = el('practiceAudioPreview');
    if (preview) { preview.pause(); preview.removeAttribute('src'); preview.load(); preview.classList.add('hidden'); }
    el('practiceClearRecording')?.classList.add('hidden');
    if (el('practiceRecordingStatus')) el('practiceRecordingStatus').textContent = 'No response recorded.';
    if (el('practiceRecordLabel')) el('practiceRecordLabel').textContent = 'Record response';
    if (el('practiceRecordIcon')) el('practiceRecordIcon').textContent = '🎙';
    el('practiceRecordResponse')?.classList.remove('recording');
  }

  async function togglePracticeRecording() {
    if (!state.practice || state.practice.selectedMode !== 'voice') return;
    if (practiceRecorder?.state === 'recording') {
      practiceRecorder.stop();
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      practiceFeedback('Voice recording is not supported in this browser. Use a current Chrome, Edge, Firefox or Safari browser.', 'error');
      return;
    }
    clearPracticeRecording();
    try {
      practiceStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = practiceMimeType();
      practiceRecorder = mimeType ? new MediaRecorder(practiceStream, { mimeType }) : new MediaRecorder(practiceStream);
      const recorder = practiceRecorder;
      const runId = ++practiceRecordingRunId;
      practiceAudioChunks = [];
      recorder.addEventListener('dataavailable', event => { if (runId === practiceRecordingRunId && event.data?.size) practiceAudioChunks.push(event.data); });
      recorder.addEventListener('stop', () => {
        if (runId !== practiceRecordingRunId) return;
        const actualType = recorder.mimeType || mimeType || 'audio/webm';
        practiceAudioBlob = new Blob(practiceAudioChunks, { type: actualType });
        practiceAudioUrl = URL.createObjectURL(practiceAudioBlob);
        const preview = el('practiceAudioPreview');
        preview.src = practiceAudioUrl;
        preview.classList.remove('hidden');
        el('practiceClearRecording').classList.remove('hidden');
        el('practiceRecordingStatus').textContent = 'Recording ready. Play it back before submitting.';
        el('practiceRecordLabel').textContent = 'Record again';
        el('practiceRecordIcon').textContent = '🎙';
        el('practiceRecordResponse').classList.remove('recording');
        practiceStream?.getTracks?.().forEach(track => track.stop());
        practiceStream = null;
      }, { once: true });
      practiceRecorder.start();
      el('practiceRecordingStatus').textContent = 'Recording… Select Stop recording when finished.';
      el('practiceRecordLabel').textContent = 'Stop recording';
      el('practiceRecordIcon').textContent = '■';
      el('practiceRecordResponse').classList.add('recording');
    } catch (error) {
      clearPracticeRecording();
      practiceFeedback(error?.name === 'NotAllowedError' ? 'Microphone permission was not granted.' : 'The microphone could not be started.', 'error');
    }
  }

  function setPracticeResponseMode(mode, fromQuestion = false) {
    if (!state.practice) return;
    const allowed = state.practice.allowedModes || ['typed', 'voice', 'whiteboard'];
    const selected = allowed.includes(mode) ? mode : allowed[0] || 'typed';
    state.practice.selectedMode = selected;
    document.querySelectorAll('[data-practice-response]').forEach(button => {
      const permitted = allowed.includes(button.dataset.practiceResponse);
      button.hidden = !permitted;
      button.disabled = !permitted;
      button.classList.toggle('active', button.dataset.practiceResponse === selected);
      button.setAttribute('aria-pressed', String(button.dataset.practiceResponse === selected));
    });
    el('practiceTypedResponse').classList.toggle('hidden', selected !== 'typed');
    el('practiceVoiceResponse').classList.toggle('hidden', selected !== 'voice');
    if (selected === 'whiteboard') {
      state.practice.useBoard = true;
      window.aiTutorPracticeBoard?.show(state.practice.requiredMode === 'whiteboard', state.practice.requiredMode === 'whiteboard'
        ? 'Your lecturer requires a handwritten response for this practice question.'
        : 'Write your response with a mouse, stylus or finger. The board grows downward as you write.');
      requestAnimationFrame(() => window.aiTutorPracticeBoard?.resize?.());
    } else {
      window.aiTutorPracticeBoard?.hide();
    }
    const required = state.practice.requiredMode !== 'student_choice';
    el('practiceResponseRequirementBadge').textContent = required
      ? `${selected.charAt(0).toUpperCase()}${selected.slice(1)} required`
      : 'Student choice';
    el('practiceResponseInstruction').textContent = required
      ? `Your lecturer has set ${selected} as the required response method.`
      : 'Choose typing, voice recording or handwriting.';
    el('practiceBoard').classList.toggle('hidden', !allowed.includes('whiteboard'));
    if (el('checkWork')) el('checkWork').title = selected === 'whiteboard' ? 'Check the handwritten practice response' : 'Check my teaching-whiteboard work';
    if (!fromQuestion && selected === 'typed') el('practiceAnswer').focus();
    if (!fromQuestion && selected === 'whiteboard') el('practiceWhiteboardWrap')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
  window.aiTutorSetPracticeResponseMode = mode => setPracticeResponseMode(mode);

  function renderPracticeQuestion(data) {
    clearPracticeRecording();
    const requiredMode = data.response_mode || window.aiTutorGetSelectedClass?.()?.practice_response_mode || 'student_choice';
    const allowedModes = Array.isArray(data.allowed_response_modes) && data.allowed_response_modes.length
      ? data.allowed_response_modes
      : (requiredMode === 'student_choice' ? ['typed', 'voice', 'whiteboard'] : [requiredMode]);
    const firstMode = requiredMode === 'student_choice' ? (allowedModes.includes('typed') ? 'typed' : allowedModes[0]) : requiredMode;
    state.practice = {
      ...(state.practice || {}),
      id: data.practice_id,
      current: data,
      hint: data.hint || '',
      pendingNext: null,
      requiredMode,
      allowedModes,
      selectedMode: firstMode,
      useBoard: firstMode === 'whiteboard',
      boardRequired: requiredMode === 'whiteboard'
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
    setPracticeResponseMode(firstMode, true);
    if (data.visual && data.visual.kind !== 'none') renderVisual(data.visual, null); else clearInk(false);
    setMobileView('chat');
    if (firstMode === 'typed') el('practiceAnswer').focus();
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
    clearPracticeRecording();
    state.practice = null;
    el('practicePanel').classList.add('hidden');
    window.aiTutorPracticeBoard?.hide();
    setStatus('Guided practice closed.');
  }

  async function capturePracticeBoard() {
    if (window.aiTutorPracticeBoard?.capture) return window.aiTutorPracticeBoard.capture();
    const blob = await (window.aiTutorPracticeBoard?.toBlob?.() || null);
    return blob ? { blob, strokeCount: Number(window.aiTutorPracticeBoard?.strokeCount?.() || 0), width: 0, height: 0, coverage: 0 } : null;
  }

  async function checkPracticeAnswer() {
    if (!state.practice) return;
    if (state.practice.pendingNext) {
      renderPracticeQuestion(state.practice.pendingNext);
      return;
    }
    const mode = state.practice.selectedMode || 'typed';
    const answer = el('practiceAnswer').value.trim();
    const practiceInk = Boolean(window.aiTutorPracticeBoard?.hasInk?.());
    if (mode === 'typed' && !answer) {
      practiceFeedback('Type your response before submitting.', 'warning');
      el('practiceAnswer').focus();
      return;
    }
    if (mode === 'voice' && !practiceAudioBlob) {
      practiceFeedback('Record your response before submitting.', 'warning');
      return;
    }
    if (mode === 'whiteboard' && !practiceInk) {
      practiceFeedback('Write your response on the practice whiteboard before submitting.', 'warning');
      window.aiTutorPracticeBoard?.show(true);
      return;
    }
    const form = new FormData();
    form.append('practice_id', state.practice.id);
    form.append('answer', mode === 'typed' ? answer : '');
    el('checkPractice').disabled = true;
    setStatus(mode === 'voice' ? 'Transcribing and checking your response…' : 'Checking your answer…', true);
    try {
      if (mode === 'voice' && practiceAudioBlob) form.append('audio_response', practiceAudioBlob, practiceAudioFilename(practiceAudioBlob));
      if (mode === 'whiteboard') {
        const capture = await capturePracticeBoard();
        if (!capture?.blob) {
          throw new Error('Your handwriting could not be captured clearly. Use a dark pen, write slightly larger, and try again.');
        }
        form.append('board_image', capture.blob, 'practice-whiteboard-cropped.png');
        form.append('board_stroke_count', String(capture.strokeCount || 0));
        form.append('board_capture_width', String(capture.width || 0));
        form.append('board_capture_height', String(capture.height || 0));
        form.append('board_ink_coverage', String(capture.coverage || 0));
      }
      const data = await apiJson('/api/practice/check', { method: 'POST', body: form });
      const partial = !data.correct && Number(data.question_score || 0) > 0;
      const tone = data.correct ? 'success' : partial ? 'info' : 'warning';
      const heading = data.correct ? 'Correct' : partial ? 'Partly correct' : 'Try again';
      const hint = data.hint ? `<p><strong>Next hint:</strong> ${escapeHtml(data.hint)}</p>` : '';
      const questionScore = Number.isFinite(Number(data.question_score)) ? `<p><strong>This response:</strong> ${Number(data.question_score)}%</p>` : '';
      practiceFeedback(`<strong>${heading}</strong>${questionScore}<p>${escapeHtml(data.feedback)}</p>${hint}`, tone);
      el('practiceScore').textContent = `Activity score ${data.total_score}%`;
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
        clearPracticeRecording();
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
    if (!state.practice || !(state.practice.allowedModes || []).includes('whiteboard')) return;
    setPracticeResponseMode('whiteboard');
    window.aiTutorPracticeBoard?.setTool?.('pen');
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
    if (state.practice && state.practice.selectedMode === 'whiteboard' && window.aiTutorPracticeBoard?.hasInk?.()) {
      setStatus('Checking the handwritten practice response…', true);
      await checkPracticeAnswer();
      return;
    }
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
  el('pauseTeaching')?.addEventListener('click', toggleTeachingPause);
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
  document.querySelectorAll('[data-practice-response]').forEach(button => button.addEventListener('click', () => setPracticeResponseMode(button.dataset.practiceResponse)));
  el('practiceRecordResponse')?.addEventListener('click', togglePracticeRecording);
  el('practiceClearRecording')?.addEventListener('click', () => clearPracticeRecording());
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
      state.practice = null;
      el('practicePanel').classList.add('hidden');
    }, 0);
  });
  window.aiTutorStopTeaching = () => stopStepTeaching(false);
  window.aiTutorPauseForLessonQuestion = pauseForLessonQuestion;
  window.aiTutorResumeAfterLessonQuestion = resumeAfterLessonQuestion;
  window.aiTutorPersistCurrentCourseMemory = saveWorkspace;
  window.aiTutorBeginCourseSwitch = beginCourseSwitch;
  window.aiTutorFinishCourseSwitch = finishCourseSwitch;
  window.aiTutorClearCurrentCourseMemory = clearCurrentCourseMemory;
  window.aiTutorOpenMemoryManager = openMemoryManager;
  window.addEventListener('beforeunload', saveWorkspace);
  el('openLearningMemory')?.addEventListener('click', openMemoryManager);
  el('clearCurrentCourseMemory')?.addEventListener('click', () => clearCurrentCourseMemory({ askConfirmation: true }));
  el('clearAllCourseMemories')?.addEventListener('click', clearAllCourseMemories);

  el('teachVisual').disabled = true;
  el('editVisual').disabled = true;
  el('checkWork').disabled = true;
})();
