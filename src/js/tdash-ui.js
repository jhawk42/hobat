import { DATASET_REGISTRY } from './tdash-dataset-registry.js';
import { currentDataset, loadDataset, loadStaticLabelMap, enrichRows, enrichRawFiles } from './tdash-dataset.js';
import {
  renderTopologyForDataset,
  getVisNetwork, getTopologyFilterHandlers,
  setAutoZoomEnabled, setAnimationEnabled,
  isAutoZoomEnabled, isAnimationEnabled
} from './tdash-topology-renderer.js';
import { renderTableForDataset, applyTableFilters, setMoreInfoEnabled, isMoreInfoEnabled } from './tdash-table-renderer.js';

// ── Section 2: Build dataset <select> ────────────────────────────────────────

function populateDatasetSelect() {
  const sel = document.getElementById('dataset-select');
  DATASET_REGISTRY.forEach((entry) => {
    const opt = document.createElement('option');
    opt.value = entry.value;
    opt.textContent = entry.label;
    sel.appendChild(opt);
  });
}

// ── Render dispatcher ────────────────────────────────────────────────────────

let currentView = 'topology';
let _physicsEnabled = true;
let _enhanceEnabled = true;

function renderCurrentView() {
  if (!currentDataset) return;
  const view = currentView;

  const effectiveDataset = _enhanceEnabled
    ? {
        ...currentDataset,
        rows:     enrichRows(currentDataset.rows),
        rawFiles: enrichRawFiles(currentDataset.rawFiles)
      }
    : currentDataset;

  if (view === 'topology') {
    renderTopologyForDataset(effectiveDataset, _physicsEnabled);
  } else {
    renderTableForDataset(effectiveDataset);
  }
}

// ── Section 7: View Toggle ────────────────────────────────────────────────────

function switchView(newView) {
  if (newView === currentView) return;
  currentView = newView;

  const topoPanel = document.getElementById('view-topology');
  const tablePanel = document.getElementById('view-table');
  const btnTopology = document.getElementById('btn-topology');
  const btnTable = document.getElementById('btn-table');
  const btnPhysics = document.getElementById('btn-physics');
  const btnAutoZoom = document.getElementById('btn-auto-zoom');
  const btnAnimation = document.getElementById('btn-animation');
  const btnLegendBtn = document.getElementById('btn-legend');
  const linkFilterEl = document.getElementById('link-filter');

  if (newView === 'topology') {
    topoPanel.style.display = 'block';
    tablePanel.style.display = 'none';
    btnTopology.classList.add('active');
    btnTable.classList.remove('active');
    btnPhysics.style.display = 'inline-block';
    btnAutoZoom.style.display = 'inline-block';
    btnAnimation.style.display = 'inline-block';
    btnLegendBtn.style.display = 'inline-block';
    linkFilterEl.classList.remove('filter-disabled');
    document.getElementById('table-details-list').innerHTML = '<li>Click a row to view its properties.</li>';
  } else {
    topoPanel.style.display = 'none';
    tablePanel.style.display = 'block';
    btnTable.classList.add('active');
    btnTopology.classList.remove('active');
    btnPhysics.style.display = 'none';
    btnAutoZoom.style.display = 'none';
    btnAnimation.style.display = 'none';
    btnLegendBtn.style.display = 'none';
    linkFilterEl.classList.add('filter-disabled');
  }

  if (currentDataset) {
    renderCurrentView();
  }
}

document.getElementById('btn-topology').addEventListener('click', () => switchView('topology'));
document.getElementById('btn-table').addEventListener('click', () => switchView('table'));

// ── Physics toggle ────────────────────────────────────────────────────────────

function setPhysics(enabled) {
  _physicsEnabled = enabled;
  const btn = document.getElementById('btn-physics');
  if (enabled) {
    btn.classList.add('active');
  } else {
    btn.classList.remove('active');
  }
  const net = getVisNetwork();
  if (net) net.setOptions({ physics: { enabled } });
}

document.getElementById('btn-physics').addEventListener('click', () => setPhysics(!_physicsEnabled));

// ── Enhance toggle ────────────────────────────────────────────────────────────

function setEnhance(enabled) {
  _enhanceEnabled = enabled;
  const btn = document.getElementById('btn-enhance');
  if (enabled) {
    btn.classList.add('active');
  } else {
    btn.classList.remove('active');
  }
  renderCurrentView();
}

document.getElementById('btn-enhance').addEventListener('click', () => setEnhance(!_enhanceEnabled));
setEnhance(_enhanceEnabled); // apply initial state to button

