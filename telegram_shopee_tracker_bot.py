import os
import time
import json
import requests
from flask import Flask, request, jsonify
from telegram import Bot, Update, ParseMode
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, Filters

# --- Configuration ---
BOT_TOKEN = os.getenv("8339982187:AAErR-8XQ7ZEKGJmdoG-RR_Ad6hoTDTbRE4")  # set this in Render environment variables
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # optional: e.g. https://your-app.onrender.com/webhook
DATA_FILE = "tracked.json"
SPX_ENDPOINT = "https://spx.vn/api/v2/track/track-package?billCode="

# --- Initialize bot & flask app ---
bot = Bot(token=BOT_TOKEN) if BOT_TOKEN else None
app = Flask(__name__)

# Create a dispatcher for handling updates
dispatcher = Dispatcher(bot, None, workers=4, use_context=True) if bot else None

# ---------------- Storage helpers ----------------
def load_data():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"subscriptions": {}}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ---------------- SPX query ----------------
def query_spx(tracking_number):
    try:
        url = SPX_ENDPOINT + tracking_number
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            return None
        body = r.json()
        data = body.get("data")
        if not data:
            return None
        status = data.get("statusText") or data.get("status")
        history = data.get("tracking") or []
        # Normalize history items
        hist = []
        for h in history:
            # SPX may use keys like updateTime and message
            ts = h.get("updateTime") or h.get("time")
            # Try to parse timestamp if numeric / string; we'll keep raw
            hist.append({"time": ts, "desc": h.get("message") or h.get("desc") or h.get("status")})
        return {
            "status_code": status,
            "status_text": status,
            "last_update": time.time(),
            "history": hist
        }
    except Exception:
        return None

# ---------------- Helpers ----------------
def format_tracking_text(courier, tracking, info):
    status = info.get("status_text") or info.get("status_code") or "Không rõ"
    last = info.get("last_update")
    t = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last)) if last else ""
    history = info.get("history", [])
    hist_lines = []
    # show up to last 5
    for h in (history[-5:][::-1] if history else []):
        ts = h.get("time")
        if isinstance(ts, (int, float)):
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
        hist_lines.append(f"- {ts or ''} {h.get('desc','')}")
    hist_txt = "\n".join(hist_lines) if hist_lines else "(không có lịch sử chi tiết)"
    return f"<b>{courier.upper()} {tracking}</b>\nTrạng thái: {status}\nCập nhật: {t}\nLịch sử:\n{hist_txt}"

# ---------------- Command Handlers ----------------
def start(update, context):
    update.message.reply_text(
        "Xin chào! Gửi /track <mã> để lưu mã theo dõi (ví dụ: /track SPXVN0123456789) hoặc /check <mã> để kiểm tra nhanh."
    )

def help_cmd(update, context):
    update.message.reply_text(
        "/track <mã> - lưu mã theo dõi cho chat này\n"
        "/check <mã> - kiểm tra mã ngay (không lưu)\n"
        "/list - danh sách mã đang theo dõi cho chat\n"
        "/remove <mã> - xoá mã khỏi theo dõi\n"
    )

def track(update, context):
    args = context.args
    if len(args) != 1:
        update.message.reply_text("Cú pháp: /track <mã_vận_đơn>")
        return
    tracking = args[0].strip()
    courier = "spx"
    data = load_data()
    chat_id = str(update.effective_chat.id)
    subs = data.setdefault("subscriptions", {})
    chat_subs = subs.setdefault(chat_id, [])
    for s in chat_subs:
        if s.get("courier")==courier and s.get("tracking")==tracking:
            update.message.reply_text("Mã này đã được thêm trước đó.")
            return
    info = query_spx(tracking) or {"status_code":"UNKNOWN","status_text":"Chưa có thông tin","last_update":time.time(),"history":[]}
    entry = {"courier":courier,"tracking":tracking,"last_status":info.get("status_code"),"last_text":info.get("status_text"),"last_update":info.get("last_update",time.time())}
    chat_subs.append(entry)
    save_data(data)
    update.message.reply_text(f"Đã thêm theo dõi: {courier} {tracking}\nTrạng thái: {entry['last_text']}")

