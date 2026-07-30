/* SuperAcademicAISearch — Annotated Edition renderer
   --
   Single-file vanilla JS. Loads ./result.json (or window.__SAAS_DATA__) and
   paints the page. Bilingual: ?lang=zh / button toggle. */

const ROLE_LABELS = {
    en: { founding:'founding', breakthrough:'breakthrough', improvement:'improvement', branch:'branch', survey:'survey', normal:'work' },
    zh: { founding:'奠基',   breakthrough:'范式突破',  improvement:'关键改进',   branch:'分支开创', survey:'集大成综述', normal:'研究' },
};

const ROLE_COLORS = {
    founding: '#8B2A1F',
    breakthrough: '#B85C2F',
    improvement: '#3F6B47',
    branch: '#1F4068',
    survey: '#6B4F8B',
    normal: '#9A9080',
};

const ROMAN = ['I','II','III','IV','V','VI','VII','VIII','IX','X','XI','XII'];

const UI_EN = {
    edition_agentic: 'Agentic edition',
    edition_deterministic: 'Deterministic edition',
    llm_on: 'LLM analysis',
    llm_off: 'Graph-only',
    field_trace_of: 'A Field Trace of',
    founding_works: 'Founding works',
    abstract: 'Abstract',
    stage: 'Stage',
    works: 'works',
    must_read: 'Must read',
    reading_path: 'Reading path',
    open_problems: 'Open problems',
    what_is_not_solved: 'What is not yet solved',
    citation_index: 'Citation index',
    top_n_by_pagerank: 'Top 30 by PageRank',
    reading_apparatus: 'Reading apparatus',
    for_the_newcomer: 'For the newcomer',
    apparatus: 'Apparatus',
    frontier: 'Frontier',
    index: 'Index',
    full_network: 'Full citation network · interactive',
    marginalia: 'Marginalia',
    ai_reasoning_trace: 'AI reasoning trace',
    events: 'events',
    agents: 'agents',
    authors_notes: "Author's notes",
    method: 'Method',
    deterministic_no_trace: 'Deterministic pipeline · no agentic trace',
    an_annotated_field_trace: 'An annotated field trace',
    cited: 'citations',
    no_founding: 'No founding paper identified.',
    no_must_read: 'No must-read list.',
    no_reading_path: 'No reading path generated.',
    no_gaps: 'No open problems generated.',
    switch_lang: '中文',
    colophon: 'typeset in Source Serif 4 + JetBrains Mono · derived from result.json · open source under Apache 2.0',
    annotated_edition: 'annotated edition',
    expand: '[expand →]',
    collapse: '[collapse]',
    citation_network: 'Citation network',
    network_short: 'Network',
    interactive_pr: 'Interactive · node size ∝ PageRank',
};

const UI_ZH = {
    edition_agentic: 'Agentic 版',
    edition_deterministic: '确定性版',
    llm_on: 'LLM 分析',
    llm_off: '纯图算法',
    field_trace_of: '领域脉络追溯',
    founding_works: '奠基论文',
    abstract: '摘要',
    stage: '阶段',
    works: '篇',
    must_read: '必读',
    reading_path: '推荐阅读顺序',
    open_problems: '研究空白',
    what_is_not_solved: '尚未解决的问题',
    citation_index: '引文索引',
    top_n_by_pagerank: 'PageRank 前 30',
    reading_apparatus: '阅读指引',
    for_the_newcomer: '给新入门者',
    apparatus: '指引',
    frontier: '前沿',
    index: '索引',
    full_network: '完整引用网络 · 可交互',
    marginalia: '作者批注',
    ai_reasoning_trace: 'AI 推理轨迹',
    events: '条事件',
    agents: '位 agent',
    authors_notes: '作者批注',
    method: '方法',
    deterministic_no_trace: '确定性流水线 · 无 agentic 轨迹',
    an_annotated_field_trace: '一份评注版领域脉络',
    cited: '次引用',
    no_founding: '未识别到奠基论文。',
    no_must_read: '暂无必读清单。',
    no_reading_path: '未生成阅读顺序。',
    no_gaps: '未生成研究空白。',
    switch_lang: 'English',
    colophon: '排版采用 Source Serif 4 + JetBrains Mono · 数据源自 result.json · Apache 2.0 协议开源',
    annotated_edition: '评注版',
    expand: '[展开 →]',
    collapse: '[收起]',
    citation_network: '引用网络',
    network_short: '网络',
    interactive_pr: '可交互 · 节点大小 ∝ PageRank',
};

// ============================================================
// State
// ============================================================

let STATE = {
    data: null,
    lang: 'en',
    root: null,
    ranks: {},   // paper_id -> integer rank by network-wide PageRank desc
};

// ============================================================
// Boot
// ============================================================

