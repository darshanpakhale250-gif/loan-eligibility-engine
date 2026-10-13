let selectedFile = null;
let activeBatchId = null;
let pollInterval = null;

const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const browseBtn = document.getElementById('browse-btn');
const fileInfo = document.getElementById('file-info');
const fileNameSpan = document.getElementById('file-name');
const fileSizeSpan = document.getElementById('file-size');
const uploadBtn = document.getElementById('upload-btn');
const statusCard = document.getElementById('status-card');
const batchesTbody = document.getElementById('batches-tbody');
const statusMsg = document.getElementById('status-message');

// Stepper elements
const stepUploaded = document.getElementById('step-uploaded');
const stepParsed = document.getElementById('step-parsed');
const stepMatched = document.getElementById('step-matched');
const stepNotified = document.getElementById('step-notified');

// Metrics
const valTotal = document.getElementById('val-total');
const valValid = document.getElementById('val-valid');
const valRejected = document.getElementById('val-rejected');
const valMatched = document.getElementById('val-matched');
const valEmails = document.getElementById('val-emails');

const funnelTotal = document.getElementById('funnel-total');
const funnelSql = document.getElementById('funnel-sql');
const funnelRules = document.getElementById('funnel-rules');
const funnelLlm = document.getElementById('funnel-llm');

// Event Listeners for File Selection
browseBtn.addEventListener('click', (e) => {
  e.stopPropagation();
  fileInput.click();
});
dropZone.addEventListener('click', () => fileInput.click());

fileInput.addEventListener('change', (e) => {
  if (e.target.files.length > 0) {
    handleFile(e.target.files[0]);
  }
});

dropZone.addEventListener('dragover', (e) => {
  e.preventDefault();
  dropZone.classList.add('dragover');
});

dropZone.addEventListener('dragleave', () => {
  dropZone.classList.remove('dragover');
});

dropZone.addEventListener('drop', (e) => {
  e.preventDefault();
  dropZone.classList.remove('dragover');
  if (e.dataTransfer.files.length > 0) {
    handleFile(e.dataTransfer.files[0]);
  }
});

function handleFile(file) {
  if (!file.name.endsWith('.csv')) {
    alert('Please select a valid .csv file');
    return;
  }
  selectedFile = file;
  fileNameSpan.textContent = file.name;
  fileSizeSpan.textContent = `(${(file.size / 1024).toFixed(1)} KB)`;
  fileInfo.style.display = 'flex';
}

uploadBtn.addEventListener('click', async () => {
  if (!selectedFile) return;

  uploadBtn.disabled = true;
  uploadBtn.textContent = 'Uploading...';
  statusCard.style.display = 'block';
  resetMetrics();

  try {
    // 1. Request batch initialization (creates batch & returns upload URL)
    const initRes = await fetch('/api/uploads', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename: selectedFile.name })
    });
    if (!initRes.ok) throw new Error('Failed to create upload batch');
    const initData = await initRes.json();
    activeBatchId = initData.batch_id;

    // 2. Stream upload the file via PUT
    const uploadRes = await fetch(initData.upload_url || `/api/uploads/${activeBatchId}`, {
      method: 'PUT',
      body: selectedFile
    });
    if (!uploadRes.ok) throw new Error('Failed to stream file to server');

    setStepActive(stepUploaded, true);
    startPolling(activeBatchId);
  } catch (err) {
    showError(err.message);
    uploadBtn.disabled = false;
    uploadBtn.textContent = 'Start Ingestion';
  }
});

function startPolling(batchId) {
  if (pollInterval) clearInterval(pollInterval);
  pollBatch(batchId);
  pollInterval = setInterval(() => pollBatch(batchId), 2000);
}

async function pollBatch(batchId) {
  try {
    const res = await fetch(`/api/batches/${batchId}`);
    if (!res.ok) return;
    const b = await res.json();

    updateUIWithBatch(b);

    if (b.status === 'completed' || b.status === 'failed') {
      clearInterval(pollInterval);
      uploadBtn.disabled = false;
      uploadBtn.textContent = 'Start Ingestion';
      loadRecentBatches();
    }
  } catch (e) {
    console.error('Polling error:', e);
  }
}

