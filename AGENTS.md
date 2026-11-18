# Reglas del proyecto para agentes (Data Pipeline Tycoon)

Lee `SPEC.md` antes de cualquier tarea. Si algo contradice el SPEC, detente y pregunta.

## Arquitectura
- Respeta Clean Architecture: `domain` ← `application` ← `infrastructure` / `api`. Las dependencias solo apuntan hacia adentro.
- `domain/` es Python puro: PROHIBIDO importar FastAPI, SQLAlchemy, Pydantic de la capa web o cualquier librería de infraestructura.
- Los casos de uso dependen de interfaces (puertos) definidas en `application/`, nunca de implementaciones concretas.
- Los routers de FastAPI solo validan entrada, llaman a un caso de uso y devuelven la respuesta. Sin lógica de negocio.

## Forma de trabajar
- Una tarea pequeña por vez. No construyas varias capas en una sola entrega.
- Escribe primero las pruebas (`pytest`) y luego la implementación.
- Antes de editar, muestra qué archivos vas a tocar. No modifiques archivos fuera de la tarea.
- No agregues dependencias nuevas sin pedir aprobación y justificarlas.
- No inventes librerías, funciones ni parámetros. Si no estás seguro, indícalo y verifica en la documentación.
- Si falta información, pregunta; no asumas.

## Calidad
- Python 3.12, tipado completo, `ruff` y `mypy` sin errores.
- Nombres en inglés para código; textos de cara al usuario en español.
- Funciones cortas, una responsabilidad por función.
- Cada cambio deja las pruebas existentes en verde.

## Seguridad (no negociable)
- Nunca ejecutes SQL del jugador con el rol principal de la aplicación.
- Nunca ejecutes código Python del jugador en el proceso de la API.
- Sandbox SQL: esquema aislado por intento, rol de permisos mínimos, `statement_timeout`, límite de filas, una sola sentencia.
- Todas las credenciales van en variables de entorno (`.env` fuera de git). Nunca en el código ni en commits.
- Usa consultas parametrizadas en la aplicación; evita construir SQL concatenando cadenas.

## Roblox (Luau)
- Las llamadas HTTP solo desde scripts de servidor. Nada de claves ni secretos en el cliente.
- Pocas llamadas por minuto: agrupa y cachea en el servidor.

## Git
- Un commit por tarea, mensaje en imperativo y claro (`feat:`, `fix:`, `test:`, `docs:`).
- No reescribas el historial ni hagas push forzado.

## Al terminar cada tarea
Resume en 3–5 líneas: qué cambiaste, qué pruebas agregaste y qué falta.
