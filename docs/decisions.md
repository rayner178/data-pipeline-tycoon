# Decisiones de diseño

Registro breve de las decisiones tomadas en cada fase. El alcance sigue definido en `SPEC.md`.

## Fase 2 — Dominio

### Identificadores
- Las entidades usan `UUID`, generado fuera del dominio (casos de uso o infraestructura). Así no hace falta `id: int | None` antes de persistir.

### Fechas
- Todo `datetime` del dominio debe tener zona horaria (*aware*). El dominio nunca llama a `now()`: la fecha se recibe desde fuera.

### Comparación de resultados (`domain/result_matching.py`)
- **Filas:** por defecto se comparan como multiconjunto: el orden se ignora, pero los duplicados cuentan. Así, un `JOIN` que multiplica filas no coincide. Si `Challenge.ordered` es `true`, el orden también debe coincidir.
- **Columnas:** se comparan por posición; los nombres y alias no forman parte del resultado. El número de columnas debe ser igual.
- **`None`:** coincide solo con `None`. No equivale a `0`, `""` ni `False`. Es distinto de la semántica `NULL` de SQL, a propósito.
- **Booleanos:** se revisan antes que los enteros (en Python, `bool` es subclase de `int`). `True` no coincide con `1`.
- **Números:** `int`, `float` y `Decimal` se normalizan a `Decimal` (los `float` vía `str()`, para evitar artefactos binarios) y se redondean a 4 decimales con `ROUND_HALF_EVEN`. Así `1 == 1.0 == Decimal("1.0000")` y `0.1 + 0.2` coincide con `0.3`.
  - **Limitación conocida:** se redondea, no se usa una tolerancia. Dos valores separados por menos de 0.0001 pueden no coincidir si caen a lados distintos de un límite de redondeo; por ejemplo, `1.00014999` → `1.0001` y `1.00015001` → `1.0002`. Los `expected_result` deben generarse ejecutando la solución de referencia.
  - Con `ROUND_HALF_EVEN`, `1.00005` → `1.0000` y `1.00015` → `1.0002`.
- **No finitos:** `NaN`, `sNaN` e `±Infinity` nunca coinciden, ni siquiera consigo mismos. El tratamiento depende de dónde aparezcan:
  - **En el resultado del jugador (`actual`):** `results_match` devuelve `False` y **no** lanza error. Una consulta que produce `'NaN'::float` o `'Infinity'` es una respuesta incorrecta, no una falla del sistema. Si lanzara error, una entrada del jugador se convertiría en excepción y se mezclaría con los errores reales. Al devolver `False`, el intento se guarda como fallo normal.
  - **En `results_match` con un `expected` no finito:** también devuelve `False`. La función es pura y total: nunca falla por los valores que compara.
  - **En `Challenge.expected_result`:** se lanza `DomainValidationError` al crear el reto. El `expected_result` lo escribimos nosotros, así que un valor no finito es un error de configuración: hay que fallar pronto, porque si no el reto sería imposible de superar.
  - **Por qué no se comparan entre sí:** según IEEE 754, `NaN ≠ NaN`. Además, estos valores no se pueden redondear a 4 decimales (`quantize` lanza `InvalidOperation`), así que no encajan en la regla numérica. Se podría haber hecho que `Infinity` coincidiera con `Infinity`, pero como ningún `expected_result` puede contenerlo, esa regla no aportaría nada.
- **Texto:** comparación exacta; distingue mayúsculas y espacios.
- **Tipos:** se admiten `str`, `int`, `float`, `Decimal`, `bool` y `None`. Las fechas, `UUID` y otros tipos de PostgreSQL los convierte la infraestructura (fase 5).
- `Challenge` guarda `expected_result` como tupla de tuplas (inmutable) y exige que todas las filas tengan el mismo número de columnas.

### Tiempo límite
- `max_seconds` no afecta a `passed` en el dominio: `passed` depende solo del resultado (SPEC §5). El sandbox aplica el límite como `statement_timeout` (fase 5).

