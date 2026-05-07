/**
 * OpenOctopus — i18n translation config
 * Supported languages: en (English), de (Deutsch), zh (中文)
 *
 * Usage:
 *   I18N.t('key')               → translated string for current language
 *   I18N.setLang('zh')          → switch language and refresh DOM
 *   I18N.currentLang()          → 'en' | 'de' | 'zh'
 */

const I18N = (() => {
  const STORAGE_KEY = 'oo_lang';
  const SUPPORTED = ['en', 'de', 'zh'];

  // ─────────────────────────────────────────────────────────────────────────────
  // Translation dictionary
  // ─────────────────────────────────────────────────────────────────────────────
  const dict = {
    en: {
      // Sidebar
      'nav.dashboard':    'Dashboard',
      'nav.portfolio':    'Portfolio',
      'nav.analysis':     'Analysis',
      'nav.market':       'Market Insights',
      'nav.documents':    'Documents',
      'nav.support':      'Support',
      'nav.signout':      'Sign Out',
      'nav.screener':     'Filter Upward Ticker',

      // Screener
      'screener.title':         'Upward Ticker Screener',
      'screener.start':         'Start Scan',
      'screener.stop':          'Pause',
      'screener.resume':        'Resume',
      'screener.cancel':        'Cancel',
      'screener.market.sp500':  'S&P 500',
      'screener.market.ndx':    'NASDAQ 100',
      'screener.market.dax':    'DAX 40',
      'screener.market.tw50':   'TW50',
      'screener.progress':      '%d / %d (%s%%)',
      'screener.date_range':    'Data range: %s → %s',
      'screener.col.ticker':    'Ticker',
      'screener.col.price':     'Price',
      'screener.col.chg_pct':   'vs 52W Low',
      'screener.col.w52_chg':   '52w Change %',
      'screener.col.ma50':      'MA50',
      'screener.col.ma150':     'MA150',
      'screener.col.ma200':     'MA200',
      'screener.col.source':    'Source',
      'screener.from_cache':    'Using cached results',
      'screener.scanning_label':'Scanning Progress',
      'screener.results_label': 'Passing Tickers',
      'screener.status.idle':   'Ready',
      'screener.status.running':'Scanning…',
      'screener.status.paused': 'Paused',
      'screener.status.done':   'Complete',
      'screener.status.cancelled': 'Cancelled',
      'screener.status.error':  'Error',
      'screener.no_results':    'No tickers matched all 7 conditions.',
      'screener.col.w52h':      '52W High',
      'screener.col.w52l':      '52W Low',
      'screener.export_all':    'Export All → Excel',
      'screener.export_selected': 'Export Selected (%d)',
      'screener.send_analysis': 'Send to Backlog (%d)',
      'screener.select_all':    'Select All',
      'screener.selected_n':    '%d selected',
      'screener.pass_count':    '✅ %d passed',
      'screener.fail_count':    '❌ %d failed',
      'screener.tab.done':      '%d✅',
      'screener.tab.scanning':  'Scanning…',
      'screener.tab.paused':    'Paused',
      'screener.saved_analysis':'Saved %d tickers for future analysis',
      'brand.subtitle':   'Institutional Grade',

      // Header
      'search.placeholder': 'Global Identifier Search...',

      // Trinity Hero section
      'section.pii.label':        'Performance Integrity Index',
      'section.pii.tooltip':      'Combines EPS earnings, price trend and analyst consensus into a single integrity score.',
      'section.trinity.title':    'Trinity Divergence Hero',
      'section.ai_overlay':       'AI Overlay',
      'section.raw_data':         'Raw Data',
      'hero.metric.label':        'Selected Ticker',
      'hero.metric.interim':      '· interim solution',
      'hero.metric.note':         'Average analyst target versus current price.',
      'hero.metric.note_fallback':'Current market price for selected ticker.',
      'hero.metric.tooltip':      'Mean Target Upside = (Analyst mean target − current price) / current price × 100. Represents the implied sell-side upside.',

      // Gauges
      'gauge.realized':   'Realized Performance',
      'gauge.guidance':   'Guidance vs Actuals',
      'gauge.consensus':  'Analyst Consensus',

      // Alignment
      'alignment.title':      'Analyst Alignment Trend',
      'alignment.positive':   'Positive Signals',
      'alignment.negative':   'Negative Signals',
      'alignment.disguised':  'Disguised Negatives',
      'alignment.disguised.tooltip': 'Negative signals concealed within positive language, identified via semantic analysis for words such as "challenges" and "transition".',

      // Raw data
      'raw.earnings_power':   'Earnings Power',
      'raw.surprise_track':   'Surprise Track',
      'raw.market_lens':      'Market Lens',

      // Earnings Cycle
      'section.earnings_cycle':           'Quarterly Earnings Reaction Cycle',
      'earnings.tooltip':                 'Compare stock price ±5 days around the earnings date to observe market reaction patterns after EPS beat/miss.',
      'earnings.col.eps':                 'EPS Est → Act',
      'earnings.col.pre':                 'Pre -5d',
      'earnings.col.day0':                'Day 0',
      'earnings.col.post':                'Post +5d',
      'earnings.col.return':              '5d Return',
      'earnings.analyst_target.label':    'Analyst Mean Target',
      'earnings.analyst_upside':          'upside',
      'earnings.pattern.label':           'Pattern:',
      'earnings.next.label':              'Next earnings:',
      'legend.pre':                       'Days -5 to -1',
      'legend.day0':                      'Day 0 (Earnings)',
      'legend.post':                      'Days +1 to +5',

      // Management Credibility
      'section.management.reliability':   'Guidance Accuracy',
      'mgmt.8quarter':                    '8-Quarter Index',
      'mgmt.8quarter_label':              '8-quarter beat pattern',
      'mgmt.stddev':                      'Forecast Variance',
      'mgmt.reliability.tooltip':         'How reliably management\'s quarterly guidance translates into actual results. Graded A–D based on 8-quarter EPS beat/miss history.',
      'reliability.exceptional':          'Exceptional',
      'reliability.reliable':             'Highly Reliable',
      'reliability.moderate':             'Moderate',
      'reliability.inconsistent':         'Inconsistent',
      'reliability.poor':                 'Poor Accuracy',
      'reliability.var_low':              'Low',
      'reliability.var_mid':              'Moderate',
      'reliability.var_high':             'High Variance',
      'section.management.transparency':  'Management Transparency',
      'mgmt.transparency.tooltip':        'Evaluates earnings call language clarity, direct analyst Q&A response rate, and hedging frequency.',
      'mgmt.transparency.low':            'Opacity',
      'mgmt.transparency.high':           'Lucid',
      'section.strategy':                 'Strategy Execution',
      'mgmt.strategy.tooltip':            'Compares prior-quarter management commitments against current-quarter actuals to assess execution quality.',
      'mgmt.commitment':                  "Last Quarter's Promises",
      'mgmt.commitment.sub':              'Did management follow through?',
      'mgmt.continuity':                  'Narrative Consistency',
      'mgmt.continuity.sub':              'Are key topics carried forward?',
      'mgmt.narrative.default':           'High correlation between verbal guidance and subsequent CapEx deployment.',

      // Right sidebar
      'sidebar.data_mode':    'Data Mode',
      'sidebar.no_ai':        'No-AI',
      'sidebar.ai':           'AI',
      'sidebar.ai.note_off':  'Deterministic mode active. No model token usage.',
      'sidebar.ai.note_on':   'AI model active. Responses may incur token usage.',
      'sidebar.policy':       'Policy Outlook',
      'sidebar.sentiment':    'Sentiment Feed',
      'sentiment.all':        'All',
      'sentiment.tech':       'Tech Shifts',
      'sentiment.archive':    'View Deep Intelligence Archive',

      // Portfolio page
      'page.portfolio.label':   'Portfolio Overview',
      'page.portfolio.title':   'Holdings & Allocation',
      'portfolio.aum':          'Total AUM',
      'portfolio.positions':    'Active Positions',
      'portfolio.positions.note': 'Across 12 sectors',
      'portfolio.ytd':          'YTD Return',
      'portfolio.holdings':     'Top Holdings',
      'portfolio.col.ticker':   'Ticker',
      'portfolio.col.weight':   'Weight',
      'portfolio.col.pl':       'P/L',
      'portfolio.col.signal':   'Signal',

      // Analysis page
      'page.analysis.label':    'OpenOctopus Agent',
      'page.analysis.title':    'Investment Analysis',
      'analysis.description':   'Enter a ticker or natural-language query to run the OpenOctopus analysis agent.',
      'analysis.placeholder':   "e.g. AAPL, NVDA, or 'analyze AI semiconductor exposure'",
      'analysis.button':        'Analyze',
      'analysis.output.label':  'Agent Output',
      'analysis.running':       'Running analysis...',

      // Market page
      'page.market.label':      'Market Intelligence',
      'page.market.title':      'Market Insights',

      // Documents page
      'page.documents.title':   'SEC Filings & Reports',

      // Loading states
      'loading.earnings':       'Loading earnings reaction windows...',
      'loading.policy':         'Loading policy outlook...',
      'loading.sentiment':      'Loading sentiment feed...',
      'loading.portfolio':      'Loading portfolio inputs...',
      'loading.ticker':         'Loading live data...',
      'loading.data':           'Loading live data...',
      'loading.alignment':      'Loading analyst alignment trend...',
      'loading.realized':       'Loading realized performance proxy...',
      'loading.guidance':       'Loading guidance consistency...',
      'loading.consensus':      'Loading analyst consensus...',
      'loading.transcript':     'Loading transcript signal...',
      'loading.alignment_trend': 'Loading guidance, commitment, and sentiment signals...',
      'loading.market':         'Loading market overview...',
      'loading.filings':        'Loading filings...',
      'alignment.panel.title':           'Forward Guidance & Commitment Sentiment',
      'alignment.transcript.unavailable': 'Transcript sentiment unavailable',
      'alignment.no_alpha':     'No alpha signals detected',
      'alignment.no_beta':      'No beta risks detected',
      'transcript.date':        'Transcript Date',
      'mgmt.llm_result':        'LLM Analysis Result',
      'mgmt.no_commitments':    'LLM: No verifiable commitments found',
      'mgmt.no_continuity':     'LLM: No topic continuity detected',
      'outcome.met':            'met',
      'outcome.mixed':          'mixed',
      'outcome.missed':         'missed',
      'outcome.unverifiable':   'unverifiable',
      'outcome.aligned':        'Direction aligned',
      'outcome.diverged':       'topic diverged',
      'outcome.dropped':        'topic dropped',
      'outcome.mixed_cont':     'Mixed continuity',
      'earnings.loaded':        'Loaded {n} earnings windows for {ticker}.',
      'earnings.loaded_partial':'Loaded {ok}/{total} earnings windows for {ticker}.',
      'page.documents.label':   'Filing Library',
      'earnings.beat.label':    'Beat',
      'earnings.beat_avg':      'Beat avg 5d',
      'earnings.miss_avg':      'Miss avg 5d',
      'mgmt.pending':           'Loading management execution signals...',
      'status.source':          'source',
      'status.generated':       'generated',
      // Market Insights — Commodities & Sentiment
      'market.commodities':     'Commodities',
      'market.crude_oil':       'WTI Crude Oil',
      'market.brent':           'Brent Crude',
      'market.gold':            'Gold',
      'market.sentiment':       'Market Sentiment',
      'market.sentiment.desc':  'Composite signal: VIX fear gauge, VIX term structure (VIX9D/VIX), gold safe-haven flow.',
      'sentiment.greed':        'Greed',
      'sentiment.neutral':      'Neutral',
      'sentiment.fear':         'Fear',
      'sentiment.extreme_greed':'Extreme Greed',
      'sentiment.extreme_fear': 'Extreme Fear',
      'sentiment.unavailable':  'Unavailable',
      'sentiment.vix_signal':   'VIX Fear Gauge',
      'sentiment.vix_ts':       'VIX Term Structure',
      'sentiment.gold_signal':  'Gold Safe-Haven',
      'sentiment.score_label':  'Sentiment Score',
      'loading.commodities':    'Loading commodities...',
      'loading.sentiment':      'Loading market sentiment...',
      'loading.checklist':      'Loading checklist...',
      'loading.topic_continuity':'Loading topic continuity...',
      'loading.methodology':    'Loading methodology and transcript status...',
      'loading.mgmt_scoring':   'Management scoring methodology pending.',

      // Status / error strings
      'status.no_data':         'NO AVAILABLE DATA',
      'status.interim':         'interim solution',
      'status.unavailable':     'Unavailable',
      'status.planned':         'Planned',
      'status.date_unavailable':'date unavailable',
      'status.loading':         'Loading...',
      'status.input_required':  'Input required',
      'status.no_data_sparkline':'No data',

      // Brand / layout
      'brand.title':            'Advisor Terminal',
      'mgmt.opacity':           'Opacity',
      'mgmt.lucid':             'Lucid',

      // Theme labels (Alpha signals)
      'theme.product_mix_upgrade':   'Product Mix Upgrade',
      'theme.operating_leverage':    'Operating Leverage',
      'theme.new_growth_pillars':    'New Growth Pillars',
      'theme.capital_return':        'Capital Return',
      // Theme labels (Beta risks)
      'theme.inventory_destocking':  'Inventory Destocking',
      'theme.asp_erosion':           'ASP Erosion',
      'theme.macro_scapegoating':    'Macro Scapegoating',
      'theme.capex_anomaly':         'CapEx Anomaly',
      // Theme labels (Disguised negatives)
      'theme.internal_efficiency_pivot':  'Internal Efficiency Pivot',
      'theme.strategic_inventory_mgmt':   'Strategic Inventory Management',
      'theme.investment_year_framing':    'Investment Year Framing',
      'theme.undervaluation_plea':        'Undervaluation Plea',
      'theme.selective_metric_shift':     'Selective Metric Shift',

      // Macro / theme
      'macro.theme_no_data':    'Theme Card · NO AVAILABLE DATA',
      'macro.asset_theme':      'Asset Class: Theme View',
      'macro.theme_default':    'Theme',

      // Earnings errors
      'earnings.no_cycle':      'No earnings cycle data available for {ticker}.',
      'earnings.no_history':    'No historical earnings data available.',
      'earnings.unavailable_row':'Unavailable',
      'earnings.missing_window':'Missing price window',

      // Portfolio
      'portfolio.api_status':   'Portfolio API status: {status}. Required inputs: {inputs}',
      'portfolio.no_holdings':  'No holdings loaded. Provide {inputs}.',

      // Policy / sentiment feed
      'policy.no_events':       'No policy events found.',
      'policy.valid_until':     'Valid until',
      'policy.window':          'Window',
      'sentiment.no_items':     'No sentiment items for this filter.',

      // Analysis
      'analysis.connecting':    'Connecting to Azure model… this may take 15–30 seconds.',
      'analysis.error_prefix':  '⚠ Error: ',
      'analysis.network_error': '⚠ Network error: ',
      'analysis.flask_hint':    'Make sure the Flask server (app.py) is running on port 5000.',

      // Dashboard errors
      'error.loading_ticker':   'error loading {ticker}',
      'error.dashboard_load':   'Dashboard load failed: {msg}',
      'error.market_overview':  'Market overview failed: {msg}',
      'error.commodities':      'Commodities unavailable: {msg}',
      'error.sentiment_load':   'Sentiment unavailable: {msg}',

      // Health badge
      'health.offline':         '🐙 server offline — run app.py',

      // AI status
      'ai.status.on':           'AI ON',
      'ai.status.offline':      'AI OFFLINE',
      'ai.usage.active':        'AI active — tokens: prompt {p}, completion {c}, total {t}.',
      'ai.usage.fallback':      'API unavailable. Local deterministic fallback active.',
      'ai.usage.no_usage':      'AI mode requested, but no model usage recorded.',

      // Transcript
      'transcript.retrieval_only':'Transcript retrieval only.',
      'transcript.current_src':   'Current source: {src}.',
    },

    de: {
      // Sidebar
      'nav.dashboard':    'Dashboard',
      'nav.portfolio':    'Portfolio',
      'nav.analysis':     'Analyse',
      'nav.market':       'Markteinblicke',
      'nav.documents':    'Dokumente',
      'nav.support':      'Support',
      'nav.signout':      'Abmelden',
      'nav.screener':     'Aufwärtsaktien filtern',

      // Screener (DE)
      'screener.title':         'Aufwärtsaktien-Scanner',
      'screener.start':         'Scan starten',
      'screener.stop':          'Pausieren',
      'screener.resume':        'Fortsetzen',
      'screener.cancel':        'Abbrechen',
      'screener.market.sp500':  'S&P 500',
      'screener.market.ndx':    'NASDAQ 100',
      'screener.market.dax':    'DAX 40',
      'screener.market.tw50':   'TW50',
      'screener.col.ticker':    'Ticker',
      'screener.col.price':     'Kurs',
      'screener.col.chg_pct':   'vs 52W Tief',
      'screener.col.w52_chg':   '52W Spanne %',
      'screener.col.ma50':      'MA50',
      'screener.col.ma150':     'MA150',
      'screener.col.ma200':     'MA200',
      'screener.col.source':    'Quelle',
      'screener.from_cache':    'Cache-Ergebnisse',
      'screener.scanning_label':'Scan-Fortschritt',
      'screener.results_label': 'Bestanden',
      'screener.status.idle':   'Bereit',
      'screener.status.running':'Scannt…',
      'screener.status.paused': 'Pausiert',
      'screener.status.done':   'Abgeschlossen',
      'screener.status.cancelled': 'Abgebrochen',
      'screener.status.error':  'Fehler',
      'screener.no_results':    'Kein Ticker erfüllt alle 7 Bedingungen.',
      'screener.col.w52h':      '52W Hoch',
      'screener.col.w52l':      '52W Tief',
      'screener.export_all':    'Alle → Excel',
      'screener.export_selected': 'Auswahl exportieren (%d)',
      'screener.send_analysis': 'Zum Backlog (%d)',
      'screener.select_all':    'Alle auswählen',
      'screener.selected_n':    '%d ausgewählt',
      'screener.pass_count':    '✅ %d bestanden',
      'screener.fail_count':    '❌ %d gefiltert',
      'screener.tab.done':      '%d✅',
      'screener.tab.scanning':  'Scannt…',
      'screener.tab.paused':    'Pausiert',
      'screener.saved_analysis':'%d Aktien für Analyse gespeichert',
      'brand.subtitle':   'Institutionell',

      // Header
      'search.placeholder': 'Globale Kennung suchen...',

      // Trinity Hero section
      'section.pii.label':        'Performance-Integritätsindex',
      'section.pii.tooltip':      'Kombiniert EPS-Ergebnis, Kurstrend und Analystenkonsens zu einem einzigen Integritätsscore.',
      'section.trinity.title':    'Trinity-Divergenz-Übersicht',
      'section.ai_overlay':       'KI-Overlay',
      'section.raw_data':         'Rohdaten',
      'hero.metric.label':        'Ausgewählter Ticker',
      'hero.metric.interim':      '· Übergangslösung',
      'hero.metric.note':         'Durchschnittliches Analystenziel vs. aktueller Kurs.',
      'hero.metric.note_fallback':'Aktueller Marktpreis des ausgewählten Tickers.',
      'hero.metric.tooltip':      'Mean Target Upside = (Analysten-Durchschnittsziel − aktueller Kurs) / aktueller Kurs × 100. Zeigt das implizierte Aufwärtspotenzial.',

      // Gauges
      'gauge.realized':   'Realisierte Performance',
      'gauge.guidance':   'Prognose vs. Ist-Werte',
      'gauge.consensus':  'Analystenkonsens',

      // Alignment
      'alignment.title':      'Analysten-Ausrichtungstrend',
      'alignment.positive':   'Positive Signale',
      'alignment.negative':   'Negative Signale',
      'alignment.disguised':  'Verdeckte Risiken',
      'alignment.disguised.tooltip': 'Negative Signale in positiver Sprache, durch semantische Analyse für Begriffe wie „Herausforderungen" und „Transformation" identifiziert.',

      // Raw data
      'raw.earnings_power':   'Ertragskraft',
      'raw.surprise_track':   'Überraschungsspur',
      'raw.market_lens':      'Marktperspektive',

      // Earnings Cycle
      'section.earnings_cycle':           'Quartals-Ergebnisreaktionszyklus',
      'earnings.tooltip':                 'Aktienkursvergleich ±5 Tage um den Ergebnistag zur Beobachtung von Marktreaktionsmustern nach EPS-Beat/Miss.',
      'earnings.col.eps':                 'EPS Schätzg. → Ist',
      'earnings.col.pre':                 'Vor -5d',
      'earnings.col.day0':                'Tag 0',
      'earnings.col.post':                'Nach +5d',
      'earnings.col.return':              '5d Rendite',
      'earnings.analyst_target.label':    'Analysten-Kursziel (Ø)',
      'earnings.analyst_upside':          'Potenzial',
      'earnings.pattern.label':           'Muster:',
      'earnings.next.label':              'Nächste Ergebnisse:',
      'legend.pre':                       'Tage -5 bis -1',
      'legend.day0':                      'Tag 0 (Ergebnisse)',
      'legend.post':                      'Tage +1 bis +5',

      // Management Credibility
      'section.management.reliability':   'Prognosegenauigkeit',
      'mgmt.8quarter':                    '8-Quartals-Index',
      'mgmt.8quarter_label':              '8-Quartals-Beat-Muster',
      'mgmt.stddev':                      'Prognoseabweichung',
      'mgmt.reliability.tooltip':         'Wie verlässlich die Quartalsprognose des Managements zu Ist-Ergebnissen führt. Bewertet A–D anhand von 8-Quartals-EPS-Beat/Miss-Verlauf.',
      'reliability.exceptional':          'Außergewöhnlich',
      'reliability.reliable':             'Sehr zuverlässig',
      'reliability.moderate':             'Mäßig',
      'reliability.inconsistent':         'Inkonsistent',
      'reliability.poor':                 'Schwache Genauigkeit',
      'reliability.var_low':              'Gering',
      'reliability.var_mid':              'Mäßig',
      'reliability.var_high':             'Hohe Abweichung',
      'section.management.transparency':  'Management-Transparenz',
      'mgmt.transparency.tooltip':        'Bewertet Sprachklarheit in Ergebniskonferenzen, direkte Analystenantwortquote und Absicherungsfrequenz.',
      'mgmt.transparency.low':            'Undurchsichtig',
      'mgmt.transparency.high':           'Klar',
      'section.strategy':                 'Strategieumsetzung',
      'mgmt.strategy.tooltip':            'Vergleicht Management-Commitments des Vorquartals mit aktuellen Ist-Werten zur Beurteilung der Ausführungsqualität.',
      'mgmt.commitment':                  'Versprechen letztes Quartal',
      'mgmt.commitment.sub':              'Hat das Management Wort gehalten?',
      'mgmt.continuity':                  'Narrative Konsistenz',
      'mgmt.continuity.sub':              'Werden Kernthemen weitergeführt?',
      'mgmt.narrative.default':           'Hohe Korrelation zwischen verbaler Guidance und nachfolgendem CapEx-Einsatz.',

      // Right sidebar
      'sidebar.data_mode':    'Datenmodus',
      'sidebar.no_ai':        'Kein KI',
      'sidebar.ai':           'KI',
      'sidebar.ai.note_off':  'Deterministischer Modus aktiv. Kein Modell-Token-Verbrauch.',
      'sidebar.ai.note_on':   'KI-Modell aktiv. Antworten können Token-Nutzung verursachen.',
      'sidebar.policy':       'Politikausblick',
      'sidebar.sentiment':    'Stimmungsfeed',
      'sentiment.all':        'Alle',
      'sentiment.tech':       'Tech-Trends',
      'sentiment.archive':    'Deep-Intelligence-Archiv öffnen',

      // Portfolio page
      'page.portfolio.label':   'Portfolio-Übersicht',
      'page.portfolio.title':   'Bestände & Allokation',
      'portfolio.aum':          'Gesamt-AUM',
      'portfolio.positions':    'Offene Positionen',
      'portfolio.positions.note': 'In 12 Sektoren',
      'portfolio.ytd':          'YTD-Rendite',
      'portfolio.holdings':     'Top-Positionen',
      'portfolio.col.ticker':   'Ticker',
      'portfolio.col.weight':   'Gewicht',
      'portfolio.col.pl':       'G/V',
      'portfolio.col.signal':   'Signal',

      // Analysis page
      'page.analysis.label':    'OpenOctopus Agent',
      'page.analysis.title':    'Investitionsanalyse',
      'analysis.description':   'Ticker oder natürlichsprachliche Abfrage eingeben, um den OpenOctopus-Analyseagenten zu starten.',
      'analysis.placeholder':   "z.B. AAPL, NVDA oder 'KI-Halbleiterexposition analysieren'",
      'analysis.button':        'Analysieren',
      'analysis.output.label':  'Agenten-Ausgabe',
      'analysis.running':       'Analyse läuft...',

      // Market page
      'page.market.label':      'Marktintelligenz',
      'page.market.title':      'Markteinblicke',

      // Documents page
      'page.documents.title':   'SEC-Einreichungen & Berichte',

      // Loading states
      'loading.earnings':       'Ergebnisfenster werden geladen...',
      'loading.policy':         'Politikausblick wird geladen...',
      'loading.sentiment':      'Stimmungsfeed wird geladen...',
      'loading.portfolio':      'Portfolio-Daten werden geladen...',
      'loading.ticker':         'Live-Daten werden geladen...',
      'loading.data':           'Live-Daten werden geladen...',
      'loading.alignment':      'Analysten-Ausrichtungstrend wird geladen...',
      'loading.realized':       'Realisierte Performance wird geladen...',
      'loading.guidance':       'Prognose-Konsistenz wird geladen...',
      'loading.consensus':      'Analystenkonsens wird geladen...',
      'loading.transcript':     'Transkript-Signal wird geladen...',
      'loading.alignment_trend': 'Signale werden geladen...',
      'loading.market':         'Marktübersicht wird geladen...',
      'loading.filings':        'Einreichungen werden geladen...',
      'alignment.panel.title':           'Zukunftsorientierte Prognose & Engagement-Sentiment',
      'alignment.transcript.unavailable': 'Transkript-Sentiment nicht verfügbar',
      'alignment.no_alpha':     'Keine Alpha-Signale erkannt',
      'alignment.no_beta':      'Keine Beta-Risiken erkannt',
      'transcript.date':        'Transkript-Datum',
      'mgmt.llm_result':        'LLM-Analyseergebnis',
      'mgmt.no_commitments':    'LLM: Keine verifizierbaren Zusagen gefunden',
      'mgmt.no_continuity':     'LLM: Keine Themenkontinuität erkannt',
      'outcome.met':            'erfüllt',
      'outcome.mixed':          'gemischt',
      'outcome.missed':         'verfehlt',
      'outcome.unverifiable':   'nicht verifizierbar',
      'outcome.aligned':        'Richtung übereinstimmend',
      'outcome.diverged':       'Thema abgewichen',
      'outcome.dropped':        'Thema weggefallen',
      'outcome.mixed_cont':     'Gemischte Kontinuität',
      'earnings.loaded':        '{n} Ergebnisfenster für {ticker} geladen.',
      'earnings.loaded_partial':'{ok}/{total} Ergebnisfenster für {ticker} geladen.',
      'page.documents.label':   'Einreichungsbibliothek',
      'earnings.beat.label':    'Übertroffen',
      'earnings.beat_avg':      'Beat Ø 5T',
      'earnings.miss_avg':      'Miss Ø 5T',
      'mgmt.pending':           'Management-Signale werden geladen...',
      'status.source':          'Quelle',
      'status.generated':       'Erstellt',
      // Market Insights — Commodities & Sentiment
      'market.commodities':     'Rohstoffe',
      'market.crude_oil':       'WTI Rohöl',
      'market.brent':           'Brent Rohöl',
      'market.gold':            'Gold',
      'market.sentiment':       'Marktstimmung',
      'market.sentiment.desc':  'Kombiniertes Signal: VIX-Angstindikator, VIX-Laufzeitstruktur (VIX9D/VIX), Gold-Sicherheitsfluss.',
      'sentiment.greed':        'Gier',
      'sentiment.neutral':      'Neutral',
      'sentiment.fear':         'Angst',
      'sentiment.extreme_greed':'Extreme Gier',
      'sentiment.extreme_fear': 'Extreme Angst',
      'sentiment.unavailable':  'Nicht verfügbar',
      'sentiment.vix_signal':   'VIX-Angstindikator',
      'sentiment.vix_ts':       'VIX Laufzeitstruktur',
      'sentiment.gold_signal':  'Gold Sicherheitsfluss',
      'sentiment.score_label':  'Stimmungsscore',
      'loading.commodities':    'Rohstoffe werden geladen...',
      'loading.sentiment':      'Marktstimmung wird geladen...',
      'loading.checklist':      'Checkliste wird geladen...',
      'loading.topic_continuity':'Themenkontinuität wird geladen...',
      'loading.methodology':    'Methodik und Transkript-Status werden geladen...',
      'loading.mgmt_scoring':   'Management-Bewertungsmethodik ausstehend.',

      // Status / error strings
      'status.no_data':         'KEINE DATEN VERFÜGBAR',
      'status.interim':         'Übergangslösung',
      'status.unavailable':     'Nicht verfügbar',
      'status.planned':         'Geplant',
      'status.date_unavailable':'Datum nicht verfügbar',
      'status.loading':         'Laden...',
      'status.input_required':  'Eingabe erforderlich',
      'status.no_data_sparkline':'Keine Daten',

      // Brand / layout
      'brand.title':            'Berater-Terminal',
      'mgmt.opacity':           'Undurchsichtig',
      'mgmt.lucid':             'Klar',

      // Theme labels (Alpha signals)
      'theme.product_mix_upgrade':   'Produktmix-Aufwertung',
      'theme.operating_leverage':    'Operativer Hebel',
      'theme.new_growth_pillars':    'Neue Wachstumssäulen',
      'theme.capital_return':        'Kapitalrückgabe',
      // Theme labels (Beta risks)
      'theme.inventory_destocking':  'Lagerabbau',
      'theme.asp_erosion':           'ASP-Erosion',
      'theme.macro_scapegoating':    'Makro-Schuldzuweisung',
      'theme.capex_anomaly':         'CapEx-Anomalie',
      // Theme labels (Disguised negatives)
      'theme.internal_efficiency_pivot':  'Interner Effizienz-Pivot',
      'theme.strategic_inventory_mgmt':   'Strategisches Bestandsmanagement',
      'theme.investment_year_framing':    'Investitionsjahr-Framing',
      'theme.undervaluation_plea':        'Unterbewertungs-Appell',
      'theme.selective_metric_shift':     'Selektive Kennzahlen-Verschiebung',

      // Macro / theme
      'macro.theme_no_data':    'Themenkarte · KEINE DATEN VERFÜGBAR',
      'macro.asset_theme':      'Anlageklasse: Themenansicht',
      'macro.theme_default':    'Thema',

      // Earnings errors
      'earnings.no_cycle':      'Keine Ergebniszyklus-Daten für {ticker} verfügbar.',
      'earnings.no_history':    'Keine historischen Ergebnisdaten verfügbar.',
      'earnings.unavailable_row':'Nicht verfügbar',
      'earnings.missing_window':'Fehlendes Preisfenster',

      // Portfolio
      'portfolio.api_status':   'Portfolio-API-Status: {status}. Erforderliche Eingaben: {inputs}',
      'portfolio.no_holdings':  'Keine Positionen geladen. Bitte angeben: {inputs}.',

      // Policy / sentiment feed
      'policy.no_events':       'Keine politischen Ereignisse gefunden.',
      'policy.valid_until':     'Gültig bis',
      'policy.window':          'Fenster',
      'sentiment.no_items':     'Keine Stimmungseinträge für diesen Filter.',

      // Analysis
      'analysis.connecting':    'Verbindung zum Azure-Modell… dies kann 15–30 Sekunden dauern.',
      'analysis.error_prefix':  '⚠ Fehler: ',
      'analysis.network_error': '⚠ Netzwerkfehler: ',
      'analysis.flask_hint':    'Stellen Sie sicher, dass der Flask-Server (app.py) auf Port 5000 läuft.',

      // Dashboard errors
      'error.loading_ticker':   'Fehler beim Laden von {ticker}',
      'error.dashboard_load':   'Dashboard-Laden fehlgeschlagen: {msg}',
      'error.market_overview':  'Marktübersicht fehlgeschlagen: {msg}',
      'error.commodities':      'Rohstoffe nicht verfügbar: {msg}',
      'error.sentiment_load':   'Stimmung nicht verfügbar: {msg}',

      // Health badge
      'health.offline':         '🐙 Server offline — app.py starten',

      // AI status
      'ai.status.on':           'KI AN',
      'ai.status.offline':      'KI OFFLINE',
      'ai.usage.active':        'KI aktiv — Tokens: Prompt {p}, Completion {c}, Gesamt {t}.',
      'ai.usage.fallback':      'API nicht verfügbar. Lokaler deterministischer Fallback aktiv.',
      'ai.usage.no_usage':      'KI-Modus angefordert, aber keine Modellnutzung erfasst.',

      // Transcript
      'transcript.retrieval_only':'Nur Transkript-Abruf.',
      'transcript.current_src':   'Aktuelle Quelle: {src}.',
    },

    zh: {
      // Sidebar
      'nav.dashboard':    '仪表盘',
      'nav.portfolio':    '投资组合',
      'nav.analysis':     '分析',
      'nav.market':       '市场洞察',
      'nav.documents':    '文件',
      'nav.support':      '帮助',
      'nav.signout':      '退出登录',
      'nav.screener':     '筛选升势股',

      // Screener (ZH)
      'screener.title':         '升势股筛选器',
      'screener.start':         '开始扫描',
      'screener.stop':          '暂停',
      'screener.resume':        '继续',
      'screener.cancel':        '取消',
      'screener.market.sp500':  'S&P 500',
      'screener.market.ndx':    'NASDAQ 100',
      'screener.market.dax':    'DAX 40',
      'screener.market.tw50':   'TW50',
      'screener.progress':      '%d / %d (%s%%)',
      'screener.date_range':    '数据范围：%s → %s',
      'screener.col.ticker':    '股票代码',
      'screener.col.price':     '当前价',
      'screener.col.chg_pct':   'vs 52周低',
      'screener.col.w52_chg':   '52周振幅 %',
      'screener.col.ma50':      'MA50',
      'screener.col.ma150':     'MA150',
      'screener.col.ma200':     'MA200',
      'screener.col.source':    '数据源',
      'screener.from_cache':    '使用缓存结果',
      'screener.scanning_label':'扫描进度',
      'screener.results_label': '通过筛选',
      'screener.status.idle':   '就绪',
      'screener.status.running':'扫描中…',
      'screener.status.paused': '已暂停',
      'screener.status.done':   '完成',
      'screener.status.cancelled': '已取消',
      'screener.status.error':  '出错',
      'screener.no_results':    '没有股票满足全部 7 个条件。',
      'screener.col.w52h':      '52周最高',
      'screener.col.w52l':      '52周最低',
      'screener.export_all':    '全部导出 → Excel',
      'screener.export_selected': '导出已选 (%d)',
      'screener.send_analysis': '加入 Backlog (%d)',
      'screener.select_all':    '全选',
      'screener.selected_n':    '已选 %d 支',
      'screener.pass_count':    '✅ %d 通过',
      'screener.fail_count':    '❌ %d 筛除',
      'screener.tab.done':      '%d✅',
      'screener.tab.scanning':  '扫描中…',
      'screener.tab.paused':    '已暂停',
      'screener.saved_analysis':'已保存 %d 支股票等待分析接入',
      'brand.subtitle':   '机构级',

      // Header
      'search.placeholder': '全局标识符搜索...',

      // Trinity Hero section
      'section.pii.label':        '业绩完整性指数',
      'section.pii.tooltip':      '综合EPS盈利、价格走势与分析师共识三项指标，生成单一完整性评分。',
      'section.trinity.title':    'Trinity 分歧概览',
      'section.ai_overlay':       'AI 叠加',
      'section.raw_data':         '原始数据',
      'hero.metric.label':        '当前标的',
      'hero.metric.interim':      '· 临时方案',
      'hero.metric.note':         '分析师平均目标价与当前股价的比较。',
      'hero.metric.note_fallback':'当前标的实时市场价格。',
      'hero.metric.tooltip':      'Mean Target Upside = (分析师平均目标价 - 当前股价) / 当前股价 × 100，用来表示卖方隐含上涨空间。',

      // Gauges
      'gauge.realized':   '实现业绩',
      'gauge.guidance':   '指引 vs 实际',
      'gauge.consensus':  '分析师共识',

      // Alignment
      'alignment.title':      '分析师一致性趋势',
      'alignment.positive':   '正面信号',
      'alignment.negative':   '负面信号',
      'alignment.disguised':  '隐性负面',
      'alignment.disguised.tooltip': '正面表述中隐藏的负面信息，通过语义分析识别词汇如"挑战""转型"。',

      // Raw data
      'raw.earnings_power':   '盈利能力',
      'raw.surprise_track':   '超预期记录',
      'raw.market_lens':      '市场视角',

      // Earnings Cycle
      'section.earnings_cycle':           '季度财报反应周期',
      'earnings.tooltip':                 '对比财报日前后5日股价，观察 EPS beat/miss 与市场反应之间的规律。',
      'earnings.col.eps':                 'EPS 预期 → 实际',
      'earnings.col.pre':                 '前 -5日',
      'earnings.col.day0':                '第0日',
      'earnings.col.post':                '后 +5日',
      'earnings.col.return':              '5日回报',
      'earnings.analyst_target.label':    '分析师均值目标价',
      'earnings.analyst_upside':          '上行空间',
      'earnings.pattern.label':           '规律：',
      'earnings.next.label':              '下次财报：',
      'legend.pre':                       '第 -5 至 -1 日',
      'legend.day0':                      '第0日（财报）',
      'legend.post':                      '第 +1 至 +5 日',

      // Management Credibility
      'section.management.reliability':   '指引准确度',
      'mgmt.8quarter':                    '8季度指数',
      'mgmt.8quarter_label':              '8季度超预期规律',
      'mgmt.stddev':                      '预测偏差',
      'mgmt.reliability.tooltip':         '管理层季度指引转化为实际业绩的可靠程度，基于8季度EPS超预期/未达预期历史，评级A至D。',
      'reliability.exceptional':          '卓越',
      'reliability.reliable':             '高度可靠',
      'reliability.moderate':             '中等',
      'reliability.inconsistent':         '不稳定',
      'reliability.poor':                 '准确性差',
      'reliability.var_low':              '低',
      'reliability.var_mid':              '中等',
      'reliability.var_high':             '高波动',
      'section.management.transparency':  '管理层透明度',
      'mgmt.transparency.tooltip':        '分析电话会语言清晰度、直接答复分析师质询频率及回避措辞频次等指标。',
      'mgmt.transparency.low':            '模糊',
      'mgmt.transparency.high':           '清晰',
      'section.strategy':                 '战略执行',
      'mgmt.strategy.tooltip':            '比较管理层上季度承诺与本季度实际执行情况，判断战略执行力。',
      'mgmt.commitment':                  '上季承诺兑现',
      'mgmt.commitment.sub':              '管理层是否言出必行？',
      'mgmt.continuity':                  '叙事一致性',
      'mgmt.continuity.sub':              '核心话题是否延续？',
      'mgmt.narrative.default':           '口头指引与后续资本支出部署高度相关。',

      // Right sidebar
      'sidebar.data_mode':    '数据模式',
      'sidebar.no_ai':        '无 AI',
      'sidebar.ai':           'AI',
      'sidebar.ai.note_off':  '确定性模式已激活，无模型 Token 消耗。',
      'sidebar.ai.note_on':   'AI 模型已激活，响应可能消耗 Token。',
      'sidebar.policy':       '政策展望',
      'sidebar.sentiment':    '情绪动态',
      'sentiment.all':        '全部',
      'sentiment.tech':       '科技变局',
      'sentiment.archive':    '查看深度情报存档',

      // Portfolio page
      'page.portfolio.label':   '投资组合概览',
      'page.portfolio.title':   '持仓与配置',
      'portfolio.aum':          '资产管理规模',
      'portfolio.positions':    '活跃仓位',
      'portfolio.positions.note': '覆盖12个行业',
      'portfolio.ytd':          '年初至今回报',
      'portfolio.holdings':     '主要持仓',
      'portfolio.col.ticker':   '标的',
      'portfolio.col.weight':   '权重',
      'portfolio.col.pl':       '盈亏',
      'portfolio.col.signal':   '信号',

      // Analysis page
      'page.analysis.label':    'OpenOctopus 智能体',
      'page.analysis.title':    '投资分析',
      'analysis.description':   '输入股票代码或自然语言查询以启动 OpenOctopus 分析智能体。',
      'analysis.placeholder':   '例如：AAPL、NVDA 或"分析 AI 半导体敞口"',
      'analysis.button':        '分析',
      'analysis.output.label':  '智能体输出',
      'analysis.running':       '正在分析...',

      // Market page
      'page.market.label':      '市场情报',
      'page.market.title':      '市场洞察',

      // Documents page
      'page.documents.title':   '研究文件',

      // Loading states
      'loading.earnings':       '正在加载财报反应窗口...',
      'loading.policy':         '正在加载政策展望...',
      'loading.sentiment':      '正在加载情绪动态...',
      'loading.portfolio':      '正在加载投资组合数据...',
      'loading.ticker':         '正在加载实时数据...',
      'loading.data':           '正在加载实时数据...',
      'loading.alignment':      '正在加载分析师一致性趋势...',
      'loading.realized':       '正在加载实现业绩数据...',
      'loading.guidance':       '正在加载指引一致性...',
      'loading.consensus':      '正在加载分析师共识...',
      'loading.transcript':     '正在加载电话会信号...',
      'loading.alignment_trend': '正在加载指引、承诺及情绪信号...',
      'loading.market':         '正在加载市场概览...',
      'loading.filings':        '正在加载文件...',
      'alignment.panel.title':           '前瞻指引与承诺情绪',
      'alignment.transcript.unavailable': '电话会情绪数据不可用',
      'alignment.no_alpha':     '未检测到 Alpha 信号',
      'alignment.no_beta':      '未检测到 Beta 风险',
      'transcript.date':        '电话会日期',
      'mgmt.llm_result':        'AI 分析结果',
      'mgmt.no_commitments':    'AI：未发现可验证承诺',
      'mgmt.no_continuity':     'AI：未检测到主题延续性',
      'outcome.met':            '已兑现',
      'outcome.mixed':          '混合结果',
      'outcome.missed':         '未兑现',
      'outcome.unverifiable':   '无法验证',
      'outcome.aligned':        '方向一致',
      'outcome.diverged':       '主题偏离',
      'outcome.dropped':        '主题消失',
      'outcome.mixed_cont':     '延续性混合',
      'earnings.loaded':        '已加载 {ticker} 的 {n} 个财报窗口。',
      'earnings.loaded_partial':'已加载 {ticker} 的 {ok}/{total} 个财报窗口。',
      'page.documents.label':   '文件库',
      'earnings.beat.label':    '超预期',
      'earnings.beat_avg':      'Beat 均值5日',
      'earnings.miss_avg':      'Miss 均值5日',
      'mgmt.pending':           '正在加载管理层信号...',
      'status.source':          '数据源',
      'status.generated':       '生成时间',
      // Market Insights — Commodities & Sentiment
      'market.commodities':     '大宗商品',
      'market.crude_oil':       'WTI 原油',
      'market.brent':           '布蘭特原油',
      'market.gold':            '黄金',
      'market.sentiment':       '市场情绪',
      'market.sentiment.desc':  '综合信号：VIX 恐慌指数、VIX 期限结构（VIX9D/VIX）、黄金避险资金流向。',
      'sentiment.greed':        '贪婪',
      'sentiment.neutral':      '中性',
      'sentiment.fear':         '恐惧',
      'sentiment.extreme_greed':'极度贪婪',
      'sentiment.extreme_fear': '极度恐惧',
      'sentiment.unavailable':  '数据不可用',
      'sentiment.vix_signal':   'VIX 恐慌指数',
      'sentiment.vix_ts':       'VIX 期限结构',
      'sentiment.gold_signal':  '黄金避险信号',
      'sentiment.score_label':  '情绪评分',
      'loading.commodities':    '正在加载大宗商品...',
      'loading.sentiment':      '正在加载市场情绪...',
      'loading.checklist':      '正在加载清单...',
      'loading.topic_continuity':'正在加载主题延续...',
      'loading.methodology':    '正在加载方法论和电话会状态...',
      'loading.mgmt_scoring':   '管理层评分方法待定。',

      // Status / error strings
      'status.no_data':         '数据不可用',
      'status.interim':         '临时方案',
      'status.unavailable':     '不可用',
      'status.planned':         '已规划',
      'status.date_unavailable':'日期不可用',
      'status.loading':         '加载中...',
      'status.input_required':  '需要输入',
      'status.no_data_sparkline':'暂无数据',

      // Brand / layout
      'brand.title':            '顾问终端',
      'mgmt.opacity':           '模糊',
      'mgmt.lucid':             '清晰',

      // Theme labels (Alpha signals)
      'theme.product_mix_upgrade':   '产品组合升级',
      'theme.operating_leverage':    '经营杠杆',
      'theme.new_growth_pillars':    '新增长支柱',
      'theme.capital_return':        '资本回报',
      // Theme labels (Beta risks)
      'theme.inventory_destocking':  '库存去化',
      'theme.asp_erosion':           '均价侵蚀',
      'theme.macro_scapegoating':    '宏观甩锅',
      'theme.capex_anomaly':         '资本支出异常',
      // Theme labels (Disguised negatives)
      'theme.internal_efficiency_pivot':  '内部效率转向',
      'theme.strategic_inventory_mgmt':   '战略库存管理',
      'theme.investment_year_framing':    '投资年框架',
      'theme.undervaluation_plea':        '低估呼吁',
      'theme.selective_metric_shift':     '选择性指标转换',

      // Macro / theme
      'macro.theme_no_data':    '主题卡片 · 数据不可用',
      'macro.asset_theme':      '资产类别：主题视图',
      'macro.theme_default':    '主题',

      // Earnings errors
      'earnings.no_cycle':      '{ticker} 暂无财报周期数据。',
      'earnings.no_history':    '暂无历史财报数据。',
      'earnings.unavailable_row':'不可用',
      'earnings.missing_window':'缺少价格窗口',

      // Portfolio
      'portfolio.api_status':   '投资组合 API 状态：{status}。所需输入：{inputs}',
      'portfolio.no_holdings':  '未加载持仓。请提供 {inputs}。',

      // Policy / sentiment feed
      'policy.no_events':       '未找到政策事件。',
      'policy.valid_until':     '有效期至',
      'policy.window':          '窗口',
      'sentiment.no_items':     '该筛选条件下无情绪数据。',

      // Analysis
      'analysis.connecting':    '正在连接 Azure 模型… 可能需要 15-30 秒。',
      'analysis.error_prefix':  '⚠ 错误：',
      'analysis.network_error': '⚠ 网络错误：',
      'analysis.flask_hint':    '请确保 Flask 服务器 (app.py) 在端口 5000 上运行。',

      // Dashboard errors
      'error.loading_ticker':   '加载 {ticker} 时出错',
      'error.dashboard_load':   '仪表盘加载失败：{msg}',
      'error.market_overview':  '市场概览加载失败：{msg}',
      'error.commodities':      '大宗商品不可用：{msg}',
      'error.sentiment_load':   '情绪数据不可用：{msg}',

      // Health badge
      'health.offline':         '🐙 服务器离线 — 请运行 app.py',

      // AI status
      'ai.status.on':           'AI 开启',
      'ai.status.offline':      'AI 离线',
      'ai.usage.active':        'AI 活跃 — 令牌：提示 {p}，完成 {c}，总计 {t}。',
      'ai.usage.fallback':      'API 不可用。本地确定性回退已激活。',
      'ai.usage.no_usage':      '已请求 AI 模式，但未记录模型使用。',

      // Transcript
      'transcript.retrieval_only':'仅电话会文本检索。',
      'transcript.current_src':   '当前数据源：{src}。',
    },
  };

  // ─────────────────────────────────────────────────────────────────────────────
  // API
  // ─────────────────────────────────────────────────────────────────────────────

  let _lang = _detectLang();

  function _detectLang() {
    // Language switcher hidden — always default to EN
    return 'en';
  }

  function t(key) {
    return (dict[_lang] && dict[_lang][key]) || (dict['en'] && dict['en'][key]) || key;
  }

  function currentLang() { return _lang; }

  function setLang(lang) {
    if (!SUPPORTED.includes(lang)) return;
    _lang = lang;
    localStorage.setItem(STORAGE_KEY, lang);
    applyToDOM();
    _updateSwitcherUI();
  }

  function applyToDOM() {
    // text content — preserve child elements (e.g. sort-arrow spans inside <th>)
    document.querySelectorAll('[data-i18n]').forEach(el => {
      const translated = t(el.dataset.i18n);
      if (el.children.length > 0) {
        // Update only the leading text node; leave child elements intact
        const firstChild = el.firstChild;
        if (firstChild && firstChild.nodeType === Node.TEXT_NODE) {
          firstChild.textContent = translated;
        } else {
          el.insertBefore(document.createTextNode(translated), el.firstChild);
        }
      } else {
        el.textContent = translated;
      }
    });
    // placeholders
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
      el.placeholder = t(el.dataset.i18nPlaceholder);
    });
    // inner HTML (for rich tooltips)
    document.querySelectorAll('[data-i18n-html]').forEach(el => {
      el.innerHTML = t(el.dataset.i18nHtml);
    });
    // title attributes
    document.querySelectorAll('[data-i18n-title]').forEach(el => {
      el.title = t(el.dataset.i18nTitle);
    });
  }

  function _updateSwitcherUI() {
    SUPPORTED.forEach(lang => {
      const btn = document.getElementById(`lang-btn-${lang}`);
      if (!btn) return;
      const active = lang === _lang;
      btn.style.background = active ? '#000f27' : 'transparent';
      btn.style.color = active ? '#ffffff' : '#8d9198';
    });
  }

  // Run on DOMContentLoaded if called before DOM is ready
  function init() {
    applyToDOM();
    _updateSwitcherUI();
  }

  function tf(key, params) {
    let s = t(key);
    if (params) Object.keys(params).forEach(k => { s = s.replace(new RegExp('\\{' + k + '\\}', 'g'), params[k]); });
    return s;
  }

  return { t, tf, setLang, currentLang, applyToDOM, init };
})();
