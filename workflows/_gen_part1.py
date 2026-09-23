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