### Intentos (`Attempt`)
- Un intento exitoso (`passed=True`) **exige** `execution_ms`: si la consulta superó el reto, se ejecutó y su tiempo se midió. Gracias a esta regla, `best_ms` del progreso siempre tiene valor.
- Un intento exitoso nunca tiene `error_message`.
- Un intento fallido puede tener `execution_ms = None`, por ejemplo cuando el SQL ni siquiera llegó a ejecutarse por un error de sintaxis.
- `execution_ms` nunca es negativo.

### Progreso (`domain/progress.py`)
- Por reto: `completed_at` es la fecha del primer intento exitoso y `best_ms` es el menor `execution_ms` entre los intentos exitosos. Los intentos fallidos no cuentan para el mejor tiempo.
- El resultado se ordena por `completed_at` y, en caso de empate, por `challenge_id`.
- Recibir intentos de otro jugador es un error (`DomainValidationError`).

### Reto 3 (índice)
- No se puede validar solo por el resultado: la consulta devuelve las mismas filas con o sin índice. En la fase 5 se evaluará además con el plan de ejecución (`EXPLAIN`), y `SubmitSolution` combinará ambas reglas: resultado correcto **y** plan que usa el índice esperado.

## Fase 2 — Aplicación

### Evaluador de SQL (`SolutionEvaluator`)
- El evaluador **no decide** `passed`: devuelve evidencia (`ExecutionSucceeded` con filas y tiempo, o `ExecutionFailed` con el error del SQL) y `SubmitSolution` aplica las reglas del dominio.
- Son dataclasses `kw_only`: en la fase 5 se agregará a `ExecutionSucceeded` un campo `plan` con valor por defecto para el reto 3, sin romper el código existente.

### Errores en `SubmitSolution`
- **Error del SQL del jugador** (`ExecutionFailed`): se guarda como intento fallido y se devuelve `SubmissionResult`.
- **Resultado no comparable** (`DomainValidationError` al comparar, por ejemplo un tipo de celda no admitido): se trata como fallo del jugador. El intento se guarda con `passed=False` y un mensaje claro, sin 503. Los NaN e infinitos no llegan aquí: el dominio devuelve "no coincide".
- **Falla de infraestructura**: los adaptadores lanzan **solo** `EvaluatorError`. `SubmitSolution` captura únicamente esa excepción y **no guarda nada**, porque el jugador no tuvo culpa y el intento no llegó a evaluarse. Registra la causa real con `logging` y lanza `EvaluatorUnavailable`, que la API traducirá a 503.
- No se captura `Exception` genérica: un error inesperado es un fallo de programación y se propaga.
- Validación antes de escribir: un envío vacío (`EmptySubmission`) o un reto inexistente (`ChallengeNotFound`) no guardan nada ni llaman al evaluador.
- Orden: validar, buscar el reto, evaluar y juzgar; solo después se crea el jugador (si es nuevo) y se guarda el intento.

### Lecturas
- `ListChallenges` no expone `setup_sql` ni `expected_result`, porque este último es la respuesta del reto.
- `GetProgress` con un jugador inexistente devuelve un progreso vacío y no lo crea. Si un `challenge_id` del progreso ya no existe en el repositorio, se omite.

### Unidad de trabajo (para la fase 3)
- Crear el jugador y guardar el intento debe confirmarse en **una transacción corta**. La evaluación queda fuera: corre con otra conexión y otro rol, y puede tardar hasta `max_seconds`.
- La carrera de dos primeros envíos simultáneos se resolverá en el repositorio con `INSERT … ON CONFLICT DO NOTHING` seguido de una lectura.

