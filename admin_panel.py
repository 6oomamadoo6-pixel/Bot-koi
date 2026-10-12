import os
import hmac
import secrets
from datetime import datetime
from functools import wraps

import psycopg2
from flask import Blueprint, current_app, jsonify, request, render_template_string, session

admin_panel = Blueprint("admin_panel", __name__, url_prefix="/admin")
PAGE_SIZE = 10

HTML = r"""<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#10100f">
<title>Golden Chat | پنل مدیریت</title>
<style>
:root{color-scheme:dark;--bg:#0d0e0c;--panel:#171815;--panel2:#20211c;--line:#333329;--gold:#e8bd55;--gold2:#f6d987;--muted:#aaa99f;--text:#f7f4e9;--red:#e77a72;--green:#8bd3a6}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at top,#282315 0,#0d0e0c 46%);color:var(--text);font-family:Tahoma,"Noto Sans Arabic",sans-serif;min-height:100vh}
button,input{font:inherit}button{cursor:pointer}.wrap{max-width:1100px;margin:auto;padding:22px 16px 48px}.top{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:22px}.brand{display:flex;align-items:center;gap:12px}.logo{width:46px;height:46px;border-radius:15px;display:grid;place-items:center;background:linear-gradient(145deg,#f6d987,#a9791c);color:#18150b;font-size:24px;box-shadow:0 7px 25px #d9a63825}.brand h1{font-size:18px;margin:0 0 5px}.sub{font-size:12px;color:var(--muted)}.pill{border:1px solid #4d4328;color:var(--gold2);border-radius:999px;padding:8px 11px;font-size:11px;white-space:nowrap}.hero{background:linear-gradient(120deg,#2a2415,#171815 68%);border:1px solid #4c4025;border-radius:22px;padding:22px;margin-bottom:18px;position:relative;overflow:hidden}.hero:after{content:"✦";position:absolute;left:22px;top:5px;color:#e8bd551e;font-size:95px}.eyebrow{font-size:12px;color:var(--gold);margin-bottom:10px}.hero h2{font-size:22px;margin:0 0 9px;line-height:1.6}.hero p{font-size:13px;color:#c5c0b2;line-height:1.9;margin:0;max-width:620px}.stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:16px 0 22px}.stat,.card{background:#171815eF;border:1px solid var(--line);border-radius:18px}.stat{padding:16px}.stat .label{color:var(--muted);font-size:12px}.stat .num{font-size:25px;font-weight:700;color:var(--gold2);margin-top:11px;direction:ltr;text-align:right}.tabs{display:flex;gap:8px;overflow:auto;padding-bottom:4px;margin-bottom:14px}.tab{background:var(--panel);color:#c8c5b8;border:1px solid var(--line);padding:12px 16px;border-radius:12px;white-space:nowrap}.tab.active{background:#392f18;color:var(--gold2);border-color:#80642c}.card{padding:16px;margin-bottom:14px}.cardhead{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:15px}.cardhead h3{font-size:16px;margin:0}.searchrow{display:flex;gap:8px;margin-bottom:14px}.searchrow input,.loginbox input{width:100%;min-width:0;background:#0f100e;border:1px solid #414137;color:var(--text);border-radius:12px;padding:12px;outline:none}.searchrow input:focus,.loginbox input:focus{border-color:var(--gold)}.btn{border:1px solid #80642c;border-radius:12px;background:linear-gradient(135deg,#f1cf76,#c49330);color:#171307;font-weight:bold;padding:11px 14px;white-space:nowrap}.btn.ghost{background:#22231e;color:var(--gold2);border-color:#45402f}.btn.danger{background:#351d1b;color:#ffb4ac;border-color:#6e3732}.tablewrap{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:12px;min-width:520px}th{text-align:right;color:var(--gold2);font-weight:600;background:#24231b}th,td{padding:12px 10px;border-bottom:1px solid #303129;vertical-align:middle}td{color:#e5e2d8}td small{display:block;color:var(--muted);margin-top:5px;direction:ltr;text-align:right}.empty{padding:28px;text-align:center;color:var(--muted);font-size:13px}.pager{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:14px;color:var(--muted);font-size:12px}.hidden{display:none!important}.notice{padding:12px;border-radius:12px;background:#252116;border:1px solid #5a4825;color:var(--gold2);font-size:12px;line-height:1.8;margin-bottom:12px}.error{color:#ffaaa2}.loginbox{max-width:440px;margin:10vh auto;background:var(--panel);border:1px solid #4a4028;border-radius:22px;padding:24px;box-shadow:0 25px 70px #0007}.loginbox h2{margin:0 0 8px}.loginbox p{color:var(--muted);font-size:13px;line-height:1.9;margin-bottom:20px}.loginbox label{display:block;font-size:12px;margin:12px 0 8px}.loginbox .btn{width:100%;margin-top:14px}.foot{text-align:center;color:#77766d;font-size:11px;margin-top:26px}.userbadge{display:inline-block;background:#29271e;color:var(--gold2);border-radius:7px;padding:5px 7px;direction:ltr}.toast{position:fixed;bottom:20px;right:16px;left:16px;max-width:480px;margin:auto;background:#24251f;border:1px solid #51452a;border-radius:12px;padding:14px;z-index:10;font-size:13px;box-shadow:0 8px 30px #0008}
@media(min-width:760px){.wrap{padding:32px 24px}.hero{padding:28px}.hero h2{font-size:27px}.stats{gap:16px}.stat{padding:21px}.card{padding:20px}}@media(max-width:420px){.stats{gap:8px}.stat{padding:12px}.stat .num{font-size:21px}.stat .label{font-size:11px}.hero h2{font-size:19px}.pill{font-size:10px}}
</style>
</head>
<body>
<div id="loginView" class="wrap hidden">
  <div class="loginbox">
    <div class="brand"><div class="logo">✦</div><div><h1>Golden Chat</h1><div class="sub">پنل مدیریت امن</div></div></div>
    <h2 style="margin-top:24px">خوش اومدی مدیر 👋</h2>
    <p>برای دسترسی به آمار کاربران و مدیریت مسدودی‌ها، رمز پنل را وارد کن.</p>
    <form id="loginForm"><label for="password">رمز عبور پنل</label><input id="password" type="password" autocomplete="current-password" required placeholder="رمز عبور امن"><button class="btn" type="submit">ورود به پنل ←</button></form>
    <div id="loginError" class="error" style="font-size:12px;margin-top:12px"></div>
  </div>
</div>
<div id="appView" class="wrap hidden">
  <header class="top"><div class="brand"><div class="logo">✦</div><div><h1>Golden Chat</h1><div class="sub">پنل مدیریت ربات</div></div></div><div style="display:flex;gap:8px;align-items:center"><span class="pill">● اتصال امن</span><button class="btn ghost" id="logoutBtn">خروج</button></div></header>
  <section class="hero"><div class="eyebrow">GOLDEN CHAT / ADMIN</div><h2>سلام مدیر، خوش اومدی ✨</h2><p>از اینجا وضعیت ربات رو ببین، کاربران رو جست‌وجو کن و فهرست مسدودی‌ها رو مدیریت کن. اطلاعات از دیتابیس فعلی خوانده می‌شه و دیتابیس جدیدی ساخته نمی‌شه.</p></section>
  <section class="stats"><div class="stat"><div class="label">👥 کل کاربران</div><div id="usersCount" class="num">—</div></div><div class="stat"><div class="label">🔴 موارد مسدودی کاربران</div><div id="blocksCount" class="num">—</div></div><div class="stat"><div class="label">✉️ پیام‌های ناشناس</div><div id="messagesCount" class="num">—</div></div></section>
  <nav class="tabs"><button class="tab active" data-tab="users">👥 کاربران</button><button class="tab" data-tab="blocks">🔴 لیست مسدودی‌ها</button></nav>
  <section id="usersPanel" class="card"><div class="cardhead"><h3>کاربران ربات</h3><span class="pill">جست‌وجو و مشاهده</span></div><form id="userSearch" class="searchrow"><input id="userQuery" placeholder="جست‌وجو با آیدی، یوزرنیم یا نام" autocomplete="off"><button class="btn" type="submit">جست‌وجو</button></form><div id="usersTable" class="tablewrap"><div class="empty">در حال دریافت اطلاعات…</div></div><div class="pager"><button id="prevUsers" class="btn ghost">قبلی</button><span id="userPage">صفحه ۱</span><button id="nextUsers" class="btn ghost">بعدی</button></div></section>
  <section id="blocksPanel" class="card hidden"><div class="cardhead"><h3>لیست مسدودی‌ها</h3><span class="pill">مسدودسازی بین کاربران</span></div><form id="blockSearch" class="searchrow"><input id="blockQuery" placeholder="جست‌وجو با آیدی یا یوزرنیم" autocomplete="off"><button class="btn" type="submit">جست‌وجو</button></form><div class="notice">رفع مسدودی، فقط رابطهٔ مسدودسازی انتخاب‌شده را حذف می‌کند؛ حساب کاربر یا کدهای ناشناس حذف نمی‌شوند.</div><div id="blocksTable" class="tablewrap"><div class="empty">در حال دریافت اطلاعات…</div></div><div class="pager"><button id="prevBlocks" class="btn ghost">قبلی</button><span id="blockPage">صفحه ۱</span><button id="nextBlocks" class="btn ghost">بعدی</button></div></section>
  <div class="foot">Golden Chat • پنل خصوصی مدیریت</div>
</div>
<div id="toast" class="toast hidden"></div>
<script>
var csrfToken="", userPage=1, blockPage=1, userQuery="", blockQuery="", activeTab="users";
function el(id){return document.getElementById(id)}
function esc(value){return String(value==null?"":value).replace(/[&<>"']/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]})}
function toast(message){el("toast").textContent=message;el("toast").classList.remove("hidden");setTimeout(function(){el("toast").classList.add("hidden")},3000)}
async function api(path,options){options=options||{};options.credentials="same-origin";options.headers=Object.assign({"Content-Type":"application/json","X-CSRF-Token":csrfToken},options.headers||{});var response=await fetch("/admin/api/"+path,options);var data=await response.json().catch(function(){return {error:"پاسخ نامعتبر از سرور"}});if(response.status===401){showLogin();throw new Error(data.error||"ابتدا وارد شوید")}if(!response.ok)throw new Error(data.error||"خطا در ارتباط با سرور");return data}
function showLogin(){el("appView").classList.add("hidden");el("loginView").classList.remove("hidden")}
function showApp(){el("loginView").classList.add("hidden");el("appView").classList.remove("hidden")}
async function init(){try{var s=await fetch("/admin/api/session",{credentials:"same-origin"});var d=await s.json();csrfToken=d.csrf_token||"";if(d.authenticated){showApp();await loadAll()}else showLogin()}catch(e){showLogin()}}
el("loginForm").addEventListener("submit",async function(e){e.preventDefault();el("loginError").textContent="";try{var d=await api("login",{method:"POST",body:JSON.stringify({password:el("password").value})});csrfToken=d.csrf_token||csrfToken;el("password").value="";showApp();await loadAll()}catch(err){el("loginError").textContent=err.message}})
el("logoutBtn").addEventListener("click",async function(){try{await api("logout",{method:"POST",body:"{}"})}catch(e){}showLogin();toast("از پنل خارج شدی")})
document.querySelectorAll(".tab").forEach(function(button){button.addEventListener("click",function(){activeTab=button.dataset.tab;document.querySelectorAll(".tab").forEach(function(b){b.classList.toggle("active",b===button)});el("usersPanel").classList.toggle("hidden",activeTab!=="users");el("blocksPanel").classList.toggle("hidden",activeTab!=="blocks");if(activeTab==="blocks")loadBlocks()})})
async function loadAll(){await Promise.all([loadStats(),loadUsers(),loadBlocks()])}
async function loadStats(){try{var d=await api("stats");el("usersCount").textContent=Number(d.users||0).toLocaleString("fa-IR");el("blocksCount").textContent=Number(d.blocks||0).toLocaleString("fa-IR");el("messagesCount").textContent=Number(d.messages||0).toLocaleString("fa-IR")}catch(e){toast(e.message)}}
async function loadUsers(){el("usersTable").innerHTML='<div class="empty">در حال دریافت اطلاعات…</div>';try{var d=await api("users?page="+userPage+"&q="+encodeURIComponent(userQuery));el("usersTable").innerHTML= d.items.length?'<table><thead><tr><th>کاربر</th><th>شناسه</th><th>عضویت</th></tr></thead><tbody>'+d.items.map(function(u){return '<tr><td>'+esc(u.display_name||u.full_name||"بدون نام")+(u.username?'<small>@'+esc(u.username)+'</small>':'')+'</td><td><span class="userbadge">'+esc(u.user_id)+'</span></td><td>'+esc(u.created_at||"—")+'</td></tr>'}).join("")+'</tbody></table>':'<div class="empty">کاربری پیدا نشد.</div>';el("userPage").textContent="صفحه "+userPage+" از "+Math.max(1,d.pages);el("prevUsers").disabled=userPage<=1;el("nextUsers").disabled=userPage>=d.pages}catch(e){el("usersTable").innerHTML='<div class="empty error">'+esc(e.message)+'</div>'}}
async function loadBlocks(){el("blocksTable").innerHTML='<div class="empty">در حال دریافت اطلاعات…</div>';try{var d=await api("blocks?page="+blockPage+"&q="+encodeURIComponent(blockQuery));el("blocksTable").innerHTML=d.items.length?'<table><thead><tr><th>مسدودکننده</th><th>کاربر مسدودشده</th><th>تاریخ</th><th>عملیات</th></tr></thead><tbody>'+d.items.map(function(b){return '<tr><td>'+esc(b.blocker_name||"بدون نام")+'<small>'+esc(b.blocker_id)+'</small></td><td>'+esc(b.blocked_name||"بدون نام")+'<small>'+esc(b.blocked_id)+'</small></td><td>'+esc(b.created_at||"—")+'</td><td><button class="btn danger" data-unblock="'+esc(b.blocker_id)+'" data-blocked="'+esc(b.blocked_id)+'">رفع مسدودی</button></td></tr>'}).join("")+'</tbody></table>':'<div class="empty">موردی پیدا نشد.</div>';el("blockPage").textContent="صفحه "+blockPage+" از "+Math.max(1,d.pages);el("prevBlocks").disabled=blockPage<=1;el("nextBlocks").disabled=blockPage>=d.pages;document.querySelectorAll("[data-unblock]").forEach(function(btn){btn.addEventListener("click",async function(){if(!confirm("فقط این رابطهٔ مسدودی حذف شود؟"))return;try{await api("blocks/unblock",{method:"POST",body:JSON.stringify({blocker_id:btn.dataset.unblock,blocked_id:btn.dataset.blocked})});toast("مسدودی رفع شد");await Promise.all([loadBlocks(),loadStats()])}catch(e){toast(e.message)}})})}catch(e){el("blocksTable").innerHTML='<div class="empty error">'+esc(e.message)+'</div>'}}
el("userSearch").addEventListener("submit",function(e){e.preventDefault();userQuery=el("userQuery").value.trim();userPage=1;loadUsers()});el("blockSearch").addEventListener("submit",function(e){e.preventDefault();blockQuery=el("blockQuery").value.trim();blockPage=1;loadBlocks()});el("prevUsers").addEventListener("click",function(){if(userPage>1){userPage--;loadUsers()}});el("nextUsers").addEventListener("click",function(){userPage++;loadUsers()});el("prevBlocks").addEventListener("click",function(){if(blockPage>1){blockPage--;loadBlocks()}});el("nextBlocks").addEventListener("click",function(){blockPage++;loadBlocks()});
init();
</script>
</body>
</html>"""


