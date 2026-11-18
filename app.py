"""Trace - NE111 single-page plot digitizer.

Run: python -m streamlit run app.py
All Python, HTML, CSS and JavaScript are embedded in this one submission file.
AI assistance: developed with OpenAI Codex; numerical and UI checks are documented.
"""
from __future__ import annotations
import base64
import copy
import hashlib
import json
import re
import uuid
import pandas as pd
import streamlit as st


import csv
import io
import math

from PIL import Image, ImageOps, UnidentifiedImageError


def _finite_number(value, name="Value") -> float:
    """Convert an input to a finite float, raising an understandable error."""
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a number.") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite.")
    return result


def _point(value, name="Point") -> tuple[float, float]:
    """Check a two-dimensional point."""
    try:
        if len(value) != 2:
            raise ValueError
        return (_finite_number(value[0], name), _finite_number(value[1], name))
    except (TypeError, IndexError, ValueError) as exc:
        raise ValueError(f"{name} must contain two finite coordinates.") from exc


class Calibration:
    """Map three image references to linear or base-10 logarithmic axes.

    ``origin`` represents (x0, y0), ``x_point`` represents (x1, y0), and
    ``y_point`` represents (x0, y1). For a logarithmic axis its values must be
    positive; its reference at the axes' intersection need not be zero.

    A two-dimensional affine basis handles rotated and skewed scans. Perspective
    distortion and nonlinear camera/lens distortion are outside this model.
    """

    def __init__(self, origin, x_point, y_point, x0, x1, y0, y1,
                 x_log=False, y_log=False):
        self.origin = _point(origin, "Origin")
        self.x_point = _point(x_point, "X reference")
        self.y_point = _point(y_point, "Y reference")
        self.x0 = _finite_number(x0, "X at origin")
        self.x1 = _finite_number(x1, "X at reference")
        self.y0 = _finite_number(y0, "Y at origin")
        self.y1 = _finite_number(y1, "Y at reference")
        self.x_log = bool(x_log)
        self.y_log = bool(y_log)
        if self.x0 == self.x1 or self.y0 == self.y1:
            raise ValueError("Each axis needs two different reference values.")
        if self.x_log and min(self.x0, self.x1) <= 0:
            raise ValueError("Logarithmic X reference values must be positive.")
        if self.y_log and min(self.y0, self.y1) <= 0:
            raise ValueError("Logarithmic Y reference values must be positive.")

        self._vx = (self.x_point[0] - self.origin[0],
                    self.x_point[1] - self.origin[1])
        self._vy = (self.y_point[0] - self.origin[0],
                    self.y_point[1] - self.origin[1])
        self._lx = math.hypot(*self._vx)
        self._ly = math.hypot(*self._vy)
        if (not math.isfinite(self._lx) or not math.isfinite(self._ly)
                or self._lx <= 1e-12 or self._ly <= 1e-12):
            raise ValueError("Place each axis reference away from the origin.")
        self._ex = (self._vx[0] / self._lx, self._vx[1] / self._lx)
        self._ey = (self._vy[0] / self._ly, self._vy[1] / self._ly)
        self._sine = self._ex[0] * self._ey[1] - self._ex[1] * self._ey[0]
        # A normalized determinant makes the check independent of image size.
        if abs(self._sine) < 1e-3:
            raise ValueError("The three references are nearly on one line. "
                             "Choose separate X and Y directions.")

        self._tx0 = math.log10(self.x0) if self.x_log else self.x0
        self._tx1 = math.log10(self.x1) if self.x_log else self.x1
        self._ty0 = math.log10(self.y0) if self.y_log else self.y0
        self._ty1 = math.log10(self.y1) if self.y_log else self.y1
        self._dx = self._tx1 - self._tx0
        self._dy = self._ty1 - self._ty0
        if (not math.isfinite(self._dx) or not math.isfinite(self._dy)
                or self._dx == 0 or self._dy == 0):
            raise ValueError("Reference values are too close or too large. "
                             "Choose a wider, finite axis interval.")

    def pixel_to_data(self, pixel_x, pixel_y) -> tuple[float, float]:
        """Convert original-image pixel coordinates to calibrated data values."""
        px = _finite_number(pixel_x, "Pixel X") - self.origin[0]
        py = _finite_number(pixel_y, "Pixel Y") - self.origin[1]
        u = ((px / self._lx) * self._ey[1]
             - (py / self._lx) * self._ey[0]) / self._sine
        v = (self._ex[0] * (py / self._ly)
             - self._ex[1] * (px / self._ly)) / self._sine
        tx = self._tx0 + u * self._dx
        ty = self._ty0 + v * self._dy
        try:
            x = 10.0 ** tx if self.x_log else tx
            y = 10.0 ** ty if self.y_log else ty
        except OverflowError as exc:
            raise ValueError("This point exceeds the numerical range. "
                             "Check the calibration values.") from exc
        if (not math.isfinite(x) or not math.isfinite(y)
                or (self.x_log and x <= 0) or (self.y_log and y <= 0)):
            raise ValueError("This point exceeds the numerical range. "
                             "Check the calibration values.")
        return x, y

    def data_to_pixel(self, data_x, data_y) -> tuple[float, float]:
        """Convert edited data back to image pixels so markers stay in sync."""
        x = _finite_number(data_x, "Data X")
        y = _finite_number(data_y, "Data Y")
        if self.x_log and x <= 0:
            raise ValueError("X must be positive on a logarithmic axis.")
        if self.y_log and y <= 0:
            raise ValueError("Y must be positive on a logarithmic axis.")
        tx = math.log10(x) if self.x_log else x
        ty = math.log10(y) if self.y_log else y
        u = (tx - self._tx0) / self._dx
        v = (ty - self._ty0) / self._dy
        px = self.origin[0] + u * self._vx[0] + v * self._vy[0]
        py = self.origin[1] + u * self._vx[1] + v * self._vy[1]
        if not math.isfinite(px) or not math.isfinite(py):
            raise ValueError("The edited point exceeds the numerical range.")
        return px, py


def csv_export(datasets, x_label="x", y_label="y") -> str:
    """Return the required wide CSV with two header rows and padded datasets.

    ``datasets`` is a list of ``{'name': ..., 'values': [(x, y), ...]}``.
    Each dataset occupies two columns. Its name starts the first column of the
    pair, and the second header repeats the chosen axis labels for every pair.
    Python's CSV writer quotes names containing commas, quotes, or newlines.
    """
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    header_names = []
    header_axes = []
    checked_values = []
    for dataset in datasets:
        header_names.extend([str(dataset["name"]), ""])
        header_axes.extend([str(x_label), str(y_label)])
        checked_values.append([
            (_finite_number(x, "CSV X"), _finite_number(y, "CSV Y"))
            for x, y in dataset.get("values", [])
        ])
    writer.writerow(header_names)
    writer.writerow(header_axes)
    for index in range(max((len(values) for values in checked_values), default=0)):
        row = []
        for values in checked_values:
            if index < len(values):
                # repr preserves the full floating-point value for round trips.
                row.extend([repr(values[index][0]), repr(values[index][1])])
            else:
                row.extend(["", ""])
        writer.writerow(row)
    return output.getvalue()


