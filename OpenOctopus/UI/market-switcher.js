/**
 * Market Switcher - Toggle between US and Taiwan stocks
 */

// Initialize market state
let currentMarket = localStorage.getItem('currentMarket') || 'us';
let currentTicker = localStorage.getItem('currentTicker') || 'AAPL';

/**
 * Switch market and update UI
 */
function switchMarket(market) {
  currentMarket = market;
  localStorage.setItem('currentMarket', market);

  // Update button states
  const usBtn = document.getElementById('market-btn-us');
  const twBtn = document.getElementById('market-btn-tw');

  if (usBtn && twBtn) {
    if (market === 'us') {
      usBtn.classList.add('nav-active');
      twBtn.classList.remove('nav-active');
    } else {
      usBtn.classList.remove('nav-active');
      twBtn.classList.add('nav-active');
    }
  }

  // Reload dashboard with current ticker
  loadDashboardData(currentTicker);
}

/**
 * Fetch dashboard data based on market
 */
async function loadDashboardDataByMarket(ticker) {
  currentTicker = ticker;
  localStorage.setItem('currentTicker', ticker);

  const isUS = currentMarket === 'us';
  const endpoint = isUS
    ? `/api/dashboard/summary?ticker=${ticker}`
    : `/api/tw/dashboard/summary?ticker=${ticker}`;

  try {
    const response = await fetch(endpoint);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);

    const data = await response.json();
    renderDashboard(data, isUS);
  } catch (error) {
    console.error('Error loading dashboard:', error);
    document.getElementById('dashboard-content').innerHTML =
      `<div class="text-error">Error loading ${currentMarket.toUpperCase()} data for ${ticker}</div>`;
  }
}

/**
 * Render dashboard content
 */
function renderDashboard(data, isUS) {
  const container = document.getElementById('dashboard-content');
  if (!container) return;

  let html = `<div class="p-6">`;
  html += `<h2 class="text-2xl font-bold mb-4">${data.ticker || data.summary?.price_data?.ticker}</h2>`;

  // Market indicator
  html += `<p class="text-sm text-slate-500 mb-6">Market: <span class="font-bold">${isUS ? 'US' : 'Taiwan'}</span></p>`;

  // Price section
  if (data.summary?.price_data && !data.summary.price_data.error) {
    const price = data.summary.price_data;
    html += `<div class="mb-6 p-4 bg-surface-container-low rounded">
      <p class="text-sm text-slate-500">Current Price</p>
      <p class="text-4xl font-bold">${price.price}</p>
      <p class="text-sm ${price.change_pct >= 0 ? 'text-performance-green' : 'text-performance-red'}">
        ${price.change_pct >= 0 ? '+' : ''}${price.change_pct}%
      </p>
    </div>`;
  }

  // Financials section
  if (data.summary?.financials && !data.summary.financials.error) {
    const fin = data.summary.financials;
    html += `<div class="mb-6 p-4 bg-surface-container-low rounded">
      <h3 class="font-bold mb-3">Key Financials</h3>
      <div class="grid grid-cols-2 gap-4 text-sm">
        <div><p class="text-slate-500">P/E Ratio</p><p class="font-bold">${fin.pe_ratio_trailing?.toFixed(2) || 'N/A'}</p></div>
        <div><p class="text-slate-500">ROE</p><p class="font-bold">${fin.return_on_equity_pct?.toFixed(2) || 'N/A'}%</p></div>
        <div><p class="text-slate-500">Debt/Equity</p><p class="font-bold">${fin.debt_to_equity?.toFixed(2) || 'N/A'}</p></div>
        <div><p class="text-slate-500">Dividend Yield</p><p class="font-bold">${fin.dividend_yield_pct?.toFixed(2) || 'N/A'}%</p></div>
      </div>
    </div>`;
  }

  // News section
  if (data.summary?.recent_news && data.summary.recent_news.length > 0) {
    html += `<div class="mb-6 p-4 bg-surface-container-low rounded">
      <h3 class="font-bold mb-3">Recent News</h3>
      <ul class="space-y-2">`;
    data.summary.recent_news.slice(0, 5).forEach(news => {
      html += `<li class="text-sm"><a href="${news.url || '#'}" target="_blank" class="text-blue-600 hover:underline">${news.title || news.headline}</a></li>`;
    });
    html += `</ul></div>`;
  }

  html += `</div>`;
  container.innerHTML = html;
}

/**
 * Initialize market switcher UI
 */
function initMarketSwitcher() {
  const navContainer = document.getElementById('main-nav');
  if (!navContainer) return;

  // Add market selector after logo
  const marketSelector = document.createElement('div');
  marketSelector.className = 'px-6 mb-6 flex gap-2';
  marketSelector.innerHTML = `
    <button id="market-btn-us" class="flex-1 py-2 px-3 text-xs font-bold uppercase rounded nav-active"
            onclick="switchMarket('us')">
      US Stocks
    </button>
    <button id="market-btn-tw" class="flex-1 py-2 px-3 text-xs font-bold uppercase rounded"
            style="background:#eee;" onclick="switchMarket('tw')">
      Taiwan
    </button>
  `;

  // Insert after logo
  const logo = document.querySelector('[data-i18n="brand.title"]')?.closest('.mb-10');
  if (logo) {
    logo.parentNode.insertBefore(marketSelector, logo.nextSibling);
  }

  // Set initial button state
  const usBtn = document.getElementById('market-btn-us');
  const twBtn = document.getElementById('market-btn-tw');
  if (currentMarket === 'us') {
    usBtn?.classList.add('nav-active');
    twBtn?.classList.remove('nav-active');
  } else {
    usBtn?.classList.remove('nav-active');
    twBtn?.classList.add('nav-active');
  }
}

// Initialize when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initMarketSwitcher);
} else {
  initMarketSwitcher();
}