### Pendientes para fases posteriores
- **Saneamiento de errores (fase 5):** los mensajes de error de PostgreSQL deben sanearse en el adaptador del evaluador antes de llegar a `ExecutionFailed.error_message`. No deben exponer nombres internos de esquemas, roles ni rutas.
- **Longitud del SQL (fases 4 y 5):** habrá un límite de longitud del SQL enviado. Se definirá en la fase 4 (validación de la API) y se reforzará en la fase 5 (sandbox).

## Fase 3 — Infraestructura y persistencia

### Serialización de `expected_result` (`infrastructure/serialization.py`)
- En PostgreSQL se guarda en una columna `JSONB` como lista de listas.
- Los valores `Decimal` se codifican explícitamente como `{"__type__": "decimal", "value": "..."}` para preservar su precisión y escala exactas sin colisionar con celdas de texto numérico (`"1.25"` frente a `Decimal("1.25")`).
- Al leer de la base de datos se valida la estructura completa y se reconstruye `FrozenResult` (`tuple[tuple[Cell, ...], ...]`).

### Modelos ORM separados y mapeo explícito (`infrastructure/orm.py`)
- `PlayerModel`, `ChallengeModel` y `AttemptModel` usan SQLAlchemy 2 (`DeclarativeBase`, `Mapped`, `mapped_column`), separados de las entidades puras de dominio y traducidos mediante funciones explícitas `*_to_domain` / `*_from_domain`.
- Todas las fechas usan `DateTime(timezone=True)` (`TIMESTAMPTZ`), `roblox_user_id` usa `BIGINT` con restricción única, `challenges.code` tiene restricción única y existen índices en `challenges(difficulty, code)`, `attempts(player_id)` y `attempts(challenge_id)`.

### Unidad de trabajo y carrera del primer envío (`infrastructure/uow.py`, `infrastructure/repositories.py`)
- Se añadió el puerto `UnitOfWork(ABC)` en `application/ports.py` y se inyectó opcionalmente en `SubmitSolution` para delimitar una transacción corta alrededor de la creación/lectura del jugador y el guardado del intento (dejando la evaluación SQL fuera de la transacción).
- `SqlAlchemyPlayerRepository.add` usa `INSERT ... ON CONFLICT (roblox_user_id) DO NOTHING` y `SubmitSolution` relee el jugador para garantizar que el intento quede asociado al `id` ganador persistido ante envíos concurrentes.

### Base de pruebas y resolución Windows → WSL2 (`infrastructure/config.py`, `infrastructure/db.py`)
- `DATABASE_URL` se lee exclusivamente del entorno (o `.env` en local). Las pruebas de integración usan siempre una base separada (`*_test`, p. ej. `tycoon_test`, o `TEST_DATABASE_URL`), rechazando cualquier ejecución sobre la base de desarrollo.
- En Windows, si un servicio PostgreSQL local ocupa el puerto 5432 en `localhost`, `resolve_database_url` detecta la IP de WSL2 (`wsl hostname -I`) como fallback sin modificar `.env`.

### Seed idempotente (`infrastructure/seed.py`)
- Los 3 retos del MVP se siembran de forma idempotente mediante `INSERT ... ON CONFLICT (code) DO UPDATE` con datos de ejemplo (`setup_sql` y `expected_result` provisionales hasta la fase 5).

## Fase 4 — API (FastAPI)

### Autenticación (`api/auth.py`)
- Los endpoints del juego (`/challenges`, `/challenges/{code}/submit`, `/players/{roblox_user_id}/progress`) exigen el encabezado `X-API-Key` leído de `API_KEY` en el entorno.
- Falta de encabezado o valor vacío responde `401`; clave distinta responde `403`. La comparación se hace en tiempo constante con `hmac.compare_digest` sobre UTF-8.
- `GET /health` es público (sin `X-API-Key`) para sondas de disponibilidad de Docker/Render.

### Validación de entrada y límite de SQL (`api/schemas.py`)
- `SubmitSolutionRequest` rechaza campos extra (`extra="forbid"`), exige `roblox_user_id > 0` y fija `MAX_SQL_LENGTH = 8000` caracteres (en la fase 5 se reforzará este límite en el sandbox SQL).
- Un envío solo con espacios pasa la longitud mínima de Pydantic y lo rechaza `SubmitSolution` con `EmptySubmission`, mapeado a `422`.

