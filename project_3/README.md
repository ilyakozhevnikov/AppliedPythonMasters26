## My URL Shortener

This project is a URL shortening service built with FastAPI.
It stores data in PostgreSQL and uses Redis to cache popular links and statistics.

### API Description

Authentication:
- POST /auth/register – register a new user.
- POST /auth/token – get a JWT token

Links:
- POST /links/shorten – create a short link
- GET /{short_code} – redirect to the original URL
- GET /links/{short_code}/stats – show statistics.
- PUT /links/{short_code} – update a link
- DELETE /links/{short_code} – delete a link
- GET /links/search?original_url={url} – find links by original URL
- GET /links/expired – history of expired links

Projects:
- POST /projects?name={project_name} – create a project
- GET /projects/{project_id}/links – get the links in a project

Maintenance:
- POST /admin/cleanup – clean up expired links
- GET /health – health check

### Request Examples

Registration:
- curl -X POST http://localhost:8000/auth/register -H "Content-Type: application/json" -d '{"email":"user@example.com","password":"secret"}'

Get a token:
- curl -X POST http://localhost:8000/auth/token -H "Content-Type: application/x-www-form-urlencoded" -d "username=user@example.com&password=secret"

Create a short link:
- set the JWT token in TOKEN, then:
- curl -X POST http://localhost:8000/links/shorten -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"original_url":"https://example.com","custom_alias":"myalias","expires_at":"2030-01-01T12:00:00Z"}'

Create a short link (guest):
- curl -X POST http://localhost:8000/links/shorten -H "Content-Type: application/json" -d '{"original_url":"https://example.org"}'

Redirect:
- open http://localhost:8000/<short_code> in a browser.

Statistics:
- curl http://localhost:8000/links/<short_code>/stats

Deletion:
- curl -X DELETE http://localhost:8000/links/<short_code> -H "Authorization: Bearer $TOKEN"

Search by original URL:
- curl "http://localhost:8000/links/search?original_url=https://example.org" -H "Authorization: Bearer $TOKEN"

### Running

Requirements:
- Python >=3.11.
- PostgreSQL
- Redis

Running with Docker:
1. Build the image: docker build -t url-shortener .
2. Make sure PostgreSQL and Redis are running
3. Run the image and connect it to Postgres and Redis:
- docker run --rm -p 8000:8000 \
-e DATABASE_URL="postgresql://postgres:postgres@host.docker.internal:5432/url_shortener" \
-e REDIS_URL="redis://host.docker.internal:6379/0" \
-e JWT_SECRET_KEY="change-me-in-prod" \
-e INACTIVE_DELETE_DAYS=30 \
url-shortener

### Database Schema

Table users:
- id – primary key.
- email – unique login.
- hashed_password – password hash.
- created_at – registration time.

Table projects:
- id – primary key.
- name – project name.
- owner_id – reference to users.id (nullable).
- created_at – creation time.

Table links:
- id – primary key.
- short_code – short alias (unique).
- original_url – target URL.
- owner_id – reference to users.id, null for guest links.
- project_id – reference to projects.id, optional.
- created_at – link creation time.
- updated_at – time of the last link update.
- last_accessed_at – time of the last redirect.
- click_count – number of redirects.
- expires_at – optional expiration time.
- deleted – soft-delete flag (used in filters).

Table expired_links_history:
- id – primary key.
- short_code – alias of the deleted link.
- original_url – URL at the time of deletion.
- owner_id – link owner at that time (nullable).
- project_id – project ID at that time (nullable).
- created_at – original creation time.
- expired_at – time the link was deleted/expired.
- click_count – total number of clicks before deletion.
- last_accessed_at – time of last use.

Cleanup logic:
- A link is deleted when its expires_at is in the past, or when its last_accessed_at is older than INACTIVE_DELETE_DAYS days.
- On deletion, the link is copied to expired_links_history and removed from links, and its Redis caches are cleared.

### Testing

Unit and functional tests are located in the `tests/` folder.

Running the tests:
- pytest -q

Checking coverage:
- coverage run -m pytest tests
- coverage report -m

The tests use SQLite as the test database and an in-memory Redis mock, so they don't need running PostgreSQL/Redis instances.

### Load Testing

The project root contains locustfile.py with the following scenarios:
- bulk link creation (POST /links/shorten)
- hot redirects (GET /{short_code})
- statistics requests (GET /links/{short_code}/stats)

Running:
- locust -f locustfile.py --host http://localhost:8000