def load_image(raw_bytes: bytes, frame: int = 0) -> Image.Image:
    """Read PNG, JPEG, GIF or TIFF into an EXIF-corrected RGB image.

    Transparencies are composited on white. The selected GIF/TIFF frame is
    copied before its file handle closes; grayscale/palette/CMYK are supported.
    No resizing occurs, preserving original pixel coordinates.
    """
    try:
        with Image.open(io.BytesIO(raw_bytes)) as source:
            if source.format not in {"PNG", "JPEG", "GIF", "TIFF"}:
                raise ValueError("Use a PNG, JPG/JPEG, GIF or TIFF image.")
            if source.width * source.height > 30_000_000:
                raise ValueError("Use an image with at most 30 million pixels. Crop the plot or reduce its resolution.")
            count = getattr(source, "n_frames", 1)
            if not isinstance(frame, int) or not 0 <= frame < count:
                raise ValueError(f"Choose a frame from 1 to {count}.")
            source.seek(frame)
            source.load()
            image = ImageOps.exif_transpose(source.copy())
            if image.mode.startswith("I;16") or image.mode in {"I", "F"}:
                # Scientific TIFF/PNG images can store more than eight bits.
                # Direct RGB conversion would clip their gray levels at 255.
                low, high = image.getextrema()
                if math.isfinite(low) and math.isfinite(high) and high > low:
                    gain = 255.0 / (high - low)
                    image = image.convert("F").point(
                        lambda value: (value - low) * gain
                    ).convert("RGB")
                else:
                    image = image.convert("RGB")
            elif image.mode in {"RGBA", "LA", "P"}:
                rgba = image.convert("RGBA")
                background = Image.new("RGBA", rgba.size, "white")
                image = Image.alpha_composite(background, rgba).convert("RGB")
            else:
                image = image.convert("RGB")
            return image
    except (UnidentifiedImageError, OSError, EOFError) as exc:
        raise ValueError("This image could not be read. Try another image or "
                         "export it as PNG.") from exc


def frame_count(raw_bytes: bytes) -> int:
    """Return the available GIF/TIFF frames, or one for a static image."""
    try:
        with Image.open(io.BytesIO(raw_bytes)) as source:
            return getattr(source, "n_frames", 1)
    except (UnidentifiedImageError, OSError, EOFError) as exc:
        raise ValueError("This image could not be read.") from exc

CANVAS_HTML = r"""
<section class="digitizer" aria-label="Interactive plot digitizer">
  <div class="canvas-toolbar">
    <div class="canvas-tools" role="group" aria-label="Image navigation">
      <button type="button" data-action="fit" title="Fit the entire image">Fit image</button>
      <button type="button" data-action="out" aria-label="Zoom out" title="Zoom out">−</button>
      <output class="zoom-value" aria-label="Current zoom">100%</output>
      <button type="button" data-action="in" aria-label="Zoom in" title="Zoom in">+</button>
      <button type="button" data-action="native" title="Show one screen pixel per image pixel">1:1</button>
      <span class="tool-divider"></span>
      <button type="button" data-action="pan" aria-pressed="false" title="Toggle pan; dragging always pans">Pan</button>
      <button type="button" data-action="loupe" aria-pressed="true" title="Show or hide the precision magnifier">Magnifier</button>
    </div>
    <span class="canvas-readout" aria-live="off">Move over the image</span>
  </div>
  <div class="canvas-stage">
    <canvas tabindex="0" role="application" aria-label="Plot image. Click to choose a point. Drag to pan, scroll to zoom. Arrow keys move the crosshair and Enter chooses a point."></canvas>
    <div class="canvas-loading" role="status">Loading image…</div>
  </div>
  <div class="canvas-footer">
    <span class="canvas-instruction" role="status"></span>
    <span class="canvas-hint">Scroll to zoom · Drag to pan · Arrows + Enter for precision</span>
  </div>
  <div class="canvas-legend" aria-label="Dataset colors"></div>
</section>
"""

CANVAS_CSS = r"""
.digitizer { width:100%; color:var(--st-text-color,#183040); font:14px/1.4 var(--st-font,system-ui,sans-serif); border:1px solid #d6e1e5; border-radius:14px; overflow:hidden; background:var(--st-background-color,#fff); box-shadow:0 3px 12px #193d4d08; }
.canvas-toolbar { min-height:64px; padding:8px 12px; display:flex; flex-direction:column; align-items:stretch; justify-content:center; gap:5px; border-bottom:1px solid #d6e1e5; }
.canvas-tools { display:flex; gap:5px; align-items:center; flex-wrap:wrap; }
.canvas-tools button { min-height:32px; min-width:32px; padding:5px 10px; color:inherit; font:inherit; font-weight:550; border:1px solid #cbd9df; border-radius:7px; background:var(--st-background-color,#fff); cursor:pointer; }
.canvas-tools button:hover { background:#e8f5f3; color:#075e58; border-color:#6bb6ad; }
.canvas-tools button:focus-visible, canvas:focus-visible { outline:3px solid #13a89a; outline-offset:-3px; }
.canvas-tools button[aria-pressed="true"] { background:#e6f4f0; color:#075e58; border-color:#8fc7ba; }
.zoom-value { font-variant-numeric:tabular-nums; min-width:49px; text-align:center; font-size:12px; }
.tool-divider { height:20px; width:1px; background:#d6e1e5; margin:0 3px; }
.canvas-readout { display:block; height:17px; line-height:17px; white-space:nowrap; color:#627981; font-size:12px; font-variant-numeric:tabular-nums; }
.canvas-stage { position:relative; height:540px; width:100%; background:#edf2f4; overflow:hidden; }
.canvas-stage canvas { display:block; width:100%; height:100%; cursor:crosshair; touch-action:none; }
.canvas-loading { position:absolute; inset:0; display:grid; place-items:center; color:#516b77; pointer-events:none; background:#edf2f4; }
.canvas-footer { padding:11px 14px; display:flex; justify-content:space-between; gap:8px; flex-wrap:wrap; border-top:1px solid #d6e1e5; }
.canvas-instruction { font-weight:600; color:var(--st-text-color,#183040); }
.canvas-hint { font-size:12px; color:#627981; }
.canvas-legend { display:flex; gap:14px; flex-wrap:wrap; padding:0 14px 11px; }
.canvas-legend:empty { display:none; }
.legend-item { display:inline-flex; align-items:center; gap:6px; font-size:12px; }
.legend-dot { display:inline-block; width:9px; height:9px; border-radius:50%; }
@media(max-width:600px) { .canvas-stage { height:430px; } .canvas-readout { display:none; } .canvas-hint { font-size:11px; } .canvas-tools button { padding:5px 7px; } }
"""