function updateUIWithBatch(b) {
  valTotal.textContent = b.rows_total || 0;
  valValid.textContent = b.rows_valid || 0;
  valRejected.textContent = b.rows_rejected || 0;
  valMatched.textContent = b.pairs_matched || 0;
  valEmails.textContent = b.emails_sent || 0;

  funnelTotal.textContent = b.pairs_total ?? '-';
  funnelSql.textContent = b.pairs_after_sql ?? '-';
  funnelRules.textContent = b.pairs_after_rules ?? '-';
  funnelLlm.textContent = b.pairs_sent_to_llm ?? '-';

  if (['uploading', 'processing', 'processed', 'matching', 'completed'].includes(b.status)) {
    setStepCompleted(stepUploaded);
  }
  if (['processing', 'processed', 'matching', 'completed'].includes(b.status)) {
    setStepCompleted(stepParsed);
  }
  if (['matching', 'completed'].includes(b.status)) {
    if (b.status === 'completed') setStepCompleted(stepMatched);
    else setStepActive(stepMatched);
  }
  if (b.status === 'completed') {
    setStepCompleted(stepNotified);
  }
  if (b.status === 'failed') {
    showError(b.error_message || 'Processing failed');
  }
}

function setStepActive(stepEl, completedPrev = false) {
  stepEl.classList.add('active');
  stepEl.classList.remove('completed');
}

function setStepCompleted(stepEl) {
  stepEl.classList.remove('active');
  stepEl.classList.add('completed');
}

function resetMetrics() {
  [stepUploaded, stepParsed, stepMatched, stepNotified].forEach(el => {
    el.classList.remove('active', 'completed');
  });
  statusMsg.className = 'status-message';
  statusMsg.textContent = '';
}

function showError(msg) {
  statusMsg.className = 'status-message error';
  statusMsg.textContent = msg;
}

async function loadRecentBatches() {
  try {
    const res = await fetch('/api/batches');
    if (!res.ok) return;
    const batches = await res.json();
    if (!batches || batches.length === 0) {
      batchesTbody.innerHTML = '<tr><td colspan="7" class="empty-state">No batches uploaded yet.</td></tr>';
      return;
    }
    batchesTbody.innerHTML = batches.map(b => `
      <tr>
        <td><code>${b.batch_id.slice(0, 8)}...</code></td>
        <td>${escapeHtml(b.filename)}</td>
        <td><strong>${b.status}</strong></td>
        <td>${b.rows_valid} / ${b.rows_total}</td>
        <td>${b.pairs_matched || 0}</td>
        <td>${b.emails_sent || 0}</td>
        <td>${new Date(b.created_at).toLocaleTimeString()}</td>
      </tr>
    `).join('');
  } catch (err) {
    batchesTbody.innerHTML = '<tr><td colspan="7" class="empty-state">Unable to load batches.</td></tr>';
  }
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text || '';
  return div.innerHTML;
}

// Initial fetch
loadRecentBatches();
loadAnalytics();

let chartFunnelInstance = null;
let chartLenderInstance = null;
let chartCreditInstance = null;
let chartIncomeInstance = null;

const refreshAnalyticsBtn = document.getElementById('refresh-analytics-btn');
if (refreshAnalyticsBtn) {
  refreshAnalyticsBtn.addEventListener('click', () => {
    loadAnalytics();
    loadRecentBatches();
  });
}

async function loadAnalytics() {
  try {
    const res = await fetch('/api/analytics');
    if (!res.ok) return;
    const data = await res.json();
    renderAnalytics(data);
  } catch (err) {
    console.error('Error fetching analytics:', err);
  }
}

