"""Keystone Core 7.2 - a deliberately "legacy" teller workstation mock.

It stands in for the long tail of back-office apps that have no API. It is built to be
hostile to naive automation, the way real ones are:

- A frameset (banner / nav / main) with no doctype, so it renders in quirks mode.
- Table-based layouts; form fields have no <label> and sit next to a text cell.
- Element ids are regenerated on every render (ASP.NET-style `ctl00_x9f2`).
- Navigation menu items are <td onclick> cells, not links.
- Detail URLs carry a per-session token, so replaying a recorded URL fails.
- Native confirm() dialogs, interstitial notices, session timeouts, transient host
  errors, and permission denials. Faults are injectable via /__control/faults.

Two tenants (lakeshore, pinecrest) run the same product with different labels,
product names, and a tenant-specific interstitial.
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import itertools
import os
import secrets
import time
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.parse import quote, urlencode

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from .data import (
    OPENABLE,
    PRODUCTS,
    SUPERVISOR_LIMIT,
    SUPERVISORS,
    TENANTS,
    USERS,
    Account,
    Member,
    TenantConfig,
    fresh_members,
    money,
)
from .faults import Fault, FaultBoard

SESSION_COOKIE = "KSSESSIONID"


class UnknownTenant(LookupError):
    pass


@dataclass
class Session:
    sid: str
    tenant: str
    user: str
    last_seen: float
    bulletin_ack: bool = False


@dataclass
class PendingOpen:
    rid: str
    member: str
    product: str
    nickname: str
    deposit: Decimal
    fund_from: str
    needs_override: bool
    overridden_by: str | None = None


@dataclass
class State:
    members: dict[str, dict[str, Member]] = field(default_factory=dict)
    sessions: dict[str, Session] = field(default_factory=dict)
    pending: dict[str, PendingOpen] = field(default_factory=dict)
    opened: list[dict] = field(default_factory=list)
    faults: FaultBoard = field(default_factory=FaultBoard)
    conf_seq: itertools.count = field(default_factory=lambda: itertools.count(417))

    def reset(self) -> None:
        self.members = {t: fresh_members() for t in TENANTS}
        self.sessions.clear()
        self.pending.clear()
        self.opened.clear()
        self.faults.clear()
        self.conf_seq = itertools.count(417)


# --------------------------------------------------------------------------- html


def e(s: object) -> str:
    return html.escape(str(s), quote=True)


def rid() -> str:
    """ASP.NET-style generated id: different on every render, useless as a selector."""
    return "ctl00_" + secrets.token_hex(3)


STYLE = """
BODY{font-family:Verdana,Arial,sans-serif;font-size:11px;background:#e6e4dc;margin:6px;color:#111}
TD{font-size:11px;font-family:Verdana,Arial,sans-serif}
.hdr{color:#fff;font-weight:bold;padding:3px 6px;font-size:12px}
.lbl{text-align:right;padding-right:6px;color:#222;white-space:nowrap}
.val{font-weight:bold}
.grid TD{border-bottom:1px solid #c9c6ba;padding:3px 8px}
.grid .gh{background:#cfcbbd;font-weight:bold}
.bar{background:#d6d3c8;padding:4px;border:1px solid #b8b4a6}
.btn{font-size:11px}
.mnu{padding:5px 8px;cursor:pointer;border-bottom:1px solid #9a9784;color:#102a5c}
.mnu:hover{background:#fff8d0}
.note{color:#555}
"""


def page(tenant: TenantConfig, title: str, body: str, script: str = "") -> HTMLResponse:
    # No doctype on purpose: quirks mode, like the real thing.
    return HTMLResponse(
        f"""<HTML><HEAD><TITLE>Keystone Core - {e(title)}</TITLE>
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=iso-8859-1">
<STYLE>{STYLE}</STYLE>
<SCRIPT LANGUAGE="JavaScript">{script}</SCRIPT></HEAD>
<BODY>{body}</BODY></HTML>"""
    )


def header_bar(tenant: TenantConfig, text: str) -> str:
    return (
        f'<TABLE WIDTH="100%" CELLSPACING=0 CELLPADDING=0><TR>'
        f'<TD CLASS=hdr BGCOLOR="{tenant.color}">&nbsp;{e(text)}</TD></TR></TABLE><BR>'
    )


def err(msg: str) -> str:
    return f'<P><FONT COLOR="#CC0000"><B>{e(msg)}</B></FONT></P>'


def viewstate() -> str:
    return f'<INPUT TYPE=HIDDEN NAME="__VIEWSTATE" VALUE="dDw{secrets.token_urlsafe(24)}">'


def token(sess: Session, member: str) -> str:
    return hashlib.sha256(f"{sess.sid}:{member}".encode()).hexdigest()[:8]


# --------------------------------------------------------------------------- app


def create_app(idle_timeout_s: float | None = None) -> FastAPI:
    idle = idle_timeout_s if idle_timeout_s is not None else float(os.environ.get("KEYSTONE_IDLE_TIMEOUT", "900"))
    app = FastAPI(title="Keystone Core mock", docs_url=None, redoc_url=None, openapi_url=None)
    st = State()
    st.reset()
    app.state.keystone = st

    # ------------------------------------------------------------- helpers

    def tcfg(tenant: str) -> TenantConfig:
        cfg = TENANTS.get(tenant)
        if not cfg:
            raise UnknownTenant(tenant)
        return cfg

    def session_for(request: Request, tenant: str) -> Session | None:
        sid = request.cookies.get(SESSION_COOKIE)
        sess = st.sessions.get(sid or "")
        if not sess or sess.tenant != tenant:
            return None
        if time.time() - sess.last_seen > idle:
            st.sessions.pop(sess.sid, None)
            return None
        sess.last_seen = time.time()
        return sess

    def expired_page(cfg: TenantConfig) -> HTMLResponse:
        return page(
            cfg,
            "Session Expired",
            header_bar(cfg, "Session Expired")
            + "<P><B>Your Keystone session has expired due to inactivity.</B></P>"
            '<P>Please <A HREF="signon.asp" TARGET="_top">sign on</A> again to continue.</P>'
            '<P CLASS=note>Message KC-SEC-0440</P>',
        )

    async def gate(request: Request, tenant: str, pg: str, *, frame_page: bool = True):
        """Common prologue: tenant, faults, session, tenant bulletin. Returns (cfg, sess, response)."""
        cfg = tcfg(tenant)
        method = request.method
        faults = st.faults.take(tenant, pg, method)
        for f in faults:
            if f.kind == "slow":
                await asyncio.sleep(f.delay_ms / 1000)
        sess = session_for(request, tenant)
        kinds = {f.kind for f in faults}
        if "session_expired" in kinds and sess:
            st.sessions.pop(sess.sid, None)
            sess = None
        if sess is None:
            return cfg, None, expired_page(cfg)
        if "server_error" in kinds:
            return cfg, sess, server_error_page()
        if "host_error" in kinds:
            return cfg, sess, await host_error_page(cfg, request)
        if "deny" in kinds:
            return cfg, sess, denied_page(cfg, pg)
        if frame_page and cfg.daily_bulletin and not sess.bulletin_ack and method == "GET":
            return cfg, sess, bulletin_page(cfg, str(request.url.path.rsplit("/", 1)[-1]) + _qs(request))
        if "notice" in kinds and method == "GET":
            return cfg, sess, notice_page(cfg, pg + _qs(request))
        return cfg, sess, None

    def _qs(request: Request) -> str:
        return ("?" + request.url.query) if request.url.query else ""

    def server_error_page() -> HTMLResponse:
        return HTMLResponse(
            """<HTML><HEAD><TITLE>Runtime Error</TITLE></HEAD>
<BODY BGCOLOR="white"><SPAN><H1>Server Error in '/Keystone' Application.<HR WIDTH=100% SIZE=1 COLOR=silver></H1>
<H2><I>Runtime Error</I></H2></SPAN>
<FONT FACE="Arial, Helvetica, Geneva, SunSans-Regular, sans-serif ">
<B>Description: </B>An application error occurred on the server. The current custom error settings for this
application prevent the details of the application error from being viewed remotely.<BR><BR>
<B>Exception Details: </B>System.NullReferenceException: Object reference not set to an instance of an object.
</FONT></BODY></HTML>""",
            status_code=500,
        )

    async def host_error_page(cfg: TenantConfig, request: Request) -> HTMLResponse:
        # Retry re-issues the same request: a link for GET, a re-post form for POST.
        target = request.url.path.rsplit("/", 1)[-1] + _qs(request)
        if request.method == "POST":
            form = await request.form()
            hidden = "".join(
                f'<INPUT TYPE=HIDDEN NAME="{e(k)}" VALUE="{e(v)}">' for k, v in form.items() if k != "__VIEWSTATE"
            )
            retry = (
                f'<FORM METHOD=POST ACTION="{e(target)}">{hidden}'
                '<INPUT TYPE=SUBMIT CLASS=btn VALUE="Retry"></FORM>'
            )
        else:
            retry = f'<A HREF="{e(target)}">Retry</A>'
        return page(
            cfg,
            "Host Communication Error",
            header_bar(cfg, "Host Communication Error")
            + err("KC-HOST-0103: Host communication timeout.")
            + "<P>The request could not be completed because the core host did not respond in time. "
            "No changes were made. You may retry the request.</P>"
            + f"<P>{retry}</P>",
        )

    def denied_page(cfg: TenantConfig, pg: str) -> HTMLResponse:
        func = {"shareadd.asp": "SHR-ADD (Open Sub-Account)"}.get(pg, f"{pg.upper()}")
        return page(
            cfg,
            "Access Denied",
            header_bar(cfg, "Access Denied")
            + err(f"Function {func} is not authorized for your security profile.")
            + "<P>Contact your Keystone security administrator to request access.</P>"
            '<P CLASS=note>Message KC-SEC-0217</P>',
        )

    def notice_page(cfg: TenantConfig, next_url: str) -> HTMLResponse:
        return page(
            cfg,
            "System Notice",
            header_bar(cfg, "System Notice")
            + '<TABLE WIDTH=520 CELLPADDING=8 BORDER=1 BGCOLOR="#fffbe6"><TR><TD>'
            "<B>Scheduled Maintenance</B><BR><BR>Core processing will be unavailable Sunday from 01:00 to 03:00 ET "
            "while the host is upgraded. Transactions entered during the window will be queued.</TD></TR></TABLE><BR>"
            f'<FORM METHOD=POST ACTION="notice.asp"><INPUT TYPE=HIDDEN NAME="next" VALUE="{e(next_url)}">'
            '<INPUT TYPE=SUBMIT CLASS=btn VALUE="Acknowledge"></FORM>',
        )

    def bulletin_page(cfg: TenantConfig, next_url: str) -> HTMLResponse:
        return page(
            cfg,
            "Daily Security Bulletin",
            header_bar(cfg, "Daily Security Bulletin")
            + '<TABLE WIDTH=560 CELLPADDING=8 BORDER=1 BGCOLOR="#eef6ee"><TR><TD>'
            "Members are reporting phone calls from people claiming to be NCUA examiners and asking for "
            "online banking codes. Never read a one-time passcode back to a caller.</TD></TR></TABLE><BR>"
            f'<FORM METHOD=POST ACTION="bulletin.asp"><INPUT TYPE=HIDDEN NAME="next" VALUE="{e(next_url)}">'
            '<INPUT TYPE=SUBMIT CLASS=btn VALUE="I Have Read This Bulletin"></FORM>',
        )

    def member_of(tenant: str, number: str) -> Member | None:
        return st.members[tenant].get(number)

    # ------------------------------------------------------------- control plane (test harness only)

    @app.post("/__control/faults")
    async def arm_fault(request: Request):
        body = await request.json()
        st.faults.arm(Fault(**body))
        return {"armed": st.faults.snapshot()}

    @app.post("/__control/reset")
    async def reset():
        st.reset()
        return {"ok": True}

    @app.get("/__control/state")
    async def state():
        return JSONResponse({"faults": st.faults.snapshot(), "fired": st.faults.fired, "opened": st.opened})

    # ------------------------------------------------------------- sign on / frameset

    @app.get("/")
    async def root():
        return RedirectResponse("/t/lakeshore/signon.asp")

    @app.get("/t/{tenant}/")
    async def tenant_root(tenant: str):
        return RedirectResponse(f"/t/{tenant}/signon.asp")

    def signon_form(cfg: TenantConfig, message: str = "") -> HTMLResponse:
        return page(
            cfg,
            "Sign On",
            f'<CENTER><BR><BR><TABLE WIDTH=420 CELLPADDING=0 CELLSPACING=0 BORDER=1><TR>'
            f'<TD CLASS=hdr BGCOLOR="{cfg.color}">&nbsp;{e(cfg.name)} &mdash; Keystone Core 7.2</TD></TR>'
            "<TR><TD BGCOLOR=#f4f2ea><BR>"
            + (err(message) if message else "")
            + '<FORM NAME="frmSignOn" METHOD=POST ACTION="signon.asp"><TABLE CELLPADDING=4 ALIGN=CENTER>'
            f'<TR><TD CLASS=lbl>User ID:</TD><TD><INPUT TYPE=TEXT NAME="uid" ID="{rid()}" SIZE=16></TD></TR>'
            f'<TR><TD CLASS=lbl>Password:</TD><TD><INPUT TYPE=PASSWORD NAME="pwd" ID="{rid()}" SIZE=16></TD></TR>'
            '<TR><TD></TD><TD><INPUT TYPE=SUBMIT CLASS=btn VALUE="Sign On"></TD></TR>'
            "</TABLE></FORM><P CLASS=note ALIGN=CENTER>Authorized use only. Activity is monitored.</P></TD></TR>"
            "</TABLE></CENTER>",
        )

    @app.get("/t/{tenant}/signon.asp")
    async def signon_get(tenant: str):
        return signon_form(tcfg(tenant))

    @app.post("/t/{tenant}/signon.asp")
    async def signon_post(tenant: str, request: Request):
        cfg = tcfg(tenant)
        form = await request.form()
        uid, pwd = str(form.get("uid", "")), str(form.get("pwd", ""))
        user = USERS.get(uid)
        if not user or not secrets.compare_digest(user["password"], pwd):
            return signon_form(cfg, "Invalid user ID or password.")
        sid = secrets.token_hex(16)
        st.sessions[sid] = Session(sid=sid, tenant=tenant, user=uid, last_seen=time.time())
        resp = RedirectResponse(f"/t/{tenant}/default.asp", status_code=303)
        resp.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="lax", path=f"/t/{tenant}/")
        return resp

    @app.get("/t/{tenant}/signoff.asp")
    async def signoff(tenant: str, request: Request):
        sid = request.cookies.get(SESSION_COOKIE)
        st.sessions.pop(sid or "", None)
        return RedirectResponse(f"/t/{tenant}/signon.asp")

    @app.get("/t/{tenant}/default.asp")
    async def frameset(tenant: str, request: Request):
        cfg = tcfg(tenant)
        if not session_for(request, tenant):
            return RedirectResponse(f"/t/{tenant}/signon.asp")
        return HTMLResponse(
            f"""<HTML><HEAD><TITLE>Keystone Core Teller Workstation - {e(cfg.name)}</TITLE></HEAD>
<FRAMESET ROWS="46,*" BORDER=0 FRAMEBORDER=0 FRAMESPACING=0>
  <FRAME NAME="banner" SRC="banner.asp" SCROLLING=NO NORESIZE>
  <FRAMESET COLS="168,*" BORDER=1 FRAMEBORDER=1>
    <FRAME NAME="nav" SRC="menu.asp">
    <FRAME NAME="main" SRC="welcome.asp">
  </FRAMESET>
</FRAMESET></HTML>"""
        )

    @app.get("/t/{tenant}/banner.asp")
    async def banner(tenant: str, request: Request):
        cfg = tcfg(tenant)
        sess = session_for(request, tenant)
        who = USERS[sess.user]["name"] if sess else "NOT SIGNED ON"
        return HTMLResponse(
            f"""<HTML><HEAD><STYLE>{STYLE}</STYLE></HEAD><BODY STYLE="margin:0;background:{cfg.color};color:#fff">
<TABLE WIDTH="100%" CELLPADDING=6><TR><TD><FONT SIZE=3><B>{e(cfg.name)}</B></FONT><BR>
<FONT COLOR="#dfe6f3">Keystone Core 7.2 &middot; Teller Workstation</FONT></TD>
<TD ALIGN=RIGHT STYLE="color:#fff">Operator: {e(who)} &nbsp;|&nbsp; {date.today():%m/%d/%Y} &nbsp;|&nbsp;
<A HREF="signoff.asp" TARGET="_top" STYLE="color:#fff">Sign Off</A></TD></TR></TABLE></BODY></HTML>"""
        )

    @app.get("/t/{tenant}/menu.asp")
    async def menu(tenant: str, request: Request):
        cfg = tcfg(tenant)
        items = [
            (cfg.labels["member_inquiry"], "mbrinq.asp"),
            (cfg.labels["open_sub_menu"], "shareadd.asp"),
            ("Teller Transactions", "txn.asp"),
            ("Reports", "reports.asp"),
            ("Administration", "admin/users.asp"),
        ]
        rows = "".join(
            f"<TR><TD CLASS=mnu onClick=\"parent.main.location.href='{u}'\">{e(t)}</TD></TR>" for t, u in items
        )
        return HTMLResponse(
            f"""<HTML><HEAD><STYLE>{STYLE}</STYLE></HEAD><BODY STYLE="margin:0;background:#dcd9cc">
<TABLE WIDTH="100%" CELLSPACING=0 CELLPADDING=0><TR><TD CLASS=hdr BGCOLOR="#555">&nbsp;Functions</TD></TR>{rows}
</TABLE></BODY></HTML>"""
        )

    @app.get("/t/{tenant}/welcome.asp")
    async def welcome(tenant: str, request: Request):
        cfg, sess, stop = await gate(request, tenant, "welcome.asp")
        if stop:
            return stop
        return page(
            cfg,
            "Teller Workstation",
            header_bar(cfg, "Teller Workstation")
            + "<P>Select a function from the menu on the left.</P>"
            '<P CLASS=note>Host status: <B>ONLINE</B> &nbsp; Branch 001 &nbsp; Drawer 04</P>',
        )

    @app.post("/t/{tenant}/notice.asp")
    async def notice_ack(tenant: str, request: Request):
        form = await request.form()
        return RedirectResponse(str(form.get("next") or "welcome.asp"), status_code=303)

    @app.post("/t/{tenant}/bulletin.asp")
    async def bulletin_ack(tenant: str, request: Request):
        sess = session_for(request, tenant)
        if sess:
            sess.bulletin_ack = True
        form = await request.form()
        return RedirectResponse(str(form.get("next") or "welcome.asp"), status_code=303)

    # ------------------------------------------------------------- member inquiry

    def inquiry_form(cfg: TenantConfig, message: str = "", results: str = "", values: dict | None = None) -> HTMLResponse:
        v = values or {}
        lb = cfg.labels
        script = """
function doSearch(){
  var f=document.frmInq;
  if(!f.txtMbrNo.value && !f.txtLName.value && !f.txtSsn4.value){ alert('Enter at least one search criterion.'); return; }
  f.submit();
}"""
        body = (
            header_bar(cfg, cfg.labels["member_inquiry"])
            + (err(message) if message else "")
            + '<FORM NAME="frmInq" METHOD=POST ACTION="mbrinq.asp" onSubmit="return false;">'
            + viewstate()
            + "<TABLE BORDER=0 CELLPADDING=3>"
            f'<TR><TD CLASS=lbl>{e(lb["member_number"])}:</TD><TD><INPUT TYPE=TEXT NAME="txtMbrNo" ID="{rid()}" '
            f'SIZE=12 MAXLENGTH=10 VALUE="{e(v.get("txtMbrNo", ""))}"></TD></TR>'
            f'<TR><TD CLASS=lbl>{e(lb["last_name"])}:</TD><TD><INPUT TYPE=TEXT NAME="txtLName" ID="{rid()}" SIZE=20 '
            f'VALUE="{e(v.get("txtLName", ""))}"></TD></TR>'
            f'<TR><TD CLASS=lbl>{e(lb["ssn4"])}:</TD><TD><INPUT TYPE=TEXT NAME="txtSsn4" ID="{rid()}" SIZE=4 '
            'MAXLENGTH=4></TD></TR>'
            '<TR><TD></TD><TD><INPUT TYPE=BUTTON CLASS=btn VALUE="Search" onClick="doSearch()"> '
            '<INPUT TYPE=BUTTON CLASS=btn VALUE="Clear" onClick="document.frmInq.reset()"></TD></TR>'
            "</TABLE></FORM>" + results
        )
        return page(cfg, cfg.labels["member_inquiry"], body, script)

    @app.get("/t/{tenant}/mbrinq.asp")
    async def inquiry(tenant: str, request: Request):
        cfg, sess, stop = await gate(request, tenant, "mbrinq.asp")
        return stop or inquiry_form(cfg)

    @app.post("/t/{tenant}/mbrinq.asp")
    async def inquiry_post(tenant: str, request: Request):
        cfg, sess, stop = await gate(request, tenant, "mbrinq.asp")
        if stop:
            return stop
        assert sess
        form = await request.form()
        values = {k: str(v).strip() for k, v in form.items()}
        mbr, lname, ssn4 = values.get("txtMbrNo", ""), values.get("txtLName", ""), values.get("txtSsn4", "")
        members = st.members[tenant]
        if mbr:
            if not mbr.isdigit():
                return inquiry_form(cfg, "Member number must be numeric.", values=values)
            m = members.get(mbr)
            if not m:
                return inquiry_form(cfg, "No records match your search criteria.", values=values)
            return RedirectResponse(f"mbrdtl.asp?m={m.number}&_k={token(sess, m.number)}", status_code=303)
        hits = [
            m
            for m in members.values()
            if (not lname or m.last.lower().startswith(lname.lower())) and (not ssn4 or m.ssn.endswith(ssn4))
        ]
        if not hits:
            return inquiry_form(cfg, "No records match your search criteria.", values=values)
        rows = "".join(
            f'<TR><TD><A HREF="mbrdtl.asp?m={m.number}&amp;_k={token(sess, m.number)}">{m.number}</A></TD>'
            f"<TD>{e(m.display_name)}</TD><TD>{e(m.address.split(',')[1].strip())}</TD></TR>"
            for m in hits
        )
        results = (
            f"<P><B>{len(hits)} member(s) found.</B></P>"
            '<TABLE CLASS=grid CELLSPACING=0><TR><TD CLASS=gh>Member #</TD><TD CLASS=gh>Name</TD>'
            f"<TD CLASS=gh>City</TD></TR>{rows}</TABLE>"
        )
        return inquiry_form(cfg, results=results, values=values)

    @app.get("/t/{tenant}/mbrdtl.asp")
    async def member_detail(tenant: str, request: Request, m: str = "", _k: str = ""):
        cfg, sess, stop = await gate(request, tenant, "mbrdtl.asp")
        if stop:
            return stop
        assert sess
        mem = member_of(tenant, m)
        if not mem or _k != token(sess, m):
            return page(cfg, "Error", header_bar(cfg, "Error") + err("KC-APP-0031: Invalid request context."))
        lb = cfg.labels
        info = [
            (lb["member_number"], mem.number),
            ("Name", mem.display_name),
            ("Member Since", mem.since),
            ("SSN", "***-**-" + mem.ssn[-4:]),
            ("Date of Birth", mem.dob),
            ("Address", mem.address),
            ("Home Phone", mem.phone),
            ("E-Mail", mem.email),
        ]
        info_html = "".join(f"<TR><TD CLASS=lbl>{e(k)}:</TD><TD CLASS=val>{e(v)}</TD></TR>" for k, v in info)
        if mem.restriction:
            accounts_html = (
                '<TABLE BORDER=2 CELLPADDING=6 BGCOLOR="#ffe9e9"><TR><TD><FONT COLOR="#AA0000"><B>'
                f"*** ACCOUNT RESTRICTED: {e(mem.restriction)} ***</B></FONT><BR>"
                "Account information is not available. Refer the member to a supervisor.</TD></TR></TABLE>"
            )
            actions = ""
        else:
            rows = "".join(
                f"<TR><TD>{a.suffix}</TD><TD>{e(cfg.products[a.product])}</TD><TD>{e(a.status)}</TD>"
                f"<TD ALIGN=RIGHT>{money(a.current)}</TD><TD ALIGN=RIGHT>{money(a.available)}</TD></TR>"
                for a in mem.accounts
            )
            accounts_html = (
                "<B>Accounts</B><TABLE CLASS=grid CELLSPACING=0 WIDTH=620>"
                "<TR><TD CLASS=gh>Suffix</TD><TD CLASS=gh>Description</TD><TD CLASS=gh>Status</TD>"
                f'<TD CLASS=gh ALIGN=RIGHT>{e(lb["current_balance"])}</TD>'
                f'<TD CLASS=gh ALIGN=RIGHT>{e(lb["available_balance"])}</TD></TR>{rows}</TABLE>'
            )
            actions = (
                '<BR><DIV CLASS=bar><A HREF="javascript:openSub()">' + e(lb["open_sub_action"]) + "</A> &nbsp;|&nbsp; "
                '<A HREF="javascript:alert(\'Transaction history is not available in this demo.\')">Transaction History</A>'
                " &nbsp;|&nbsp; <A HREF=\"javascript:window.print()\">Print</A></DIV>"
            )
        confirm = (
            "if(!confirm('This member has a pending address change that has not been verified.\\n"
            "Continue opening a new sub-account?')) return;"
            if mem.pending_address_change
            else ""
        )
        script = f"function openSub(){{ {confirm} location.href='shareadd.asp?m={mem.number}&_k={token(sess, mem.number)}'; }}"
        body = (
            header_bar(cfg, f"Member Detail - {mem.number}")
            + f"<TABLE><TR><TD VALIGN=TOP><TABLE CELLPADDING=2>{info_html}</TABLE></TD></TR></TABLE><BR>"
            + accounts_html
            + actions
        )
        return page(cfg, "Member Detail", body, script)

    # ------------------------------------------------------------- open sub-account

    def open_form(cfg: TenantConfig, sess: Session, mem: Member, message: str = "", v: dict | None = None):
        v = v or {}
        prod_opts = "".join(
            f'<OPTION VALUE="{c}"{" SELECTED" if v.get("selProduct") == c else ""}>{e(cfg.products[c])}</OPTION>'
            for c in OPENABLE
        )
        fund_opts = "".join(
            f'<OPTION VALUE="{a.suffix}"{" SELECTED" if v.get("selFund") == a.suffix else ""}>'
            f"{a.suffix} - {e(cfg.products[a.product])} ({money(a.available)} avail)</OPTION>"
            for a in mem.accounts
            if a.status == "Open"
        )
        body = (
            header_bar(cfg, f"Open Sub-Account - Member {mem.number}")
            + f"<P>Member: <B>{e(mem.display_name)}</B></P>"
            + (err(message) if message else "")
            + f'<FORM NAME="frmOpen" METHOD=POST ACTION="shareadd.asp?m={mem.number}&amp;_k={token(sess, mem.number)}">'
            + viewstate()
            + "<TABLE CELLPADDING=3>"
            f'<TR><TD CLASS=lbl>Product:</TD><TD><SELECT NAME="selProduct" ID="{rid()}">'
            f'<OPTION VALUE="">-- Select --</OPTION>{prod_opts}</SELECT></TD></TR>'
            f'<TR><TD CLASS=lbl>Account Nickname:</TD><TD><INPUT TYPE=TEXT NAME="txtNick" ID="{rid()}" SIZE=20 '
            f'MAXLENGTH=20 VALUE="{e(v.get("txtNick", ""))}"></TD></TR>'
            f'<TR><TD CLASS=lbl>Opening Deposit:</TD><TD><INPUT TYPE=TEXT NAME="txtDep" ID="{rid()}" SIZE=12 '
            f'VALUE="{e(v.get("txtDep", ""))}"></TD></TR>'
            f'<TR><TD CLASS=lbl>Fund From:</TD><TD><SELECT NAME="selFund" ID="{rid()}">'
            f'<OPTION VALUE="">-- Select --</OPTION>{fund_opts}</SELECT></TD></TR>'
            '<TR><TD></TD><TD><INPUT TYPE=SUBMIT CLASS=btn VALUE="Continue"> '
            f"<INPUT TYPE=BUTTON CLASS=btn VALUE=\"Cancel\" onClick=\"location.href='mbrdtl.asp?m={mem.number}&_k={token(sess, mem.number)}'\">"
            "</TD></TR></TABLE></FORM>"
        )
        return page(cfg, "Open Sub-Account", body)

    @app.get("/t/{tenant}/shareadd.asp")
    async def open_get(tenant: str, request: Request, m: str = "", _k: str = ""):
        cfg, sess, stop = await gate(request, tenant, "shareadd.asp")
        if stop:
            return stop
        assert sess
        mem = member_of(tenant, m)
        if not m:
            return page(
                cfg,
                "Open Sub-Account",
                header_bar(cfg, "Open Sub-Account")
                + f"<P>Select a member first using <B>{e(cfg.labels['member_inquiry'])}</B>.</P>",
            )
        if not mem or _k != token(sess, m):
            return page(cfg, "Error", header_bar(cfg, "Error") + err("KC-APP-0031: Invalid request context."))
        return open_form(cfg, sess, mem)

    @app.post("/t/{tenant}/shareadd.asp")
    async def open_post(tenant: str, request: Request, m: str = "", _k: str = ""):
        cfg, sess, stop = await gate(request, tenant, "shareadd.asp")
        if stop:
            return stop
        assert sess
        mem = member_of(tenant, m)
        if not mem or _k != token(sess, m):
            return page(cfg, "Error", header_bar(cfg, "Error") + err("KC-APP-0031: Invalid request context."))
        form = await request.form()
        v = {k: str(x).strip() for k, x in form.items()}
        product, nick, dep_raw, fund = v.get("selProduct", ""), v.get("txtNick", ""), v.get("txtDep", ""), v.get("selFund", "")
        if product not in OPENABLE:
            return open_form(cfg, sess, mem, "Product is required.", v)
        if not nick:
            return open_form(cfg, sess, mem, "Account nickname is required.", v)
        try:
            dep = Decimal(dep_raw.replace("$", "").replace(",", ""))
        except InvalidOperation:
            return open_form(cfg, sess, mem, "Opening deposit must be a dollar amount.", v)
        minimum, _rate = PRODUCTS[product]
        if dep < minimum:
            return open_form(
                cfg, sess, mem,
                f"Opening deposit of {money(dep)} is below the minimum of {money(minimum)} for {cfg.products[product]}.",
                v,
            )
        src = next((a for a in mem.accounts if a.suffix == fund and a.status == "Open"), None)
        if dep > 0 and not src:
            return open_form(cfg, sess, mem, "Select a funding account.", v)
        if src and dep > src.available:
            return open_form(cfg, sess, mem, f"Insufficient available funds in suffix {src.suffix}.", v)
        pid = secrets.token_hex(4)
        st.pending[pid] = PendingOpen(pid, mem.number, product, nick, dep, fund, needs_override=dep > SUPERVISOR_LIMIT)
        nxt = "ovrd.asp" if dep > SUPERVISOR_LIMIT else "sharerev.asp"
        return RedirectResponse(f"{nxt}?r={pid}", status_code=303)

    @app.get("/t/{tenant}/ovrd.asp")
    async def override_get(tenant: str, request: Request, r: str = "", message: str = ""):
        cfg, sess, stop = await gate(request, tenant, "ovrd.asp")
        if stop:
            return stop
        p = st.pending.get(r)
        if not p:
            return page(cfg, "Error", header_bar(cfg, "Error") + err("KC-APP-0044: Pending request not found."))
        body = (
            header_bar(cfg, "Supervisor Override Required")
            + err(f"Opening deposit of {money(p.deposit)} exceeds the teller limit of {money(SUPERVISOR_LIMIT)}.")
            + (err(message) if message else "")
            + "<P>A supervisor must authorize this transaction at this workstation.</P>"
            f'<FORM METHOD=POST ACTION="ovrd.asp?r={p.rid}"><TABLE CELLPADDING=3>'
            f'<TR><TD CLASS=lbl>Supervisor ID:</TD><TD><INPUT TYPE=TEXT NAME="supId" ID="{rid()}" SIZE=12></TD></TR>'
            f'<TR><TD CLASS=lbl>Override Code:</TD><TD><INPUT TYPE=PASSWORD NAME="supCode" ID="{rid()}" SIZE=8></TD></TR>'
            '<TR><TD></TD><TD><INPUT TYPE=SUBMIT CLASS=btn VALUE="Submit Override"></TD></TR></TABLE></FORM>'
        )
        return page(cfg, "Supervisor Override", body)

    @app.post("/t/{tenant}/ovrd.asp")
    async def override_post(tenant: str, request: Request, r: str = ""):
        cfg, sess, stop = await gate(request, tenant, "ovrd.asp")
        if stop:
            return stop
        p = st.pending.get(r)
        form = await request.form()
        sup, code = str(form.get("supId", "")), str(form.get("supCode", ""))
        if not p:
            return page(cfg, "Error", header_bar(cfg, "Error") + err("KC-APP-0044: Pending request not found."))
        if SUPERVISORS.get(sup) != code:
            return RedirectResponse(
                f"ovrd.asp?r={p.rid}&message={quote('Override rejected: invalid supervisor credentials.')}",
                status_code=303,
            )
        p.overridden_by = sup
        return RedirectResponse(f"sharerev.asp?r={p.rid}", status_code=303)

    @app.get("/t/{tenant}/sharerev.asp")
    async def review_get(tenant: str, request: Request, r: str = ""):
        cfg, sess, stop = await gate(request, tenant, "sharerev.asp")
        if stop:
            return stop
        p = st.pending.get(r)
        if not p:
            return page(cfg, "Error", header_bar(cfg, "Error") + err("KC-APP-0044: Pending request not found."))
        if p.needs_override and not p.overridden_by:
            return RedirectResponse(f"ovrd.asp?r={p.rid}", status_code=303)
        mem = member_of(tenant, p.member)
        assert mem
        src = next((a for a in mem.accounts if a.suffix == p.fund_from), None)
        rows = [
            ("Member", f"{mem.number} - {mem.display_name}"),
            ("Product", cfg.products[p.product]),
            ("Account Nickname", p.nickname),
            ("Opening Deposit", money(p.deposit)),
            ("Fund From", f"{src.suffix} - {cfg.products[src.product]}" if src else "(none)"),
            ("Dividend Rate", PRODUCTS[p.product][1]),
        ]
        if p.overridden_by:
            rows.append(("Supervisor Override", p.overridden_by.upper()))
        table = "".join(f"<TR><TD CLASS=lbl>{e(k)}:</TD><TD CLASS=val>{e(v)}</TD></TR>" for k, v in rows)
        body = (
            header_bar(cfg, "Review New Sub-Account")
            + "<P>Please verify the information below with the member. Press <B>Confirm &amp; Open Account</B> "
            "to open the account. This action cannot be undone.</P>"
            + f"<TABLE CELLPADDING=3>{table}</TABLE><BR>"
            f'<FORM METHOD=POST ACTION="sharerev.asp?r={p.rid}">'
            '<INPUT TYPE=SUBMIT NAME="action" CLASS=btn VALUE="Confirm &amp; Open Account"> '
            '<INPUT TYPE=SUBMIT NAME="action" CLASS=btn VALUE="Back"> '
            '<INPUT TYPE=SUBMIT NAME="action" CLASS=btn VALUE="Cancel"></FORM>'
        )
        return page(cfg, "Review New Sub-Account", body)

    @app.post("/t/{tenant}/sharerev.asp")
    async def review_post(tenant: str, request: Request, r: str = ""):
        cfg, sess, stop = await gate(request, tenant, "sharerev.asp")
        if stop:
            return stop
        assert sess
        p = st.pending.get(r)
        if not p:
            return page(cfg, "Error", header_bar(cfg, "Error") + err("KC-APP-0044: Pending request not found."))
        form = await request.form()
        action = str(form.get("action", ""))
        mem = member_of(tenant, p.member)
        assert mem
        back = f"mbrdtl.asp?m={mem.number}&_k={token(sess, mem.number)}"
        if action.startswith("Back"):
            q = urlencode({"m": mem.number, "_k": token(sess, mem.number)})
            return RedirectResponse(f"shareadd.asp?{q}", status_code=303)
        if not action.startswith("Confirm"):
            st.pending.pop(p.rid, None)
            return RedirectResponse(back, status_code=303)
        if p.needs_override and not p.overridden_by:
            return RedirectResponse(f"ovrd.asp?r={p.rid}", status_code=303)
        used = {a.suffix for a in mem.accounts}
        suffix = next(f"{n:02d}" for n in range(20, 100) if f"{n:02d}" not in used)
        src = next((a for a in mem.accounts if a.suffix == p.fund_from), None)
        if src and p.deposit > 0:
            src.current -= p.deposit
            src.available -= p.deposit
        mem.accounts.append(Account(suffix, p.product, "Open", p.deposit, p.deposit, p.nickname))
        conf = f"KC-{date.today():%Y%m%d}-{next(st.conf_seq):04d}"
        st.opened.append({"tenant": tenant, "member": mem.number, "suffix": suffix, "product": p.product, "conf": conf})
        st.pending.pop(p.rid, None)
        return RedirectResponse(f"sharecnf.asp?c={conf}&s={suffix}&m={mem.number}", status_code=303)

    @app.get("/t/{tenant}/sharecnf.asp")
    async def confirmation(tenant: str, request: Request, c: str = "", s: str = "", m: str = ""):
        cfg, sess, stop = await gate(request, tenant, "sharecnf.asp")
        if stop:
            return stop
        opened = next((o for o in st.opened if o["conf"] == c), None)
        if not opened:
            return page(cfg, "Error", header_bar(cfg, "Error") + err("KC-APP-0045: Confirmation not found."))
        rows = [
            ("Member Number", opened["member"]),
            ("New Suffix", opened["suffix"]),
            ("Product", cfg.products[opened["product"]]),
            ("Confirmation Number", opened["conf"]),
        ]
        table = "".join(f"<TR><TD CLASS=lbl>{e(k)}:</TD><TD CLASS=val>{e(v)}</TD></TR>" for k, v in rows)
        return page(
            cfg,
            "Sub-Account Opened",
            header_bar(cfg, "Sub-Account Opened")
            + "<P><B>The sub-account was opened successfully.</B></P>"
            + f"<TABLE CELLPADDING=3>{table}</TABLE>",
        )

    # ------------------------------------------------------------- other menu targets

    @app.get("/t/{tenant}/txn.asp")
    async def txn(tenant: str, request: Request):
        cfg, sess, stop = await gate(request, tenant, "txn.asp")
        return stop or page(cfg, "Teller Transactions", header_bar(cfg, "Teller Transactions")
                            + "<P>Teller transactions are not available in this workstation mode.</P>")

    @app.get("/t/{tenant}/reports.asp")
    async def reports(tenant: str, request: Request):
        cfg, sess, stop = await gate(request, tenant, "reports.asp")
        return stop or page(cfg, "Reports", header_bar(cfg, "Reports") + "<P>No reports are scheduled.</P>")

    @app.get("/t/{tenant}/admin/users.asp")
    async def admin_users(tenant: str, request: Request):
        cfg, sess, stop = await gate(request, tenant, "admin/users.asp")
        if stop:
            return stop
        rows = "".join(f"<TR><TD>{u}</TD><TD>{d['role']}</TD><TD><INPUT TYPE=BUTTON VALUE='Reset Password'></TD></TR>"
                       for u, d in USERS.items())
        return page(cfg, "User Administration", header_bar(cfg, "User Administration")
                    + f"<TABLE CLASS=grid>{rows}</TABLE>")

    @app.exception_handler(UnknownTenant)
    async def unknown_tenant(request: Request, exc: UnknownTenant):
        return Response("Unknown institution", status_code=404)

    return app


app = create_app()