### Errores y separación de capas (`api/app.py`, `api/routers.py`, `api/dependencies.py`)
- Los routers no contienen lógica de negocio: solo reciben entrada validada, llaman al caso de uso y serializan el DTO de salida.
- `EmptySubmission` → `422`, `ChallengeNotFound` → `404` y `EvaluatorUnavailable` → `503`, todos con mensajes fijos en español en `ErrorResponse(detail=...)` sin filtrar trazas, hosts ni credenciales internas.
- Hasta la fase 5, la dependencia por defecto `get_solution_evaluator` devuelve un adaptador que lanza `EvaluatorError`, traducido limpiamente a `503`.

## Fase 5 — Sandbox SQL y los 3 retos del MVP

### Aislamiento de rol y esquema (`infrastructure/sandbox.py`)
- **Conexión independiente de permisos mínimos (`tycoon_sandbox_player`):** en vez de usar `SET LOCAL ROLE` sobre la conexión administradora (`tycoon`), se abre una segunda conexión TCP autenticada directamente como `tycoon_sandbox_player` (sin privilegios de superusuario, creación, herencia ni bypass RLS, y con contraseña aleatoria en memoria). Así `session_user` tampoco tiene privilegios y resulta imposible escapar con `RESET ROLE` o `SET ROLE`.
- **Esquema desechable por intento (`sandbox_<hex>`):** la conexión administradora crea el esquema temporal, carga `setup_sql`, concede únicamente `USAGE` en el esquema y `SELECT` sobre sus tablas a `tycoon_sandbox_player`, y ejecuta siempre `DROP SCHEMA IF EXISTS ... CASCADE` en un bloque `finally` incluso si la consulta falla.
- **Bloqueo de `public` y funciones peligrosas:** se revocan de `PUBLIC` y `tycoon_sandbox_player` el acceso/creación sobre `public`, `CREATE`/`TEMPORARY` sobre la base de datos y `EXECUTE` sobre `set_config`, `pg_terminate_backend`, `pg_cancel_backend`, `pg_reload_conf`, `pg_read_file*`, `pg_ls_dir*` y `pg_stat_file*`.

### Validación de sentencia única, límites y saneamiento
- **Doble barrera:** `validate_single_select_sql` refuerza `MAX_SQL_LENGTH = 8000`, ignora comentarios/literales para rechazar cualquier `;` intermedio y exige inicio con `SELECT` o `WITH`. Además, la consulta se ejecuta con un cursor nombrado de `psycopg` (`DECLARE ... CURSOR`), que usa el protocolo extendido de PostgreSQL y rechaza múltiples sentencias y comandos no `SELECT`.
- **Límites:** `SET LOCAL statement_timeout` derivado de `challenge.max_seconds`, `lock_timeout = 500ms` y lectura acotada con `fetchmany(max_rows + 1)` (`MAX_RESULT_ROWS = 1000`).
- **Conversión y saneamiento:** `date`, `datetime`, `time` y `UUID` se convierten a `str`; los errores de PostgreSQL se traducen a mensajes en español eliminando el nombre del esquema temporal y los nombres internos de rol.

### Evaluación de plan `EXPLAIN` para el reto 3 (`domain/execution_plan.py`)
- `Challenge.requires_index_plan()` detecta la presencia de `CREATE INDEX` en `setup_sql`.
- Cuando es `True`, `PostgresSandboxEvaluator` ejecuta `EXPLAIN (COSTS OFF)` dentro de la misma transacción aislada y `SubmitSolution` exige resultado coincidente **y** uso de `Index Scan`, `Index Only Scan` o `Bitmap Index Scan` en el plan (`plan_uses_index`).

