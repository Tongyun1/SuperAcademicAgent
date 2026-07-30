/* Variant 01 · Newspaper — renderer (bilingual: en / zh) */

// All UI labels used by the Newspaper variant. `result.i18n.zh.ui[key]` (if the
// backend translated it) wins over the bundled zh value, which wins over the en.
const NP_EN = {
    sec_brief: 'In Brief',
    sec_brief_sub: 'A one-minute orientation',
    the_story: 'The Story',
    sec_founding: 'Founding works',
    sec_founding_sub: 'Where it all began',
    sec_stages: 'Stages of the field',
    sec_stages_sub: 'How the lineage unfolded',
    sec_roadmap: 'The roadmap',
    sec_roadmap_sub: 'Key papers, in order',
    sec_app: 'Reading apparatus',
    sec_app_sub: 'For the complete beginner',
    sec_net: 'Citation network',
    sec_net_sub: 'Node size ∝ PageRank · double-click to open paper',
    by_numbers: 'By the numbers',
    must_read: 'Must read',
    prereq: 'Prerequisites',
    start: 'Getting started',
    reading_path: 'Reading path',
    no_tldr: 'No one-minute summary available.',
    no_founding: 'No founding paper identified.',
    no_stages: 'No stages.',
    no_roadmap: 'No roadmap.',
    no_prereq: 'No prerequisites listed.',
    no_start: 'No getting-started steps.',
    no_path: 'No reading path.',
    no_gap: 'No open problems generated.',
    no_must: 'No must-reads.',
    founding_role: 'founding',
    untitled: '(untitled)',
    authors_unknown: 'Authors unknown',
    citations: 'citations',
    cited: 'cited',
    papers: 'papers',
    span: 'Span',
    stages_key: 'Stages',
    roadmap_key: 'Roadmap',
    founding_key: 'Founding',
    papers_key: 'Papers',
    citations_key: 'Citations',
    nav_brief: 'In Brief',
    nav_founding: 'Founding',
    nav_stages: 'Stages',
    nav_roadmap: 'Roadmap',
    nav_apparatus: 'Apparatus',
    nav_open: 'Open Problems',
    nav_network: 'Network',
    nav_seed: 'Your Paper',
    sec_seed: 'The paper you asked about',
    sec_seed_sub: 'How this specific work sits in the field',
    seed_on_main_line: 'On the main line',
    seed_off_main_line: 'A branch of the field',
    seed_relation_heading: 'How it relates to the main line',
    seed_summary_heading: 'What this paper is',
    rm_th_year: 'Year',
    rm_th_role: 'Role',
    rm_th_title: 'Title',
    rm_th_contrib: 'Contribution',
    rm_th_cite: 'Cites',
    no_contrib: '—',
    lang_btn: '中文',
    title_suffix: '— SuperAcademicAISearch',
    colophon: 'Newspaper edition · typeset in Playfair Display + Source Serif 4 + JetBrains Mono · derived from <code>result.json</code> · Apache-2.0',
};

