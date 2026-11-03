/**
 * ToolTruth runtime configuration.
 *
 * API_BASE_URL is determined at load time from:
 *   1. <meta name="tt-api-base"> (set by the deploy pipeline)
 *   2. http://localhost:8000 when running on localhost
 *   3. The hard-coded production URL as a final fallback
 *
 * Never put API keys or Shopify values here — this file is public.
 */
(function () {
  var metaEl = document.querySelector('meta[name="tt-api-base"]');
  var metaUrl = metaEl ? metaEl.getAttribute("content") : null;

  var apiBase;
  if (metaUrl && metaUrl.trim()) {
    apiBase = metaUrl.trim().replace(/\/$/, "");
  } else if (
    location.hostname === "localhost" ||
    location.hostname === "127.0.0.1"
  ) {
    apiBase = "http://localhost:8000";
  } else {
    // Production fallback — set the <meta> tag at deploy time instead of editing here
    apiBase = "https://api.tooltruth.duckdns.org";
  }

  window.TOOLTRUTH_CONFIG = {
    API_BASE_URL: apiBase,
    DEMO_MODE: false,
    MAX_FILE_SIZE_MB: 25,
    GITHUB_REPO_URL: "https://github.com/VDkrnl/ToolTruth-",
    TEAM: [
      {
        name: "Tejbeer Kaur",
        role: "Team Lead",
        initials: "TK",
        photo: "assets/team/member4.jpeg",
      },
      {
        name: "Shaurya Sharma",
        role: "ML Developer",
        initials: "SS",
        photo: "assets/team/member1.jpeg",
      },
      {
        name: "Raghav Sachdeva",
        role: "Frontend Developer",
        initials: "RS",
        photo: "assets/team/member2.jpeg",
      },
      {
        name: "Vaibhav Dhiman",
        role: "Backend Developer",
        initials: "VD",
        photo: "assets/team/member3.jpeg",
      },
    ],
    STATIC_VERSIONS: [
      {
        slug: "planning",
        title: "Planning Presentation",
        version: "v1",
        date: "2026-08-11",
        authors:
          "Tejbeer Kaur, Shaurya Sharma, Raghav Sachdeva, Vaibhav Dhiman",
        summary:
          "Initial project scope, users, architecture, quality goals and technical risk register.",
        page: "v1.html",
        preview_ready: true,
      },
    ],
  };
})();
