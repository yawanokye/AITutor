(() => {
  'use strict';

  const canvas = document.getElementById('practiceDrawingCanvas');
  const wrap = document.getElementById('practiceWhiteboardWrap');
  const shell = document.getElementById('practiceCanvasShell') || canvas?.parentElement;
  if (!canvas || !wrap || !shell) return;
  const ctx = canvas.getContext('2d');
  const state = {
    tool: 'pen', strokes: [], current: null,
    width: 1, height: 900, minHeight: 900, maxHeight: 5000,
  };
  const $ = id => document.getElementById(id);

  function configureCanvas(nextWidth = null, nextHeight = null) {
    const rect = shell.getBoundingClientRect();
    const cssWidth = Math.max(320, nextWidth || rect.width || state.width || 800);
    const cssHeight = Math.max(state.minHeight, Math.min(state.maxHeight, nextHeight || state.height));
    const previousWidth = state.width > 1 ? state.width : cssWidth;
    if (Math.abs(cssWidth - previousWidth) > 1 && state.strokes.length) {
      const scaleX = cssWidth / previousWidth;
      state.strokes.forEach(stroke => stroke.points.forEach(point => { point.x *= scaleX; }));
      if (state.current) state.current.points.forEach(point => { point.x *= scaleX; });
    }
    state.width = cssWidth;
    state.height = cssHeight;
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(cssWidth * ratio);
    canvas.height = Math.round(cssHeight * ratio);
    canvas.style.width = `${cssWidth}px`;
    canvas.style.height = `${cssHeight}px`;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    redraw();
  }

  function resize() { configureCanvas(); }

  function grow(amount = 650, scroll = true) {
    const previous = state.height;
    const next = Math.min(state.maxHeight, state.height + amount);
    if (next === previous) return false;
    configureCanvas(state.width, next);
    if (scroll) requestAnimationFrame(() => shell.scrollTo({ top: shell.scrollHeight, behavior: 'smooth' }));
    $('practiceAddSpace').disabled = next >= state.maxHeight;
    return true;
  }

  function drawStroke(stroke, target = ctx) {
    if (!stroke?.points?.length) return;
    target.save();
    target.lineCap = 'round';
    target.lineJoin = 'round';
    target.lineWidth = stroke.tool === 'eraser' ? 26 : 3.5;
    if (stroke.tool === 'eraser') {
      target.globalCompositeOperation = 'destination-out';
      target.strokeStyle = '#000';
    } else {
      target.globalCompositeOperation = 'source-over';
      target.strokeStyle = stroke.colour || '#0b5d4b';
    }
    target.beginPath();
    stroke.points.forEach((point, index) => {
      if (index === 0) target.moveTo(point.x, point.y); else target.lineTo(point.x, point.y);
    });
    if (stroke.points.length === 1) {
      const point = stroke.points[0];
      target.lineTo(point.x + 0.1, point.y + 0.1);
    }
    target.stroke();
    target.restore();
  }

  function redraw() {
    ctx.clearRect(0, 0, state.width, state.height);
    [...state.strokes, ...(state.current ? [state.current] : [])].forEach(stroke => drawStroke(stroke));
    $('practiceUndo').disabled = !state.strokes.length;
  }

  function point(event) {
    const rect = canvas.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(state.width, event.clientX - rect.left)),
      y: Math.max(0, Math.min(state.height, event.clientY - rect.top)),
    };
  }

  function ensureWritingSpace(pointValue) {
    if (pointValue.y > state.height - 110 && state.height < state.maxHeight) grow(650, false);
  }

  function pointerDown(event) {
    event.preventDefault();
    canvas.setPointerCapture(event.pointerId);
    const start = point(event);
    ensureWritingSpace(start);
    state.current = {
      tool: state.tool,
      colour: $('practicePenColour')?.value || '#0b5d4b',
      points: [start],
    };
    redraw();
  }
  function pointerMove(event) {
    if (!state.current) return;
    event.preventDefault();
    const next = point(event);
    ensureWritingSpace(next);
    state.current.points.push(next);
    redraw();
  }
  function pointerUp(event) {
    if (!state.current) return;
    event.preventDefault();
    state.current.points.push(point(event));
    state.strokes.push(state.current);
    state.current = null;
    redraw();
  }

  function setTool(tool) {
    state.tool = tool;
    $('practicePen')?.classList.toggle('active', tool === 'pen');
    $('practiceEraser')?.classList.toggle('active', tool === 'eraser');
    canvas.style.cursor = tool === 'eraser' ? 'cell' : 'crosshair';
  }

  function reset() {
    state.strokes = [];
    state.current = null;
    state.height = state.minHeight;
    configureCanvas(state.width, state.height);
    shell.scrollTop = 0;
    $('practiceAddSpace').disabled = false;
  }

  function show(required = false, message = '') {
    wrap.classList.remove('hidden');
    $('practiceWhiteboardBadge').textContent = required ? 'Required' : 'Available';
    $('practiceWhiteboardBadge').classList.toggle('required-badge', required);
    $('practiceWhiteboardRequirement').textContent = message || (required
      ? 'Your lecturer requires a handwritten response for this practice question.'
      : 'Use a mouse, stylus or finger. More writing space is added as you reach the bottom.');
    requestAnimationFrame(resize);
  }

  function hide() { wrap.classList.add('hidden'); }
  function hasInk() { return state.strokes.length > 0; }

  async function toBlob() {
    if (!hasInk()) return null;
    const output = document.createElement('canvas');
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    output.width = Math.round(state.width * ratio);
    output.height = Math.round(state.height * ratio);
    const out = output.getContext('2d');
    out.scale(ratio, ratio);
    out.fillStyle = '#ffffff';
    out.fillRect(0, 0, state.width, state.height);
    state.strokes.forEach(stroke => drawStroke(stroke, out));
    return new Promise(resolve => output.toBlob(resolve, 'image/png', 0.92));
  }

  async function toggleFullscreen() {
    try {
      if (document.fullscreenElement === wrap) await document.exitFullscreen();
      else await wrap.requestFullscreen();
    } catch {
      wrap.classList.toggle('practice-board-expanded');
    }
    requestAnimationFrame(resize);
  }

  canvas.addEventListener('pointerdown', pointerDown);
  canvas.addEventListener('pointermove', pointerMove);
  canvas.addEventListener('pointerup', pointerUp);
  canvas.addEventListener('pointercancel', pointerUp);
  $('practicePen')?.addEventListener('click', () => setTool('pen'));
  $('practiceEraser')?.addEventListener('click', () => setTool('eraser'));
  $('practiceUndo')?.addEventListener('click', () => { state.strokes.pop(); redraw(); });
  $('practiceClear')?.addEventListener('click', reset);
  $('practiceAddSpace')?.addEventListener('click', () => grow());
  $('practiceFullscreen')?.addEventListener('click', toggleFullscreen);
  document.addEventListener('fullscreenchange', () => {
    wrap.classList.toggle('is-fullscreen', document.fullscreenElement === wrap);
    requestAnimationFrame(resize);
  });
  window.addEventListener('resize', () => { if (!wrap.classList.contains('hidden')) resize(); });

  window.aiTutorPracticeBoard = { show, hide, reset, hasInk, toBlob, resize, setTool, grow, toggleFullscreen };
})();
