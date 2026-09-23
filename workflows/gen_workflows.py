#!/usr/bin/env python3
"""
BDR Intelligence Agent - n8n workflow generator.
Generates all n8n workflow JSON files for the FlytBase BDR hackathon agent.
Workflow ID references use __WFID:<LOGICAL_NAME>__ placeholders;
import_workflows.py resolves them against workflows/ids.json after creating
the sub-workflows (deterministic re-import: IDs are stable across updates).
"""
import json
import os
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = HERE

FASTAPI = "http://127.0.0.1:8000"

# --------------------------------------------------------------------------
# n8n construction helpers
# --------------------------------------------------------------------------

def nid():
    return str(uuid.uuid4())


def node(name, ntype, params, pos, tv=2, extra=None):
    n = {"parameters": params, "id": nid(), "name": name, "type": ntype,
         "typeVersion": tv, "position": pos}
    if extra:
        n.update(extra)
    return n


def trigger_node(name="Trigger"):
    return node(name, "n8n-nodes-base.executeWorkflowTrigger",
                {"inputSource": "passthrough"}, [0, 0], tv=1.2)


def code_node(name, js, pos):
    return node(name, "n8n-nodes-base.code", {"jsCode": js}, pos, tv=2)


def http_node(name, method, url, pos, headers=None, json_body=None,
              response_text=False, on_error_continue=False, timeout=20000):
    params = {"url": url, "method": method, "options": {"timeout": timeout}}
    if response_text:
        params["options"]["response"] = {"response": {"responseFormat": "text", "outputPropertyName": "data"}}
    if headers:
        params["sendHeaders"] = True
        params["headerParameters"] = {"parameters": headers}
    if json_body is not None:
        params["sendBody"] = True
        params["specifyBody"] = "json"
        params["jsonBody"] = json_body
    extra = {"onError": "continueErrorOutput"} if on_error_continue else None
    return node(name, "n8n-nodes-base.httpRequest", params, pos, tv=4.2, extra=extra)


def wait_node(name, seconds, pos):
    return node(name, "n8n-nodes-base.wait", {"amount": seconds, "unit": "seconds"}, pos, tv=1.1)


def split_node(name, batch=1, pos=(0, 0)):
    return node(name, "n8n-nodes-base.splitInBatches", {"batchSize": batch, "options": {}}, list(pos), tv=3)


def switch_node(name, expr, rules, pos, fallback="last"):
    values = []
    for key in rules:
        values.append({
            "renameOutput": True,
            "outputKey": key,
            "conditions": {
                "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose"},
                "conditions": [{"id": nid(), "leftValue": expr, "rightValue": key,
                                 "operator": {"type": "string", "operation": "equals"}}],
                "combinator": "and",
            },
        })
    params = {"rules": {"values": values}, "options": {}}
    if fallback == "extra":
        params["options"]["fallbackOutput"] = "extra"
    return node(name, "n8n-nodes-base.switch", params, pos, tv=3)


def exec_wf_node(name, logical_id, pos):
    return node(name, "n8n-nodes-base.executeWorkflow", {
        "source": "database",
        "workflowId": {"__rl": True, "mode": "id", "value": "__WFID:%s__" % logical_id},
        "mode": "once",
        "workflowInputs": {"mappingMode": "defineBelow", "value": None},
        "options": {},
    }, pos, tv=1.3, extra={"onError": "continueErrorOutput"})


def edges(*specs):
    conns = {}
    for spec in specs:
        src, dst = spec[0], spec[1]
        idx = spec[2] if len(spec) > 2 else 0
        conns.setdefault(src, {"main": []})
        while len(conns[src]["main"]) <= idx:
            conns[src]["main"].append([])
        conns[src]["main"][idx].append({"node": dst, "type": "main", "index": 0})
    return conns


def workflow(name, nodes, connections, description=""):
    return {"name": name, "nodes": nodes, "connections": connections,
            "settings": {"executionOrder": "v1"}, "description": description, "active": False}


# --------------------------------------------------------------------------
# Shared JS snippets
# --------------------------------------------------------------------------

JS_HELPERS = """
// ===== shared helpers (BDR agent) =====
const FA = '""" + FASTAPI + """';
async function ingest(campaign_id, type, payload, retries = 3) {
  for (let i = 0; i < retries; i++) {
    try {
      await this.helpers.httpRequest({ method: 'POST', url: FA + '/api/ingest',
        body: JSON.stringify({ campaign_id, type, payload }),
        headers: { 'Content-Type': 'application/json' }, timeout: 15000 });
      return { ok: true };
    } catch (e) {
      if (i === retries - 1) return { ok: false, error: String((e && e.message) || e) };
      await new Promise(r => setTimeout(r, 1500));
    }
  }
}
async function faGet(path, timeout = 30000) {
  const resp = await this.helpers.httpRequest({ method: 'GET', url: FA + path, timeout });
  if (typeof resp === 'string') { try { return JSON.parse(resp); } catch (e) { return resp; } }
  return resp;
}
function parseJsonLoose(text) {
  if (!text) return null;
  let t = String(text).trim();
  t = t.replace(/^```(?:json)?/i, '').replace(/```$/, '').trim();
  const s = t.indexOf('{'); const e = t.lastIndexOf('}');
  if (s === -1 || e === -1 || e <= s) return null;
  try { return JSON.parse(t.slice(s, e + 1)); } catch (err) { return null; }
}
function htmlToText(html) {
  if (!html) return '';
  let h = String(html);
  h = h.replace(/<script[^>]*>[\\s\\S]*?<\\/script>/gi, ' ');
  h = h.replace(/<style[^>]*>[\\s\\S]*?<\\/style>/gi, ' ');
  h = h.replace(/<nav[^>]*>[\\s\\S]*?<\\/nav>/gi, ' ');
  h = h.replace(/<footer[^>]*>[\\s\\S]*?<\\/footer>/gi, ' ');
  h = h.replace(/<(br|\\/p|\\/div|\\/h[1-6]|\\/li|\\/tr)[^>]*>/gi, '\\n');
  h = h.replace(/<[^>]+>/g, ' ');
  h = h.replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'");
  h = h.replace(/[ \\t]+/g, ' ');
  h = h.replace(/\\n\\s*\\n+/g, '\\n');
  return h.trim();
}
function parseRss(xml) {
  const out = [];
  if (!xml) return out;
  const items = String(xml).match(/<item>[\\s\\S]*?<\\/item>/g) || [];
  const grab = (block, tag) => {
    const m = block.match(new RegExp('<' + tag + '[^>]*>([\\\\s\\\\S]*?)</' + tag + '>', 'i'));
    return m ? m[1].replace(/<!\\[CDATA\\[|\\]\\]>/g, '').trim() : '';
  };
  for (const it of items.slice(0, 12)) {
    const title = grab(it, 'title').replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/&#39;/g, "'");
    const link = grab(it, 'link');
    const pub = grab(it, 'pubDate');
    let desc = grab(it, 'description').replace(/<[^>]+>/g, ' ').replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/\\s+/g, ' ').trim();
    if (title && link) out.push({ title, url: link, snippet: desc.slice(0, 500), published: pub || null, source: 'Google News' });
  }
  return out;
}
function safeNode(name) { try { const h = $(name); const n = (h && h.first) ? h.first() : h; if (n && n.json !== undefined) return n; } catch (e) {} return null; }
function outText(name) { const n = safeNode(name); if (!n) return ''; const j = n.json; if (typeof j === 'string') return j; if (j && typeof j.data === 'string') return j.data; return (j && j.json && typeof j.json.data === 'string') ? j.json.data : ''; }
"""