def _db():
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL is not configured")
    return psycopg2.connect(dsn, connect_timeout=8)


def _json_error(message, status):
    return jsonify({"error": message}), status


def _csrf_ok():
    supplied = request.headers.get("X-CSRF-Token", "")
    expected = session.get("csrf_token", "")
    return bool(supplied and expected and hmac.compare_digest(supplied, expected))


def _auth_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("admin_authenticated"):
            return _json_error("برای ادامه وارد پنل شو.", 401)
        return fn(*args, **kwargs)
    return wrapped


def _csrf_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not _csrf_ok():
            return _json_error("درخواست معتبر نیست؛ صفحه را تازه کن.", 403)
        return fn(*args, **kwargs)
    return wrapped


def _configured():
    return bool(os.getenv("ADMIN_PANEL_PASSWORD") and os.getenv("ADMIN_PANEL_SECRET_KEY"))


@admin_panel.get("/")
def index():
    session.setdefault("csrf_token", secrets.token_urlsafe(32))
    return render_template_string(HTML)


@admin_panel.get("/api/session")
def session_status():
    session.setdefault("csrf_token", secrets.token_urlsafe(32))
    return jsonify({
        "authenticated": bool(session.get("admin_authenticated")),
        "csrf_token": session["csrf_token"],
        "configured": _configured(),
    })


