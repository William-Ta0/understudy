// understudy human-action capture. Injected into every frame next to perceive.js.
//
// While an operator holds control of a live session, whatever they do in the page is
// reported back through the `__us_capture` binding, whether they act through the
// operator console (relayed input) or directly in a headed browser window. Targets are
// described with the same code the recorder uses, so a human's actions land in the
// trace in exactly the same shape as the model's.
(() => {
  if (window.__usCaptureInstalled) return;
  window.__usCaptureInstalled = true;

  const INTERACTIVE = "a[href],button,input,select,textarea,[onclick],[role=button],[role=link]";

  function send(kind, el, extra) {
    try {
      if (typeof window.__us_capture !== "function" || !window.__us) return;
      const target = el ? window.__us.describeEl(el) : null;
      window.__us_capture(Object.assign({ kind, target, url: location.href }, extra || {}));
    } catch (e) {
      /* capture must never break the page */
    }
  }

  document.addEventListener(
    "click",
    (ev) => {
      const el = ev.target && ev.target.closest ? ev.target.closest(INTERACTIVE) || ev.target : null;
      if (!el) return;
      const t = (el.getAttribute && (el.getAttribute("type") || "").toLowerCase()) || "";
      if (el.tagName === "INPUT" && !["button", "submit", "reset", "image", "checkbox", "radio"].includes(t)) return;
      if (el.tagName === "SELECT" || el.tagName === "TEXTAREA") return;
      send("click", el);
    },
    true
  );

  document.addEventListener(
    "change",
    (ev) => {
      const el = ev.target;
      if (!el || !el.tagName) return;
      if (el.tagName === "SELECT") {
        const o = el.options[el.selectedIndex];
        send("select", el, { value: o ? o.text.trim() : "" });
      } else if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") {
        const t = (el.getAttribute("type") || "text").toLowerCase();
        if (t === "checkbox" || t === "radio") return;
        send("input", el, { value: t === "password" ? null : el.value, secret: t === "password" });
      }
    },
    true
  );

  document.addEventListener(
    "keydown",
    (ev) => {
      if (ev.key === "Enter" || ev.key === "Escape") send("key", ev.target && ev.target.tagName ? ev.target : null, { key: ev.key });
    },
    true
  );
})();
