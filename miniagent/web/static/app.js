'use strict';
const $ = id => document.getElementById(id);
let run = '', selected = null, source = false, files = [], loading = false, renderId = 0;
let runSignature = '', fileSignature = '';
const isHTML = path => /\.html?$/i.test(path);
const isImage = path => /\.(png|jpe?g|gif|webp|svg|ico)$/i.test(path);
const previewURL = file => `/preview/${encodeURIComponent(run)}/${file.path.split('/').map(encodeURIComponent).join('/')}?v=${file.version}`;
async function api(path, params = {}) {
  const response = await fetch(path + '?' + new URLSearchParams(params), {cache: 'no-store'});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Dateien nicht erreichbar');
  return data;
}
function message(text) { $('notice').textContent = text; }
function empty(text) {
  renderId++;
  $('preview').replaceChildren();
  const box = document.createElement('div'); box.className = 'empty'; box.textContent = text;
  $('preview').append(box); $('filename').textContent = 'Keine Datei ausgewählt';
  $('source').disabled = true; $('view-kind').textContent = 'Vorschau';
}
async function render() {
  const id = ++renderId;
  if (!selected) return;
  const file = selected;
  $('filename').textContent = file.path; $('filename').title = file.path;
  $('source').disabled = !(isHTML(file.path) || isImage(file.path));
  $('source').setAttribute('aria-pressed', String(source));
  $('source').textContent = source ? 'Vorschau' : 'Quelltext';
  $('preview').replaceChildren(); message('');
  if (!source && isHTML(file.path)) {
    const frame = document.createElement('iframe');
    frame.title = `Vorschau: ${file.path}`; frame.sandbox = 'allow-scripts';
    frame.referrerPolicy = 'no-referrer'; frame.src = previewURL(file);
    $('preview').append(frame); $('view-kind').textContent = 'HTML · isolierte Vorschau';
  } else if (!source && isImage(file.path)) {
    const box = document.createElement('div'); box.className = 'image-view';
    const image = document.createElement('img'); image.alt = file.path; image.src = previewURL(file);
    image.onerror = () => { if (id === renderId) message('Bild nicht verfügbar. Quelltextansicht verwenden.'); };
    box.append(image); $('preview').append(box); $('view-kind').textContent = 'Bild';
  } else {
    $('view-kind').textContent = 'Text · UTF-8';
    try {
      const data = await api('/api/text', {run, path: file.path});
      if (id !== renderId) return;
      const pre = document.createElement('pre'); pre.textContent = data.text;
      $('preview').append(pre);
      if (data.truncated) message('Textvorschau auf 512 KiB gekürzt.');
    } catch (error) { if (id === renderId) message(error.message); }
  }
}
function drawFiles() {
  $('files').replaceChildren();
  for (const file of files) {
    const button = document.createElement('button'); button.className = 'file';
    button.setAttribute('aria-pressed', String(selected?.path === file.path));
    button.title = file.path;
    const name = document.createElement('span'); name.className = 'path'; name.textContent = file.path;
    button.append(name);
    if (file.output) { const tag = document.createElement('span'); tag.className = 'tag'; tag.textContent = 'Ausgabe'; button.append(tag); }
    const size = document.createElement('span'); size.className = 'size'; size.textContent = `${(file.size / 1024).toFixed(1)} KB`; button.append(size);
    button.onclick = () => { selected = file; source = false; drawFiles(); render(); };
    $('files').append(button);
  }
}
async function refresh(force = false) {
  if (loading) return;
  loading = true;
  try {
    const data = await api('/api/runs');
    const signature = JSON.stringify(data.runs);
    if (signature !== runSignature) {
      const choice = $('run').value;
      $('run').replaceChildren(new Option('Aktueller / neuester Run', ''));
      for (const entry of data.runs) $('run').add(new Option(`${entry.label} · ${entry.status}`, entry.id));
      $('run').value = data.runs.some(r => r.id === choice) ? choice : '';
      runSignature = signature;
    }
    const nextRun = $('run').value || data.current || data.runs[0]?.id || '';
    if (run !== nextRun) { run = nextRun; selected = null; fileSignature = ''; }
    if (!run) { files = []; drawFiles(); empty('Noch keine Ergebnisdateien. Starte links mit /run eine Aufgabe.'); $('file-count').textContent = '0 Dateien'; return; }
    const listing = await api('/api/files', {run});
    files = listing.files;
    $('file-count').textContent = `${files.length} Dateien${listing.truncated ? ' (Liste begrenzt)' : ''}`;
    const newSignature = JSON.stringify(files);
    const changed = fileSignature !== newSignature;
    const old = selected;
    selected = files.find(f => f.path === selected?.path) || files.find(f => f.output && isHTML(f.path)) || files.find(f => isHTML(f.path)) || files[0] || null;
    if (changed || force) { drawFiles(); fileSignature = newSignature; }
    if (!selected) empty('Dieser Run hat noch keine sichtbaren Workspace-Dateien.');
    else if (force || old?.path !== selected.path || old?.version !== selected.version ||
             (changed && isHTML(selected.path) && !source)) await render();
    $('connection').textContent = '● Verbunden';
  } catch (error) { $('connection').textContent = 'Verbindung unterbrochen'; message(error.message); }
  finally { loading = false; }
}
$('run').onchange = () => refresh(true);
$('refresh').onclick = () => refresh(true);
$('source').onclick = () => { source = !source; render(); };
$('toggle-files').onclick = () => {
  const hidden = !$('file-browser').hidden; $('file-browser').hidden = hidden;
  $('toggle-files').setAttribute('aria-expanded', String(!hidden));
  $('toggle-files').textContent = hidden ? 'Dateien einblenden' : 'Dateien ausblenden';
  localStorage.setItem('miniagent.filesHidden', String(hidden));
};
if (localStorage.getItem('miniagent.filesHidden') === 'true') $('toggle-files').click();
function split(percent) {
  percent = Math.max(25, Math.min(75, percent));
  document.documentElement.style.setProperty('--left', `${percent}%`);
  $('divider').setAttribute('aria-valuenow', String(Math.round(percent)));
  localStorage.setItem('miniagent.split', String(percent));
}
split(Number(localStorage.getItem('miniagent.split')) || 50);
$('divider').onpointerdown = event => { $('divider').setPointerCapture(event.pointerId); document.body.classList.add('dragging'); };
$('divider').onpointermove = event => { if (document.body.classList.contains('dragging')) split(event.clientX / $('layout').clientWidth * 100); };
$('divider').onpointerup = $('divider').onpointercancel = () => document.body.classList.remove('dragging');
$('divider').onkeydown = event => { if (['ArrowLeft', 'ArrowRight'].includes(event.key)) { event.preventDefault(); split(Number($('divider').getAttribute('aria-valuenow')) + (event.key === 'ArrowLeft' ? -5 : 5)); } };
refresh(); setInterval(refresh, 3000);
