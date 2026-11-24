document.addEventListener("DOMContentLoaded", () => {
  // B-31: named helper instead of repeated getElementById calls.
  const $ = id => document.getElementById(id);

  // B-31: 401 interceptor — clear token and redirect to login.
  function handle401() {
    sessionStorage.removeItem(ToolTruthAPI.tokenKey);
    location.href = "login.html";
  }

  const loginForm = $("login-form");

  if (loginForm) {
    loginForm.onsubmit = async e => {
      e.preventDefault();
      const err = $("login-error");
      err.textContent = "";
      const username = $("username");
      const password = $("password");
      try {
        const r = await ToolTruthAPI.login(username.value, password.value);
        sessionStorage.setItem(ToolTruthAPI.tokenKey, r.access_token);
        location.href = "dashboard.html";
      } catch (x) {
        // B-31: Surface 401 specifically.
        if (x?.status === 401 || x?.message?.includes("401")) {
          err.textContent = "Invalid credentials. Please try again.";
        } else {
          err.textContent = "Login failed. Check your credentials or API connection.";
        }
      }
    };
    return;
  }

  if (!sessionStorage.getItem(ToolTruthAPI.tokenKey) && !TOOLTRUTH_CONFIG.DEMO_MODE) {
    location.href = "login.html";
    return;
  }

  const fileInput = $("file-input");
  const folderInput = $("folder-input");
  const chooseFolderBtn = $("choose-folder");
  const drop = $("drop-zone");
  const nameEl = $("file-name");
  const progress = $("upload-progress") || document.querySelector(".progress");
  const bar = document.querySelector(".progress span");
  const status = $("upload-status");

  let selected = null;
  let uploadId = null;

  function setStatus(message) {
    if (status) status.textContent = message;
  }

  function validateSize(file) {
    const max = TOOLTRUTH_CONFIG.MAX_FILE_SIZE_MB * 1024 * 1024;
    if (file.size > max) {
      toast(`File exceeds ${TOOLTRUTH_CONFIG.MAX_FILE_SIZE_MB} MB`, "bad");
      return false;
    }
    return true;
  }

  function choose(file) {
    if (!file) return;
    if (!validateSize(file)) return;

    selected = file;
    if (nameEl) nameEl.textContent = file.name;
    setStatus(`${(file.size / 1024 / 1024).toFixed(2)} MB ready`);
  }

  async function zipFiles(files, archiveName = "deliverable-folder.zip") {
    if (typeof JSZip === "undefined") {
      throw new Error("Folder upload library could not be loaded. Refresh the page and try again.");
    }

    const zip = new JSZip();
    let totalBytes = 0;

    for (const file of files) {
      totalBytes += file.size;
      if (totalBytes > TOOLTRUTH_CONFIG.MAX_FILE_SIZE_MB * 1024 * 1024) {
        throw new Error(`The folder contents exceed ${TOOLTRUTH_CONFIG.MAX_FILE_SIZE_MB} MB.`);
      }

      // webkitRelativePath preserves the selected folder structure.
      const relativePath = file.webkitRelativePath || file.name;
      zip.file(relativePath, file);
    }

    setStatus("Compressing folder…");
    const blob = await zip.generateAsync({ type: "blob", compression: "DEFLATE", compressionOptions: { level: 6 } });

    if (!validateSize(blob)) {
      throw new Error(`Compressed folder exceeds ${TOOLTRUTH_CONFIG.MAX_FILE_SIZE_MB} MB.`);
    }

    return new File([blob], archiveName, { type: "application/zip" });
  }

  async function chooseFolderFiles(files) {
    if (!files || !files.length) return;

    try {
      const rootName = (files[0].webkitRelativePath || files[0].name).split("/")[0] || "folder";
      const zipFile = await zipFiles(Array.from(files), `${rootName}.zip`);
      choose(zipFile);
      setStatus(`${(zipFile.size / 1024 / 1024).toFixed(2)} MB ready · folder zipped`);
    } catch (error) {
      selected = null;
      if (nameEl) nameEl.textContent = "";
      setStatus("");
      toast(error.message || "Could not zip folder", "bad");
    }
  }

  async function collectDroppedFiles(items) {
    const entries = Array.from(items)
      .map(item => item.webkitGetAsEntry?.())
      .filter(Boolean);

    const files = [];

    async function walk(entry, prefix = "") {
      if (entry.isFile) {
        const file = await new Promise((resolve, reject) => entry.file(resolve, reject));
        if (prefix) {
          try {
            Object.defineProperty(file, "webkitRelativePath", { value: `${prefix}${file.name}` });
          } catch (_) {}
        }
        files.push(file);
        return;
      }

      if (entry.isDirectory) {
        const reader = entry.createReader();
        const readAll = () => new Promise((resolve, reject) => {
          const all = [];
          const next = () => reader.readEntries(batch => {
            if (!batch.length) return resolve(all);
            all.push(...batch);
            next();
          }, reject);
          next();
        });

        const children = await readAll();
        for (const child of children) {
          await walk(child, `${prefix}${entry.name}/`);
        }
      }
    }

    for (const entry of entries) await walk(entry);
    return files;
  }

  if (fileInput) {
    fileInput.onchange = () => choose(fileInput.files[0]);
  }

  if (folderInput) {
    folderInput.onchange = () => chooseFolderFiles(folderInput.files);
  }

  chooseFolderBtn?.addEventListener("click", () => folderInput?.click());

  if (drop) {
    ["dragenter", "dragover"].forEach(eventName => {
      drop.addEventListener(eventName, e => {
        e.preventDefault();
        drop.classList.add("drag");
      });
    });

    ["dragleave", "drop"].forEach(eventName => {
      drop.addEventListener(eventName, e => {
        e.preventDefault();
        drop.classList.remove("drag");
      });
    });

    drop.addEventListener("drop", async e => {
      const items = e.dataTransfer?.items;
      if (items && Array.from(items).some(item => item.webkitGetAsEntry?.()?.isDirectory)) {
        try {
          setStatus("Reading folder…");
          const files = await collectDroppedFiles(items);
          if (!files.length) throw new Error("The dropped folder is empty.");
          const rootName = (files[0].webkitRelativePath || files[0].name).split("/")[0] || "folder";
          const zipFile = await zipFiles(files, `${rootName}.zip`);
          choose(zipFile);
          setStatus(`${(zipFile.size / 1024 / 1024).toFixed(2)} MB ready · folder zipped`);
        } catch (error) {
          selected = null;
          if (nameEl) nameEl.textContent = "";
          setStatus("");
          toast(error.message || "Could not read dropped folder", "bad");
        }
        return;
      }

      const file = e.dataTransfer?.files?.[0];
      choose(file);
    });
  }

  const today = new Date().toISOString().slice(0, 10);
  const date = $("date");
  if (date) date.value = today;

  const form = $("publish-form");

  // B-31: Wrap all API calls with 401 detection.
  async function apiCallWithAuth(fn) {
    try {
      return await fn();
    } catch (x) {
      if (x?.status === 401 || x?.message?.includes("401") || x?.message?.includes("Unauthorized")) {
        handle401();
        return null;
      }
      throw x;
    }
  }

  if (form) {
    form.onsubmit = async e => {
      e.preventDefault();

      if (!selected) {
        toast("Select a file or folder first", "bad");
        return;
      }

      try {
        if (progress) progress.style.display = "block";
        const r = await apiCallWithAuth(() => ToolTruthAPI.upload(selected, p => {
          if (bar) bar.style.width = p + "%";
        }));
        if (!r) return;

        uploadId = r.id;
        setStatus("Upload complete.");

        const pub = await apiCallWithAuth(() => ToolTruthAPI.publish({
          upload_id: uploadId,
          title: $("title")?.value,
          slug: $("slug")?.value,
          version: $("version")?.value,
          date: date?.value,
          authors: $("authors")?.value,
          summary: $("summary")?.value,
        }));
        if (!pub) return;

        toast("Published successfully", "good");
        addHistory(pub);
        form.reset();
        if (date) date.value = today;
        if (nameEl) nameEl.textContent = "";
        if (bar) bar.style.width = "0%";
        if (progress) progress.style.display = "none";
        selected = null;
        uploadId = null;
      } catch (x) {
        toast(x.message || "Publish failed", "bad");
      }
    };
  }

  $("logout")?.addEventListener("click", () => {
    sessionStorage.removeItem(ToolTruthAPI.tokenKey);
    location.href = "login.html";
  });

  $("refresh")?.addEventListener("click", loadHistory);

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, char => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;",
    }[char]));
  }

  function historyRow(v) {
    const view = v.id && v.preview_ready
      ? `<a class="btn btn-ghost btn-small" href="../presentations/viewer.html?id=${encodeURIComponent(v.id)}">View</a>`
      : `<span class="muted">No preview</span>`;

    const del = v.id && !String(v.id).startsWith("demo-")
      ? `<button class="btn btn-danger btn-small delete-presentation" data-id="${encodeURIComponent(v.id)}" data-title="${escapeHtml(v.title || "this presentation")}">Delete</button>`
      : "";

    return `<tr data-version-id="${escapeHtml(v.id || "")}">
      <td>${escapeHtml(v.title || "Upload")}</td>
      <td>${escapeHtml(v.version || "—")}</td>
      <td><span class="tag">Published</span></td>
      <td>${escapeHtml(v.date || "")}</td>
      <td><div class="history-actions">${view}${del}</div></td>
    </tr>`;
  }

  function addHistory(v) {
    const tbody = $("history");
    if (!tbody) return;
    tbody.insertAdjacentHTML("afterbegin", historyRow(v));
  }

  async function loadHistory() {
    const tbody = $("history");
    if (!tbody) return;

    let data = TOOLTRUTH_CONFIG.STATIC_VERSIONS || [];

    try {
      if (!TOOLTRUTH_CONFIG.DEMO_MODE) {
        data = await apiCallWithAuth(() => ToolTruthAPI.versions()) ?? data;
      }
    } catch (e) {
      console.warn("Could not load publishing history:", e);
    }

    tbody.innerHTML = data.map(historyRow).join("");
  }

  $("history")?.addEventListener("click", async e => {
    const button = e.target.closest(".delete-presentation");
    if (!button) return;

    const id = button.dataset.id;
    const title = button.dataset.title || "this presentation";

    if (!confirm(`Delete "${title}"? This removes the presentation file and its preview permanently.`)) return;

    button.disabled = true;
    button.textContent = "Deleting…";

    try {
      await apiCallWithAuth(() => ToolTruthAPI.deleteVersion(id));
      button.closest("tr")?.remove();
      toast("Presentation deleted successfully", "good");
    } catch (err) {
      button.disabled = false;
      button.textContent = "Delete";
      toast(err.message || "Delete failed", "bad");
    }
  });

  function toast(msg, type = "good") {
    const t = $("toast");
    if (!t) return;
    t.textContent = msg;
    t.className = `toast show ${type}`;
    setTimeout(() => t.className = "toast", 2800);
  }

  loadHistory();
});
