# Política de Seguridad — Data Pipeline Tycoon

La plataforma ejecuta consultas SQL escritas por jugadores contra PostgreSQL, por lo que el aislamiento del evaluador es una propiedad de seguridad crítica del proyecto.

## Capas de defensa actuales

1. **Separación cliente/servidor en Roblox:** las llamadas HTTP salen únicamente desde scripts de servidor en `roblox/src/server/`. La clave `X-API-Key` nunca se envía al cliente ni se versiona en Git.
2. **Autenticación en tiempo constante:** los endpoints de juego validan `X-API-Key` mediante `hmac.compare_digest`.
3. **Validación léxica estricta (`infrastructure/sandbox.py`):** límite de 8,000 caracteres, una sola sentencia (`SELECT` o `WITH`), rechazo de comentarios/literales encubriendo `;` adicionales y bloqueo explícito de invocaciones a `set_config` (con o sin comillas dobles).
4. **Aislamiento de rol, guard *fail-closed* y esquema efímero:**
   - Las consultas del jugador se ejecutan con una conexión TCP independiente perteneciente a un rol de mínimos privilegios (`tycoon_sandbox_player` en local o el rol dedicado de `SANDBOX_DATABASE_URL` en producción), nunca con el rol administrador de la aplicación.
   - **Verificación *fail-closed* antes de ejecutar SQL:** tras aplicar los `REVOKE`, `PostgresSandboxEvaluator` consulta `pg_roles`, `pg_has_role` y `has_table_privilege` para confirmar que el rol configurado **no** tiene `rolsuper`, `pg_read_all_data`, `pg_write_all_data`, `neon_superuser` ni permiso `SELECT` sobre `public.players`, `public.challenges` o `public.attempts`. Esto bloquea por diseño roles sobre-privilegiados (como los creados desde el botón *"Add Role"* de la UI de Neon, que heredan `neon_superuser`/`pg_read_all_data`), devolviendo HTTP `503` antes de abrir sesión de jugador.
   - Cada evaluación crea un esquema temporal `sandbox_<uuid>`, carga únicamente los datos del reto, concede solo `USAGE` y `SELECT` sobre ese esquema y ejecuta `DROP SCHEMA ... CASCADE` en un bloque `finally`.
   - En PostgreSQL gestionado/local se revoca acceso sobre `public` y funciones peligrosas de `pg_catalog`, y todas las ejecuciones corren dentro de una transacción con `force_rollback=True`.
5. **Límites de recursos:** `statement_timeout` por reto, `lock_timeout = 500ms`, `work_mem = 4MB`, límite de 1,000 filas devueltas con cursor nombrado y saneamiento de mensajes de error de PostgreSQL antes de devolverlos al jugador.

## Alcance de vulnerabilidades reportables

Son especialmente relevantes reportes relacionados con:
- Escape del esquema temporal o lectura/escritura sobre tablas de la aplicación (`players`, `challenges`, `attempts`, `alembic_version`).
- Ejecución de múltiples sentencias, DDL, DML o escalación de privilegios dentro del sandbox SQL.
- Denegación de servicio capaz de agotar memoria/disco o bloquear conexiones de forma persistente pese a los límites configurados.
- Exposición de secretos en artefactos, endpoints o scripts cliente de Roblox.

## Cómo reportar una vulnerabilidad

- **No abras un Issue público** con payloads de explotación o pruebas de concepto activas.
- Reporta el hallazgo de forma privada a través de **GitHub Security Advisories** (*Security -> Advisories -> Report a vulnerability* en el repositorio) o contactando directamente al mantenedor del proyecto.
- Incluye: descripción del vector, pasos mínimos de reproducción y el impacto observado. Responderemos para coordinar la corrección antes de cualquier divulgación pública.
