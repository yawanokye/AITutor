(() => {
  'use strict';

  const canvas = document.getElementById('practiceDrawingCanvas');
  const wrap = document.getElementById('practiceWhiteboardWrap');
  const shell = document.getElementById('practiceCanvasShell') || canvas?.parentElement;
  if (!canvas || !wrap || !shell) return;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
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

  function drawStroke(stroke, target = ctx, offsetX = 0, offsetY = 0, scale = 1) {
    if (!stroke?.points?.length) return;
    target.save();
    target.lineCap = 'round';
    target.lineJoin = 'round';
    target.lineWidth = (stroke.tool === 'eraser' ? 26 : 3.5) * scale;
    if (stroke.tool === 'eraser') {
      target.globalCompositeOperation = 'destination-out';
      target.strokeStyle = '#000';
    } else {
      target.globalCompositeOperation = 'source-over';
      target.strokeStyle = stroke.colour || '#0b5d4b';
    }
    target.beginPath();
    stroke.points.forEach((point, index) => {
      const x = (point.x - offsetX) * scale;
      const y = (point.y - offsetY) * scale;
      if (index === 0) target.moveTo(x, y); else target.lineTo(x, y);
    });
    if (stroke.points.length === 1) {
      const point = stroke.points[0];
      target.lineTo((point.x - offsetX) * scale + 0.1, (point.y - offsetY) * scale + 0.1);
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

  function commitCurrent(finalPoint = null) {
    if (!state.current) return false;
    if (finalPoint) state.current.points.push(finalPoint);
    if (state.current.points.length) state.strokes.push(state.current);
    state.current = null;
    redraw();
    return true;
  }

  function pointerDown(event) {
    event.preventDefault();
    canvas.setPointerCapture?.(event.pointerId);
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
    commitCurrent(point(event));
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
    updateCaptureStatus('');
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
  function penStrokes() { return state.strokes.filter(stroke => stroke.tool !== 'eraser' && stroke.points?.length); }
  function hasInk() { return penStrokes().length > 0 || (state.current?.tool !== 'eraser' && state.current?.points?.length > 0); }

  function inkBounds() {
    const points = penStrokes().flatMap(stroke => stroke.points || []);
    if (state.current?.tool !== 'eraser') points.push(...(state.current?.points || []));
    if (!points.length) return null;
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    points.forEach(({ x, y }) => {
      minX = Math.min(minX, x); minY = Math.min(minY, y);
      maxX = Math.max(maxX, x); maxY = Math.max(maxY, y);
    });
    const margin = 55;
    return {
      x: Math.max(0, minX - margin),
      y: Math.max(0, minY - margin),
      width: Math.max(120, Math.min(state.width, maxX + margin) - Math.max(0, minX - margin)),
      height: Math.max(120, Math.min(state.height, maxY + margin) - Math.max(0, minY - margin)),
    };
  }

  function inkCoverage(output, context) {
    try {
      const { width, height } = output;
      const data = context.getImageData(0, 0, width, height).data;
      const step = Math.max(1, Math.floor(Math.sqrt((width * height) / 250000)));
      let sampled = 0;
      let ink = 0;
      for (let y = 0; y < height; y += step) {
        for (let x = 0; x < width; x += step) {
          const index = (y * width + x) * 4;
          sampled += 1;
          const r = data[index], g = data[index + 1], b = data[index + 2], a = data[index + 3];
          if (a > 20 && (r < 242 || g < 242 || b < 242)) ink += 1;
        }
      }
      return sampled ? ink / sampled : 0;
    } catch {
      return 0.001;
    }
  }

  function updateCaptureStatus(message) {
    const node = $('practiceCaptureStatus');
    if (!node) return;
    node.textContent = message;
    node.classList.toggle('hidden', !message);
  }

  async function capture() {
    commitCurrent();
    const bounds = inkBounds();
    if (!bounds) return null;

    const targetWidth = Math.max(900, Math.min(1800, Math.round(bounds.width * 2)));
    const scale = targetWidth / bounds.width;
    const targetHeight = Math.max(280, Math.min(2400, Math.round(bounds.height * scale)));
    const effectiveScale = Math.min(scale, targetHeight / bounds.height);
    const output = document.createElement('canvas');
    output.width = Math.max(320, Math.round(bounds.width * effectiveScale));
    output.height = Math.max(220, Math.round(bounds.height * effectiveScale));
    const out = output.getContext('2d', { willReadFrequently: true });
    out.fillStyle = '#ffffff';
    out.fillRect(0, 0, output.width, output.height);
    state.strokes.forEach(stroke => drawStroke(stroke, out, bounds.x, bounds.y, effectiveScale));
    const coverage = inkCoverage(output, out);
    if (coverage < 0.00008) return null;
    const blob = await new Promise(resolve => output.toBlob(resolve, 'image/png', 0.96));
    if (!blob || blob.size < 800) return null;
    const metadata = {
      blob,
      strokeCount: penStrokes().length,
      width: output.width,
      height: output.height,
      coverage,
      bounds,
    };
    updateCaptureStatus(`Handwriting captured: ${metadata.strokeCount} stroke${metadata.strokeCount === 1 ? '' : 's'}.`);
    return metadata;
  }

  async function toBlob() {
    const result = await capture();
    return result?.blob || null;
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
  canvas.addEventListener('lostpointercapture', () => commitCurrent());
  $('practicePen')?.addEventListener('click', () => setTool('pen'));
  $('practiceEraser')?.addEventListener('click', () => setTool('eraser'));
  $('practiceUndo')?.addEventListener('click', () => { commitCurrent(); state.strokes.pop(); redraw(); updateCaptureStatus(''); });
  $('practiceClear')?.addEventListener('click', reset);
  $('practiceAddSpace')?.addEventListener('click', () => grow());
  $('practiceFullscreen')?.addEventListener('click', toggleFullscreen);
  document.addEventListener('fullscreenchange', () => {
    wrap.classList.toggle('is-fullscreen', document.fullscreenElement === wrap);
    requestAnimationFrame(resize);
  });
  window.addEventListener('resize', () => { if (!wrap.classList.contains('hidden')) resize(); });

  window.aiTutorPracticeBoard = {
    show, hide, reset, hasInk, toBlob, capture, resize, setTool, grow, toggleFullscreen,
    strokeCount: () => penStrokes().length,
  };
})();
