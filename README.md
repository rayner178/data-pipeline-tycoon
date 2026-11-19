# Data Pipeline Tycoon

Plataforma de simulación gamificada para practicar y validar competencias de ingeniería de datos (SQL/PostgreSQL, limpieza de datos y optimización de consultas). Cliente visual en **Roblox (Luau)** y backend en **Python (FastAPI)** con **Clean Architecture** y **PostgreSQL**.

Proyecto monográfico de UNICARIBE. La fuente de verdad del alcance es [`SPEC.md`](SPEC.md), las reglas de desarrollo están en [`AGENTS.md`](AGENTS.md), las decisiones técnicas en [`docs/decisions.md`](docs/decisions.md) y las puertas por fase en [`PHASES.md`](PHASES.md).

## Arquitectura y estructura

Las dependencias solo apuntan hacia adentro (`domain` <- `application` <- `infrastructure` / `api`):

```text
src/
  domain/             # Entidades puras (Player, Challenge, Attempt), matching y reglas EXPLAIN
  application/        # Puertos y casos de uso (ListChallenges, SubmitSolution, GetProgress)
  infrastructure/     # SQLAlchemy 2, Alembic, repositorios, seed idempotente y sandbox SQL
  api/                # FastAPI (routers, autenticación X-API-Key, esquemas Pydantic)
roblox/               # Cliente Luau compatible con Rojo (véase roblox/README.md)
scripts/              # Script de arranque reproducible para producción (Render)
tests/                # Pruebas unitarias, de integración y de seguridad por capa
.github/workflows/    # CI en GitHub Actions (ruff, mypy, pytest con postgres:16-alpine)
render.yaml           # Blueprint opcional de despliegue gratuito en Render
```

---

## Quickstart local (3 pasos)

