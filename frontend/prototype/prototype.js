(() => {
  const cfg = window.TOOLTRUTH_CONFIG || {};
  const API = (cfg.API_BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
  const $ = id => document.getElementById(id);
  const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, ch => ({
    "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"
  }[ch]));

  let currentRun = null;
  let currentCertificate = null;

  async function request(path, options = {}) {
    const headers = {...(options.headers || {})};
    if (!(options.body instanceof FormData)) headers["Content-Type"] = "application/json";
    const res = await fetch(`${API}${path}`, {...options, headers});
    if (!res.ok) {
      const text = await res.text();
      let msg = text || `HTTP ${res.status}`;
      try { const body = JSON.parse(text); msg = body.detail || msg; } catch (_) {}
      throw new Error(Array.isArray(msg) ? msg.map(x => x.msg || JSON.stringify(x)).join("; ") : msg);
    }
    return res.json();
  }

  function toast(message, good = false) {
    const el = $("toast"); el.textContent = message;
    el.className = `toast show ${good ? "good" : "bad"}`;
    setTimeout(() => el.classList.remove("show"), 3200);
  }

  const defaults = {
    ecommerce: {
      entity: "SKU-100",
      actions: {
        get_inventory: {product_id:"SKU-100"},
        reserve: {product_id:"SKU-100", quantity:1},
        sell: {product_id:"SKU-102"},
        return: {product_id:"SKU-103"}
      }
    },
    travel: {
      entity: "SEAT-12A",
      actions: {
        get_availability: {seat_id:"SEAT-12A"},
        hold: {seat_id:"SEAT-12A", booking_id:"BKG-100"},
        confirm: {booking_id:"BKG-100"},
        check_in: {booking_id:"BKG-101"},
        board: {booking_id:"BKG-101"},
        cancel: {booking_id:"BKG-100"}
      }
    },
    devops: {
      entity: "ISS-100",
      actions: {
        get_issue: {issue_id:"ISS-100"},
        start: {issue_id:"ISS-100"},
        review: {issue_id:"ISS-101"},
        merge: {issue_id:"ISS-101"},
        close_issue: {issue_id:"ISS-101"},
        reopen: {issue_id:"ISS-104"},
        deploy: {deployment_id:"DEP-100", environment:"staging"}
      }
    },
    shopify_content: {
      entity: "product-id",
      actions: {
        // READ tools
        list_products:       {query:"", limit:10},
        get_product:         {product_id:"<product-id>"},
        list_pages:          {limit:10},
        get_page:            {page_id:"<page-id>"},
        list_blogs:          {limit:10},
        list_blog_articles:  {blog_id:"<blog-id>", limit:10},
        get_blog_article:    {blog_id:"<blog-id>", article_id:"<article-id>"},
        list_collections:    {limit:10},
        get_collection:      {collection_id:"<collection-id>"},
        get_metafields:      {owner_resource:"product", owner_id:"<product-id>"},
        // WRITE tools
        create_product:      {title:"New Product", body_html:"<p>Description</p>", vendor:"", product_type:"", tags:"", status:"draft"},
        update_product:      {product_id:"<product-id>", title:"", body_html:"", status:""},
        create_page:         {title:"New Page", body_html:"<p>Content</p>", published:false},
        update_page:         {page_id:"<page-id>", title:"", body_html:"", published:null},
        create_blog_article: {blog_id:"<blog-id>", title:"New Article", body_html:"<p>Content</p>", author:"", tags:"", published:false},
        update_blog_article: {blog_id:"<blog-id>", article_id:"<article-id>", title:"", body_html:""},
        set_metafield:       {owner_resource:"product", owner_id:"<product-id>", namespace:"custom", key:"label", value:"", value_type:"string"}
      }
    }
  };

  function setPayloadForAction() {
    const domain = $("domain").value, action = $("action").value;
    const template = {...(defaults[domain]?.actions[action] || {})};
    const id = $("entity-id").value.trim();
    if (domain === "ecommerce") template.product_id = id || template.product_id || "SKU-100";
    if (domain === "travel") {
      if (["hold","get_availability"].includes(action)) template.seat_id = id || template.seat_id || "SEAT-12A";
      if (["confirm","check_in","board","cancel"].includes(action)) template.booking_id = id || template.booking_id || "BKG-100";
    }
    if (domain === "devops") {
      if (action === "deploy") template.deployment_id = id || "DEP-100";
      else template.issue_id = id || template.issue_id || "ISS-100";
    }
    if (domain === "shopify_content") {
      // Inject the entity-id field into whichever key the template uses.
      if ("product_id" in template)    template.product_id    = id || template.product_id;
      if ("page_id" in template)       template.page_id       = id || template.page_id;
      if ("blog_id" in template)       template.blog_id       = id || template.blog_id;
      if ("article_id" in template)    template.article_id    = id || template.article_id;
      if ("collection_id" in template) template.collection_id = id || template.collection_id;
      if ("owner_id" in template)      template.owner_id      = id || template.owner_id;
    }
    $("payload").value = JSON.stringify(template, null, 2);
  }

  function renderStateMachine(data) {
    const graph = $("state-graph");
    const states = data.states;
    const firstIndex = {};
    data.transitions.forEach(t => { if (firstIndex[t.from_state] === undefined) firstIndex[t.from_state] = t; });
    graph.innerHTML = `<div class="state-track">${
      states.map((state, i) => `<div class="state-node"><b>${escapeHtml(state)}</b><small>${i + 1}</small></div>`).join("")
    }</div><div class="transition-list">${
      data.transitions.map(t => `<div class="state-transition"><strong>${escapeHtml(t.from_state)} → ${escapeHtml(t.to_state)}</strong><span>${escapeHtml(t.action)}</span><small>pre: ${escapeHtml(t.preconditions.join("; ") || "—")} · post: ${escapeHtml(t.postconditions.join("; ") || "—")} · TTL ${t.freshness_ttl_seconds}s</small></div>`).join("")
    }</div>`;

    $("state-machine-meta").innerHTML = `
      <div class="fact-grid">
        <div><b>Domain facts</b><small>${data.facts.map(x=>escapeHtml(x.name)).join(", ") || "None"}</small></div>
        <div><b>Workflow rules</b><small>${data.workflow_rules.map(x=>escapeHtml(x.name)).join(", ") || "None"}</small></div>
        <div><b>User constraints</b><small>${data.user_constraints.map(x=>escapeHtml(x.name)).join(", ") || "None"} <em>not consistency invariants</em></small></div>
      </div>
      <p class="muted">Schema ${escapeHtml(data.schema_version)} · ${data.entities.length} demo entities · ${data.transitions.length} legal transitions</p>`;
  }

  async function loadDomain() {
    const domain = $("domain").value;

    // ── Shopify Content: no state-machine endpoint; populate from local defaults. ──
    if (domain === "shopify_content") {
      $("state-graph").innerHTML =
        `<div class="state-track"><div class="state-node"><b>Shopify Content Agent</b><small>Manage products, pages, blogs, collections and metafields.</small></div></div>`;
      $("state-machine-meta").innerHTML =
        `<p class="muted">Shopify Content mode — read/write store content via the Shopify Admin API. No order placement.</p>`;
      const actionNames = Object.keys(defaults.shopify_content.actions);
      $("action").innerHTML = actionNames.map(a => `<option value="${escapeHtml(a)}">${escapeHtml(a)}</option>`).join("");
      $("entity-id").value = defaults.shopify_content.entity;
      setPayloadForAction();
      $("api-status").textContent = "Content mode";
      $("api-status").className = "severity-chip severity-low";
      $("comparison-body").innerHTML = `<tr><td colspan="8">Comparison metrics are not available for the Shopify Content agent.</td></tr>`;
      return;
    }

    try {
      const data = await request(`/prototype/state-machine/${domain}`);
      renderStateMachine(data);
      const actionNames = [...new Set(data.transitions.map(t => t.action))];
      // Add read-only actions that don't create a state transition.
      if (domain === "ecommerce") actionNames.unshift("get_inventory");
      if (domain === "travel") actionNames.unshift("get_availability");
      if (domain === "devops") actionNames.unshift("get_issue");
      $("action").innerHTML = [...new Set(actionNames)].map(a => `<option value="${escapeHtml(a)}">${escapeHtml(a)}</option>`).join("");
      $("entity-id").value = defaults[domain].entity;
      setPayloadForAction();
      await loadMetrics();
      $("api-status").textContent = "API online";
      $("api-status").className = "severity-chip severity-low";
    } catch (err) {
      $("api-status").textContent = "API offline";
      $("api-status").className = "severity-chip severity-critical";
      toast(`Could not load prototype API: ${err.message}`);
    }
  }

  function activeFault() {
    const selected = document.querySelector(".fault-toggle input:checked");
    if (!selected) return null;
    const type = selected.dataset.fault;
    const params = {};
    if (type === "stale_evidence") params.age_seconds = Number($("stale-age").value);
    if (type === "contradictory_observation") {
      params.field = $("conflict-field").value.trim() || "price";
      const raw = $("conflict-value").value;
      params.value = raw !== "" && !Number.isNaN(Number(raw)) ? Number(raw) : raw;
    }
    if (type === "invalid_transition" && $("forced-state").value.trim()) params.forced_state = $("forced-state").value.trim();
    const severityEl = document.querySelector(`[data-severity-for="${CSS.escape(type)}"]`);
    return {type, severity:severityEl ? severityEl.value : "medium", params};
  }

  function decisionClass(decision) {
    return decision === "allow" ? "allow" : decision === "block" ? "block" : "request";
  }

  function renderResult(run) {
    const decision = run.decision || (run.allowed ? "allow" : "block");
    const checks = run.checks || [];
    $("run-id").textContent = `RUN ${run.run_id}`;
    $("result").innerHTML = `
      <div class="decision-badge ${decisionClass(decision)}">${escapeHtml(decision.replaceAll("_"," ").toUpperCase())}</div>
      <div class="result-summary">
        <div><b>State version</b><span>${escapeHtml(run.state_version_before || "—")} → ${escapeHtml(run.state_version_after || "—")}</span></div>
        <div><b>Entity</b><span>${escapeHtml(run.entity_id)}</span></div>
        <div><b>Reason</b><span>${escapeHtml(run.reason || "All checks passed.")}</span></div>
      </div>
      <h3>Rules evaluated</h3>
      <div class="check-list proto-checks">${checks.map(c => `<div class="${c.passed ? "check-pass":"check-fail"}"><b>${c.passed ? "PASS":"FAIL"} · ${escapeHtml(c.name)}</b><span>${escapeHtml(c.reason)}</span></div>`).join("")}</div>
      <h3>Evidence used</h3>
      <div class="table-wrap"><table><thead><tr><th>Node</th><th>Claim</th><th>Source</th><th>Confidence</th><th>Freshness</th></tr></thead><tbody>${
        (run.evidence_nodes || run.evidence_trail || []).map(n => {
          const age = n.timestamp ? Math.max(0, Math.floor((Date.now()-Date.parse(n.timestamp))/1000)) : null;
          const fresh = age !== null && age <= 300 ? "fresh" : "stale";
          return `<tr><td>${escapeHtml(n.id)}</td><td>${escapeHtml(n.claim)}</td><td>${escapeHtml(n.source)}</td><td>${escapeHtml(n.confidence)}</td><td>${fresh} · ${age ?? "—"}s</td></tr>`;
        }).join("") || `<tr><td colspan="5">No evidence nodes recorded.</td></tr>`
      }</tbody></table></div>`;
    $("certificate-card").hidden = false;
    $("generate-cert").disabled = false;
    $("download-cert").disabled = true;
    currentCertificate = null;
  }

  function renderCertificate(cert) {
    currentCertificate = cert;
    $("certificate").innerHTML = `
      <div class="certificate-head"><div><b>${escapeHtml(cert.certificate_id)}</b><small>${escapeHtml(cert.timestamp)}</small></div><span class="decision-badge ${decisionClass(cert.decision)}">${escapeHtml(cert.decision.replaceAll("_"," ").toUpperCase())}</span></div>
      <div class="cert-meta"><span><b>Domain</b>${escapeHtml(cert.domain)}</span><span><b>Action</b>${escapeHtml(cert.action)}</span><span><b>Entity</b>${escapeHtml(cert.entity_id)}</span><span><b>Verifier</b>${escapeHtml(cert.verifier_version)}</span><span><b>Schema</b>${escapeHtml(cert.schema_version)}</span></div>
      <div class="table-wrap"><table><thead><tr><th>Node</th><th>Claim</th><th>Source</th><th>Confidence</th><th>Age</th><th>Status</th></tr></thead><tbody>${
        cert.evidence.map(e=>`<tr><td>${escapeHtml(e.node_id)}</td><td>${escapeHtml(e.claim)}</td><td>${escapeHtml(e.source)}</td><td>${escapeHtml(e.confidence)}</td><td>${escapeHtml(e.age_at_decision_seconds)}s</td><td>${escapeHtml(e.freshness_status)}</td></tr>`).join("") || `<tr><td colspan="6">No evidence.</td></tr>`
      }</tbody></table></div>
      <div class="table-wrap"><table><thead><tr><th>Rule</th><th>Outcome</th><th>Reason</th></tr></thead><tbody>${
        cert.rules.map(r=>`<tr><td>${escapeHtml(r.name)}</td><td>${escapeHtml(r.outcome)}</td><td>${escapeHtml(r.reason)}</td></tr>`).join("")
      }</tbody></table></div>
      <div class="fingerprint"><b>SHA-256</b><code>${escapeHtml(cert.sha256_fingerprint)}</code></div>`;
    $("download-cert").disabled = false;
  }

  function downloadCertificate() {
    if (!currentCertificate) return;
    const blob = new Blob([JSON.stringify(currentCertificate, null, 2)], {type:"application/json"});
    const url = URL.createObjectURL(blob), a = document.createElement("a");
    a.href=url; a.download=`tooltruth-${currentCertificate.certificate_id}.json`;
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
  }

  async function runSimulation() {
    let payload;
    try { payload = JSON.parse($("payload").value || "{}"); }
    catch (_) { toast("Payload is not valid JSON."); return; }

    const domain = $("domain").value, action = $("action").value;
    const id = $("entity-id").value.trim();
    if (domain === "ecommerce") payload.product_id = id;
    if (domain === "travel" && ["hold","get_availability"].includes(action)) payload.seat_id = id;
    if (domain === "travel" && ["confirm","check_in","board","cancel"].includes(action)) payload.booking_id = id;
    if (domain === "devops" && action === "deploy") payload.deployment_id = id;
    if (domain === "devops" && action !== "deploy") payload.issue_id = id;
    // shopify_content: IDs are already embedded in the payload template.

    const context = {};
    if ($("budget-enabled").checked && $("budget-limit").value !== "") {
      context.budget_limit = Number($("budget-limit").value);
      if (domain === "ecommerce") payload.budget_limit = context.budget_limit;
    }
    try {
      $("run").disabled = true; $("run").textContent = "Running…";
      const run = await request("/prototype/simulate", {
        method:"POST", body:JSON.stringify({
          domain, action, payload, agent_id:"prototype-ui",
          fault_config:activeFault(), context_snapshot:context
        })
      });
      currentRun = run; renderResult(run);
      renderMetrics(run.comparison_metrics || []);
      toast("Simulation completed.", true);
    } catch (err) { toast(err.message); }
    finally { $("run").disabled=false; $("run").innerHTML="Run Simulation <span>→</span>"; }
  }

  function renderMetrics(rows) {
    $("comparison-body").innerHTML = rows.map(r => `<tr>
      <td><b>${escapeHtml(r.mode)}</b></td><td>${Number(r.detection_precision).toFixed(3)}</td>
      <td>${Number(r.detection_recall).toFixed(3)}</td><td>${Number(r.false_block_rate).toFixed(3)}</td>
      <td>${escapeHtml(r.unsafe_actions_prevented)}</td><td>${Number(r.task_success).toFixed(3)}</td>
      <td>${Number(r.avg_latency_ms).toFixed(2)} ms</td><td>${escapeHtml(r.token_overhead)}</td>
    </tr>`).join("");
  }

  async function loadMetrics() {
    try { renderMetrics(await request(`/prototype/comparison-metrics?domain=${encodeURIComponent($("domain").value)}`)); }
    catch (_) { $("comparison-body").innerHTML = `<tr><td colspan="8">Metrics unavailable until the backend is running.</td></tr>`; }
  }

  async function generateCertificate() {
    if (!currentRun?.run_id) return;
    try {
      $("generate-cert").disabled = true;
      const cert = await request("/prototype/certificate", {method:"POST",body:JSON.stringify({run_id:currentRun.run_id})});
      renderCertificate(cert); toast("Certificate generated.", true);
    } catch (err) { toast(err.message); $("generate-cert").disabled=false; }
  }

  document.addEventListener("DOMContentLoaded", () => {
    $("domain").addEventListener("change", loadDomain);
    $("action").addEventListener("change", setPayloadForAction);
    $("entity-id").addEventListener("change", setPayloadForAction);
    $("run").addEventListener("click", runSimulation);
    $("generate-cert").addEventListener("click", generateCertificate);
    $("download-cert").addEventListener("click", downloadCertificate);
    $("stale-age").addEventListener("input", e => { $("stale-age-label").textContent=e.target.value; $("stale-age-output").value=e.target.value; });
    document.querySelectorAll(".fault-toggle input").forEach(input => input.addEventListener("change", e => {
      if (e.target.checked) document.querySelectorAll(".fault-toggle input").forEach(other => { if(other!==e.target) other.checked=false; });
    }));
    loadDomain();
    document.querySelector(".nav-toggle")?.addEventListener("click",()=>document.querySelector(".site-nav").classList.toggle("mobile-open"));
  });
})();