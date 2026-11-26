# БоссVPN — Telegram-бот продажи VPN

Бот продаёт подписки VPN: тарифы, оплата по СБП, автоматическая выдача
VLESS-ключей из пула, «Моя подписка», статистика и управление ключами
(имя, описание, трафик) прямо через панель 3x-ui.

## Возможности

- 🛡 Тарифы: 1/3/12 месяцев с ценами из `core/config.py`
- 💳 Оплата по СБП с подтверждением админом
- 🔑 Выдача ключей из пула (один ключ — один клиент)
- 📊 «Моя подписка»: срок, ключ, израсходованный трафик с сервера
- ✏️ Управление ключами: имя, описание, трафик — в боте и из консоли
- ⚙️ Админка: заказы, статистика, остатки ключей

## Быстрый старт

```bash
pip install pillow

# 1. Создайте .env из примера
cp .env.example .env

# 2. Проверка логики без сети
python bot.py --selftest

# 3. Запуск
python bot.py
```

## Переменные окружения

```
BOT_TOKEN=токен_бота
ADMIN_IDS=id_админа
BRAND=БоссVPN
PAY_SBP=+7 900 000-00-00
PAY_NAME=Т-Банк
PANEL_URL=http://IP:порт/секретный_путь/
PANEL_USER=admin
PANEL_PASS=пароль_панели
```

`PANEL_*` — доступ к панели 3x-ui, чтобы показывать трафик и менять
имена/описания клиентов. Без них бот работает, но без статистики ключей.

## Управление

```bash
python admin.py keys --plan m1 --items "vless://...","vless://..."
python admin.py list
python admin.py orders
python admin.py stats
python admin.py confirm <order_id>

python keys.py traffic
python keys.py rename <uuid> "Новое имя"
python keys.py comment <uuid> "Описание"
```

## Структура

```
bossvpn-bot/
├─ bot.py          логика бота и selftest
├─ admin.py        заказы, ключи, статистика
├─ keys.py         трафик и управление ключами
├─ brand.py        генератор аватара, баннера, промо и карточек тарифов
├─ core/
│  ├─ config.py    настройки и тарифы
│  ├─ storage.py   SQLite: пользователи, заказы, пул ключей
│  ├─ server.py    клиент панели 3x-ui
│  └─ keyboards.py кнопки и тексты
└─ vpn_brand/      аватар, баннер, промо
   ├─ src/         фоны-заготовки для brand.py
   └─ fonts/       шрифты Unbounded и Manrope (OFL)
```

## Картинки

```bash
python brand.py   # перерисует vpn_brand/*.png по ценам из core/config.py
```

## Безопасность

- `.env` с токеном и паролем панели **не коммитится**.
- База `data/vpn.db` с заказами — тоже в `.gitignore`.
- Если токен бота или пароль панели засветились — поменяйте оба.
