function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;"
  }[char]));
}

document.addEventListener("DOMContentLoaded", () => {
  const nav = document.querySelector(".site-nav");
  const toggle = document.querySelector(".nav-toggle");

  if (toggle) {
    toggle.onclick = () => nav.classList.toggle("mobile-open");
  }

  const team = document.getElementById("team-grid");

  if (team) {
    team.innerHTML = TOOLTRUTH_CONFIG.TEAM.map(m => `
      <article class="team-card glass">
        <div class="avatar">
          ${m.photo
        ? `<img src="${escapeHtml(m.photo)}" alt="${escapeHtml(m.name)}" class="team-photo">`
        : escapeHtml(m.initials)
      }
        </div>
        <h3>${escapeHtml(m.name)}</h3>
        <p>${escapeHtml(m.role)}</p>
      </article>
    `).join("");
  }

  const list = document.getElementById("deliverables");

  if (list) {
    list.innerHTML = TOOLTRUTH_CONFIG.STATIC_VERSIONS.map(v => `
      <a class="timeline-item glass" href="presentations/${encodeURIComponent(v.page)}">
        <span class="version">${escapeHtml(v.version)}</span>
        <div>
          <strong>${escapeHtml(v.title)}</strong><br>
          <small>${escapeHtml(v.summary)}</small>
        </div>
        <small>${escapeHtml(v.date)} →</small>
      </a>
    `).join("");
  }
});