def check(update, context):
    args = context.args
    if len(args) != 1:
        update.message.reply_text("Cú pháp: /check <mã_vận_đơn>")
        return
    tracking = args[0].strip()
    info = query_spx(tracking)
    if not info:
        update.message.reply_text("Không lấy được thông tin. Vui lòng thử lại sau.")
        return
    txt = format_tracking_text("spx", tracking, info)
    update.message.reply_text(txt, parse_mode=ParseMode.HTML)

def list_tracks(update, context):
    data = load_data()
    chat_id = str(update.effective_chat.id)
    chat_subs = data.get("subscriptions", {}).get(chat_id, [])
    if not chat_subs:
        update.message.reply_text("Không có mã nào được theo dõi trong chat này.")
        return
    lines = [f"{s['courier']} {s['tracking']} — {s.get('last_text','?')}" for s in chat_subs]
    update.message.reply_text("Các mã đang theo dõi:\n" + "\n".join(lines))

def remove(update, context):
    args = context.args
    if len(args)!=1:
        update.message.reply_text("Cú pháp: /remove <mã_vận_đơn>")
        return
    tracking = args[0].strip()
    courier = "spx"
    data = load_data()
    chat_id = str(update.effective_chat.id)
    chat_subs = data.get("subscriptions", {}).get(chat_id, [])
    new_subs = [s for s in chat_subs if not (s['courier']==courier and s['tracking']==tracking)]
    data.setdefault("subscriptions", {})[chat_id] = new_subs
    save_data(data)
    update.message.reply_text("Đã xóa nếu tồn tại.")

def echo_message(update, context):
    # If user sends a plain message that looks like a tracking code, auto-check it
    txt = update.message.text.strip()
    # simple heuristic: contains letters+digits and length between 6 and 30
    if 6 <= len(txt) <= 40 and any(c.isdigit() for c in txt):
        info = query_spx(txt)
        if info:
            update.message.reply_text(format_tracking_text("spx", txt, info), parse_mode=ParseMode.HTML)
            return
    update.message.reply_text("Gõ /help để xem lệnh.")

# ---------------- Register handlers if dispatcher available ----------------
if dispatcher:
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("help", help_cmd))
    dispatcher.add_handler(CommandHandler("track", track))
    dispatcher.add_handler(CommandHandler("check", check))
    dispatcher.add_handler(CommandHandler("list", list_tracks))
    dispatcher.add_handler(CommandHandler("remove", remove))
    dispatcher.add_handler(MessageHandler(Filters.text & (~Filters.command), echo_message))

# ---------------- Flask routes ----------------
@app.route("/")
def index():
    return "Shopee Tracker Bot (webhook) is running."

@app.route("/webhook", methods=["POST"])
def webhook():
    if not bot:
        return jsonify({"ok": False, "error": "Bot token not configured"}), 500
    try:
        update = Update.de_json(request.get_json(force=True), bot)
        dispatcher.process_update(update)
    except Exception as e:
        # return error for debugging
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True})

@app.route("/set_webhook", methods=["GET"])
def set_webhook():
    # optional convenience route to set webhook using WEBHOOK_URL env var
    if not bot:
        return "BOT_TOKEN not configured", 500
    url = WEBHOOK_URL or request.args.get("url")
    if not url:
        return "Provide WEBHOOK_URL env var or ?url=", 400
    hook = url.rstrip("/") + "/webhook"
    s = bot.set_webhook(hook)
    return f"set_webhook: {s} -> {hook}"

if __name__ == "__main__":
    # If WEBHOOK_URL provided at startup, attempt to set webhook (useful for Render)
    if bot and WEBHOOK_URL:
        try:
            hook = WEBHOOK_URL.rstrip("/") + "/webhook"
            bot.set_webhook(hook)
            print("Webhook set to", hook)
        except Exception as e:
            print("Failed to set webhook on startup:", e)
    # Run Flask (gunicorn will be used in Render)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))