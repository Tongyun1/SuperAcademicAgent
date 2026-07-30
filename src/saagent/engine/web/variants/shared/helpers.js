/* Shared helpers for all 5 frontend variants.
   Each variant loads this as a classic <script>, exposing window.SAAS.* */
(function () {
    const ROLE_COLORS = {
        founding: '#8B2A1F',
        breakthrough: '#B85C2F',
        improvement: '#3F6B47',
        branch: '#1F4068',
        survey: '#6B4F8B',
        normal: '#9A9080',
    };

    const ROLE_LABELS_EN = {
        founding: 'founding', breakthrough: 'breakthrough', improvement: 'improvement',
        branch: 'branch', survey: 'survey', normal: 'work',
    };

    async function loadData(url) {
        url = url || './result.json';
        // Allow `?data=...` override for ad-hoc previews
        const q = new URLSearchParams(location.search).get('data');
        if (q) url = q;
        const r = await fetch(url, { cache: 'no-store' });
        if (!r.ok) throw new Error(`HTTP ${r.status} loading ${url}`);
        const data = await r.json();
        return normalize(data);
    }

    function normalize(d) {
        d.graph = d.graph || { nodes: [], edges: [], papers: {} };
        d.graph.nodes = d.graph.nodes || [];
        d.graph.edges = d.graph.edges || [];
        d.graph.papers = d.graph.papers || {};
        d.roadmap = d.roadmap || { nodes: [], edges: [] };
        d.roadmap.nodes = d.roadmap.nodes || [];
        d.roadmap.edges = d.roadmap.edges || [];
        d.founding = d.founding || [];
        d.report = d.report || {};
        const r = d.report;
        r.stages = r.stages || [];
        r.main_line = r.main_line || [];
        r.gaps = r.gaps || [];
        r.reading_path = r.reading_path || [];
        r.must_read = r.must_read || [];
        r.must_read_reasons = r.must_read_reasons || {};
        r.prerequisites = r.prerequisites || [];
        r.glossary = r.glossary || {};
        r.getting_started = r.getting_started || [];
        return d;
    }

    function escapeHtml(s) {
        if (s == null) return '';
        return String(s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function formatCites(n) {
        if (n == null) return '—';
        if (n >= 1000) return (n / 1000).toFixed(1).replace(/\.0$/, '') + 'k';
        return String(n);
    }

    function computeRanks(graph) {
        // [NN] tag by network-wide PageRank desc — used as a stable cross-reference id
        const sorted = (graph.nodes || []).slice().sort(
            (a, b) => (b.metrics?.pagerank || 0) - (a.metrics?.pagerank || 0));
        const out = {};
        sorted.forEach((n, i) => { out[n.paper_id] = i + 1; });
        return out;
    }

    function rankTag(ranks, pid) {
        const r = ranks[pid];
        return r ? `[${String(r).padStart(2, '0')}]` : '';
    }

    function yearRange(graph) {
        const years = (graph.nodes || []).map(n => n.year).filter(Boolean);
        if (!years.length) return null;
        return [Math.min(...years), Math.max(...years)];
    }

    function roleColor(role) { return ROLE_COLORS[role] || ROLE_COLORS.normal; }
    function roleLabel(role) { return ROLE_LABELS_EN[role] || 'work'; }

    function paperUrl(paper) {
        // Best link for a paper — prefer arxiv > doi > openalex
        if (!paper) return '';
        return paper.arxiv_url || paper.pdf_url || paper.doi || paper.url || '';
    }

    function authorsShort(paper, max) {
        max = max || 2;
        const a = paper?.authors || [];
        if (!a.length) return '';
        const head = a.slice(0, max).join(', ');
        return a.length > max ? head + ' et al.' : head;
    }

    function setupNetwork(container, data, ranks) {
        try {
            return _setupNetworkImpl(container, data, ranks);
        } catch (e) {
            // Canvas may be unavailable (e.g. jsdom test environment). Fall back
            // to a placeholder so the rest of render() keeps going.
            if (container) container.innerHTML = '<p class="net-fallback">Network render unavailable (' + (e && e.message ? e.message : 'error') + ')</p>';
            return null;
        }
    }

    function _setupNetworkImpl(container, data, ranks) {
        if (typeof vis === 'undefined') {
            container.innerHTML = '<p class="net-fallback">vis-network not loaded (offline?)</p>';
            return null;
        }
        const mustReadSet = new Set(data.report?.must_read || []);
        const firstSeed = (data.graph?.seeds || [])[0];
        const seedSet = firstSeed ? new Set([firstSeed]) : new Set();
        const visNodes = (data.graph.nodes || []).map(n => {
            const p = data.graph.papers[n.paper_id] || {};
            let label = rankTag(ranks, n.paper_id) || ' ';
            const isSeed = seedSet.has(n.paper_id);
            const isMustRead = mustReadSet.has(n.paper_id);
            if (isSeed) label += '\n◆你查询的论文';
            if (isMustRead) label += '\n★必读论文';
            return {
                id: n.paper_id,
                label: label,
                value: 4 + (n.metrics?.pagerank || 0) * 400,
                color: {
                    background: isSeed ? '#FFF3E0' : isMustRead ? '#E8F5E9' : '#F7F3EA',
                    border: isSeed ? '#E65100' : isMustRead ? '#2E7D32' : roleColor(n.role),
                    highlight: { background: '#FBF8F0', border: '#1A1814' },
                    hover: { background: '#FBF8F0', border: '#1A1814' },
                },
                borderWidth: (isSeed || isMustRead) ? 2.5 : 1.5,
                font: { size: 11, face: 'JetBrains Mono, ui-monospace', color: '#1A1814', multi: 'md' },
                title: `${n.title}\n${p.year || '—'} · cited ${formatCites(p.citation_count)} · ${n.role || 'normal'}`,
            };
        });
        const defaultEdgeColor = 'rgba(30, 28, 24, 0.3)';
        const outgoingColor = '#1565C0';  // blue: this node cites others
        const incomingColor = '#E65100';  // orange: others cite this node
        const visEdges = (data.graph.edges || []).map((e, i) => ({
            id: `e${i}`, from: e.source, to: e.target,
            color: { color: defaultEdgeColor, highlight: defaultEdgeColor, hover: defaultEdgeColor },
            width: 0.7, smooth: false,
            arrows: { to: { enabled: true, scaleFactor: 0.4, type: 'arrow' } },
        }));
        const edgeDS = new vis.DataSet(visEdges);
        const net = new vis.Network(container,
            { nodes: new vis.DataSet(visNodes), edges: edgeDS },
            {
                nodes: { shape: 'dot', scaling: { min: 4, max: 36 }, borderWidth: 1.5 },
                edges: { selectionWidth: 1.5 },
                physics: { stabilization: { iterations: 250 }, barnesHut: { gravitationalConstant: -7200, springLength: 110 } },
                interaction: { hover: true, tooltipDelay: 120 },
            });

        // Build edge lookup for fast hover coloring
        const edgesByNode = {};  // nodeId -> [{edgeId, direction: 'out'|'in'}]
        (data.graph.edges || []).forEach((e, i) => {
            const eid = `e${i}`;
            if (!edgesByNode[e.source]) edgesByNode[e.source] = [];
            if (!edgesByNode[e.target]) edgesByNode[e.target] = [];
            edgesByNode[e.source].push({ id: eid, direction: 'out' });
            edgesByNode[e.target].push({ id: eid, direction: 'in' });
        });

        net.on('hoverNode', (params) => {
            const nodeId = params.node;
            const connected = edgesByNode[nodeId] || [];
            const updates = connected.map(({ id, direction }) => ({
                id,
                color: {
                    color: direction === 'out' ? outgoingColor : incomingColor,
                    highlight: direction === 'out' ? outgoingColor : incomingColor,
                    hover: direction === 'out' ? outgoingColor : incomingColor,
                },
                width: 1.5,
            }));
            if (updates.length) edgeDS.update(updates);
        });

        net.on('blurNode', () => {
            const allEdges = edgeDS.get();
            const resets = allEdges.map(e => ({
                id: e.id,
                color: { color: defaultEdgeColor, highlight: defaultEdgeColor, hover: defaultEdgeColor },
                width: 0.7,
            }));
            edgeDS.update(resets);
        });

        net.on('doubleClick', (params) => {
            if (params.nodes[0]) {
                const p = data.graph.papers[params.nodes[0]];
                const url = paperUrl(p);
                if (url) window.open(url, '_blank');
            }
        });
        return net;
    }

    // ----- i18n helpers (used by variants that expose a lang toggle) ---------
    // The result.json may contain {i18n: {zh: {cover_blurb, narrative, gaps,
    // must_read_reasons, stages, roadmap_contributions, ui}}}. Fields missing
    // from i18n.zh fall back to the English value. Glossary / tldr / core_idea
    // / prerequisites / getting_started are not yet translated by the backend
    // — these will simply stay in English when lang=zh, which is acceptable.
    function getLang() {
        try {
            const q = new URLSearchParams(location.search).get('lang');
            if (q === 'zh' || q === 'en') return q;
            const stored = localStorage.getItem('saas.lang');
            if (stored === 'zh' || stored === 'en') return stored;
        } catch (e) {}
        return 'en';
    }
    function setLang(lang) {
        try { localStorage.setItem('saas.lang', lang); } catch (e) {}
    }
    function _zh(data) {
        return (data && data.i18n && data.i18n.zh) || null;
    }
    function tx(data, lang, field, fallback) {
        if (lang === 'zh') {
            const z = _zh(data);
            if (z && typeof z[field] === 'string' && z[field].trim()) return z[field];
        }
        return fallback;
    }
    function txList(data, lang, field, fallback) {
        if (lang === 'zh') {
            const z = _zh(data);
            if (z && Array.isArray(z[field]) && z[field].length) return z[field];
        }
        return fallback || [];
    }
    function txMap(data, lang, field, fallback) {
        // Merge zh map onto fallback so untranslated keys still display English.
        if (lang === 'zh') {
            const z = _zh(data);
            if (z && z[field] && typeof z[field] === 'object') {
                return Object.assign({}, fallback || {}, z[field]);
            }
        }
        return fallback || {};
    }
    function txStage(data, lang, idx, field, fallback) {
        // Each translated stage is matched back to its source by paper_id_anchor
        // = `stage_<idx>`; fall back to index if missing.
        if (lang === 'zh') {
            const z = _zh(data);
            const stages = z && Array.isArray(z.stages) ? z.stages : null;
            if (stages) {
                const s = stages.find(x => x && x.paper_id_anchor === `stage_${idx}`) || stages[idx];
                if (s && typeof s[field] === 'string' && s[field].trim()) return s[field];
            }
        }
        return fallback;
    }
    function txUI(data, lang, key, baseEN, baseZH) {
        // UI labels: prefer translated value from result.i18n.zh.ui[key],
        // else the bundled zh label, else English.
        if (lang === 'zh') {
            const z = _zh(data);
            if (z && z.ui && typeof z.ui[key] === 'string' && z.ui[key].trim()) return z.ui[key];
            if (baseZH && typeof baseZH[key] === 'string') return baseZH[key];
        }
        return (baseEN && baseEN[key]) || key;
    }

    function scrollSpy(linkSelector, sectionSelector, activeCls) {
        // Highlight nav links as their target section enters view. Idempotent.
        if (typeof IntersectionObserver === 'undefined') return;
        const links = Array.from(document.querySelectorAll(linkSelector));
        const sections = Array.from(document.querySelectorAll(sectionSelector));
        if (!links.length || !sections.length) return;
        activeCls = activeCls || 'is-active';
        const byId = Object.fromEntries(links.map(a => [a.getAttribute('href')?.slice(1), a]));
        const io = new IntersectionObserver((entries) => {
            entries.forEach(en => {
                const id = en.target.id;
                if (!byId[id]) return;
                if (en.isIntersecting) {
                    links.forEach(a => a.classList.remove(activeCls));
                    byId[id].classList.add(activeCls);
                }
            });
        }, { rootMargin: '-40% 0px -55% 0px', threshold: 0 });
        sections.forEach(s => io.observe(s));
    }

    window.SAAS = {
        loadData, escapeHtml, formatCites, computeRanks, rankTag,
        yearRange, roleColor, roleLabel, paperUrl, authorsShort,
        setupNetwork, scrollSpy, ROLE_COLORS,
        getLang, setLang, tx, txList, txMap, txStage, txUI,
    };
})();