CANVAS_JS = r"""
export default function(component) {
  const {data, parentElement, setTriggerValue, key} = component;
  const root = parentElement.querySelector('.digitizer');
  const canvas = root.querySelector('canvas');
  const ctx = canvas.getContext('2d');
  const stage = root.querySelector('.canvas-stage');
  const loading = root.querySelector('.canvas-loading');
  const zoomLabel = root.querySelector('.zoom-value');
  const readout = root.querySelector('.canvas-readout');
  const instruction = root.querySelector('.canvas-instruction');
  const panButton = root.querySelector('[data-action="pan"]');
  const loupeButton = root.querySelector('[data-action="loupe"]');
  const image = new Image();
  let disposed = false;
  let ready = false;
  let frame = null;
  let drag = null;
  let hovering = false;
  let space = false;
  const listeners = [];

  // Keep the view stable when Python reruns after a point or a table edit.
  // The map contains only small numbers; image contents never enter global state.
  const cacheName = '__ne111DigitizerViews';
  const cache = window[cacheName] || (window[cacheName] = new Map());
  const cacheKey = String(key || 'plot_canvas');
  const imageId = String(data.image_id || data.image?.slice(-100));
  const old = cache.get(cacheKey);
  const state = old && old.imageId === imageId ? old : {
    imageId, scale:1, ox:0, oy:0, width:0, height:0, manual:false,
    pan:false, loupe:true, cursor:null
  };
  cache.set(cacheKey, state);
  if (state.mode !== data.mode) state.pan = false;
  state.mode = data.mode;
  instruction.textContent = data.instruction || 'Click the image to choose a point.';
  panButton.setAttribute('aria-pressed', String(state.pan || data.mode === 'pan'));
  loupeButton.setAttribute('aria-pressed', String(state.loupe));
  const legend = root.querySelector('.canvas-legend');
  legend.replaceChildren();
  for (const dataset of data.datasets || []) {
    const item = document.createElement('span'); item.className = 'legend-item';
    const dot = document.createElement('span'); dot.className = 'legend-dot';
    dot.style.backgroundColor = dataset.color;
    item.append(dot, document.createTextNode(`${dataset.name} (${(dataset.points || []).length})`));
    legend.appendChild(item);
  }

  function listen(element, type, callback, options) {
    element.addEventListener(type, callback, options);
    listeners.push(() => element.removeEventListener(type, callback, options));
  }
  function toImage(x, y) {
    return {x:(x-state.ox)/state.scale, y:(y-state.oy)/state.scale};
  }
  function toScreen(point) {
    return {x:state.ox + point[0]*state.scale, y:state.oy + point[1]*state.scale};
  }
  function inImage(p) {
    return p && p.x >= 0 && p.y >= 0 && p.x <= image.naturalWidth-1 && p.y <= image.naturalHeight-1;
  }
  function local(event) {
    const rect = canvas.getBoundingClientRect();
    // CSS-to-canvas conversion remains correct under browser and CSS scaling.
    return {x:(event.clientX-rect.left)*state.width/rect.width,
            y:(event.clientY-rect.top)*state.height/rect.height};
  }
  function requestDraw() {
    if (frame === null && !disposed) frame = requestAnimationFrame(() => {frame=null; draw();});
  }
  function fit() {
    if (!ready || !state.width) return;
    state.scale = Math.min((state.width-36)/image.naturalWidth, (state.height-36)/image.naturalHeight);
    state.ox = (state.width-image.naturalWidth*state.scale)/2;
    state.oy = (state.height-image.naturalHeight*state.scale)/2;
    state.manual = false;
    requestDraw();
  }
  function zoom(factor, x=state.width/2, y=state.height/2) {
    if (!ready) return;
    const p = toImage(x,y);
    const fitScale = Math.min(state.width/image.naturalWidth,state.height/image.naturalHeight);
    state.scale = Math.max(Math.min(.1,fitScale/3), Math.min(40,state.scale*factor));
    state.ox = x-p.x*state.scale; state.oy = y-p.y*state.scale;
    state.manual = true; requestDraw();
  }
  function resize() {
    const rect = stage.getBoundingClientRect();
    const w = Math.max(1,Math.round(rect.width)); const h=Math.max(1,Math.round(rect.height));
    const previousWidth = state.width, previousHeight = state.height;
    if (state.manual && previousWidth && previousHeight) {
      state.ox += (w-previousWidth)/2; state.oy += (h-previousHeight)/2;
    }
    state.width=w; state.height=h;
    const dpr=Math.min(window.devicePixelRatio||1,3);
    canvas.width=Math.round(w*dpr); canvas.height=Math.round(h*dpr);
    ctx.setTransform(dpr,0,0,dpr,0,0);
    if (ready && !state.manual) fit(); else requestDraw();
  }
  function marker(x,y,color,label,radius=4) {
    ctx.beginPath(); ctx.arc(x,y,radius+1.5,0,Math.PI*2);
    ctx.fillStyle='#fff'; ctx.fill();
    ctx.beginPath(); ctx.arc(x,y,radius,0,Math.PI*2);
    ctx.fillStyle=color; ctx.fill();
    ctx.strokeStyle='#16313a'; ctx.lineWidth=.7; ctx.stroke();
    if (label) {
      ctx.font='600 12px system-ui,sans-serif';
      ctx.lineWidth=3; ctx.strokeStyle='#fff'; ctx.strokeText(label,x+8,y-8);
      ctx.fillStyle=color; ctx.fillText(label,x+8,y-8);
    }
  }
  function draw() {
    if (!ctx || disposed) return;
    ctx.clearRect(0,0,state.width,state.height);
    ctx.fillStyle='#edf2f4'; ctx.fillRect(0,0,state.width,state.height);
    if (!ready) return;
    ctx.save();
    ctx.shadowColor='#18344222'; ctx.shadowBlur=12;
    ctx.fillStyle='#fff';
    ctx.fillRect(state.ox,state.oy,image.naturalWidth*state.scale,image.naturalHeight*state.scale);
    ctx.restore();
    ctx.imageSmoothingEnabled = state.scale < 3;
    ctx.drawImage(image,state.ox,state.oy,image.naturalWidth*state.scale,image.naturalHeight*state.scale);
    for (const dataset of data.datasets || []) {
      const points=dataset.points || [];
      if (data.show_lines && points.length>1) {
        ctx.beginPath();
        points.forEach((point,i) => {const p=toScreen(point); i ? ctx.lineTo(p.x,p.y) : ctx.moveTo(p.x,p.y);});
        ctx.strokeStyle=dataset.color; ctx.lineWidth=1.4; ctx.globalAlpha=.7; ctx.stroke(); ctx.globalAlpha=1;
      }
      points.forEach((point,i) => {const p=toScreen(point); marker(p.x,p.y,dataset.color,data.show_numbers?String(i+1):'');});
    }
    const refs=data.refs || [];
    if (refs[0]) {
      for (let i=1;i<=2;i++) if (refs[i]) {
        const a=toScreen(refs[0]),b=toScreen(refs[i]);
        ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);
        ctx.strokeStyle='#c97917';ctx.lineWidth=1.5;ctx.setLineDash([6,4]);ctx.stroke();ctx.setLineDash([]);
      }
    }
    refs.forEach((point,i) => {if(point) {const p=toScreen(point);marker(p.x,p.y,'#b96712',['O','X','Y'][i],6);}});
    const cursor=state.cursor;
    if (hovering && cursor && inImage(cursor)) {
      const p=toScreen([cursor.x,cursor.y]);
      ctx.strokeStyle='#172f3b';ctx.lineWidth=1;
      ctx.beginPath();ctx.moveTo(p.x-12,p.y);ctx.lineTo(p.x-4,p.y);ctx.moveTo(p.x+4,p.y);ctx.lineTo(p.x+12,p.y);
      ctx.moveTo(p.x,p.y-12);ctx.lineTo(p.x,p.y-4);ctx.moveTo(p.x,p.y+4);ctx.lineTo(p.x,p.y+12);ctx.stroke();
      if(state.loupe && !drag) drawLoupe(cursor);
    }
    zoomLabel.textContent=`${Math.round(state.scale*100)}%`;
    canvas.style.cursor = (space || state.pan || data.mode==='pan' || drag?.moved) ? (drag?'grabbing':'grab') : 'crosshair';
  }
  function drawLoupe(p) {
    const size=116,pad=12,left=state.width-size-pad,top=pad;
    if(left<10) return;
    ctx.save();
    ctx.fillStyle='#fff';ctx.fillRect(left-4,top-4,size+8,size+28);
    ctx.strokeStyle='#b3c5cb';ctx.lineWidth=1;ctx.strokeRect(left-4,top-4,size+8,size+28);
    ctx.beginPath();ctx.rect(left,top,size,size);ctx.clip();
    ctx.fillStyle='#fff';ctx.fillRect(left,top,size,size);
    const magnification=Math.max(5,Math.min(24,state.scale*2.5));
    ctx.imageSmoothingEnabled=false;
    ctx.drawImage(image,left+size/2-p.x*magnification,top+size/2-p.y*magnification,image.naturalWidth*magnification,image.naturalHeight*magnification);
    ctx.strokeStyle='#03b8ad';ctx.lineWidth=1;
    ctx.beginPath();ctx.moveTo(left,top+size/2);ctx.lineTo(left+size,top+size/2);ctx.moveTo(left+size/2,top);ctx.lineTo(left+size/2,top+size);ctx.stroke();
    ctx.restore();
    ctx.font='11px system-ui,sans-serif';ctx.fillStyle='#415d68';ctx.fillText('PRECISION VIEW',left+8,top+size+16);
  }
  function updateCursor(p) {
    state.cursor=toImage(p.x,p.y);
    readout.textContent=inImage(state.cursor) ? `Pixel ${state.cursor.x.toFixed(1)}, ${state.cursor.y.toFixed(1)}` : 'Outside image';
    requestDraw();
  }
  function choose(p) {
    if (!ready || !inImage(p) || space || state.pan || data.mode==='pan') return;
    const token=window.crypto?.randomUUID ? window.crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
    setTriggerValue('clicked',{x:p.x,y:p.y,token,mode:data.mode,dataset_id:data.active_id ?? null});
  }
  listen(canvas,'pointerdown', event => {
    if(event.button!==0 && event.button!==1) return;
    event.preventDefault();canvas.focus({preventScroll:true});
    const p=local(event);updateCursor(p);hovering=true;
    drag={id:event.pointerId,startX:p.x,startY:p.y,ox:state.ox,oy:state.oy,moved:false,force:event.button===1 || space || state.pan || data.mode==='pan'};
    canvas.setPointerCapture(event.pointerId);
  });
  listen(canvas,'pointermove',event => {
    const p=local(event);hovering=true;
    if(drag && drag.id===event.pointerId) {
      const dx=p.x-drag.startX,dy=p.y-drag.startY;
      if(Math.hypot(dx,dy)>4) drag.moved=true;
      if(drag.moved || drag.force) {state.ox=drag.ox+dx;state.oy=drag.oy+dy;state.manual=true;}
    }
    updateCursor(p);
  });
  listen(canvas,'pointerup',event => {
    if(!drag || drag.id!==event.pointerId) return;
    const finished=drag;drag=null;
    if(canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
    const p=local(event);updateCursor(p);
    if(!finished.moved && !finished.force) choose(toImage(p.x,p.y));
    requestDraw();
  });
  listen(canvas,'pointercancel',()=>{drag=null;requestDraw();});
  listen(canvas,'pointerleave',()=>{if(!drag) hovering=false;requestDraw();});
  listen(canvas,'wheel',event=>{
    event.preventDefault();const p=local(event);
    zoom(Math.exp(Math.max(-.7,Math.min(.7,-event.deltaY*.002))),p.x,p.y);updateCursor(p);
  },{passive:false});
  listen(canvas,'keydown',event=>{
    const step=event.shiftKey ? 0.1 : 1;
    const directions={ArrowLeft:[-step,0],ArrowRight:[step,0],ArrowUp:[0,-step],ArrowDown:[0,step]};
    if(directions[event.key]) {
      event.preventDefault();hovering=true;
      if(!state.cursor || !inImage(state.cursor)) state.cursor={x:(image.naturalWidth-1)/2,y:(image.naturalHeight-1)/2};
      state.cursor.x=Math.max(0,Math.min(image.naturalWidth-1,state.cursor.x+directions[event.key][0]));
      state.cursor.y=Math.max(0,Math.min(image.naturalHeight-1,state.cursor.y+directions[event.key][1]));
      const p=toScreen([state.cursor.x,state.cursor.y]);
      if(p.x<15 || p.x>state.width-15) state.ox=state.width/2-state.cursor.x*state.scale;
      if(p.y<15 || p.y>state.height-15) state.oy=state.height/2-state.cursor.y*state.scale;
      readout.textContent=`Pixel ${state.cursor.x.toFixed(1)}, ${state.cursor.y.toFixed(1)}`;requestDraw();
    } else if(event.key==='Enter') {event.preventDefault();choose(state.cursor);}
    else if(event.code==='Space') {event.preventDefault();space=true;requestDraw();}
    else if(event.key==='+' || event.key==='=') {event.preventDefault();zoom(1.25);}
    else if(event.key==='-') {event.preventDefault();zoom(.8);}
    else if(event.key==='0') {event.preventDefault();fit();}
  });
  listen(canvas,'keyup',event=>{if(event.code==='Space'){space=false;requestDraw();}});
  listen(canvas,'blur',()=>{space=false;hovering=false;requestDraw();});
  for(const button of root.querySelectorAll('[data-action]')) {
    listen(button,'click',()=>{
      const action=button.dataset.action;
      if(action==='fit') fit();
      else if(action==='in') zoom(1.25);
      else if(action==='out') zoom(.8);
      else if(action==='native') zoom(1/state.scale);
      else if(action==='pan') {state.pan=!state.pan;button.setAttribute('aria-pressed',String(state.pan));requestDraw();}
      else if(action==='loupe') {state.loupe=!state.loupe;button.setAttribute('aria-pressed',String(state.loupe));requestDraw();}
    });
  }
  const observer=new ResizeObserver(resize);observer.observe(stage);
  image.onload=()=>{if(disposed)return;ready=true;loading.style.display='none';resize();};
  image.onerror=()=>{loading.textContent='The image could not be displayed. Please upload it again.';};
  image.src=data.image;
  resize();
  return ()=>{
    disposed=true;observer.disconnect();listeners.forEach(remove=>remove());
    if(frame!==null) cancelAnimationFrame(frame);
    image.onload=null;image.onerror=null;
  };
}
"""

