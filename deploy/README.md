# Depter: продакшен-памятка

## 1. Nginx (HTTPS обязателен)
    server {
        listen 443 ssl http2;
        server_name depter.example.com;
        # ssl_certificate ... (certbot)
        location / {
            proxy_pass http://127.0.0.1:8000;
            proxy_set_header Host $host;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }
    }
    server { listen 80; server_name depter.example.com; return 301 https://$host$request_uri; }

В `.env`: `DJANGO_BEHIND_PROXY=1`. Без этого блокировка входа по IP увидит только адрес Nginx.
Gunicorn должен слушать только 127.0.0.1, чтобы заголовок X-Forwarded-For нельзя было подделать снаружи.

## 2. Проверка перед запуском
    DJANGO_DEBUG=0 python manage.py check --deploy
    python manage.py test

## 3. Резервные копии (раз в сутки)
    crontab -e
    15 3 * * * cd /путь/к/Depter && ./venv/bin/python manage.py backup_db --keep 14 >> backups/backup.log 2>&1

Команда сама проверяет копию (SQLite: целостность и чтение данных; PostgreSQL: pg_restore --list).
Копию нужно вывозить на другую машину (rsync / rclone / S3): копия рядом с базой не спасёт при потере сервера.

Полная проверка восстановления PostgreSQL (создаёт и удаляет временную БД, нужны права createdb):
    python manage.py verify_backup backups/depter-XXXX.dump --restore-test
Делайте её раз в месяц: копия, которую ни разу не восстанавливали, это не копия.

Восстановление:
    SQLite:   остановить сервер, заменить db.sqlite3 файлом из backups/
    Postgres: createdb depter_new && pg_restore --no-owner -d depter_new backups/depter-XXXX.dump

## 4. Первый суперпользователь
    python manage.py createsuperuser     # заходит только в админку, данных магазинов в приложении не видит
