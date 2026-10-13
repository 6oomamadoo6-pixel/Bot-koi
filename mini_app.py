import hashlib
import hmac
import json
import os
import time
from urllib.parse import parse_qsl

import psycopg2
from flask import Blueprint, jsonify, make_response, render_template_string, request

mini_app = Blueprint("mini_app", __name__, url_prefix="/miniapp")

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
BOT_USERNAME = os.getenv("BOT_USERNAME", "HideMyChatRobot").lstrip("@")

PAGE = r"""<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0b0b0a">
<title>Golden Chat</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root{color-scheme:dark;--bg:#0b0b0a;--panel:#141411;--panel2:#1b1a15;--gold:#e6bb51;--gold2:#ffe7a0;--muted:#aaa79b;--line:#51401d;--green:#5dd49a;--red:#ff7777}
*{box-sizing:border-box}html,body{margin:0;min-height:100%;background:radial-gradient(ellipse at 50% -10%,#352910 0,#15130d 32%,var(--bg) 72%);color:#f8f3e4;font-family:Tahoma,"Noto Sans Arabic",sans-serif}body{padding:env(safe-area-inset-top) 0 env(safe-area-inset-bottom)}button{font:inherit;cursor:pointer}.wrap{max-width:760px;margin:auto;padding:18px 14px 28px}.top{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:18px}.brand{display:flex;align-items:center;gap:10px;direction:ltr}.logo{width:43px;height:43px;display:grid;place-items:center;border-radius:15px;background:linear-gradient(145deg,#ffe7a0,#a87819);color:#211703;font-size:24px;box-shadow:0 5px 24px #e6bb5126}.brand h1{font-size:17px;letter-spacing:1.5px;margin:0;color:var(--gold2)}.brand small{display:block;margin-top:4px;color:#999587;font-size:10px;letter-spacing:1px}.status{border:1px solid var(--green);border-radius:13px;padding:9px 10px;text-align:right;background:#11271d;font-size:11px;line-height:1.7;max-width:53%}.status.banned{border-color:var(--red);background:#301716}.status strong{display:block;font-size:12px}.welcome{border:1px solid #4b3a19;border-radius:22px;padding:18px;background:linear-gradient(130deg,#27200f,#151510 68%);box-shadow:0 12px 36px #0003;margin-bottom:16px;position:relative;overflow:hidden}.welcome:after{content:"✦";position:absolute;left:15px;top:-15px;font-size:92px;color:#e6bb5110}.eyebrow{font-size:10px;color:var(--gold);letter-spacing:2px;direction:ltr;text-align:right}.welcome h2{font-size:20px;margin:10px 0 6px}.welcome p{font-size:12px;line-height:1.9;color:#c3bdad;margin:0}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin:14px 0}.navbtn{min-height:106px;text-align:right;color:#f7f0dc;border:1px solid #9c792c;border-radius:19px;padding:14px;background:linear-gradient(145deg,#201c12,#131310);box-shadow:inset 0 1px #ffe7a012,0 6px 16px #0002;transition:transform .15s,border-color .15s}.navbtn:active{transform:scale(.98);border-color:var(--gold2)}.navbtn.active{border-color:var(--gold2);background:linear-gradient(145deg,#332811,#19170f);box-shadow:0 0 0 1px #e6bb5122,inset 0 1px #ffe7a022}.navicon{display:grid;place-items:center;width:35px;height:35px;border:1px solid #775b24;border-radius:12px;color:var(--gold2);font-size:18px;margin-bottom:10px;background:#e6bb510c}.navbtn strong{display:block;font-size:12px;line-height:1.8}.navbtn small{display:block;color:#9d988a;font-size:10px;margin-top:2px}.panel{border:1px solid #3e341f;border-radius:20px;background:#12120ff2;padding:15px;margin-top:13px;min-height:210px}.panelhead{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:14px}.panelhead h3{font-size:15px;margin:0}.counter{font-size:10px;border:1px solid #5d4921;color:var(--gold2);border-radius:99px;padding:5px 9px}.hidden{display:none!important}.message-list{height:min(55vh,540px);min-height:240px;overflow-y:auto;display:flex;flex-direction:column;gap:12px;padding:4px 2px 12px;direction:ltr;overscroll-behavior:contain}.message{width:min(88%,520px);border:1px solid #554522;border-radius:16px;padding:12px;background:linear-gradient(140deg,#211d13,#171712);direction:rtl;align-self:flex-end;box-shadow:0 4px 15px #0002}.message.outgoing{align-self:flex-start;border-color:#8d6b27;background:linear-gradient(140deg,#2b2414,#171712)}.msglabel{font-size:11px;color:var(--gold2);font-weight:bold;line-height:1.9;margin-bottom:7px}.msgbody{font-size:12px;line-height:1.9;white-space:pre-wrap;overflow-wrap:anywhere;color:#f3eee0}.msgmeta{display:flex;flex-wrap:wrap;justify-content:space-between;gap:6px;color:#9c978a;font-size:9px;margin-top:10px;border-top:1px solid #ffffff0d;padding-top:8px}.tag{display:inline-block;color:#f4d98b;border:1px solid #665020;border-radius:7px;padding:2px 6px;font-size:9px;margin-bottom:6px}.loadmore,.copybtn,.backbtn{border:1px solid #8c6c2b;background:#201b10;color:var(--gold2);border-radius:12px;padding:10px 12px;font-size:11px}.loadmore{width:100%;margin:0 0 10px}.item{border:1px solid #3f351f;background:#191811;border-radius:15px;padding:13px;margin-bottom:10px;overflow-wrap:anywhere}.item strong{display:block;font-size:12px;margin-bottom:8px}.item code{direction:ltr;display:block;text-align:left;color:#f7d98a;font-size:11px;overflow-wrap:anywhere;white-space:normal;line-height:1.8}.item .hint{color:#aaa494;font-size:10px;line-height:1.8;margin-top:8px}.itemrow{display:flex;gap:8px;align-items:center;justify-content:space-between}.itemrow code{flex:1}.empty{padding:30px 12px;text-align:center;color:#aaa494;font-size:12px;line-height:2}.loader{width:25px;height:25px;border:2px solid #58451e;border-top-color:var(--gold2);border-radius:50%;animation:spin .8s linear infinite;margin:20px auto}@keyframes spin{to{transform:rotate(360deg)}}.foot{text-align:center;color:#6f6b5e;font-size:9px;padding:20px 0 5px}.toast{position:fixed;z-index:9;bottom:calc(18px + env(safe-area-inset-bottom));right:15px;left:15px;max-width:440px;margin:auto;background:#272115;border:1px solid #9c792c;border-radius:12px;padding:12px;text-align:center;font-size:12px;box-shadow:0 8px 35px #0009}.error{color:#ffaaa2}.blocked-user{display:flex;justify-content:space-between;align-items:center;gap:10px}.blocked-user .uid{color:#b9b3a4;font-size:10px;direction:ltr}.muted{color:#a7a193;font-size:11px;line-height:1.9}
@media(min-width:600px){.wrap{padding:24px}.welcome{padding:23px}.grid{gap:13px}.navbtn{min-height:115px;padding:17px}.panel{padding:20px}.message{width:82%}}
@media(max-width:350px){.wrap{padding:12px 9px}.brand h1{font-size:14px}.status{font-size:10px;padding:7px}.grid{gap:7px}.navbtn{padding:11px;min-height:98px}.navbtn strong{font-size:11px}.message{width:94%}}
</style>
</head>
<body>
<main class="wrap">
<header class="top">
  <div class="brand"><div class="logo">✦</div><div><h1>GOLDEN CHAT</h1><small>YOUR ANONYMOUS SPACE</small></div></div>
  <div id="status" class="status"><span>وضعیت حساب</span><strong>در حال بررسی…</strong></div>
</header>
<section class="welcome"><div class="eyebrow">WELCOME TO GOLDEN CHAT</div><h2>فضای ناشناس تو ✨</h2><p>پیام‌ها، لینک‌ها و کاربران مسدودت رو از یک‌جا مدیریت کن.</p></section>
<nav class="grid" aria-label="بخش‌های مینی‌اپ">
<button class="navbtn active" data-view="messages"><span class="navicon">💬</span><strong>چت‌های ارسالی و دریافتی من</strong><small>تاریخچه پیام‌های ناشناس</small></button>
<button class="navbtn" data-view="personal"><span class="navicon">🔗</span><strong>لینک ناشناس من</strong><small>لینک اختصاصی دریافت پیام</small></button>
<button class="navbtn" data-view="channels"><span class="navicon">📣</span><strong>لینک‌های ناشناس چنل من</strong><small>لینک‌های کانال‌های متصل</small></button>
<button class="navbtn" data-view="blocks"><span class="navicon">🚫</span><strong>کاربران مسدود</strong><small>فهرست مسدودی‌های تو</small></button>
</nav>
<section id="messagesPanel" class="panel"><div class="panelhead"><h3>💬 تاریخچه پیام‌ها</h3><span id="messageCount" class="counter">— پیام</span></div><div id="messages"><div class="loader"></div></div></section>
<section id="personalPanel" class="panel hidden"><div class="panelhead"><h3>🔗 لینک ناشناس من</h3></div><div id="personal"><div class="loader"></div></div></section>
<section id="channelsPanel" class="panel hidden"><div class="panelhead"><h3>📣 لینک‌های ناشناس چنل من</h3></div><div id="channels"><div class="loader"></div></div></section>
<section id="blocksPanel" class="panel hidden"><div class="panelhead"><h3>🚫 کاربران مسدود</h3><span id="blockCount" class="counter">— نفر</span></div><div id="blocks"><div class="loader"></div></div></section>
<div class="foot">GOLDEN CHAT · GOLDEN THEME ✦</div>
</main>
<div id="toast" class="toast hidden"></div>
<script>
(function(){
  var tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  if(tg){tg.ready();tg.expand();try{tg.setHeaderColor("#0b0b0a");tg.setBackgroundColor("#0b0b0a");}catch(e){}}
  var initData = tg ? tg.initData : "";
  var currentView = "messages";
  var offset = 0, limit = 40, loading = false, hasMore = true;
  var totalMessages = 0;
  var cache = {};
  function el(id){return document.getElementById(id);}
  function toast(msg){var t=el("toast");t.textContent=msg;t.classList.remove("hidden");setTimeout(function(){t.classList.add("hidden");},2300);}
  function node(tag, cls, text){var n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;}
  function button(text, fn, cls){var b=node("button",cls||"copybtn",text);b.type="button";b.addEventListener("click",fn);return b;}
  async function api(path){
    var res=await fetch("/miniapp/api/"+path,{headers:{"X-Telegram-Init-Data":initData},credentials:"same-origin"});
    var data=await res.json().catch(function(){return {};});
    if(!res.ok)throw new Error(data.error||"دریافت اطلاعات ناموفق بود.");
    return data;
  }
  function formatDate(value){
    if(!value)return "زمان ثبت نشده";
    var d=new Date(value);if(isNaN(d.getTime()))return String(value);
    try{return new Intl.DateTimeFormat("fa-IR",{year:"numeric",month:"short",day:"numeric",hour:"2-digit",minute:"2-digit"}).format(d);}catch(e){return d.toLocaleString();}
  }
  function renderStatus(profile){
    var s=el("status");s.classList.toggle("banned",profile.is_banned);
    s.style.borderColor=profile.is_banned?"var(--red)":"var(--green)";
    s.innerHTML="";
    s.appendChild(node("span","","وضعیت حساب"));
    s.appendChild(node("strong","",profile.is_banned?"مسدود ⛔":"مسدود نیست ✅"));
  }
  function setView(view){
    currentView=view;
    ["messages","personal","channels","blocks"].forEach(function(v){
      el(v+"Panel").classList.toggle("hidden",v!==view);
    });
    document.querySelectorAll(".navbtn").forEach(function(b){b.classList.toggle("active",b.dataset.view===view);});
    if(view==="messages" && !cache.messages)loadMessages(true);
    if(view==="personal" && !cache.personal)loadPersonal();
    if(view==="channels" && !cache.channels)loadChannels();
    if(view==="blocks" && !cache.blocks)loadBlocks();
  }
  document.querySelectorAll(".navbtn").forEach(function(b){b.addEventListener("click",function(){setView(b.dataset.view);});});
  function renderMessages(items, prepend){
    var container=el("messageList");
    if(!container){container=node("div","message-list");container.id="messageList";el("messages").replaceChildren(container);}
    var oldHeight=container.scrollHeight, oldTop=container.scrollTop;
    var frag=document.createDocumentFragment();
    items.forEach(function(m){
      var card=node("article","message "+(m.direction==="sent"?"outgoing":"incoming"));
      card.appendChild(node("div","msglabel",m.direction==="sent"?"شما به "+(m.other_name||("کاربر "+m.other_id))+" پیام زیر را ارسال کردید.":"کاربر "+m.other_id+" برای شما پیام زیر را ارسال کرد."));
      if(m.media_type)card.appendChild(node("span","tag",m.media_label||("رسانه: "+m.media_type)));
      card.appendChild(node("div","msgbody",m.text||"محتوای متنی برای این پیام ثبت نشده است."));
      var meta=node("div","msgmeta");
      meta.appendChild(node("span","","شناسه پیام: "+m.id));
      meta.appendChild(node("span","",formatDate(m.created_at)));
      if(m.seen_at)meta.appendChild(node("span","","دیده‌شده: "+formatDate(m.seen_at)));
      card.appendChild(meta);frag.appendChild(card);
    });
    if(prepend){container.insertBefore(frag,container.firstChild);container.scrollTop=container.scrollHeight-oldHeight+oldTop;}
    else{container.appendChild(frag);}
  }
  async function loadMessages(reset){
    if(loading)return;loading=true;
    if(reset){offset=0;hasMore=true;el("messages").replaceChildren(node("div","loader"));}
    try{
      var data=await api("messages?offset="+offset+"&limit="+limit);
      if(reset){el("messages").replaceChildren();cache.messages=true;totalMessages=data.total||0;el("messageCount").textContent=String(totalMessages)+" پیام";}
      var old=el("loadMore");if(old)old.remove();
      if(data.items&&data.items.length){renderMessages(data.items,false);offset+=data.items.length;hasMore=!!data.has_more;}
      else if(reset){el("messages").replaceChildren(node("div","empty","هنوز پیامی در تاریخچه ثبت نشده است."));}
      if(hasMore){
        var b=button("نمایش پیام‌های قدیمی‌تر ↓",function(){loadMessages(false);},"loadmore");b.id="loadMore";
        var list=el("messageList");if(list)list.parentNode.insertBefore(b,list);else el("messages").appendChild(b);
      }
    }catch(e){el("messages").replaceChildren(node("div","empty error",e.message));}
    finally{loading=false;}
  }
  async function loadPersonal(){
    el("personal").replaceChildren(node("div","loader"));
    try{var d=await api("personal-link");cache.personal=true;var box=node("div","item");box.appendChild(node("strong","","لینک اختصاصی تو"));var row=node("div","itemrow");row.appendChild(node("code","",d.url));row.appendChild(button("کپی",function(){copyText(d.url);},"copybtn"));box.appendChild(row);box.appendChild(node("div","hint","","این لینک را برای دیگران بفرست تا بتوانند ناشناس برایت پیام ارسال کنند."));el("personal").replaceChildren(box);}
    catch(e){el("personal").replaceChildren(node("div","empty error",e.message));}
  }
  async function loadChannels(){
    el("channels").replaceChildren(node("div","loader"));
    try{var d=await api("channel-links");cache.channels=true;el("channels").replaceChildren();if(!d.items.length){el("channels").appendChild(node("div","empty","هنوز لینک ناشناس کانالی برای حساب تو ثبت نشده است."));return;}
      d.items.forEach(function(item){var box=node("div","item");box.appendChild(node("strong","",item.title||"کانال"));var row=node("div","itemrow");row.appendChild(node("code","",item.url));row.appendChild(button("کپی",function(){copyText(item.url);},"copybtn"));box.appendChild(row);box.appendChild(node("div","hint","","شناسه کانال: "+item.channel_id));el("channels").appendChild(box);});
    }catch(e){el("channels").replaceChildren(node("div","empty error",e.message));}
  }
  async function loadBlocks(){
    el("blocks").replaceChildren(node("div","loader"));
    try{var d=await api("blocks");cache.blocks=true;el("blockCount").textContent=String(d.items.length)+" نفر";el("blocks").replaceChildren();if(!d.items.length){el("blocks").appendChild(node("div","empty","فهرست مسدودی‌های تو خالی است ✨"));return;}
      d.items.forEach(function(item){var box=node("div","item blocked-user");var info=node("div","");info.appendChild(node("strong","",item.name||("کاربر "+item.user_id)));info.appendChild(node("div","uid","ID: "+item.user_id));box.appendChild(info);box.appendChild(node("span","tag","مسدود"));el("blocks").appendChild(box);});
    }catch(e){el("blocks").replaceChildren(node("div","empty error",e.message));}
  }
  function copyText(value){
    if(tg&&tg.clipboard&&tg.clipboard.writeText){tg.clipboard.writeText(value).then(function(){toast("لینک کپی شد ✅");}).catch(function(){fallbackCopy(value);});}
    else if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(value).then(function(){toast("لینک کپی شد ✅");}).catch(function(){fallbackCopy(value);});}
    else fallbackCopy(value);
  }
  function fallbackCopy(value){var input=node("textarea","");input.value=value;input.style.position="fixed";input.style.opacity="0";document.body.appendChild(input);input.select();try{document.execCommand("copy");toast("لینک کپی شد ✅");}catch(e){toast("کپی خودکار نشد؛ لینک را انتخاب کن.");}input.remove();}
  async function start(){
    if(!initData){el("status").classList.add("banned");el("status").innerHTML="<span>وضعیت حساب</span><strong>از داخل تلگرام باز کن</strong>";el("messages").replaceChildren(node("div","empty error","این مینی‌اپ باید از دکمه داخل ربات تلگرام باز شود تا هویت حساب تأیید شود."));return;}
    try{var p=await api("me");renderStatus(p);loadMessages(true);}
    catch(e){el("status").classList.add("banned");el("status").innerHTML="<span>وضعیت حساب</span><strong>تأیید ناموفق</strong>";el("messages").replaceChildren(node("div","empty error",e.message));}
  }
  start();
})();
</script>
</body>
</html>"""