@st.cache_resource
def canvas_component(html, css, js):
    version = hashlib.sha256((html + css + js).encode()).hexdigest()[:12]
    return st.components.v2.component('trace_canvas_' + version, html=html, css=css, js=js)


def render_canvas(data):
    return canvas_component(CANVAS_HTML, CANVAS_CSS, CANVAS_JS)(data=data, key='trace_canvas', on_clicked_change=lambda: None)


# ---------- Session model and interface ----------
PALETTE = ['#2563eb', '#e05228', '#159570', '#a247ba', '#c48a07', '#d43d77', '#008ba3']


def new_dataset(index=0):
    return {'id': uuid.uuid4().hex, 'name': f'Dataset {index + 1}',
            'color': PALETTE[index % len(PALETTE)], 'points': []}


def remember():
    """Keep reversible annotation edits separate from large image bytes."""
    s = st.session_state
    s.undo_stack.append(copy.deepcopy((s.datasets, s.refs)))
    s.undo_stack = s.undo_stack[-100:]
    s.redo_stack = []
    s.revision += 1


def history_action(source, target):
    s = st.session_state
    if s[source]:
        s[target].append(copy.deepcopy((s.datasets, s.refs)))
        s.datasets, s.refs = s[source].pop()
        if s.active_id not in [d['id'] for d in s.datasets]:
            s.active_id = s.datasets[0]['id']
        s.revision += 1


