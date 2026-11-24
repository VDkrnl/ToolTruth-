/* evidence/evidence.js  — B-33: replace innerHTML with server data with textContent/createElement */
const api = window.TOOLTRUTH_CONFIG.API_BASE_URL;

function escapeHtml(str) {
  return String(str ?? "").replace(/[&<>"']/g, ch => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
  }[ch]));
}

function buildNodeCard(n) {
  const article = document.createElement("article");
  article.className = "feature-card glass";

  const tag = document.createElement("span");
  tag.className = "tag";
  tag.textContent = n.node_type;
  article.appendChild(tag);

  const h3 = document.createElement("h3");
  h3.textContent = n.claim;
  article.appendChild(h3);

  const p = document.createElement("p");
  p.textContent = `Source: ${n.source}`;
  p.appendChild(document.createElement("br"));
  p.appendChild(document.createTextNode(`Confidence: ${n.confidence}`));
  p.appendChild(document.createElement("br"));
  p.appendChild(document.createTextNode(n.timestamp || ""));
  article.appendChild(p);

  return article;
}

async function loadEvidence() {
  const id = document.getElementById("entity").value;
  const box = document.getElementById("result");
  box.textContent = "";
  try {
    const r = await fetch(`${api}/gateway/evidence/${encodeURIComponent(id)}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const d = await r.json();
    if (d.nodes && d.nodes.length) {
      d.nodes.forEach(n => box.appendChild(buildNodeCard(n)));
    } else {
      const article = document.createElement("article");
      article.className = "feature-card glass";
      const h3 = document.createElement("h3");
      h3.textContent = "No evidence yet";
      const p = document.createElement("p");
      p.textContent = "Run a gateway call for this entity.";
      article.appendChild(h3);
      article.appendChild(p);
      box.appendChild(article);
    }
  } catch (e) {
    const article = document.createElement("article");
    article.className = "feature-card glass";
    const h3 = document.createElement("h3");
    h3.textContent = "Backend unavailable";
    const p = document.createElement("p");
    p.textContent = "Start FastAPI on port 8000.";
    article.appendChild(h3);
    article.appendChild(p);
    box.appendChild(article);
  }
}

async function gatewayCall() {
  const domain = document.getElementById("domain").value;
  const action = document.getElementById("action").value;
  let payload = {};
  if (domain === "ecommerce" && action === "get_inventory") payload = { product_id: "SKU-100" };
  if (domain === "ecommerce" && action === "reserve") payload = { product_id: "SKU-100", quantity: 1 };
  if (domain === "devops" && action === "deploy") payload = { environment: "prod" };
  if (domain === "travel" && action === "hold") payload = { seat_id: "SEAT-12A" };

  try {
    const r = await fetch(`${api}/gateway/call`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ domain, action, payload, agent_id: "website-demo" })
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const callout = document.getElementById("callout");
    // Use textContent — JSON has no HTML risk but we never use innerHTML with server data.
    callout.textContent = JSON.stringify(await r.json(), null, 2);
    loadEvidence();
  } catch (e) {
    const callout = document.getElementById("callout");
    callout.textContent = `Error: ${e.message}`;
  }
}

document.getElementById("load").onclick = loadEvidence;
document.getElementById("call").onclick = gatewayCall;
loadEvidence();