function renderAnalytics(data) {
  if (!data) return;

  // 1. Update KPI pills
  if (data.product_counts) {
    const el = document.getElementById('kpi-products');
    const sub = document.getElementById('kpi-products-sub');
    if (el) el.textContent = data.product_counts.total;
    if (sub) sub.textContent = `${data.product_counts.crawled} Crawled • ${data.product_counts.seed} Seed`;
  }

  if (data.funnel) {
    const mEl = document.getElementById('kpi-matches');
    const rEl = document.getElementById('kpi-sql-rate');
    if (mEl) mEl.textContent = Number(data.funnel.pairs_matched || 0).toLocaleString();
    if (rEl) {
      const sqlRate = data.funnel.pairs_total > 0 
        ? ((data.funnel.pairs_after_sql / data.funnel.pairs_total) * 100).toFixed(1) + '%'
        : '0%';
      rEl.textContent = sqlRate;
    }
  }

  if (data.lender_stats && data.lender_stats.length > 0) {
    const topL = data.lender_stats[0];
    const topEl = document.getElementById('kpi-top-lender');
    const topSub = document.getElementById('kpi-top-lender-sub');
    if (topEl) topEl.textContent = topL.lender.split(' ')[0];
    if (topSub) topSub.textContent = `${Number(topL.count).toLocaleString()} Matches`;
  }

  // 2. Render Charts if Chart.js is available
  if (typeof Chart !== 'undefined') {
    renderFunnelChart(data.funnel);
    renderLenderChart(data.lender_stats);
    renderCreditChart(data.credit_stats);
    renderIncomeChart(data.income_stats);
  }

  // 3. Render Top Products
  renderTopProducts(data.top_products);
}

function renderFunnelChart(funnel) {
  const ctx = document.getElementById('chart-funnel');
  if (!ctx || !funnel) return;
  if (chartFunnelInstance) chartFunnelInstance.destroy();

  chartFunnelInstance = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: ['Total Pairs', 'SQL Filter', 'Rules Ranked', 'Matches'],
      datasets: [{
        label: 'Pairs Volume',
        data: [
          funnel.pairs_total || 0,
          funnel.pairs_after_sql || 0,
          funnel.pairs_after_rules || 0,
          funnel.pairs_matched || 0
        ],
        backgroundColor: ['#94a3b8', '#3b82f6', '#8b5cf6', '#10b981'],
        borderRadius: 4
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        y: { beginAtZero: true, grid: { color: '#f1f5f9' } },
        x: { grid: { display: false } }
      }
    }
  });
}

function renderLenderChart(lenderStats) {
  const ctx = document.getElementById('chart-lender');
  if (!ctx || !lenderStats) return;
  if (chartLenderInstance) chartLenderInstance.destroy();

  chartLenderInstance = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: lenderStats.map(s => s.lender),
      datasets: [{
        data: lenderStats.map(s => s.count),
        backgroundColor: ['#2563eb', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899'],
        borderWidth: 2,
        borderColor: '#ffffff'
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: 'right', labels: { boxWidth: 12, font: { size: 11 } } }
      }
    }
  });
}

function renderCreditChart(creditStats) {
  const ctx = document.getElementById('chart-credit');
  if (!ctx || !creditStats) return;
  if (chartCreditInstance) chartCreditInstance.destroy();

  chartCreditInstance = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: creditStats.map(s => s.bracket),
      datasets: [{
        label: 'Borrowers',
        data: creditStats.map(s => s.count),
        backgroundColor: '#0ea5e9',
        borderRadius: 4
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        y: { beginAtZero: true, grid: { color: '#f1f5f9' } },
        x: { grid: { display: false } }
      }
    }
  });
}

function renderIncomeChart(incomeStats) {
  const ctx = document.getElementById('chart-income');
  if (!ctx || !incomeStats) return;
  if (chartIncomeInstance) chartIncomeInstance.destroy();

  chartIncomeInstance = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: incomeStats.map(s => s.bracket),
      datasets: [{
        label: 'Borrowers',
        data: incomeStats.map(s => s.count),
        backgroundColor: '#6366f1',
        borderRadius: 4
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        y: { beginAtZero: true, grid: { color: '#f1f5f9' } },
        x: { grid: { display: false } }
      }
    }
  });
}

function renderTopProducts(products) {
  const container = document.getElementById('top-products-list');
  if (!container) return;
  if (!products || products.length === 0) {
    container.innerHTML = '<div class="empty-state">No product matches recorded.</div>';
    return;
  }

  container.innerHTML = products.map(p => {
    const rateText = p.rate ? `${p.rate}%` : 'Variable';
    return `
      <div class="product-item-card">
        <div>
          <div class="product-lender-tag">${escapeHtml(p.lender)}</div>
          <div class="product-name-title">${escapeHtml(p.product)}</div>
        </div>
        <div class="product-stats-row">
          <span class="product-rate-pill">${rateText}</span>
          <span class="product-matches-badge">${Number(p.matches).toLocaleString()} matches</span>
        </div>
      </div>
    `;
  }).join('');
}