def replace_image(image, name, fingerprint, refs=None, logarithmic=False):
    s = st.session_state
    buf = io.BytesIO()
    image.save(buf, format='PNG')
    s.image_url = 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode('ascii')
    s.image_id, s.image_name = fingerprint, name
    s.image_size = image.size
    s.refs = refs or [None, None, None]
    s.datasets = [new_dataset()]
    s.active_id = s.datasets[0]['id']
    s.next_dataset = 1
    s.undo_stack, s.redo_stack = [], []
    s.revision += 1
    s.mode = 'collect' if refs else 'origin'
    s.x0, s.x1 = (1.0, 100.0) if logarithmic else (0.0, 10.0)
    s.y0, s.y1 = (1.0, 100.0) if logarithmic else (0.0, 10.0)
    s.x_scale = s.y_scale = 'Logarithmic' if logarithmic else 'Linear'
    s.x_label, s.y_label = 'x', 'y'
    s.last_click = None


def example_plot(kind='Linear'):
    """Generate original, reproducible examples without external image assets."""
    from PIL import ImageDraw, ImageFont
    im = Image.new('RGB', (1000, 650), '#ffffff')
    draw = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype('DejaVuSans.ttf', 19)
        title_font = ImageFont.truetype('DejaVuSans.ttf', 25)
    except OSError:
        font = ImageFont.load_default(size=19)
        title_font = ImageFont.load_default(size=25)
    rotated = kind == 'Rotated'
    origin, xp, yp = ((155, 545), (875, 430), (85, 100)) if rotated else ((115, 535), (900, 535), (115, 90))
    def at(u, v):
        return (origin[0] + u*(xp[0]-origin[0]) + v*(yp[0]-origin[0]),
                origin[1] + u*(xp[1]-origin[1]) + v*(yp[1]-origin[1]))
    draw.text((260, 22), f'{kind} plot / practice example', fill='#172d42', font=title_font)
    for i in range(11):
        u = i/10
        draw.line([at(u, 0), at(u, 1)], fill='#e3eaf1', width=1)
        draw.line([at(0, u), at(1, u)], fill='#e3eaf1', width=1)
        value = f'{10**(2*u):.2g}' if kind == 'Logarithmic' else str(i)
        p, q = at(u, 0), at(0, u)
        if i % 2 == 0:
            draw.text((p[0]-8, p[1]+12), value, font=font, fill='#526273')
            draw.text((q[0]-48, q[1]-10), value, font=font, fill='#526273')
    draw.line([yp, origin, xp], fill='#243b53', width=3)
    for color, fn in [('#2563eb', lambda u: .12+.72*u), ('#e05228', lambda u: .15+.65*u*u)]:
        samples = [at(i/10, fn(i/10)) for i in range(11)]
        draw.line(samples, fill=color, width=3)
        for x, y in samples:
            draw.ellipse((x-5, y-5, x+5, y+5), fill='white', outline=color, width=3)
    draw.text((460, 597), 'x', fill='#243b53', font=font)
    draw.text((28, 290), 'y', fill='#243b53', font=font)
    return im, [list(origin), list(xp), list(yp)]