@admin_panel.post("/api/login")
@_csrf_required
def login():
    if not _configured():
        return _json_error("مدیر باید ADMIN_PANEL_PASSWORD و ADMIN_PANEL_SECRET_KEY را در تنظیمات Deplexo ثبت کند.", 503)
    payload = request.get_json(silent=True) or {}
    supplied = str(payload.get("password", ""))
    expected = os.getenv("ADMIN_PANEL_PASSWORD", "")
    if not supplied or not hmac.compare_digest(supplied, expected):
        return _json_error("رمز عبور اشتباه است.", 401)
    session.clear()
    session["admin_authenticated"] = True
    session["csrf_token"] = secrets.token_urlsafe(32)
    session.permanent = True
    return jsonify({"ok": True, "csrf_token": session["csrf_token"]})


@admin_panel.post("/api/logout")
@_auth_required
@_csrf_required
def logout():
    session.clear()
    return jsonify({"ok": True})


@admin_panel.get("/api/stats")
@_auth_required
def stats():
    conn = _db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users")
            users = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM blocks")
            blocks = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM anonymous_messages")
            messages = cur.fetchone()[0]
        return jsonify({"users": users, "blocks": blocks, "messages": messages})
    finally:
        conn.close()


def _pages(total):
    return max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)


@admin_panel.get("/api/users")
@_auth_required
def users():
    q = request.args.get("q", "").strip()[:100]
    try:
        page = max(1, min(100000, int(request.args.get("page", "1"))))
    except ValueError:
        page = 1
    pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    where = ""
    params = []
    if q:
        where = "WHERE CAST(user_id AS TEXT) ILIKE %s OR COALESCE(username,'') ILIKE %s OR COALESCE(full_name,'') ILIKE %s OR COALESCE(display_name,'') ILIKE %s"
        params = [pattern, pattern, pattern, pattern]
    conn = _db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users " + where, params)
            total = cur.fetchone()[0]
            cur.execute(
                "SELECT user_id, username, full_name, display_name, created_at FROM users "
                + where + " ORDER BY created_at DESC NULLS LAST, user_id DESC LIMIT %s OFFSET %s",
                params + [PAGE_SIZE, (page - 1) * PAGE_SIZE]
            )
            rows = cur.fetchall()
        items = [{
            "user_id": row[0],
            "username": row[1],
            "full_name": row[2],
            "display_name": row[3],
            "created_at": row[4].strftime("%Y-%m-%d") if row[4] else None,
        } for row in rows]
        return jsonify({"items": items, "page": page, "pages": _pages(total), "total": total})
    finally:
        conn.close()


