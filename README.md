# AmoCRM ↔ Google Sheets Integration

## Описание проекта

**AmoCRM-GSheets-Integration** — это FastAPI-сервис, обеспечивающий автоматическую **двустороннюю синхронизацию** данных
между Google Sheets и AmoCRM.

### Основные возможности:

- **Автоматическое создание контактов и сделок** в AmoCRM при добавлении строк в Google Sheets
- **Обновление данных в таблице** при изменении сделок в AmoCRM
- **Защита от дубликатов** с помощью Redis-блокировок
- **Умный поиск контактов** по email, телефону и имени
- **Автоимпорт существующих строк** при старте приложения
- **Rate limiting** для защиты от превышения лимитов API
- **Retry-механизмы** для надежности при сетевых ошибках

### Как это работает:

1. **Google Sheets → AmoCRM:**
    - Пользователь добавляет/редактирует строку в таблице
    - Google Apps Script отправляет webhook на сервер
    - Сервер создает/обновляет контакт и сделку в AmoCRM
    - ID сделки и ссылка записываются обратно в таблицу

2. **AmoCRM → Google Sheets:**
    - Менеджер меняет сделку в AmoCRM (статус, бюджет)
    - AmoCRM отправляет webhook на сервер
    - Сервер обновляет соответствующую строку в таблице

---

## Архитектура проекта

### Структура каталогов

```
amocrm-gsheets-integration/
├── app/
│   ├── __init__.py
│   ├── main.py                    # Точка входа приложения, запуск FastAPI
│   │
│   ├── api/                       # API endpoints (вебхуки)
│   │   ├── __init__.py
│   │   ├── health.py              # Health check endpoint
│   │   ├── webhook_amocrm.py      # POST /webhook/amocrm
│   │   └── webhook_sheets.py      # POST /webhook/sheets
│   │
│   ├── core/                      # Низкоуровневые клиенты и утилиты
│   │   ├── __init__.py
│   │   ├── settings.py            # Конфигурация (Pydantic Settings)
│   │   ├── amocrm_client.py       # Клиент для AmoCRM API
│   │   ├── sheets_client.py       # Клиент для Google Sheets API
│   │   ├── sync_lock.py           # Redis-блокировки для защиты от гонок
│   │   └── utils.py               # Вспомогательные функции (normalize_phone, make_external_id)
│   │
│   ├── services/                  # Бизнес-логика
│   │   ├── __init__.py
│   │   ├── amocrm_service.py      # Обработка вебхуков от AmoCRM
│   │   ├── sheets_service.py      # Обработка вебхуков от Google Sheets
│   │   └── import_service.py      # Автоимпорт существующих строк при старте
│   │
│   └── models/                    # Pydantic модели
│       ├── __init__.py
│       └── webhook_row.py         # Модель данных вебхука
│
├── scripts/
│   └── apps_script.js             # Google Apps Script для отправки вебхуков
│
├── secrets/
│   └── *.json                     # Секреты Google Service Account (не коммитится)
│
├── tests/                         # Тесты (pytest)
│   ├── __init__.py
│   └── test_utils.py
│
├── .env                           # Переменные окружения (не коммитится)
├── .pylintrc                      # Конфигурация Pylint
├── docker-compose.yml             # Docker Compose для Redis
├── Makefile                       # Команды для форматирования и линтинга
├── pyproject.toml                 # Poetry зависимости
└── README.md                      # Эта документация
```

### Описание модулей

#### `app/main.py`

**Назначение:** Главный файл приложения

- Инициализация FastAPI
- Подключение роутеров (`/webhook/sheets`, `/webhook/amocrm`, `/health`)
- Настройка логирования
- **Автоимпорт строк** при старте (`import_existing_rows()`)
- Обработка событий startup/shutdown

#### `app/api/webhook_sheets.py`

**Назначение:** Обработка вебхуков от Google Sheets