document.addEventListener('DOMContentLoaded', async () => {
    STATE.root = document.getElementById('root');
    try {
        STATE.data = window.__SAAS_DATA__ || await loadJSON('./result.json');
    } catch (err) {
        STATE.root.innerHTML = `
            <div class="notice">
                <h2>No <code>result.json</code> in this directory.</h2>
                <p>Generate one with the CLI and place it here, or symlink an export:</p>
                <p><code>superacademic run "your query" --out ./tmp/demo</code><br>
                <code>ln -sf ../tmp/demo/result.json ./result.json</code></p>
                <p style="margin-top:1em;font-size:13px;opacity:0.7">Reason: ${escapeHtml(err.message)}</p>
            </div>`;
        return;
    }

    STATE.lang = initialLang(STATE.data);
    setupLanguageToggle();
    render();
});

async function loadJSON(path) {
    const res = await fetch(path, { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
}

function initialLang(data) {
    const fromQuery = new URLSearchParams(location.search).get('lang');
    if (fromQuery === 'zh' || fromQuery === 'en') return fromQuery;
    const fromStorage = (() => { try { return localStorage.getItem('saas.lang'); } catch (e) { return null; } })();
    if (fromStorage === 'zh' || fromStorage === 'en') return fromStorage;
    if ((navigator.language || '').toLowerCase().startsWith('zh') && data.i18n && data.i18n.zh) {
        return 'zh';
    }
    return 'en';
}

function setupLanguageToggle() {
    const btn = document.querySelector('.lang-toggle');
    if (!btn) return;
    btn.addEventListener('click', () => {
        STATE.lang = STATE.lang === 'zh' ? 'en' : 'zh';
        try { localStorage.setItem('saas.lang', STATE.lang); } catch (e) {}
        render();
    });
}

// ============================================================
// Translation helpers
// ============================================================

function ui(key) {
    const base = STATE.lang === 'zh' ? UI_ZH : UI_EN;
    if (STATE.lang === 'zh') {
        const i18n = (STATE.data && STATE.data.i18n && STATE.data.i18n.zh) || {};
        if (i18n.ui && i18n.ui[key]) return i18n.ui[key];
    }
    return base[key] || UI_EN[key] || key;
}

function tx(field, fallback) {
    // Retrieve a translated text field from result.i18n[lang]; fall back to English.
    if (STATE.lang === 'zh' && STATE.data && STATE.data.i18n && STATE.data.i18n.zh) {
        const v = STATE.data.i18n.zh[field];
        if (typeof v === 'string' && v.trim()) return v;
    }
    return fallback;
}

function txList(field, fallback) {
    if (STATE.lang === 'zh' && STATE.data && STATE.data.i18n && STATE.data.i18n.zh) {
        const v = STATE.data.i18n.zh[field];
        if (Array.isArray(v) && v.length) return v;
    }
    return fallback;
}

function txMap(field, fallback) {
    if (STATE.lang === 'zh' && STATE.data && STATE.data.i18n && STATE.data.i18n.zh) {
        const v = STATE.data.i18n.zh[field];
        if (v && typeof v === 'object') return Object.assign({}, fallback, v);
    }
    return fallback || {};
}

function txStage(idx, field, fallback) {
    if (STATE.lang === 'zh' && STATE.data && STATE.data.i18n && STATE.data.i18n.zh) {
        const stages = STATE.data.i18n.zh.stages || [];
        const found = stages.find(s => s && s.paper_id_anchor === `stage_${idx}`) || stages[idx];
        if (found && typeof found[field] === 'string' && found[field].trim()) return found[field];
    }
    return fallback;
}

function roleLabel(role) {
    const map = ROLE_LABELS[STATE.lang === 'zh' ? 'zh' : 'en'];
    return map[role || 'normal'] || map.normal;
}

// ============================================================
// Render
// ============================================================

function render() {
    const data = STATE.data;
    const root = STATE.root;
    const papers = data.graph.papers || {};
    const nodesById = Object.fromEntries((data.graph.nodes || []).map(n => [n.paper_id, n]));

    // Assign a stable [NN] index to every node by PageRank desc — this is the
    // ONE numbering system the page reuses: network labels, the citation index,
    // must-read meta lines, paper cards. Makes the network graph readable
    // (numbers instead of overlapping titles) and lets the eye cross-reference.
    const rankedAll = (data.graph.nodes || [])
        .slice()
        .sort((a, b) => (b.metrics.pagerank || 0) - (a.metrics.pagerank || 0));
    STATE.ranks = Object.fromEntries(rankedAll.map((n, i) => [n.paper_id, i + 1]));

    const yearRange = computeYearRange(data);
    const stageNodes = data.report.stages || [];
    const founding = data.founding || [];
    const mustRead = data.report.must_read || [];
    const reasons = txMap('must_read_reasons', data.report.must_read_reasons || {});
    const contribOverride = txMap('roadmap_contributions', {});
    const roadmapByPid = Object.fromEntries((data.roadmap.nodes || []).map(n => [n.paper_id, n]));

    // Model-composed academic/literary cover title; fall back to the raw query
    // (heuristic/degraded reports, or older result.json without a cover_title).
    // Reused for the browser tab title, masthead, and the cover headline below.
    const coverTitle = tx('cover_title', data.report.cover_title) || data.query;

    // -- document language / title --------------------------------------
    document.documentElement.lang = STATE.lang === 'zh' ? 'zh-CN' : 'en';
    document.title = `${coverTitle} — ${ui('an_annotated_field_trace')}`;

    // -- masthead --------------------------------------------------------
    const mast = document.querySelector('.masthead__title b');
    if (mast) mast.textContent = coverTitle;
    const dateEl = document.querySelector('.masthead__date');
    if (dateEl) dateEl.textContent = isoMonth(STATE.lang);
    const mastSub = document.querySelector('.masthead__sub');
    if (mastSub) mastSub.textContent = ui('an_annotated_field_trace');

    // -- language toggle button label -----------------------------------
    const langBtn = document.querySelector('.lang-toggle');
    if (langBtn) langBtn.textContent = ui('switch_lang');

    // -- cover -----------------------------------------------------------
    document.querySelector('.cover__eyebrow .field-of').textContent = ui('field_trace_of');
    document.querySelector('.cover__eyebrow .mode').textContent =
        data.agentic ? ui('edition_agentic') : ui('edition_deterministic');
    const llmTag = document.querySelector('.cover__eyebrow .llm');
    llmTag.innerHTML = data.llm_used
        ? `<em>${escapeHtml(ui('llm_on'))}</em>`
        : `<em style="color:var(--ink-soft);border-color:var(--rule)">${escapeHtml(ui('llm_off'))}</em>`;

    const titleEl = document.querySelector('.cover__title');
    titleEl.innerHTML = wrapTitle(coverTitle);
    titleEl.classList.remove('cover__title--long', 'cover__title--xlong');
    const titleLen = coverTitle.length;
    if (titleLen > 90) titleEl.classList.add('cover__title--xlong');
    else if (titleLen > 40) titleEl.classList.add('cover__title--long');

    const blurbEl = document.querySelector('.cover__blurb');
    const blurb = tx('cover_blurb', data.report.cover_blurb);
    if (blurb) {
        blurbEl.style.display = '';
        blurbEl.textContent = STATE.lang === 'zh' ? `「${blurb}」` : `“${blurb}”`;
    } else {
        blurbEl.style.display = 'none';
    }

    document.querySelector('.cover__stats').innerHTML = [
        statBox(data.graph.nodes.length, ui('works')),
        statBox(data.graph.edges.length, ui('cited')),
        statBox(stageNodes.length, STATE.lang === 'zh' ? '阶段' : 'stages'),
        statBox(yearRange ? `${yearRange[0]}–${yearRange[1]}` : '—', STATE.lang === 'zh' ? '年跨度' : 'span'),
    ].join('');

    // -- foundations -----------------------------------------------------
    document.querySelector('.foundations__label').textContent = ui('founding_works');
    const foundList = document.querySelector('.foundations__list');
    foundList.innerHTML = founding.length
        ? founding.map((pid, i) => {
            const p = papers[pid] || {};
            const yr = p.year || '—';
            const tag = rankTag(pid);
            return `<li class="foundations__item">
                <span class="foundations__num">[${(i+1).toString().padStart(2,'0')}]</span>
                ${paperLink(p.title || '(untitled)', p, 'foundations__title')}
                <span class="foundations__meta">${yr} · ${formatCites(p.citation_count)} ${escapeHtml(ui('cited'))}${tag ? ` · ${tag}` : ''}</span>
            </li>`;
        }).join('')
        : `<li class="foundations__item" style="color:var(--ink-faint)">${escapeHtml(ui('no_founding'))}</li>`;

    // -- abstract --------------------------------------------------------
    const abstractEl = document.querySelector('.abstract');
    const narrEl = document.querySelector('.abstract__body');
    const narr = tx('narrative', data.report.narrative);
    if (narr) {
        abstractEl.style.display = '';
        document.querySelector('.abstract__label').textContent = ui('abstract');
        narrEl.textContent = narr;
    } else {
        abstractEl.style.display = 'none';
    }

    // -- stages ----------------------------------------------------------
    const stagesHost = document.querySelector('.stages');
    stagesHost.innerHTML = stageNodes.map((s, idx) =>
        renderStage(s, idx, papers, nodesById, roadmapByPid, contribOverride)
    ).join('');

    // -- reading apparatus --------------------------------------------
    document.querySelector('.section--apparatus .section__title').textContent = ui('reading_apparatus');
    document.querySelector('.section--apparatus .section__period').textContent = ui('for_the_newcomer');
    document.querySelector('.section--apparatus .section__num span').textContent = ui('apparatus');

    document.querySelector('.must-label').textContent = ui('must_read');
    document.querySelector('.path-label').textContent = ui('reading_path');

    document.querySelector('.must').innerHTML = mustRead.length
        ? mustRead.map(pid => {
            const p = papers[pid] || {};
            const reason = reasons[pid];
            return `<li class="must__item">
                <span class="must__star">★</span>
                <div>
                    ${paperLink(p.title || '(untitled)', p, 'must__title')}
                    <span class="must__year">${p.year || '—'} · ${rankTag(pid) || shortId(pid)}</span>
                    ${reason ? `<div class="must__reason">${escapeHtml(reason)}</div>` : ''}
                </div>
            </li>`;
        }).join('')
        : `<li class="must__item" style="color:var(--ink-faint)">${escapeHtml(ui('no_must_read'))}</li>`;

    document.querySelector('.path').innerHTML = (data.report.reading_path || []).map(pid => {
        const p = papers[pid] || {};
        return `<li class="path__item">
            ${paperLink(p.title || '(untitled)', p, 'path__title')}
            <span class="path__year">${p.year || '—'}</span>
        </li>`;
    }).join('') || `<li class="path__item" style="color:var(--ink-faint)">${escapeHtml(ui('no_reading_path'))}</li>`;

    // -- gaps ---------------------------------------------------
    document.querySelector('.section--gaps .section__title').textContent = ui('open_problems');
    document.querySelector('.section--gaps .section__period').textContent = ui('what_is_not_solved');
    document.querySelector('.section--gaps .section__num span').textContent = ui('frontier');

    const gapsHost = document.querySelector('.gaps');
    const gapsList = txList('gaps', data.report.gaps || []);
    gapsHost.innerHTML = gapsList.length
        ? gapsList.map(g => `<li class="gap">${escapeHtml(g)}</li>`).join('')
        : `<li class="gap" style="color:var(--ink-faint)">${escapeHtml(ui('no_gaps'))}</li>`;

    // -- citation index --------------------------------------------------
    document.querySelector('.section--index .section__title').textContent = ui('citation_index');
    document.querySelector('.section--index .section__period').textContent = ui('top_n_by_pagerank');
    document.querySelector('.section--index .section__num span').textContent = ui('index');

    const indexHost = document.querySelector('.index');
    const indexed = (data.graph.nodes || [])
        .slice()
        .sort((a, b) => (b.metrics.pagerank || 0) - (a.metrics.pagerank || 0))
        .slice(0, 30);
    indexHost.innerHTML = indexed.map(n => {
        const p = papers[n.paper_id] || {};
        const authors = (p.authors || []).slice(0, 2).join(', ') + (p.authors && p.authors.length > 2 ? ' et al.' : '');
        return `<div class="index__item">
            <span class="index__id">${rankTag(n.paper_id)}</span>
            ${paperLink(p.title || '(untitled)', p, 'index__title')}
            <span class="index__meta">${authors || '—'} · ${p.year || '—'} · ${ui('cited')} ${formatCites(p.citation_count)}× · PR ${(n.metrics.pagerank || 0).toFixed(3)}</span>
        </div>`;
    }).join('');

    // network section header (independent appendix section)
    const netSection = document.querySelector('.section--network');
    if (netSection) {
        netSection.querySelector('.section__title').textContent = ui('citation_network');
        netSection.querySelector('.section__period').textContent = ui('interactive_pr');
        netSection.querySelector('.section__num span').textContent = ui('network_short');
    }

    document.querySelector('.network summary span').textContent = ui('full_network');

    // colophon
    const colophon = document.querySelector('.colophon');
    colophon.innerHTML = `<b>SuperAcademicAISearch</b> · ${escapeHtml(ui('annotated_edition'))} · ${escapeHtml(ui('colophon'))}`;

    // -- appendix network graph (lazy) ----------------------------------
    setupNetwork(data);

    // -- marginalia (trace) ---------------------------------------------
    setupRail(data);
}

// ============================================================
// Stage rendering — headline, time spine, paper cards
// ============================================================

function renderStage(stage, idx, papers, nodesById, roadmapByPid, contribOverride) {
    const num = ROMAN[idx] || String(idx + 1);
    const stageName = txStage(idx, 'name', stage.name);
    const stageHeadline = txStage(idx, 'headline', stage.headline);
    const stageSummary = txStage(idx, 'summary', stage.summary);
    const period = stage.period || '';
    const papersInStage = (stage.papers || [])
        .map(pid => ({
            pid,
            paper: papers[pid] || {},
            roadmap: roadmapByPid[pid],
            node: nodesById[pid],
        }))
        .filter(x => x.paper.title)
        .sort((a, b) => (a.paper.year || 0) - (b.paper.year || 0));

    const ticks = makeSpineTicks(stage.period);
    const worksLabel = ui('works');

    return `
    <article class="stage">
        <header class="section__head">
            <div class="section__num">§ ${num}<span>${escapeHtml(ui('stage'))}</span></div>
            <div>
                <h2 class="section__title">${escapeHtml(stageName)}</h2>
                <span class="section__period">${escapeHtml(period)} · ${papersInStage.length} ${escapeHtml(worksLabel)}</span>
            </div>
        </header>
        ${stageHeadline ? `<p class="stage__headline">${STATE.lang === 'zh' ? '「' : '“'}${escapeHtml(stageHeadline)}${STATE.lang === 'zh' ? '」' : '”'}</p>` : ''}
        ${stageSummary ? `<p class="stage__summary">${escapeHtml(stageSummary)}</p>` : ''}
        ${ticks ? `<div class="spine">
            <div class="spine__line"></div>
            <div class="spine__ticks">${ticks}</div>
        </div>` : ''}
        <div class="cards">
            ${papersInStage.map(({pid, paper, roadmap, node}) => renderCard(pid, paper, roadmap, node, contribOverride)).join('')}
        </div>
    </article>`;
}

function renderCard(pid, paper, roadmap, node, contribOverride) {
    const role = (roadmap && roadmap.role) || (node && node.role) || 'normal';
    const contribution = (contribOverride && contribOverride[pid]) || (roadmap && roadmap.contribution);
    const tag = rankTag(pid);
    return `<div class="card" data-role="${role}">
        <div class="card__head">
            <span class="card__year">${paper.year || '—'}</span>
            <span class="card__role" data-role="${role}">${escapeHtml(roleLabel(role))}</span>
        </div>
        <h3 class="card__title">${paperLink(paper.title || '(untitled)', paper)}</h3>
        ${contribution ? `<p class="card__contribution">${escapeHtml(contribution)}</p>` : ''}
        <div class="card__cites">${tag ? `<span class="card__tag">${tag}</span> · ` : ''}<b>${formatCites(paper.citation_count)}</b> ${escapeHtml(ui('cited'))}</div>
    </div>`;
}

function makeSpineTicks(period) {
    if (!period) return '';
    const m = period.match(/(\d{4}).*?(\d{4})/);
    if (!m) return '';
    const a = parseInt(m[1], 10), b = parseInt(m[2], 10);
    if (b < a) return '';
    const span = b - a;
    const step = span <= 2 ? 1 : Math.ceil(span / 4);
    const out = [];
    for (let y = a; y <= b; y += step) out.push(y);
    if (out[out.length - 1] !== b) out.push(b);
    return out.map(y => `<div class="spine__tick">${y}</div>`).join('');
}

// ============================================================
// Marginalia rail (AI trace)
// ============================================================

function setupRail(data) {
    const trace = data.trace || [];
    const toggle = document.querySelector('.rail-toggle');
    const rail = document.querySelector('.rail');
    const closeBtn = document.querySelector('.rail__close');
    const traceHost = document.querySelector('.trace');
    const railTitle = document.querySelector('.rail__title b');
    const railSub = document.querySelector('.rail__sub');
    const toggleLabel = document.querySelector('.rail-toggle__label');
    const countEl = document.querySelector('.rail-toggle__count');

    if (toggleLabel) toggleLabel.textContent = ui('authors_notes');
    if (railTitle) railTitle.textContent = ui('marginalia');

    if (data.agentic && trace.length) {
        countEl.textContent = trace.length;
        railSub.textContent = `${trace.length} ${ui('events')} · ${countAgents(trace)} ${ui('agents')}`;
        traceHost.innerHTML = trace.map(renderTraceItem).join('');
    } else {
        toggle.style.background = 'var(--ink-soft)';
        toggle.style.borderColor = 'var(--ink-soft)';
        countEl.textContent = ui('method').toUpperCase();
        if (railTitle) railTitle.textContent = ui('method');
        railSub.textContent = ui('deterministic_no_trace');
        traceHost.innerHTML = renderMethodologyFallback(data);
    }

    // Re-bind listeners (idempotent: clone to remove existing listeners on re-render)
    const newToggle = toggle.cloneNode(true);
    toggle.parentNode.replaceChild(newToggle, toggle);
    const newClose = closeBtn.cloneNode(true);
    closeBtn.parentNode.replaceChild(newClose, closeBtn);

    newToggle.addEventListener('click', () => {
        rail.classList.add('open');
        document.body.classList.add('rail-open');
        newClose.focus();
    });
    newClose.addEventListener('click', closeRail);
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && rail.classList.contains('open')) closeRail();
    });

    function closeRail() {
        rail.classList.remove('open');
        document.body.classList.remove('rail-open');
        newToggle.focus();
    }

    if (new URLSearchParams(location.search).get('rail') === '1') {
        rail.classList.add('open');
        document.body.classList.add('rail-open');
    }
}

