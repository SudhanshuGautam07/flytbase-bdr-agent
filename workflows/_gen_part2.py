

# --------------------------------------------------------------------------
# Agent prompts
# --------------------------------------------------------------------------

ICP_SYSTEM = """You are the ICP Intelligence Agent in a multi-agent BDR research system for FlytBase (category leader in Physical AI: autonomous drone inspection for large industrial sites).
You receive a campaign brief plus fetched public context about the reference (anchor) company.
Build the Ideal Customer Profile (ICP) fingerprint that candidate companies must match, modeled strictly on the anchor company's real profile.
Respond with STRICT JSON only (no markdown fences, no commentary), exactly this schema:
{"fingerprint":{"scale":str,"operations":str,"geography":str,"commodities":[str],"safety_exposure":str,"technology_adoption":str,"automation_potential":str},"criteria":[{"name":str,"weight":number,"description":str}],"search_queries":[str]}
Rules: base everything on the anchor profile visible in the provided context; do not invent anchor facts; include 8-12 concrete search_queries for finding similar companies (commodity + country + scale terms, e.g. "large copper mining companies Chile production")."""

DISCOVERY_SYSTEM = """You are the Account Discovery Agent in a multi-agent BDR system for FlytBase (autonomous drone inspection, Physical AI for industrial sites).
You receive: the campaign brief, the ICP criteria, a seed candidate pool, and live web-search results.
Merge these into a deduplicated list of candidate companies that plausibly match the ICP (large-scale lithium / copper / iron ore mining operations in Latin America).
Respond with STRICT JSON only:
{"candidates":[{"name":str,"country":str,"commodities":[str],"website":str|null,"origin":"seed|search","note":str}]}
Rules: max 14 candidates; prefer real operating large-scale companies over pure developers/explorers; include a candidate only if it appears in the seed pool or the search results; NEVER invent company names or websites; use null for unknown websites; one entry per legal entity (do not duplicate a JV under partner names)."""

VERIFICATION_SYSTEM = """You are the Account Verification Agent in a multi-agent BDR system for FlytBase (autonomous drone inspection for large industrial sites).
Given a candidate company, the ICP criteria, and evidence (company website text, news items, search results), decide whether the company is a QUALIFIED account for a discovery campaign about autonomous drone inspection at hazardous 24/7 extraction sites.
Respond with STRICT JSON only:
{"qualified":bool,"icp_score":number,"large_scale":bool,"commodities":[str],"country":str,"fit_reason":str,"why_it_fits":[{"point":str,"source_url":str|null}],"evidence":[{"claim":str,"source":str,"url":str|null,"published":str|null,"extract":str,"confidence":number}]}
Rules: every evidence entry must be grounded in the provided text (extract = short verbatim quote); only qualify if the company is a real, currently operating, large-scale mining company in Latin America matching at least 4 ICP criteria; if evidence is thin, lower icp_score and set qualified=false; never assume unverified facts; fit_reason must read like a human BDR's note (2-3 sentences)."""

CONTACT_SYSTEM = """You are the Contact Discovery Agent in a multi-agent BDR system for FlytBase.
Target personas: Head of Operations, VP Operations, Operations Director, Site Director, General Manager - Mine, VP of HSE, HSE Director, Safety Director, Director of Industrial Operations.
From the provided text ONLY (search results, news, company website sections), extract REAL named people at the account whose role matches a target persona.
Respond with STRICT JSON only:
{"contacts":[{"name":str,"role":str,"seniority":"C-suite|VP|Director|GM|Other","linkedin":str|null,"email":str|null,"source_url":str|null,"confidence":number,"why_relevant":str}]}
Rules: NEVER invent a person, role, or email address. Include a person only if their name appears in the provided text with a connection to this company or a current-role signal. If nobody qualifies, return {"contacts":[]}. Do not guess or pattern-generate email addresses."""

CONTACT_VERIFY_SYSTEM = """You are the Contact Verification Agent in a multi-agent BDR system for FlytBase.
Determine whether the candidate contact is (a) a real person, (b) currently at the company, (c) in a role matching the target personas (Head of Operations / VP HSE / Site Director / Operations Director / Safety Director etc.).
Respond with STRICT JSON only:
{"is_real":bool,"current_at_company":bool,"current_role":str|null,"role_matches_persona":bool,"confidence":number,"summary":str,"evidence":[{"claim":str,"source":str,"url":str|null,"published":str|null,"extract":str,"confidence":number}]}
Rules: base strictly on the provided search results/news. If the only evidence is old (>3 years) or ambiguous, set current_at_company=false and explain in summary. Never confirm a person without evidence. summary = 1-2 sentences a human BDR can act on."""

