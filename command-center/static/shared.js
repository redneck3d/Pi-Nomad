// Helpers shared by the dashboard and manager pages.
const GB = 1024 ** 3;
const fmt = b => b >= GB ? (b / GB).toFixed(1) + " GB" : (b / 1048576).toFixed(b >= 1048576 * 10 ? 0 : 1) + " MB";
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[c]));
const $ = id => document.getElementById(id);

async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && data.locked) {      // admin PIN needed: ask for it, then try again
    if (typeof Admin !== "undefined" && await Admin.unlock()) return api(path, body);
    throw new Error("The admin PIN is needed for that.");
  }
  if (!res.ok || data.error) throw new Error(data.error || res.statusText);
  return data;
}

// Render running/finished jobs of one kind into an element; calls onDone when a job finishes.
function watchJobs(kind, el, onDone) {
  const seen = {};
  async function tick() {
    try {
      const jobs = (await api("/api/jobs")).filter(j => j.kind === kind);
      el.innerHTML = jobs.length ? jobs.map(j => {
        const pct = j.total ? Math.min(100, j.done / j.total * 100) : 0;
        const live = j.state === "running" || j.state === "queued";
        const note = j.state === "error" ? `<span class="err">${esc(j.message)}</span>`
          : j.state === "done" ? '<span class="ok">Done</span>'
          : j.state === "queued" ? "Waiting for the current job"
          : `${j.total && kind === "zim" ? fmt(j.done) + " of " + fmt(j.total) + " " : ""}${esc(j.message)}`;
        return `<div class="panel"><div class="row"><b>${esc(j.title)}</b><span class="mut">${esc(j.state)}</span>
          ${live ? `<button class="del" onclick="cancelJob('${j.id}')">Cancel</button>` : ""}</div>
          ${live ? `<div class="prog"><i style="width:${pct}%"></i></div>` : ""}<div class="mut">${note}</div></div>`;
      }).join("") : '<span class="mut">Nothing in progress.</span>';
      jobs.forEach(j => { if (seen[j.id] && seen[j.id] !== j.state && j.state === "done") onDone && onDone(); seen[j.id] = j.state; });
    } catch (e) { /* server restarting; try again */ }
  }
  tick(); setInterval(tick, 2000);
}
async function cancelJob(id) { try { await api("/api/jobs/cancel", { id }); } catch (e) { alert(e.message); } }
