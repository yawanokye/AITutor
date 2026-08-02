# v2.0 Visual Whiteboard Upgrade

## Implemented visual formats

1. **Step board**
   - one step per page,
   - explanatory text,
   - mathematical equations,
   - previous and next controls.

2. **Graph board**
   - labelled axes,
   - grid lines,
   - multiple numeric series,
   - point labels and legends.

3. **Table board**
   - comparison and calculation tables,
   - responsive horizontal scrolling on small screens.

4. **Labelled diagrams**
   - boxes, circles and pill-shaped nodes,
   - labelled directional links,
   - process, cycle and concept-map layouts.

5. **Image annotations**
   - numbered boxes over an uploaded image,
   - matching annotation key,
   - fine-detail image input setting.

6. **Lesson slides**
   - slide title,
   - concise learning points,
   - equation area,
   - speaker note,
   - slide navigation.

## Live board tools

- Pointer
- Pen
- Highlighter
- Eraser
- Colour selector
- Undo and redo
- Clear ink
- Full-screen display
- PNG export
- Attach board to the next question

## Files changed from v1.2

```text
app/config.py
app/main.py
app/prompts.py
app/schemas.py
app/static/index.html
app/static/styles.css
app/static/app.js
tests/test_app.py
render.yaml
.env.example
README.md
```

## Render deployment

No new Render service is required. Replace the files in the existing GitHub repository and redeploy the current `anovlad-ai-tutor` service.