- Эндпоинт `POST /webhook/sheets`
- Валидация секрета (`X-Webhook-Secret`)
- Парсинг входящих данных (Pydantic модель `WebhookRow`)
- Передача в `sheets_service.process_webhook_sheets()`

#### `app/api/webhook_amocrm.py`

**Назначение:** Обработка вебхуков от AmoCRM

- Эндпоинт `POST /webhook/amocrm`
- Парсинг `application/x-www-form-urlencoded` формата AmoCRM
- Извлечение данных об обновлении сделок (`leads[update]`)
- Передача в `amocrm_service.process_webhook_amocrm()`

#### `app/services/sheets_service.py`

**Назначение:** Бизнес-логика обработки изменений в Google Sheets

**Ключевые функции:**

- `process_webhook_sheets()` — точка входа для вебхука
- `_process_webhook_sheets_internal()` — основная логика:
    - Проверка блокировки синхронизации (защита от циклов)
    - Чтение текущей строки из таблицы
    - Проверка Redis-блокировки создания сделки
    - **Ожидание 3 секунды** и повторное чтение (если сделка создается)
    - Создание/обновление контакта (`upsert_contact`)
    - Создание/обновление сделки (`upsert_lead`)
    - Запись результата обратно в таблицу

**Защита от дубликатов:**

- Гибридная Redis-блокировка `creating_lead:{row_index}` (TTL=10 сек)
- Если `amo_deal_id` уже есть — обновление вместо создания

#### `app/services/amocrm_service.py`

**Назначение:** Обработка вебхуков от AmoCRM

**Ключевые функции:**

- `process_webhook_amocrm()` — точка входа
- Извлечение `lead_id` из обновлений
- Поиск строки в таблице по `amo_deal_id`
- Получение актуальных данных о сделке и контакте из AmoCRM
- **Установка блокировки синхронизации** перед записью в таблицу
- Обновление строки с новыми данными (`name`, `budget`, `status`, `phone`, `email`)

#### `app/services/import_service.py`

**Назначение:** Автоимпорт существующих строк при старте

**Ключевые функции:**

- `import_existing_rows()` — читает все строки без `amo_deal_id`
- **Семафор** `asyncio.Semaphore(2)` — ограничение параллелизма (максимум 2 строки одновременно)
- Создание контактов и сделок для каждой строки
- Запись результата в таблицу

**Защита от rate limiting:** Обработка не более 2 строк параллельно предотвращает превышение лимитов AmoCRM API (429 Too
Many Requests).

#### `app/core/amocrm_client.py`

**Назначение:** Клиент для работы с AmoCRM API

**Ключевые методы:**

- `find_contact()` — поиск контакта по email/телефону/имени
- `upsert_contact()` — создание или обновление контакта
- `create_lead()` — создание новой сделки
- `upsert_lead()` — создание или обновление сделки
- `get_lead_info()` — получение информации о сделке
- `get_contact_info()` — получение информации о контакте
- `lead_link()` — генерация ссылки на сделку

**Особенности:**

- Все синхронные вызовы обернуты в `asyncio.to_thread()` для неблокирующей работы
- Retry-механизм с экспоненциальной задержкой (`@retry` от `tenacity`)
- Умный поиск контактов: сначала по email (более уникальный), затем по телефону

#### `app/core/sheets_client.py`

**Назначение:** Клиент для работы с Google Sheets API

**Ключевые методы:**

- `read_all_rows()` — чтение всех строк таблицы
- `update_cells()` — обновление ячеек в строке
- `find_row_by_deal_id()` — поиск строки по `amo_deal_id`

**Особенности:**

- Использует `gspread` библиотеку
- Все операции обернуты в `asyncio.to_thread()`
- Thread-safe инициализация клиента (`threading.Lock`)

#### `app/core/sync_lock.py`

**Назначение:** Redis-блокировки для защиты от гонок и циклов

**Ключевые методы:**

