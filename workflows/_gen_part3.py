

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
