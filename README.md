# CaptionGen Bot (Telegram)

بات آماده فروش کپشن‌های اختصاصی و اعتباری.  
- مدل درآمدی: «اعتبار» (هر تولید = ۱ اعتبار) + امکان پرداخت تلگرام یا کارت‌شارژ
- تکنولوژی: python-telegram-bot 21، OpenAI API

---

## 0) ساخت بات در BotFather
1. در تلگرام به @BotFather پیام دهید → `/newbot` → اسم و یوزرنیم را بسازید → **توکن** می‌دهد.
2. (اختیاری) پرداخت تلگرامی: در BotFather تنظیمات Provider را انجام دهید تا `PROVIDER_TOKEN` بگیرید.
3. آیدی عددی خود را با @userinfobot بردارید و در `ADMIN_ID` بگذارید.

> نکته: توکن‌ها را در چت منتشر نکنید؛ در `.env` بگذارید.

---

## 1) آماده‌سازی محلی (Polling)
```bash
cp .env.example .env
# مقداردهی متغیرها: TELEGRAM_BOT_TOKEN و OPENAI_API_KEY الزامی‌اند
pip install -r requirements.txt
python bot.py
```
- حالا در تلگرام /start را بزنید.

---

## 2) اجرای Webhook (برای سرور/کلاد)
- دامنه یا URL عمومی داشته باشید. در `.env` مقدار دهید:
```
MODE=webhook
WEBHOOK_URL=https://your-domain.com
WEBHOOK_PATH=/telegram/webhook
PORT=8080
```
- Docker:
```bash
docker compose up -d --build
```
- یا بدون Docker:
```bash
pip install -r requirements.txt
python bot.py
```

> کتابخانه خودش Webhook را ثبت می‌کند. مسیر وبهوک می‌شود: `${WEBHOOK_URL}${WEBHOOK_PATH}`

---

## 3) فروش اعتبار
- **کد شارژ**: به‌عنوان ادمین دستور ` /makecodes <credits> <count> ` را بزنید. کدها را بفروشید؛ کاربر «🎟️ شارژ با کد» را می‌زند.
- **پرداخت تلگرام**: اگر `PROVIDER_TOKEN` تنظیم باشد، دکمه «💳 خرید اعتبار» فعال می‌شود و پس از پرداخت اعتبار اضافه می‌شود.

---

## 4) متغیرهای محیطی مهم
- `TELEGRAM_BOT_TOKEN` ، `OPENAI_API_KEY` (اجباری)
- `PROVIDER_TOKEN` ، `CURRENCY` (اختیاری پرداخت)
- `ADMIN_ID` (برای دستورات ادمین)
- `MODE` = polling / webhook
- `WEBHOOK_URL`, `WEBHOOK_PATH`, `PORT`, `HOST` (برای webhook)

---

## 5) دستورات ادمین
- `/makecodes <credits> <count>` → ساخت کد شارژ
- `/adminstats` → آمار کاربران و خریدها

---

## 6) نکات استقرار سریع (Render/Railway)
- ریپوزیتوری را آپلود کنید.  
- متغیرهای محیطی را در داشبورد ست کنید.  
- `MODE=webhook` و `WEBHOOK_URL` را برابر با URL سرویس بگذارید (مثلا `https://your-service.onrender.com`).  
- پورت را 10000 بگذارید (در Render).
