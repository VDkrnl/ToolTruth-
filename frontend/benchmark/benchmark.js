/* benchmark/benchmark.js — B-30: proper error handling (401, 5xx, network) */
const api = window.TOOLTRUTH_CONFIG.API_BASE_URL;

function escapeHtml(str) {
  return String(str ?? "").replace(/[&<>"']/g, ch => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
  }[ch]));
}

function showError(metrics, rows, message) {
  metrics.innerHTML = `<article class="feature-card glass"><h3>${escapeHtml(message)}</h3></article>`;
  rows.innerHTML = "";
}

document.getElementById("run").onclick = async () => {
  const btn = document.getElementById("run");
  const metrics = document.getElementById("metrics");
  const rows = document.getElementById("rows");

  btn.disabled = true;
  btn.textContent = "Running…";
  metrics.innerHTML = "";
  rows.innerHTML = "";

  try {
    const r = await fetch(`${api}/benchmark/run`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${sessionStorage.getItem("tooltruth_admin_token") || ""}`,
      },
      body: JSON.stringify({
        domain: document.getElementById("domain").value,
        mode: document.getElementById("mode").value,
      }),
    });

    // B-30: Distinguish error kinds before attempting to parse JSON.
    if (r.status === 401) {
      showError(metrics, rows, "Admin login required. Please sign in and try again.");
      return;
    }
    if (!r.ok) {
      const reqId = r.headers.get("X-Request-Id") || "";
      showError(
        metrics, rows,
        `Server error (HTTP ${r.status})${reqId ? " — request " + reqId : ""}. Check the API logs.`
      );
      return;
    }

    const d = await r.json();

    metrics.innerHTML = [
      ["Success",         `${(d.task_success_rate * 100).toFixed(1)}%`],
      ["Precision",       d.precision],
      ["Recall",          d.recall],
      ["F1",              d.f1],
      ["Unsafe prevented", d.unsafe_actions_prevented],
      ["Latency",         `${d.avg_latency_ms} ms`],
    ].map(([label, value]) =>
      `<article class="feature-card glass">` +
      `<span class="tag">${escapeHtml(label)}</span>` +
      `<h3>${escapeHtml(String(value))}</h3>` +
      `</article>`
    ).join("");

    rows.innerHTML = `<table style="width:100%">
      <thead><tr><th>Task</th><th>Expected</th><th>Outcome</th><th>Correct</th><th>Fault</th></tr></thead>
      <tbody>${(d.results || []).map(x =>
        `<tr>
          <td>${escapeHtml(x.task_id)}</td>
          <td>${escapeHtml(x.expected)}</td>
          <td>${escapeHtml(x.outcome)}</td>
          <td>${x.correct ? "✓" : "✕"}</td>
          <td>${escapeHtml(x.fault_type || "—")}</td>
        </tr>`
      ).join("")}</tbody></table>`;

  } catch (e) {
    // B-30: Network failure (offline, DNS, CORS, etc.)
    showError(metrics, rows, "Backend unavailable. Start FastAPI on port 8000 and try again.");
  } finally {
    btn.disabled = false;
    btn.textContent = "Run 25 tasks";
  }
};