def _verify_init_data(raw):
    if not BOT_TOKEN or not raw:
        return None
    try:
        pairs = parse_qsl(raw, keep_blank_values=True)
        data = dict(pairs)
        supplied_hash = data.pop("hash", None)
        if not supplied_hash:
            return None
        check_string = "\n".join(
            key + "=" + value for key, value in sorted(data.items())
        )
        secret_key = hmac.new(
            b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256
        ).digest()
        expected_hash = hmac.new(
            secret_key, check_string.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected_hash, supplied_hash):
            return None
        auth_date = int(data.get("auth_date", "0"))
        if auth_date <= 0 or time.time() - auth_date > 86400 or auth_date - time.time() > 60:
            return None
        user = json.loads(data.get("user", "{}"))
        user_id = int(user.get("id", 0))
        if user_id <= 0:
            return None
        return user_id
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def _current_user_id():
    user_id = _verify_init_data(request.headers.get("X-Telegram-Init-Data", ""))
    return user_id


def _db_connect():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured")
    return psycopg2.connect(DATABASE_URL, connect_timeout=10)


def _auth_error():
    return jsonify({"error": "هویت تلگرام تأیید نشد. مینی‌اپ را از داخل ربات باز کن و دوباره امتحان کن."}), 401


@mini_app.get("/")
def mini_app_page():
    response = make_response(render_template_string(PAGE))
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@mini_app.get("/api/me")
def mini_app_me():
    user_id = _current_user_id()
    if not user_id:
        return _auth_error()
    conn = _db_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT user_id, ban_until, ban_reason FROM users WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "حساب شما هنوز در ربات ثبت نشده است. ابتدا /start را بزن."}), 404
            ban_until, ban_reason = row[1], row[2]
            is_banned = bool(ban_reason and (ban_until is None or ban_until > __import__("datetime").datetime.now()))
            return jsonify({"user_id": int(row[0]), "is_banned": is_banned})
    finally:
        conn.close()