const NP_ZH = {
    sec_brief: '摘要',
    sec_brief_sub: '快速建立全局认识',
    the_story: '故事梗概',
    sec_founding: '奠基论文',
    sec_founding_sub: '一切的起点',
    sec_stages: '领域阶段',
    sec_stages_sub: '脉络如何展开',
    sec_roadmap: '关键路线',
    sec_roadmap_sub: '按时间顺序排列的关键论文',
    sec_app: '阅读指引',
    sec_app_sub: '写给完全不懂的人',
    sec_net: '引用网络',
    sec_net_sub: '节点大小 ∝ PageRank · 双击节点打开论文',
    by_numbers: '关键数字',
    must_read: '必读清单',
    prereq: '前置知识',
    start: '如何入手',
    reading_path: '推荐阅读顺序',
    no_tldr: '暂无摘要。',
    no_founding: '未识别出奠基论文。',
    no_stages: '暂无阶段划分。',
    no_roadmap: '暂无路线图。',
    no_prereq: '暂无前置知识。',
    no_start: '暂无入门步骤。',
    no_path: '暂无阅读顺序。',
    no_gap: '暂未生成研究空白。',
    no_must: '暂无必读清单。',
    founding_role: '奠基',
    untitled: '(无标题)',
    authors_unknown: '作者未知',
    citations: '次引用',
    cited: '次引用',
    papers: '篇论文',
    span: '年跨度',
    stages_key: '阶段',
    roadmap_key: '关键论文',
    founding_key: '奠基',
    papers_key: '论文',
    citations_key: '引用',
    nav_brief: '摘要',
    nav_founding: '奠基',
    nav_stages: '阶段',
    nav_roadmap: '路线',
    nav_apparatus: '指引',
    nav_open: '研究空白',
    nav_network: '网络',
    nav_seed: '您的论文',
    sec_seed: '您所问的论文',
    sec_seed_sub: '这篇论文在领域中的位置',
    seed_on_main_line: '位于主干',
    seed_off_main_line: '领域分支',
    seed_relation_heading: '与主干的关系',
    seed_summary_heading: '论文简介',
    rm_th_year: '年份',
    rm_th_role: '角色',
    rm_th_title: '论文标题',
    rm_th_contrib: '主要贡献',
    rm_th_cite: '引用',
    no_contrib: '—',
    lang_btn: 'EN',
    title_suffix: '— SuperAcademicAISearch',
    colophon: '评注版 · 排版采用 Playfair Display + Source Serif 4 + JetBrains Mono · 数据来自 <code>result.json</code> · Apache-2.0',
};

const ROLE_LABELS = {
    en: { founding: 'founding', breakthrough: 'breakthrough', improvement: 'improvement', branch: 'branch', survey: 'survey', normal: 'work' },
    zh: { founding: '奠基', breakthrough: '范式突破', improvement: '关键改进', branch: '分支开创', survey: '集大成综述', normal: '研究' },
};

let DATA = null;
let LANG = 'en';

document.addEventListener('DOMContentLoaded', async () => {
    try {
        DATA = await SAAS.loadData();
        LANG = SAAS.getLang();
        setupLangToggle();
        render();
    } catch (e) {
        const err = document.getElementById('np-error');
        err.hidden = false;
        err.textContent = 'Failed to load result.json: ' + e.message;
        console.error(e);
    }
});

function setupLangToggle() {
    const btn = document.getElementById('np-lang');
    if (!btn) return;
    btn.addEventListener('click', () => {
        LANG = (LANG === 'zh') ? 'en' : 'zh';
        SAAS.setLang(LANG);
        render();
    });
}

function t(key) {
    return SAAS.txUI(DATA, LANG, key, NP_EN, NP_ZH);
}
function roleLbl(role) {
    return (ROLE_LABELS[LANG] || ROLE_LABELS.en)[role || 'normal'] || ROLE_LABELS.en.normal;
}

