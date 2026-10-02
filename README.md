# Analytics-engine

Servicio FastAPI que recibe eventos de la app Android y del backend Spring, los guarda en SQLite y calcula las métricas de negocio del dashboard.

## Cómo correrlo

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
uvicorn main:app --reload --port 8000
python scripts/seed_demo.py --users 30                # datos de prueba (con el servidor corriendo)
python -m unittest discover -s tests -t .             # o: pytest
```

Documentación interactiva en `http://localhost:8000/docs`. La base se crea sola en `./data/analytics.db`.

### Variables de entorno

| Variable | Para qué | Default |
|---|---|---|
| `ANALYTICS_DB_PATH` | Archivo SQLite | `data/analytics.db` |
| `ANALYTICS_INGEST_KEY` | Llave (`X-API-Key`) para **escribir** eventos | vacía = sin protección (solo dev) |
| `ANALYTICS_ADMIN_KEY` | Llave para **leer** métricas y borrar eventos | vacía = sin protección (solo dev) |
| `ANALYTICS_LOADING_THRESHOLD_MS` | Umbral de la métrica de carga | `1000` |
| `ANALYTICS_FREE_TIME_BUCKETS` | Límites en minutos de los rangos de tiempo libre | `30,60,120` |

## Eventos

Todos comparten estos campos:

| Campo | Req. | Notas |
|---|---|---|
| `eventType` | sí | Ver tabla de abajo |
| `userId` | sí | UUID del `User` del backend |
| `eventId` | no | UUID generado por quien envía. Si reintenta, el duplicado se descarta |
| `sessionId` | no | Id de sesión de la app |
| `appVersion` | no | Los eventos del backend no la tienen |
| `timestamp` | no | Hora del cliente (ISO 8601). Si falta o va más de 5 min en el futuro, se usa la del servidor |

| `eventType` | Campos propios | Quién lo emite |
|---|---|---|
| `app_loading_time` | `loadType` (`cold_start`/`warm_start`/`screen`), `screen` (obligatorio si `loadType=screen`), `durationMs` | App |
| `screen_view` | `screen` | App |
| `crash` | `screen`, `component?`, `exceptionType?` | App (en el siguiente arranque) |
| `recommendation_shown` | `recommendationId` (uno por carga), `freeTimeMinutes?` | Backend |
| `recommended_activity_selected` | `activityId`, `category`, `freeTimeMinutes?`, `recommendationId?`. Se emite al hacer **join** a una actividad recomendada | Backend |
| `friend_availability_used` | `action` (`viewed`/`plan_created`/`plan_joined`, default `viewed`), `activityId?` | Backend (al llamar `/api/friends/gaps`) |

### Ingesta

| Método | Ruta | Auth | Qué hace |
|---|---|---|---|
| `POST` | `/events` | ingest | Un evento → `{ "accepted": 1, "duplicates": 0 }` |
| `POST` | `/events/batch` | ingest | `{ "events": [ … ] }`, hasta 500, todo o nada |
| `DELETE` | `/events` | admin | Sin parámetros borra todo. `?appVersionBefore=1.0.0` borra solo versiones viejas |

## Métricas

Cada métrica es una feature independiente (ver `routes/` y `metrics/`); su definición está en el docstring del módulo de `metrics/` y en `/docs`. Todas son `GET` bajo `/metrics`, requieren la llave admin, aceptan los mismos filtros y devuelven tasas de 0 a 1.

| Filtro | Significado |
|---|---|
| `from`, `to` | Rango de fechas ISO 8601 (`from` inclusivo, `to` exclusivo) |
| `appVersion` | Solo esa versión exacta |
| `minAppVersion` | Descarta versiones más viejas. Los eventos sin versión (del backend) no se descartan |

`GET /metrics/summary` junta todas las métricas instaladas en una sola llamada, pensado para el dashboard.

### Agregar una métrica nueva

1. `metrics/<nombre>.py`: función pura `(conn, filters, ...) -> dict`.
2. `routes/<nombre>.py`: `router = metrics_router()`, el endpoint y, opcional, `summary_key` + `summary(conn, filters)`.
3. `tests/test_<nombre>.py`.

No hay que editar ningún archivo compartido: `main.py` y `/metrics/summary` descubren las rutas solos.

## Limitaciones conocidas

- **SQLite:** suficiente para este tamaño. El esquema es SQL estándar; migrar a Postgres solo exige cambiar `db.py`.
- **La llave de ingesta dentro del APK es extraíble.** Protege contra ruido, no contra un atacante decidido. Si la app envía eventos directo, lo robusto es validar el JWT del backend en este servicio.
- **`Category` está duplicada** (`config.CATEGORIES` y `models.Category`) y refleja el enum del backend. Un test verifica que coincidan entre sí, no con el backend.