@mini_app.get("/api/messages")
def mini_app_messages():
    user_id = _current_user_id()
    if not user_id:
        return _auth_error()
    try:
        offset = max(0, min(int(request.args.get("offset", "0")), 1000000))
        limit = max(1, min(int(request.args.get("limit", "40")), 100))
    except ValueError:
        return jsonify({"error": "صفحه‌بندی نامعتبر است."}), 400
    conn = _db_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM anonymous_messages WHERE sender_id = %s OR receiver_id = %s",
                (user_id, user_id),
            )
            total = cur.fetchone()[0]
            cur.execute(
                """
                SELECT m.id, m.sender_id, m.receiver_id, m.message_text,
                       m.created_at, m.seen_at, m.media_type, m.media_caption,
                       CASE WHEN m.sender_id = %s THEN 'sent' ELSE 'received' END AS direction,
                       CASE WHEN m.sender_id = %s THEN COALESCE(NULLIF(r.display_name, ''),
                             NULLIF(r.full_name, ''), NULLIF(r.username, ''), 'کاربر')
                            ELSE NULL END AS other_name
                FROM anonymous_messages m
                LEFT JOIN users r ON r.user_id = m.receiver_id
                WHERE m.sender_id = %s OR m.receiver_id = %s
                ORDER BY m.created_at DESC NULLS LAST, m.id DESC
                OFFSET %s LIMIT %s
                """,
                (user_id, user_id, user_id, user_id, offset, limit),
            )
            rows = cur.fetchall()
            items = []
            for row in rows:
                media_type = row[6]
                text_value = row[3] or row[7] or ""
                if row[7] and row[3] and row[7] != row[3]:
                    text_value = row[3] + "\n\n" + row[7]
                items.append({
                    "id": int(row[0]),
                    "sender_id": int(row[1]),
                    "receiver_id": int(row[2]),
                    "direction": row[8],
                    "other_id": int(row[2] if row[8] == "sent" else row[1]),
                    "other_name": row[9],
                    "text": text_value,
                    "created_at": row[4].isoformat() if row[4] else None,
                    "seen_at": row[5].isoformat() if row[5] else None,
                    "media_type": media_type,
                    "media_label": ({"photo": "عکس", "video": "ویدیو", "voice": "پیام صوتی",
                                     "audio": "فایل صوتی", "document": "فایل", "sticker": "استیکر",
                                     "animation": "گیف", "video_note": "ویدیوی گرد"}.get(media_type, media_type)
                                    if media_type else None),
                })
            return jsonify({"items": items, "total": total, "has_more": offset + len(items) < total})
    finally:
        conn.close()


