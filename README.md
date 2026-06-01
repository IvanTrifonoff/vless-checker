# VLESS Service — Саммари

## 📋 Описание

Сервис автоматической проверки VLESS-ключей, формирования подписки и отправки результатов в Telegram.

**Назначение:**
- Проверка работоспособности VLESS-ключей из публичного источника (GitHub)
- Тестирование скорости и латентности через sing-box
- Формирование ТОП-20 лучших ключей
- Отправка результатов в Telegram-канал
- Публикация подписки для клиентов

---

## 🌐 URLs

| Ресурс | URL |
|--------|-----|
| **Подписка** | https://panel.trfnv.ru/sub.txt |
| **Альтернатива** | https://vless.trfnv.ru/sub.txt |
| **Исходник ключей** | https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt |

---

## 🖥️ Инфраструктура

### Хост: VPS vmt01 (82.202.141.81)

**Расположение:** `/opt/vless-service/`

**Компоненты:**

| Компонент | Описание |
|-----------|----------|
| `vless-checker` | Контейнер проверки ключей (Python + sing-box) |
| `vless-sub-server` | Nginx для раздачи файла подписки |
| `nginx` (host) | Проксирует panel.trfnv.ru → /opt/vless-service/html/ |

**Структура каталогов:**
```
/opt/vless-service/
├── docker-compose.yml      # Конфигурация Docker
├── vless_checker.py        # Скрипт проверки ключей
├── .env                    # Переменные окружения (TG_TOKEN, TG_CHAT_ID)
├── html/                   # Файлы подписки
│   ├── sub.txt             # Base64-подписка (ТОП-20)
│   └── sub_v2.txt          # Резервная версия
├── Dockerfile              # Образ контейнера
├── requirements.txt        # Python зависимости
└── CHANGELOG.md            # История изменений
```

---

## ⚙️ Конфигурация

### docker-compose.yml

```yaml
services:
  vless-checker:
    build: .
    container_name: vless-checker
    restart: on-failure
    environment:
      - TG_TOKEN=${TG_TOKEN}
      - TG_CHAT_ID=${TG_CHAT_ID}
      - TG_PROXY=socks5h://10.10.10.2:10810  # Обход блокировок РКН
      - SUB_PATH=/var/www/html/sub.txt
      - PYTHONUNBUFFERED=1
    volumes:
      - ./html:/var/www/html
      - ./vless_checker.py:/app/vless_checker.py

  nginx:
    image: nginx:alpine
    container_name: vless-sub-server
    volumes:
      - ./html:/usr/share/nginx/html:ro
```

### Переменные окружения (.env)

```bash
TG_TOKEN=7824808765:AAFY4ibAP6p1upLf--rZgVXuPG2xE5HkT3w
TG_CHAT_ID=-1003327050465
TG_PROXY=socks5h://10.10.10.2:10810
```

### Планировщик (cron)

```bash
0 */4 * * * cd /opt/vless-service && /usr/bin/docker compose run --rm vless-checker
```

**Расписание:** каждые 4 часа (00:00, 04:00, 08:00, 12:00, 16:00, 20:00)

### Nginx (host) — /etc/nginx/sites-available/panel.trfnv.ru

```nginx
server {
    server_name panel.trfnv.ru;
    
    location /sub.txt {
        alias /opt/vless-service/html/sub.txt;
        add_header Content-Type text/plain;
    }
    
    location / {
        alias /opt/vless-service/html/;
        add_header Content-Type text/plain;
    }
}
```

---

## 🔧 Алгоритм работы

1. **Загрузка ключей:** Скачивание списка VLESS-ключей из GitHub
2. **Тестирование:** Параллельная проверка через sing-box (5 потоков)
   - Проверка доступности Google (latency)
   - Тест скорости (download 5MB файла)
3. **Сортировка:** По скорости (убывание) и латентности (возрастание)
4. **Фильтрация:** Выборка по 1 ключу из каждой страны + лучшие остальные
5. **Формирование ТОП-20:** Итоговый список рабочих ключей
6. **Отправка в Telegram:** Два сообщения (по 10 ключей) + ссылка на подписку
7. **Сохранение подписки:** Base64-кодирование и запись в sub.txt

---

## 📊 Формат подписки

