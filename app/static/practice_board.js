(() => {
  'use strict';

  const canvas = document.getElementById('practiceDrawingCanvas');
  const wrap = document.getElementById('practiceWhiteboardWrap');
  if (!canvas || !wrap) return;
  const ctx = canvas.getContext('2d');
  const state = { tool: 'pen', strokes: [], current: null, width: 1, height: 1 };
  const $ = id => document.getElementById(id);

  function resize() {
    const shell = canvas.parentElement;
    const rect = shell.getBoundingClientRect();
    if (!rect.width) return;
    const cssWidth = rect.width;
    const cssHeight = Math.max(260, Math.min(430, window.innerHeight * 0.42));
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    state.width = cssWidth;
    state.height = cssHeight;
    canvas.width = Math.round(cssWidth * ratio);
    canvas.height = Math.round(cssHeight * ratio);
    canvas.style.width = `${cssWidth}px`;
    canvas.style.height = `${cssHeight}px`;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    redraw();
  }

  function drawStroke(stroke) {
    if (!stroke?.points?.length) return;
    ctx.save();
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.lineWidth = stroke.tool === 'eraser' ? 24 : 3.5;
    if (stroke.tool === 'eraser') {
      ctx.globalCompositeOperation = 'destination-out';
      ctx.strokeStyle = '#000';
    } else {
      ctx.globalCompositeOperation = 'source-over';
      ctx.strokeStyle = stroke.colour || '#0b5d4b';
    }
    ctx.beginPath();
    stroke.points.forEach((point, index) => {
      const x = point.x * state.width;
      const y = point.y * state.height;
      if (index === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    if (stroke.points.length === 1) {
      const point = stroke.points[0];
      ctx.lineTo(point.x * state.width + 0.1, point.y * state.height + 0.1);
    }
    ctx.stroke();
    ctx.restore();
  }

  function redraw() {
    ctx.clearRect(0, 0, state.width, state.height);
    [...state.strokes, ...(state.current ? [state.current] : [])].forEach(drawStroke);
    $('practiceUndo').disabled = !state.strokes.length;
  }

  function point(event) {
    const rect = canvas.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
      y: Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)),
    };
  }

  function pointerDown(event) {
    event.preventDefault();
    canvas.setPointerCapture(event.pointerId);
    state.current = {
      tool: state.tool,
      colour: $('practicePenColour')?.value || '#0b5d4b',
      points: [point(event)],
    };
    redraw();
  }
  function pointerMove(event) {
    if (!state.current) return;
    event.preventDefault();
    state.current.points.push(point(event));
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
    redraw();
  }

  function show(required = false) {
    wrap.classList.remove('hidden');
    $('practiceWhiteboardBadge').textContent = required ? 'Required' : 'Optional';
    $('practiceWhiteboardBadge').classList.toggle('required-badge', required);
    $('practiceWhiteboardRequirement').textContent = required
      ? 'Your lecturer requires handwritten working for this practice question.'
      : 'Use a mouse, stylus or finger to add handwritten working when it helps.';
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
    state.strokes.forEach(stroke => {
      out.save();
      out.lineCap = 'round';
      out.lineJoin = 'round';
      out.lineWidth = stroke.tool === 'eraser' ? 24 : 3.5;
      if (stroke.tool === 'eraser') {
        out.globalCompositeOperation = 'destination-out';
        out.strokeStyle = '#000';
      } else {
        out.globalCompositeOperation = 'source-over';
        out.strokeStyle = stroke.colour || '#0b5d4b';
      }
      out.beginPath();
      stroke.points.forEach((p, index) => {
        const x = p.x * state.width;
        const y = p.y * state.height;
        if (index === 0) out.moveTo(x, y); else out.lineTo(x, y);
      });
      out.stroke();
      out.restore();
    });
    return new Promise(resolve => output.toBlob(resolve, 'image/png', 0.92));
  }

  canvas.addEventListener('pointerdown', pointerDown);
  canvas.addEventListener('pointermove', pointerMove);
  canvas.addEventListener('pointerup', pointerUp);
  canvas.addEventListener('pointercancel', pointerUp);
  $('practicePen')?.addEventListener('click', () => setTool('pen'));
  $('practiceEraser')?.addEventListener('click', () => setTool('eraser'));
  $('practiceUndo')?.addEventListener('click', () => { state.strokes.pop(); redraw(); });
  $('practiceClear')?.addEventListener('click', reset);
  window.addEventListener('resize', () => { if (!wrap.classList.contains('hidden')) resize(); });

  window.aiTutorPracticeBoard = { show, hide, reset, hasInk, toBlob, resize, setTool };
})();