**Requisitos:** [uv](https://docs.astral.sh/uv/) (gestiona Python 3.12), Docker Compose v2 y Git.

### 1. Clonar, instalar dependencias y configurar `.env`

```bash
uv sync
cp .env.example .env          # en PowerShell: Copy-Item .env.example .env
```

Completa en `.env`: `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `DATABASE_URL` y `API_KEY` (deja `SANDBOX_DATABASE_URL=` vacío en local para que el evaluador aprovisione `tycoon_sandbox_player` automáticamente).

### 2. Levantar PostgreSQL, aplicar migraciones y cargar los 3 retos MVP

```bash
docker compose up -d
uv run alembic upgrade head
PYTHONPATH=src uv run python -m infrastructure.seed   # PowerShell: $env:PYTHONPATH="src"; uv run python -m infrastructure.seed
```

### 3. Iniciar la API y verificar

```bash
PYTHONPATH=src uv run uvicorn api.app:app --host 127.0.0.1 --port 8000 --reload
# PowerShell: $env:PYTHONPATH="src"; uv run uvicorn api.app:app --host 127.0.0.1 --port 8000 --reload
curl http://127.0.0.1:8000/health   # -> {"status":"ok"}
```

Para conectar Roblox Studio contra el entorno local o remoto, sigue [`roblox/README.md`](roblox/README.md).

---

## Despliegue en producción (Neon + Render, costo cero)

### Parte 1: Base de datos en Neon (PostgreSQL 16)

1. Crea un proyecto gratuito en [Neon](https://neon.tech/) con **PostgreSQL 16**.
2. En **Connection Details**, selecciona la conexión **Direct** (**sin** `-pooler` en el hostname) con `?sslmode=require`.
   > **¿Por qué conexión directa (non-pooled)?** `PostgresSandboxEvaluator` utiliza `SET LOCAL`, cursores nombrados en protocolo extendido y comandos de esquema temporal incompatibles con el *transaction pooling* de PgBouncer.
3. Guarda esa cadena como tu **`DATABASE_URL`** de producción (p. ej. `postgresql://neondb_owner:PASSWORD@ep-xxxx.region.aws.neon.tech/neondb?sslmode=require`).
4. **Recomendado — crear rol restringido para `SANDBOX_DATABASE_URL`:**
   En Neon, el rol dueño puede no tener permisos de `SUPERUSER` sobre ciertos parámetros globales. Crea un rol dedicado de mínimos privilegios desde el **SQL Editor** de Neon:
   ```sql
   CREATE ROLE tycoon_sandbox_player
     WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS
     PASSWORD 'REEMPLAZAR_CON_PASSWORD_SEGURO';

   REVOKE ALL ON SCHEMA public FROM PUBLIC, tycoon_sandbox_player;
   REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC, tycoon_sandbox_player;
   REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC, tycoon_sandbox_player;
   REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC, tycoon_sandbox_player;
   ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM PUBLIC, tycoon_sandbox_player;
   REVOKE CREATE, TEMPORARY ON DATABASE neondb FROM PUBLIC, tycoon_sandbox_player;

   ALTER ROLE tycoon_sandbox_player SET work_mem = '4MB';
   ```
   Luego arma `SANDBOX_DATABASE_URL` con la misma conexión **Direct** (sin `-pooler`) usando ese rol y contraseña:
   `postgresql://tycoon_sandbox_player:REEMPLAZAR_CON_PASSWORD_SEGURO@ep-xxxx.region.aws.neon.tech/neondb?sslmode=require`.
   *(Por defensa en profundidad, el backend vuelve a intentar los `REVOKE` sobre `public` de forma tolerante al iniciar el evaluador.)*

---

### Parte 2: Servicio web en Render (plan gratuito)

1. Conecta tu repositorio en [Render](https://render.com/) usando el Blueprint [`render.yaml`](render.yaml) (o creando un **Web Service** Python manualmente):
   - **Build Command:** `pip install --upgrade uv && uv sync --frozen --no-dev`
   - **Start Command:** `bash scripts/start_prod.sh`
   - **Health Check Path:** `/health`
2. Configura las variables de entorno en el panel de Render (**Environment**, nunca en Git):
   - `PYTHON_VERSION` = `3.12.13`
   - `PYTHONPATH` = `src`
   - `DATABASE_URL` = *(cadena directa de Neon con `?sslmode=require`)*
   - `SANDBOX_DATABASE_URL` = *(cadena directa de `tycoon_sandbox_player` en Neon con `?sslmode=require`)*
   - `API_KEY` = *(clave aleatoria fuerte para `X-API-Key`)*
3. Al desplegar, `scripts/start_prod.sh` ejecuta automáticamente `alembic upgrade head`, siembra de forma idempotente los 3 retos MVP (`infrastructure.seed`) y arranca `uvicorn api.app:app --host 0.0.0.0 --port "${PORT:-8000}"` usando `--frozen --offline --no-dev`.
4. Verifica el despliegue:
   ```bash
   curl -i https://TU-SERVICIO.onrender.com/health
   curl -H "X-API-Key: TU_API_KEY" https://TU-SERVICIO.onrender.com/challenges
   ```
5. Coloca `https://TU-SERVICIO.onrender.com` en `BASE_URL` y tu `API_KEY` en `ServerStorage` (o `Secrets.luau`) siguiendo [`roblox/README.md`](roblox/README.md).

---

### Cold start en Render gratuito y registro para el monográfico

El plan gratuito de Render suspende el servicio web tras **15 minutos** sin tráfico entrante (`SPEC.md §9`). Al llegar la primera petición tras ese reposo, tanto el arranque del contenedor como el despertar de Neon (si escaló a cero) provocan una latencia típica de **30–60 s**.

En el cliente Roblox, `TerminalServer` envía un `GET /health` en segundo plano al entrar el primer jugador (`Players.PlayerAdded`) y `TerminalGui` muestra *"Conectando con el motor SQL..."* si una evaluación supera los 2 segundos.

Para medir el tiempo real en producción tras dejar el servicio inactivo > 15 min:

```bash
curl -o /dev/null -s -w "HTTP: %{http_code} | total: %{time_total}s | ttfb: %{time_starttransfer}s\n" \
  https://TU-SERVICIO.onrender.com/health
```

#### Plantilla de medición empírica (completar tras desplegar en Fase 7)

| Prueba | Estado previo | Código HTTP | Tiempo total (s) | Fecha / Región Render-Neon | Observaciones |
| --- | --- | --- | --- | --- | --- |
| Request 1 (`GET /health`) | Dormido (> 15 min inactivo) | *Pendiente* | *Pendiente* | *Pendiente* | *Primer arranque en frío* |
| Request 2 (`GET /health`) | Caliente (inmediato) | *Pendiente* | *Pendiente* | *Pendiente* | *Contenedor y BD activos* |
| Request 3 (`POST /challenges/dedupe-row-number/submit`) | Dormido (> 15 min inactivo) | *Pendiente* | *Pendiente* | *Pendiente* | *Incluye sandbox SQL completo* |

---

## Calidad, pruebas y seguridad

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

- Política de reporte de vulnerabilidades: [`SECURITY.md`](SECURITY.md).

## Licencia

[MIT](LICENSE) © 2026 Rayner Javier Rodriguez Brito
