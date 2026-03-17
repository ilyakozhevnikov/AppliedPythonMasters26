## Моя URL-сокращалка

Этот проект - сервис сокращения URL-адресов, написанный на FastAPI.  
Он хранит данные в PostgreSQL и использует Redis для кэширования популярных ссылок и статистики.

### Описание API

Авторизация:
- POST /auth/register – для нового юзера.
- POST /auth/token – получить JWT токен

Ссылки:
- POST /links/shorten – создать короткую ссылку
- GET /{short_code} – редирект на оригинальную урлу
- GET /links/{short_code}/stats – показать статистику.
- PUT /links/{short_code} – внести изменения
- DELETE /links/{short_code} – удалить ссылку
- GET /links/search?original_url={url} – найти ссылки по оригинальной урле
- GET /links/expired – история протухших ссылок

Проекты:
- POST /projects?name={project_name} – создать проект
- GET /projects/{project_id}/links – получить ссылки в проекте

Поддержка:
- POST /admin/cleanup – почистить протухшие ссылки
- GET /health – health check


### Примеры запросов

Регистрация:
- curl -X POST http://localhost:8000/auth/register -H "Content-Type: application/json" -d '{"email":"user@example.com","password":"secret"}'

Получить токен:
- curl -X POST http://localhost:8000/auth/token -H "Content-Type: application/x-www-form-urlencoded" -d "username=user@example.com&password=secret"

Создать короткую ссылку:
- установить токен в JWT, затем:
- curl -X POST http://localhost:8000/links/shorten -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"original_url":"https://example.com","custom_alias":"myalias","expires_at":"2030-01-01T12:00:00Z"}'

Создать короткую ссылку (guest):
- curl -X POST http://localhost:8000/links/shorten -H "Content-Type: application/json" -d '{"original_url":"https://example.org"}'

Редирект:
- открыть http://localhost:8000/<short_code> в браузере.

Статистики:
- curl http://localhost:8000/links/<short_code>/stats

Удаление:
- curl -X DELETE http://localhost:8000/links/<short_code> -H "Authorization: Bearer $TOKEN"

Поиск по оригинальному URL:
- curl "http://localhost:8000/links/search?original_url=https://example.org" -H "Authorization: Bearer $TOKEN"

### Запуск

Требования:
- Python >=3.11.
- PostgreSQL
- Redis

Запуск с докером:
1. Построить образ: docker build -t url-shortener .
2. Убедиться, что PostgreSQL и Redis запущены
3. Запустить образ и соединить с Postgres и Redis:
   - docker run --rm -p 8000:8000 \
     -e DATABASE_URL="postgresql://postgres:postgres@host.docker.internal:5432/url_shortener" \
     -e REDIS_URL="redis://host.docker.internal:6379/0" \
     -e JWT_SECRET_KEY="change-me-in-prod" \
     -e INACTIVE_DELETE_DAYS=30 \
     url-shortener

### Описание БД

Таблица users:
- id – первичный ключ.
- email – уникальный логин.
- hashed_password – хэш пароля.
- created_at – время регистрации.

Таблица projects:
- id – первичный ключ.
- name – название проекта.
- owner_id – ссылка на users.id (может быть null).
- created_at – время создания.

Таблица ссылки:
- id – первичный ключ.
- short_code – короткий псевдоним (уникальный).
- original_url – целевой URL.
- owner_id – ссылка на users.id, null для гостевых ссылок.
- project_id – ссылка на projects.id, необязательно.
- created_at – время создания ссылки.
- updated_at – время последнего обновления ссылки.
- last_accessed_at – время последнего перенаправления.
- click_count – количество перенаправлений.
- expires_at – необязательное время истечения срока действия.
- deleted – флаг мягкого удаления (используется в фильтрах).

Таблица expired_links_history:
- id – первичный ключ.
- short_code – псевдоним удаленной ссылки.
- original_url – URL на момент удаления.
- owner_id – владелец ссылки на тот момент (может быть нулевым).
- project_id – идентификатор проекта на тот момент (может быть нулевым).
- created_at – время первоначального создания.
- expired_at – время удаления/истечения срока действия ссылки.
- click_count – общее количество кликов до удаления.
- last_accessed_at – время последнего использования.

Логика очистки:
- Ссылка удаляется, когда ее expires_at находится в прошлом или когда last_accessed_at старше INACTIVE_DELETE_DAYS дней.
- При удалении она копируется в expired_links_history и удаляется из ссылок, а ее кэши Redis очищаются.

### Тестирование

Юнит и функциональные тесты лежат в папке `tests/`.

Прогон тестов:
- pytest -q

Проверка покрытия:
- coverage run -m pytest tests
- coverage report -m

Тесты используют SQLite как тестовую БД и мок Redis (in-memory), поэтому не требуют поднятого PostgreSQL/Redis.

### Нагрузочное тестирование

В корне проекта есть locustfile.py со сценариями:
- массовое создание ссылок (POST /links/shorten)
- горячие редиректы (GET /{short_code})
- запросы статистики (GET /links/{short_code}/stats)

Запуск:
- locust -f locustfile.py --host http://localhost:8000