# --------------------------------------------------------------------------
# TOOLS_search
# --------------------------------------------------------------------------

def build_tools_search():
    n0 = trigger_node()
    nswitch = switch_node("Provider",
                          "={{ $env.BRAVE_API_KEY ? 'brave' : ($env.SERPER_API_KEY ? 'serper' : ($env.TAVILY_API_KEY ? 'tavily' : 'rss')) }}",
                          ['brave', 'serper', 'tavily', 'rss'], [220, 0])
    nb = http_node("Brave HTTP", "GET",
                   "={{ 'https://api.search.brave.com/res/v1/web/search?q=' + encodeURIComponent($json.query) + '&count=' + ($json.num || 8) + '&search_lang=en' }}",
                   [440, -300],
                   headers=[{"name": "Accept", "value": "application/json"},
                             {"name": "X-Subscription-Token", "value": "={{ $env.BRAVE_API_KEY }}"}],
                   on_error_continue=True)
    pb = code_node("Brave Parse", """
const r = $json || {};
let results = [];
const web = Array.isArray(r.web) ? r.web : (Array.isArray(r.results) ? r.results : []);
for (const it of web.slice(0, 8)) results.push({ title: it.title || '', url: it.url || it.link || '', snippet: (it.description || '').slice(0, 500), published: it.page_age_raw || null, source: 'Brave Web' });
return [{ json: { provider: 'brave', results } }];
""", [660, -300])
    ns = http_node("Serper HTTP", "POST", "https://google.serper.dev/search", [440, -100],
                   headers=[{"name": "X-API-KEY", "value": "={{ String($env.SERPER_API_KEY || '') }}"},
                             {"name": "Content-Type", "value": "application/json"}],
                   json_body="={{ JSON.stringify({ q: $json.query, num: $json.num || 8 }) }}",
                   on_error_continue=True)
    ps = code_node("Serper Parse", """
const r = $json || {};
let results = [];
if (Array.isArray(r.organic)) for (const it of r.organic.slice(0, 8)) results.push({ title: it.title || '', url: it.link || '', snippet: (it.snippet || '').slice(0, 500), published: it.date || null, source: 'Serper (Google)' });
return [{ json: { provider: 'serper', results } }];
""", [660, -100])
    nt = http_node("Tavily HTTP", "POST", "https://api.tavily.com/search", [440, 100],
                   headers=[{"name": "Authorization", "value": "={{ 'Bearer ' + String($env.TAVILY_API_KEY || '') }}"},
                             {"name": "Content-Type", "value": "application/json"}],
                   json_body="={{ JSON.stringify({ query: $json.query, max_results: $json.num || 8, include_answer: false }) }}",
                   on_error_continue=True)
    pt = code_node("Tavily Parse", """
const r = $json || {};
let results = [];
if (Array.isArray(r.results)) for (const it of r.results.slice(0, 8)) results.push({ title: it.title || '', url: it.url || '', snippet: (it.content || '').slice(0, 500), published: it.published_date || null, source: 'Tavily' });
return [{ json: { provider: 'tavily', results } }];
""", [660, 100])
    nr = http_node("News RSS HTTP", "GET",
                   "={{ 'https://news.google.com/rss/search?q=' + encodeURIComponent($json.query) + '&hl=en-US&gl=US&ceid=US:en' }}",
                   [440, 300], response_text=True, on_error_continue=True)
    pr = code_node("RSS Parse", JS_HELPERS + """
const xml = (typeof $json.data === 'string' ? $json.data : '') || outText('News RSS HTTP') || (typeof $json === 'string' ? $json : '');
const results = parseRss(xml);
return [{ json: { provider: 'google-news-rss', results } }];
""", [660, 300])
    nf = code_node("Search Fail", """
const err = ($json && $json.error) ? (typeof $json.error === 'string' ? $json.error : ($json.error.message || JSON.stringify($json.error))) : 'unknown error';
return [{ json: { provider: 'error', results: [], error: String(err).slice(0, 300) } }];
""", [660, 500])
    nout = code_node("Out", """
const j = $json;
const t = $('Trigger').first().json;
return [{ json: { query: t.query || null, provider: j.provider || 'unknown', results: Array.isArray(j.results) ? j.results : [], error: j.error || null } }];
""", [900, 0])
    nodes = [n0, nswitch, nb, pb, ns, ps, nt, pt, nr, pr, nf, nout]
    conns = edges(
        (n0["name"], nswitch["name"]),
        (nswitch["name"], nb["name"], 0), (nswitch["name"], ns["name"], 1),
        (nswitch["name"], nt["name"], 2), (nswitch["name"], nr["name"], 3),
        (nb["name"], pb["name"]), (nb["name"], nf["name"], 1),
        (ns["name"], ps["name"]), (ns["name"], nf["name"], 1),
        (nt["name"], pt["name"]), (nt["name"], nf["name"], 1),
        (nr["name"], pr["name"]), (nr["name"], nf["name"], 1),
        (pb["name"], nout["name"]), (ps["name"], nout["name"]),
        (pt["name"], nout["name"]), (pr["name"], nout["name"]), (nf["name"], nout["name"]),
    )
    return workflow("BDR :: TOOLS_search", nodes, conns,
                    "Tool: multi-provider web search. In: {query, num}. Out: {query, provider, results[], error?}.")


# --------------------------------------------------------------------------
# TOOLS_fetch_page
# --------------------------------------------------------------------------

