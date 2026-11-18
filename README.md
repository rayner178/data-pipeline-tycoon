# Data Pipeline Tycoon

Plataforma de simulación gamificada para practicar y validar competencias de ingeniería de datos (SQL/PostgreSQL, limpieza de datos, resiliencia de APIs). Cliente visual en Roblox (Luau) y backend en Python (FastAPI) con Clean Architecture y PostgreSQL.

Proyecto monográfico de UNICARIBE. La fuente de verdad del alcance es [`SPEC.md`](SPEC.md); las reglas para agentes de IA están en [`AGENTS.md`](AGENTS.md).

> **Estado:** Fase 1, con la estructura del repositorio y el entorno de desarrollo. Todavía no contiene lógica de negocio.

## Estructura

```
src/
  domain/          # entidades y reglas puras (sin dependencias externas)
  application/     # casos de uso + puertos (interfaces)
  infrastructure/  # SQLAlchemy, repositorios concretos, sandbox SQL
  api/             # FastAPI: routers, esquemas, dependencias
roblox/            # scripts Luau
tests/             # pruebas por capa
```

## Requisitos

- [uv](https://docs.astral.sh/uv/) (gestiona Python 3.12 y las dependencias)
- Docker con Compose v2 (`docker compose`), ya sea **Docker Engine dentro de WSL 2** o **Docker Desktop**
- Git

## Puesta en marcha

### 1. Dependencias de Python

```bash
uv sync
```

`uv` descarga Python 3.12 si no está instalado y crea el entorno virtual en `.venv/`.

### 2. Variables de entorno

Copia la plantilla y completa los valores. **Nunca** subas `.env` al repositorio.

```bash
# Bash (WSL / Linux / macOS)
cp .env.example .env
```

```powershell
# PowerShell (Windows)
Copy-Item .env.example .env
```

`docker compose` se niega a arrancar si faltan `POSTGRES_USER`, `POSTGRES_PASSWORD` o `POSTGRES_DB`.

### 3. PostgreSQL con Docker

Elige **una** de las dos opciones.

#### Opción A: Docker Engine dentro de WSL 2

1. Abre la terminal de tu distribución (por ejemplo, Ubuntu).
2. Por rendimiento, clona el repositorio en el sistema de archivos de Linux (`~/...`) en lugar de `/mnt/c/...`.
3. Asegúrate de que el servicio de Docker esté en ejecución:
   ```bash
   # Con systemd habilitado en WSL
   sudo systemctl start docker
   # Sin systemd
   sudo service docker start
   ```
4. Si `docker` pide `sudo`, agrega tu usuario al grupo `docker` (`sudo usermod -aG docker $USER`) y abre una terminal nueva.
5. Desde la raíz del proyecto:
   ```bash
   docker compose up -d
   ```

#### Opción B: Docker Desktop (Windows)

1. Instala Docker Desktop con el backend **WSL 2** activado (*Settings → General → Use the WSL 2 based engine*).
2. Si vas a trabajar desde WSL, activa la integración con tu distribución en *Settings → Resources → WSL integration*.
3. Abre Docker Desktop y espera a que el motor esté en ejecución.
4. Desde la raíz del proyecto (PowerShell o terminal de WSL):
   ```bash
   docker compose up -d
   ```

#### Verificar la base de datos

```bash
docker compose ps        # el servicio "db" debe mostrarse como "healthy"
docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

Para detenerla: `docker compose down` (agrega `-v` solo si quieres **borrar** los datos del volumen).

## Calidad y pruebas

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

## Licencia

[MIT](LICENSE) © 2026 Rayner Javier Rodriguez Brito
