"""Operator console: a minimal but real surface for taking over a live session.

It runs in the same process as the automation and serves the *same* browser session:
a live view, click/type/key relay, native-dialog answers, and the claim/release controls.
It is deliberately bare. A production console would stream video (CDP screencast or
VNC), authenticate operators via SSO, and sit behind an intervention queue; the control
model underneath (single holder, epochs, capture) would not change.
"""

from __future__ import annotations

import asyncio
import html
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from ..surface.web import DialogPending
from .control import ControlCenter, ControlError, LiveSession


def create_console(center: ControlCenter) -> FastAPI:
    app = FastAPI(title="understudy operator console", docs_url=None, redoc_url=None, openapi_url=None)

    def auth(request: Request) -> None:
        tok = request.query_params.get("token") or request.headers.get("x-operator-token")
        if tok != center.token:
            raise HTTPException(403, "operator token required")

    def session(run_id: str) -> LiveSession:
        s = center.sessions.get(run_id)
        if not s:
            raise HTTPException(404, f"no live session {run_id}")
        return s

    def summary(s: LiveSession) -> dict[str, Any]:
        return {
            "run_id": s.run_id, "mode": s.mode, "label": s.label, "holder": s.holder.value, "operator": s.operator,
            "epoch": s.epoch, "status": s.status, "dialog": s.surface.dialog_info,
            "request": s.request.dump() if s.request else None,
            "human_actions": [a.dump() for a in s._actions][-20:],
        }

    @app.get("/api/sessions")
    async def list_sessions(request: Request):
        auth(request)
        return [summary(s) for s in center.sessions.values()]

    @app.get("/api/sessions/{run_id}")
    async def get_session(run_id: str, request: Request):
        auth(request)
        return summary(session(run_id))

    @app.get("/api/sessions/{run_id}/screen.png")
    async def screen(run_id: str, request: Request):
        auth(request)
        s = session(run_id)
        try:
            png = await s.surface.screenshot()  # live and unmasked: the operator is an authorised user
        except DialogPending:
            return JSONResponse({"dialog": s.surface.dialog_info}, status_code=409)
        return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.get("/api/sessions/{run_id}/ui")
    async def ui(run_id: str, request: Request):
        """Visible elements with page coordinates (what a scripted operator uses to aim its clicks)."""
        auth(request)
        s = session(run_id)
        if s.surface.pending_dialog is not None:
            return {"dialog": s.surface.dialog_info, "nodes": []}
        obs = await s.surface.observe(record=False)
        nodes = []
        for f in obs.frames:
            ox, oy = f.offset
            for n in f.nodes:
                x, y, w, h = n["rect"]
                nodes.append({**{k: n.get(k) for k in ("role", "name", "label", "text", "cell")}, "frame": f.key,
                              "x": ox + x + w / 2, "y": oy + y + h / 2})
        return {"nodes": nodes}

    @app.post("/api/sessions/{run_id}/claim")
    async def claim(run_id: str, request: Request):
        auth(request)
        body = await request.json()
        try:
            session(run_id).claim(str(body["operator"]))
        except ControlError as e:
            raise HTTPException(409, str(e)) from e
        return summary(session(run_id))

    @app.post("/api/sessions/{run_id}/release")
    async def release(run_id: str, request: Request):
        auth(request)
        body = await request.json()
        try:
            res = session(run_id).release(str(body["operator"]), body["resolution"], body.get("note"))
        except ControlError as e:
            raise HTTPException(409, str(e)) from e
        return res.dump()

    @app.post("/api/sessions/{run_id}/input")
    async def relay(run_id: str, request: Request):
        auth(request)
        body = await request.json()
        s = session(run_id)
        try:
            await s.relay(str(body.pop("operator")), str(body.pop("kind")), **body)
        except ControlError as e:
            raise HTTPException(409, str(e)) from e
        await asyncio.sleep(0.3)
        await s.surface.settle(timeout_ms=4000)
        return {"ok": True}

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        auth(request)
        rows = "".join(
            f'<tr><td><a href="/sessions/{s.run_id}?token={center.token}">{html.escape(s.run_id)}</a></td>'
            f"<td>{s.mode}</td><td>{html.escape(s.label)}</td><td><b>{s.holder.value}</b></td>"
            f"<td>{html.escape(s.request.reason if s.request else s.status)}</td></tr>"
            for s in center.sessions.values()
        )
        return f"""<html><head><title>understudy console</title><meta http-equiv="refresh" content="2">
<style>body{{font:14px system-ui;margin:24px}} td,th{{padding:6px 10px;border-bottom:1px solid #ddd;text-align:left}}</style></head>
<body><h2>Live sessions</h2><table><tr><th>run</th><th>mode</th><th>capability / goal</th><th>holder</th><th>status</th></tr>{rows}</table></body></html>"""

    @app.get("/sessions/{run_id}", response_class=HTMLResponse)
    async def page(run_id: str, request: Request):
        auth(request)
        session(run_id)
        return CONSOLE_HTML.replace("__RUN__", run_id).replace("__TOKEN__", center.token)

    return app


