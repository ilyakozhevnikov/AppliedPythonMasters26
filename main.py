import telebot
import requests

API_TOKEN = "TOKEN"

bot = telebot.TeleBot(API_TOKEN)

users = {}
user_states = {}
food_wait = {}

STEPS = ["weight", "height", "age", "activity", "city", "calorie_goal"]


@bot.message_handler(commands=["start"])
def set_profile(message):
    user_id = message.from_user.id
    bot.send_message(message.chat.id, "Привет! Я Зожик!")

@bot.message_handler(commands=["set_profile"])
def set_profile(message):
    user_id = message.from_user.id

    users[user_id] = {
        "logged_water": 0,
        "logged_calories": 0,
        "burned_calories": 0
    }

    user_states[user_id] = "weight"
    bot.send_message(message.chat.id, "Введите ваш вес (в кг):")


@bot.message_handler(func=lambda m: m.from_user.id in user_states)
def profile_steps(message):
    user_id = message.from_user.id
    step = user_states[user_id]
    text = message.text.strip()

    if step == "weight":
        users[user_id]["weight"] = float(text)
        user_states[user_id] = "height"
        bot.send_message(message.chat.id, "Введите ваш рост (в см):")

    elif step == "height":
        users[user_id]["height"] = float(text)
        user_states[user_id] = "age"
        bot.send_message(message.chat.id, "Введите ваш возраст:")

    elif step == "age":
        users[user_id]["age"] = int(text)
        user_states[user_id] = "activity"
        bot.send_message(message.chat.id, "Сколько минут активности в день?")

    elif step == "activity":
        users[user_id]["activity"] = int(text)
        user_states[user_id] = "city"
        bot.send_message(message.chat.id, "В каком городе вы находитесь?")

    elif step == "city":
        users[user_id]["city"] = text
        user_states[user_id] = "calorie_goal"
        bot.send_message(
            message.chat.id,
            "Введите цель калорий или напишите 'auto' для расчёта:"
        )

    elif step == "calorie_goal":
        if text.lower() == "auto":
            users[user_id]["calorie_goal"] = calculate_calories(users[user_id])
        else:
            users[user_id]["calorie_goal"] = int(text)

        users[user_id]["water_goal"] = calculate_water(users[user_id])
        user_states.pop(user_id)

        bot.send_message(message.chat.id, "Профиль сохранён ✅\n\n" + profile_text(users[user_id]))