RESEARCH_SYSTEM = """You are the Deep Research Agent in a multi-agent BDR system for FlytBase (autonomous drone inspection replacing contracted crews at hazardous, 24/7 extraction sites).
From the provided sources (news, search results, company website), produce a research brief for the account covering: company profile, recent events, operational signals, technology signals, safety signals, and FlytBase-relevant opportunities.
Respond with STRICT JSON only:
{"account_name":str,"company_profile":{"size_context":str,"countries":[str],"assets":[str],"commodities":[str],"production_context":str},"recent_events":[{"title":str,"detail":str,"kind":"expansion|new_asset|incident|safety_initiative|technology|production|other","published":str|null,"source":str,"url":str|null,"is_inference":false}],"operational_signals":[{"signal":str,"detail":str,"source":str,"url":str|null,"is_inference":bool}],"technology_signals":[{"signal":str,"detail":str,"source":str,"url":str|null,"is_inference":bool}],"safety_signals":[{"signal":str,"detail":str,"source":str,"url":str|null,"is_inference":bool}],"opportunities":[{"description":str,"reasoning":str,"personalization_angle":str,"is_inference":true}]}
Rules: facts must come from the provided sources (is_inference=false, with source and url when available); inferences (e.g. "expansion likely increases inspection workload") must have is_inference=true and be framed as inference; no invented numbers, dates, or asset names; focus on strategic insight (expansion, 24/7 operations, remote/hazardous sites, safety incidents, technology investment), not trivia."""

EMAIL_SYSTEM = """You are the Personalization Agent - a senior BDR writer - for FlytBase.
FlytBase: category leader in Physical AI for large industrial sites; autonomous drone inspection that replaces contracted inspection crews at hazardous, 24/7 operations. Referenceable customers: Shell, Anglo American, CSX.
Write ONE outbound discovery email for the given contact, grounded ONLY in the provided research.
Respond with STRICT JSON only:
{"subject":str,"body":str,"proof_refs":[str]}
Requirements:
- subject: max 12 words, specific, no clickbait.
- body: 150-220 words, plain text (no markdown), signed with the sender name provided at the end.
- Open with a specific verifiable observation from the research (name the site, asset, or event).
- Connect it to a pain in this recipient's role lane (operations safety, HSE risk, inspection workload).
- Mention the FlytBase angle once, concretely: autonomous drone inspection replacing contracted crews at hazardous 24/7 sites.
- Reference a FlytBase customer (proof_refs) only when it genuinely strengthens the framing; Anglo American is the natural mining-peer reference.
- Close with a low-friction CTA (a short 15-minute call).
- Sound like a human who did their homework; no marketing fluff; no {placeholders}; no facts not present in the provided research; never present an inference as a fact."""

CLAIMS_SYSTEM = """You are the Hallucination Checker (claim extractor). Extract every atomic factual claim about the world (company, person, asset, event, technology) from the email below. Ignore greetings and calls to action.
Respond with STRICT JSON only: {"claims":[str]}
Each claim must be a single checkable statement, phrased in the third person."""

JUDGE_SYSTEM = """You are the Fact Checker agent. For each claim from the outreach email, decide whether the provided evidence (research brief, account evidence, contact verification) supports it.
Respond with STRICT JSON only:
{"verdicts":[{"claim":str,"verdict":"supported|partial|unsupported","note":str,"evidence_ref":str|null}]}
Rules: "supported" = evidence contains the fact (or a direct paraphrase); "partial" = evidence points at it but not exactly (e.g., an inference stated too strongly); "unsupported" = no evidence at all. Be strict: a claim about a specific site, number, date, or person is unsupported unless the evidence names it."""

REWRITE_SYSTEM = """You are the Personalization Agent (BDR writer) for FlytBase, doing a fact-checked rewrite.
You receive the original email plus fact-check verdicts and the research evidence. Rewrite the email so that EVERY factual claim is supported by the provided research: remove or soften unsupported claims, reframe partial ones as hedges ("I believe", "it looks like"), keep the structure, length and tone.
Respond with STRICT JSON only: {"subject":str,"body":str,"proof_refs":[str]}
Constraints: 150-220 words, human tone, low-friction CTA, no facts outside the provided research."""


# --------------------------------------------------------------------------
# A1 — ICP agent
# --------------------------------------------------------------------------