function render() {
    const d = DATA;
    const papers = d.graph.papers;
    const ranks = SAAS.computeRanks(d.graph);
    const yr = SAAS.yearRange(d.graph);
    const stages = d.report.stages || [];
    const rmByPid = Object.fromEntries((d.roadmap.nodes || []).map(n => [n.paper_id, n]));
    const txContribOverride = SAAS.txMap(d, LANG, 'roadmap_contributions', {});

    // Model-composed academic/literary cover title; fall back to the raw query
    // (heuristic/degraded reports, or older result.json without a cover_title).
    // Reused for the browser tab title and the headline below.
    const coverTitle = SAAS.tx(d, LANG, 'cover_title', d.report.cover_title) || d.query || '';

    // ----- <html> lang + title -----
    document.documentElement.lang = LANG === 'zh' ? 'zh-CN' : 'en';
    document.title = `${coverTitle} ${t('title_suffix')}`;

    // ----- Masthead -----
    document.getElementById('np-date').textContent = isoDate(LANG);
    document.getElementById('np-lang').textContent = t('lang_btn');

    // ----- Sticky TOC labels -----
    const navMap = [
        ['#brief', 'nav_brief'], ['#seed', 'nav_seed'], ['#founding', 'nav_founding'], ['#stages', 'nav_stages'],
        ['#roadmap', 'nav_roadmap'], ['#apparatus', 'nav_apparatus'],
        ['#network', 'nav_network'],
    ];
    document.querySelectorAll('.np-toc__a').forEach((a, i) => {
        const m = navMap[i]; if (!m) return;
        a.textContent = t(m[1]);
    });

    // ----- Headline -----
    document.getElementById('np-kicker').textContent = 'Agent Analysis';
    const titleEl = document.getElementById('np-title');
    titleEl.textContent = coverTitle || '—';
    titleEl.classList.remove('np-h1--long', 'np-h1--xlong');
    const titleLen = (coverTitle || '').length;
    if (titleLen > 90) titleEl.classList.add('np-h1--xlong');
    else if (titleLen > 40) titleEl.classList.add('np-h1--long');
    const deck = SAAS.tx(d, LANG, 'cover_blurb', d.report.cover_blurb) || d.report.tldr || '';
    document.getElementById('np-deck').textContent = deck;
    document.getElementById('np-byline-stats').textContent =
        `${d.graph.nodes.length} ${t('papers')} · ${d.graph.edges.length} ${t('citations')} · ${yr ? yr[0] + '–' + yr[1] : '—'}`;

    // ----- Section headings -----
    setSection('.np-brief', t('sec_brief'), t('sec_brief_sub'));
    setSection('.np-seed', t('sec_seed'), t('sec_seed_sub'));
    setSection('.np-found', t('sec_founding'), t('sec_founding_sub'));
    setSection('.np-stages', t('sec_stages'), t('sec_stages_sub'));
    setSection('.np-roadmap', t('sec_roadmap'), t('sec_roadmap_sub'));
    setSection('.np-app', t('sec_app'), t('sec_app_sub'));
    setSection('.np-net', t('sec_net'), t('sec_net_sub'));

    // ----- I. In Brief (translations preferred when available) -----
    document.querySelector('.np-brief__tldr-label').textContent = t('the_story');
    const tldrText = SAAS.tx(d, LANG, 'tldr', d.report.tldr);
    document.getElementById('np-tldr').textContent = tldrText || t('no_tldr');
    const idea = document.getElementById('np-core-idea');
    const ideaText = SAAS.tx(d, LANG, 'core_idea', d.report.core_idea);
    if (ideaText) { idea.textContent = ideaText; idea.style.display = ''; }
    else idea.style.display = 'none';

    // sidebar stats label
    document.querySelectorAll('.np-side__label')[0].textContent = t('by_numbers');
    document.querySelectorAll('.np-side__label')[1].textContent = t('must_read');

    const statItems = [
        [t('papers_key'), d.graph.nodes.length],
        [t('citations_key'), d.graph.edges.length],
        [t('span'), yr ? `${yr[0]}–${yr[1]}` : '—'],
        [t('stages_key'), stages.length],
        [t('founding_key'), d.founding.length],
        [t('roadmap_key'), d.roadmap.nodes.length],
    ];
    document.getElementById('np-stats').innerHTML = statItems.map(([k, v]) =>
        `<div class="np-side__stat">
            <span class="np-side__stat-key">${SAAS.escapeHtml(k)}</span>
            <span class="np-side__stat-val">${SAAS.escapeHtml(String(v))}</span>
        </div>`).join('');

    const mustReads = d.report.must_read || [];
    document.getElementById('np-must').innerHTML = mustReads.map(pid => {
        const p = papers[pid] || {};
        return `<li>
            <span>${linkTitle(p, p.title)}</span>
            <span class="yr">${p.year || '—'} · ${SAAS.rankTag(ranks, pid)}</span>
        </li>`;
    }).join('') || `<li>${SAAS.escapeHtml(t('no_must'))}</li>`;

    // ----- II. Seed paper (the one the user asked about) -----
    const seedSection = document.getElementById('seed');
    const seed = d.report.seed_paper;
    const seedI18nCheck = (d.i18n && d.i18n[LANG] && d.i18n[LANG].seed_paper) || {};
    const hasSeedText = seed && ((seed.summary || '').trim() || (seed.relation_to_main_line || '').trim()
        || (seedI18nCheck.summary || '').trim() || (seedI18nCheck.relation_to_main_line || '').trim());
    if (seed && seed.paper_id && hasSeedText) {
        seedSection.hidden = false;
        const seedPaper = papers[seed.paper_id] || {};
        const seedTitle = seed.title || seedPaper.title || '';
        const seedYear = seed.year || seedPaper.year || '—';
        const roleKey = seed.role_in_field || 'normal';
        const roleLabel = (ROLE_LABELS[LANG] || ROLE_LABELS.en)[roleKey] || roleKey;
        const onMain = seed.on_main_line;
        const positionLabel = onMain ? t('seed_on_main_line') : t('seed_off_main_line');
        const stageName = seed.stage_name ? ` · ${SAAS.escapeHtml(seed.stage_name)}` : '';
        // i18n: prefer translated summary/relation from result.i18n.zh.seed_paper
        const seedI18n = (d.i18n && d.i18n[LANG] && d.i18n[LANG].seed_paper) || {};
        const summary = seedI18n.summary || seed.summary || '';
        const relation = seedI18n.relation_to_main_line || seed.relation_to_main_line || '';
        document.getElementById('np-seed-sub').textContent =
            `${positionLabel}${stageName}`;
        document.getElementById('np-seed-card').innerHTML = `
            <header class="np-seed__header">
                <div class="np-seed__meta">
                    ${seedYear} · <span class="np-seed__role">${SAAS.escapeHtml(roleLabel)}</span>
                    · ${SAAS.formatCites(seedPaper.citation_count || 0)} ${SAAS.escapeHtml(t('citations'))}
                </div>
                <h3 class="np-seed__title">${linkTitle(seedPaper, seedTitle)}</h3>
            </header>
            ${summary ? `
                <div class="np-seed__block">
                    <div class="np-seed__block-label">${SAAS.escapeHtml(t('seed_summary_heading'))}</div>
                    <p class="np-seed__block-body">${SAAS.escapeHtml(summary)}</p>
                </div>
            ` : ''}
            ${relation ? `
                <div class="np-seed__block">
                    <div class="np-seed__block-label">${SAAS.escapeHtml(t('seed_relation_heading'))}</div>
                    <p class="np-seed__block-body">${SAAS.escapeHtml(relation)}</p>
                </div>
            ` : ''}
        `;
    } else {
        seedSection.hidden = true;
    }

    // ----- III. Founding -----
    document.getElementById('np-found-grid').innerHTML = d.founding.map(pid => {
        const p = papers[pid] || {};
        const rm = rmByPid[pid];
        const contrib = txContribOverride[pid] || rm?.contribution || '';
        return `<article class="np-found-card">
            <div class="np-found-card__year">${p.year || '—'} · ${SAAS.escapeHtml(t('founding_role'))}</div>
            <h3 class="np-found-card__title">${linkTitle(p, p.title)}</h3>
            ${contrib ? `<p class="np-found-card__contrib">${SAAS.escapeHtml(contrib)}</p>` : ''}
            <div class="np-found-card__meta">
                ${SAAS.escapeHtml(SAAS.authorsShort(p, 3) || t('authors_unknown'))}
                · ${SAAS.formatCites(p.citation_count)} ${SAAS.escapeHtml(t('citations'))}
                · ${SAAS.rankTag(ranks, pid)}
            </div>
        </article>`;
    }).join('') || `<p>${SAAS.escapeHtml(t('no_founding'))}</p>`;

    // ----- III. Stages -----
    const ROMAN = ['I','II','III','IV','V','VI','VII','VIII','IX','X'];
    document.getElementById('np-stages-list').innerHTML = stages.map((s, idx) => {
        const sName = SAAS.txStage(d, LANG, idx, 'name', s.name);
        const sSummary = SAAS.txStage(d, LANG, idx, 'summary', s.summary);
        const cards = (s.papers || []).map(pid => paperCard(pid, papers, rmByPid, ranks, txContribOverride)).join('');
        return `<div class="np-stage">
            <div>
                <div class="np-stage__roman">${ROMAN[idx] || (idx + 1)}</div>
                <div class="np-stage__period">${SAAS.escapeHtml(s.period || '')}</div>
                <h3 class="np-stage__name">${SAAS.escapeHtml(sName || 'Stage')}</h3>
                <p class="np-stage__summary">${SAAS.escapeHtml(sSummary || '')}</p>
            </div>
            <div class="np-stage__cards">${cards || ''}</div>
        </div>`;
    }).join('') || `<p>${SAAS.escapeHtml(t('no_stages'))}</p>`;

    // ----- IV. Roadmap (table) -----
    // Sync header text with current language
    const rmTable = document.getElementById('np-rm-table');
    if (rmTable) {
        const ths = rmTable.querySelectorAll('thead th');
        ths[0].textContent = t('rm_th_year');
        ths[1].textContent = t('rm_th_role');
        ths[2].textContent = t('rm_th_title');
        ths[3].textContent = t('rm_th_contrib');
        ths[4].textContent = t('rm_th_cite');
    }
    const rmSorted = (d.roadmap.nodes || []).slice().sort((a, b) => (a.year || 0) - (b.year || 0));
    const rmBody = rmTable?.querySelector('tbody');
    if (rmBody) {
        rmBody.innerHTML = rmSorted.map(n => {
            const p = papers[n.paper_id] || {};
            const role = n.role || 'normal';
            const contrib = (txContribOverride && txContribOverride[n.paper_id]) || n.contribution || '';
            return `<tr>
                <td class="np-rm-yr">${n.year || '—'}</td>
                <td><span class="np-role-pill" data-role="${SAAS.escapeHtml(role)}">${SAAS.escapeHtml(roleLbl(role))}</span></td>
                <td class="np-rm-t">${linkTitle(p, n.title)}</td>
                <td class="np-rm-c">${contrib ? SAAS.escapeHtml(contrib) : SAAS.escapeHtml(t('no_contrib'))}</td>
                <td class="np-rm-cite">${SAAS.formatCites(p.citation_count)}</td>
            </tr>`;
        }).join('') || `<tr><td colspan="5" class="np-rm-empty">${SAAS.escapeHtml(t('no_roadmap'))}</td></tr>`;
    }

    // ----- V. Apparatus (4 cards: prereq | start | path | open problems) -----
    const appLabels = document.querySelectorAll('.np-app__label');
    appLabels[0].textContent = t('prereq');
    appLabels[1].textContent = t('start');
    appLabels[2].textContent = t('reading_path');
    appLabels[3].textContent = t('nav_open');

    const prereqList = SAAS.txList(d, LANG, 'prerequisites', d.report.prerequisites || []);
    document.getElementById('np-prereq').innerHTML =
        prereqList.map(x => `<li>${SAAS.escapeHtml(x)}</li>`).join('')
        || `<li>${SAAS.escapeHtml(t('no_prereq'))}</li>`;
    const startList = SAAS.txList(d, LANG, 'getting_started', d.report.getting_started || []);
    document.getElementById('np-start').innerHTML =
        startList.map(x => `<li>${SAAS.escapeHtml(x)}</li>`).join('')
        || `<li>${SAAS.escapeHtml(t('no_start'))}</li>`;
    document.getElementById('np-path').innerHTML = (d.report.reading_path || []).map(pid => {
        const p = papers[pid] || {};
        return `<li>${linkTitle(p, p.title)} <span class="yr"> · ${p.year || '—'}</span></li>`;
    }).join('') || `<li>${SAAS.escapeHtml(t('no_path'))}</li>`;
    const gaps = SAAS.txList(d, LANG, 'gaps', d.report.gaps || []);
    document.getElementById('np-gaps').innerHTML =
        gaps.map(g => `<li>${SAAS.escapeHtml(g)}</li>`).join('')
        || `<li>${SAAS.escapeHtml(t('no_gap'))}</li>`;

    // ----- VI. Network (lazy, render once) -----
    const netFrame = document.getElementById('np-net-frame');
    if (!netFrame.dataset.rendered) {
        const tryNet = () => {
            if (typeof vis !== 'undefined') {
                SAAS.setupNetwork(netFrame, d, ranks);
                netFrame.dataset.rendered = '1';
            } else setTimeout(tryNet, 300);
        };
        if ('IntersectionObserver' in window) {
            const io = new IntersectionObserver((ents) => {
                ents.forEach(e => { if (e.isIntersecting) { tryNet(); io.disconnect(); } });
            }, { rootMargin: '200px' });
            io.observe(netFrame);
        } else { tryNet(); }
    }

    // ----- Citation index (all nodes, ordered by importance) -----
    const topByPR = (d.graph.nodes || []).slice()
        .sort((a, b) => (b.metrics?.pagerank || 0) - (a.metrics?.pagerank || 0));
    document.getElementById('np-net-index').innerHTML = topByPR.map(n => {
        const p = papers[n.paper_id] || {};
        return `<div class="np-idx__item">
            <span class="np-idx__id">${SAAS.rankTag(ranks, n.paper_id)}</span>
            <span>${linkTitle(p, p.title)}</span>
            <span class="np-idx__meta">${SAAS.escapeHtml(SAAS.authorsShort(p) || '—')} · ${p.year || '—'} · ${SAAS.escapeHtml(t('cited'))} ${SAAS.formatCites(p.citation_count)}× · PR ${(n.metrics?.pagerank || 0).toFixed(3)}</span>
        </div>`;
    }).join('');

    // ----- Colophon -----
    const col = document.querySelector('.np-colophon');
    if (col) col.innerHTML = `<b>SuperAcademicAISearch</b> · ${t('colophon')}`;

    // ----- Scroll-spy (idempotent enough; IO observers will re-attach harmlessly) -----
    SAAS.scrollSpy('.np-toc__a', '.np-section', 'is-active');
}