@mini_app.get("/api/personal-link")
def mini_app_personal_link():
    user_id = _current_user_id()
    if not user_id:
        return _auth_error()
    conn = _db_connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT link_code FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            if not row or not row[0]:
                return jsonify({"error": "لینک اختصاصی هنوز برای حساب تو ثبت نشده است."}), 404
            return jsonify({"url": "https://t.me/" + BOT_USERNAME + "?start=" + str(row[0])})
    finally:
        conn.close()


@mini_app.get("/api/channel-links")
def mini_app_channel_links():
    user_id = _current_user_id()
    if not user_id:
        return _auth_error()
    conn = _db_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT channel_id, channel_title, link_code FROM channel_links WHERE owner_id = %s ORDER BY created_at DESC",
                (user_id,),
            )
            rows = cur.fetchall()
            items = [{
                "channel_id": int(row[0]),
                "title": row[1] or "کانال",
                "url": "https://t.me/" + BOT_USERNAME + "?start=" + str(row[2]),
            } for row in rows]
            return jsonify({"items": items})
    finally:
        conn.close()


@mini_app.get("/api/blocks")
def mini_app_blocks():
    user_id = _current_user_id()
    if not user_id:
        return _auth_error()
    conn = _db_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT b.blocked_id, COALESCE(NULLIF(u.display_name, ''),
                       NULLIF(u.full_name, ''), NULLIF(u.username, ''), 'کاربر') AS name
                FROM blocks b
                LEFT JOIN users u ON u.user_id = b.blocked_id
                WHERE b.blocker_id = %s
                ORDER BY b.created_at DESC NULLS LAST, b.blocked_id DESC
                """,
                (user_id,),
            )
            return jsonify({"items": [{"user_id": int(row[0]), "name": row[1]} for row in cur.fetchall()]})
    finally:
        conn.close()