// ── More Info toggle ──────────────────────────────────────────────────

function setMoreInfo(enabled) {
  setMoreInfoEnabled(enabled);
  const btn = document.getElementById('btn-more-info');
  if (enabled) {
    btn.classList.add('active');
  } else {
    btn.classList.remove('active');
  }
  if (currentDataset && currentView === 'table') applyTableFilters();
}

document.getElementById('btn-more-info').addEventListener('click', () => setMoreInfo(!isMoreInfoEnabled()));

// ── Animation toggle ──────────────────────────────────────────────────────────

function setAnimation(enabled) {
  setAnimationEnabled(enabled);
  const btn = document.getElementById('btn-animation');
  if (enabled) {
    btn.classList.add('active');
  } else {
    btn.classList.remove('active');
  }
}

document.getElementById('btn-animation').addEventListener('click', () => setAnimation(!isAnimationEnabled()));

// ── Legend toggle ─────────────────────────────────────────────────────────────

const btnLegend  = document.getElementById('btn-legend');
const lqLegendEl = document.getElementById('lq-legend');
btnLegend.addEventListener('click', () => {
  btnLegend.classList.toggle('active');
  lqLegendEl.classList.toggle('hidden', !btnLegend.classList.contains('active'));
});

// ── Auto Zoom toggle ──────────────────────────────────────────────────────────

function setAutoZoom(enabled) {
  setAutoZoomEnabled(enabled);
  const btn = document.getElementById('btn-auto-zoom');
  if (enabled) {
    btn.classList.add('active');
    if (currentView === 'topology') {
      const handlers = getTopologyFilterHandlers();
      if (handlers) handlers.fitIfEnabled();
    }
  } else {
    btn.classList.remove('active');
  }
}

document.getElementById('btn-auto-zoom').addEventListener('click', () => setAutoZoom(!isAutoZoomEnabled()));

// ── Section 8: Filter Controls + Dataset Select Wiring ───────────────────────

document.getElementById('dataset-select').addEventListener('change', async (event) => {
  document.getElementById('node-filter').value = 'all';
  document.getElementById('diagnostic-filter').value = 'all';
  await loadDataset(event.target.value);
  renderCurrentView();
});

document.getElementById('node-filter').addEventListener('change', () => {
  if (!currentDataset) return;
  if (currentView === 'topology') {
    const handlers = getTopologyFilterHandlers();
    if (handlers) {
      const linkFilterEl = document.getElementById('link-filter');
      const nodeFilterEl = document.getElementById('node-filter');
      const diagFilterEl = document.getElementById('diagnostic-filter');
      const counts = handlers.applyFilters(
        nodeFilterEl.value, linkFilterEl.value, diagFilterEl.value
      );
      handlers.updateStatus(counts);
      handlers.fitIfEnabled();
      document.getElementById('details-list').innerHTML = '<li>Click a node to view its properties.</li>';
    }
  } else {
    applyTableFilters();
  }
});

document.getElementById('link-filter').addEventListener('change', () => {
  if (!currentDataset || currentView !== 'topology') return;
  const handlers = getTopologyFilterHandlers();
  if (handlers) {
    const linkFilterEl = document.getElementById('link-filter');
    const nodeFilterEl = document.getElementById('node-filter');
    const diagFilterEl = document.getElementById('diagnostic-filter');
    const counts = handlers.applyFilters(
      nodeFilterEl.value, linkFilterEl.value, diagFilterEl.value
    );
    handlers.updateStatus(counts);
    handlers.fitIfEnabled();
    document.getElementById('details-list').innerHTML = '<li>Click a node to view its properties.</li>';
  }
});

document.getElementById('diagnostic-filter').addEventListener('change', () => {
  if (!currentDataset) return;
  if (currentView === 'topology') {
    const handlers = getTopologyFilterHandlers();
    if (handlers) {
      const linkFilterEl = document.getElementById('link-filter');
      const nodeFilterEl = document.getElementById('node-filter');
      const diagFilterEl = document.getElementById('diagnostic-filter');
      const counts = handlers.applyFilters(
        nodeFilterEl.value, linkFilterEl.value, diagFilterEl.value
      );
      handlers.updateStatus(counts);
      handlers.fitIfEnabled();
      document.getElementById('details-list').innerHTML = '<li>Click a node to view its properties.</li>';
    }
  } else {
    applyTableFilters();
  }
});

// ── Bootstrap ─────────────────────────────────────────────────────────────────

populateDatasetSelect();
await loadStaticLabelMap();
await loadDataset(document.getElementById('dataset-select').value);
renderCurrentView();