def build_tools_fetch():
    n0 = trigger_node()
    nh = http_node("Fetch", "GET", "={{ $json.url }}", [220, 0],
                   headers=[{"name": "User-Agent", "value": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0"}],
                   response_text=True, on_error_continue=True, timeout=25000)
    np = code_node("Parse", JS_HELPERS + """
const t = $('Trigger').first().json;
const raw = (typeof $json.data === 'string' ? $json.data : '') || outText('Fetch') || (typeof $json === 'string' ? $json : '');
const text = htmlToText(raw).slice(0, t.max_chars || 15000);
return [{ json: { url: t.url, ok: !!text, status: text ? 'ok' : 'empty', text } }];
""", [440, 0])
    nf = code_node("Fail", """
const t = $('Trigger').first().json;
return [{ json: { url: t.url, ok: false, status: 'error', text: '' } }];
""", [440, 220])
    nodes = [n0, nh, np, nf]
    conns = edges((n0["name"], nh["name"]), (nh["name"], np["name"]), (nh["name"], nf["name"], 1))
    return workflow("BDR :: TOOLS_fetch_page", nodes, conns,
                    "Tool: fetch a URL, return clean text. In: {url, max_chars?}. Out: {url, ok, status, text}.")


# --------------------------------------------------------------------------
# TOOLS_llm
# --------------------------------------------------------------------------

def build_tools_llm():
    n0 = trigger_node()
    nswitch = switch_node("Provider", "={{ ($env.LLM_PROVIDER || 'openai').toLowerCase() }}",
                          ['openai', 'gemini', 'anthropic'], [220, 0], fallback="extra")
    body_oe = """={{ JSON.stringify({
  model: $json.model || ($env.LLM_MODEL || 'gpt-4o-mini'),
  temperature: typeof $json.temperature === 'number' ? $json.temperature : 0.4,
  reasoning_effort: $json.reasoning_effort || 'none',
  max_tokens: $json.max_tokens || 1500,
  messages: [
    { role: 'system', content: $json.system || 'You are a precise assistant.' },
    { role: 'user', content: $json.prompt }
  ]
}) }}"""
    no = http_node("OpenAI HTTP", "POST",
                   "={{ ($env.OPENAI_BASE_URL || 'https://api.openai.com/v1').replace(/\\/$/, '') + '/chat/completions' }}",
                   [440, -300],
                   headers=[{"name": "Authorization", "value": "={{ 'Bearer ' + String($env.OPENAI_API_KEY || '') }}"},
                             {"name": "Content-Type", "value": "application/json"}],
                   json_body=body_oe, on_error_continue=True, timeout=360000)
    no.update({"retryOnFail": True, "maxTries": 6, "waitBetweenTries": 4000})
    po = code_node("OpenAI Parse", """
const r = $json || {};
const c = r.choices && r.choices[0] && r.choices[0].message ? r.choices[0].message.content : '';
return [{ json: { ok: true, content: c || '', model: ($json.model || 'gpt-4o-mini') } }];
""", [660, -300])
    ng = http_node("Gemini HTTP", "POST",
                   "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
                   [440, -100],
                   headers=[{"name": "x-goog-api-key", "value": "={{ String($env.GEMINI_API_KEY || '') }}"},
                             {"name": "Content-Type", "value": "application/json"}],
                   json_body="""={{ JSON.stringify({
  model: $json.model || ($env.LLM_MODEL || 'gemini-2.0-flash'),
  temperature: typeof $json.temperature === 'number' ? $json.temperature : 0.4,
  max_tokens: $json.max_tokens || 1800,
  messages: [
    { role: 'system', content: $json.system || 'You are a precise assistant.' },
    { role: 'user', content: $json.prompt }
  ]
}) }}""",
                   on_error_continue=True, timeout=360000)
    pg = code_node("Gemini Parse", """
const r = $json || {};
const c = r.choices && r.choices[0] && r.choices[0].message ? r.choices[0].message.content : '';
return [{ json: { ok: true, content: c || '', model: ($json.model || 'gemini-2.0-flash') } }];
""", [660, -100])
    na = http_node("Anthropic HTTP", "POST", "https://api.anthropic.com/v1/messages", [440, 100],
                   headers=[{"name": "x-api-key", "value": "={{ String($env.ANTHROPIC_API_KEY || '') }}"},
                             {"name": "anthropic-version", "value": "2023-06-01"},
                             {"name": "Content-Type", "value": "application/json"}],
                   json_body="""={{ JSON.stringify({
  model: $json.model || ($env.LLM_MODEL || 'claude-3-5-haiku-20241022'),
  max_tokens: $json.max_tokens || 1800,
  temperature: typeof $json.temperature === 'number' ? $json.temperature : 0.4,
  system: $json.system || 'You are a precise assistant.',
  messages: [{ role: 'user', content: $json.prompt }]
}) }}""",
                   on_error_continue=True, timeout=360000)
    pa = code_node("Anthropic Parse", """
const r = $json || {};
const c = Array.isArray(r.content) ? r.content.map(x => x.text || '').join('') : '';
return [{ json: { ok: true, content: c, model: ($json.model || 'claude-3-5-haiku-20241022') } }];
""", [660, 100])
    nfail = code_node("LLM Fail", """
const err = ($json && $json.error) ? (typeof $json.error === 'string' ? $json.error : ($json.error.message || 'unknown LLM error')) : 'unknown LLM error (check LLM_PROVIDER / API keys)';
return [{ json: { ok: false, content: '', model: null, error: String(err).slice(0, 400) } }];
""", [660, 300])
    nodes = [n0, nswitch, no, po, ng, pg, na, pa, nfail]
    conns = edges(
        (n0["name"], nswitch["name"]),
        (nswitch["name"], no["name"], 0), (nswitch["name"], ng["name"], 1),
        (nswitch["name"], na["name"], 2), (nswitch["name"], nfail["name"], 3),
        (no["name"], po["name"]), (no["name"], nfail["name"], 1),
        (ng["name"], pg["name"]), (ng["name"], nfail["name"], 1),
        (na["name"], pa["name"]), (na["name"], nfail["name"], 1),
    )
    return workflow("BDR :: TOOLS_llm", nodes, conns,
                    "Tool: provider-agnostic LLM call. In: {system, prompt, model?, temperature?, max_tokens?}. Out: {ok, content, model, error?}.")


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


# --------------------------------------------------------------------------
# A5 — Contact verification
# --------------------------------------------------------------------------

def build_a5():
    n0 = trigger_node()
    nprep = code_node("Prep (itemize)", """
const t = $input.first().json;
const campaign = t.campaign;
const contacts = Array.isArray(t.contacts) ? t.contacts : [];
const cs = contacts.slice(0, 20);
if (!cs.length) {
  return [{ json: { __skipped: true, campaign, reason: 'no candidate contacts to verify (contact discovery found nothing)' } }];
}
return cs.map(c => ({ json: { campaign, contact: c } }));
""", [220, 0])
    nswitch = switch_node("Has Contacts?", "={{ $json.__skipped === true ? 'yes' : 'no' }}", ['yes'], [440, 0], fallback="extra")
    nsplit = split_node("Loop", 1, [660, 0])
    nsearch = exec_wf_node("Search Person", "TOOLS_SEARCH", [660, 120])
    nwait = wait_node("Throttle", 1.5, [880, 120])
    nctx = code_node("Build Context", """
const it = $('Loop').first().json;
const c = it.contact;
const s = safeNode('Search Person');
const results = (s && Array.isArray(s.json.results)) ? s.json.results.slice(0, 12) : [];
const context = [
  '## CANDIDATE CONTACT',
  'Name: ' + c.name, 'Role (claimed): ' + (c.role || '?'), 'Seniority: ' + (c.seniority || '?'), 'Company: ' + (c.account_name || '?'),
  'Source URL for claim: ' + (c.source_url || 'unknown'), 'Discovery note: ' + (c.why || ''),
  '', '## LIVE SEARCH RESULTS',
  results.map(r => '- ' + r.title + ' :: ' + r.url + ' :: ' + (r.published || '') + ' :: ' + (r.snippet || '').slice(0, 300)).join('\\n') || '(none)'
].join('\\n');
return [{ json: { system: """ + json.dumps(CONTACT_VERIFY_SYSTEM) + """, prompt: context, temperature: 0.1 } }];
""", [1100, 120])
    nllm = exec_wf_node("Call LLM", "TOOLS_LLM", [1320, 120])
    npersist = code_node("Persist", JS_HELPERS + """
const it = $('Loop').first().json;
const c = it.contact;
const out = $json;
const v = (out && out.ok) ? parseJsonLoose(out.content) : null;
let verified = false;
let reason = v ? (v.summary || '') : 'verification failed: ' + ((out && out.error) || 'llm error');
if (v) verified = !!v.is_real && !!v.current_at_company && !!v.role_matches_persona;
await ingest(it.campaign.id, 'contact_update', {
  match: { account_name: c.account_name, name: c.name, status: 'candidate' },
  patch: {
    status: verified ? 'verified' : 'rejected',
    verified: !!verified,
    current_role: (v && v.current_role) || c.role,
    verification_summary: String(reason).slice(0, 400),
    confidence: (v && typeof v.confidence === 'number') ? v.confidence : 0,
    evidence: (v && Array.isArray(v.evidence)) ? v.evidence : []
  }
});
return [{ json: { contact: c.name, verified } }];
""", [1540, 120])
    nreturn = code_node("Return", JS_HELPERS + """
const p0 = $('Prep (itemize)').first().json;
const skipped = p0.__skipped === true;
const campaign = p0.campaign;
let contacts = [];
try { contacts = await faGet('/api/contacts?campaign_id=' + encodeURIComponent(campaign.id) + '&status=verified'); } catch (e) {}
return [{ json: { stage: 'contact_verification', status: skipped ? 'skipped' : 'ok', reason: skipped ? p0.reason : null, verified_contacts: Array.isArray(contacts) ? contacts : [], counts: { verified: Array.isArray(contacts) ? contacts.length : 0 } } }];
""", [660, -220])
    nodes = [n0, nprep, nswitch, nsplit, nsearch, nwait, nctx, nllm, npersist, nreturn]
    conns = edges(
        (n0["name"], nprep["name"]),
        (nprep["name"], nswitch["name"]),
        (nswitch["name"], nreturn["name"], 0),
        (nswitch["name"], nsplit["name"], 1),
        (nsplit["name"], nreturn["name"], 0),
        (nsplit["name"], nsearch["name"], 1),
        (nsearch["name"], nwait["name"]),
        (nsearch["name"], nwait["name"], 1),
        (nwait["name"], nctx["name"]),
        (nctx["name"], nllm["name"]),
        (nllm["name"], npersist["name"]),
        (nllm["name"], npersist["name"], 1),
        (npersist["name"], nsplit["name"]),
    )
    return workflow("BDR :: A5 Contact Verification", nodes, conns,
                    "Agent 5: verifies contacts are real, current, role-matched. In: {campaign, contacts[]}. Out: {stage, status, verified_contacts[], counts}.")


# --------------------------------------------------------------------------
# A6 — Deep research
# --------------------------------------------------------------------------

def build_a6():
    n0 = trigger_node()
    nprep = code_node("Prep (itemize)", JS_HELPERS + """
const t = $input.first().json;
const campaign = t.campaign;
let accounts = Array.isArray(t.qualified_accounts) ? t.qualified_accounts : [];
if (!accounts.length) { try { accounts = await faGet('/api/accounts?campaign_id=' + encodeURIComponent(campaign.id) + '&status=qualified'); } catch (e) {} }
const accs = (Array.isArray(accounts) ? accounts : []).slice(0, 10);
if (!accs.length) {
  return [{ json: { __skipped: true, campaign, reason: 'no qualified accounts to research (verification produced nothing)' } }];
}
return accs.map(a => ({ json: { campaign, account: a } }));
""", [220, 0])
    nswitch = switch_node("Has Accounts?", "={{ $json.__skipped === true ? 'yes' : 'no' }}", ['yes'], [440, 0], fallback="extra")
    nsplit = split_node("Loop", 1, [660, 0])
    nsearch1 = exec_wf_node("Search News", "TOOLS_SEARCH", [660, 60])
    nwait1 = wait_node("Throttle 1", 1.5, [880, 60])
    nsearch2 = exec_wf_node("Search Signals", "TOOLS_SEARCH", [1100, 60])
    nrss = http_node("News RSS", "GET",
                     "={{ 'https://news.google.com/rss/search?q=' + encodeURIComponent($('Loop').first().json.account.name + ' mining') + '&hl=en-US&gl=US&ceid=US:en' }}",
                     [1320, 60], response_text=True, on_error_continue=True, timeout=25000)
    nsite = http_node("Fetch Site", "GET",
                      "={{ ($('Loop').first().json.account.website || '').startsWith('http') ? $('Loop').first().json.account.website : 'https://' + ($('Loop').first().json.account.website || 'invalid-host') }}",
                      [1540, 60],
                      headers=[{"name": "User-Agent", "value": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0"}],
                      response_text=True, on_error_continue=True, timeout=25000)
    nctx = code_node("Build Context", JS_HELPERS + """
const it = $('Loop').first().json;
const a = it.account;
const s1 = safeNode('Search News');
const s2 = safeNode('Search Signals');
const r1 = (s1 && Array.isArray(s1.json.results)) ? s1.json.results.slice(0, 10) : [];
const r2 = (s2 && Array.isArray(s2.json.results)) ? s2.json.results.slice(0, 10) : [];
const news = parseRss(outText('News RSS')).slice(0, 10);
const siteText = htmlToText(outText('Fetch Site')).slice(0, 6000);
const fmt = (rs) => rs.map(x => '- ' + x.title + ' :: ' + x.url + ' :: ' + (x.published || '') + ' :: ' + (x.snippet || '').slice(0, 250)).join('\\n') || '(none)';
const context = [
  '## ACCOUNT', 'Name: ' + a.name, 'Country: ' + (a.country || ''), 'Commodities: ' + (a.commodities || []).join('/'), 'Fit reason: ' + (a.fit_reason || ''),
  '', '## SEARCH: RECENT NEWS / EXPANSION', fmt(r1),
  '', '## SEARCH: AUTOMATION / SAFETY / TECHNOLOGY', fmt(r2),
  '', '## GOOGLE NEWS', news.map(n => '- ' + n.title + ' (' + (n.published || '?') + ') ' + n.snippet).join('\\n') || '(none)',
  '', '## COMPANY WEBSITE TEXT', siteText || '(fetch failed)'
].join('\\n');
return [{ json: { system: """ + json.dumps(RESEARCH_SYSTEM) + """, prompt: context, temperature: 0.2, max_tokens: 6000 } }];
""", [1760, 60])
    nllm = exec_wf_node("Call LLM", "TOOLS_LLM", [1980, 60])
    npersist = code_node("Persist", JS_HELPERS + """
const it = $('Loop').first().json;
const a = it.account;
const out = $json;
const r = (out && out.ok) ? parseJsonLoose(out.content) : null;
let research = r;
let fallbackUsed = false;
if (!research || !(research.company_profile || research.recent_events)) {
  const s1 = safeNode('Search News'); const s2 = safeNode('Search Signals');
  const hits = [
    ...((s1 && Array.isArray(s1.json.results)) ? s1.json.results : []),
    ...((s2 && Array.isArray(s2.json.results)) ? s2.json.results : []),
    ...parseRss(outText('News RSS'))
  ].filter(x => x && x.url && (x.title || x.snippet));
  const unique = []; const seen = new Set();
  for (const h of hits) { if (!seen.has(h.url)) { seen.add(h.url); unique.push(h); } }
  research = {
    account_name: a.name,
    company_profile: { size_context: a.large_scale ? 'Large-scale operating account (verified)' : 'Scale requires review', countries: [a.country].filter(Boolean), assets: [], commodities: a.commodities || [], production_context: a.fit_reason || '' },
    recent_events: unique.slice(0, 6).map(h => ({ title: h.title || 'Public update', detail: String(h.snippet || '').slice(0, 400), kind: 'other', published: h.published || null, source: h.source || 'Public web/news', url: h.url, is_inference: false })),
    operational_signals: unique.slice(0, 4).map(h => ({ signal: h.title || 'Operating signal', detail: String(h.snippet || '').slice(0, 300), source: h.source || 'Public web/news', url: h.url, is_inference: false })),
    technology_signals: [], safety_signals: [],
    opportunities: [{ description: 'Assess repeatable autonomous inspection workflows at large or hazardous operating areas', reasoning: 'Large distributed mining assets commonly require recurring visual inspection; validate the exact workflow in discovery.', personalization_angle: 'Ask about inspection frequency, contractor exposure, and remote-site coverage rather than assuming a current pain.', is_inference: true }],
    fallback_research: true
  };
  fallbackUsed = true;
}
research.account_name = research.account_name || a.name;
await ingest(it.campaign.id, 'research', research);
return [{ json: { account: a.name, researched: true, fallbackUsed } }];
""", [2200, 60])
    nreturn = code_node("Return", JS_HELPERS + """
const p0 = $('Prep (itemize)').first().json;
const skipped = p0.__skipped === true;
const campaign = p0.campaign;
let research = [];
try { research = await faGet('/api/research?campaign_id=' + encodeURIComponent(campaign.id)); } catch (e) {}
research = Array.isArray(research) ? research.filter(r => r && !r.status) : [];
return [{ json: { stage: 'research', status: skipped ? 'skipped' : 'ok', reason: skipped ? p0.reason : null, research, counts: { researched: research.length } } }];
""", [660, -220])
    nodes = [n0, nprep, nswitch, nsplit, nsearch1, nwait1, nsearch2, nrss, nsite, nctx, nllm, npersist, nreturn]
    conns = edges(
        (n0["name"], nprep["name"]),
        (nprep["name"], nswitch["name"]),
        (nswitch["name"], nreturn["name"], 0),
        (nswitch["name"], nsplit["name"], 1),
        (nsplit["name"], nreturn["name"], 0),
        (nsplit["name"], nsearch1["name"], 1),
        (nsearch1["name"], nwait1["name"]),
        (nsearch1["name"], nwait1["name"], 1),
        (nwait1["name"], nsearch2["name"]),
        (nsearch2["name"], nrss["name"]),
        (nsearch2["name"], nrss["name"], 1),
        (nrss["name"], nsite["name"]),
        (nrss["name"], nsite["name"], 1),
        (nsite["name"], nctx["name"]),
        (nsite["name"], nctx["name"], 1),
        (nctx["name"], nllm["name"]),
        (nllm["name"], npersist["name"]),
        (nllm["name"], npersist["name"], 1),
        (npersist["name"], nsplit["name"]),
    )
    return workflow("BDR :: A6 Deep Research", nodes, conns,
                    "Agent 6: 5-bucket research per account (profile, events, ops/tech/safety signals, opportunities). In: {campaign, qualified_accounts[]}. Out: {stage, status, research[], counts}.")


# --------------------------------------------------------------------------
# A7 — Personalization
# --------------------------------------------------------------------------

def build_a7():
    n0 = trigger_node()
    nprep = code_node("Prep (itemize)", """
const t = $input.first().json;
const campaign = t.campaign;
const kb = t.kb || {};
const contacts = Array.isArray(t.verified_contacts) ? t.verified_contacts : [];
const research = Array.isArray(t.research) ? t.research : [];
const byAccount = {};
for (const r of research) { if (r && r.account_name) byAccount[r.account_name] = r; }
const cs = contacts.slice(0, 12);
if (!cs.length) {
  return [{ json: { __skipped: true, campaign, kb, reason: 'no verified contacts to write emails for' } }];
}
return cs.map(c => ({ json: { campaign, kb, contact: c, research: byAccount[c.account_name] || null } }));
""", [220, 0])
    nswitch = switch_node("Has Contacts?", "={{ $json.__skipped === true ? 'yes' : 'no' }}", ['yes'], [440, 0], fallback="extra")
    nsplit = split_node("Loop", 1, [660, 0])
    nctx = code_node("Build Context", """
const it = $('Loop').first().json;
const c = it.contact;
const r = it.research || {};
const kb = it.kb || {};
const angle = (kb.flytbase_angle && kb.flytbase_angle.core) || 'Autonomous drone inspection replacing contracted inspection crews at hazardous, 24/7 industrial sites.';
const proof = kb.customers_referenceable_in_outreach || ['Shell', 'Anglo American', 'CSX'];
const ev = (arr) => (Array.isArray(arr) ? arr.slice(0, 6).map(x => (x.title || x.signal || x.description || '') + (x.detail || x.reasoning ? ' - ' + (x.detail || x.reasoning) : '') + (x.url ? ' [' + x.url + ']' : '')).join('\\n') : '(none)');
const context = [
  '## RECIPIENT', 'Name: ' + c.name, 'Role: ' + (c.current_role || c.role || '?'), 'Company: ' + (c.account_name || '?'),
  'Verification summary: ' + (c.verification_summary || '(not verified in detail)'),
  '', '## ACCOUNT RESEARCH (FACTS)',
  'Profile: ' + JSON.stringify(r.company_profile || {}).slice(0, 800),
  'Recent events:\\n' + ev(r.recent_events),
  'Operational signals:\\n' + ev(r.operational_signals),
  'Technology signals:\\n' + ev(r.technology_signals),
  'Safety signals:\\n' + ev(r.safety_signals),
  'Opportunities (inferences - frame as inferences):\\n' + ev(r.opportunities),
  '', '## FLYTBASE KNOWLEDGE BASE',
  'Positioning: ' + (kb.positioning || ''),
  'Angle: ' + angle,
  'Referenceable customers: ' + proof.join(', '),
  'Customer context: ' + JSON.stringify(kb.referenceable_customer_context || {}).slice(0, 600),
  '', '## SENDER SIGN-OFF', 'Alex from FlytBase'
].join('\\n');
return [{ json: { system: """ + json.dumps(EMAIL_SYSTEM) + """, prompt: context, temperature: 0.5 } }];
""", [660, 120])
    nllm = exec_wf_node("Call LLM", "TOOLS_LLM", [880, 120])
    npersist = code_node("Persist", JS_HELPERS + """
const it = $('Loop').first().json;
const c = it.contact;
const out = $json;
const e = (out && out.ok) ? parseJsonLoose(out.content) : null;
if (e && e.body) {
  await ingest(it.campaign.id, 'email', {
    account_name: c.account_name, contact_name: c.name, contact_role: (c.current_role || c.role || ''),
    subject: e.subject || '', body: e.body,
    proof_refs: Array.isArray(e.proof_refs) ? e.proof_refs : [],
    status: 'draft'
  });
}
return [{ json: { contact: c.name, drafted: !!(e && e.body) } }];
""", [1100, 120])
    nreturn = code_node("Return", JS_HELPERS + """
const p0 = $('Prep (itemize)').first().json;
const skipped = p0.__skipped === true;
const campaign = p0.campaign;
let emails = [];
try { emails = await faGet('/api/emails?campaign_id=' + encodeURIComponent(campaign.id)); } catch (e) {}
emails = Array.isArray(emails) ? emails : [];
return [{ json: { stage: 'personalization', status: skipped ? 'skipped' : 'ok', reason: skipped ? p0.reason : null, emails, counts: { drafted: emails.length } } }];
""", [660, -220])
    nodes = [n0, nprep, nswitch, nsplit, nctx, nllm, npersist, nreturn]
    conns = edges(
        (n0["name"], nprep["name"]),
        (nprep["name"], nswitch["name"]),
        (nswitch["name"], nreturn["name"], 0),
        (nswitch["name"], nsplit["name"], 1),
        (nsplit["name"], nreturn["name"], 0),
        (nsplit["name"], nctx["name"], 1),
        (nctx["name"], nllm["name"]),
        (nllm["name"], npersist["name"]),
        (nllm["name"], npersist["name"], 1),
        (npersist["name"], nsplit["name"]),
    )
    return workflow("BDR :: A7 Personalization", nodes, conns,
                    "Agent 7: writes the personalized outreach email per verified contact. In: {campaign, kb, verified_contacts[], research[]}. Out: {stage, status, emails[], counts}.")


# --------------------------------------------------------------------------
# A8 — Fact checker
# --------------------------------------------------------------------------

def build_a8():
    n0 = trigger_node()
    nprep = code_node("Prep (itemize)", JS_HELPERS + """
const t = $input.first().json;
const campaign = t.campaign;
const emails = Array.isArray(t.emails) ? t.emails : [];
if (!emails.length) {
  return [{ json: { __skipped: true, campaign, reason: 'no draft emails to fact-check (personalization produced nothing)' } }];
}
let bundle = [];
try { bundle = await faGet('/api/evidence_bundle?campaign_id=' + encodeURIComponent(campaign.id)); } catch (e) { bundle = []; }
return emails.map(e => ({ json: { campaign, email: e, bundle } }));
""", [220, 0])
    nswitch = switch_node("Has Emails?", "={{ $json.__skipped === true ? 'yes' : 'no' }}", ['yes'], [440, 0], fallback="extra")
    nsplit = split_node("Loop", 1, [660, 0])
    nclaims = code_node("Prepare Claims", """
const it = $('Loop').first().json;
const e = it.email;
return [{ json: { system: """ + json.dumps(CLAIMS_SYSTEM) + """, prompt: 'EMAIL SUBJECT: ' + (e.subject || '') + '\\n\\nEMAIL BODY:\\n' + (e.body || ''), temperature: 0.1 } }];
""", [660, 120])
    nllm1 = exec_wf_node("Call Claims LLM", "TOOLS_LLM", [880, 120])
    njudge = code_node("Prepare Judge", """
const it = $('Loop').first().json;
const out = $json;
let claims = [];
if (out && out.ok) {
  const parsed = parseJsonLoose(out.content);
  if (parsed && Array.isArray(parsed.claims)) claims = parsed.claims.slice(0, 12);
}
const bundleText = JSON.stringify(it.bundle || []).slice(0, 12000);
return [{ json: {
  system: """ + json.dumps(JUDGE_SYSTEM) + """,
  prompt: 'CLAIMS (JSON): ' + JSON.stringify(claims) + '\\n\\nEVIDENCE BUNDLE (JSON):\\n' + bundleText,
  temperature: 0.1
} }];
""", [1100, 120])
    nllm2 = exec_wf_node("Call Judge LLM", "TOOLS_LLM", [1320, 120])
    ncheck = code_node("Apply Verdicts", """
const prep = $('Loop').first().json;
const jctx = $('Prepare Judge').first().json;
const out = $json;
let verdicts = [];
if (out && out.ok) {
  const parsed = parseJsonLoose(out.content);
  if (parsed && Array.isArray(parsed.verdicts)) verdicts = parsed.verdicts;
}
const bad = verdicts.filter(v => v.verdict === 'unsupported').length;
const partial = verdicts.filter(v => v.verdict === 'partial').length;
return [{ json: {
  campaign: prep.campaign, email: prep.email, bundle: prep.bundle, verdicts, bad, partial,
  needsRewrite: bad > 0,
  system: """ + json.dumps(REWRITE_SYSTEM) + """,
  prompt: 'ORIGINAL EMAIL\\nSubject: ' + (prep.email.subject || '') + '\\n\\n' + (prep.email.body || '') +
          '\\n\\nFACT-CHECK VERDICTS (JSON): ' + JSON.stringify(verdicts) +
          '\\n\\nRESEARCH EVIDENCE (JSON): ' + JSON.stringify(prep.bundle || []).slice(0, 12000),
  temperature: 0.5
} }];
""", [1540, 120])
    nif = node("Need Rewrite?", "n8n-nodes-base.if", {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose"},
            "conditions": [{
                "id": nid(),
                "leftValue": "={{ $json.needsRewrite }}",
                "rightValue": True,
                "operator": {"type": "boolean", "operation": "true", "singleValue": True},
            }],
            "combinator": "and",
        },
        "options": {},
    }, [1760, 120], tv=2.2)
    nrewrite = exec_wf_node("Call Rewrite LLM", "TOOLS_LLM", [1980, -80])
    nfinal = code_node("Persist Final", JS_HELPERS + """
const base = $('Apply Verdicts').first().json;
const rew = $json;
let finalEmail = base.email;
let rewritten = false;
if (base.needsRewrite && rew && rew.ok) {
  const parsed = parseJsonLoose(rew.content);
  if (parsed && parsed.body) {
    finalEmail = { ...base.email, subject: parsed.subject || base.email.subject, body: parsed.body,
                   proof_refs: parsed.proof_refs || base.email.proof_refs };
    rewritten = true;
  }
}
await ingest(base.campaign.id, 'email_update', {
  match: { contact_name: base.email.contact_name, account_name: base.email.account_name },
  patch: {
    subject: finalEmail.subject, body: finalEmail.body, proof_refs: finalEmail.proof_refs || [],
    status: 'final',
    fact_check: { verdicts: base.verdicts, unsupported: base.bad, partial: base.partial, rewritten }
  }
});
return [{ json: { contact: base.email.contact_name, rewritten, unsupported: base.bad, partial: base.partial } }];
""", [2200, 120])
    nreturn = code_node("Return", JS_HELPERS + """
const p0 = $('Prep (itemize)').first().json;
const skipped = p0.__skipped === true;
const campaign = p0.campaign;
let emails = [];
try { emails = await faGet('/api/emails?campaign_id=' + encodeURIComponent(campaign.id) + '&status=final'); } catch (e) {}
emails = Array.isArray(emails) ? emails : [];
return [{ json: { stage: 'fact_check', status: skipped ? 'skipped' : 'ok', reason: skipped ? p0.reason : null, emails, counts: { fact_checked: emails.length } } }];
""", [660, -220])
    nodes = [n0, nprep, nswitch, nsplit, nclaims, nllm1, njudge, nllm2, ncheck, nif, nrewrite, nfinal, nreturn]
    conns = edges(
        (n0["name"], nprep["name"]),
        (nprep["name"], nswitch["name"]),
        (nswitch["name"], nreturn["name"], 0),
        (nswitch["name"], nsplit["name"], 1),
        (nsplit["name"], nreturn["name"], 0),
        (nsplit["name"], nclaims["name"], 1),
        (nclaims["name"], nllm1["name"]),
        (nllm1["name"], njudge["name"]),
        (nllm1["name"], njudge["name"], 1),
        (njudge["name"], nllm2["name"]),
        (nllm2["name"], ncheck["name"]),
        (nllm2["name"], ncheck["name"], 1),
        (ncheck["name"], nif["name"]),
        (nif["name"], nrewrite["name"], 0),
        (nif["name"], nfinal["name"], 1),
        (nrewrite["name"], nfinal["name"]),
        (nrewrite["name"], nfinal["name"], 1),
        (nfinal["name"], nsplit["name"]),
    )
    return workflow("BDR :: A8 Fact Checker", nodes, conns,
                    "Agent 8: claim-level fact check vs the evidence store; rewrites emails with unsupported claims. In: {campaign, emails[]}. Out: {stage, status, emails[], counts}.")


# --------------------------------------------------------------------------
# MASTER orchestrator
# --------------------------------------------------------------------------

def build_master():
    nweb = node("Webhook", "n8n-nodes-base.webhook", {
        "httpMethod": "POST", "path": "master", "responseMode": "onReceived", "options": {},
    }, [0, 0], tv=2, extra={"webhookId": "bdr-master-1"})
    ninit = code_node("Init Campaign", """
const body = ($json && ($json.body || $json)) || {};
const campaign = {
  id: 'run_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
  vertical: body.vertical || 'Large-scale lithium, copper, and iron ore mining operations in Latin America',
  geography: body.geography || 'Latin America',
  reference_account: body.reference_account || 'Sociedad Quimica y Minera de Chile (SQM)',
  target_roles: Array.isArray(body.target_roles) && body.target_roles.length ? body.target_roles : ['Head of Operations', 'VP of HSE', 'Site Directors'],
  solution: body.solution || 'Autonomous drone inspection replacing contracted crews at hazardous, 24/7 extraction sites',
  max_accounts: (body.max_accounts ? Number(body.max_accounts) : 8),
  sender_name: body.sender_name || 'Alex from FlytBase',
  created_at: new Date().toISOString(),
  status: 'running'
};
return [{ json: { campaign } }];
""", [220, 0])
    nkb = code_node("Start Run + Load KB", JS_HELPERS + """
const prev = $json;
const campaign = prev.campaign;
await ingest(campaign.id, 'campaign', { ...campaign, status: 'running' });
let kb = {};
try { kb = await faGet('/api/kb'); } catch (e) { kb = {}; }
await ingest(campaign.id, 'agent_run', { agent: 'master', label: 'Pipeline Start', status: 'running', started_at: new Date().toISOString() });
return [{ json: { campaign, kb: kb || {} } }];
""", [440, 0])
    ncarry0 = code_node("A0 Carry", """
const p = $json;
return [{ json: { campaign: p.campaign, kb: p.kb || {}, icp: null, candidates: [], qualified_accounts: [], contacts: [], verified_contacts: [], research: [], emails: [] } }];
""", [660, 0])

    stage_input = {
        "A1": "return [{ json: { campaign: p.campaign } }];",
        "A2": "return [{ json: { campaign: p.campaign, icp: p.icp } }];",
        "A3": "return [{ json: { campaign: p.campaign, icp: p.icp, candidates: p.candidates } }];",
        "A4": "return [{ json: { campaign: p.campaign, qualified_accounts: p.qualified_accounts } }];",
        "A5": "return [{ json: { campaign: p.campaign, contacts: p.verified_contacts } }];",
        "A6": "return [{ json: { campaign: p.campaign, qualified_accounts: p.qualified_accounts } }];",
        "A7": "return [{ json: { campaign: p.campaign, kb: p.kb, verified_contacts: p.verified_contacts, research: p.research } }];",
        "A8": "return [{ json: { campaign: p.campaign, emails: p.emails } }];",
    }
    carry_merge = {
        "A1": "r.icp = sub.icp || ctx.icp || null;",
        "A2": "r.candidates = (sub.candidates || []).length ? sub.candidates : ctx.candidates;",
        "A3": "r.qualified_accounts = (sub.qualified_accounts || []).length ? sub.qualified_accounts : ctx.qualified_accounts;",
        "A4": "r.contacts = (sub.contacts || []).length ? sub.contacts : ctx.contacts;",
        "A5": "r.verified_contacts = (sub.verified_contacts || []).length ? sub.verified_contacts : ctx.verified_contacts;",
        "A6": "r.research = (sub.research || []).length ? sub.research : ctx.research;",
        "A7": "r.emails = (sub.emails || []).length ? sub.emails : ctx.emails;",
        "A8": "r.final_emails = (sub.emails || []).length ? sub.emails : ctx.emails;",
    }

    stages = [
        ("A1", "A1 ICP Agent", "TOOLS_LLM", "icp_agent", "ICP Intelligence (SQM fingerprint)"),
        ("A2", "A2 Account Discovery", "TOOLS_LLM", "account_discovery", "Account Discovery (seed + live search)"),
        ("A3", "A3 Account Verification", "TOOLS_LLM", "account_verification", "Account Verification (ICP fit + evidence)"),
        ("A4", "A4 Contact Discovery", "TOOLS_LLM", "contact_discovery", "Contact Discovery (target personas)"),
        ("A5", "A5 Contact Verification", "TOOLS_LLM", "contact_verification", "Contact Verification (real + current)"),
        ("A6", "A6 Deep Research", "TOOLS_LLM", "deep_research", "Deep Research (5 buckets)"),
        ("A7", "A7 Personalization", "TOOLS_LLM", "personalization", "Personalized Email Generation"),
        ("A8", "A8 Fact Checker", "TOOLS_LLM", "fact_checker", "Fact Check + Rewrite"),
    ]
    wf_ids = {
        "A1 ICP Agent": "A1_ICP", "A2 Account Discovery": "A2_DISCOVERY",
        "A3 Account Verification": "A3_VERIFICATION", "A4 Contact Discovery": "A4_CONTACTS",
        "A5 Contact Verification": "A5_CONTACT_VERIFY", "A6 Deep Research": "A6_RESEARCH",
        "A7 Personalization": "A7_EMAILS", "A8 Fact Checker": "A8_FACT_CHECK",
    }

    nodes = [nweb, ninit, nkb, ncarry0]
    conns = edges((nweb["name"], ninit["name"]), (ninit["name"], nkb["name"]), (nkb["name"], ncarry0["name"]))

    prev_name = ncarry0["name"]
    x = 880
    for (key, wf_name, _tool, agent, label) in stages:
        nlog = code_node(label + " start", JS_HELPERS + """
const p = $json;
await ingest(p.campaign.id, 'agent_run', { agent: '""" + agent + """', label: '""" + label + """', status: 'running', started_at: new Date().toISOString() });
return [{ json: p }];
""", [x, 0])
        ninput = code_node(key + " Input", "const p = $json;\n" + stage_input[key], [x + 200, 0])
        nex = exec_wf_node(wf_name, wf_ids[wf_name], [x + 400, 0])
        nend = code_node(label + " end", JS_HELPERS + """
const sub = $json;
const p0 = $('""" + key + """ Input').first().json;
const failed = !sub || sub.status === 'failed' || !sub.stage;
await ingest(p0.campaign.id, 'agent_run_end', {
  agent: '""" + agent + """',
  status: failed ? 'failed' : 'done',
  finished_at: new Date().toISOString(),
  detail: JSON.stringify((sub && sub.counts) || (sub && sub.status) || (sub && sub.reason) || null).slice(0, 400),
  error: failed ? String((sub && (sub.error || sub.message || sub.reason)) || 'sub-workflow execution error (see n8n executions)').slice(0, 400) : null
});
return [{ json: sub || { stage: '""" + agent + """', status: 'failed', error: 'sub-workflow produced no output' } }];
""", [x + 600, 0])
        ncarry = code_node(key + " Carry", "const sub = $json;\nconst ctx = $('" + key + " Input').first().json;\nconst r = { campaign: ctx.campaign, kb: ctx.kb || {} };\nr.icp = ctx.icp || null; r.candidates = ctx.candidates || []; r.qualified_accounts = ctx.qualified_accounts || []; r.contacts = ctx.contacts || []; r.verified_contacts = ctx.verified_contacts || []; r.research = ctx.research || []; r.emails = ctx.emails || [];\n" + carry_merge[key] + "\nreturn [{ json: r }];", [x + 800, 0])
        nodes.extend([nlog, ninput, nex, nend, ncarry])
        conns.update(edges(
            (prev_name, nlog["name"]),
            (nlog["name"], ninput["name"]),
            (ninput["name"], nex["name"]),
            (nex["name"], nend["name"]),
            (nex["name"], nend["name"], 1),
            (nend["name"], ncarry["name"]),
        ))
        prev_name = ncarry["name"]
        x += 1000

    nfinal = code_node("Finish", JS_HELPERS + """
const ctx = $json;
const campaign = ctx.campaign;
let summary = {};
try { summary = await faGet('/api/summary?campaign_id=' + encodeURIComponent(campaign.id)); } catch (e) {}
const failed = (summary && Array.isArray(summary.failed_agents) && summary.failed_agents.length) || false;
await ingest(campaign.id, 'campaign_update', { match: { id: campaign.id }, patch: { status: failed ? 'completed_with_failures' : 'complete', summary } });
return [{ json: { campaign_id: campaign.id, status: failed ? 'completed_with_failures' : 'complete', summary } }];
""", [x + 200, 0])
    nnoop = node("Done", "n8n-nodes-base.noOp", {}, [x + 420, 0], tv=1)
    nodes.extend([nfinal, nnoop])
    conns.update(edges((prev_name, nfinal["name"]), (nfinal["name"], nnoop["name"])))
    return workflow("BDR :: MASTER Orchestrator", nodes, conns,
                    "Master orchestrator: webhook POST /webhook/master; runs the 8-agent pipeline sequentially and logs every agent run.")


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main():
    os.makedirs(OUT, exist_ok=True)
    defs = {
        "tools_search.json": build_tools_search(),
        "tools_fetch.json": build_tools_fetch(),
        "tools_llm.json": build_tools_llm(),
        "a1_icp.json": build_a1(),
        "a2_discovery.json": build_a2(),
        "a3_verification.json": build_a3(),
        "a4_contact_discovery.json": build_a4(),
        "a5_contact_verification.json": build_a5(),
        "a6_research.json": build_a6(),
        "a7_personalization.json": build_a7(),
        "a8_fact_checker.json": build_a8(),
        "master.json": build_master(),
    }
    for fname, wf in defs.items():
        path = os.path.join(OUT, fname)
        with open(path, "w") as f:
            json.dump(wf, f, indent=1)
        print("wrote", path)


if __name__ == "__main__":
    main()