def current_calibration():
    s = st.session_state
    if any(p is None for p in s.refs):
        return None, 'Set the three reference points to begin collecting data.'
    try:
        return Calibration(*s.refs, s.x0, s.x1, s.y0, s.y1,
                           s.x_scale == 'Logarithmic', s.y_scale == 'Logarithmic'), None
    except ValueError as error:
        return None, str(error)


def apply_table(dataset_id, editor_key, values, calibration):
    """Apply table deltas before the canvas renders on the next Streamlit run."""
    s = st.session_state
    delta = s[editor_key]
    rows = [list(p) for p in values]
    try:
        for index, changes in delta.get('edited_rows', {}).items():
            for col, value in changes.items():
                rows[int(index)][0 if col == 'x' else 1] = value
        rows = [row for i, row in enumerate(rows) if i not in delta.get('deleted_rows', [])]
        for row in delta.get('added_rows', []):
            if row.get('x') is None and row.get('y') is None:
                continue
            rows.append([row.get('x'), row.get('y')])
        pixels = []
        for row in rows:
            if any(v is None for v in row):
                s.table_error = 'Complete both coordinates in the new row, then press Enter.'
                return
            if any(not math.isfinite(float(v)) for v in row):
                raise ValueError('Every coordinate must be a finite number.')
            p = calibration.data_to_pixel(*map(float, row))
            if not (0 <= p[0] < s.image_size[0] and 0 <= p[1] < s.image_size[1]):
                raise ValueError('That row maps outside the image. Enter coordinates within the image.')
            pixels.append(list(p))
        remember()
        next(d for d in s.datasets if d['id'] == dataset_id)['points'] = pixels
        s.table_error = None
    except (ValueError, OverflowError, TypeError) as error:
        s.table_error = str(error)
        s.revision += 1


def project_bytes():
    s = st.session_state
    fields = ['image_url', 'image_name', 'image_size', 'refs', 'datasets', 'active_id',
              'next_dataset', 'x0', 'x1', 'y0', 'y1', 'x_scale', 'y_scale', 'x_label', 'y_label']
    return json.dumps({'version': 1, **{key: s[key] for key in fields}}, ensure_ascii=False).encode('utf-8')


def restore_project(raw):
    """Validate an untrusted JSON backup completely before changing session state."""
    if len(raw) > 35_000_000:
        raise ValueError('Project is too large (35 MB maximum).')
    p = json.loads(raw)
    if not isinstance(p, dict) or p.get('version') != 1 or not isinstance(p.get('image_url'), str) or not p['image_url'].startswith('data:image/png;base64,'):
        raise ValueError('Choose a Trace project JSON downloaded from this app.')
    image_raw = base64.b64decode(p['image_url'].split(',', 1)[1], validate=True)
    im = load_image(image_raw)
    refs = p['refs']
    if len(refs) != 3 or not isinstance(p['datasets'], list) or not 1 <= len(p['datasets']) <= 100:
        raise ValueError('Invalid references or datasets in project.')
    def check_pixel(point):
        if len(point) != 2 or not all(math.isfinite(float(v)) for v in point):
            raise ValueError('Invalid point in project.')
        if not (0 <= point[0] < im.width and 0 <= point[1] < im.height):
            raise ValueError('A point lies outside the image.')
    for point in refs:
        if point is not None:
            check_pixel(point)
    ids = set()
    for d in p['datasets']:
        if not isinstance(d['id'], str) or d['id'] in ids or not str(d['name']).strip():
            raise ValueError('Invalid dataset identity or name.')
        ids.add(d['id'])
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', d['color']):
            raise ValueError('Invalid dataset color.')
        if len(d['points']) > 100_000:
            raise ValueError('Too many points in this project.')
        for point in d['points']:
            check_pixel(point)
    for field in ['x0', 'x1', 'y0', 'y1']:
        if not isinstance(p[field], (int, float)) or not math.isfinite(p[field]):
            raise ValueError('Invalid calibration number.')
    for field in ['x_scale', 'y_scale']:
        if p[field] not in ['Linear', 'Logarithmic']:
            raise ValueError('Invalid axis scale.')
    for field in ['x_label', 'y_label']:
        if not isinstance(p[field], str) or not p[field].strip():
            raise ValueError('Invalid axis label.')
    replace_image(im, str(p['image_name']), hashlib.sha256(image_raw).hexdigest())
    for field in ['refs', 'datasets', 'x0', 'x1', 'y0', 'y1', 'x_scale', 'y_scale', 'x_label', 'y_label']:
        st.session_state[field] = p[field]
    st.session_state.active_id = p['active_id'] if p['active_id'] in ids else p['datasets'][0]['id']
    st.session_state.next_dataset = len(p['datasets'])
    st.session_state.mode = 'collect' if all(refs) else 'origin'


