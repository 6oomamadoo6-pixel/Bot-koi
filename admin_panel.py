import os
import hmac
import secrets
import json
import urllib.request
import urllib.error
from urllib.parse import urlsplit
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
button,input{font:inherit}button{cursor:pointer}.wrap{max-width:1100px;margin:auto;padding:22px 16px 48px}.top{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:22px}.brand{display:flex;align-items:center;gap:12px}.logo{width:46px;height:46px;border-radius:15px;display:grid;place-items:center;background:linear-gradient(145deg,#f6d987,#a9791c);color:#18150b;font-size:24px;box-shadow:0 7px 25px #d9a63825}.brand h1{font-size:18px;margin:0 0 5px}.sub{font-size:12px;color:var(--muted)}.pill{border:1px solid #4d4328;color:var(--gold2);border-radius:999px;padding:8px 11px;font-size:11px;white-space:nowrap}.hero{background:linear-gradient(120deg,#2a2415,#171815 68%);border:1px solid #4c4025;border-radius:22px;padding:22px;margin-bottom:18px;position:relative;overflow:hidden}.hero:after{content:"✦";position:absolute;left:22px;top:5px;color:#e8bd551e;font-size:95px}.eyebrow{font-size:12px;color:var(--gold);margin-bottom:10px}.hero h2{font-size:22px;margin:0 0 9px;line-height:1.6}.hero p{font-size:13px;color:#c5c0b2;line-height:1.9;margin:0;max-width:620px}.stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:16px 0 22px}.stat,.card{background:#171815eF;border:1px solid var(--line);border-radius:18px}.stat{padding:16px}.stat .label{color:var(--muted);font-size:12px}.stat .num{font-size:25px;font-weight:700;color:var(--gold2);margin-top:11px;direction:ltr;text-align:right}.menu-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin:16px 0 18px}.menu-tile{display:flex;flex-direction:column;align-items:flex-start;justify-content:center;gap:7px;min-height:96px;padding:15px 13px;background:linear-gradient(145deg,#222219,#171815);color:var(--text);border:1px solid #48402b;border-radius:16px;text-align:right;white-space:normal;transition:transform .15s,border-color .15s}.menu-tile:active{transform:scale(.98)}.menu-tile:hover{border-color:var(--gold)}.menu-tile .tile-icon{font-size:23px}.menu-tile .tile-title{font-size:13px;font-weight:bold;color:var(--gold2);line-height:1.6}.menu-tile .tile-desc{font-size:10px;color:var(--muted);line-height:1.6}.backrow{display:flex;gap:8px;align-items:center;margin-bottom:14px}.backrow .btn{flex:0 0 auto}.backrow .page-title{font-size:15px;font-weight:bold;margin:0}@media(max-width:360px){.menu-grid{gap:8px}.menu-tile{padding:12px 10px;min-height:88px}.menu-tile .tile-title{font-size:12px}}.card{padding:16px;margin-bottom:14px}.cardhead{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:15px}.cardhead h3{font-size:16px;margin:0}.searchrow{display:flex;gap:8px;margin-bottom:14px}.searchrow input,.loginbox input{width:100%;min-width:0;background:#0f100e;border:1px solid #414137;color:var(--text);border-radius:12px;padding:12px;outline:none}.searchrow input:focus,.loginbox input:focus{border-color:var(--gold)}.btn{border:1px solid #80642c;border-radius:12px;background:linear-gradient(135deg,#f1cf76,#c49330);color:#171307;font-weight:bold;padding:11px 14px;white-space:nowrap}.btn.ghost{background:#22231e;color:var(--gold2);border-color:#45402f}.btn.danger{background:#351d1b;color:#ffb4ac;border-color:#6e3732}.tablewrap{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:12px;min-width:520px}th{text-align:right;color:var(--gold2);font-weight:600;background:#24231b}th,td{padding:12px 10px;border-bottom:1px solid #303129;vertical-align:middle}td{color:#e5e2d8}td small{display:block;color:var(--muted);margin-top:5px;direction:ltr;text-align:right}.empty{padding:28px;text-align:center;color:var(--muted);font-size:13px}.pager{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:14px;color:var(--muted);font-size:12px}.hidden{display:none!important}.notice{padding:12px;border-radius:12px;background:#252116;border:1px solid #5a4825;color:var(--gold2);font-size:12px;line-height:1.8;margin-bottom:12px}.error{color:#ffaaa2}.loginbox{max-width:440px;margin:10vh auto;background:var(--panel);border:1px solid #4a4028;border-radius:22px;padding:24px;box-shadow:0 25px 70px #0007}.loginbox h2{margin:0 0 8px}.loginbox p{color:var(--muted);font-size:13px;line-height:1.9;margin-bottom:20px}.loginbox label{display:block;font-size:12px;margin:12px 0 8px}.loginbox .btn{width:100%;margin-top:14px}.foot{text-align:center;color:#77766d;font-size:11px;margin-top:26px}.userbadge{display:inline-block;background:#29271e;color:var(--gold2);border-radius:7px;padding:5px 7px;direction:ltr}.reportlight{display:inline-block;width:10px;height:10px;border-radius:50%;background:#ff2929;box-shadow:0 0 8px #ff2929;vertical-align:middle;margin-left:6px;animation:reportBlink .85s infinite alternate}.reportcount{display:inline-grid;place-items:center;min-width:22px;height:22px;padding:0 6px;margin-right:6px;border-radius:999px;background:#b91c1c;color:#fff;font-size:11px;font-weight:bold}.reportcount.zero{display:none}@keyframes reportBlink{from{opacity:.25;box-shadow:0 0 2px #ff2929}to{opacity:1;box-shadow:0 0 13px #ff2929}}.toast{position:fixed;bottom:20px;right:16px;left:16px;max-width:480px;margin:auto;background:#24251f;border:1px solid #51452a;border-radius:12px;padding:14px;z-index:10;font-size:13px;box-shadow:0 8px 30px #0008}
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
  <header class="top"><div class="brand"><div class="logo">✦</div><div><h1>Golden Chat</h1><div class="sub">پنل مدیریت ربات</div></div></div><div style="display:flex;gap:8px;align-items:center"><span class="pill">● اتصال امن</span><button class="btn" type="button" data-open="adrequests">📢 درخواست‌های تبلیغات</button><button class="btn ghost" id="logoutBtn">خروج</button></div></header>
  <section id="dashboardHero" class="hero"><div class="eyebrow">GOLDEN CHAT / ADMIN</div><h2>سلام مدیر، خوش اومدی ✨</h2><p>از اینجا وضعیت ربات رو ببین، کاربران رو جست‌وجو کن و فهرست مسدودی‌ها رو مدیریت کن. اطلاعات از دیتابیس فعلی خوانده می‌شه و دیتابیس جدیدی ساخته نمی‌شه.</p></section>
  <section id="dashboardStats" class="stats"><div class="stat"><div class="label">👥 تعداد کل کاربران ربات</div><div id="usersCount" class="num">—</div></div><div class="stat"><div class="label">🔴 موارد مسدودی کاربران</div><div id="blocksCount" class="num">—</div></div><div class="stat"><div class="label">✉️ پیام‌های ناشناس</div><div id="messagesCount" class="num">—</div></div></section>
  <section id="menuGrid" class="menu-grid" aria-label="بخش‌های مدیریت"><button class="menu-tile" data-open="groups"><span class="tile-icon">📣</span><span class="tile-title">مدیریت پیام‌های گروهی</span><span class="tile-desc">ارسال به یک گروه یا همه گروه‌ها</span></button><button class="menu-tile" data-open="users"><span class="tile-icon">👥</span><span class="tile-title">مدیریت کاربران</span><span class="tile-desc">جست‌وجو و کاربران جدید</span></button><button class="menu-tile" data-open="blocks"><span class="tile-icon">🔴</span><span class="tile-title">لیست مسدودی‌ها</span><span class="tile-desc">مشاهده و رفع مسدودی</span></button><button class="menu-tile" data-open="bans"><span class="tile-icon">⛔</span><span class="tile-title">بن کاربران</span><span class="tile-desc">بن و رفع بن حساب‌ها</span></button><button class="menu-tile" data-open="tools"><span class="tile-icon">🛠️</span><span class="tile-title">ابزارهای کاربر</span><span class="tile-desc">تغییر نام، پیام و بن مستقیم</span></button><button class="menu-tile" data-open="broadcast"><span class="tile-icon">📢</span><span class="tile-title">پیام همگانی</span><span class="tile-desc">ارسال پیام به کاربران ربات</span></button><button class="menu-tile" data-open="supervisors"><span class="tile-icon">🛡️</span><span class="tile-title">مدیریت ناظران</span><span class="tile-desc">افزودن و حذف ناظر</span></button><button class="menu-tile" data-open="requests"><span class="tile-icon">📥</span><span class="tile-title">درخواست‌های ناظران</span><span class="tile-desc">بررسی و تأیید درخواست‌ها</span></button><button class="menu-tile" data-open="adrequests"><span class="tile-icon">📢</span><span class="tile-title">درخواست‌های تبلیغات</span><span class="tile-desc">مشاهده موضوع، لینک و ارتباط مستقیم با کاربر</span></button><button class="menu-tile" data-open="reports"><span class="tile-icon">🚨 <span id="reportLight" class="reportlight hidden"></span><span id="reportCount" class="reportcount zero">۰</span></span><span class="tile-title">گزارش تخلف کاربران</span><span class="tile-desc">مشاهده گزارش‌ها و اقدام مدیریتی</span></button></section>
  <section id="usersPanel" class="card hidden featurePanel"><div class="backrow"><button class="btn ghost" data-back>← بازگشت به پنل</button><h3 class="page-title">مدیریت کاربران</h3></div><div class="cardhead"><h3>کاربران ربات</h3><button id="newUsersButton" class="btn" type="button">🆕 ۰ کاربر جدید</button></div><form id="userSearch" class="searchrow"><input id="userQuery" placeholder="جست‌وجو با آیدی، یوزرنیم یا نام" autocomplete="off"><button class="btn" type="submit">جست‌وجو</button></form><div id="usersTable" class="tablewrap"><div class="empty">در حال دریافت اطلاعات…</div></div><div class="pager"><button id="prevUsers" class="btn ghost">قبلی</button><span id="userPage">صفحه ۱</span><button id="nextUsers" class="btn ghost">بعدی</button></div><div id="newUsersPanel" class="notice hidden" style="margin-top:18px"><div class="cardhead"><h3>🆕 کاربران جدید</h3><button id="closeNewUsers" class="btn ghost" type="button">بستن</button></div><p>این فهرست دو ساعت بعد از اولین مشاهده پاک می‌شود؛ کاربران از فهرست جدید خارج می‌شوند اما حسابشان حذف نمی‌شود.</p><div id="newUsersTable" class="tablewrap"></div></div></section>
  <section id="blocksPanel" class="card hidden featurePanel"><div class="backrow"><button class="btn ghost" data-back>← بازگشت به پنل</button><h3 class="page-title">لیست مسدودی‌ها</h3></div><div class="cardhead"><h3>لیست مسدودی‌ها</h3><span class="pill">مسدودسازی بین کاربران</span></div><form id="blockSearch" class="searchrow"><input id="blockQuery" placeholder="جست‌وجو با آیدی یا یوزرنیم" autocomplete="off"><button class="btn" type="submit">جست‌وجو</button></form><div class="notice">رفع مسدودی، فقط رابطهٔ مسدودسازی انتخاب‌شده را حذف می‌کند؛ حساب کاربر یا کدهای ناشناس حذف نمی‌شوند.</div><div id="blocksTable" class="tablewrap"><div class="empty">در حال دریافت اطلاعات…</div></div><div class="pager"><button id="prevBlocks" class="btn ghost">قبلی</button><span id="blockPage">صفحه ۱</span><button id="nextBlocks" class="btn ghost">بعدی</button></div></section>
  
<section id="bansPanel" class="card hidden featurePanel"><div class="backrow"><button class="btn ghost" data-back>← بازگشت به پنل</button><h3 class="page-title">بن کاربران</h3></div><div class="cardhead"><h3>مدیریت بن کاربران</h3><span class="pill">همه کاربران + وضعیت حساب</span></div><div class="notice">تمام کاربران ثبت‌شده نمایش داده می‌شوند؛ برای هر حساب وضعیت بن و دکمهٔ بن یا رفع بن در دسترس است.</div><form id="banSearch" class="searchrow"><input id="banQuery" placeholder="جست‌وجوی کاربر با آیدی، یوزرنیم یا نام" autocomplete="off"><button class="btn" type="submit">جست‌وجو</button></form><div id="bansTable" class="tablewrap"><div class="empty">در حال دریافت…</div></div><button class="btn ghost" id="refreshBans">به‌روزرسانی</button></section>
<section id="toolsPanel" class="card hidden featurePanel"><div class="backrow"><button class="btn ghost" data-back>← بازگشت به پنل</button><h3 class="page-title">ابزارهای کاربر</h3></div><div class="cardhead"><h3>مدیریت مستقیم کاربر</h3></div><div class="notice">شناسه عددی تلگرام کاربر را وارد کن. تغییر نام فقط نام نمایشی ذخیره‌شده در ربات را تغییر می‌دهد.</div>
<form id="renameForm" class="searchrow"><input id="renameId" required placeholder="آیدی عددی کاربر"><input id="renameName" required placeholder="نام نمایشی جدید"><button class="btn" type="submit">تغییر نام</button></form>
<form id="dmForm" class="searchrow" style="flex-wrap:wrap"><input id="dmId" required placeholder="آیدی عددی کاربر"><input id="dmText" required placeholder="متن پیام مدیریت"><button class="btn" type="submit">ارسال پیام</button></form>
<form id="dmButtonForm" style="margin-top:14px;border-top:1px solid var(--line);padding-top:14px"><div class="notice">ارسال مستقیم به یک کاربر، دقیقاً با متن دلخواه و یک دکمهٔ شیشه‌ای؛ هیچ متن اضافه‌ای از طرف مدیریت به پیام اضافه نمی‌شود.</div><div class="searchrow" style="flex-wrap:wrap"><input id="dmButtonId" inputmode="numeric" required placeholder="آیدی عددی کاربر"><input id="dmButtonText" required maxlength="4000" placeholder="متن دقیق پیام"></div><div class="searchrow" style="flex-wrap:wrap"><input id="dmInlineLabel" required maxlength="40" placeholder="متن دکمهٔ شیشه‌ای"><input id="dmInlineUrl" type="url" required placeholder="لینک دکمه (https://…)"></div><button class="btn" type="submit">ارسال بدون متن اضافه + دکمه 🔘</button></form><div id="dmButtonResult" class="notice hidden" style="margin-top:12px"></div>
<form id="banForm" class="searchrow" style="flex-wrap:wrap"><input id="banId" required placeholder="آیدی عددی کاربر"><input id="banDays" type="number" min="1" max="3650" value="1" required placeholder="مدت به روز"><input id="banReason" required placeholder="دلیل بن"><button class="btn danger" type="submit">بن کاربر</button></form></section>
<section id="broadcastPanel" class="card hidden featurePanel"><div class="backrow"><button class="btn ghost" data-back>← بازگشت به پنل</button><h3 class="page-title">پیام همگانی</h3></div><div class="cardhead"><h3>ارسال پیام همگانی</h3><span class="pill">ارسال به کاربران ربات</span></div><div class="notice">پیام برای همه کاربران ثبت‌شده ارسال می‌شود. این عملیات قابل برگشت نیست؛ متن را پیش از ارسال بررسی کن.</div><form id="broadcastForm"><textarea id="broadcastText" required rows="5" maxlength="4000" placeholder="متن پیام همگانی…" style="width:100%;background:#0f100e;border:1px solid #414137;color:var(--text);border-radius:12px;padding:12px;resize:vertical"></textarea><button class="btn" type="submit" style="margin-top:12px">ارسال برای همه</button></form><div id="broadcastResult" class="notice hidden" style="margin-top:12px"></div></section>
<section id="supervisorsPanel" class="card hidden featurePanel"><div class="backrow"><button class="btn ghost" data-back>← بازگشت به پنل</button><h3 class="page-title">مدیریت ناظران</h3></div><div class="cardhead"><h3>مدیریت ناظران</h3><span class="pill">فقط مدیر اصلی مجاز است</span></div><form id="addSupervisorForm" class="searchrow"><input id="supervisorId" required placeholder="آیدی عددی ناظر جدید"><button class="btn" type="submit">افزودن ناظر</button></form><div id="supervisorsTable" class="tablewrap"><div class="empty">در حال دریافت…</div></div></section>
<section id="requestsPanel" class="card hidden featurePanel"><div class="backrow"><button class="btn ghost" data-back>← بازگشت به پنل</button><h3 class="page-title">درخواست‌های ناظران</h3></div><div class="cardhead"><h3>درخواست‌های ناظران</h3><button class="btn ghost" id="refreshRequests">به‌روزرسانی</button></div><div class="notice">درخواست‌های رفع بن و پیام همگانی که ناظران برای تأیید مدیر اصلی ثبت کرده‌اند.</div><div id="requestsTable" class="tablewrap"><div class="empty">در حال دریافت…</div></div></section>
<section id="adrequestsPanel" class="card hidden featurePanel"><div class="backrow"><button class="btn ghost" data-back>← بازگشت به پنل</button><h3 class="page-title">درخواست‌های تبلیغات</h3></div><div class="cardhead"><h3>📢 درخواست‌های تبلیغات کاربران</h3><button class="btn ghost" id="refreshAdRequests">به‌روزرسانی</button></div><div class="notice">موضوع و لینک تبلیغ همراه با شناسه کاربر نمایش داده می‌شود. برای پیگیری، از لینک مراجعه مستقیم به گفت‌وگوی کاربر استفاده کن.</div><div id="adRequestsTable" class="tablewrap"><div class="empty">در حال دریافت درخواست‌ها…</div></div></section>
<section id="groupsPanel" class="card hidden featurePanel"><div class="backrow"><button class="btn ghost" data-back>← بازگشت به پنل</button><h3 class="page-title">مدیریت پیام‌های گروهی</h3></div><div class="cardhead"><h3>ارسال پیام به گروه‌ها 📣</h3><button class="btn ghost" id="refreshGroups" type="button">به‌روزرسانی فهرست</button></div><div class="notice">این بخش پیام متنی را مستقیماً از طریق ربات ارسال می‌کند و روی زمان‌بندی تبلیغات خودکار گروه‌ها اثری ندارد. ربات باید از قبل عضو گروه باشد و اجازهٔ ارسال پیام داشته باشد.</div><div class="searchrow" style="flex-wrap:wrap"><select id="groupTarget" style="width:100%;min-width:0;background:#0f100e;border:1px solid #414137;color:var(--text);border-radius:12px;padding:12px"><option value="all">همه گروه‌های ثبت‌شده</option></select></div><div id="groupsList" class="notice">در حال دریافت فهرست گروه‌ها…</div><form id="groupBroadcastForm"><textarea id="groupBroadcastText" required rows="5" maxlength="4000" placeholder="متن پیام گروهی را بنویس…" style="width:100%;background:#0f100e;border:1px solid #414137;color:var(--text);border-radius:12px;padding:12px;resize:vertical;margin-bottom:10px"></textarea><div class="searchrow" style="flex-wrap:wrap"><input id="groupButtonText" maxlength="40" placeholder="متن دکمهٔ شیشه‌ای (اختیاری)"><input id="groupButtonUrl" type="url" placeholder="لینک دکمه (اختیاری؛ https://…)"></div><button class="btn" type="submit">ارسال پیام 📤</button></form><div id="groupBroadcastResult" class="notice hidden" style="margin-top:12px"></div></section><section id="reportsPanel" class="card hidden featurePanel"><div class="backrow"><button class="btn ghost" data-back>← بازگشت به پنل</button><h3 class="page-title">گزارش تخلف کاربران</h3></div><div class="cardhead"><h3>🚨 گزارش تخلف کاربران</h3><div style="display:flex;align-items:center;gap:8px"><span id="reportsUnreadPill" class="pill">خوانده‌نشده: ۰</span><button class="btn ghost" id="refreshReports">به‌روزرسانی</button></div></div><div class="notice">با باز شدن این بخش، گزارش‌های نمایش‌داده‌شده خودکار خوانده‌شده می‌شوند. از همین‌جا می‌توانی کاربر گزارش‌شده را هم بن کنی.</div><div id="reportsTable" class="tablewrap"><div class="empty">در حال دریافت گزارش‌ها…</div></div></section><div class="foot">Golden Chat • پنل خصوصی مدیریت</div>
</div>
<div id="toast" class="toast hidden"></div>
<script>
var csrfToken="", userPage=1, blockPage=1, userQuery="", blockQuery="", banQuery="", activeTab="users";
function el(id){return document.getElementById(id)}
function esc(value){return String(value==null?"":value).replace(/[&<>"']/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]})}
function toast(message){el("toast").textContent=message;el("toast").classList.remove("hidden");setTimeout(function(){el("toast").classList.add("hidden")},3000)}
async function api(path,options){options=options||{};options.credentials="same-origin";options.headers=Object.assign({"Content-Type":"application/json","X-CSRF-Token":csrfToken},options.headers||{});var response=await fetch("/admin/api/"+path,options);var data=await response.json().catch(function(){return {error:"پاسخ نامعتبر از سرور"}});if(response.status===401){showLogin();throw new Error(data.error||"ابتدا وارد شوید")}if(!response.ok)throw new Error(data.error||"خطا در ارتباط با سرور");return data}
function showLogin(){el("appView").classList.add("hidden");el("loginView").classList.remove("hidden")}
function showApp(){el("loginView").classList.add("hidden");el("appView").classList.remove("hidden")}
async function init(){try{var s=await fetch("/admin/api/session",{credentials:"same-origin"});var d=await s.json();csrfToken=d.csrf_token||"";if(d.authenticated){showApp();await loadAll()}else showLogin()}catch(e){showLogin()}}
el("loginForm").addEventListener("submit",async function(e){e.preventDefault();el("loginError").textContent="";try{var d=await api("login",{method:"POST",body:JSON.stringify({password:el("password").value})});csrfToken=d.csrf_token||csrfToken;el("password").value="";showApp();await loadAll()}catch(err){el("loginError").textContent=err.message}})
el("logoutBtn").addEventListener("click",async function(){try{await api("logout",{method:"POST",body:"{}"})}catch(e){}showLogin();toast("از پنل خارج شدی")})
function openSection(key){activeTab=key;el("menuGrid").classList.add("hidden");el("dashboardHero").classList.add("hidden");el("dashboardStats").classList.add("hidden");["users","blocks","bans","tools","broadcast","supervisors","requests","adrequests","reports","groups"].forEach(function(k){var p=el(k+"Panel");if(p)p.classList.toggle("hidden",k!==key)});if(key==="blocks")loadBlocks();if(key==="bans")loadBans();if(key==="supervisors")loadSupervisors();if(key==="requests")loadRequests();if(key==="adrequests")loadAdRequests();if(key==="reports")loadReports();if(key==="groups")loadGroups();window.scrollTo({top:0,behavior:"smooth"})}function showMenu(){["users","blocks","bans","tools","broadcast","supervisors","requests","adrequests","reports","groups"].forEach(function(k){var p=el(k+"Panel");if(p)p.classList.add("hidden")});el("dashboardHero").classList.remove("hidden");el("dashboardStats").classList.remove("hidden");el("menuGrid").classList.remove("hidden");activeTab="";window.scrollTo({top:0,behavior:"smooth"})}document.querySelectorAll("[data-open]").forEach(function(button){button.addEventListener("click",function(){openSection(button.dataset.open)})});document.querySelectorAll("[data-back]").forEach(function(button){button.addEventListener("click",showMenu)})
async function loadAll(){await Promise.all([loadStats(),loadUsers(),loadBlocks(),loadReportCount(),loadNewUserCount()])}
async function loadNewUserCount(){try{var d=await api("new-users/count");el("newUsersButton").textContent="🆕 "+Number(d.count||0).toLocaleString("fa-IR")+" کاربر جدید";}catch(e){}}
async function openNewUsers(){el("newUsersPanel").classList.remove("hidden");el("newUsersTable").innerHTML='<div class="empty">در حال دریافت کاربران جدید…</div>';try{var d=await api("new-users");el("newUsersTable").innerHTML=d.items.length?'<table><thead><tr><th>کاربر</th><th>شناسه</th><th>تاریخ ورود</th></tr></thead><tbody>'+d.items.map(function(u){return '<tr><td>'+esc(u.display_name||u.full_name||"بدون نام")+(u.username?'<small>@'+esc(u.username)+'</small>':'')+'</td><td><span class="userbadge">'+esc(u.user_id)+'</span></td><td>'+esc(u.created_at||"—")+'</td></tr>'}).join("")+'</tbody></table>':'<div class="empty">کاربر جدیدی برای نمایش نیست.</div>';await loadNewUserCount();}catch(e){el("newUsersTable").innerHTML='<div class="empty error">'+esc(e.message)+'</div>'}}
el("newUsersButton").addEventListener("click",openNewUsers);
el("closeNewUsers").addEventListener("click",function(){el("newUsersPanel").classList.add("hidden")});
async function loadStats(){try{var d=await api("stats");el("usersCount").textContent=Number(d.users||0).toLocaleString("fa-IR");el("blocksCount").textContent=Number(d.blocks||0).toLocaleString("fa-IR");el("messagesCount").textContent=Number(d.messages||0).toLocaleString("fa-IR")}catch(e){toast(e.message)}}
async function loadUsers(){el("usersTable").innerHTML='<div class="empty">در حال دریافت اطلاعات…</div>';try{var d=await api("users?page="+userPage+"&q="+encodeURIComponent(userQuery));if(userPage>d.pages&&userPage>1){userPage=d.pages;return loadUsers()}el("usersTable").innerHTML= d.items.length?'<table><thead><tr><th>کاربر</th><th>شناسه</th><th>عضویت</th><th>عملیات</th></tr></thead><tbody>'+d.items.map(function(u){return '<tr><td>'+esc(u.display_name||u.full_name||"بدون نام")+(u.username?'<small>@'+esc(u.username)+'</small>':'')+'</td><td><span class="userbadge">'+esc(u.user_id)+'</span></td><td>'+esc(u.created_at||"—")+'</td><td><button class="btn danger" type="button" data-delete-user="'+esc(u.user_id)+'">🗑️ حذف کاربر</button></td></tr>'}).join("")+'</tbody></table>':'<div class="empty">کاربری پیدا نشد.</div>';el("userPage").textContent="صفحه "+userPage+" از "+Math.max(1,d.pages);el("prevUsers").disabled=userPage<=1;el("nextUsers").disabled=userPage>=d.pages;document.querySelectorAll("[data-delete-user]").forEach(function(btn){btn.addEventListener("click",async function(){var id=btn.dataset.deleteUser;if(!confirm("کاربر با شناسه "+id+" از فهرست کاربران ربات حذف شود؟ رکورد حساب حذف می‌شود؛ پیام‌های ناشناس و روابط مسدودی نگه داشته می‌شوند. اگر کاربر دوباره با ربات تعامل کند ممکن است دوباره ثبت شود."))return;btn.disabled=true;try{await api("users/delete",{method:"POST",body:JSON.stringify({user_id:id})});toast("کاربر از فهرست حذف شد");await Promise.all([loadUsers(),loadStats(),loadNewUserCount()])}catch(e){toast(e.message);btn.disabled=false}})})}catch(e){el("usersTable").innerHTML='<div class="empty error">'+esc(e.message)+'</div>'}}
async function loadBlocks(){el("blocksTable").innerHTML='<div class="empty">در حال دریافت اطلاعات…</div>';try{var d=await api("blocks?page="+blockPage+"&q="+encodeURIComponent(blockQuery));el("blocksTable").innerHTML=d.items.length?'<table><thead><tr><th>مسدودکننده</th><th>کاربر مسدودشده</th><th>تاریخ</th><th>عملیات</th></tr></thead><tbody>'+d.items.map(function(b){return '<tr><td>'+esc(b.blocker_name||"بدون نام")+'<small>'+esc(b.blocker_id)+'</small></td><td>'+esc(b.blocked_name||"بدون نام")+'<small>'+esc(b.blocked_id)+'</small></td><td>'+esc(b.created_at||"—")+'</td><td><button class="btn danger" data-unblock="'+esc(b.blocker_id)+'" data-blocked="'+esc(b.blocked_id)+'">رفع مسدودی</button></td></tr>'}).join("")+'</tbody></table>':'<div class="empty">موردی پیدا نشد.</div>';el("blockPage").textContent="صفحه "+blockPage+" از "+Math.max(1,d.pages);el("prevBlocks").disabled=blockPage<=1;el("nextBlocks").disabled=blockPage>=d.pages;document.querySelectorAll("[data-unblock]").forEach(function(btn){btn.addEventListener("click",async function(){if(!confirm("فقط این رابطهٔ مسدودی حذف شود؟"))return;try{await api("blocks/unblock",{method:"POST",body:JSON.stringify({blocker_id:btn.dataset.unblock,blocked_id:btn.dataset.blocked})});toast("مسدودی رفع شد");await Promise.all([loadBlocks(),loadStats()])}catch(e){toast(e.message)}})})}catch(e){el("blocksTable").innerHTML='<div class="empty error">'+esc(e.message)+'</div>'}}
el("userSearch").addEventListener("submit",function(e){e.preventDefault();userQuery=el("userQuery").value.trim();userPage=1;loadUsers()});el("blockSearch").addEventListener("submit",function(e){e.preventDefault();blockQuery=el("blockQuery").value.trim();blockPage=1;loadBlocks()});el("prevUsers").addEventListener("click",function(){if(userPage>1){userPage--;loadUsers()}});el("nextUsers").addEventListener("click",function(){userPage++;loadUsers()});el("prevBlocks").addEventListener("click",function(){if(blockPage>1){blockPage--;loadBlocks()}});el("nextBlocks").addEventListener("click",function(){blockPage++;loadBlocks()});

async function loadBans(){el("bansTable").innerHTML='<div class="empty">در حال دریافت فهرست همه کاربران…</div>';try{var d=await api("bans");var q=banQuery.trim().toLocaleLowerCase();var items=d.items.filter(function(b){return !q||[b.user_id,b.username,b.full_name,b.display_name].some(function(v){return String(v==null?"":v).toLocaleLowerCase().indexOf(q)!==-1})});el("bansTable").innerHTML=items.length?'<table><thead><tr><th>کاربر</th><th>شناسه</th><th>وضعیت حساب</th><th>پایان بن</th><th>دلیل</th><th>عملیات</th></tr></thead><tbody>'+items.map(function(b){return '<tr><td>'+esc(b.display_name||b.full_name||b.username||"بدون نام")+(b.username?'<small>@'+esc(b.username)+'</small>':'')+'</td><td><span class="userbadge">'+esc(b.user_id)+'</span></td><td>'+(b.is_banned?'<span style="color:#ff8f87;font-weight:bold">⛔ بن است</span>':'<span style="color:#8bd3a6;font-weight:bold">✅ بن نیست</span>')+'</td><td>'+esc(b.ban_until||"—")+'</td><td>'+esc(b.reason||"—")+'</td><td>'+(b.is_banned?'<button class="btn" data-unban="'+esc(b.user_id)+'">رفع بن</button>':'<button class="btn danger" data-ban="'+esc(b.user_id)+'">بن کاربر</button>')+'</td></tr>'}).join("")+'</tbody></table>':'<div class="empty">'+(q?'کاربری با این عبارت پیدا نشد.':'هنوز کاربری در دیتابیس ثبت نشده است.')+'</div>';document.querySelectorAll("[data-unban]").forEach(function(b){b.addEventListener("click",async function(){if(!confirm("بن این کاربر برداشته شود؟"))return;try{await api("bans/unban",{method:"POST",body:JSON.stringify({user_id:b.dataset.unban})});toast("بن کاربر برداشته شد");await loadBans()}catch(e){toast(e.message)}})});document.querySelectorAll("[data-ban]").forEach(function(b){b.addEventListener("click",async function(){var days=prompt("مدت بن به روز (مثلاً 1):","1");if(days===null)return;if(!/^\d+$/.test(days)||Number(days)<1||Number(days)>3650){toast("مدت باید عددی بین ۱ تا ۳۶۵۰ روز باشد");return}var reason=prompt("دلیل بن:","تخلف از قوانین");if(reason===null)return;if(!reason.trim()){toast("دلیل بن را وارد کن");return}if(!confirm("این کاربر برای "+days+" روز بن شود؟"))return;try{await api("bans/ban",{method:"POST",body:JSON.stringify({user_id:b.dataset.ban,days:Number(days),reason:reason.trim()})});toast("کاربر با موفقیت بن شد");await loadBans()}catch(e){toast(e.message)}})})}catch(e){el("bansTable").innerHTML='<div class="empty error">'+esc(e.message)+'</div>'}}
async function loadSupervisors(){el("supervisorsTable").innerHTML='<div class="empty">در حال دریافت…</div>';try{var d=await api("supervisors");el("supervisorsTable").innerHTML=d.items.length?'<table><thead><tr><th>شناسه</th><th>نام کاربری</th><th>افزوده‌شده</th><th>عملیات</th></tr></thead><tbody>'+d.items.map(function(x){return '<tr><td>'+esc(x.user_id)+'</td><td>'+esc(x.username||x.full_name||"—")+'</td><td>'+esc(x.added_at||"—")+'</td><td><button class="btn danger" data-rmsup="'+esc(x.user_id)+'">حذف ناظر</button></td></tr>'}).join("")+'</tbody></table>':'<div class="empty">هنوز ناظری ثبت نشده است.</div>';document.querySelectorAll("[data-rmsup]").forEach(function(b){b.addEventListener("click",async function(){if(!confirm("این ناظر حذف شود؟"))return;try{await api("supervisors/remove",{method:"POST",body:JSON.stringify({user_id:b.dataset.rmsup})});toast("ناظر حذف شد");loadSupervisors()}catch(e){toast(e.message)}})})}catch(e){el("supervisorsTable").innerHTML='<div class="empty error">'+esc(e.message)+'</div>'}}
el("refreshBans").addEventListener("click",loadBans);el("banSearch").addEventListener("submit",function(e){e.preventDefault();banQuery=el("banQuery").value;loadBans()});
el("renameForm").addEventListener("submit",async function(e){e.preventDefault();try{await api("users/rename",{method:"POST",body:JSON.stringify({user_id:el("renameId").value,display_name:el("renameName").value})});toast("نام نمایشی تغییر کرد");loadUsers()}catch(x){toast(x.message)}});
el("dmForm").addEventListener("submit",async function(e){e.preventDefault();if(!confirm("پیام از طرف مدیریت ارسال شود؟"))return;try{await api("users/message",{method:"POST",body:JSON.stringify({user_id:el("dmId").value,text:el("dmText").value})});toast("پیام ارسال شد");el("dmText").value=""}catch(x){toast(x.message)}});
el("dmButtonForm").addEventListener("submit",async function(e){e.preventDefault();var userId=el("dmButtonId").value.trim(),message=el("dmButtonText").value,buttonText=el("dmInlineLabel").value.trim(),buttonUrl=el("dmInlineUrl").value.trim();if(!/^\d+$/.test(userId)||Number(userId)<=0)return toast("آیدی عددی کاربر معتبر نیست");if(!buttonUrl.toLowerCase().startsWith("https://"))return toast("لینک دکمه باید با https:// شروع شود");if(!confirm("پیام دقیقاً بدون متن اضافه و با دکمهٔ شیشه‌ای برای این کاربر ارسال شود؟"))return;var out=el("dmButtonResult");out.classList.remove("hidden");out.textContent="در حال ارسال…";try{await api("users/message-inline",{method:"POST",body:JSON.stringify({user_id:userId,text:message,button_text:buttonText,button_url:buttonUrl})});out.textContent="پیام با دکمهٔ شیشه‌ای ارسال شد.";toast("ارسال شد");el("dmButtonText").value="";el("dmInlineLabel").value="";el("dmInlineUrl").value=""}catch(x){out.textContent=x.message;toast(x.message)}});
el("banForm").addEventListener("submit",async function(e){e.preventDefault();if(!confirm("کاربر برای مدت تعیین‌شده بن شود؟"))return;try{await api("bans/ban",{method:"POST",body:JSON.stringify({user_id:el("banId").value,days:el("banDays").value,reason:el("banReason").value})});toast("بن ثبت شد");loadBans()}catch(x){toast(x.message)}});
el("broadcastForm").addEventListener("submit",async function(e){e.preventDefault();if(!confirm("پیام برای همه کاربران ارسال شود؟ این عملیات قابل برگشت نیست."))return;var out=el("broadcastResult");out.classList.remove("hidden");out.textContent="در حال ارسال…";try{var d=await api("broadcast",{method:"POST",body:JSON.stringify({text:el("broadcastText").value})});out.textContent="ارسال تمام شد؛ موفق: "+d.sent+"، ناموفق: "+d.failed;toast("ارسال همگانی تمام شد")}catch(x){out.textContent=x.message;toast(x.message)}});
el("addSupervisorForm").addEventListener("submit",async function(e){e.preventDefault();try{await api("supervisors/add",{method:"POST",body:JSON.stringify({user_id:el("supervisorId").value})});el("supervisorId").value="";toast("ناظر اضافه شد");loadSupervisors()}catch(x){toast(x.message)}});


async function loadRequests(){el("requestsTable").innerHTML='<div class="empty">در حال دریافت…</div>';try{var d=await api("requests");el("requestsTable").innerHTML=d.items.length?'<table><thead><tr><th>نوع</th><th>ناظر</th><th>جزئیات</th><th>زمان</th><th>عملیات</th></tr></thead><tbody>'+d.items.map(function(x){return '<tr><td>'+esc(x.kind==="unban"?"درخواست رفع بن":"درخواست پیام همگانی")+'</td><td>'+esc(x.supervisor_id)+'</td><td style="white-space:pre-wrap">'+esc(x.details)+'</td><td>'+esc(x.created_at||"—")+'</td><td><button class="btn" data-req="approve" data-kind="'+esc(x.kind)+'" data-id="'+esc(x.id)+'">تأیید</button> <button class="btn danger" data-req="reject" data-kind="'+esc(x.kind)+'" data-id="'+esc(x.id)+'">رد</button></td></tr>'}).join("")+'</tbody></table>':'<div class="empty">درخواست معلقی وجود ندارد.</div>';document.querySelectorAll("[data-req]").forEach(function(b){b.addEventListener("click",async function(){var verb=b.dataset.req==="approve"?"تأیید":"رد";if(!confirm("درخواست "+verb+" شود؟"))return;try{await api("requests/decision",{method:"POST",body:JSON.stringify({id:b.dataset.id,kind:b.dataset.kind,decision:b.dataset.req})});toast("درخواست بررسی شد");loadRequests();loadBans()}catch(e){toast(e.message)}})})}catch(e){el("requestsTable").innerHTML='<div class="empty error">'+esc(e.message)+'</div>'}}
el("refreshRequests").addEventListener("click",loadRequests);

async function loadAdRequests(){
  el("adRequestsTable").innerHTML='<div class="empty">در حال دریافت درخواست‌های تبلیغات…</div>';
  try{
    var d=await api("ad-requests");
    el("adRequestsTable").innerHTML=d.items.length?'<table><thead><tr><th>کاربر</th><th>شناسه</th><th>موضوع تبلیغ</th><th>لینک تبلیغ</th><th>زمان ثبت</th><th>وضعیت</th><th>عملیات</th></tr></thead><tbody>'+
      d.items.map(function(x){
        var direct=x.username?("https://t.me/"+encodeURIComponent(x.username)):( "tg://user?id="+encodeURIComponent(x.user_id));
        return '<tr><td>'+esc(x.full_name||x.username||"کاربر")+(x.username?'<small>@'+esc(x.username)+'</small>':'')+'</td><td><span class="userbadge">'+esc(x.user_id)+'</span></td><td style="white-space:pre-wrap;min-width:180px">'+esc(x.subject)+'</td><td style="min-width:160px;max-width:260px;overflow-wrap:anywhere"><a href="'+esc(x.ad_link)+'" target="_blank" rel="noopener noreferrer" style="color:var(--gold2)">باز کردن لینک ↗</a><small>'+esc(x.ad_link)+'</small></td><td>'+esc(x.created_at||"—")+'</td><td>'+esc(x.status==="contacted"?"پیگیری شده":x.status==="rejected"?"رد شده":"در انتظار")+'</td><td><a class="btn" href="'+esc(direct)+'" target="_blank" rel="noopener noreferrer" style="display:inline-block;text-decoration:none">پیوی کاربر ↗</a> '+(x.status==="pending"?'<button class="btn ghost" data-adstatus="contacted" data-adid="'+esc(x.id)+'">پیگیری شد</button> <button class="btn danger" data-adstatus="rejected" data-adid="'+esc(x.id)+'">رد</button>':'')+'</td></tr>';
      }).join("")+'</tbody></table>':'<div class="empty">هنوز درخواست تبلیغاتی ثبت نشده است.</div>';
    document.querySelectorAll("[data-adstatus]").forEach(function(b){b.addEventListener("click",async function(){try{await api("ad-requests/status",{method:"POST",body:JSON.stringify({id:b.dataset.adid,status:b.dataset.adstatus})});toast("وضعیت درخواست به‌روزرسانی شد");await loadAdRequests()}catch(e){toast(e.message)}})});
  }catch(e){el("adRequestsTable").innerHTML='<div class="empty error">'+esc(e.message)+'</div>'}
}
el("refreshAdRequests").addEventListener("click",loadAdRequests);

async function loadReportCount(){try{var d=await api("reports/unread-count");var n=Number(d.unread||0);el("reportCount").textContent=n.toLocaleString("fa-IR");el("reportsUnreadPill").textContent="خوانده‌نشده: "+n.toLocaleString("fa-IR");el("reportCount").classList.toggle("zero",n===0);el("reportLight").classList.toggle("hidden",n===0)}catch(e){}}
async function loadReports(){el("reportsTable").innerHTML='<div class="empty">در حال دریافت گزارش‌ها…</div>';try{var d=await api("reports");await loadReportCount();el("reportsTable").innerHTML=d.items.length?'<table><thead><tr><th>وضعیت</th><th>گزارش‌دهنده</th><th>کاربر گزارش‌شده</th><th>متن پیام</th><th>گروه</th><th>زمان</th><th>عملیات</th></tr></thead><tbody>'+d.items.map(function(r){return '<tr><td><span class="pill">خوانده‌شده</span></td><td>'+esc(r.reporter_name||"کاربر")+'<small>'+esc(r.reporter_id)+'</small></td><td>'+esc(r.reported_name||"کاربر")+'<small>'+esc(r.reported_username?"@"+r.reported_username:"بدون یوزرنیم")+' · '+esc(r.reported_user_id)+'</small></td><td style="white-space:pre-wrap;min-width:220px;max-width:360px">'+esc(r.message_text||"—")+'</td><td>'+esc(r.group_title||"پیام خصوصی")+(r.group_id?'<small>'+esc(r.group_id)+'</small>':'')+'</td><td>'+esc(r.created_at||"—")+'</td><td><button class="btn danger" data-reportban="'+esc(r.reported_user_id)+'" data-reportname="'+esc(r.reported_name||r.reported_username||r.reported_user_id)+'">بن کاربر</button></td></tr>'}).join("")+'</tbody></table>':'<div class="empty">هنوز گزارشی ثبت نشده است.</div>';document.querySelectorAll("[data-reportban]").forEach(function(b){b.addEventListener("click",async function(){var days=prompt("مدت بن به روز (مثلاً 1):","1");if(days===null)return;if(!/^\d+$/.test(days)||Number(days)<1||Number(days)>3650){toast("مدت باید عددی بین ۱ تا ۳۶۵۰ روز باشد");return}var reason=prompt("دلیل بن "+b.dataset.reportname+":","گزارش تخلف");if(reason===null)return;if(!reason.trim())return toast("دلیل بن را وارد کن");if(!confirm("کاربر "+b.dataset.reportname+" برای "+days+" روز بن شود؟"))return;try{await api("bans/ban",{method:"POST",body:JSON.stringify({user_id:b.dataset.reportban,days:Number(days),reason:reason.trim()})});toast("کاربر گزارش‌شده بن شد");await Promise.all([loadReports(),loadReportCount(),loadBans(),loadStats()])}catch(e){toast(e.message)}})})}catch(e){el("reportsTable").innerHTML='<div class="empty error">'+esc(e.message)+'</div>'}}
el("refreshReports").addEventListener("click",loadReports);
async function loadGroups(){var list=el("groupsList"),select=el("groupTarget");list.textContent="در حال دریافت فهرست گروه‌ها…";try{var d=await api("groups");var old=select.value;select.innerHTML='<option value="all">همه گروه‌های ثبت‌شده ('+Number(d.total||0).toLocaleString("fa-IR")+' گروه)</option>'+d.items.map(function(g){return '<option value="'+esc(g.chat_id)+'">'+esc(g.title||"گروه بدون نام")+' · '+esc(g.chat_id)+'</option>'}).join("");if(Array.from(select.options).some(function(o){return o.value===old}))select.value=old;list.textContent=d.items.length?"گروه‌های ثبت‌شده: "+d.items.map(function(g){return (g.title||"گروه بدون نام")+" ("+g.chat_id+")"}).join("، "):"هنوز گروهی در دیتابیس ثبت نشده است. برای ثبت گروه، ربات را به گروه اضافه کنید و مطمئن شوید پیام عضویت/فعالیت گروه توسط ربات دریافت می‌شود."}catch(e){list.textContent=e.message}}
el("refreshGroups").addEventListener("click",loadGroups);
el("groupBroadcastForm").addEventListener("submit",async function(e){e.preventDefault();var target=el("groupTarget").value,textValue=el("groupBroadcastText").value.trim(),buttonText=el("groupButtonText").value.trim(),buttonUrl=el("groupButtonUrl").value.trim();if(!textValue)return toast("متن پیام را وارد کن");if(Boolean(buttonText)!==Boolean(buttonUrl))return toast("برای دکمه، هم متن و هم لینک را وارد کن");if(buttonUrl&&!buttonUrl.toLowerCase().startsWith("https://"))return toast("لینک دکمه باید با https:// شروع شود");if(!confirm(target==="all"?"پیام برای همه گروه‌های ثبت‌شده ارسال شود؟":"پیام برای گروه انتخاب‌شده ارسال شود؟"))return;var out=el("groupBroadcastResult");out.classList.remove("hidden");out.textContent="در حال ارسال پیام…";try{var d=await api("groups/broadcast",{method:"POST",body:JSON.stringify({target:target,text:textValue,button_text:buttonText,button_url:buttonUrl})});out.textContent="ارسال تمام شد؛ موفق: "+Number(d.sent||0).toLocaleString("fa-IR")+"، ناموفق: "+Number(d.failed||0).toLocaleString("fa-IR")+(d.errors&&d.errors.length?"\nجزئیات: "+d.errors.join(" | "):"");toast("ارسال گروهی تمام شد")}catch(x){out.textContent=x.message;toast(x.message)}});

setInterval(function(){if(!el("appView").classList.contains("hidden")){loadReportCount();loadNewUserCount();if(activeTab==="reports")loadReports()}},15000);

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


@admin_panel.after_request
def prevent_admin_cache(response):
    # Ensure mobile browsers/webviews do not keep an older dashboard HTML or API response.
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


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


@admin_panel.get("/api/new-users/count")
@_auth_required
def new_user_count():
    conn = _db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM new_user_queue
                WHERE viewed_at IS NOT NULL
                  AND viewed_at <= CURRENT_TIMESTAMP - INTERVAL '2 hours'
            """)
            cur.execute("""
                SELECT COUNT(*) FROM new_user_queue
                WHERE viewed_at IS NULL
                   OR viewed_at > CURRENT_TIMESTAMP - INTERVAL '2 hours'
            """)
            count = cur.fetchone()[0]
        conn.commit()
        return jsonify({"count": count})
    finally:
        conn.close()


@admin_panel.get("/api/new-users")
@_auth_required
def new_users():
    conn = _db()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    DELETE FROM new_user_queue
                    WHERE viewed_at IS NOT NULL
                      AND viewed_at <= CURRENT_TIMESTAMP - INTERVAL '2 hours'
                """)
                # Start the two-hour countdown only the first time the admin opens the list.
                cur.execute("""
                    UPDATE new_user_queue
                    SET viewed_at = CURRENT_TIMESTAMP
                    WHERE viewed_at IS NULL
                """)
                cur.execute("""
                    SELECT q.user_id, u.username, u.full_name, u.display_name, q.created_at
                    FROM new_user_queue q
                    LEFT JOIN users u ON u.user_id = q.user_id
                    WHERE q.viewed_at > CURRENT_TIMESTAMP - INTERVAL '2 hours'
                    ORDER BY q.created_at DESC
                """)
                rows = cur.fetchall()
        items = [{
            "user_id": row[0],
            "username": row[1],
            "full_name": row[2],
            "display_name": row[3],
            "created_at": row[4].strftime("%Y-%m-%d %H:%M") if row[4] else None,
        } for row in rows]
        return jsonify({"items": items, "total": len(items)})
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


# Extended admin tools matching the Telegram bot's management commands.
def _format_jalali_datetime(value):
    """Format a datetime as an Iranian/Jalali calendar date."""
    if not value:
        return "نامشخص"
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    gy, gm, gd = value.year, value.month, value.day
    g_month_days = [31, 29 if (gy % 4 == 0 and (gy % 100 != 0 or gy % 400 == 0)) else 28,
                    31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gy -= 1600
    gm -= 1
    gd -= 1
    g_day_no = 365 * gy + (gy + 3) // 4 - (gy + 99) // 100 + (gy + 399) // 400
    for month in range(gm):
        g_day_no += g_month_days[month]
    g_day_no += gd
    j_day_no = g_day_no - 79
    j_np = j_day_no // 12053
    j_day_no %= 12053
    jy = 979 + 33 * j_np + 4 * (j_day_no // 1461)
    j_day_no %= 1461
    if j_day_no >= 366:
        jy += (j_day_no - 1) // 365
        j_day_no = (j_day_no - 1) % 365
    if j_day_no < 186:
        jm = 1 + j_day_no // 31
        jd = 1 + j_day_no % 31
    else:
        jm = 7 + (j_day_no - 186) // 30
        jd = 1 + (j_day_no - 186) % 30
    return f"{jy:04d}/{jm}/{jd} {value.hour:02d}:{value.minute:02d}"


def _telegram_call(method, payload):
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN در تنظیمات هاست موجود نیست.")
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        "https://api.telegram.org/bot" + token + "/" + method,
        data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try: details = json.loads(exc.read().decode("utf-8")).get("description", "خطای تلگرام")
        except Exception: details = "خطای تلگرام"
        raise RuntimeError(details)
    if not result.get("ok"):
        raise RuntimeError(result.get("description", "خطای تلگرام"))
    return result.get("result")


@admin_panel.get("/api/groups")
@_auth_required
def list_groups():
    conn = _db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT chat_id, title, created_at FROM group_chats ORDER BY created_at ASC")
            rows = cur.fetchall()
        return jsonify({
            "items": [
                {"chat_id": row[0], "title": row[1], "created_at": row[2].strftime("%Y-%m-%d") if row[2] else None}
                for row in rows
            ],
            "total": len(rows),
        })
    finally:
        conn.close()


@admin_panel.post("/api/groups/broadcast")
@_auth_required
@_csrf_required
def broadcast_groups():
    payload = request.get_json(silent=True) or {}
    target = str(payload.get("target", "all")).strip()
    message = str(payload.get("text", "")).strip()
    button_text = str(payload.get("button_text", "")).strip()[:40]
    button_url = str(payload.get("button_url", "")).strip()[:1000]
    if not message:
        return _json_error("متن پیام را وارد کن.", 400)
    if len(message) > 4000:
        return _json_error("متن پیام نباید بیشتر از ۴۰۰۰ کاراکتر باشد.", 400)
    if bool(button_text) != bool(button_url):
        return _json_error("برای دکمه، هم متن و هم لینک را وارد کن.", 400)
    if button_url:
        parsed = urlsplit(button_url)
        if parsed.scheme != "https" or not parsed.netloc:
            return _json_error("لینک دکمه باید یک آدرس معتبر HTTPS باشد.", 400)

    conn = _db()
    try:
        with conn.cursor() as cur:
            if target == "all":
                cur.execute("SELECT chat_id, title FROM group_chats ORDER BY created_at ASC")
                groups = cur.fetchall()
            else:
                try:
                    target_id = int(target)
                except (TypeError, ValueError):
                    return _json_error("گروه انتخاب‌شده معتبر نیست.", 400)
                cur.execute("SELECT chat_id, title FROM group_chats WHERE chat_id = %s", (target_id,))
                groups = cur.fetchall()
    finally:
        conn.close()

    if not groups:
        return _json_error("گروهی برای ارسال پیدا نشد؛ ابتدا ربات را به گروه اضافه کن.", 404)

    reply_markup = None
    if button_text and button_url:
        reply_markup = {"inline_keyboard": [[{"text": button_text, "url": button_url}]]}
    sent = 0
    errors = []
    for chat_id, title in groups:
        try:
            api_payload = {"chat_id": chat_id, "text": message}
            if reply_markup:
                api_payload["reply_markup"] = reply_markup
            _telegram_call("sendMessage", api_payload)
            sent += 1
        except Exception as exc:
            if len(errors) < 8:
                errors.append((title or str(chat_id)) + ": " + str(exc)[:180])
    return jsonify({"sent": sent, "failed": len(groups) - sent, "errors": errors})


@admin_panel.get("/api/bans")
@_auth_required
def list_bans():
    conn = _db()
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT user_id, username, full_name, display_name, ban_until, ban_reason,
                (ban_until IS NOT NULL AND ban_until > CURRENT_TIMESTAMP) AS is_banned
                FROM users ORDER BY created_at DESC NULLS LAST, user_id DESC""")
            rows = cur.fetchall()
        return jsonify({"items":[{"user_id":r[0],"username":r[1],"full_name":r[2],"display_name":r[3],
            "ban_until":r[4].strftime("%Y-%m-%d %H:%M") if r[4] else None,"reason":r[5],"is_banned":bool(r[6])} for r in rows]})
    finally:
        conn.close()


@admin_panel.post("/api/bans/unban")
@_auth_required
@_csrf_required
def unban_user():
    payload = request.get_json(silent=True) or {}
    try:
        user_id = int(payload.get("user_id"))
    except (TypeError, ValueError):
        return _json_error("شناسه کاربر معتبر نیست.", 400)
    conn = _db()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE users SET ban_until=NULL, ban_reason=NULL
                    WHERE user_id=%s AND ban_until IS NOT NULL
                    RETURNING user_id
                """, (user_id,))
                row = cur.fetchone()
        if not row:
            return _json_error("بن فعالی برای این کاربر پیدا نشد.", 404)
        try:
            _telegram_call("sendMessage", {
                "chat_id": user_id,
                "text": "🟢 مسدودی حساب کاربری شما توسط مدیریت گلدن چت رفع شد.\n\nاکنون می‌توانید از قابلیت‌های ربات استفاده کنید. برای شروع /start را بزنید."
            })
        except Exception as exc:
            return jsonify({"ok": True, "notification_sent": False,
                            "notification_error": str(exc)})
        return jsonify({"ok": True, "notification_sent": True})
    finally:
        conn.close()


@admin_panel.post("/api/bans/ban")
@_auth_required
@_csrf_required
def ban_user():
    payload = request.get_json(silent=True) or {}
    try:
        user_id = int(payload.get("user_id"))
        days = int(payload.get("days"))
        if days < 1 or days > 3650:
            raise ValueError()
    except (TypeError, ValueError):
        return _json_error("آیدی یا مدت بن معتبر نیست.", 400)
    reason = str(payload.get("reason", "")).strip()[:500]
    if not reason:
        return _json_error("دلیل بن را وارد کن.", 400)
    conn = _db()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE users
                    SET ban_until=CURRENT_TIMESTAMP + (%s * INTERVAL '1 day'),
                        ban_reason=%s
                    WHERE user_id=%s
                    RETURNING user_id, ban_until
                """, (days, reason, user_id))
                row = cur.fetchone()
        if not row:
            return _json_error("کاربر در دیتابیس پیدا نشد.", 404)
        ban_until = row[1]
        jalali_until = _format_jalali_datetime(ban_until)
        message = (
            f"⛔ حساب کاربری شما به مدت {days} روز مسدود شد.\n"
            f"علت : {reason}\n"
            f"تاریخ رفع بن : {jalali_until}"
        )
        try:
            _telegram_call("sendMessage", {"chat_id": user_id, "text": message})
        except Exception as exc:
            return jsonify({"ok": True, "notification_sent": False,
                            "notification_error": str(exc),
                            "ban_until": jalali_until})
        return jsonify({"ok": True, "notification_sent": True,
                        "ban_until": jalali_until})
    finally:
        conn.close()


@admin_panel.post("/api/users/delete")
@_auth_required
@_csrf_required
def delete_user():
    payload = request.get_json(silent=True) or {}
    try:
        user_id = int(payload.get("user_id"))
    except (TypeError, ValueError):
        return _json_error("شناسه کاربر معتبر نیست.", 400)

    conn = _db()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM users WHERE user_id = %s RETURNING user_id", (user_id,))
                deleted = cur.fetchone()
                if not deleted:
                    return _json_error("کاربر پیدا نشد.", 404)
                # Remove only the pending-new-user queue entry. Preserve anonymous
                # messages and block relationships so this action does not erase history.
                cur.execute("DELETE FROM new_user_queue WHERE user_id = %s", (user_id,))
        return jsonify({"ok": True, "user_id": user_id})
    finally:
        conn.close()


@admin_panel.post("/api/users/rename")
@_auth_required
@_csrf_required
def rename_user():
    payload=request.get_json(silent=True) or {}
    try: user_id=int(payload.get("user_id"))
    except (TypeError,ValueError): return _json_error("شناسه کاربر معتبر نیست.",400)
    name=str(payload.get("display_name","")).strip()[:100]
    if not name: return _json_error("نام نمایشی را وارد کن.",400)
    conn=_db()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE users SET display_name=%s WHERE user_id=%s RETURNING user_id",(name,user_id))
                row=cur.fetchone()
        if not row: return _json_error("کاربر پیدا نشد.",404)
        return jsonify({"ok":True})
    finally: conn.close()


@admin_panel.post("/api/users/message")
@_auth_required
@_csrf_required
def message_user():
    payload=request.get_json(silent=True) or {}
    try: user_id=int(payload.get("user_id"))
    except (TypeError,ValueError): return _json_error("شناسه کاربر معتبر نیست.",400)
    message=str(payload.get("text","")).strip()
    if not message or len(message)>4000: return _json_error("متن پیام خالی یا بیش از حد طولانی است.",400)
    try: _telegram_call("sendMessage",{"chat_id":user_id,"text":"📢 پیام از طرف مدیریت گلدن چت:\n\n"+message})
    except Exception as exc: return _json_error("ارسال نشد: "+str(exc),502)
    return jsonify({"ok":True})


@admin_panel.post("/api/users/message-inline")
@_auth_required
@_csrf_required
def message_user_with_inline_button():
    payload = request.get_json(silent=True) or {}
    try:
        user_id = int(payload.get("user_id"))
    except (TypeError, ValueError):
        return _json_error("شناسه کاربر معتبر نیست.", 400)
    if user_id <= 0:
        return _json_error("شناسه کاربر معتبر نیست.", 400)

    message = str(payload.get("text", ""))
    button_text = str(payload.get("button_text", "")).strip()
    button_url = str(payload.get("button_url", "")).strip()
    if not message.strip() or len(message) > 4000:
        return _json_error("متن پیام خالی یا بیش از حد طولانی است.", 400)
    if not button_text or len(button_text) > 40:
        return _json_error("متن دکمه باید بین ۱ تا ۴۰ نویسه باشد.", 400)
    parsed_url = urlsplit(button_url)
    if parsed_url.scheme != "https" or not parsed_url.netloc or any(ch.isspace() for ch in button_url):
        return _json_error("لینک دکمه باید یک آدرس معتبر HTTPS باشد.", 400)

    # Send exactly the admin-provided text. Do not prepend any management notice.
    try:
        _telegram_call("sendMessage", {
            "chat_id": user_id,
            "text": message,
            "reply_markup": {
                "inline_keyboard": [[{"text": button_text, "url": button_url}]]
            },
        })
    except Exception as exc:
        return _json_error("ارسال نشد: " + str(exc), 502)
    return jsonify({"ok": True})


@admin_panel.post("/api/broadcast")
@_auth_required
@_csrf_required
def broadcast_users():
    payload=request.get_json(silent=True) or {}
    message=str(payload.get("text","")).strip()
    if not message or len(message)>4000: return _json_error("متن پیام خالی یا بیش از حد طولانی است.",400)
    conn=_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM users ORDER BY user_id")
            ids=[r[0] for r in cur.fetchall()]
    finally: conn.close()
    sent=failed=0
    for uid in ids:
        try:
            _telegram_call("sendMessage",{"chat_id":uid,"text":message})
            sent+=1
        except Exception:
            failed+=1
    return jsonify({"ok":True,"total":len(ids),"sent":sent,"failed":failed})


@admin_panel.get("/api/supervisors")
@_auth_required
def list_supervisors():
    conn=_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT s.user_id,u.username,u.full_name,s.added_at FROM supervisors s
                LEFT JOIN users u ON u.user_id=s.user_id ORDER BY s.added_at ASC""")
            rows=cur.fetchall()
        return jsonify({"items":[{"user_id":r[0],"username":r[1],"full_name":r[2],
            "added_at":r[3].strftime("%Y-%m-%d") if r[3] else None} for r in rows]})
    finally: conn.close()


@admin_panel.post("/api/supervisors/add")
@_auth_required
@_csrf_required
def add_supervisor_web():
    payload=request.get_json(silent=True) or {}
    try: user_id=int(payload.get("user_id"))
    except (TypeError,ValueError): return _json_error("شناسه ناظر معتبر نیست.",400)
    if user_id <= 0: return _json_error("شناسه ناظر معتبر نیست.",400)
    conn=_db()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO supervisors(user_id) VALUES(%s) ON CONFLICT(user_id) DO NOTHING RETURNING user_id",(user_id,))
                row=cur.fetchone()
        if not row: return _json_error("این ناظر از قبل وجود دارد.",409)
        return jsonify({"ok":True})
    finally: conn.close()


@admin_panel.post("/api/supervisors/remove")
@_auth_required
@_csrf_required
def remove_supervisor_web():
    payload=request.get_json(silent=True) or {}
    try: user_id=int(payload.get("user_id"))
    except (TypeError,ValueError): return _json_error("شناسه ناظر معتبر نیست.",400)
    conn=_db()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM supervisors WHERE user_id=%s RETURNING user_id",(user_id,))
                row=cur.fetchone()
        if not row: return _json_error("ناظر پیدا نشد.",404)
        return jsonify({"ok":True})
    finally: conn.close()


@admin_panel.get("/api/ad-requests")
@_auth_required
def list_advertisement_requests():
    conn = _db()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS advertisement_requests (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    username TEXT,
                    full_name TEXT,
                    subject TEXT NOT NULL,
                    ad_link TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    reviewed_at TIMESTAMP
                    )
                """)
                cur.execute("""
                    SELECT id, user_id, username, full_name, subject, ad_link, status, created_at
                    FROM advertisement_requests
                    ORDER BY CASE WHEN status='pending' THEN 0 ELSE 1 END, created_at DESC
                    LIMIT 500
                """)
                rows = cur.fetchall()
        return jsonify({"items": [{
            "id": row[0], "user_id": row[1], "username": row[2], "full_name": row[3],
            "subject": row[4], "ad_link": row[5], "status": row[6],
            "created_at": row[7].strftime("%Y-%m-%d %H:%M") if row[7] else None,
        } for row in rows]})
    finally:
        conn.close()


@admin_panel.post("/api/ad-requests/status")
@_auth_required
@_csrf_required
def update_advertisement_request_status():
    payload = request.get_json(silent=True) or {}
    try:
        request_id = int(payload.get("id"))
    except (TypeError, ValueError):
        return _json_error("شناسه درخواست معتبر نیست.", 400)
    status = str(payload.get("status", ""))
    if status not in ("contacted", "rejected"):
        return _json_error("وضعیت درخواست معتبر نیست.", 400)
    conn = _db()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE advertisement_requests
                    SET status=%s, reviewed_at=CURRENT_TIMESTAMP
                    WHERE id=%s AND status='pending'
                    RETURNING id
                """, (status, request_id))
                row = cur.fetchone()
        if not row:
            return _json_error("درخواست پیدا نشد یا قبلاً بررسی شده است.", 404)
        return jsonify({"ok": True})
    finally:
        conn.close()


@admin_panel.get("/api/requests")
@_auth_required
def list_pending_requests():
    conn=_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT id, supervisor_id, target_id, target_name, reason, created_at
                FROM supervisor_unban_requests WHERE status='pending' ORDER BY created_at ASC""")
            unbans=cur.fetchall()
            cur.execute("""SELECT id, supervisor_id, message_text, created_at
                FROM supervisor_broadcast_requests WHERE status='pending' ORDER BY created_at ASC""")
            broadcasts=cur.fetchall()
        items=[]
        for r in unbans:
            items.append({"id":r[0],"kind":"unban","supervisor_id":r[1],
                "details":f"کاربر {r[2]} ({r[3] or 'بدون نام'})\nدلیل: {r[4]}",
                "created_at":r[5].strftime("%Y-%m-%d %H:%M") if r[5] else None})
        for r in broadcasts:
            items.append({"id":r[0],"kind":"broadcast","supervisor_id":r[1],
                "details":r[2],"created_at":r[3].strftime("%Y-%m-%d %H:%M") if r[3] else None})
        items.sort(key=lambda x:x["created_at"] or "")
        return jsonify({"items":items})
    finally: conn.close()


@admin_panel.post("/api/requests/decision")
@_auth_required
@_csrf_required
def decide_request():
    payload=request.get_json(silent=True) or {}
    kind=str(payload.get("kind","")); decision=str(payload.get("decision",""))
    try: request_id=int(payload.get("id"))
    except (TypeError,ValueError): return _json_error("شناسه درخواست معتبر نیست.",400)
    if kind not in ("unban","broadcast") or decision not in ("approve","reject"):
        return _json_error("نوع تصمیم معتبر نیست.",400)
    conn=_db()
    try:
        with conn:
            with conn.cursor() as cur:
                if kind=="unban":
                    cur.execute("SELECT target_id, target_code FROM supervisor_unban_requests WHERE id=%s AND status='pending' FOR UPDATE",(request_id,))
                    req=cur.fetchone()
                    if not req: return _json_error("درخواست پیدا نشد یا قبلاً بررسی شده.",404)
                    if decision=="approve":
                        cur.execute("UPDATE users SET ban_until=NULL, ban_reason=NULL WHERE lower(ban_code)=lower(%s)",(req[1],))
                    cur.execute("UPDATE supervisor_unban_requests SET status=%s WHERE id=%s",("approved" if decision=="approve" else "rejected",request_id))
                else:
                    cur.execute("SELECT message_text FROM supervisor_broadcast_requests WHERE id=%s AND status='pending' FOR UPDATE",(request_id,))
                    req=cur.fetchone()
                    if not req: return _json_error("درخواست پیدا نشد یا قبلاً بررسی شده.",404)
                    if decision=="approve":
                        cur.execute("SELECT user_id FROM users ORDER BY user_id")
                        user_ids=[r[0] for r in cur.fetchall()]
                    else: user_ids=[]
                    cur.execute("UPDATE supervisor_broadcast_requests SET status=%s WHERE id=%s",("approved" if decision=="approve" else "rejected",request_id))
                    message=req[0]
        if kind == "unban" and decision == "approve":
            try:
                _telegram_call("sendMessage", {
                    "chat_id": req[0],
                    "text": "🟢 مسدودی حساب کاربری شما توسط مدیریت گلدن چت رفع شد.\\n\\nاکنون می‌توانید از قابلیت‌های ربات استفاده کنید. برای شروع /start را بزنید."
                })
            except Exception:
                pass
        if kind=="broadcast" and decision=="approve":
            sent=failed=0
            for uid in user_ids:
                try: _telegram_call("sendMessage",{"chat_id":uid,"text":message}); sent+=1
                except Exception: failed+=1
            return jsonify({"ok":True,"sent":sent,"failed":failed})
        return jsonify({"ok":True})
    finally: conn.close()


@admin_panel.get("/api/reports/unread-count")
@_auth_required
def unread_abuse_report_count():
    conn=_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM abuse_reports WHERE is_read=FALSE")
            count=cur.fetchone()[0]
        return jsonify({"unread":count})
    finally: conn.close()


@admin_panel.get("/api/reports")
@_auth_required
def list_abuse_reports():
    conn=_db()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""UPDATE abuse_reports SET is_read=TRUE WHERE id IN (
                    SELECT id FROM abuse_reports ORDER BY is_read ASC, created_at DESC LIMIT 200
                )""")
        with conn.cursor() as cur:
            cur.execute("""SELECT id, report_type, reporter_id, reporter_name,
                    reported_user_id, reported_username, reported_name, message_id,
                    group_id, group_title, message_text, created_at, is_read
                FROM abuse_reports ORDER BY is_read ASC, created_at DESC LIMIT 200""")
            rows=cur.fetchall()
        items=[]
        for r in rows:
            items.append({"id":r[0],"report_type":r[1],"reporter_id":r[2],
                "reporter_name":r[3],"reported_user_id":r[4],"reported_username":r[5],
                "reported_name":r[6],"message_id":r[7],"group_id":r[8],"group_title":r[9],
                "message_text":r[10],"created_at":r[11].strftime("%Y-%m-%d %H:%M") if r[11] else None,
                "is_read":r[12]})
        return jsonify({"items":items})
    finally: conn.close()


@admin_panel.post("/api/reports/read")
@_auth_required
@_csrf_required
def mark_abuse_report_read():
    payload=request.get_json(silent=True) or {}
    try: report_id=int(payload.get("id"))
    except (TypeError,ValueError): return _json_error("شناسه گزارش معتبر نیست.",400)
    conn=_db()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE abuse_reports SET is_read=TRUE WHERE id=%s RETURNING id",(report_id,))
                row=cur.fetchone()
        if not row: return _json_error("گزارش پیدا نشد.",404)
        return jsonify({"ok":True})
    finally: conn.close()