- `set_amocrm_to_sheets_lock(row_index, ttl=5)` — установка блокировки при записи из AmoCRM в Sheets
- `check_amocrm_to_sheets_lock(row_index)` — проверка блокировки при записи из Sheets в AmoCRM
- `_get_client()` — ленивая инициализация Redis клиента с `asyncio.Lock`

**Как работает защита от циклов:**

1. AmoCRM отправляет вебхук → сервер устанавливает блокировку → пишет в таблицу
2. Google Sheets отправляет вебхук → сервер проверяет блокировку → пропускает обработку
3. Через 5 секунд блокировка истекает → следующие изменения обрабатываются нормально

#### `app/core/settings.py`

**Назначение:** Конфигурация приложения

- Загрузка переменных из `.env` через `pydantic-settings`
- Валидация обязательных параметров
- Значения по умолчанию для необязательных полей

#### `app/core/utils.py`

**Назначение:** Вспомогательные функции

- `normalize_phone(phone)` — нормализация номера телефона (добавление `+`)
- `make_external_id(phone, email)` — генерация уникального ID строки (MD5 hash)

---

## Используемые технологии

### Backend

| Технология   | Версия | Назначение                   |
|--------------|--------|------------------------------|
| **Python**   | 3.13+  | Основной язык                |
| **FastAPI**  | 0.120+ | Web framework для REST API   |
| **Uvicorn**  | 0.38+  | ASGI сервер                  |
| **Pydantic** | 2.11+  | Валидация данных и настройки |
| **Redis**    | 7.0+   | Синхронизационные блокировки |
| **asyncio**  | stdlib | Асинхронное программирование |

### Интеграции

| Сервис                | Библиотека          | Назначение                           |
|-----------------------|---------------------|--------------------------------------|
| **Google Sheets API** | `gspread` 6.2+      | Чтение/запись таблиц                 |
| **Google Auth**       | `google-auth` 2.42+ | Аутентификация через Service Account |
| **AmoCRM API v2**     | `amocrm-api` 2.6+   | Работа с контактами и сделками       |

### Вспомогательные библиотеки

- **tenacity** — Retry-механизмы для устойчивости к сетевым ошибкам
- **python-dotenv** — Загрузка переменных из `.env`
- **aiohttp** — HTTP-клиент (зависимость `amocrm-api`)

### Dev Tools

- **Black** — Форматирование кода
- **isort** — Сортировка импортов
- **Flake8** — Линтер (стиль кода)
- **Pylint** — Статический анализ кода
- **MyPy** — Проверка типов
- **Pytest** — Тестирование

### Infrastructure

- **Docker / Docker Compose** — Контейнеризация (Redis)
- **Poetry** — Управление зависимостями
- **Makefile** — Автоматизация команд

---

## Установка и запуск

### Предварительные требования

- Python 3.13+
- Redis 7.0+ (локально или Docker)
- Google Cloud Service Account с доступом к Google Sheets API
- AmoCRM аккаунт с настроенной интеграцией

### Шаг 1: Клонирование репозитория

```bash
git clone https://github.com/ZhulikovN/amocrm-gsheets-integration
```

### Шаг 2: Установка зависимостей

```bash
poetry install

poetry shell
```

### Шаг 3: Запуск Redis

```bash
docker-compose up -d
```

### Шаг 4: Настройка переменных окружения

Создайте файл `.env` в корне проекта:

### Шаг 5: Настройка Google Service Account