def calculate_water(user):
    base = user["weight"] * 30
    activity_bonus = (user["activity"] // 30) * 500

    heat_bonus = 0
    temp = get_temperature(user["city"])
    if temp and temp > 25:
        heat_bonus = 700

    return int(base + activity_bonus + heat_bonus)


def calculate_calories(user):
    bmr = 10 * user["weight"] + 6.25 * user["height"] - 5 * user["age"]

    if user["activity"] < 30:
        bonus = 200
    elif user["activity"] < 60:
        bonus = 300
    else:
        bonus = 400

    return int(bmr + bonus)


def get_temperature(city):
    return -20 # Сейчас в Москве -20


def profile_text(u):
    return (
        f"Вес: {u['weight']} кг\n"
        f"Рост: {u['height']} см\n"
        f"Возраст: {u['age']}\n"
        f"Активность: {u['activity']} мин\n"
        f"Город: {u['city']}\n\n"
        f"Норма воды: {u['water_goal']} мл\n"
        f"Норма калорий: {u['calorie_goal']} ккал"
    )

@bot.message_handler(commands=["log_water"])
def log_water(message):
    user_id = message.from_user.id

    if user_id not in users:
        bot.send_message(message.chat.id, "Сначала настрой профиль через /set_profile")
        return

    try:
        amount = int(message.text.split()[1])
    except:
        bot.send_message(message.chat.id, "Используй: /log_water 250")
        return

    users[user_id]["logged_water"] += amount

    left = users[user_id]["water_goal"] - users[user_id]["logged_water"]

    bot.send_message(
        message.chat.id,
        f"💧 Записано: {amount} мл\n"
        f"Всего выпито: {users[user_id]['logged_water']} мл\n"
        f"Осталось: {max(left, 0)} мл"
    )


@bot.message_handler(commands=["log_food"])
def log_food(message):
    user_id = message.from_user.id

    if user_id not in users:
        bot.send_message(message.chat.id, "Сначала настрой профиль через /set_profile")
        return

    try:
        product = " ".join(message.text.split()[1:])
    except:
        bot.send_message(message.chat.id, "Используй: /log_food банан")
        return

    data = search_food(product)

    if not data:
        bot.send_message(message.chat.id, "Продукт не найден 😕")
        return

    food_wait[user_id] = data

    bot.send_message(
        message.chat.id,
        f"{data['name']} — {data['calories']} ккал на 100 г.\nСколько грамм вы съели?"
    )


@bot.message_handler(func=lambda m: m.from_user.id in food_wait)
def food_weight(message):
    user_id = message.from_user.id

    grams = float(message.text)
    data = food_wait[user_id]

    calories = grams * data["calories"] / 100
    users[user_id]["logged_calories"] += calories

    food_wait.pop(user_id)

    bot.send_message(
        message.chat.id,
        f"Записано: {int(calories)} ккал.\n"
        f"Всего потреблено: {int(users[user_id]['logged_calories'])} ккал"
    )


def search_food(name):
    url = f"https://world.openfoodfacts.org/cgi/search.pl?action=process&search_terms={name}&json=true"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        products = data.get('products', [])
        if products:  # Проверяем, есть ли найденные продукты
            first_product = products[0]
            return {
                'name': first_product.get('product_name', 'Неизвестно'),
                'calories': first_product.get('nutriments', {}).get('energy-kcal_100g', 0)
            }
        return None
    print(f"Ошибка: {response.status_code}")
    return None
    # try:
    #     return {"name": name, "calories": PRODUCT_X_CALORIES[name]}
    # except:
    #     return None


@bot.message_handler(commands=["log_workout"])
def log_workout(message):
    user_id = message.from_user.id

    if user_id not in users:
        bot.send_message(message.chat.id, "Сначала настрой профиль через /set_profile")
        return

    try:
        _, wtype, minutes = message.text.split()
        minutes = int(minutes)
    except:
        bot.send_message(message.chat.id, "Используй: /log_workout бег 30")
        return

    kcal = workout_calories(wtype, minutes)
    water_bonus = (minutes // 30) * 200

    users[user_id]["burned_calories"] += kcal
    users[user_id]["water_goal"] += water_bonus

    bot.send_message(
        message.chat.id,
        f"🏃 {wtype.capitalize()} {minutes} мин — {kcal} ккал.\n"
        f"Дополнительно выпейте {water_bonus} мл воды."
    )


def workout_calories(wtype, minutes):
    rates = {
        "бег": 10,
        "ходьба": 5,
        "велосипед": 8,
        "плавание": 9,
        "зал": 7
    }

    rate = rates.get(wtype.lower(), 6)
    return int(rate * minutes)


@bot.message_handler(commands=["check_progress"])
def check_progress(message):
    user_id = message.from_user.id

    if user_id not in users:
        bot.send_message(message.chat.id, "Сначала настрой профиль через /set_profile")
        return

    u = users[user_id]

    water_left = u["water_goal"] - u["logged_water"]
    cal_balance = u["logged_calories"] - u["burned_calories"]

    text = (
        "📊 Прогресс:\n\n"
        "Вода:\n"
        f"- Выпито: {u['logged_water']} мл из {u['water_goal']} мл\n"
        f"- Осталось: {max(water_left, 0)} мл\n\n"
        "Калории:\n"
        f"- Потреблено: {int(u['logged_calories'])} ккал из {u['calorie_goal']} ккал\n"
        f"- Сожжено: {u['burned_calories']} ккал\n"
        f"- Баланс: {int(cal_balance)} ккал"
    )

    bot.send_message(message.chat.id, text)


print("Bot is running...")
bot.infinity_polling()
