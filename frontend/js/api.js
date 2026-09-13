window.ToolTruthAPI = (() => {
  const cfg = window.TOOLTRUTH_CONFIG;
  const tokenKey = "tooltruth_admin_token";
  async function request(path, options = {}) {
    const headers = options.headers || {};
    const token = sessionStorage.getItem(tokenKey);
    if (token) headers.Authorization = `Bearer ${token}`;
    if (!(options.body instanceof FormData)) headers["Content-Type"] = "application/json";
    const res = await fetch(`${cfg.API_BASE_URL}${path}`, { ...options, headers });
    if (!res.ok) {
      const bodyText = await res.text();
      let message = bodyText || `HTTP ${res.status}`;
      try {
        const parsed = JSON.parse(bodyText);
        if (parsed && parsed.detail) {
          if (Array.isArray(parsed.detail)) {
            message = parsed.detail.map(d => d.msg || JSON.stringify(d)).join("; ");
          } else if (typeof parsed.detail === "string") {
            message = parsed.detail;
          }
        }
      } catch (e) {
        // Not JSON — fall back to the raw text already assigned above.
      }
      throw new Error(message);
    }
    return res.status === 204 ? null : res.json();
  }
  return {
    tokenKey,
    login: (username, password) => request("/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }),
    upload: (file, onProgress) => {
      if (cfg.DEMO_MODE) return Promise.resolve({ id: "demo-upload", status: "uploaded", filename: file.name });
      return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest(); xhr.open("POST", `${cfg.API_BASE_URL}/uploads`);
        const token = sessionStorage.getItem(tokenKey); if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
        xhr.upload.onprogress = e => { if (e.lengthComputable && onProgress) onProgress(Math.round(e.loaded / e.total * 100)) };
        xhr.onload = () => xhr.status >= 200 && xhr.status < 300 ? resolve(JSON.parse(xhr.responseText)) : reject(new Error(xhr.responseText));
        xhr.onerror = () => reject(new Error("Network error"));
        const fd = new FormData(); fd.append("file", file); xhr.send(fd);
      });
    },
    publish: (data) => request("/publish", { method: "POST", body: JSON.stringify(data) }),
    versions: () => request("/versions"),
    fileUrl: (versionId) => request(`/files/${encodeURIComponent(versionId)}`),
    deleteVersion: (id) => request(`/versions/${encodeURIComponent(id)}`, { method: "DELETE" })
  };
})();