1. Перейдите в [Google Cloud Console](https://console.cloud.google.com/)
2. Создайте новый проект (или выберите существующий)
3. Включите **Google Sheets API**
4. Создайте Service Account:
    - IAM & Admin → Service Accounts → Create Service Account
    - Скачайте JSON-ключ
5. Сохраните JSON в `secrets/`
6. **Дайте доступ Service Account к таблице:**
    - Откройте вашу Google Таблицу
    - Нажмите "Поделиться"
    - Добавьте email Service Account (из JSON: `client_email`)
    - Права: "Редактор"

### Шаг 6: Настройка AmoCRM

1. Создайте интеграцию в AmoCRM:
    - Настройки → Интеграции → Создать интеграцию
    - Скопируйте `Client ID` и `Client Secret`
    - Укажите `Redirect URI` (например, `https://example.com/oauth/callback`)
    - Получите `Authorization Code` (код авторизации) из настроек интеграции

2. Скопируйте значения в `.env`:
    - `AMO_CLIENT_ID` — Client ID интеграции
    - `AMO_CLIENT_SECRET` — Client Secret интеграции
    - `AMO_AUTH_CODE` — Authorization Code интеграции
    - `AMO_BASE_URL` — URL вашего аккаунта AmoCRM (из "Основные настройки" → "Заголовок")
    - `AMO_REDIRECT_URI` — тот же Redirect URI, что указали при создании интеграции
    - `AMO_PIPELINE_ID` — ID воронки, где будут создаваться сделки
    - `AMO_STATUS_ID` — ID статуса "Новая заявка" в воронке

3. **Токены создадутся автоматически при первом запуске:**
    - При запуске приложения функция `init_token_manager()` использует `AMO_AUTH_CODE` для получения токенов
    - Токены сохранятся в директории `.amocrm_tokens/`:
        - `access_token.txt`
        - `refresh_token.txt`
    - В дальнейшем приложение будет автоматически обновлять токены через Refresh Token

4. Настройте webhook в AmoCRM:
    - Настройки → Вебхуки → Добавить вебхук
    - URL: `https://your-domain.com/webhook/amocrm`
    - События: "Обновление сделки" (`leads[update]`)

### Шаг 7: Настройка Google Apps Script

1. Откройте вашу Google Таблицу
2. Расширения → Apps Script
3. Вставьте код из `scripts/apps_script.js`:

```javascript
const WEBHOOK_URL = "https://your-domain.com/webhook/sheets";
const WEBHOOK_SECRET = "your-super-secret-key-here";

function handleEdit(e) {
    try {
        if (!e || !e.range) {
            Logger.log("Событие не содержит range");
            return;
        }

        Utilities.sleep(3000)

        const sheet = e.source.getActiveSheet();
        const row = e.range.getRow();
        if (row === 1) return;

        const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
        const values = sheet.getRange(row, 1, 1, sheet.getLastColumn()).getValues()[0];

        const data = {};
        headers.forEach((header, i) => {
            data[header.trim().toLowerCase()] = values[i] ?? "";
        });

        const name = data.name || "";
        const phone = String(data.phone || "");
        const email = String(data.email || "");
        const budget = parseFloat(data.budget) || 0;
        const amoDealId = String(data.amo_deal_id || "");

        if (!name && !phone && !email) {
            Logger.log(`Пустая строка ${row} — пропуск`);
            return;
        }

        const payload = {
            row_index: row,
            data: {
                name,
                phone,
                email,
                budget,
                amo_deal_id: amoDealId,
                external_id: null
            }
        };

        const options = {
            method: "post",
            contentType: "application/json",
            headers: {
                "X-Webhook-Secret": WEBHOOK_SECRET
            },
            payload: JSON.stringify(payload),
            muteHttpExceptions: true
        };

        const response = UrlFetchApp.fetch(WEBHOOK_URL, options);
        const code = response.getResponseCode();
        const text = response.getContentText();

        if (code >= 200 && code < 300) {
            Logger.log(`Вебхук успешно отправлен для строки ${row}: ${code}`);
        } else {
            Logger.log(`Ошибка при отправке строки ${row}: ${code} ${text}`);
        }

    } catch (err) {
        Logger.log(`Exception: ${err.message}`);
    }
}
```

4. Триггеры → Добавить триггер:
    - Функция: `handleEdit`
    - События: "При Редактирование"
    - Сохранить

### Шаг 8: Запуск приложения

```bash
uvicorn app.main:app --reload --port 8000
```

Приложение будет доступно по адресу: `http://localhost:8080`

### Шаг 9: Проверка работоспособности

```bash
# Health check
curl http://localhost:8080/health

# Должен вернуть:
# {"status": "healthy"}
```

## Логика синхронизации

### Жизненный цикл данных

```
┌─────────────────────────────────────────────────────────────────────┐
│                     GOOGLE SHEETS → AmoCRM                          │
└─────────────────────────────────────────────────────────────────────┘

1. Пользователь редактирует строку в Google Sheets
   │
   ├─> Google Apps Script перехватывает событие onEdit
   │
   ├─> Debounce: ждет 3 секунды (объединение быстрых правок)
   │
   ├─> POST /webhook/sheets
   │   Headers: X-Webhook-Secret
   │   Body: { row_index, data: { name, phone, email, budget, ... } }
   │
   └─> FastAPI endpoint (webhook_sheets.py)
       │
       ├─> Валидация секрета
       │
       └─> sheets_service.process_webhook_sheets()
           │
           ├─> Проверка sync_lock (защита от циклов)
           │   ├─> Если блокировка активна → SKIP (недавно обновлено из AmoCRM)
           │   └─> Иначе → продолжить
           │
           ├─> Чтение текущей строки из Google Sheets
           │   └─> Извлечение existing_lead_id, existing_contact_id
           │
           ├─> Проверка Redis-блокировки creating_lead:{row_index}
           │   ├─> Если заблокировано → WAIT 3 сек → перечитать таблицу
           │   │   ├─> amo_deal_id появился → продолжить как UPDATE
           │   │   └─> amo_deal_id не появился → SKIP
           │   └─> Иначе → установить блокировку (TTL=10 сек)
           │
           ├─> Upsert контакта в AmoCRM
           │   ├─> find_contact(email, phone, name)
           │   │   ├─> Поиск по email (более уникальный)
           │   │   └─> Поиск по телефону (если email не нашелся)
           │   └─> update_contact() или create_contact()
           │
           ├─> Upsert сделки в AmoCRM
           │   ├─> Если existing_lead_id → update_lead()
           │   └─> Иначе → create_lead()
           │
           ├─> Получить актуальный статус сделки
           │   └─> get_lead_info(lead_id) → status_name
           │
           ├─> Записать обратно в Google Sheets:
           │   └─> { amo_deal_id, amo_contact_id, amo_link, status, external_id }
           │
           └─> Снять блокировку creating_lead:{row_index}

┌─────────────────────────────────────────────────────────────────────┐
│                      AmoCRM → GOOGLE SHEETS                         │
└─────────────────────────────────────────────────────────────────────┘

1. Менеджер обновляет сделку в AmoCRM (статус, бюджет, ...)
   │
   ├─> AmoCRM отправляет webhook
   │
   ├─> POST /webhook/amocrm
   │   Content-Type: application/x-www-form-urlencoded
   │   Body: leads[update][0][id]=12345&leads[update][0][status_id]=...
   │
   └─> FastAPI endpoint (webhook_amocrm.py)
       │
       ├─> Парсинг form data
       │
       └─> amocrm_service.process_webhook_amocrm()
           │
           ├─> Извлечение lead_id из leads[update]
           │
           ├─> Поиск строки в Google Sheets по amo_deal_id
           │   └─> sheets_client.find_row_by_deal_id(lead_id)
           │
           ├─> Получение актуальных данных из AmoCRM:
           │   ├─> get_lead_info(lead_id) → name, budget, status_name, contact_id
           │   └─> get_contact_info(contact_id) → phone, email
           │
           ├─> Установка блокировки синхронизации (TTL=5 сек)
           │   └─> sync_lock.set_amocrm_to_sheets_lock(row_index)
           │
           ├─> Обновление строки в Google Sheets:
           │   └─> { name, budget, status, phone, email }
           │
           └─> Блокировка автоматически истекает через 5 секунд
               └─> Следующие изменения в таблице будут обрабатываться нормально
```

## Конфигурация

### Переменные окружения (.env)

Все конфигурации задаются через переменные окружения. Полный список:

#### Google Sheets

| Переменная                    | Обязательно | Описание                        | Пример                 |
|-------------------------------|-------------|---------------------------------|------------------------|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Да          | Путь к JSON сервисного аккаунта | `./secrets/sa.json`    |
| `GOOGLE_SPREADSHEET_ID`       | Да          | ID таблицы (из URL)             | `1AbC...xyz`           |
| `GOOGLE_WORKSHEET_NAME`       | Нет         | Название листа                  | `Лист1` (по умолчанию) |

#### AmoCRM

| Переменная          | Обязательно | Описание                                                                       | Пример                               |
|---------------------|-------------|--------------------------------------------------------------------------------|--------------------------------------|
| `AMO_BASE_URL`      | Да          | URL аккаунта AmoCRM (из "Основные настройки" → "Заголовок")                    | `https://yoursubdomain.amocrm.ru`    |
| `AMO_CLIENT_ID`     | Да          | Client ID интеграции (из настроек интеграции)                                  | `xxxxxxxx-xxxx-xxxx-xxxx-...`        |
| `AMO_CLIENT_SECRET` | Да          | Client Secret интеграции (из настроек интеграции)                              | `YourClientSecretHere`               |
| `AMO_REDIRECT_URI`  | Да          | Redirect URI, указанный при создании интеграции                                | `https://example.com/oauth/callback` |
| `AMO_AUTH_CODE`     | Да          | Authorization Code (код авторизации из настроек интеграции)                    | `def502...`                          |
| `AMO_ACCESS_TOKEN`  | Нет         | Access Token (создается автоматически при первом запуске в `.amocrm_tokens/`)  | -                                    |
| `AMO_REFRESH_TOKEN` | Нет         | Refresh Token (создается автоматически при первом запуске в `.amocrm_tokens/`) | -                                    |
| `AMO_PIPELINE_ID`   | Да          | ID воронки, где будут создаваться сделки                                       | `1234567`                            |
| `AMO_STATUS_ID`     | Да          | ID статуса "Новая заявка" в воронке                                            | `7654321`                            |

**Примечание:** `AMO_ACCESS_TOKEN` и `AMO_REFRESH_TOKEN` создаются автоматически при первом запуске приложения через
`AMO_AUTH_CODE`. После создания они сохраняются в файлах `.amocrm_tokens/access_token.txt` и
`.amocrm_tokens/refresh_token.txt`, и в `.env` их указывать не нужно.

#### Application

| Переменная       | Обязательно | Описание                      | По умолчанию |
|------------------|-------------|-------------------------------|--------------|
| `APP_HOST`       | Нет         | Хост приложения               | `0.0.0.0`    |
| `APP_PORT`       | Нет         | Порт приложения               | `8080`       |
| `LOG_LEVEL`      | Нет         | Уровень логирования           | `INFO`       |
| `WEBHOOK_SECRET` | Да          | Секрет для валидации вебхуков | -            |

#### Redis

| Переменная       | Обязательно | Описание             | По умолчанию |
|------------------|-------------|----------------------|--------------|
| `REDIS_HOST`     | Нет         | Хост Redis           | `localhost`  |
| `REDIS_PORT`     | Нет         | Порт Redis           | `6379`       |
| `REDIS_DB`       | Нет         | Номер БД Redis       | `0`          |
| `REDIS_PASSWORD` | Нет         | Пароль Redis         | `None`       |
| `SYNC_LOCK_TTL`  | Нет         | TTL блокировки (сек) | `10`         |

### Makefile команды

```bash
# Форматирование кода
make format

# Линтинг
make lint

# Форматирование + Линтинг
make format && make lint

# Запуск тестов
make test
```

## Контакты и автор

**Автор:** Nikita Zhulikov  
**Email:** zhulikovnikita884@gmail.com  
**GitHub:** https://github.com/ZhulikovN