def main():
    st.set_page_config(page_title='Trace | Plot digitizer', page_icon='📈', layout='wide', initial_sidebar_state='auto')
    st.markdown('''<style>
      .stApp {background:#f7f9fc; color:#193248;}
      .block-container {padding-top:3.5rem; padding-bottom:2.5rem; max-width:1650px;}
      [data-testid="stSidebar"] {background:#fff; border-right:1px solid #e2e8f0;}
      h1,h2,h3 {letter-spacing:-.035em;}
      h1 {font-size:2.5rem !important; padding-bottom:0 !important;}
      [data-testid="stMetric"] {background:white; border:1px solid #e0e8f0; border-radius:12px; padding:12px 16px;}
      .trace-kicker {font-size:.73rem; font-weight:700; letter-spacing:.16em; color:#487ba0; text-transform:uppercase;}
      .trace-sub {color:#5d7286; margin-bottom:1.2rem; font-size:1.02rem;}
      .trace-step {padding:10px 14px; border:1px solid #dce5ef; border-radius:9px; color:#526b80; background:#fff; font-size:.85rem; margin-bottom:16px;}
      .trace-step strong {color:#196b98;}
      .stButton>button {border-radius:8px;}
      [data-testid="stExpander"] {background:white;}
      div[data-testid="stVerticalBlockBorderWrapper"]>div {border-color:#e0e8f0;}
      @media(max-width:700px){.block-container{padding:1.1rem;} h1{font-size:2rem!important;}}
    </style>''', unsafe_allow_html=True)
    s = st.session_state
    defaults = dict(image_url=None, image_id='', image_name='', image_size=(0,0),
                    refs=[None,None,None], datasets=[], active_id='', next_dataset=1,
                    undo_stack=[], redo_stack=[], revision=0, mode='origin',
                    x0=0.0, x1=10.0, y0=0.0, y1=10.0, x_scale='Linear', y_scale='Linear',
                    x_label='x', y_label='y', last_click=None, table_error=None)
    for key, value in defaults.items():
        if key not in s:
            s[key] = copy.deepcopy(value)

    # Load/reset operations precede widget creation so their values can be replaced.
    with st.sidebar:
        st.markdown('<div class="trace-kicker">TRACE / WORKSPACE</div>', unsafe_allow_html=True)
        st.header('Start with a plot')
        upload = st.file_uploader('Upload a graph image', type=['png','jpg','jpeg','gif','tif','tiff'], max_upload_size=20,
                                  help='PNG, JPEG, GIF or TIFF; color and grayscale. Up to 20 MB. Uploading a different image starts a new workspace.')
        pending = None
        if upload is not None:
            raw = upload.getvalue()
            if len(raw) > 20_000_000:
                st.error('Choose an image smaller than 20 MB.')
            else:
                try:
                    count = frame_count(raw)
                    frame_key = 'frame_' + hashlib.sha256(raw).hexdigest()
                    frame = st.number_input('Image frame / page', 1, count, 1, key=frame_key)-1 if count > 1 else 0
                    fingerprint = hashlib.sha256(raw+str(frame).encode()).hexdigest()
                    if fingerprint != s.get('last_upload'):
                        pending = (load_image(raw, frame), upload.name, fingerprint)
                except (ValueError, OSError, Image.DecompressionBombError) as error:
                    st.error(f'Could not open this image: {error}')
        else:
            s.last_upload = None
        if pending:
            replace_image(*pending)
            s.last_upload = pending[2]
        example = st.selectbox('Or explore an example', ['Linear','Rotated','Logarithmic'], key='example_kind')
        if st.button('Try example', width='stretch'):
            im, refs = example_plot(example)
            replace_image(im, f'{example.lower()}-example.png', 'example-'+example, refs, example=='Logarithmic')
        with st.expander('Resume a saved project'):
            backup = st.file_uploader('Trace project (.json)', type=['json'], key='restore_file')
            if st.button('Restore project', disabled=backup is None, width='stretch'):
                try:
                    restore_project(backup.getvalue())
                    st.success('Workspace restored.')
                except (ValueError, KeyError, TypeError, OSError, OverflowError) as error:
                    st.error(f'Could not restore: {error}')
        st.divider()
        st.subheader('Axes & scale')
        st.text_input('X-axis label', key='x_label', max_chars=100)
        st.text_input('Y-axis label', key='y_label', max_chars=100)
        ca, cb = st.columns(2)
        ca.selectbox('X scale', ['Linear','Logarithmic'], key='x_scale')
        cb.selectbox('Y scale', ['Linear','Logarithmic'], key='y_scale')
        st.caption('At O, enter (x₀, y₀). X shares y₀; Y shares x₀. These values may be nonzero.')
        ca, cb = st.columns(2)
        ca.number_input('x₀ at O', key='x0', format='%.8g')
        cb.number_input('x₁ at X', key='x1', format='%.8g')
        ca, cb = st.columns(2)
        ca.number_input('y₀ at O', key='y0', format='%.8g')
        cb.number_input('y₁ at Y', key='y1', format='%.8g')
        st.caption('Log axes require positive reference values. Descending axes are supported.')

    st.markdown('<div class="trace-kicker">FROM IMAGE TO EVIDENCE</div>', unsafe_allow_html=True)
    st.title('Trace')
    st.markdown('<div class="trace-sub">Precision plot digitizing, one point at a time.</div>', unsafe_allow_html=True)
    if not s.image_url:
        st.markdown('<div class="trace-step"><strong>01 Upload</strong> &nbsp; → &nbsp; 02 Calibrate &nbsp; → &nbsp; 03 Collect &nbsp; → &nbsp; 04 Export</div>', unsafe_allow_html=True)
        with st.container(border=True):
            st.subheader('Give an old graph new data.')
            st.write('Upload your plot in the sidebar, then set three reference points and click the data you need.')
            st.info('New here? Choose an example and select **Try example**. It arrives calibrated and ready for your first point.')
            a,b,c=st.columns(3)
            a.markdown('**Calibrate once**  \nLinear, semi-log, log-log and rotated scans.')
            b.markdown('**Keep every series**  \nNamed datasets, distinct colors and reversible edits.')
            c.markdown('**Export cleanly**  \nLabeled CSV, editable values and a saved workspace.')
        return

    cal, calibration_error = current_calibration()
    total = sum(len(d['points']) for d in s.datasets)
    a,b,c,d=st.columns(4)
    a.metric('Reference points', f'{sum(p is not None for p in s.refs)} / 3')
    b.metric('Datasets', len(s.datasets))
    c.metric('Collected points', total)
    d.metric('Calibration', 'Ready' if cal else 'Set references')
    st.caption(f'{s.image_name} · {s.image_size[0]} × {s.image_size[1]} pixels')

    left, right = st.columns([3.2, 1], gap='large')
    with right:
        st.subheader('Datasets')
        ids = [d['id'] for d in s.datasets]
        if s.active_id not in ids:
            s.active_id = ids[0]
        names = {d['id']: d['name'] for d in s.datasets}
        active_id = st.selectbox('Active dataset', ids, index=ids.index(s.active_id), key=f'dataset_choice_{s.revision}',
                                format_func=names.__getitem__)
        s.active_id = active_id
        active = next(d for d in s.datasets if d['id']==active_id)
        name_key = f'name_{active_id}_{s.revision}'
        def rename_dataset():
            name = s[name_key].strip()
            if name and not any(d['name']==name and d['id']!=active_id for d in s.datasets):
                remember()
                active['name'] = name
                s.notice = None
            else:
                s.notice = 'Use a nonempty, unique dataset name.'
        st.text_input('Dataset name', value=active['name'], key=name_key,
                      max_chars=100, on_change=rename_dataset)
        if s.get('notice'):
            st.warning(s.notice)
        st.caption(f"● {len(active['points'])} points · {active['color']}")
        if st.button('+ Add dataset', width='stretch'):
            remember()
            while f'Dataset {s.next_dataset + 1}' in [d['name'] for d in s.datasets]:
                s.next_dataset += 1
            new = new_dataset(s.next_dataset)
            s.next_dataset += 1
            # Golden-angle hues keep later datasets visually distinct.
            if s.next_dataset > len(PALETTE):
                import colorsys
                rgb=colorsys.hsv_to_rgb((s.next_dataset*.618034)%1,.73,.74)
                new['color']='#'+''.join(f'{round(v*255):02x}' for v in rgb)
            s.datasets.append(new)
            s.active_id = new['id']
            st.rerun()
        if st.button('Delete dataset', width='stretch'):
            remember()
            s.datasets = [d for d in s.datasets if d['id']!=active_id]
            if not s.datasets:
                s.datasets = [new_dataset(s.next_dataset)]
                s.next_dataset += 1
            s.active_id = s.datasets[0]['id']
            st.rerun()
        st.divider()
        a,b=st.columns(2)
        a.button('Undo', disabled=not s.undo_stack, on_click=history_action, args=('undo_stack','redo_stack'), width='stretch')
        b.button('Redo', disabled=not s.redo_stack, on_click=history_action, args=('redo_stack','undo_stack'), width='stretch')
        st.caption('Undo / redo points, table edits, reference picks and dataset changes.')
        show_lines=st.toggle('Connect points', value=False)
        show_numbers=st.toggle('Number points', value=True)
        with st.expander('Quick guide'):
            st.markdown('1. Enter the axis labels and reference values in the sidebar.\n2. Pick **O**, **X**, **Y** in order. O is the intersection of your reference axes, not necessarily zero.\n3. Select **Collect** and click a series. Add a dataset for each other series.\n4. Edit values or delete rows in the table, then download the CSV.\n\nWheel to zoom; drag to pan. Arrow keys position the crosshair; Enter places a point. Hold Shift for fine keyboard steps.')

    with left:
        st.subheader('Digitizing canvas')
        modes = ['origin','x','y','collect','pan']
        labels = ['1 · Pick O','2 · Pick X','3 · Pick Y','Collect','Pan']
        cols=st.columns(5)
        for col, mode, label in zip(cols,modes,labels):
            if col.button(label, type='primary' if s.mode==mode else 'secondary', width='stretch', disabled=mode=='collect' and cal is None):
                s.mode=mode
                st.rerun()
        instructions = {'origin':'Click O: the intersection of the x₀ and y₀ reference lines.',
                        'x':'Click X: a known x₁ on the same x-axis reference line as O.',
                        'y':'Click Y: a known y₁ on the same y-axis reference line as O.',
                        'collect':f"Click points for {active['name']}. Zoom in for more precision.",
                        'pan':'Drag to move the image. Switch to Collect to place points.'}
        st.info(instructions[s.mode])
        if calibration_error and all(p is not None for p in s.refs):
            st.error(calibration_error)
        canvas_data = dict(image=s.image_url, image_id=s.image_id, width=s.image_size[0],height=s.image_size[1],
                           datasets=s.datasets,refs=s.refs,mode=s.mode,active_id=active_id,active_color=active['color'],
                           show_lines=show_lines,show_numbers=show_numbers,instruction=instructions[s.mode])
        result = render_canvas(canvas_data)
        clicked = result.clicked
        if clicked and clicked.get('token') != s.last_click and clicked.get('mode') == s.mode and clicked.get('dataset_id') == active_id:
            s.last_click=clicked.get('token')
            px,py=float(clicked['x']),float(clicked['y'])
            if 0 <= px < s.image_size[0] and 0 <= py < s.image_size[1]:
                if s.mode in ['origin','x','y']:
                    remember()
                    index=['origin','x','y'].index(s.mode)
                    s.refs[index]=[px,py]
                    s.mode=['x','y','collect'][index]
                    st.rerun()
                elif s.mode=='collect' and cal:
                    try:
                        cal.pixel_to_data(px,py)
                        remember()
                        active['points'].append([px,py])
                        st.rerun()
                    except (ValueError,OverflowError) as error:
                        st.error(str(error))
        with st.expander('Reference positions / precision adjustment'):
            st.caption('Image pixels, measured from the top-left. Changing these recalibrates existing data points.')
            rows = [{'reference':name,'pixel_x':p[0] if p else None,'pixel_y':p[1] if p else None}
                    for name,p in zip(['O','X','Y'],s.refs)]
            refs_edited=st.data_editor(pd.DataFrame(rows),disabled=['reference'],hide_index=True,
                                      key=f'refs_{s.revision}',width='stretch')
            if st.button('Apply reference positions'):
                try:
                    points=[]
                    for _,row in refs_edited.iterrows():
                        x,y=float(row.pixel_x),float(row.pixel_y)
                        if not (math.isfinite(x) and math.isfinite(y) and 0<=x<s.image_size[0] and 0<=y<s.image_size[1]):
                            raise ValueError('Each reference must be a finite position inside the image.')
                        points.append([x,y])
                    remember()
                    s.refs=points
                    st.rerun()
                except (ValueError, TypeError) as error:
                    st.error(str(error))

    st.divider()
    st.subheader('Data & export')
    if not cal:
        st.warning(calibration_error)
        st.caption('Finish calibration to see values, edit coordinates and export CSV.')
        st.download_button('Save workspace',project_bytes(),file_name='trace-project.json',mime='application/json')
    else:
        try:
            values = [cal.pixel_to_data(*p) for p in active['points']]
            key=f"points_{active_id}_{s.revision}_{hash((s.x0,s.x1,s.y0,s.y1,s.x_scale,s.y_scale))}"
            st.caption(f"Editing: {active['name']}. Changes move its markers automatically. Select rows and press Delete to remove points. Add rows with both coordinates to place points.")
            if s.table_error:
                st.warning(s.table_error)
            st.data_editor(pd.DataFrame(values,columns=['x','y'],dtype=float),key=key,hide_index=True,
                           num_rows='dynamic',width='stretch',height=250,
                           column_config={'x':st.column_config.NumberColumn(s.x_label.strip() or 'x',format='%.10g',required=True),
                                          'y':st.column_config.NumberColumn(s.y_label.strip() or 'y',format='%.10g',required=True)},
                           on_change=apply_table,args=(active_id,key,values,cal))
            exports=[{'name':d['name'],'values':[cal.pixel_to_data(*p) for p in d['points']]} for d in s.datasets]
            csv_text=csv_export(exports,s.x_label.strip() or 'x',s.y_label.strip() or 'y')
            a,b,c=st.columns([1,1,2])
            a.download_button('↓ Download CSV',csv_text.encode('utf-8-sig'),file_name='digitized-data.csv',mime='text/csv',
                              type='primary',width='stretch',disabled=total==0)
            b.download_button('Save workspace',project_bytes(),file_name='trace-project.json',mime='application/json',width='stretch')
            c.caption('CSV: dataset names in row 1, axis labels in row 2, then x/y pairs. Every dataset is included; shorter series are padded with empty cells.')
            with st.expander('Preview exported CSV · all datasets'):
                st.code(csv_text,language='csv')
        except (ValueError,OverflowError) as error:
            st.error(f'Cannot export these values: {error}')
    st.caption('Trace · NE111 plot digitizer · Images and edits are session-based. Save your workspace before leaving.')


if __name__ == '__main__':
    main()