## Fase 5.5 — Endurecimiento para Neon y preview diagnóstico

### Reto 3 read-only (sin DDL del jugador)
- El índice compuesto `idx_events_user_created` se crea en `setup_sql` y el jugador debe reescribir la consulta para que sea *sargable* y el planificador use `Index Scan` / `Bitmap Index Scan`. Así el sandbox se mantiene 100 % *read-only* (`SELECT` / `WITH` de una sola sentencia, sin DDL ni escritura del jugador), reduciendo la superficie de ataque y manteniendo uniforme la evaluación de resultados + `EXPLAIN`.

### Endurecimiento del sandbox y compatibilidad con Neon (`infrastructure/sandbox.py`)
- **Orden de `EXPLAIN` y medición:** `EXPLAIN (COSTS OFF)` se ejecuta **antes** que el cursor de la consulta del jugador dentro de la transacción de solo lectura (`force_rollback=True`), y `execution_ms` mide únicamente el tiempo de ejecución de la consulta (sin el `EXPLAIN`).
- **Límites de memoria y disco temporal:** en cada transacción del sandbox se fija `SET LOCAL work_mem = '4MB'`. Como `temp_file_limit` es un parámetro de nivel `superuser` (`PGC_SUSET`), se configura en el rol mediante `ALTER ROLE tycoon_sandbox_player SET temp_file_limit = '10MB'` durante el aprovisionamiento (capturando `InsufficientPrivilege` en entornos administrados como Neon donde el dueño de base no es superusuario), evitando intentos repetidos dentro de la sesión del jugador.
- **Compatibilidad con `neon_superuser` y bloqueo léxico de `set_config`:** la revocación sobre `pg_catalog` captura `(UndefinedFunction, InsufficientPrivilege)` y se compensa bloqueando léxicamente cualquier llamada a `set_config(...)` tanto sin comillas como con identificadores entre comillas dobles (`pg_catalog."set_config"(...)`).
- **Parámetros de conexión SSL/query (`_make_conninfo`):** se propagan los parámetros de query de `DATABASE_URL` (p. ej. `sslmode=require`, `channel_binding`), ignorando claves reservadas (`host`, `port`, `dbname`, `user`, `password`, `connect_timeout`) y normalizando valores tupla de SQLAlchemy.

### Preview de salida y feedback diagnóstico (`application/` y `api/`)
- `POST /challenges/{code}/submit` devuelve también `columns` (`list[str]`) y `preview_rows` (`list[list[str]]`, máximo 10 filas de la salida que produjo la **propia** consulta del jugador, formateando `None` como `"NULL"` y truncando celdas > 120 caracteres), sin exponer jamás `expected_result` ni `setup_sql`.
- Cuando la consulta se ejecuta sin error SQL pero el resultado no coincide con `expected_result`, `SubmitSolution` devuelve un diagnóstico accionable en español indicando si difiere el número de columnas, el número de filas, el orden (`ordered=True`) o los valores.

## Fase 6 — Cliente Roblox (Luau)

### Estructura Open Source compatible con Rojo e interfaz programática (`roblox/`)
- Se estructuró `roblox/` con `default.project.json` mapeando `src/shared` (`ReplicatedStorage`), `src/server` (`ServerScriptService`) y `src/client` (`StarterPlayerScripts`), manteniendo separación estricta cliente/servidor.
- Toda la UI (`TerminalGui.client.luau`) se construye programáticamente en Luau para evitar dependencias de archivos binarios `.rbxl` en Git y hacer el cliente 100% auditable y reproducible mediante Rojo o copia manual.
- `src/shared/ChallengeCatalog.luau` incluye metadatos de apoyo (nombres de `PipelineNode_1..3`, esquemas de entrada/salida, plantillas iniciales y 2 pistas progresivas en español), sin incluir jamás soluciones, `expected_result` ni secretos.