function setSection(rootSel, title, sub) {
    const root = document.querySelector(rootSel);
    if (!root) return;
    const t = root.querySelector('.np-section__title');
    const s = root.querySelector('.np-section__sub');
    if (t) t.textContent = title;
    if (s) s.textContent = sub;
}

function paperCard(pid, papers, rmByPid, ranks, contribOverride) {
    const p = papers[pid] || {};
    const rm = rmByPid[pid];
    const role = rm?.role || 'normal';
    const contrib = (contribOverride && contribOverride[pid]) || rm?.contribution || '';
    return `<article class="np-card" data-role="${SAAS.escapeHtml(role)}">
        <div class="np-card__hd">
            <span class="np-card__year">${p.year || '—'}</span>
            <span class="np-card__role">${SAAS.escapeHtml(roleLbl(role))}</span>
        </div>
        <h4 class="np-card__title">${linkTitle(p, p.title)}</h4>
        ${contrib ? `<p class="np-card__contrib">${SAAS.escapeHtml(contrib)}</p>` : ''}
        <div class="np-card__cite">${SAAS.rankTag(ranks, pid)} · <b>${SAAS.formatCites(p.citation_count)}</b> ${SAAS.escapeHtml(t('cited'))}</div>
    </article>`;
}

function linkTitle(paper, text) {
    const url = SAAS.paperUrl(paper);
    const safe = SAAS.escapeHtml(text || t('untitled'));
    if (url) return `<a href="${SAAS.escapeHtml(url)}" target="_blank" rel="noopener">${safe}</a>`;
    return safe;
}

function isoDate(lang) {
    const d = new Date();
    if (lang === 'zh') return `${d.getFullYear()} 年 ${d.getMonth() + 1} 月 ${d.getDate()} 日`;
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }).toUpperCase();
}
