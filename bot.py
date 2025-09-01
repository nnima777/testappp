import os, sqlite3, string, random, datetime
from dotenv import load_dotenv
from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes, PreCheckoutQueryHandler
)

# ---------- Config ----------
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # required
PROVIDER_TOKEN = os.getenv("PROVIDER_TOKEN")  # optional (Telegram Payments)
CURRENCY = os.getenv("CURRENCY", "USD")       # change if needed

SIGNUP_BONUS = 3
CREDIT_COST_PACKS = [
    ("10 اعتبار", 10, 199_00),   # $1.99
    ("50 اعتبار", 50, 799_00),   # $7.99
    ("200 اعتبار", 200, 2499_00) # $24.99
]

# ---------- OpenAI ----------
from openai import OpenAI
oa = OpenAI(api_key=OPENAI_API_KEY)

# ---------- DB ----------
DB_PATH = "data.db"
os.makedirs(".", exist_ok=True)

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as conn:
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            credits INTEGER DEFAULT 0,
            referred_by INTEGER,
            created_at TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS codes(
            code TEXT PRIMARY KEY,
            credits INTEGER NOT NULL,
            used_by INTEGER,
            used_at TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS purchases(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            credits INTEGER,
            charge_id TEXT,
            created_at TEXT
        )""")
        conn.commit()

def user_get_or_create(u, referred_by=None):
    with db() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE user_id=?", (u.id,))
        row = c.fetchone()
        if row:
            return row
        c.execute("INSERT INTO users(user_id, username, credits, referred_by, created_at) VALUES(?,?,?,?,?)",
                  (u.id, u.username, SIGNUP_BONUS, referred_by, datetime.datetime.utcnow().isoformat()))
        conn.commit()
        return c.execute("SELECT * FROM users WHERE user_id=?", (u.id,)).fetchone()

def user_add_credits(uid: int, amount: int):
    with db() as conn:
        c = conn.cursor()
        c.execute("UPDATE users SET credits = COALESCE(credits,0) + ? WHERE user_id=?",(amount, uid))
        conn.commit()

def user_take_credit(uid: int) -> bool:
    with db() as conn:
        c = conn.cursor()
        c.execute("SELECT credits FROM users WHERE user_id=?", (uid,))
        row = c.fetchone()
        if not row or row["credits"] <= 0: return False
        c.execute("UPDATE users SET credits=credits-1 WHERE user_id=?", (uid,))
        conn.commit()
        return True

def make_codes(n=10, credits=10):
    import secrets, string as s
    codes = []
    with db() as conn:
        c = conn.cursor()
        for _ in range(n):
            code = ''.join(secrets.choice(s.ascii_uppercase + s.digits) for _ in range(10))
            c.execute("INSERT OR IGNORE INTO codes(code, credits) VALUES(?,?)", (code, credits))
            codes.append(code)
        conn.commit()
    return codes

def redeem_code(uid: int, code: str):
    with db() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM codes WHERE code=?", (code.strip().upper(),))
        row = c.fetchone()
        if not row: return False, "کد معتبر نیست."
        if row["used_by"]: return False, "این کد قبلاً استفاده شده است."
        c.execute("UPDATE codes SET used_by=?, used_at=? WHERE code=?",(uid, datetime.datetime.utcnow().isoformat(), row["code"]))
        c.execute("UPDATE users SET credits = COALESCE(credits,0) + ? WHERE user_id=?", (row["credits"], uid))
        conn.commit()
        return True, row["credits"]

# ---------- UI Helpers ----------
def main_menu(has_payments: bool):
    buttons = [
        [InlineKeyboardButton("📝 ساخت کپشن جدید", callback_data="gen:start")],
        [InlineKeyboardButton("👤 پروفایل", callback_data="profile")],
        [InlineKeyboardButton("🎟️ شارژ با کد", callback_data="redeem")],
    ]
    if has_payments:
        buttons.insert(1, [InlineKeyboardButton("💳 خرید اعتبار", callback_data="buy")])
    return InlineKeyboardMarkup(buttons)

def tone_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("صمیمی", callback_data="tone:friendly"),
         InlineKeyboardButton("حرفه‌ای", callback_data="tone:pro")],
        [InlineKeyboardButton("طنز/خلاق", callback_data="tone:funny"),
         InlineKeyboardButton("فروش‌محور", callback_data="tone:sales")]
    ])

# ---------- Prompts ----------
def build_prompt(desc: str, tone: str, lang: str = "FA"):
    tmap = {
        "friendly": "لحن صمیمی و دوستانه",
        "pro": "لحن حرفه‌ای و رسمی",
        "funny": "لحن خلاق و کمی طنز",
        "sales": "لحن فروش‌محور و قانع‌کننده"
    }
    style = tmap.get(tone, tmap["friendly"])
    if lang.upper() == "FA":
        system = "تو یک کپی‌رایتر فارسی‌زبان حرفه‌ای برای شبکه‌های اجتماعی هستی."
        user = f"""شرح پست/محصول:
{desc}

خروجی: 5 کپشن فارسی کوتاه و خوش‌خوان، هر کدام نهایتاً 2–3 خط، با {style}.
قوانین: هیچ ایموجی اجباری نیست؛ هشتگ‌های مرتبط در یک خط آخر هر کپشن؛ از تکرار پرهیز کن."""
    else:
        system = "You are a skilled social copywriter."
        user = f"""Brief:
{desc}

Output: 5 short captions in English (2–3 lines each), tone: {style}.
Rules: Relevant hashtags on last line; avoid repetition."""
    return system, user

async def generate_captions(desc: str, tone: str, lang: str = "FA"):
    system, user = build_prompt(desc, tone, lang)
    resp = oa.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role":"system","content":system},
                  {"role":"user","content":user}],
        temperature=0.8
    )
    text = resp.choices[0].message.content.strip()
    return text

# ---------- Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payload = (update.message.text or "").split(" ",1)
    ref_id = None
    if len(payload) > 1 and payload[1].startswith("ref_"):
        try: ref_id = int(payload[1].split("_",1)[1])
        except: pass
    u = user_get_or_create(update.effective_user, referred_by=ref_id)
    text = (
        "سلام! 👋\n"
        "من CaptionGen هستم؛ برات تو چند ثانیه کپشن حرفه‌ای می‌سازم.\n\n"
        f"🎁 هدیه شروع: {SIGNUP_BONUS} اعتبار به حسابت اضافه شد.\n"
        "هر بسته ۵ کپشن = ۱ اعتبار.\n"
        "برای شروع «ساخت کپشن جدید» رو بزن."
    )
    await update.message.reply_text(text, reply_markup=main_menu(has_payments=bool(PROVIDER_TOKEN)))

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db() as conn:
        c = conn.cursor()
        c.execute("SELECT credits, referred_by, created_at FROM users WHERE user_id=?", (update.effective_user.id,))
        row = c.fetchone()
    credits = row["credits"] if row else 0
    try:
        me = await context.bot.get_me()
        bot_username = me.username
    except Exception:
        bot_username = "YourBot"
    link = f"https://t.me/{bot_username}?start=ref_{update.effective_user.id}"
    txt = (f"👤 پروفایل شما\n"
           f"اعتبار فعلی: {credits}\n"
           f"لینک دعوت دوستان (اعتبار هدیه می‌گیرید):\n{link}")
    await update.callback_query.message.edit_text(txt, reply_markup=main_menu(has_payments=bool(PROVIDER_TOKEN)))

async def redeem_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.message.edit_text("کد شارژ رو ارسال کن (مثال: **AB12CD34EF**).")
    context.user_data["awaiting_redeem"] = True

async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("awaiting_redeem"):
        ok, val = redeem_code(update.effective_user.id, update.message.text.strip())
        if ok:
            await update.message.reply_text(f"✅ {val} اعتبار به حسابت اضافه شد.", reply_markup=main_menu(bool(PROVIDER_TOKEN)))
        else:
            await update.message.reply_text(f"❌ {val}")
        context.user_data["awaiting_redeem"] = False
        return

    if context.user_data.get("awaiting_desc"):
        context.user_data["desc"] = update.message.text.strip()
        context.user_data["awaiting_desc"] = False
        await update.message.reply_text("لحن دلخواه رو انتخاب کن:", reply_markup=tone_keyboard())
        return

    await update.message.reply_text("دستور نامعتبر. از منو استفاده کن 👇", reply_markup=main_menu(bool(PROVIDER_TOKEN)))

async def gen_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["awaiting_desc"] = True
    await update.callback_query.message.edit_text("توضیح کوتاه پست/محصولت رو بفرست (مثال: «کفش ورزشی مدل X برای دویدن…»).")

async def tone_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tone = update.callback_query.data.split(":",1)[1]
    desc = context.user_data.get("desc")
    if not desc:
        await update.callback_query.message.edit_text("اول توضیح پست رو بفرست. /start")
        return
    if not user_take_credit(update.effective_user.id):
        msg = "اعتبار کافی نداری. از «خرید اعتبار» یا «شارژ با کد» استفاده کن."
        await update.callback_query.message.edit_text(msg, reply_markup=main_menu(bool(PROVIDER_TOKEN)))
        return
    await update.callback_query.message.edit_text("⏳ در حال ساخت ۵ کپشن…")
    try:
        captions = await generate_captions(desc, tone, "FA")
        await update.callback_query.message.edit_text("✅ آماده شد:\n\n" + captions,
                                                      reply_markup=main_menu(bool(PROVIDER_TOKEN)))
    except Exception as e:
        user_add_credits(update.effective_user.id, 1)
        await update.callback_query.message.edit_text(f"خطا در تولید کپشن. دوباره تلاش کن.\n{e}")

# ---------- Payments (optional) ----------
async def buy_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not PROVIDER_TOKEN:
        await update.callback_query.message.edit_text(
            "پرداخت آنلاین فعلاً غیرفعاله. می‌تونی از فروشنده کد شارژ بخری و اینجا وارد کنی.",
            reply_markup=main_menu(False)
        )
        return
    kb = []
    for idx, (title, credits, price) in enumerate(CREDIT_COST_PACKS):
        kb.append([InlineKeyboardButton(f"{title} — {price/100:.2f} {CURRENCY}", callback_data=f"buy:{idx}")])
    kb.append([InlineKeyboardButton("بازگشت", callback_data="back")])
    await update.callback_query.message.edit_text("یکی از بسته‌های زیر رو انتخاب کن:", reply_markup=InlineKeyboardMarkup(kb))

async def buy_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not PROVIDER_TOKEN: return
    idx = int(update.callback_query.data.split(":",1)[1])
    title, credits, price = CREDIT_COST_PACKS[idx]
    payload = f"pack:{credits}:{price}"
    prices = [LabeledPrice(label=f"{title}", amount=price)]
    await context.bot.send_invoice(
        chat_id=update.effective_chat.id,
        title=f"خرید {title}",
        description=f"خرید {credits} اعتبار CaptionGen",
        payload=payload,
        provider_token=PROVIDER_TOKEN,
        currency=CURRENCY,
        prices=prices,
        need_name=False,
        need_phone_number=False,
        need_email=False,
        is_flexible=False
    )

async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)

async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payload = update.message.successful_payment.invoice_payload
    try:
        _, credits, price = payload.split(":")
        credits = int(credits); price = int(price)
        user_add_credits(update.effective_user.id, credits)
        with db() as conn:
            c = conn.cursor()
            c.execute("INSERT INTO purchases(user_id, credits, charge_id, created_at) VALUES(?,?,?,?)",
                      (update.effective_user.id, credits, update.message.successful_payment.provider_payment_charge_id, datetime.datetime.utcnow().isoformat()))
            conn.commit()
    except Exception:
        pass
    await update.message.reply_text(f"✅ پرداخت موفق. {credits} اعتبار به حسابت اضافه شد.", reply_markup=main_menu(bool(PROVIDER_TOKEN)))

# ---------- Admin ----------
def is_admin(uid: int) -> bool:
    admin_id = os.getenv("ADMIN_ID")
    try:
        return admin_id and int(admin_id) == uid
    except Exception:
        return False

async def admin_make_codes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        credits = int(context.args[0]); count = int(context.args[1])
    except:
        await update.message.reply_text("استفاده: /makecodes <credits> <count>")
        return
    codes = make_codes(count, credits)
    text = "کدها ساخته شد:\n" + "\n".join(codes) + "\n\nاین کدها رو بفروش و کاربر /redeem کنه."
    await update.message.reply_text(text)

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    with db() as conn:
        c = conn.cursor()
        u = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        p = c.execute("SELECT COUNT(*), COALESCE(SUM(credits),0) FROM purchases").fetchone()
    await update.message.reply_text(f"👥 کاربران: {u}\n🧾 خریدها: {p[0]}\n📦 مجموع اعتبارات فروخته‌شده: {p[1]}")

# ---------- Router ----------
async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = update.callback_query.data
    if data == "profile": return await profile(update, context)
    if data == "redeem": return await redeem_flow(update, context)
    if data == "gen:start": return await gen_start(update, context)
    if data.startswith("tone:"): return await tone_pick(update, context)
    if data == "buy": return await buy_menu(update, context)
    if data.startswith("buy:"): return await buy_invoice(update, context)
    if data == "back":
        await update.callback_query.message.edit_text("منوی اصلی:", reply_markup=main_menu(bool(PROVIDER_TOKEN)))

def build_app():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("makecodes", admin_make_codes))  # /makecodes 10 5
    app.add_handler(CommandHandler("adminstats", admin_stats))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    return app

if __name__ == "__main__":
    if not BOT_TOKEN or not OPENAI_API_KEY:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN and OPENAI_API_KEY in environment.")
    app = build_app()
    mode = os.getenv("MODE", "polling").lower()
    if mode == "webhook":
        port = int(os.getenv("PORT", "8080"))
        host = os.getenv("HOST", "0.0.0.0")
        webhook_url = os.getenv("WEBHOOK_URL")
        path = os.getenv("WEBHOOK_PATH", f"/{BOT_TOKEN}")
        if not webhook_url:
            raise SystemExit("MODE=webhook but WEBHOOK_URL is not set.")
        full_url = webhook_url.rstrip("/") + "/" + path.strip("/")
        print(f"Starting webhook on {host}:{port} -> {full_url}")
        app.run_webhook(listen=host, port=port, url_path=path.strip("/"), webhook_url=full_url)
    else:
        print("CaptionGen Bot is running in polling mode…")
        app.run_polling()