**Тип:** Base64 (одной строкой, без переносов)

**Содержимое:** 20 VLESS-ключей, разделённых newline (до кодирования)

**Пример декодирования:**
```bash
curl -s https://panel.trfnv.ru/sub.txt | base64 -d
```

---

## 🛠️ Управление сервисом

### Запуск / остановка

```bash
# На VPS
cd /opt/vless-service

# Запуск
docker compose up -d

# Остановка
docker compose down

# Пересборка
docker compose up -d --build

# Ручной запуск проверки
docker compose run --rm vless-checker
```

### Просмотр логов

```bash
# Логи checker
docker logs vless-checker --tail 50

# Логи nginx
docker logs vless-sub-server --tail 50
```

### Проверка статуса

```bash
# Статус контейнеров
docker ps --format 'table {{.Names}}\t{{.Status}}' | grep vless

# Проверка подписки
curl -s -o /dev/null -w "%{http_code}" https://panel.trfnv.ru/sub.txt

# Размер файла
ls -la /opt/vless-service/html/sub.txt
```

---

## 🐛 Известные проблемы и решения

### 1. Таймауты Telegram API (РКН блокирует)

**Симптомы:**
```
❌ TG EXCEPTION: HTTPSConnectionPool(host='api.telegram.org', port=443): Read timed out
```

**Решение:** Использовать SOCKS5 прокси
```bash
# В docker-compose.yml добавить:
TG_PROXY=socks5h://10.10.10.2:10810

# В vless_checker.py:
TG_SESSION = requests.Session()
TG_SESSION.proxies = {'http': TG_PROXY, 'https': TG_PROXY}
```

### 2. Подписка не обновляется (nginx проксирует не туда)

**Симптомы:**
- Возвращается HTML вместо Base64
- HTTP 200, но содержимое — страница приложения

**Решение:** Исправить конфиг nginx panel.trfnv.ru
```nginx
location / {
    alias /opt/vless-service/html/;
    add_header Content-Type text/plain;
}
```

### 3. Конфликт server_name в nginx

**Симптомы:**
```
conflicting server name "_" on 0.0.0.0:80, ignored
```

**Решение:** Проверить уникальность server_name в sites-enabled

---

## 📈 Мониторинг

### Uptime-Kuma

**URL:** https://uptime.trfnv.ru

**Проверка:**
- HTTPS https://panel.trfnv.ru/sub.txt
- Интервал: 1 минута
- Ожидается: HTTP 200, Content-Type: text/plain

### Логи

```bash
# Последние ошибки
docker logs vless-checker 2>&1 | grep -i error

# Отправки в Telegram
docker logs vless-checker 2>&1 | grep "TG"
```

---

## 📝 История изменений

### [2025-03-20] Восстановление после поломки

**Проблема:**
- proxytarget-edge сломал маршрутизацию panel.trfnv.ru
- nginx проксировал на localhost:3001 вместо раздачи файла
- Telegram API блокировался РКН

**Решение:**
1. Добавлен SOCKS5 прокси (10.10.10.2:10810) в vless_checker.py
2. Обновлён docker-compose.yml — переменная TG_PROXY
3. Восстановлен nginx конфиг panel.trfnv.ru
4. Формат подписки: Base64 одной строкой

**Результат:**
- ✅ https://panel.trfnv.ru/sub.txt — HTTP 200, ~7KB
- ✅ Telegram уведомления — через прокси
- ✅ 20 рабочих ключей в подписке

---

## 🔐 Безопасность

**Токены и доступы:**
- TG_TOKEN: хранится в .env (не коммитить в git!)
- TG_CHAT_ID: ID Telegram-канала
- Прокси: 10.10.10.2:10810 (внутренняя сеть)

**Рекомендации:**
- Не коммитить .env в репозиторий
- Ограничить доступ к /opt/vless-service/
- Регулярно обновлять образы Docker

---

## 📞 Контакты

**Владелец:** trfnv.ru  
**Канал:** Telegram (ID: -1003327050465)  
**Поддержка:** через Telegram

---

## 📚 Дополнительные материалы

- [sing-box документация](https://sing-box.sagernet.org/)
- [VLESS протокол](https://github.com/XTLS/Xray-core)
- [Telegram Bot API](https://core.telegram.org/bots/api)
