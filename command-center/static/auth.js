// Admin PIN helpers, shared by every page. Everything lives on one object so it
// cannot clash with a page's own variables.
const Admin = {
  async call(path, body) {
    const res = await fetch(path, body === undefined ? { cache: "no-store" } : {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.error) throw new Error(data.error || res.statusText);
    return data;
  },
  status() { return this.call("/api/auth"); },

  css() {
    if (document.getElementById("adm-css")) return;
    const st = document.createElement("style"); st.id = "adm-css";
    st.textContent = `.adm-back{position:fixed;inset:0;background:#070b13cc;display:flex;align-items:center;justify-content:center;z-index:50;padding:1rem}
      .adm-box{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);padding:1.3rem;width:100%;max-width:22rem;color:var(--txt)}
      .adm-box h4{margin:0 0 .3rem;font-family:var(--display);font-size:1.2rem;font-weight:600}.adm-box p{margin:0 0 .8rem;color:var(--mut);font-size:.92rem}
      .adm-box label{display:block;font-size:.84rem;color:var(--mut);margin:.6rem 0 .25rem}
      .adm-box input{width:100%}
      .adm-err{color:var(--bad);font-size:.88rem;min-height:1.2em;margin-top:.5rem}
      .adm-row{display:flex;gap:.5rem;justify-content:flex-end;margin-top:.6rem;flex-wrap:wrap}
      .adm-strip{display:flex;gap:.6rem;align-items:center;flex-wrap:wrap;border:1px solid var(--line);background:var(--panel);border-radius:var(--r);padding:.7rem 1rem;margin-top:1.4rem;color:var(--mut);font-size:.94rem}
      .adm-strip.open{border-color:var(--amber);background:rgba(234,166,64,.1);color:var(--amber)}.adm-strip span{flex:1 1 14rem}`;
    document.head.appendChild(st);
  },

  // Show a small form. `submit(values)` may throw to show an error and keep the form open.
  // Resolves true when submit succeeds, false if the person cancels.
  dialog(title, text, fields, submit) {
    this.css();
    return new Promise(done => {
      const back = document.createElement("div"); back.className = "adm-back";
      back.innerHTML = `<form class="adm-box"><h4></h4><p></p><div class="adm-fields"></div>
        <div class="adm-err" role="alert"></div><div class="adm-row">
        <button type="button" data-x>Cancel</button><button class="go">OK</button></div></form>`;
      back.querySelector("h4").textContent = title; back.querySelector("p").textContent = text;
      const inputs = fields.map(f => {
        const l = document.createElement("label"); l.textContent = f.label;
        const i = document.createElement("input"); i.type = "password"; i.autocomplete = f.auto || "off"; i.name = f.name;
        back.querySelector(".adm-fields").append(l, i); return i;
      });
      const close = v => { back.remove(); done(v); };
      back.querySelector("[data-x]").onclick = () => close(false);
      back.querySelector("form").onsubmit = async e => {
        e.preventDefault();
        const vals = Object.fromEntries(inputs.map(i => [i.name, i.value]));
        try { await submit(vals); close(true); }
        catch (err) { back.querySelector(".adm-err").textContent = err.message; inputs[0].select(); }
      };
      document.body.appendChild(back); inputs[0].focus();
    });
  },

  unlock() {
    return this.dialog("Admin PIN", "Enter the PIN to download, delete or change things on this deck.",
      [{ name: "pin", label: "PIN", auto: "current-password" }], v => this.call("/api/auth/unlock", { pin: v.pin }));
  },
  choosePin(first) {
    return this.dialog(first ? "Set an admin PIN" : "Change the admin PIN",
      "At least 4 characters. Reading stays open to everyone; the PIN is only for changing things.",
      [{ name: "pin", label: "New PIN", auto: "new-password" }, { name: "again", label: "New PIN again", auto: "new-password" }],
      async v => { if (v.pin !== v.again) throw new Error("The two entries do not match."); await this.call("/api/auth/set", { pin: v.pin }); });
  },

  // Draw the status strip on the dashboard.
  async mount(el) {
    this.css();
    let s;
    try { s = await this.status(); } catch (e) { el.textContent = ""; return; }
    const btn = (label, fn, go) => { const b = document.createElement("button"); if (go) b.className = "go";
      b.textContent = label; b.onclick = async () => { try { await fn(); } catch (e) { alert(e.message); } this.mount(el); }; return b; };
    const strip = document.createElement("div"); const text = document.createElement("span"); strip.append(text);
    if (!s.pin_set) {
      strip.className = "adm-strip open";
      text.textContent = "No admin PIN is set. Anyone on this network can download or delete content.";
      strip.append(btn("Set a PIN", () => this.choosePin(true), true));
    } else if (!s.unlocked) {
      strip.className = "adm-strip";
      text.textContent = "Locked. Reading is open; downloading and deleting need the admin PIN.";
      strip.append(btn("Unlock", () => this.unlock(), true));
    } else {
      strip.className = "adm-strip";
      text.textContent = "Unlocked on this device.";
      strip.append(btn("Lock", () => this.call("/api/auth/lock", {})), btn("Change PIN", () => this.choosePin(false)),
        btn("Remove PIN", async () => { if (confirm("Remove the admin PIN? Anyone on the network will be able to change things."))
          await this.call("/api/auth/clear", {}); }));
    }
    el.replaceChildren(strip);
  },
};
