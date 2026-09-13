function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;"
  }[char]));
}

document.addEventListener("DOMContentLoaded", async () => {
  const list = document.getElementById("archive-list");
  let versions = TOOLTRUTH_CONFIG.STATIC_VERSIONS || [];

  try {
    if (!TOOLTRUTH_CONFIG.DEMO_MODE) {
      const remote = await ToolTruthAPI.versions();
      if (Array.isArray(remote) && remote.length) versions = remote;
    }
  } catch (e) {
    console.warn("API unavailable — showing static versions:", e.message);
  }

  if (!versions.length) {
    list.innerHTML = '<p style="color:#888;text-align:center;padding:2rem;">No published versions yet.</p>';
    return;
  }

  list.innerHTML = versions.map(v => {
    const canView = Boolean(v.id && v.preview_ready);
    const action = canView
      ? `<a class="btn btn-primary" href="viewer.html?id=${encodeURIComponent(v.id)}">View presentation →</a>`
      : v.page
        ? `<a class="btn btn-primary" href="${encodeURIComponent(v.page)}">Open →</a>`
        : `<span class="tag">Preview unavailable</span>`;
    return `
      <article class="archive-item glass">
        <span class="version">${escapeHtml(v.version || "v?")}</span>
        <div>
          <strong>${escapeHtml(v.title || "Untitled")}</strong>
          <p>${escapeHtml(v.date || "")} · ${escapeHtml(v.authors || "ToolTruth Team")}<br>${escapeHtml(v.summary || "")}</p>
          ${v.filename ? `<small style="color:var(--muted)">${escapeHtml(v.filename)}</small>` : ""}
        </div>
        ${action}
      </article>`;
  }).join("");
});
