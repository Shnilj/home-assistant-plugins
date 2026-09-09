"""Flask ingress UI: live frame, multi-zone editor, capture labelling, training.

Served under Home Assistant ingress, so all links/fetches are RELATIVE — the
ingress base path is prepended by HA automatically.
"""
from __future__ import annotations

import glob
import logging
import os
import shutil
import time

from flask import Flask, Response, jsonify, request, send_from_directory
from waitress import serve as waitress_serve
from werkzeug.utils import secure_filename

from .. import classifier, config
from ..state import ModelHolder, SharedState

log = logging.getLogger("catwatch.web")

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CatWatch</title>
<style>
  :root { color-scheme: light dark; --food:#00c853; --water:#2979ff; }
  body { font-family: system-ui, sans-serif; margin: 0; background: #f5f5f7; color: #1a1a1a; }
  @media (prefers-color-scheme: dark) { body { background: #16171a; color: #e8e8ea; } .card{background:#212226 !important;} }
  header { padding: 14px 20px; background: #3f51b5; color: #fff; font-size: 20px; font-weight: 600; }
  header small { font-weight: 400; opacity: .8; font-size: 13px; }
  main { max-width: 1100px; margin: 0 auto; padding: 16px; display: grid; gap: 16px; grid-template-columns: 1fr 1fr; }
  .card { background: #fff; border-radius: 12px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,.1); }
  .card h2 { margin: 0 0 12px; font-size: 15px; text-transform: uppercase; letter-spacing: .04em; opacity: .7; }
  .full { grid-column: 1 / -1; }
  .pill { display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: 13px; margin: 2px; }
  .ok { background: #d5f5e0; color: #0a6b33; } .bad { background: #ffdede; color: #a10000; }
  #frameWrap { position: relative; display: inline-block; max-width: 100%; }
  #frame { max-width: 100%; border-radius: 8px; display: block; }
  #zoneCanvas { position: absolute; inset: 0; cursor: crosshair; width: 100%; height: 100%; }
  img.snap { max-width: 100%; border-radius: 8px; }
  button { background: #3f51b5; color: #fff; border: 0; padding: 8px 14px; border-radius: 8px; font-size: 14px; cursor: pointer; }
  button.ghost { background: transparent; color: inherit; border: 1px solid #8888; }
  input[type=text] { padding: 7px 9px; border-radius: 8px; border: 1px solid #8888; background: transparent; color: inherit; font-size: 14px; }
  .seg { display: inline-flex; border: 1px solid #8888; border-radius: 8px; overflow: hidden; }
  .seg button { background: transparent; color: inherit; border: 0; border-radius: 0; }
  .seg button.on[data-t=food] { background: var(--food); color: #003417; }
  .seg button.on[data-t=water] { background: var(--water); color: #001a3d; }
  .zrow { display: flex; align-items: center; gap: 8px; padding: 6px 0; border-bottom: 1px solid #8882; }
  .dot { width: 12px; height: 12px; border-radius: 50%; flex: none; }
  .cap { position: relative; display: inline-block; margin: 6px; cursor: pointer; line-height: 0; }
  .cap img { width: 120px; height: 120px; object-fit: cover; border-radius: 8px; display: block; }
  .cap.sel img { outline: 3px solid #00e676; outline-offset: -1px; }
  .cap.sel::after { content: "✓"; position: absolute; top: 6px; left: 6px; width: 22px; height: 22px;
    background: #00e676; color: #084b22; border-radius: 50%; font-size: 15px; font-weight: 700;
    display: flex; align-items: center; justify-content: center; line-height: 1; }
  .bar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; position: sticky; top: 0;
    z-index: 5; background: #3f51b5; color: #fff; padding: 10px 12px; border-radius: 10px; margin-bottom: 10px; }
  .bar button { background: #fff; color: #3f51b5; }
  .bar button.warn { background: #ffd9d9; color: #a10000; }
  .toolrow { margin: 8px 0; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  nav.tabs { max-width: 1100px; margin: 0 auto; padding: 10px 16px 0; display: flex; gap: 8px; }
  nav.tabs button { background: transparent; color: inherit; border: 1px solid #8888;
    border-bottom: 0; padding: 9px 18px; border-radius: 10px 10px 0 0; font-size: 14px; cursor: pointer; }
  nav.tabs button.on { background: #3f51b5; color: #fff; border-color: #3f51b5; }
  .chips { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 12px; }
  .chips button { background: transparent; color: inherit; border: 1px solid #8888; padding: 5px 12px; }
  .chips button.on { background: #3f51b5; color: #fff; border-color: #3f51b5; }
  .evgrid { display: flex; flex-wrap: wrap; gap: 10px; }
  .ev { width: 132px; }
  .evimg { position: relative; }
  .ev img, .ev .noimg { width: 132px; height: 99px; object-fit: cover; border-radius: 8px; display: block; background: #8882; }
  .ev img { cursor: zoom-in; }
  .ev .del { position: absolute; top: 4px; right: 4px; width: 22px; height: 22px; padding: 0;
    border-radius: 50%; border: 0; background: rgba(0,0,0,.55); color: #fff; font-size: 12px;
    line-height: 22px; text-align: center; cursor: pointer; display: none; }
  .ev:hover .del, .evimg:focus-within .del { display: block; }
  .ev .cap2 { font-size: 12px; margin-top: 4px; line-height: 1.35; }
  .ev select.fix { width: 132px; margin-top: 4px; font-size: 12px; padding: 3px; border-radius: 6px;
    background: transparent; color: inherit; border: 1px solid #8888; }
  img.snap { cursor: zoom-in; }
  #lightbox { position: fixed; inset: 0; background: rgba(0,0,0,.85); display: flex;
    align-items: center; justify-content: center; z-index: 50; cursor: zoom-out; padding: 20px; }
  #lightbox[hidden] { display: none; }
  #lightbox img { max-width: 96vw; max-height: 96vh; border-radius: 8px; }
  .recg { margin: 14px 0; }
  .recg h3 { margin: 0 0 4px; font-size: 15px; font-weight: 600; }
  .confusion { width: auto; margin: 8px 0; border-collapse: collapse; }
  .confusion th, .confusion td { padding: 4px 10px; text-align: center; font-size: 13px; border: 1px solid #8883; }
  .confusion th { opacity: .75; }
  .confusion td.diag { font-weight: 700; color: #0a8a3a; }
  .wkrow { display: flex; align-items: flex-end; gap: 10px; margin: 6px 0; }
  .wklabel { width: 100px; font-size: 13px; display: flex; align-items: center; gap: 6px; flex: none; }
  .wkbars { display: flex; gap: 8px; align-items: flex-end; }
  .wkbar { width: 34px; text-align: center; font-size: 11px; }
  .wkfill { width: 100%; border-radius: 4px 4px 0 0; min-height: 2px; }
  .wknum { font-size: 11px; opacity: .7; }
  .wkdaylabel { opacity: .6; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  td { padding: 6px 4px; border-bottom: 1px solid #8882; vertical-align: top; }
  .muted { opacity: .6; font-size: 13px; }
</style>
</head>
<body>
<header>🐱 CatWatch <small>local cat recognition</small></header>
<nav class="tabs">
  <button data-t="monitor" class="on" onclick="showTab('monitor')">Monitor</button>
  <button data-t="zones" onclick="showTab('zones')">Zones</button>
  <button data-t="training" onclick="showTab('training')">Training</button>
</nav>
<main>
  <div class="card full" data-tab="monitor">
    <h2>Live feed</h2>
    <img id="liveFrame" class="snap" alt="live camera" onclick="openLightbox(this.src)">
  </div>

  <div class="card" data-tab="monitor">
    <h2>Status</h2>
    <div id="status"></div>
  </div>

  <div class="card" data-tab="monitor">
    <h2>Cats</h2>
    <table id="catTable"></table>
  </div>

  <div class="card full" data-tab="monitor">
    <h2>History — last 24h</h2>
    <div id="histTotals" style="margin:-4px 0 12px; font-size:14px"></div>
    <div id="histChips" class="chips"></div>
    <div id="histHint" class="muted" style="margin:-4px 0 8px"></div>
    <div id="history" class="evgrid"></div>
  </div>

  <div class="card full" data-tab="monitor">
    <h2>Last 7 days</h2>
    <div id="week"></div>
  </div>

  <div class="card full" data-tab="zones">
    <h2>Zones — food &amp; water bowls</h2>
    <p class="muted">Pick a type, then drag a box tightly around each bowl or fountain (draw it a touch larger so a nudged bowl stays inside). A cat leaning into a <b style="color:var(--food)">food</b> zone counts as eating; a <b style="color:var(--water)">water</b> zone as drinking. Add as many as are out.</p>
    <div class="toolrow">
      <span class="seg">
        <button id="tFood" data-t="food" class="on" onclick="setType('food')">🍽️ Food</button>
        <button id="tWater" data-t="water" onclick="setType('water')">💧 Water</button>
      </span>
      <input type="text" id="zoneName" placeholder="optional name (e.g. Kitchen bowl)">
      <button class="ghost" onclick="clearZones()">Clear all</button>
      <span id="zoneMsg" class="muted"></span>
    </div>
    <div id="frameWrap">
      <img id="frame" alt="camera frame">
      <canvas id="zoneCanvas"></canvas>
    </div>
    <div id="zoneList"></div>
  </div>

  <div class="card" data-tab="monitor">
    <h2>Latest capture</h2>
    <img id="snap" class="snap" alt="latest snapshot" onclick="openLightbox(this.src)">
  </div>

  <div class="card" data-tab="training">
    <h2>Recognition model</h2>
    <p class="muted">Label captures below to teach CatWatch your cats, then retrain. More labelled examples per cat = better recognition.</p>
    <button onclick="train()">Train now</button>
    <button class="ghost" onclick="runEval()">Evaluate accuracy</button>
    <span id="trainMsg" class="muted"></span>
  </div>

  <div class="card full" id="evalCard" data-tab="training">
    <h2>Recognition accuracy</h2>
    <p class="muted">Leave-one-out test on your labelled crops: each crop is classified using all the <i>others</i>, so this reflects real accuracy, not memorisation. Higher is better.</p>
    <div id="evalResults"></div>
  </div>

  <div class="card full" data-tab="training">
    <h2>Captures to label</h2>
    <div id="bar" class="bar" hidden>
      <b><span id="selCount">0</span> selected →</b>
      <span id="catBtns"></span>
      <button class="warn" onclick="assign('_delete')">🗑 Delete</button>
      <button onclick="clearSel()">Clear</button>
    </div>
    <div class="toolrow">
      <button class="ghost" onclick="selectAll()">Select all</button>
      <button class="ghost" onclick="loadCaptures()">Refresh</button>
      <span class="muted">Click images to select, then assign the whole batch to a cat.</span>
    </div>
    <div id="captures"></div>
  </div>
</main>

<div id="lightbox" hidden onclick="this.hidden = true"><img id="lightboxImg" src="" alt="enlarged"></div>

<script>
let CATS = [];
let ZONES = [];
let curType = 'food';
let drawing = false, startX = 0, startY = 0;
const COLORS = { food: '#00c853', water: '#2979ff' };
const frame = document.getElementById('frame');
const canvas = document.getElementById('zoneCanvas');
const ctx = canvas.getContext('2d');

function fit() { canvas.width = frame.clientWidth; canvas.height = frame.clientHeight; drawZones(); }
function sx() { return frame.naturalWidth ? frame.clientWidth / frame.naturalWidth : 1; }
function sy() { return frame.naturalHeight ? frame.clientHeight / frame.naturalHeight : 1; }

function drawZones(temp) {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  for (const z of ZONES) {
    const c = COLORS[z.type] || '#888';
    const [x, y, w, h] = z.rect;
    ctx.strokeStyle = c; ctx.lineWidth = 2;
    ctx.fillStyle = c + '22';
    ctx.fillRect(x*sx(), y*sy(), w*sx(), h*sy());
    ctx.strokeRect(x*sx(), y*sy(), w*sx(), h*sy());
    ctx.fillStyle = c; ctx.font = '13px system-ui';
    ctx.fillText(z.name, x*sx() + 4, y*sy() + 15);
  }
  if (temp) {
    ctx.strokeStyle = COLORS[curType]; ctx.lineWidth = 2;
    ctx.strokeRect(temp[0], temp[1], temp[2], temp[3]);
  }
}

canvas.addEventListener('mousedown', e => { drawing = true; startX = e.offsetX; startY = e.offsetY; });
canvas.addEventListener('mousemove', e => {
  if (!drawing) return;
  drawZones([startX, startY, e.offsetX-startX, e.offsetY-startY]);
});
canvas.addEventListener('mouseup', e => {
  drawing = false;
  const x = Math.min(startX, e.offsetX), y = Math.min(startY, e.offsetY);
  const w = Math.abs(e.offsetX-startX), h = Math.abs(e.offsetY-startY);
  if (w < 8 || h < 8) { drawZones(); return; }
  const rect = [Math.round(x/sx()), Math.round(y/sy()), Math.round(w/sx()), Math.round(h/sy())];
  addZone(rect);
});

function setType(t) {
  curType = t;
  document.getElementById('tFood').classList.toggle('on', t==='food');
  document.getElementById('tWater').classList.toggle('on', t==='water');
}
function nextName(type) {
  const base = type === 'food' ? 'Food bowl' : 'Water';
  return base + ' ' + (ZONES.filter(z => z.type === type).length + 1);
}
function addZone(rect) {
  const field = document.getElementById('zoneName');
  const name = (field.value || '').trim() || nextName(curType);
  ZONES.push({ id: 'z' + Math.random().toString(36).slice(2, 8), name, type: curType, rect });
  field.value = '';
  saveZones(); renderZones(); drawZones();
}
function deleteZone(id) { ZONES = ZONES.filter(z => z.id !== id); saveZones(); renderZones(); drawZones(); }
function clearZones() { ZONES = []; saveZones(); renderZones(); drawZones(); }

async function saveZones() {
  await fetch('api/zones', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({zones: ZONES})});
  const m = document.getElementById('zoneMsg'); m.textContent = 'Saved ✓';
  setTimeout(() => m.textContent = '', 1500);
}
function renderZones() {
  const box = document.getElementById('zoneList');
  if (!ZONES.length) { box.innerHTML = '<span class="muted">No zones yet — draw one above.</span>'; return; }
  box.innerHTML = ZONES.map(z =>
    `<div class="zrow"><span class="dot" style="background:${COLORS[z.type]}"></span>
      <b>${z.name}</b> <span class="muted">${z.type}</span>
      <span style="flex:1"></span>
      <button class="ghost" onclick="deleteZone('${z.id}')">Remove</button></div>`).join('');
}
async function loadZones() {
  ZONES = await (await fetch('api/zones')).json();
  renderZones(); drawZones();
}

async function train() {
  document.getElementById('trainMsg').textContent = 'Training…';
  const j = await (await fetch('api/train', {method:'POST'})).json();
  document.getElementById('trainMsg').textContent = j.trained
    ? `Trained on ${j.samples} images ✓` : 'No labelled images yet.';
  loadCaptures();
}

function showTab(name) {
  document.querySelectorAll('.card').forEach(c => { c.hidden = (c.dataset.tab !== name); });
  document.querySelectorAll('nav.tabs button').forEach(b => b.classList.toggle('on', b.dataset.t === name));
  if (name === 'zones') fit();  // canvas needs a real size once its card is visible
}

const pct = x => x == null ? '–' : (x*100).toFixed(0) + '%';
async function runEval() {
  const msg = document.getElementById('trainMsg');
  msg.textContent = 'Evaluating… this can take a moment.';
  try {
    const j = await (await fetch('api/evaluate', {method:'POST'})).json();
    renderEval(j);
  } finally { msg.textContent = ''; }
}
function confusionTable(conf, cats) {
  const cols = cats.filter(c => cats.some(t => (conf[t] || {})[c] !== undefined));
  let t = '<table class="confusion"><tr><th>actual \\\\ guessed</th>' +
    cols.map(c => `<th>${c}</th>`).join('') + '</tr>';
  for (const c of cats) {
    const row = conf[c] || {};
    t += `<tr><th>${c}</th>` + cols.map(p => {
      const v = row[p] || 0;
      return `<td class="${p === c ? 'diag' : ''}">${v || ''}</td>`;
    }).join('') + '</tr>';
  }
  return t + '</table>';
}
function renderEval(j) {
  const card = document.getElementById('evalCard');
  const box = document.getElementById('evalResults');
  card.hidden = false;
  if (j.note) { box.innerHTML = `<span class="muted">${j.note}</span>`; return; }
  const cats = Object.keys(j.per_cat_counts);
  let html = `<div class="muted">${j.total} labelled crops · ` +
    cats.map(c => `${c} ${j.per_cat_counts[c]}`).join(' · ') + `</div>`;
  for (const name of ['embedding', 'signature'].filter(r => j.recognizers[r])) {
    const r = j.recognizers[name];
    html += `<div class="recg"><h3>${name} — <b>${pct(r.accuracy)}</b> correct <span class="muted">(${r.n} crops)</span></h3>`;
    html += `<div class="muted">At the ${Math.round(j.margin*100)}% margin: ${r.attributed} attributed at ${pct(r.attributed_accuracy)}, ${r.abstained} left unknown.</div>`;
    html += confusionTable(r.confusion, cats);
    if (r.mistakes.length) {
      html += `<div class="muted" style="margin-top:8px">Misclassified (${r.mistakes.length}, worst first):</div><div class="evgrid">`;
      html += r.mistakes.map(m =>
        `<div class="ev"><div class="evimg">
           <img src="api/dataset/${encodeURIComponent(m.true)}/${encodeURIComponent(m.file)}" loading="lazy" onclick="openLightbox(this.src)">
         </div><div class="cap2">${m.true} → <b>${m.pred || '—'}</b><br>
           <span class="muted">${Math.round(m.share*100)}% sure</span></div></div>`).join('');
      html += `</div>`;
    }
    html += `</div>`;
  }
  box.innerHTML = html;
}

function fmtTime(ts) { return ts ? new Date(ts).toLocaleTimeString() : 'never'; }

async function loadStatus() {
  const j = await (await fetch('api/status')).json();
  const s = j.status;
  const pill = (ok, on, off) => `<span class="pill ${ok?'ok':'bad'}">${ok?on:off}</span>`;
  let nowLine = `Now: <b>${s.current_cat}</b>`;
  if (s.current_cat !== 'none') nowLine += ` (${(s.current_confidence*100).toFixed(0)}%)`;
  if (s.current_action && s.current_action !== 'none') nowLine += ` — ${s.current_action} @ ${s.current_zone}`;
  if (s.current_elapsed) nowLine += ` for ${fmtDur(s.current_elapsed)}`;
  document.getElementById('status').innerHTML =
    pill(s.camera_connected,'Camera','No camera') +
    pill(s.mqtt_connected,'MQTT','No MQTT') +
    pill(s.model_ready,'Model ready','Model empty') +
    `<div style="margin-top:10px">${nowLine}</div>`;
  let rows = '';
  for (const [name, c] of Object.entries(j.cats)) {
    const doing = c.eating ? '🍽️ eating' : (c.drinking ? '💧 drinking' : (c.overdue ? '⚠️ overdue' : '—'));
    rows += `<tr><td><b>${name}</b></td><td>${doing}</td>`
         + `<td>${c.meals_today} 🍽️<br>${c.drinks_today} 💧</td>`
         + `<td class="muted">ate ${fmtTime(c.last_eaten)}${c.last_meal_duration!=null?' ('+fmtDur(c.last_meal_duration)+')':''}`
         + `<br>drank ${fmtTime(c.last_drank)}${c.last_drink_duration!=null?' ('+fmtDur(c.last_drink_duration)+')':''}</td></tr>`;
  }
  document.getElementById('catTable').innerHTML = rows;

  const totals = document.getElementById('histTotals');
  if (totals) {
    const parts = Object.entries(j.cats)
      .map(([n, c]) => `<b>${n}</b> ${c.meals_today} 🍽️ &nbsp; ${c.drinks_today} 💧`);
    totals.innerHTML = parts.length
      ? 'Today &nbsp; ' + parts.join(' &nbsp;·&nbsp; ')
      : '';
  }
}

const SELECTED = new Set();
async function loadCats() {
  CATS = await (await fetch('api/cats')).json();
  document.getElementById('catBtns').innerHTML =
    CATS.map(c => `<button onclick="assign('${c}')">${c}</button>`).join(' ');
}
function updateBar() {
  document.getElementById('selCount').textContent = SELECTED.size;
  document.getElementById('bar').hidden = SELECTED.size === 0;
}
function toggleSel(file, el) {
  if (SELECTED.has(file)) { SELECTED.delete(file); el.classList.remove('sel'); }
  else { SELECTED.add(file); el.classList.add('sel'); }
  updateBar();
}
function selectAll() {
  document.querySelectorAll('.cap').forEach(el => { SELECTED.add(el.dataset.file); el.classList.add('sel'); });
  updateBar();
}
function clearSel() {
  SELECTED.clear();
  document.querySelectorAll('.cap').forEach(el => el.classList.remove('sel'));
  updateBar();
}
async function assign(cat) {
  if (SELECTED.size === 0) return;
  await fetch('api/label_batch', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({files: [...SELECTED], cat})});
  SELECTED.clear(); updateBar(); loadCaptures();
}
async function loadCaptures() {
  const files = await (await fetch('api/captures')).json();
  const box = document.getElementById('captures');
  if (!files.length) {
    box.innerHTML = '<span class="muted">No captures yet. They appear here when a cat visits the bowls.</span>';
    clearSel(); return;
  }
  box.innerHTML = files.map(f =>
    `<div class="cap${SELECTED.has(f)?' sel':''}" data-file="${f}" onclick="toggleSel('${f}', this)">
       <img src="api/captures/${f}" loading="lazy"></div>`).join('');
  [...SELECTED].forEach(f => { if (!files.includes(f)) SELECTED.delete(f); });
  updateBar();
}

let EVENTS = [];
let histFilter = 'all';
function actionIcon(a) { return a === 'eating' ? '🍽️' : (a === 'drinking' ? '💧' : '•'); }
function fmtWhen(ts) {
  const d = new Date(ts);
  return d.toLocaleString([], {weekday:'short', hour:'2-digit', minute:'2-digit'});
}
function fmtDur(s) {
  if (!s || s < 1) return '';
  const m = Math.floor(s / 60), sec = Math.round(s % 60);
  return m ? `${m}m ${sec}s` : `${sec}s`;
}
function buildHistChips() {
  const cats = [...new Set(EVENTS.map(e => e.cat))];
  const mk = (v, label) => `<button class="${histFilter===v?'on':''}" onclick="setHistFilter('${v}')">${label}</button>`;
  document.getElementById('histChips').innerHTML = mk('all', 'All') + cats.map(c => mk(c, c)).join('');
}
function setHistFilter(v) { histFilter = v; buildHistChips(); renderHistory(); }
function renderHistory() {
  const box = document.getElementById('history');
  const evs = EVENTS.filter(e => histFilter === 'all' || e.cat === histFilter);
  if (!evs.length) { box.innerHTML = '<span class="muted">No events yet in the last 24h.</span>'; return; }
  box.innerHTML = evs.map(e =>
    `<div class="ev">
       <div class="evimg">
         ${e.snapshot
            ? `<img src="api/snap/${e.snapshot}" loading="lazy" onclick="openLightbox('api/snap/${e.snapshot}')">`
            : '<div class="noimg"></div>'}
         <button class="del" title="Remove" onclick="deleteEvent('${e.id}')">✕</button>
       </div>
       <div class="cap2">${actionIcon(e.action)} ${e.cat === 'unknown' ? '<span class="muted">❓ unknown</span>' : '<b>' + e.cat + '</b>'}<br>
         <span class="muted">${fmtWhen(e.ts)} · ${e.zone}${e.duration != null ? ' · ' + fmtDur(e.duration) : ''}</span></div>
       <select class="fix" onchange="relabelEvent('${e.id}', this.value)">
         <option value="">✎ correct…</option>
         ${CATS.map(c => `<option value="${c}">${c}</option>`).join('')}
       </select>
     </div>`).join('');
}
async function relabelEvent(id, cat) {
  if (!cat) return;
  const j = await (await fetch('api/events/relabel', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({id, cat})})).json();
  const e = EVENTS.find(x => x.id === id); if (e) e.cat = cat;
  renderHistory();
  const h = document.getElementById('histHint');
  if (h) h.textContent = j.trained
    ? '✓ Correction saved and added to training — open Training → Train to apply it.'
    : '✓ Label updated (no training crop was available for this older event).';
}
function openLightbox(src) {
  document.getElementById('lightboxImg').src = src;
  document.getElementById('lightbox').hidden = false;
}
async function deleteEvent(id) {
  await fetch('api/events/delete', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({id})});
  EVENTS = EVENTS.filter(e => e.id !== id);
  buildHistChips(); renderHistory();
}
async function loadHistory() {
  EVENTS = await (await fetch('api/events')).json();
  buildHistChips(); renderHistory();
}

const CATCOLORS = ['#3f51b5', '#00c853', '#ff7043', '#ab47bc', '#26c6da', '#fbc02d'];
async function loadWeek() {
  const j = await (await fetch('api/stats')).json();
  const days = j.days, cats = j.cats;
  let max = 1;
  days.forEach(d => cats.forEach(c => { max = Math.max(max, d.cats[c].meals); }));
  let html = '';
  cats.forEach((c, ci) => {
    const color = CATCOLORS[ci % CATCOLORS.length];
    html += `<div class="wkrow"><div class="wklabel"><span class="dot" style="background:${color}"></span>${c}</div><div class="wkbars">`;
    days.forEach(d => {
      const meals = d.cats[c].meals;
      const h = Math.round(meals / max * 44);
      html += `<div class="wkbar" title="${d.date}: ${meals} meals, ${Math.round(d.cats[c].eat_sec/60)} min at bowl">
                 <div class="wkfill" style="height:${h}px;background:${color}"></div><div class="wknum">${meals || ''}</div></div>`;
    });
    html += `</div></div>`;
  });
  const labels = days.map(d => new Date(d.date).toLocaleDateString([], {weekday:'short'}));
  html += `<div class="wkrow"><div class="wklabel muted">meals / day</div><div class="wkbars">` +
    labels.map(l => `<div class="wkbar wkdaylabel">${l}</div>`).join('') + `</div></div>`;
  document.getElementById('week').innerHTML = html;
}

frame.addEventListener('load', fit);
window.addEventListener('resize', fit);
window.addEventListener('keydown', e => { if (e.key === 'Escape') document.getElementById('lightbox').hidden = true; });
function refreshFrame() {
  const t = 'api/frame.jpg?t=' + Date.now();
  frame.src = t;  // zone editor
  const lf = document.getElementById('liveFrame');
  if (lf) lf.src = t;  // Monitor live feed
}
function refreshSnap() { document.getElementById('snap').src = 'api/snapshot.jpg?t=' + Date.now(); }

showTab('monitor');
loadCats().then(loadCaptures);
loadZones();
loadHistory();
loadWeek();
loadStatus(); refreshFrame(); refreshSnap();
setInterval(loadStatus, 2000);
setInterval(refreshFrame, 1500);
setInterval(refreshSnap, 3000);
setInterval(loadHistory, 15000);
setInterval(loadWeek, 60000);
setInterval(() => { if (SELECTED.size === 0) loadCaptures(); }, 8000);
</script>
</body>
</html>
"""


def _event_day(ev):
    ts = ev.get("ts", "")
    return ts[:10] if len(ts) >= 10 else None


def _list_captures(limit=60):
    files = glob.glob(os.path.join(config.UNLABELED_DIR, "*.jpg"))
    files.sort(key=os.path.getmtime, reverse=True)
    return [os.path.basename(f) for f in files[:limit]]


def create_app(state: SharedState, settings: config.Settings, model_holder: ModelHolder, history, stats):
    app = Flask(__name__)

    @app.get("/")
    def index():
        return Response(INDEX_HTML, mimetype="text/html")

    @app.get("/api/cats")
    def api_cats():
        return jsonify(settings.cats)

    @app.get("/api/status")
    def api_status():
        return jsonify(state.snapshot_status())

    @app.get("/health")
    def health():
        # Used by the Supervisor watchdog: 200 while the processing loop is ticking.
        hb = state.get_heartbeat()
        ok = (not hb) or (time.time() - hb) < 60
        return ("ok", 200) if ok else ("stale", 503)

    @app.get("/api/frame.jpg")
    def api_frame():
        jpg = state.get_frame()
        return Response(jpg, mimetype="image/jpeg") if jpg else ("", 204)

    @app.get("/api/snapshot.jpg")
    def api_snapshot():
        jpg = state.get_snapshot()
        return Response(jpg, mimetype="image/jpeg") if jpg else ("", 204)

    @app.get("/api/events")
    def api_events():
        return jsonify(history.list())

    @app.get("/api/stats")
    def api_stats():
        return jsonify({"cats": settings.cats, "days": stats.last_days(7, settings.cats)})

    @app.post("/api/events/delete")
    def api_events_delete():
        event_id = (request.get_json(silent=True) or {}).get("id", "")
        ev = history.get(event_id)
        ok = history.remove(event_id)
        if ok and ev and ev.get("cat") and ev.get("cat") != "unknown":
            day, action = _event_day(ev), ev.get("action")
            if day and action in ("eating", "drinking"):
                stats.adjust(day, ev["cat"], action, d_count=-1, d_seconds=-(ev.get("duration") or 0))
        return jsonify({"ok": bool(ok)})

    @app.post("/api/events/relabel")
    def api_events_relabel():
        body = request.get_json(silent=True) or {}
        event_id, cat = body.get("id", ""), body.get("cat", "")
        if cat not in settings.cats:
            return jsonify({"ok": False, "error": "unknown cat"}), 400
        ev = history.get(event_id)
        if not ev:
            return jsonify({"ok": False, "error": "not found"}), 404
        fields, trained = {"cat": cat}, False
        crop = ev.get("crop")
        if crop:
            src = os.path.join(config.EVENT_CROP_DIR, secure_filename(crop))
            if os.path.exists(src):
                prev = ev.get("trained_path")  # undo a previous correction's copy
                if prev and os.path.exists(prev):
                    try:
                        os.remove(prev)
                    except OSError:
                        pass
                dst_dir = settings.dataset_dir_for(cat)
                os.makedirs(dst_dir, exist_ok=True)
                dst = os.path.join(dst_dir, f"evt_{ev['id']}.jpg")
                try:
                    shutil.copyfile(src, dst)
                    fields["trained_path"] = dst
                    trained = True
                except OSError:
                    pass
        # Move the meal/drink between cats in the durable stats (unknown didn't count).
        old, action = ev.get("cat"), ev.get("action")
        day, dur = _event_day(ev), (ev.get("duration") or 0)
        if day and action in ("eating", "drinking") and old != cat:
            if old and old != "unknown":
                stats.adjust(day, old, action, d_count=-1, d_seconds=-dur)
            stats.adjust(day, cat, action, d_count=1, d_seconds=dur)
        history.set_fields(event_id, **fields)
        return jsonify({"ok": True, "trained": trained})

    @app.get("/api/snap/<path:name>")
    def api_snap(name):
        return send_from_directory(config.SNAP_DIR, secure_filename(name))

    @app.get("/api/zones")
    def api_zones_get():
        return jsonify(config.load_zones())

    @app.post("/api/zones")
    def api_zones_post():
        zones = (request.get_json(silent=True) or {}).get("zones", [])
        config.save_zones(zones)
        return jsonify({"ok": True, "zones": config.load_zones()})

    @app.get("/api/captures")
    def api_captures():
        return jsonify(_list_captures())

    @app.get("/api/captures/<path:name>")
    def api_capture_img(name):
        return send_from_directory(config.UNLABELED_DIR, secure_filename(name))

    @app.post("/api/label_batch")
    def api_label_batch():
        body = request.get_json(silent=True) or {}
        files = body.get("files", [])
        cat = body.get("cat", "")
        if not isinstance(files, list) or not files:
            return jsonify({"ok": False, "error": "no files"}), 400
        if cat != "_delete" and cat not in settings.cats:
            return jsonify({"ok": False, "error": "unknown cat"}), 400
        moved = 0
        if cat != "_delete":
            dst_dir = settings.dataset_dir_for(cat)
            os.makedirs(dst_dir, exist_ok=True)
        for raw in files:
            fname = secure_filename(str(raw))
            src = os.path.join(config.UNLABELED_DIR, fname)
            if not fname or not os.path.exists(src):
                continue
            try:
                if cat == "_delete":
                    os.remove(src)
                else:
                    os.replace(src, os.path.join(dst_dir, fname))
                moved += 1
            except OSError:
                continue
        return jsonify({"ok": True, "count": moved})

    @app.post("/api/train")
    def api_train():
        summary = classifier.train()
        if summary["trained"]:
            model_holder.set(classifier.SignatureModel.load())
        return jsonify(summary)

    @app.post("/api/evaluate")
    def api_evaluate():
        return jsonify(classifier.evaluate(margin=settings.recognition_margin))

    @app.get("/api/dataset/<label>/<path:name>")
    def api_dataset_img(label, name):
        if label not in settings.cats:
            return ("", 404)
        return send_from_directory(settings.dataset_dir_for(label), secure_filename(name))

    return app


def serve(state, settings, model_holder, history, stats, camera=None):
    app = create_app(state, settings, model_holder, history, stats)
    log.info("Web UI listening on :8099 (ingress)")
    waitress_serve(app, host="0.0.0.0", port=8099, threads=6)