CONSOLE_HTML = """<!doctype html><html><head><title>understudy · operator console</title>
<style>
body{font:14px system-ui,-apple-system,sans-serif;margin:0;background:#f4f4f2;color:#1b1b1b}
header{padding:10px 18px;background:#1b1b1b;color:#fff;display:flex;gap:18px;align-items:center}
header b{font-size:15px} .pill{padding:2px 10px;border-radius:12px;background:#555;font-size:12px}
.pill.human{background:#b3541e}.pill.paused{background:#a1831b}.pill.automation{background:#2e6b3a}
main{display:grid;grid-template-columns:minmax(0,1fr) 360px;gap:14px;padding:14px}
#screen{width:100%;border:2px solid #999;cursor:not-allowed;background:#fff}
#screen.live{border-color:#b3541e;cursor:crosshair}
aside section{background:#fff;border:1px solid #ddd;border-radius:6px;padding:12px;margin-bottom:12px}
h3{margin:0 0 8px;font-size:13px;text-transform:uppercase;letter-spacing:.04em;color:#666}
button{font:13px system-ui;padding:6px 10px;margin:2px;border:1px solid #888;border-radius:4px;background:#fafafa;cursor:pointer}
button.primary{background:#1b1b1b;color:#fff;border-color:#1b1b1b} input,textarea{font:13px system-ui;padding:5px;width:100%;box-sizing:border-box}
pre{white-space:pre-wrap;font-size:12px;background:#f7f7f5;padding:6px;max-height:180px;overflow:auto}
#dialog{display:none;background:#fff3cd;border:1px solid #d6b656;padding:8px;border-radius:4px;margin-bottom:8px}
</style></head><body>
<header><b>understudy operator console</b><span id="label"></span><span id="holder" class="pill">…</span><span id="epoch"></span></header>
<main><div><div id="dialog"></div><img id="screen" alt="live session"></div>
<aside>
<section><h3>Intervention</h3><div id="reason">No open request.</div><pre id="ctx"></pre></section>
<section><h3>Control</h3>
<input id="op" placeholder="operator id"><br>
<button class="primary" onclick="claim()">Take control</button>
<div id="release"></div><textarea id="note" rows="2" placeholder="note for the record (optional)"></textarea></section>
<section><h3>Keyboard</h3><input id="txt" placeholder="text to type into the focused field">
<button onclick="typeText()">Type</button><button onclick="key('Tab')">Tab</button><button onclick="key('Enter')">Enter</button>
<button onclick="key('Backspace')">⌫</button><button onclick="key('Escape')">Esc</button></section>
<section><h3>Captured human actions</h3><pre id="log">—</pre></section>
</aside></main>
<script>
const RUN="__RUN__", TOKEN="__TOKEN__", api=p=>`/api/sessions/${RUN}${p}?token=${TOKEN}`;
const op=document.getElementById('op'); op.value=localStorage.getItem('op')||'';
let state={};
async function post(p,b){const r=await fetch(api(p),{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(b)});
 if(!r.ok){alert(await r.text());} return r;}
function who(){const v=op.value.trim(); if(!v){alert('enter your operator id');throw 'no op';} localStorage.setItem('op',v); return v;}
async function claim(){await post('/claim',{operator:who()}); refresh();}
async function release(res){await post('/release',{operator:who(),resolution:res,note:document.getElementById('note').value||null}); refresh();}
async function typeText(){await post('/input',{operator:who(),kind:'type',text:document.getElementById('txt').value}); document.getElementById('txt').value='';}
async function key(k){await post('/input',{operator:who(),kind:'key',key:k});}
async function dlg(a){await post('/input',{operator:who(),kind:'dialog',accept:a});}
document.getElementById('screen').addEventListener('click',async e=>{
 if(state.holder!=='human')return; const img=e.target, r=img.getBoundingClientRect();
 const x=(e.clientX-r.left)*img.naturalWidth/r.width, y=(e.clientY-r.top)*img.naturalHeight/r.height;
 await post('/input',{operator:who(),kind:'click',x,y});});
async function refresh(){
 const s=await (await fetch(api(''))).json(); state=s;
 document.getElementById('label').textContent=`${s.mode} · ${s.label}`;
 const h=document.getElementById('holder'); h.textContent=s.holder+(s.operator?` (${s.operator})`:''); h.className='pill '+s.holder;
 document.getElementById('epoch').textContent='epoch '+s.epoch;
 document.getElementById('screen').className=s.holder==='human'?'live':'';
 const rq=s.request; document.getElementById('reason').innerHTML=rq?`<b>${rq.kind}</b>: ${rq.reason}`:'No open request.';
 document.getElementById('ctx').textContent=rq?JSON.stringify(rq.context,null,1):'';
 const opts=rq?rq.options:['resume','completed','abort'];
 document.getElementById('release').innerHTML=(s.holder==='automation')?'':opts.map(o=>`<button onclick="release('${o}')">${o}</button>`).join('');
 const d=document.getElementById('dialog');
 if(s.dialog){d.style.display='block'; d.innerHTML=`Native ${s.dialog.type}: <b>${s.dialog.message}</b> <button onclick="dlg(true)">OK</button><button onclick="dlg(false)">Cancel</button>`;}
 else d.style.display='none';
 document.getElementById('log').textContent=(s.human_actions||[]).map(a=>`${a.kind} ${(a.target&&(a.target.label||a.target.name||a.target.text))||''} ${a.value||''}`).join('\\n')||'—';
 if(!s.dialog){document.getElementById('screen').src=api('/screen.png')+'&t='+Date.now();}
}
setInterval(refresh,900); refresh();
</script></body></html>"""