function renderTraceItem(ev) {
    const caption = traceCaption(ev);
    const detail = traceDetail(ev);
    const cls = `trace__item trace__item--${ev.type}`;
    return `<li class="${cls}">
        <div class="trace__head">
            <span class="trace__agent">${escapeHtml(ev.agent)}</span>
            <span class="trace__type">${escapeHtml(ev.type)}</span>
        </div>
        <div class="trace__caption">${escapeHtml(caption)}</div>
        ${detail ? `<code class="trace__detail">${escapeHtml(detail)}</code>` : ''}
    </li>`;
}

function traceCaption(ev) {
    const c = ev.content;
    switch (ev.type) {
        case 'thought':
            return typeof c === 'string' ? c : JSON.stringify(c);
        case 'action':
            if (c && typeof c === 'object' && c.tool) {
                const args = c.args && Object.values(c.args)[0];
                return args ? `Calling ${c.tool}(${truncate(String(args), 40)})` : `Calling ${c.tool}`;
            }
            return typeof c === 'string' ? c : JSON.stringify(c);
        case 'observation':
            return typeof c === 'string' ? truncate(c.split('\n')[0], 90) : JSON.stringify(c);
        case 'verify': {
            if (c && typeof c === 'object') {
                const verdict = c.verdict ? 'upheld' : 'refuted';
                return `Verdict ${verdict} · ${c.support}/${c.n} reviewers agreed`;
            }
            return String(c);
        }
        case 'self_correct':
            return typeof c === 'string' ? c : JSON.stringify(c);
        case 'consistency':
            if (Array.isArray(c)) return c.length ? c.join('; ') : 'Consistency check passed.';
            return c === 'ok' ? 'Consistency check passed.' : String(c);
        case 'finish':
            return 'Agent finished.';
        case 'note':
            return typeof c === 'string' ? c : (c && c.final_founding ? `Final founding: ${c.final_founding.map(shortId).join(', ')}` : JSON.stringify(c));
        case 'error':
            return typeof c === 'string' ? c : JSON.stringify(c);
        default:
            return typeof c === 'string' ? c : JSON.stringify(c);
    }
}

