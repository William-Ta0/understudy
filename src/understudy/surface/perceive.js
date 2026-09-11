// understudy in-page perception. Injected into every frame of a web surface.
//
// One module does perception (what the agent sees), resolution (how replay finds a
// recorded target) and description (how the recorder turns an acted-on element into
// locators). Keeping all three on the same role/name/label code means "what the model
// saw", "what we recorded" and "what replay looks for" cannot drift apart.
//
// The vocabulary is deliberately surface-agnostic (role, accessible name, visual
// label, visible text, table cell by header + row key). A desktop surface would
// implement the same functions over UIA / AX trees.
(() => {
  if (window.__us && window.__us.version === 4) return;

  // `doc` identifies this document instance: refs from an older observation are rejected once the frame navigates.
  const US = { version: 4, refs: new Map(), bySeq: new WeakMap(), seq: 0, doc: Math.random().toString(36).slice(2, 10) };

  // ------------------------------------------------------------------ text utils
  const norm = (s) => (s || "").replace(/\u00a0/g, " ").replace(/\s+/g, " ").trim();
  const stripLabel = (s) => norm(s).replace(/[\s:*]+$/, "").trim();
  const lc = (s) => norm(s).toLowerCase();

  function textOf(el) {
    if (!el) return "";
    // innerText respects CSS visibility and line layout; textContent is the fallback for detached nodes.
    return norm(el.innerText !== undefined ? el.innerText : el.textContent);
  }

  function matchText(actual, m) {
    // m: {value, mode} where mode is exact | contains | regex. Comparison is whitespace- and case-insensitive.
    if (m === null || m === undefined) return true;
    if (typeof m === "string") m = { value: m, mode: "exact" };
    const a = lc(actual);
    const v = lc(m.value);
    switch (m.mode || "exact") {
      case "exact": return a === v;
      case "contains": return a.includes(v);
      case "regex": try { return new RegExp(m.value, "i").test(norm(actual)); } catch (e) { return false; }
      default: return false;
    }
  }

  // ------------------------------------------------------------------ element facts
  function isVisible(el) {
    if (!el || !el.isConnected) return false;
    if (el.tagName === "INPUT" && (el.type || "").toLowerCase() === "hidden") return false;
    const cs = getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden" || parseFloat(cs.opacity || "1") === 0) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 || r.height > 0;
  }

  function isDisabled(el) {
    return !!(el.disabled || el.getAttribute("aria-disabled") === "true");
  }

  const CONTROL_TAGS = new Set(["INPUT", "SELECT", "TEXTAREA", "BUTTON"]);

  function roleOf(el) {
    const explicit = el.getAttribute && el.getAttribute("role");
    if (explicit) return explicit.split(/\s+/)[0];
    const tag = el.tagName;
    if (tag === "A" && el.hasAttribute("href")) return "link";
    if (tag === "BUTTON") return "button";
    if (tag === "INPUT") {
      const t = (el.getAttribute("type") || "text").toLowerCase();
      if (["button", "submit", "reset", "image"].includes(t)) return "button";
      if (t === "checkbox") return "checkbox";
      if (t === "radio") return "radio";
      if (t === "hidden") return null;
      return "textbox";
    }
    if (tag === "SELECT") return "combobox";
    if (tag === "TEXTAREA") return "textbox";
    if (/^H[1-6]$/.test(tag)) return "heading";
    // Legacy apps hang behaviour on non-semantic elements (<td onclick>). Treat them as buttons.
    if (el.hasAttribute && el.hasAttribute("onclick") && tag !== "BODY") return "button";
    if (tag === "TH") return "columnheader";
    if (tag === "TD") return isHeaderCell(el) ? "columnheader" : "cell";
    return null;
  }

  function isInferred(el) {
    return !el.getAttribute("role") && el.hasAttribute("onclick") && !["A", "BUTTON", "INPUT"].includes(el.tagName);
  }

  function nameOf(el) {
    const al = el.getAttribute("aria-label");
    if (al) return norm(al);
    const lb = el.getAttribute("aria-labelledby");
    if (lb) {
      const t = lb.split(/\s+/).map((id) => el.ownerDocument.getElementById(id)).filter(Boolean).map(textOf).join(" ");
      if (t) return norm(t);
    }
    const tag = el.tagName;
    if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") {
      const t = (el.getAttribute("type") || "").toLowerCase();
      if (["button", "submit", "reset"].includes(t)) return norm(el.value || (t === "reset" ? "Reset" : "Submit"));
      if (t === "image") return norm(el.alt || el.value || "");
      if (el.id) {
        const l = el.ownerDocument.querySelector(`label[for="${CSS.escape(el.id)}"]`);
        if (l) return stripLabel(textOf(l));
      }
      const wrap = el.closest("label");
      if (wrap) return stripLabel(textOf(wrap));
      return norm(el.getAttribute("title") || el.getAttribute("placeholder") || "");
    }
    if (tag === "IMG") return norm(el.alt || el.title || "");
    const role = roleOf(el);
    if (["link", "button", "heading", "cell", "columnheader", "tab", "menuitem", "option"].includes(role)) {
      return textOf(el).slice(0, 160);
    }
    return norm(el.getAttribute("title") || "");
  }

  // Text that appears before `target` inside `container`, e.g. "Member #: <input>".
  function textBefore(container, target) {
    if (!container) return "";
    const walker = container.ownerDocument.createTreeWalker(container, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
    let last = "";
    let node;
    while ((node = walker.nextNode())) {
      if (node === target || (node.nodeType === 1 && node.contains(target))) {
        if (node === target) break;
        continue;
      }
      if (node.nodeType === 1 && CONTROL_TAGS.has(node.tagName)) last = "";
      if (node.nodeType === 3 && norm(node.textContent)) last = node.textContent;
    }
    return stripLabel(last);
  }

  // The label a human operator reads next to a control. Legacy forms rarely have
  // <label>; the label is the text in the cell to the left (or above) the field.
  function visualLabelOf(el) {
    const tag = el.tagName;
    if (!CONTROL_TAGS.has(tag)) return "";
    const explicit = nameOf(el);
    const t = (el.getAttribute("type") || "").toLowerCase();
    if (["button", "submit", "reset", "image"].includes(t) || tag === "BUTTON") return explicit;
    if (el.id && el.ownerDocument.querySelector(`label[for="${CSS.escape(el.id)}"]`)) return explicit;
    if (el.closest("label")) return explicit;
    const cell = el.closest("td,th");
    if (cell) {
      const inCell = textBefore(cell, el);
      if (inCell) return inCell;
      let prev = cell.previousElementSibling;
      while (prev) {
        const txt = stripLabel(textOf(prev));
        if (txt && !prev.querySelector("input,select,textarea,button")) return txt;
        prev = prev.previousElementSibling;
      }
      // Stacked layout: the label sits in the same column one row up.
      const row = cell.parentElement;
      const idx = Array.prototype.indexOf.call(row.children, cell);
      const above = row.previousElementSibling;
      if (above && above.children[idx]) {
        const txt = stripLabel(textOf(above.children[idx]));
        if (txt && !above.children[idx].querySelector("input,select,textarea,button")) return txt;
      }
    }
    const before = textBefore(el.parentElement, el);
    if (before) return before;
    return explicit;
  }

  // ------------------------------------------------------------------ tables
  function rowsOf(table) {
    return Array.from(table.rows || []).filter((r) => r.closest("table") === table);
  }

  function headerRowOf(table) {
    const rows = rowsOf(table);
    if (!rows.length) return null;
    const first = rows[0];
    const cells = Array.from(first.cells);
    if (cells.length < 2) return null;
    const looksHeader = cells.every((c) => c.tagName === "TH")
      || cells.every((c) => /\bgh\b|head|hdr/i.test(c.className || ""))
      || (first.parentElement && first.parentElement.tagName === "THEAD");
    return looksHeader ? first : null;
  }

  function isHeaderCell(cell) {
    const table = cell.closest("table");
    if (!table) return false;
    const hr = headerRowOf(table);
    return !!hr && cell.parentElement === hr;
  }

  function headersOf(table) {
    const hr = headerRowOf(table);
    return hr ? Array.from(hr.cells).map((c) => stripLabel(textOf(c))) : [];
  }

  function cellContext(cell) {
    const table = cell.closest("table");
    if (!table) return null;
    const headers = headersOf(table);
    if (!headers.length) return null;
    const row = cell.parentElement;
    const col = Array.prototype.indexOf.call(row.cells, cell);
    return { table, headers, row, col, header: headers[col] || null, isHeader: row === headerRowOf(table) };
  }

  function findTableCell(root, spec) {
    // spec: {headers: [..], row: {colHeader: TextMatch}, column: header}
    const out = [];
    for (const table of root.querySelectorAll("table")) {
      const headers = headersOf(table);
      if (!headers.length) continue;
      const hl = headers.map(lc);
      if (!(spec.headers || []).every((h) => hl.includes(lc(h)))) continue;
      const colIdx = hl.indexOf(lc(spec.column));
      if (colIdx < 0) continue;
      const keys = Object.entries(spec.row || {}).map(([h, m]) => [hl.indexOf(lc(h)), m]);
      if (keys.some(([i]) => i < 0)) continue;
      for (const row of rowsOf(table).slice(1)) {
        if (keys.every(([i, m]) => row.cells[i] && matchText(textOf(row.cells[i]), m))) {
          if (row.cells[colIdx]) out.push(row.cells[colIdx]);
        }
      }
    }
    return out;
  }

  // ------------------------------------------------------------------ sensitivity
  const SENSITIVE_LABELS = [
    [/\b(ssn|social security|tax ?id|tin)\b/i, "pii"],
    [/\b(date of birth|birth ?date|dob)\b/i, "pii"],
    [/\baddress\b/i, "pii"],
    [/\b(phone|mobile)\b/i, "pii"],
    [/\be-?mail\b/i, "pii"],
    [/^(name|member|member name|account holder|customer|borrower|joint owner)$/i, "pii"],
    [/\b(balance|amount|deposit|limit)\b/i, "financial"],
    [/\b(password|passcode|override code|pin)\b/i, "secret"],
  ];
  const SENSITIVE_PATTERNS = [
    [/\$\s?-?[\d,]+\.\d{2}/, "financial"],
    [/\b\d{3}-\d{2}-\d{4}\b/, "pii"],
    [/[\w.+-]+@[\w-]+\.[\w.-]+/, "pii"],
    [/\(\d{3}\)\s?\d{3}-\d{4}/, "pii"],
  ];

  function labelForValue(el) {
    // For a value cell in a two-column "Label: | Value" layout, the label is the previous cell.
    const cell = el.closest("td,th");
    if (!cell) return "";
    const ctx = cellContext(cell);
    if (ctx && !ctx.isHeader && ctx.header) return ctx.header;
    let prev = cell.previousElementSibling;
    while (prev) {
      const t = stripLabel(textOf(prev));
      if (t) return t;
      prev = prev.previousElementSibling;
    }
    return "";
  }

  // Label for an inline value outside a table, e.g. <p>Member: <b>DANA R WHITFIELD</b></p>.
  function inlineLabelOf(el) {
    return el.closest("td,th") ? "" : textBefore(el.parentElement, el);
  }

  function sensitivityOf(el, role, text) {
    if (el.tagName === "INPUT" && (el.type || "").toLowerCase() === "password") return "secret";
    if (role === "columnheader" || el.tagName === "TH") return null;
    const lab = role === "textbox" || role === "combobox" ? visualLabelOf(el) : (labelForValue(el) || inlineLabelOf(el));
    // Only the value side of a label/value pair is sensitive, never the label itself.
    const isLabelCell = el.tagName === "TD" && /:\s*$/.test(textOf(el));
    if (!isLabelCell && lab) {
      for (const [re, kind] of SENSITIVE_LABELS) if (re.test(lab)) return kind;
    }
    if (text && /^\$?-?[\d,]+\.\d{2}$/.test(norm(text))) return "financial";
    for (const [re, kind] of SENSITIVE_PATTERNS) if (text && re.test(text)) return kind;
    return null;
  }

  // Red text is how most legacy apps flag errors; it is a visual cue a human relies on too.
  function isErrorColored(el) {
    const m = getComputedStyle(el).color.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
    return !!m && +m[1] >= 150 && +m[2] <= 80 && +m[3] <= 80;
  }

  // ------------------------------------------------------------------ refs
  function refFor(el) {
    let r = US.bySeq.get(el);
    if (!r || !r.startsWith(US.prefix || "e")) {
      r = `${US.prefix || "e"}${++US.seq}`;
      US.bySeq.set(el, r);
    }
    US.refs.set(r, el);
    return r;
  }

  function rect(el) {
    const r = el.getBoundingClientRect();
    return [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)];
  }

  // Non-volatile attributes worth recording. Generated ids (ctl00_x9f2) are excluded.
  function looksGenerated(id) {
    return !id || /^ctl\d+_|[0-9a-f]{6,}|\d{3,}|^(ember|react|ext-gen|gwt-|j_id|x-auto-)/i.test(id);
  }

  function attrsOf(el) {
    const a = {};
    for (const k of ["name", "type", "value", "href", "onclick", "title", "alt", "id"]) {
      if (!el.hasAttribute(k)) continue;
      let v = el.getAttribute(k);
      if (k === "id" && looksGenerated(v)) continue;
      if (k === "value" && !["button", "submit", "reset"].includes((el.getAttribute("type") || "").toLowerCase())) continue;
      if (k === "href") v = v.replace(/([?&])_k=[^&]*/g, "$1").slice(0, 200);
      a[k] = v.slice(0, 200);
    }
    return a;
  }

  // ------------------------------------------------------------------ snapshot
  const CANDIDATE_SELECTOR =
    "a[href],button,input,select,textarea,[role],[onclick],h1,h2,h3,h4,h5,h6,td,th,b,strong,font,p,span,li,label,div,legend,caption";

  function ownText(el) {
    // Text directly inside this element (not in child elements that we will visit anyway).
    let t = "";
    for (const n of el.childNodes) if (n.nodeType === 3) t += n.textContent;
    return norm(t);
  }

  US.snapshot = function (opts) {
    opts = opts || {};
    US.prefix = opts.prefix || "e";
    US.refs = new Map();
    const limit = opts.limit || 600;
    const nodes = [];
    const doc = document;
    const els = doc.querySelectorAll(CANDIDATE_SELECTOR);
    for (const el of els) {
      if (nodes.length >= limit) break;
      if (!isVisible(el)) continue;
      const role = roleOf(el);
      const interactive = ["link", "button", "textbox", "combobox", "checkbox", "radio"].includes(role);
      let text = "";
      if (interactive) {
        text = textOf(el).slice(0, 160);
      } else if (role === "cell" || role === "columnheader") {
        if (el.querySelector("table,input,select,textarea,button,a[href],[onclick]")) continue; // layout cell
        text = textOf(el);
        if (!text) continue;
      } else {
        // Plain text-bearing elements: keep only those that own text (avoid duplicating ancestors).
        if (el.closest("a[href],button,[onclick]") && el.closest("a[href],button,[onclick]") !== el) continue;
        if (el.tagName !== "TD" && el.closest("td,th") && el.closest("td,th").querySelectorAll("*").length < 4) continue;
        text = ownText(el);
        if (!text || !/[\p{L}\p{N}]/u.test(text)) continue;
      }
      const node = {
        ref: refFor(el),
        role: role || "text",
        tag: el.tagName.toLowerCase(),
        name: interactive || role === "heading" ? nameOf(el) : "",
        text: text.slice(0, 200),
        rect: rect(el),
      };
      if (interactive) {
        node.label = visualLabelOf(el);
        node.attrs = attrsOf(el);
        if (isDisabled(el)) node.disabled = true;
        if (isInferred(el)) node.inferred = true;
        if (el.tagName === "SELECT") {
          node.options = Array.from(el.options).map((o) => ({ label: norm(o.text), value: o.value, selected: o.selected })).slice(0, 40);
        }
        if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") {
          const t = (el.getAttribute("type") || "text").toLowerCase();
          if (t === "checkbox" || t === "radio") node.checked = !!el.checked;
          else if (!["button", "submit", "reset", "image"].includes(t)) node.value = t === "password" ? (el.value ? "********" : "") : el.value;
        }
      }
      if (role === "cell" || role === "columnheader") {
        const ctx = cellContext(el);
        if (ctx) {
          node.cell = { header: ctx.header, isHeader: ctx.isHeader, rowKey: textOf(ctx.row.cells[0] || el).slice(0, 80) };
        }
      }
      if (isErrorColored(el)) node.emphasis = "error";
      const sens = sensitivityOf(el, role, node.value !== undefined ? node.value : text);
      if (sens) node.sensitive = sens;
      nodes.push(node);
    }
    return {
      doc: US.doc,
      url: location.href,
      title: doc.title,
      text: textOf(doc.body).slice(0, opts.textLimit || 4000),
      nodes,
    };
  };

  // ------------------------------------------------------------------ resolution
  function candidates(root, role) {
    const pool = root.querySelectorAll(CANDIDATE_SELECTOR);
    const out = [];
    for (const el of pool) {
      if (role && roleOf(el) !== role) continue;
      out.push(el);
    }
    return out;
  }

  // Keep the innermost match: if both a <td> and the <b> inside it match "Search", keep the <b>'s owner.
  function innermost(list) {
    return list.filter((el) => !list.some((o) => o !== el && el.contains(o)));
  }

  function scopeRoot(within) {
    let root = document;
    for (const s of within || []) {
      if (s.dialog !== undefined && s.dialog !== null) {
        const dlg = Array.from(document.querySelectorAll("dialog[open],[role=dialog],[role=alertdialog]")).find(
          (d) => !s.dialog || matchText(nameOf(d) || textOf(d).slice(0, 80), { value: s.dialog, mode: "contains" })
        );
        if (!dlg) return null;
        root = dlg;
      }
    }
    return root;
  }

  function resolveElements(loc, within) {
    const root = scopeRoot(within);
    if (!root) return [];
    const by = loc.by;
    let found = [];
    if (by === "role") {
      found = candidates(root, loc.role).filter((el) => matchText(nameOf(el), loc.name));
    } else if (by === "label") {
      if (loc.role === "cell") {
        // A value cell in a "Label: | Value" layout, found by the label a human reads next to it.
        found = Array.from(root.querySelectorAll("td,th")).filter(
          (el) => !el.querySelector("table") && textOf(el) && !/:\s*$/.test(textOf(el)) && matchText(labelForValue(el), loc.label)
        );
      } else {
        found = candidates(root, loc.role).filter((el) => CONTROL_TAGS.has(el.tagName) && matchText(visualLabelOf(el), loc.label));
      }
    } else if (by === "text") {
      found = candidates(root, loc.role).filter((el) => matchText(textOf(el), loc.text));
      if (!loc.role) found = innermost(found);
    } else if (by === "table_cell") {
      found = findTableCell(root, loc);
    } else if (by === "attr") {
      const tag = loc.tag || "*";
      found = Array.from(root.querySelectorAll(tag)).filter((el) =>
        Object.entries(loc.attrs || {}).every(([k, m]) => el.hasAttribute(k) && matchText(el.getAttribute(k), m))
      );
    } else if (by === "css") {
      try { found = Array.from(root.querySelectorAll(loc.css)); } catch (e) { found = []; }
    } else if (by === "xpath") {
      try {
        const it = document.evaluate(loc.xpath, root === document ? document : root, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
        for (let i = 0; i < it.snapshotLength; i++) found.push(it.snapshotItem(i));
      } catch (e) { found = []; }
    } else if (by === "point") {
      const el = document.elementFromPoint(loc.x, loc.y);
      found = el ? [el] : [];
    }
    found = found.filter(isVisible);
    if (loc.nth !== undefined && loc.nth !== null) found = found[loc.nth] ? [found[loc.nth]] : [];
    return found;
  }

  function brief(el) {
    return {
      ref: refFor(el),
      role: roleOf(el) || el.tagName.toLowerCase(),
      name: nameOf(el),
      label: CONTROL_TAGS.has(el.tagName) ? visualLabelOf(el) : "",
      text: textOf(el).slice(0, 120),
      tag: el.tagName.toLowerCase(),
      rect: rect(el),
      disabled: isDisabled(el),
    };
  }

  US.resolve = function (loc, within) {
    const els = resolveElements(loc, within);
    return els.slice(0, 5).map(brief).concat(els.length > 5 ? [{ more: els.length - 5 }] : []);
  };

  US.count = function (loc, within) {
    return resolveElements(loc, within).length;
  };

  US.textVisible = function (m, within) {
    const root = scopeRoot(within);
    if (!root) return false;
    const body = root === document ? document.body : root;
    return !!body && matchText(textOf(body), typeof m === "string" ? { value: m, mode: "contains" } : m);
  };

  // The innermost visible element whose text matches: used to capture an app's own error message.
  US.textSnippet = function (m, within) {
    const root = scopeRoot(within);
    if (!root) return null;
    if (typeof m === "string") m = { value: m, mode: "contains" };
    const base = root === document ? document.body : root;
    if (!base) return null;
    const els = Array.from(base.querySelectorAll("*")).filter((el) => isVisible(el) && matchText(textOf(el), m));
    const inner = innermost(els);
    return inner.length ? textOf(inner[0]).slice(0, 300) : null;
  };

  US.readRef = function (ref) {
    const el = US.refs.get(ref);
    if (!el || !el.isConnected) return null;
    const t = (el.getAttribute("type") || "").toLowerCase();
    const value = el.tagName === "SELECT"
      ? norm(el.options[el.selectedIndex] ? el.options[el.selectedIndex].text : "")
      : (el.tagName === "INPUT" || el.tagName === "TEXTAREA") && !["button", "submit", "reset"].includes(t) ? el.value : null;
    return { text: textOf(el), value };
  };

  // ------------------------------------------------------------------ description (recording)
  function cssPath(el) {
    // A selector built only from stable attributes: tag, name, type, value; anchored on a named form if any.
    const tag = el.tagName.toLowerCase();
    const parts = [tag];
    for (const k of ["name", "type"]) if (el.hasAttribute(k)) parts.push(`[${k}="${CSS.escape(el.getAttribute(k))}"]`);
    if (el.hasAttribute("value") && ["button", "submit", "reset"].includes((el.getAttribute("type") || "").toLowerCase())) {
      parts.push(`[value="${CSS.escape(el.getAttribute("value"))}"]`);
    }
    if (el.id && !looksGenerated(el.id)) return `#${CSS.escape(el.id)}`;
    const form = el.closest("form[name]");
    const sel = parts.join("");
    return form ? `form[name="${CSS.escape(form.getAttribute("name"))}"] ${sel}` : sel;
  }

  function xpathOf(el) {
    const segs = [];
    for (let n = el; n && n.nodeType === 1 && n !== document.documentElement; n = n.parentElement) {
      const same = Array.from(n.parentElement ? n.parentElement.children : []).filter((c) => c.tagName === n.tagName);
      segs.unshift(`${n.tagName.toLowerCase()}${same.length > 1 ? `[${same.indexOf(n) + 1}]` : ""}`);
    }
    return "/html/" + segs.join("/");
  }

  US.describe = function (ref, within) {
    const el = US.refs.get(ref);
    if (!el || !el.isConnected) return null;
    const role = roleOf(el);
    const name = nameOf(el);
    const label = visualLabelOf(el);
    const text = el.tagName === "SELECT" || el.tagName === "TEXTAREA" || (el.tagName === "INPUT" && role === "textbox") ? "" : textOf(el).slice(0, 160);
    const cands = [];
    if (role && name && role !== "cell" && role !== "columnheader") cands.push({ by: "role", role, name });
    if (label && CONTROL_TAGS.has(el.tagName) && (el.tagName === "SELECT" || el.tagName === "TEXTAREA" || role === "textbox" || role === "checkbox" || role === "radio")) {
      cands.push({ by: "label", role, label });
    }
    if (role === "cell" || role === "columnheader") {
      const ctx = cellContext(el);
      if (ctx && !ctx.isHeader && ctx.header) {
        // Key the row on its most human-meaningful columns: text columns first (a product name), then
        // identifiers (a suffix). Add key columns until the row is unique. Amount columns are never keys.
        const cells = Array.from(ctx.row.cells);
        const isAmount = (t) => /^\$?-?[\d,]+\.\d{2}$/.test(t);
        const order = cells
          .map((c, i) => ({ i, t: textOf(c) }))
          .filter(({ i, t }) => i !== ctx.col && ctx.headers[i] && t && !isAmount(t))
          .sort((a, b) => (/^[\d\s\-]+$/.test(a.t) ? 1 : 0) - (/^[\d\s\-]+$/.test(b.t) ? 1 : 0));
        const row = {};
        for (const { i, t } of order) {
          row[ctx.headers[i]] = t;
          const loc = { by: "table_cell", headers: Object.keys(row).concat([ctx.header]), row: Object.assign({}, row), column: ctx.header };
          if (findTableCell(document, loc).length === 1) {
            cands.push(loc);
            break;
          }
        }
      }
      const lab = labelForValue(el);
      if (lab && (!ctx || ctx.isHeader || !ctx.header)) cands.push({ by: "label", role: "cell", label: lab });
    }
    if (text && (role === "button" || role === "link") && text !== name) cands.push({ by: "text", role, text });
    if (!role && text) cands.push({ by: "text", text });
    const a = attrsOf(el);
    const stable = {};
    if (a.name) stable.name = a.name;
    if (a.onclick) {
      const m = a.onclick.match(/['"]([\w\-/]+\.(?:asp|aspx|jsp|do|php|html?))/i);
      if (m) stable.onclick = { value: m[1], mode: "contains" };
    }
    if (a.href && !a.href.startsWith("javascript:")) stable.href = { value: a.href.split("?")[0], mode: "contains" };
    else if (a.href) stable.href = a.href;
    if (Object.keys(stable).length) cands.push({ by: "attr", tag: el.tagName.toLowerCase(), attrs: stable });
    if (CONTROL_TAGS.has(el.tagName)) cands.push({ by: "css", css: cssPath(el) });
    cands.push({ by: "xpath", xpath: xpathOf(el) });

    // Validate every candidate against the live page: it must match exactly one visible element, and it must be this one.
    const results = cands.map((loc) => {
      const els = resolveElements(loc, within);
      return { locator: loc, matches: els.length, unique: els.length === 1, same: els.length === 1 && els[0] === el };
    });
    return {
      role: role || el.tagName.toLowerCase(),
      name,
      label,
      text,
      tag: el.tagName.toLowerCase(),
      inferred: isInferred(el),
      sensitive: sensitivityOf(el, role, text),
      candidates: results,
    };
  };

  US.describeEl = function (el) {
    return US.describe(refFor(el), []);
  };

  // ------------------------------------------------------------------ masking for screenshots
  US.mask = function (on, kinds) {
    const cls = "__us_mask";
    if (!document.getElementById("__us_mask_style")) {
      const st = document.createElement("style");
      st.id = "__us_mask_style";
      st.textContent = `.${cls}{background:#1b1b1b!important;color:#1b1b1b!important;border-radius:2px;}`;
      (document.head || document.documentElement).appendChild(st);
    }
    if (!on) {
      for (const el of document.querySelectorAll("." + cls)) el.classList.remove(cls);
      return 0;
    }
    let n = 0;
    for (const el of document.querySelectorAll("td,th,input,span,b,font,p,div,li")) {
      if (!isVisible(el)) continue;
      if (!["INPUT"].includes(el.tagName) && el.querySelector("td,table,div,p")) continue;
      const role = roleOf(el);
      const text = el.tagName === "INPUT" ? el.value : textOf(el);
      const s = sensitivityOf(el, role, text);
      if (s && (!kinds || kinds.includes(s)) && text) {
        el.classList.add(cls);
        n++;
      }
    }
    return n;
  };

  window.__us = US;
})();