### Seguridad HTTP, cuotas y aislamiento multijugador (`roblox/src/server/`)
- **Credenciales solo en servidor:** `ApiClient.luau` busca dinámicamente el módulo local opcional `Secrets` (vía `FindFirstChild`, ignorado por Git) y cae a atributos `BASE_URL` y `API_KEY` en `ServerStorage` para funcionar sin código hardcoded tanto en Rojo local como en Roblox Studio.
- **Protección de cuota `HttpService`:** `ApiClient.luau` cachea `GET /challenges` (TTL 300 s) y `GET /players/{id}/progress` (TTL 15 s, invalidado al aprobar un reto), ejecuta warm-up en segundo plano (`GET /health`) al entrar jugadores (`PlayerAdded` y `Players:GetPlayers()`), y `TerminalServer.server.luau` aplica validación Zero-Trust + bloqueos de concurrencia/cooldown por jugador tanto en `SubmitSql` (3 s) como en `RequestDashboard` (1 s) con limpieza garantizada tras `pcall`.
- **Compatibilidad Local Server de Studio:** Si `player.UserId <= 0` con `RunService:IsStudio() == true`, `TerminalServer` mapea el ID a `900000000 + math.abs(player.UserId)` con advertencia en log; en servidores publicados rechaza todo `UserId <= 0`.
- **Visuales estrictamente locales:** El coloreado de `PipelineNode_1..3` en `Workspace` ocurre únicamente en `TerminalGui.client.luau` para que el avance de un jugador no modifique los nodos visibles para otros jugadores en la misma sesión.

## Fase 7 — Despliegue (Render + Neon) y CI Open Source

### Rol de sandbox externo opcional (`SANDBOX_DATABASE_URL`)
- `PostgresSandboxEvaluator` acepta `sandbox_database_url: str | None` opcional leído vía `get_sandbox_database_url()`.
- Cuando no está definida (entorno local/Docker), mantiene el autoaprovisionamiento de `tycoon_sandbox_player`.
- Cuando sí está definida (p. ej. rol creado en la consola de Neon), omite `CREATE ROLE`/`ALTER ROLE` (evitando errores de privilegios en proveedores gestionados), exige que el usuario sea distinto al de `DATABASE_URL` y vuelve a intentar de forma tolerante (`except InsufficientPrivilege`) los `REVOKE` sobre `public` y funciones de `pg_catalog` como defensa en profundidad.

### Neon Direct Connection vs Pooler y fallback WSL2
- Neon debe conectarse mediante su URL **Direct** (sin `-pooler`) con `?sslmode=require`, porque el sandbox requiere `SET LOCAL`, cursores nombrados en protocolo extendido y aislamiento por transacción incompatibles con el modo *transaction pooling* de PgBouncer.
- `resolve_database_url` en `infrastructure/db.py` solo sondea WSL2 cuando `sys.platform == "win32"` y el host pertenece a `{localhost, 127.0.0.1}`, dejando intactas las URLs en Linux, Render, GitHub Actions y hosts remotos como `*.neon.tech`.

### Arranque reproducible en Render y CI (`scripts/start_prod.sh`, `render.yaml`, `.github/workflows/ci.yml`)
- `.gitattributes` fuerza finales de línea LF en `*.sh` para evitar errores `\r` al desplegar desde Windows hacia Linux/Render.
- `render.yaml` instala `uv` y sincroniza dependencias sin paquetes de desarrollo (`pip install --upgrade uv && uv sync --frozen --no-dev`), y `scripts/start_prod.sh` ejecuta `alembic upgrade head`, `infrastructure.seed` y `uvicorn api.app:app --host 0.0.0.0 --port "${PORT:-8000}"` con `uv run --frozen --offline --no-dev` para no depender de descargas en tiempo de arranque.
- `.github/workflows/ci.yml` levanta `postgres:16-alpine` con healthcheck `pg_isready` y valida `ruff check`, `ruff format --check`, `mypy` y `pytest` en cada `push` y `pull_request`.