function traceDetail(ev) {
    if (ev.type === 'action' && ev.content && typeof ev.content === 'object') {
        return JSON.stringify(ev.content.args || {});
    }
    if (ev.type === 'observation' && typeof ev.content === 'string') {
        const lines = ev.content.split('\n').slice(0, 3).join('\n');
        if (lines.length > 90) return truncate(lines, 240);
    }
    if (ev.type === 'verify' && ev.content && ev.content.claim) {
        return truncate(ev.content.claim, 180);
    }
    return '';
}

function countAgents(trace) {
    return new Set(trace.map(e => e.agent)).size;
}

function renderMethodologyFallback(data) {
    const items = STATE.lang === 'zh' ? [
        ['Resolve / 解析', '把输入解析为关键词或论文标识，从 OpenAlex 拉取种子论文。'],
        ['Collect / 建图', `双向 BFS 在 ${data.graph.nodes.length} 篇论文与 ${data.graph.edges.length} 条引用上构建图。`],
        ['Score / 打分', 'PageRank、中介中心性与入度共同决定每个节点的重要度。'],
        ['Founding / 奠基', '综合分预筛 → LLM 读摘要复核，选出真正开创领域的论文。'],
        ['Filter / 精筛', '中心度排名前 40 进入候选池，LLM 选出关键论文、贴上角色与演进边。'],
        ['Synthesize / 综述', '阶段、必读、研究空白基于精筛后的关键论文集合生成。'],
    ] : [
        ['Resolve', 'Parsed your query as keywords or a paper identifier; pulled the seed work from OpenAlex.'],
        ['Collect', `Two-way breadth-first search built a graph of ${data.graph.nodes.length} works across ${data.graph.edges.length} real citations.`],
        ['Score', 'PageRank, betweenness and in-degree gave every node a centrality budget.'],
        ['Locate founding', 'Top candidates ranked by 0.45·pagerank + 0.30·citation count + 0.25·age, then refined by an abstract-reading LLM.'],
        ['Filter', '40 most central works became the LLM\'s candidate pool; key papers and roles emerged from there.'],
        ['Synthesize', 'Stages, must-reads and open problems were authored against the filtered set.'],
    ];
    return items.map(([k, v]) => `
        <li class="trace__item">
            <div class="trace__head">
                <span class="trace__agent">${escapeHtml(k)}</span>
                <span class="trace__type">step</span>
            </div>
            <div class="trace__caption">${escapeHtml(v)}</div>
        </li>`).join('');
}

