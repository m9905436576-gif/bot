import telebot
from telebot import types
import random
import sqlite3
import os
import threading
from flask import Flask

# ======================== تنظیمات اولیه ========================
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8724613423:AAHMrCBnHfbA9TDy7cNtFmDhZQV4V_rLs40")
OWNER_ID = 8813403561  # آیدی مالک (دریافت اطلاعات برداشت)

bot = telebot.TeleBot(TOKEN)

# ======================== دیتابیس ========================
DB_NAME = 'game_data.db'

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    balance INTEGER DEFAULT 100
                )''')
    conn.commit()
    conn.close()

def get_user_balance(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT balance FROM users WHERE id=?', (user_id,))
    result = c.fetchone()
    conn.close()
    if result:
        return result[0]
    else:
        set_user_balance(user_id, 100)
        return 100

def set_user_balance(user_id, amount):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO users (id, balance) VALUES (?, ?)', (user_id, amount))
    conn.commit()
    conn.close()

def update_balance(user_id, delta):
    current = get_user_balance(user_id)
    new_balance = current + delta
    if new_balance < 0:
        new_balance = 0
    set_user_balance(user_id, new_balance)
    return new_balance

# ======================== وضعیت کاربران ========================
user_states = {}

def get_state(user_id):
    if user_id not in user_states:
        user_states[user_id] = {
            'state': 'main',
            'choice': None,
            'bet': 0,
            'bot_dice': None,
            'warn_count': 0,
        }
    return user_states[user_id]

# ======================== کیبوردها ========================
def main_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row('💰 موجودی', '🎮 شروع بازی')
    kb.row('💳 برداشت و شارژ')
    return kb

def game_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row('تاس فرد', 'تاس زوج')
    kb.row('انتخاب عدد', 'بازی با بات')
    kb.row('🔙 بازگشت به منو')
    return kb

def back_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row('🔙 بازگشت به منو')
    return kb

def number_picker_keyboard():
    kb = types.InlineKeyboardMarkup()
    buttons = [types.InlineKeyboardButton(str(i), callback_data=f'pick_{i}') for i in range(1, 7)]
    kb.add(*buttons[:3])
    kb.add(*buttons[3:])
    return kb

def roll_dice_button():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton('🎲 تاس بنداز', callback_data='roll_dice'))
    return kb

# ======================== دستورات مالک ========================
@bot.message_handler(commands=['increase_coins'])
def increase_coins(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "❌ شما دسترسی به این دستور ندارید.")
        return
    parts = message.text.split()
    if len(parts) != 3:
        bot.reply_to(message, "⚠️ فرمت صحیح:\n/increase_coins [آیدی کاربر] [مقدار]")
        return
    try:
        target_id = int(parts[1])
        amount = int(parts[2])
        if amount <= 0:
            bot.reply_to(message, "❌ مقدار باید مثبت باشد.")
            return
        new_bal = update_balance(target_id, amount)
        bot.reply_to(message, f"✅ {amount:,} کوین به کاربر با آیدی {target_id} اضافه شد.\nموجودی جدید: {new_bal:,}")
    except ValueError:
        bot.reply_to(message, "❌ آیدی و مقدار باید عددی باشند.")

@bot.message_handler(commands=['decrease_coins'])
def decrease_coins(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "❌ شما دسترسی به این دستور ندارید.")
        return
    parts = message.text.split()
    if len(parts) != 3:
        bot.reply_to(message, "⚠️ فرمت صحیح:\n/decrease_coins [آیدی کاربر] [مقدار]")
        return
    try:
        target_id = int(parts[1])
        amount = int(parts[2])
        if amount <= 0:
            bot.reply_to(message, "❌ مقدار باید مثبت باشد.")
            return
        new_bal = update_balance(target_id, -amount)
        bot.reply_to(message, f"✅ {amount:,} کوین از کاربر با آیدی {target_id} کم شد.\nموجودی جدید: {new_bal:,}")
    except ValueError:
        bot.reply_to(message, "❌ آیدی و مقدار باید عددی باشند.")

# ======================== استارت ========================
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    get_user_balance(user_id)
    state = get_state(user_id)
    state['state'] = 'main'
    bot.reply_to(message, "🎉 به ربات خوش آمدی!\nشما ۱۰۰ کوین هدیه دریافت کردید.", reply_markup=main_keyboard())

# ======================== هندلر متن ========================
@bot.message_handler(func=lambda m: True)
def handle_text(message):
    user_id = message.from_user.id
    state = get_state(user_id)
    text = message.text.strip()

    # --- اخطار برای عدم ارسال تاس در بازی با بات ---
    if state['state'] == 'waiting_user_dice_vs_bot' and text != '🔙 بازگشت به منو':
        state['warn_count'] += 1
        if state['warn_count'] >= 3:
            bot.reply_to(message, "⚠️ شما ۳ بار تاس ارسال نکردید! مبلغ شرط شما سوخت شد.", reply_markup=game_keyboard())
            state['state'] = 'game_menu'
            return
        else:
            bot.reply_to(message, f"⚠️ اخطار {state['warn_count']} از ۳: لطفاً تاس خود را با کلیک روی دکمه یا ارسال ایموجی 🎲 بیندازید.", reply_markup=roll_dice_button())
            return

    # ---------- منوی اصلی ----------
    if state['state'] == 'main':
        if text == '💰 موجودی':
            bal = get_user_balance(user_id)
            bot.reply_to(message, f"💵 موجودی شما: {bal:,} کوین", reply_markup=main_keyboard())

        elif text == '🎮 شروع بازی':
            state['state'] = 'game_menu'
            bot.reply_to(message, "🎲 یکی از گزینه‌های بازی رو انتخاب کن:", reply_markup=game_keyboard())

        elif text == '💳 برداشت و شارژ':
            state['state'] = 'withdraw_charge'
            kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
            kb.row('برداشت', 'شارژ')
            kb.row('🔙 بازگشت به منو')
            bot.reply_to(message, "💰 عملیات مدنظر را انتخاب کنید:", reply_markup=kb)

        else:
            bot.reply_to(message, "❌ لطفاً از دکمه‌های منو استفاده کن.", reply_markup=main_keyboard())

    # ---------- برداشت و شارژ ----------
    elif state['state'] == 'withdraw_charge':
        if text == 'برداشت':
            bal = get_user_balance(user_id)
            if bal >= 50000:
                new_bal = update_balance(user_id, -50000)
                state['state'] = 'waiting_card_info'
                bot.reply_to(message, f"✅ مبلغ ۵۰,۰۰۰ کوین از حساب شما کسر شد.\nموجودی جدید: {new_bal:,}\n\nلطفاً شماره کارت و نام خود را به صورت زیر وارد کنید:\nمثال:\n`6219...1...8..943\nعلی بابا خانی`", 
                             reply_markup=back_keyboard(), parse_mode='Markdown')
            else:
                bot.reply_to(message, "❌ موجودی شما کمتر از ۵۰,۰۰۰ کوین است. حداقل برداشت ۵۰,۰۰۰ کوین می‌باشد.", reply_markup=main_keyboard())
                state['state'] = 'main'

        elif text == 'شارژ':
            bot.reply_to(message, "به پیوی ویو مراجع کنید و یا اگر ریپ هستید به گپ ویو مراجع کنید", reply_markup=main_keyboard())
            state['state'] = 'main'

        elif text == '🔙 بازگشت به منو':
            state['state'] = 'main'
            bot.reply_to(message, "به منوی اصلی برگشتی.", reply_markup=main_keyboard())

        else:
            bot.reply_to(message, "❌ یکی از گزینه‌های برداشت یا شارژ رو انتخاب کن.")

    # ---------- دریافت اطلاعات کارت ----------
    elif state['state'] == 'waiting_card_info':
        if text == '🔙 بازگشت به منو':
            update_balance(user_id, 50000)
            state['state'] = 'main'
            bot.reply_to(message, "انصراف داده شد. مبلغ به حسابت برگشت.", reply_markup=main_keyboard())
            return

        try:
            bot.forward_message(OWNER_ID, message.chat.id, message.message_id)
            bot.reply_to(message, "✅ اطلاعات شما با موفقیت ارسال شد. در اسرع وقت بررسی می‌شود.", reply_markup=main_keyboard())
        except Exception as e:
            bot.reply_to(message, f"❌ خطا در ارسال اطلاعات. لطفاً دوباره تلاش کنید.\nخطا: {e}", reply_markup=main_keyboard())
        state['state'] = 'main'

    # ---------- منوی بازی ----------
    elif state['state'] == 'game_menu':
        if text == '🔙 بازگشت به منو':
            state['state'] = 'main'
            bot.reply_to(message, "به منوی اصلی برگشتی.", reply_markup=main_keyboard())

        elif text in ['تاس فرد', 'تاس زوج']:
            state['state'] = 'waiting_bet_odd_even'
            state['choice'] = 'odd' if text == 'تاس فرد' else 'even'
            bot.reply_to(message, f"🎯 {text} رو انتخاب کردی.\nحالا مبلغ شرط خود را به عدد وارد کن:", reply_markup=back_keyboard())

        elif text == 'انتخاب عدد':
            state['state'] = 'waiting_bet_pick'
            bot.reply_to(message, "🔢 یک عدد (۱ تا ۶) رو انتخاب کردی.\nمبلغ شرط را وارد کن:", reply_markup=back_keyboard())

        elif text == 'بازی با بات':
            state['state'] = 'waiting_bet_vs_bot'
            bot.reply_to(message, "🤖 حالت بازی با بات.\nمبلغ شرط را وارد کن:", reply_markup=back_keyboard())

        else:
            bot.reply_to(message, "❌ لطفاً از دکمه‌های بازی استفاده کن.")

    # ---------- فرد/زوج ----------
    elif state['state'] == 'waiting_bet_odd_even':
        if text == '🔙 بازگشت به منو':
            state['state'] = 'main'
            bot.reply_to(message, "انصراف داده شد.", reply_markup=main_keyboard())
            return

        if not text.isdigit() or int(text) <= 0:
            bot.reply_to(message, "❌ لطفاً یک عدد معتبر (بزرگتر از صفر) وارد کن.")
            return

        bet = int(text)
        bal = get_user_balance(user_id)
        if bet > bal:
            bot.reply_to(message, f"⚠️ موجودی شما کافی نیست! موجودی: {bal:,}", reply_markup=back_keyboard())
            return

        update_balance(user_id, -bet)
        sent_dice = bot.send_dice(message.chat.id, emoji='🎲')
        roll = sent_dice.dice.value

        is_odd = roll % 2 != 0
        user_won = (state['choice'] == 'odd' and is_odd) or (state['choice'] == 'even' and not is_odd)

        if user_won:
            win_amount = int(bet * 1.8)
            update_balance(user_id, win_amount)
            result_text = f"✅ تاس آمد: {roll} (فرد)" if is_odd else f"✅ تاس آمد: {roll} (زوج)"
            result_text += f"\n🎉 برداشتی! برد: {win_amount:,} کوین"
        else:
            result_text = f"❌ تاس آمد: {roll} (فرد)" if is_odd else f"❌ تاس آمد: {roll} (زوج)"
            result_text += f"\n💔 باختی! مبلغ شرط ({bet:,} کوین) از دست رفت."

        new_bal = get_user_balance(user_id)
        bot.reply_to(message, result_text + f"\n💰 موجودی جدید: {new_bal:,}", reply_markup=game_keyboard())
        state['state'] = 'game_menu'

    # ---------- انتخاب عدد (دریافت مبلغ) ----------
    elif state['state'] == 'waiting_bet_pick':
        if text == '🔙 بازگشت به منو':
            state['state'] = 'main'
            bot.reply_to(message, "انصراف داده شد.", reply_markup=main_keyboard())
            return

        if not text.isdigit() or int(text) <= 0:
            bot.reply_to(message, "❌ لطفاً یک عدد معتبر (بزرگتر از صفر) وارد کن.")
            return

        bet = int(text)
        bal = get_user_balance(user_id)
        if bet > bal:
            bot.reply_to(message, f"⚠️ موجودی شما کافی نیست! موجودی: {bal:,}", reply_markup=back_keyboard())
            return

        update_balance(user_id, -bet)
        state['bet'] = bet
        state['state'] = 'waiting_pick_number'
        bot.reply_to(message, "🎯 حالا عدد مدنظرت رو انتخاب کن (۱ تا ۶):", reply_markup=number_picker_keyboard())

    # ---------- بازی با بات (دریافت مبلغ) ----------
    elif state['state'] == 'waiting_bet_vs_bot':
        if text == '🔙 بازگشت به منو':
            state['state'] = 'main'
            bot.reply_to(message, "انصراف داده شد.", reply_markup=main_keyboard())
            return

        if not text.isdigit() or int(text) <= 0:
            bot.reply_to(message, "❌ لطفاً یک عدد معتبر (بزرگتر از صفر) وارد کن.")
            return

        bet = int(text)
        bal = get_user_balance(user_id)
        if bet > bal:
            bot.reply_to(message, f"⚠️ موجودی شما کافی نیست! موجودی: {bal:,}", reply_markup=back_keyboard())
            return

        update_balance(user_id, -bet)
        state['bet'] = bet
        state['warn_count'] = 0

        sent_dice = bot.send_dice(message.chat.id, emoji='🎲')
        bot_dice_value = sent_dice.dice.value
        state['bot_dice'] = bot_dice_value

        state['state'] = 'waiting_user_dice_vs_bot'
        bot.reply_to(message, f"🤖 تاس ربات: {bot_dice_value}\n\n🎲 حالا نوبت شماست! لطفاً تاس خود را با کلیک روی دکمه یا ارسال ایموجی 🎲 بیندازید.", 
                     reply_markup=roll_dice_button())

    else:
        bot.reply_to(message, "⚠️ دوباره از منو انتخاب کن.", reply_markup=main_keyboard())
        state['state'] = 'main'

# ======================== کالبک‌ها ========================
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    user_id = call.from_user.id
    state = get_state(user_id)
    data = call.data

    # ---------- انتخاب عدد ----------
    if data.startswith('pick_'):
        if state['state'] != 'waiting_pick_number':
            bot.answer_callback_query(call.id, "⏳ زمان انتخاب عدد گذشته، دوباره بازی رو شروع کن.")
            return

        picked_number = int(data.split('_')[1])
        bet = state['bet']

        sent_dice = bot.send_dice(call.message.chat.id, emoji='🎲')
        roll = sent_dice.dice.value

        if picked_number == roll:
            win_amount = int(bet * 4)
            update_balance(user_id, win_amount)
            result = f"🎯 عدد شما: {picked_number} | تاس آمد: {roll}\n🎉 برداشتی! برد: {win_amount:,} کوین"
        else:
            result = f"🎯 عدد شما: {picked_number} | تاس آمد: {roll}\n💔 باختی! مبلغ شرط ({bet:,} کوین) از دست رفت."

        state['state'] = 'game_menu'
        new_bal = get_user_balance(user_id)
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                              text=result + f"\n💰 موجودی جدید: {new_bal:,}")
        bot.send_message(call.message.chat.id, "🎮 منوی بازی:", reply_markup=game_keyboard())
        bot.answer_callback_query(call.id)

    # ---------- دکمه تاس بنداز ----------
    elif data == 'roll_dice':
        if state['state'] != 'waiting_user_dice_vs_bot':
            bot.answer_callback_query(call.id, "⏳ زمان تاس انداختن گذشته.")
            return

        sent_msg = bot.send_dice(call.message.chat.id, emoji='🎲')
        user_roll = sent_msg.dice.value
        bot_roll = state['bot_dice']
        bet = state['bet']

        if user_roll > bot_roll:
            win = int(bet * 2)
            update_balance(user_id, win)
            result = f"🎲 شما: {user_roll} | 🤖 ربات: {bot_roll}\n🎉 برداشتی! برد: {win:,} کوین"
        elif user_roll < bot_roll:
            result = f"🎲 شما: {user_roll} | 🤖 ربات: {bot_roll}\n💔 باختی! مبلغ شرط ({bet:,} کوین) از دست رفت."
        else:
            update_balance(user_id, bet)
            result = f"🎲 شما: {user_roll} | 🤖 ربات: {bot_roll}\n🤝 مساوی شد! مبلغ شرط به حسابت برگشت."

        state['state'] = 'game_menu'
        new_bal = get_user_balance(user_id)
        bot.send_message(call.message.chat.id, result + f"\n💰 موجودی جدید: {new_bal:,}", reply_markup=game_keyboard())
        bot.answer_callback_query(call.id)

# ======================== هندلر تاس ارسالی کاربر ========================
@bot.message_handler(content_types=['dice'])
def handle_user_dice(message):
    user_id = message.from_user.id
    state = get_state(user_id)

    if state['state'] == 'waiting_user_dice_vs_bot':
        user_roll = message.dice.value
        bot_roll = state['bot_dice']
        bet = state['bet']

        if user_roll > bot_roll:
            win = int(bet * 2)
            update_balance(user_id, win)
            result = f"🎲 شما: {user_roll} | 🤖 ربات: {bot_roll}\n🎉 برداشتی! برد: {win:,} کوین"
        elif user_roll < bot_roll:
            result = f"🎲 شما: {user_roll} | 🤖 ربات: {bot_roll}\n💔 باختی! مبلغ شرط ({bet:,} کوین) از دست رفت."
        else:
            update_balance(user_id, bet)
            result = f"🎲 شما: {user_roll} | 🤖 ربات: {bot_roll}\n🤝 مساوی شد! مبلغ شرط به حسابت برگشت."

        state['state'] = 'game_menu'
        new_bal = get_user_balance(user_id)
        bot.reply_to(message, result + f"\n💰 موجودی جدید: {new_bal:,}", reply_markup=game_keyboard())

# ======================== اجرای ربات و وب‌سرور ========================

if __name__ == '__main__':
    init_db()
    
    # --- راه‌اندازی Flask برای Render ---
    app = Flask(__name__)
    
    @app.route('/')
    def home():
        return "🤖 Telegram Dice Bot is running!"
    
    @app.route('/health')
    def health():
        return "OK", 200
    
    # --- اجرای ربات در یک ترد جداگانه ---
    def run_bot():
        print("🤖 ربات روشن شد...")
        bot.infinity_polling()
    
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    
    # --- اجرای Flask روی پورت مشخص شده توسط Render ---
    port = int(os.environ.get("PORT", 5000))
    print(f"🌐 Web server running on port {port}")
    app.run(host="0.0.0.0", port=port)