@admin_panel.get("/api/blocks")
@_auth_required
def blocks():
    q = request.args.get("q", "").strip()[:100]
    try:
        page = max(1, min(100000, int(request.args.get("page", "1"))))
    except ValueError:
        page = 1
    pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    where = ""
    params = []
    if q:
        where = """WHERE CAST(b.blocker_id AS TEXT) ILIKE %s
          OR CAST(b.blocked_id AS TEXT) ILIKE %s
          OR COALESCE(u1.username,'') ILIKE %s
          OR COALESCE(u2.username,'') ILIKE %s
          OR COALESCE(u1.full_name,'') ILIKE %s
          OR COALESCE(u2.full_name,'') ILIKE %s"""
        params = [pattern] * 6
    conn = _db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM blocks b LEFT JOIN users u1 ON u1.user_id=b.blocker_id LEFT JOIN users u2 ON u2.user_id=b.blocked_id " + where, params)
            total = cur.fetchone()[0]
            cur.execute(
                """SELECT b.blocker_id, b.blocked_id, b.created_at,
                    COALESCE(NULLIF(u1.display_name,''), NULLIF(u1.full_name,''), u1.username, '') AS blocker_name,
                    COALESCE(NULLIF(u2.display_name,''), NULLIF(u2.full_name,''), u2.username, '') AS blocked_name
                    FROM blocks b
                    LEFT JOIN users u1 ON u1.user_id=b.blocker_id
                    LEFT JOIN users u2 ON u2.user_id=b.blocked_id
                    """ + where + " ORDER BY b.created_at DESC NULLS LAST LIMIT %s OFFSET %s",
                params + [PAGE_SIZE, (page - 1) * PAGE_SIZE]
            )
            rows = cur.fetchall()
        items = [{
            "blocker_id": row[0], "blocked_id": row[1], "created_at": row[2].strftime("%Y-%m-%d") if row[2] else None,
            "blocker_name": row[3], "blocked_name": row[4],
        } for row in rows]
        return jsonify({"items": items, "page": page, "pages": _pages(total), "total": total})
    finally:
        conn.close()


@admin_panel.post("/api/blocks/unblock")
@_auth_required
@_csrf_required
def unblock():
    payload = request.get_json(silent=True) or {}
    try:
        blocker_id = int(payload.get("blocker_id"))
        blocked_id = int(payload.get("blocked_id"))
    except (TypeError, ValueError):
        return _json_error("شناسهٔ کاربر معتبر نیست.", 400)
    if blocker_id == blocked_id:
        return _json_error("شناسه‌ها نمی‌توانند یکسان باشند.", 400)
    conn = _db()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM blocks WHERE blocker_id=%s AND blocked_id=%s RETURNING blocker_id",
                    (blocker_id, blocked_id)
                )
                removed = cur.fetchone() is not None
        if not removed:
            return _json_error("این مورد قبلاً حذف شده یا وجود ندارد.", 404)
        return jsonify({"ok": True})
    finally:
        conn.close()