// ============================================================
// Network appendix (vis-network, lazy)
// ============================================================

function setupNetwork(data) {
    const det = document.querySelector('details.network');
    // bind toggle once
    if (!det.dataset.bound) {
        det.dataset.bound = '1';
        det.addEventListener('toggle', () => {
            if (det.open && !det.dataset.rendered) {
                det.dataset.rendered = '1';
                renderNetwork(data);
            }
        });
    }

    if (new URLSearchParams(location.search).get('network') === '1' && !det.open) {
        det.open = true;
    }
    // If the appendix is already open (default), trigger the lazy render now —
    // the `toggle` event only fires on state change.
    if (det.open && !det.dataset.rendered) {
        det.dataset.rendered = '1';
        renderNetwork(data);
    }
}

function renderNetwork(data) {
    const container = document.querySelector('.network__frame');
    if (typeof vis === 'undefined') {
        container.innerHTML = '<p style="padding:24px;color:var(--ink-soft)">vis-network failed to load (offline?).</p>';
        return;
    }

    const EDGE_DEFAULT = 'rgba(91, 84, 72, 0.30)';
    const EDGE_OUT = '#8B2A1F';   // cites others — vermilion
    const EDGE_IN = '#1F4068';    // cited by others — Prussian blue
    const EDGE_FADE = 'rgba(91, 84, 72, 0.08)';

    const visNodes = (data.graph.nodes || []).map(n => {
        const p = data.graph.papers[n.paper_id] || {};
        const tag = rankTag(n.paper_id);
        const cited = ui('cited');
        const dblHint = paperUrl(p)
            ? (STATE.lang === 'zh' ? '\n（双击打开原文）' : '\n(double-click to open)')
            : '';
        return {
            id: n.paper_id,
            label: tag || ' ',
            value: 4 + (n.metrics.pagerank || 0) * 400,
            color: {
                background: '#F7F3EA',
                border: ROLE_COLORS[n.role] || ROLE_COLORS.normal,
                highlight: { background: '#FBF8F0', border: '#1A1814' },
                hover: { background: '#FBF8F0', border: '#1A1814' },
            },
            font: { size: 11, face: 'JetBrains Mono, ui-monospace', color: '#1A1814', strokeWidth: 0 },
            title: `${tag ? tag + '  ' : ''}${n.title}\n${p.year || '—'} · ${cited} ${formatCites(p.citation_count)}× · ${n.role || 'normal'}${dblHint}`,
        };
    });

    const visEdges = (data.graph.edges || []).map((e, i) => ({
        id: `e${i}`,
        from: e.source,
        to: e.target,
        color: { color: EDGE_DEFAULT, highlight: '#1A1814', hover: '#1A1814' },
        width: 0.6, smooth: false,
        arrows: { to: { enabled: true, scaleFactor: 0.35 } },
    }));

    const nodesDs = new vis.DataSet(visNodes);
    const edgesDs = new vis.DataSet(visEdges);

    const network = new vis.Network(container, { nodes: nodesDs, edges: edgesDs }, {
        nodes: { shape: 'dot', scaling: { min: 4, max: 36 }, borderWidth: 1.5 },
        edges: { selectionWidth: 1.4 },
        physics: { stabilization: { iterations: 280 }, barnesHut: { gravitationalConstant: -7200, springLength: 110 } },
        interaction: { hover: true, tooltipDelay: 120, hideEdgesOnDrag: false },
    });

    function highlight(pid) {
        const updates = [];
        edgesDs.forEach(e => {
            let color;
            if (e.from === pid)      color = EDGE_OUT;   // pid cites someone (outgoing)
            else if (e.to === pid)   color = EDGE_IN;    // pid is cited (incoming)
            else                     color = EDGE_FADE;  // unrelated, fade away
            updates.push({ id: e.id, color: { color, highlight: color, hover: color }, width: (e.from === pid || e.to === pid) ? 1.6 : 0.4 });
        });
        edgesDs.update(updates);
    }

    function clearHighlight() {
        const updates = [];
        edgesDs.forEach(e => {
            updates.push({ id: e.id, color: { color: EDGE_DEFAULT, highlight: '#1A1814', hover: '#1A1814' }, width: 0.6 });
        });
        edgesDs.update(updates);
    }

    network.on('hoverNode', (params) => highlight(params.node));
    network.on('blurNode', () => clearHighlight());
    network.on('selectNode', (params) => { if (params.nodes[0]) highlight(params.nodes[0]); });
    network.on('deselectNode', () => clearHighlight());
    network.on('doubleClick', (params) => {
        const pid = params.nodes && params.nodes[0];
        if (!pid) return;
        const paper = (data.graph.papers || {})[pid];
        const href = paperUrl(paper);
        if (href) window.open(href, '_blank', 'noopener');
    });

    // render the legend once
    const legendHost = document.querySelector('.network__legend');
    if (legendHost) legendHost.innerHTML = renderNetworkLegend();
}

