# Guía para Contribuir — Data Pipeline Tycoon

¡Gracias por querer aportar a **Data Pipeline Tycoon**! Cualquier persona puede proponer nuevos retos de SQL en PostgreSQL sin tocar código Python ni Roblox, o mejorar el backend, el CLI y el cliente Roblox.

## 1. Requisitos y entorno local

- [uv](https://docs.astral.sh/uv/) (gestiona Python 3.12)
- Docker con Compose v2 (PostgreSQL 16)
- Git
- *(Opcional si editas `roblox/`)* [Selene 0.27.1](https://github.com/Kampfkarren/selene/releases/tag/0.27.1) y [Rojo](https://rojo.space/)

Configura tu entorno local:

```bash
uv sync
cp .env.example .env          # PowerShell: Copy-Item .env.example .env
# Completa POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, DATABASE_URL y API_KEY en .env
docker compose up -d
uv run alembic upgrade head
PYTHONPATH=src uv run python -m infrastructure.seed
```

---

## 2. Cómo agregar un reto SQL nuevo (`challenges/<slug>/`)

Los retos se definen de forma declarativa. Cada reto vive en una carpeta cuyo nombre coincide exactamente con su `code` en **kebab-case estricto** (`^[a-z0-9]+(?:-[a-z0-9]+)*$`), por ejemplo `challenges/window-lag-revenue/`.

Crea los **5 archivos obligatorios** dentro de `challenges/<slug>/`:

1. **`challenge.toml`**
   ```toml
   # `id` es opcional: si se omite se deriva determinísticamente desde `code`.
   code = "window-lag-revenue"
   module = "postgresql"
   title = "Comparar ingresos mes a mes con LAG()"
   description = "Enunciado claro en español indicando tablas, columnas esperadas y criterio de orden si aplica."
   difficulty = 2          # 1 = Fácil, 2 = Media, 3 = Difícil
   max_seconds = 2.0       # Límite del sandbox (statement_timeout)
   ordered = true          # true si el orden de filas es parte de la solución
   starter_sql = """
   -- Plantilla opcional para mostrar en clientes (CLI / Roblox)
   SELECT ...;
   """
   hints = [
     "Pista 1/2: ...",
     "Pista 2/2: ...",
   ]
   ```
   > **Nota sobre Roblox:** si quieres que el reto tenga también pistas dentro del HUD de Roblox, sincroniza opcionalmente el slug en `roblox/src/shared/ChallengeCatalog.luau`.

2. **`setup.sql`**
   - DDL + `INSERT` + índices (`CREATE INDEX ...; ANALYZE ...;`) autocontenidos.
   - Usa datos pequeños y deterministas (los tests corren contra PostgreSQL 16 en cada PR).
   - Recuerda que el sandbox del jugador es **estrictamente read-only (`SELECT` / `WITH`)**: todo DDL o índice del reto va en `setup.sql`.

3. **`expected_result.json`**
   - Matriz JSON con las filas esperadas por posición de columna (`null` para SQL `NULL`).
   - Para tipos numéricos exactos (`NUMERIC` / `DECIMAL`), usa la representación biyectiva explícita para preservar escala:
     ```json
     [
       [1, "Cliente A", {"__type__": "decimal", "value": "150.00"}]
     ]
     ```

4. **`solution.sql`**
   - Consulta de referencia (`SELECT` o `WITH`, una sola sentencia) que **debe superar** el reto (`passed = true`).
   - Si `setup.sql` define un índice (`CREATE INDEX`), `solution.sql` debe producir un plan con `Index Scan`, `Index Only Scan` o `Bitmap Index Scan` en `EXPLAIN (COSTS OFF)`.

5. **`wrong_solution.sql`**
   - Consulta representativa de un error común que **debe fallar** (`passed = false`).
   - En retos de índices (`CREATE INDEX` en `setup.sql`), `wrong_solution.sql` debe devolver las filas correctas usando `Seq Scan` (p. ej. rompiendo sargabilidad) para validar que `EXPLAIN` rechaza soluciones lentas.

La suite [`tests/infrastructure/test_challenge_packs.py`](tests/infrastructure/test_challenge_packs.py) descubre automáticamente cualquier carpeta nueva dentro de `challenges/` y la valida contra PostgreSQL real.

---

## 3. Puerta de verificación local antes de abrir PR

Ejecuta todos los controles desde la raíz del proyecto:

```bash
uv run --frozen --offline ruff check .
uv run --frozen --offline ruff format --check .
uv run --frozen --offline mypy
uv run --frozen --offline pytest -q
uv run --frozen --offline python scripts/smoke_test_e2e.py
```

Si modificaste archivos en `roblox/`:

```bash
cd roblox
selene generate-roblox-std
selene src/
```

También puedes probar tus retos manualmente de extremo a extremo con `tycoon-cli`:

```bash
PYTHONPATH=src uv run python -m cli play
```

---

## 4. Reglas del proyecto

- Arquitectura limpia en `src/`: `domain` $\leftarrow$ `application` $\leftarrow$ `infrastructure` / `api`.
- `src/cli/` es un cliente externo: solo puede importar librería estándar de Python (sin importar `domain`, `application`, `infrastructure` ni `api`).
- Identificadores y código en inglés; textos visibles para el jugador y diagnósticos en español.
- Commits claros con prefijo convencional (`feat:`, `fix:`, `test:`, `docs:`, `chore:`).
- **Nunca** incluyas claves reales, `.env` ni `Secrets.luau` en ningún commit.