def build_a1():
    ua = [{"name": "User-Agent", "value": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0"}]
    n0 = trigger_node()
    nprep = code_node("Prep", JS_HELPERS + """
const c = $input.first().json;
const campaign = c.campaign || c;
const refFull = (campaign.reference_account || 'Sociedad Quimica y Minera de Chile (SQM)').split('(')[0].trim();
return [{ json: { campaign, refFull } }];
""", [220, 0])
    nwiki1 = http_node("Wiki Search", "GET",
                       "={{ 'https://en.wikipedia.org/w/api.php?action=opensearch&search=' + encodeURIComponent($('Prep').first().json.refFull) + '&limit=1&format=json' }}",
                       [440, 0], headers=ua, on_error_continue=True, timeout=20000)
    nwiki2 = http_node("Wiki Extract", "GET",
                       "={{ 'https://en.wikipedia.org/w/api.php?action=query&prop=extracts&explaintext=1&redirects=1&format=json&titles=' + encodeURIComponent($('Wiki Search').first().json[1][0]) }}",
                       [660, 0], headers=ua, on_error_continue=True, timeout=25000)
    nnews = http_node("Fetch News RSS", "GET",
                      "={{ 'https://news.google.com/rss/search?q=' + encodeURIComponent($('Prep').first().json.refFull + ' mining') + '&hl=en-US&gl=US&ceid=US:en' }}",
                      [880, 0], response_text=True, on_error_continue=True, timeout=25000)
    nctx = code_node("Build Context", JS_HELPERS + """
const t = $('Prep').first().json;
const campaign = t.campaign;
const we = safeNode('Wiki Extract');
let wikiText = '';
if (we && we.json && we.json.query && we.json.query.pages) {
  const p = Object.values(we.json.query.pages)[0] || {};
  wikiText = (p.extract || '').slice(0, 9000);
}
const newsItems = parseRss(outText('Fetch News RSS')).slice(0, 8);
const context = [
  '## CAMPAIGN BRIEF',
  'Target vertical: ' + (campaign.vertical || ''),
  'Geography: ' + (campaign.geography || ''),
  'Reference (anchor) account: ' + (campaign.reference_account || ''),
  'Target personas: ' + (Array.isArray(campaign.target_roles) ? campaign.target_roles.join(', ') : (campaign.target_roles || '')),
  'Solution: ' + (campaign.solution || ''),
  '', '## ANCHOR COMPANY - WIKIPEDIA (plain text extract)', wikiText || '(wiki fetch failed)',
  '', '## ANCHOR COMPANY - RECENT NEWS',
  newsItems.map(n => '- ' + n.title + ' (' + (n.published || 'date unknown') + ') ' + n.snippet).join('\\n') || '(no news)'
].join('\\n');
return [{ json: { system: """ + json.dumps(ICP_SYSTEM) + """, prompt: context, temperature: 0.2 } }];
""", [1100, 0])
    nllm = exec_wf_node("Call LLM", "TOOLS_LLM", [1320, 0])
    nparse = code_node("Parse ICP", JS_HELPERS + """
const out = $json;
const icp = (out && out.ok) ? parseJsonLoose(out.content) : null;
if (!icp || !Array.isArray(icp.search_queries) || !Array.isArray(icp.criteria)) {
  const campaign = $('Prep').first().json.campaign;
  const fallback = {
    fingerprint: {
      scale: 'Large-scale operating mine or integrated mining company',
      operations: 'Active extraction and processing operations with recurring inspection workload',
      geography: campaign.geography || 'Latin America',
      commodities: ['lithium', 'copper', 'iron ore'],
      safety_exposure: 'Remote or hazardous industrial areas where manual inspections expose personnel',
      technology_adoption: 'Evidence required during account verification',
      automation_potential: 'Large distributed sites suitable for repeatable autonomous drone inspection'
    },
    criteria: [
      { name: 'Operating scale', weight: 25, description: 'Currently operating a large mine or processing site' },
      { name: 'Geographic fit', weight: 20, description: 'Material operations in Latin America' },
      { name: 'Commodity fit', weight: 20, description: 'Lithium, copper, or iron ore exposure' },
      { name: 'Inspection intensity', weight: 20, description: 'Large, remote, hazardous, or continuous-operation assets' },
      { name: 'Automation readiness', weight: 15, description: 'Public technology, safety, or automation signals' }
    ],
    search_queries: [
      'large copper mining companies Latin America',
      'lithium mining companies Latin America production',
      'iron ore mining operations Latin America expansion'
    ],
    anchor: campaign.reference_account,
    fallback_reason: (out && out.error) || 'ICP model output unavailable'
  };
  return [{ json: { stage: 'icp', status: 'ok_fallback', icp: fallback } }];
}
return [{ json: { stage: 'icp', status: 'ok', icp } }];
""", [1540, 0])
    npersist = code_node("Persist", JS_HELPERS + """
const out = $json;
const campaign = $('Prep').first().json.campaign;
if (out.status === 'ok' && out.icp) {
  out.icp.anchor = campaign.reference_account;
  await ingest(campaign.id, 'icp', out.icp);
}
return [{ json: out }];
""", [1760, 0])
    nodes = [n0, nprep, nwiki1, nwiki2, nnews, nctx, nllm, nparse, npersist]
    conns = edges(
        (n0["name"], nprep["name"]),
        (nprep["name"], nwiki1["name"]),
        (nwiki1["name"], nwiki2["name"]),
        (nwiki1["name"], nnews["name"], 1),
        (nwiki2["name"], nnews["name"]),
        (nwiki2["name"], nnews["name"], 1),
        (nnews["name"], nctx["name"]),
        (nnews["name"], nctx["name"], 1),
        (nctx["name"], nllm["name"]),
        (nllm["name"], nparse["name"]),
        (nllm["name"], nparse["name"], 1),
        (nparse["name"], npersist["name"]),
    )
    return workflow("BDR :: A1 ICP Agent", nodes, conns,
                    "Agent 1: builds the ICP fingerprint from the reference account (SQM). In: {campaign}. Out: {stage, status, icp}.")


# --------------------------------------------------------------------------
# A2 — Account discovery
# --------------------------------------------------------------------------

def build_a2():
    n0 = trigger_node()
    nprep = code_node("Prep + Load Seed", JS_HELPERS + """
const t = $input.first().json;
const campaign = t.campaign;
const icp = t.icp;
let seed = [];
try {
  const pool = await faGet('/api/seed');
  if (pool && Array.isArray(pool.companies)) seed = pool.companies;
} catch (e) { seed = []; }
const queries = Array.isArray(icp && icp.search_queries) ? icp.search_queries.slice(0, 8) : ['large copper mining companies Latin America', 'lithium mining companies Latin America production', 'iron ore mining operations Latin America expansion'];
return queries.map(q => ({ json: { campaign, icp, seed, query: q, num: 8 } }));
""", [220, 0])
    nsplit = split_node("Loop", 1, [440, 0])
    nsearch = exec_wf_node("Search", "TOOLS_SEARCH", [660, 140])
    nwait = wait_node("Throttle", 1.5, [880, 140])
    nacc = code_node("Accumulate", JS_HELPERS + """
const q = $('Loop').first().json.query;
const j = $json;
await ingest($('Loop').first().json.campaign.id, 'search', {
  query: q, provider: j.provider || 'error', result_count: (j.results || []).length,
  results: (j.results || []).slice(0, 8), error: j.error || null
});
return [{ json: j }];
""", [1100, 140])
    ncollect = code_node("Collect + Build Context", JS_HELPERS + """
const t0 = $('Prep + Load Seed').first().json;
const searches = await faGet('/api/searches?campaign_id=' + encodeURIComponent(t0.campaign.id));
const seen = new Set();
const merged = [];
for (const s of (Array.isArray(searches) ? searches : [])) {
  for (const it of (s.results || [])) {
    if (!it.url || seen.has(it.url)) continue;
    seen.add(it.url);
    merged.push({ title: it.title, url: it.url, snippet: (it.snippet || '').slice(0, 220), query: s.query });
  }
}
if (merged.length === 0 && t0.seed.length === 0) {
  return [{ json: { __skipped: true, stage: 'discovery', status: 'skipped', reason: 'no live search results and no seed pool available (all search providers failed)', candidates: [] } }];
}
const context = [
  '## CAMPAIGN', t0.campaign.vertical, t0.campaign.geography, 'Reference account: ' + t0.campaign.reference_account,
  '', '## ICP CRITERIA', JSON.stringify((t0.icp && t0.icp.criteria) || [], null, 1),
  '', '## SEED CANDIDATE POOL (real companies, BDR seed list)',
  t0.seed.map(s => '- ' + s.name + ' | ' + s.country + ' | ' + (s.commodities || []).join('/') + ' | ' + (s.note || '')).join('\\n'),
  '', '## LIVE SEARCH RESULTS (' + merged.length + ' unique)',
  merged.slice(0, 60).map(m => '- [' + m.query + '] ' + m.title + ' :: ' + m.url + ' :: ' + m.snippet).join('\\n')
].join('\\n');
return [{ json: { system: """ + json.dumps(DISCOVERY_SYSTEM) + """, prompt: context, temperature: 0.1 } }];
""", [660, -160])
    nswitch2 = switch_node("Has Pool?", "={{ $json.__skipped === true ? 'yes' : 'no' }}", ['yes'], [880, -300], fallback="extra")
    nllm = exec_wf_node("Call LLM", "TOOLS_LLM", [880, -160])
    nparse = code_node("Parse Candidates", JS_HELPERS + """
const out = $json;
let candidates = null;
if (out && out.ok) {
  const parsed = parseJsonLoose(out.content);
  if (parsed && Array.isArray(parsed.candidates)) candidates = parsed.candidates.slice(0, 14);
}
if (!candidates) {
  const prep = $('Prep + Load Seed').first().json;
  candidates = (Array.isArray(prep.seed) ? prep.seed : []).slice(0, 14).map(s => ({
    name: s.name, country: s.country, commodities: s.commodities || [], website: s.website || null,
    origin: 'seed', note: s.note || 'BDR seed candidate; requires evidence verification'
  }));
  return [{ json: { stage: 'discovery', status: 'ok_fallback', reason: (out && out.error) || 'discovery model output unavailable', candidates } }];
}
return [{ json: { stage: 'discovery', status: 'ok', candidates } }];
""", [1100, -160])
    npersist = code_node("Persist", JS_HELPERS + """
const out = $json;
const campaign = $('Prep + Load Seed').first().json.campaign;
if (out.status === 'ok') {
  for (const c of out.candidates) {
    await ingest(campaign.id, 'account', { ...c, status: 'candidate', icp_score: null, fit_reason: null, evidence: [] });
  }
}
return [{ json: out }];
""", [1320, -160])
    nodes = [n0, nprep, nsplit, nsearch, nwait, nacc, ncollect, nswitch2, nllm, nparse, npersist]
    conns = edges(
        (n0["name"], nprep["name"]),
        (nprep["name"], nsplit["name"]),
        (nsplit["name"], ncollect["name"], 0),
        (nsplit["name"], nsearch["name"], 1),
        (nsearch["name"], nwait["name"]),
        (nsearch["name"], nacc["name"], 1),
        (nwait["name"], nacc["name"]),
        (nacc["name"], nsplit["name"]),
        (ncollect["name"], nswitch2["name"]),
        (nswitch2["name"], npersist["name"], 0),
        (nswitch2["name"], nllm["name"], 1),
        (nllm["name"], nparse["name"]),
        (nllm["name"], nparse["name"], 1),
        (nparse["name"], npersist["name"]),
    )
    return workflow("BDR :: A2 Account Discovery", nodes, conns,
                    "Agent 2: discovers candidate accounts (BDR seed pool + live web search). In: {campaign, icp}. Out: {stage, status, candidates[]}.")


# --------------------------------------------------------------------------
# A3 — Account verification
# --------------------------------------------------------------------------

def build_a3():
    n0 = trigger_node()
    nprep = code_node("Prep (itemize)", """
const t = $input.first().json;
const campaign = t.campaign;
const icp = t.icp;
const candidates = Array.isArray(t.candidates) ? t.candidates : [];
const maxN = (campaign.max_accounts && Number(campaign.max_accounts)) || 10;
const cands = candidates.slice(0, maxN);
if (!cands.length) {
  return [{ json: { __skipped: true, campaign, icp, reason: 'no candidates to verify (upstream discovery failed or returned nothing)' } }];
}
return cands.map(c => ({ json: { campaign, icp, candidate: c } }));
""", [220, 0])
    nswitch = switch_node("Has Candidates?", "={{ $json.__skipped === true ? 'yes' : 'no' }}", ['yes'], [440, 0], fallback="extra")
    nsplit = split_node("Loop", 1, [660, 0])
    nsite = http_node("Fetch Site", "GET",
                      "={{ ($json.candidate.website || '').startsWith('http') ? $json.candidate.website : 'https://' + ($json.candidate.website || 'invalid-host') }}",
                      [660, 120],
                      headers=[{"name": "User-Agent", "value": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0"}],
                      response_text=True, on_error_continue=True, timeout=25000)
    nrss = http_node("Fetch News RSS", "GET",
                     "={{ 'https://news.google.com/rss/search?q=' + encodeURIComponent($('Loop').first().json.candidate.name + ' mining ' + (($('Loop').first().json.candidate.commodities || []).join(' '))) + '&hl=en-US&gl=US&ceid=US:en' }}",
                     [880, 120], response_text=True, on_error_continue=True, timeout=25000)
    nsearch = exec_wf_node("Search More", "TOOLS_SEARCH", [1100, 120])
    nwait = wait_node("Throttle", 1.5, [1320, 120])
    nctx = code_node("Build Context", JS_HELPERS + """
const it = $('Loop').first().json;
const c = it.candidate;
const siteText = htmlToText(outText('Fetch Site')).slice(0, 6000);
const news = parseRss(outText('Fetch News RSS')).slice(0, 10);
const s = safeNode('Search More');
const searchResults = (s && Array.isArray(s.json.results)) ? s.json.results.slice(0, 10) : [];
const context = [
  '## CANDIDATE COMPANY',
  'Name: ' + c.name, 'Country: ' + (c.country || 'unknown'), 'Commodities: ' + (c.commodities || []).join('/'), 'Website: ' + (c.website || 'unknown'), 'Seed note: ' + (c.note || ''),
  '', '## ICP CRITERIA', JSON.stringify((it.icp && it.icp.criteria) || [], null, 1),
  '', '## COMPANY WEBSITE TEXT', siteText || '(fetch failed)',
  '', '## RECENT NEWS', news.map(n => '- ' + n.title + ' (' + (n.published || '?') + ') ' + n.snippet).join('\\n') || '(none)',
  '', '## WEB SEARCH RESULTS', searchResults.map(x => '- ' + x.title + ' :: ' + x.url + ' :: ' + (x.snippet || '').slice(0, 250)).join('\\n') || '(none)'
].join('\\n');
return [{ json: { system: """ + json.dumps(VERIFICATION_SYSTEM) + """, prompt: context, temperature: 0.1 } }];
""", [1540, 120])
    nllm = exec_wf_node("Call LLM", "TOOLS_LLM", [1760, 120])
    nparse = code_node("Evaluate", JS_HELPERS + """
const it = $('Loop').first().json;
const c = it.candidate;
const out = $json;
let v = (out && out.ok) ? parseJsonLoose(out.content) : null;
let fallbackUsed = false;
if (!v) {
  const news = parseRss(outText('Fetch News RSS')).slice(0, 5);
  const s = safeNode('Search More');
  const sr = (s && Array.isArray(s.json.results)) ? s.json.results.slice(0, 5) : [];
  const publicHits = [...news, ...sr].filter(x => x && x.url && (x.title || x.snippet));
  const note = String(c.note || '').toLowerCase();
  const operatingSignal = /(operat|mine|producer|production|large|major|asset)/.test(note);
  const commodityFit = Array.isArray(c.commodities) && c.commodities.some(x => /(copper|lithium|iron)/i.test(x));
  const geoFit = !!c.country;
  const qualified = operatingSignal && commodityFit && geoFit && publicHits.length > 0;
  const evidence = publicHits.slice(0, 5).map(x => ({
    claim: x.title || ('Public result for ' + c.name), source: x.source || 'Public web/news result',
    url: x.url, published: x.published || null,
    extract: String(x.snippet || x.title || '').slice(0, 350), confidence: 0.65
  }));
  v = {
    qualified, icp_score: qualified ? 72 : 38, large_scale: operatingSignal,
    commodities: c.commodities || [], country: c.country || '',
    fit_reason: qualified
      ? c.name + ' matches the campaign geography and commodity scope, and current public results provide an operating-company signal. LLM verification was unavailable, so this is a conservative evidence fallback for BDR review.'
      : 'Insufficient public evidence to verify this account automatically; keep it out of outreach until a human or later run confirms operating scale.',
    why_it_fits: qualified ? [
      { point: 'Commodity and geography match the campaign brief', source_url: publicHits[0] ? publicHits[0].url : null },
      { point: 'Public-source operating signal available for verification', source_url: publicHits[0] ? publicHits[0].url : null }
    ] : [], evidence, fallback_verification: true
  };
  fallbackUsed = true;
}
return [{ json: { candidate: c, verdict: v, failed: false, fallbackUsed, error: null } }];
""", [1980, 120])
    npersist = code_node("Persist", JS_HELPERS + """
const { candidate: c, verdict: v, failed, error } = $json;
const campaign = $('Prep (itemize)').first().json.campaign;
if (failed) {
  await ingest(campaign.id, 'account', { ...c, status: 'rejected', icp_score: 0, fit_reason: 'Verification failed: ' + (error || 'llm error'), evidence: [] });
  return [{ json: { name: c.name, status: 'rejected' } }];
}
const qualified = !!v.qualified;
await ingest(campaign.id, 'account', {
  ...c,
  status: qualified ? 'qualified' : 'rejected',
  icp_score: typeof v.icp_score === 'number' ? v.icp_score : 0,
  large_scale: !!v.large_scale,
  fit_reason: v.fit_reason || '',
  why_it_fits: Array.isArray(v.why_it_fits) ? v.why_it_fits : [],
  evidence: Array.isArray(v.evidence) ? v.evidence : []
});
return [{ json: { name: c.name, status: qualified ? 'qualified' : 'rejected', icp_score: v.icp_score } }];
""", [2200, 120])
    nreturn = code_node("Return", JS_HELPERS + """
const p0 = $('Prep (itemize)').first().json;
const skipped = p0.__skipped === true;
const campaign = p0.campaign;
let qualified = [];
try { qualified = await faGet('/api/accounts?campaign_id=' + encodeURIComponent(campaign.id) + '&status=qualified'); } catch (e) {}
let all = [];
try { all = await faGet('/api/accounts?campaign_id=' + encodeURIComponent(campaign.id)); } catch (e) {}
const counts = { qualified: 0, rejected: 0, failed: 0 };
for (const a of (Array.isArray(all) ? all : [])) {
  if (a.status === 'qualified') counts.qualified++;
  else if (a.status === 'rejected') counts.rejected++;
}
return [{ json: { stage: 'verification', status: skipped ? 'skipped' : 'ok', reason: skipped ? p0.reason : null, qualified_accounts: Array.isArray(qualified) ? qualified : [], counts } }];
""", [660, -220])
    nodes = [n0, nprep, nswitch, nsplit, nsite, nrss, nsearch, nwait, nctx, nllm, nparse, npersist, nreturn]
    conns = edges(
        (n0["name"], nprep["name"]),
        (nprep["name"], nswitch["name"]),
        (nswitch["name"], nreturn["name"], 0),
        (nswitch["name"], nsplit["name"], 1),
        (nsplit["name"], nreturn["name"], 0),
        (nsplit["name"], nsite["name"], 1),
        (nsite["name"], nrss["name"]),
        (nsite["name"], nrss["name"], 1),
        (nrss["name"], nsearch["name"]),
        (nrss["name"], nsearch["name"], 1),
        (nsearch["name"], nwait["name"]),
        (nsearch["name"], nwait["name"], 1),
        (nwait["name"], nctx["name"]),
        (nctx["name"], nllm["name"]),
        (nllm["name"], nparse["name"]),
        (nllm["name"], nparse["name"], 1),
        (nparse["name"], npersist["name"]),
        (npersist["name"], nsplit["name"]),
    )
    return workflow("BDR :: A3 Account Verification", nodes, conns,
                    "Agent 3: verifies each candidate against the ICP with evidence. In: {campaign, icp, candidates[]}. Out: {stage, status, qualified_accounts[], counts}.")


# --------------------------------------------------------------------------
# A4 — Contact discovery
# --------------------------------------------------------------------------

def build_a4():
    n0 = trigger_node()
    nprep = code_node("Prep (itemize)", """
const t = $input.first().json;
const campaign = t.campaign;
const accounts = Array.isArray(t.qualified_accounts) ? t.qualified_accounts : [];
const accs = accounts.slice(0, 12);
if (!accs.length) {
  return [{ json: { __skipped: true, campaign, reason: 'no qualified accounts (verification produced nothing)' } }];
}
return accs.map(a => ({ json: { campaign, account: a } }));
""", [220, 0])
    nswitch = switch_node("Has Accounts?", "={{ $json.__skipped === true ? 'yes' : 'no' }}", ['yes'], [440, 0], fallback="extra")
    nsplit = split_node("Loop", 1, [660, 0])
    nsearch = exec_wf_node("Search Roles", "TOOLS_SEARCH", [660, 120])
    nwait = wait_node("Throttle", 1.5, [880, 120])
    nrss = http_node("News RSS", "GET",
                     "={{ 'https://news.google.com/rss/search?q=' + encodeURIComponent($('Loop').first().json.account.name + ' (\"operations director\" OR \"vp hse\" OR \"site director\" OR appoints)') + '&hl=en-US&gl=US&ceid=US:en' }}",
                     [1100, 120], response_text=True, on_error_continue=True, timeout=25000)
    nabout = http_node("Fetch About", "GET",
                       "={{ (($('Loop').first().json.account.website || '').startsWith('http') ? $('Loop').first().json.account.website : 'https://' + ($('Loop').first().json.account.website || 'invalid-host')).replace(/\\/$/, '') + '/about' }}",
                     [1320, 120],
                     headers=[{"name": "User-Agent", "value": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0"}],
                     response_text=True, on_error_continue=True, timeout=25000)
    nctx = code_node("Build Context", JS_HELPERS + """
const it = $('Loop').first().json;
const a = it.account;
const s = safeNode('Search Roles');
const searchResults = (s && Array.isArray(s.json.results)) ? s.json.results.slice(0, 12) : [];
const news = parseRss(outText('News RSS')).slice(0, 10);
const aboutText = htmlToText(outText('Fetch About')).slice(0, 5000);
const context = [
  '## ACCOUNT', 'Name: ' + a.name, 'Country: ' + (a.country || ''), 'Commodities: ' + (a.commodities || []).join('/'), 'Website: ' + (a.website || ''),
  '', '## TARGET PERSONAS', 'Head of Operations, VP Operations, Operations Director, Site Director, General Manager Mine, VP HSE, HSE Director, Safety Director, Director of Industrial Operations',
  '', '## WEB SEARCH RESULTS (people / roles)', searchResults.map(x => '- ' + x.title + ' :: ' + x.url + ' :: ' + (x.snippet || '').slice(0, 300)).join('\\n') || '(none)',
  '', '## NEWS (appointments)', news.map(n => '- ' + n.title + ' (' + (n.published || '?') + ') ' + n.snippet).join('\\n') || '(none)',
  '', '## COMPANY ABOUT PAGE TEXT', aboutText || '(fetch failed)'
].join('\\n');
return [{ json: { system: """ + json.dumps(CONTACT_SYSTEM) + """, prompt: context, temperature: 0.1 } }];
""", [1540, 120])
    nllm = exec_wf_node("Call LLM", "TOOLS_LLM", [1760, 120])
    npersist = code_node("Persist", JS_HELPERS + """
const it = $('Loop').first().json;
const a = it.account;
const out = $json;
let contacts = [];
if (out && out.ok) {
  const parsed = parseJsonLoose(out.content);
  if (parsed && Array.isArray(parsed.contacts)) contacts = parsed.contacts.slice(0, 8);
}
for (const c of contacts) {
  await ingest(it.campaign.id, 'contact', {
    account_name: a.name, name: c.name, role: c.role, seniority: c.seniority || 'Other',
    linkedin: c.linkedin || null, email: c.email || null,
    email_status: c.email ? 'unverified' : 'unknown',
    why: c.why_relevant || '', source_url: c.source_url || null,
    confidence: typeof c.confidence === 'number' ? c.confidence : 0.5,
    status: 'candidate'
  });
}
return [{ json: { account: a.name, found: contacts.length } }];
""", [1980, 120])
    nreturn = code_node("Return", JS_HELPERS + """
const p0 = $('Prep (itemize)').first().json;
const skipped = p0.__skipped === true;
const campaign = p0.campaign;
let contacts = [];
try { contacts = await faGet('/api/contacts?campaign_id=' + encodeURIComponent(campaign.id) + '&status=candidate'); } catch (e) {}
return [{ json: { stage: 'contact_discovery', status: skipped ? 'skipped' : 'ok', reason: skipped ? p0.reason : null, contacts: Array.isArray(contacts) ? contacts : [], counts: { candidates: Array.isArray(contacts) ? contacts.length : 0 } } }];
""", [660, -220])
    nodes = [n0, nprep, nswitch, nsplit, nsearch, nwait, nrss, nabout, nctx, nllm, npersist, nreturn]
    conns = edges(
        (n0["name"], nprep["name"]),
        (nprep["name"], nswitch["name"]),
        (nswitch["name"], nreturn["name"], 0),
        (nswitch["name"], nsplit["name"], 1),
        (nsplit["name"], nreturn["name"], 0),
        (nsplit["name"], nsearch["name"], 1),
        (nsearch["name"], nwait["name"]),
        (nsearch["name"], nwait["name"], 1),
        (nwait["name"], nrss["name"]),
        (nrss["name"], nabout["name"]),
        (nrss["name"], nabout["name"], 1),
        (nabout["name"], nctx["name"]),
        (nabout["name"], nctx["name"], 1),
        (nctx["name"], nllm["name"]),
        (nllm["name"], npersist["name"]),
        (nllm["name"], npersist["name"], 1),
        (npersist["name"], nsplit["name"]),
    )
    return workflow("BDR :: A4 Contact Discovery", nodes, conns,
                    "Agent 4: finds target-persona contacts per qualified account. In: {campaign, qualified_accounts[]}. Out: {stage, status, contacts[], counts}.")