function renderNetworkLegend() {
    const out = (STATE.lang === 'zh') ? '出边（引用他人）' : 'out (cites others)';
    const inn = (STATE.lang === 'zh') ? '入边（被引用）' : 'in (cited by)';
    const hint = (STATE.lang === 'zh')
        ? '悬停或点选 · 编号见引用索引 · 双击节点打开原文'
        : 'hover or click · numbers match the citation index · double-click a node to open it';
    return `
        <span class="legend__swatch" style="background:#8B2A1F"></span><span>${escapeHtml(out)}</span>
        <span class="legend__swatch" style="background:#1F4068"></span><span>${escapeHtml(inn)}</span>
        <span class="legend__hint">${escapeHtml(hint)}</span>`;
}

// ============================================================
// helpers
// ============================================================

function shortId(id) { return id ? id.toString() : ''; }
function rankTag(pid) {
    const r = STATE.ranks && STATE.ranks[pid];
    if (!r) return '';
    return `[${String(r).padStart(2, '0')}]`;
}
function truncate(s, n) { return (s || '').length > n ? s.slice(0, n - 1) + '…' : (s || ''); }
function formatCites(n) {
    if (n == null) return '—';
    if (n >= 1000) return (n / 1000).toFixed(1).replace(/\.0$/, '') + 'k';
    return String(n);
}
function statBox(value, label) {
    return `<span><b>${value}</b>${escapeHtml(label)}</span>`;
}
function escapeHtml(s) {
    if (s == null) return '';
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

// Pick the best URL for a paper, preferring open-access reading over identifier pages.
// arxiv_url and pdf_url are direct reading links (added in schema 1.3.0; absent on older runs);
// doi resolves through doi.org; url falls back to the OpenAlex landing page.
function paperUrl(paper) {
    if (!paper) return '';
    const arxiv = paper.arxiv_url;
    if (arxiv) return arxiv;
    const pdf = paper.pdf_url;
    if (pdf) return pdf;
    const doi = paper.doi;
    if (doi) return /^https?:\/\//i.test(doi) ? doi : `https://doi.org/${doi.replace(/^doi:/i, '')}`;
    return paper.url || '';
}

function urlKind(paper) {
    // Returns a short hint shown in tooltips so the reader knows where the link goes.
    if (!paper) return '';
    if (paper.arxiv_url) return 'arXiv';
    if (paper.pdf_url)   return 'PDF';
    if (paper.doi)       return 'DOI';
    if (paper.url)       return 'OpenAlex';
    return '';
}

// Wrap a piece of text in an <a> that opens the paper's URL in a new tab.
// When no URL is available we degrade to a plain span so layout stays identical.
function paperLink(text, paper, extraClass) {
    const safe = escapeHtml(text);
    const href = paperUrl(paper);
    const cls = `paper-link${extraClass ? ' ' + extraClass : ''}`;
    if (!href) return `<span class="${cls} paper-link--inert">${safe}</span>`;
    const kind = urlKind(paper);
    const tip = kind ? ` (${kind})` : '';
    const titleLabel = STATE.lang === 'zh' ? `打开${kind ? '：' + kind : '原文'}` : `Open${tip}`;
    return `<a class="${cls}" href="${escapeHtml(href)}" target="_blank" rel="noopener" title="${escapeHtml(titleLabel)}">${safe}</a>`;
}
function computeYearRange(data) {
    const years = (data.graph.nodes || []).map(n => n.year).filter(Boolean);
    if (!years.length) return null;
    return [Math.min(...years), Math.max(...years)];
}
function isoMonth(lang) {
    const d = new Date();
    if (lang === 'zh') return `${d.getFullYear()} 年 ${d.getMonth() + 1} 月`;
    const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    return `${months[d.getMonth()]} ${d.getFullYear()}`;
}

function wrapTitle(s) {
    if (!s) return '';
    // Latin titles look much better in small caps treatment; Chinese queries (Han chars
    // present) read better without uppercase. Detect cheaply.
    const hasHan = /[\u4e00-\u9fff]/.test(s);
    return escapeHtml(hasHan ? s : s.toUpperCase());
}
