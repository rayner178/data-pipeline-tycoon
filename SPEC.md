# SPEC — Data Pipeline Tycoon (Monográfico UNICARIBE)

> Fuente de verdad del proyecto. Todo cambio de alcance se registra aquí antes de programarse.

## 1. Objetivo
Plataforma de simulación gamificada para practicar y validar competencias de ingeniería de datos (SQL/PostgreSQL, limpieza de datos, resiliencia de APIs). Cliente visual en Roblox (Luau); backend en Python (FastAPI) con Clean Architecture y PostgreSQL.

## 2. Alcance del MVP (lo único que se construye primero)
- **Un módulo:** Optimización y consultas en PostgreSQL.
- **3 retos** (dificultad creciente), por ejemplo:
  1. Eliminar duplicados con `ROW_NUMBER()`.
  2. Corregir un `JOIN` que multiplica filas.
  3. Acelerar una consulta lenta creando el índice adecuado.
- **3 endpoints:** listar retos, enviar solución, ver progreso.
- **1 terminal interactiva** en Roblox que consume la API.
- Pruebas automatizadas del dominio, de los casos de uso y de la API.

### Fuera del MVP (trabajo futuro, documentarlo como tal)
- Módulo de ejecución de código Python del jugador.
- Módulo de resiliencia de APIs (429/503, exponential backoff) como simulación.
- Ranking, múltiples oficinas 3D, autenticación avanzada.

## 3. Arquitectura (Clean Architecture)
Las dependencias solo apuntan hacia adentro.

```
src/
  domain/          # entidades y reglas puras. NO importa FastAPI, SQLAlchemy ni nada externo
  application/     # casos de uso + interfaces (puertos / repositorios abstractos)
  infrastructure/  # SQLAlchemy, repositorios concretos, sandbox SQL
  api/             # FastAPI: routers, esquemas Pydantic, dependencias
roblox/            # scripts Luau
tests/
  domain/ application/ api/ infrastructure/
```

## 4. Stack
Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy 2 + Alembic · psycopg 3 · PostgreSQL 16 · pytest · ruff · mypy · uv · Docker Compose (desarrollo local).

## 5. Modelo de datos (borrador)
- **Player**: id, roblox_user_id (único), created_at.
- **Challenge**: id, code (único), module, title, description, difficulty, setup_sql, expected_result (JSON), max_seconds.
- **Attempt**: id, player_id, challenge_id, submitted_sql, passed (bool), execution_ms, error_message, created_at.
- **Progress** (derivado o tabla): player_id, challenge_id, completed_at, best_ms.

Reglas de dominio:
- Un reto se considera superado cuando el resultado de la consulta del jugador coincide con `expected_result`.
- Los intentos se guardan siempre; el progreso se calcula a partir del primer intento exitoso.

## 6. Contrato de API (borrador)
| Método | Ruta | Descripción |
|---|---|---|
| GET | `/challenges` | Lista de retos disponibles |
| POST | `/challenges/{code}/submit` | Envía SQL del jugador; devuelve `passed`, `execution_ms`, `message` |
| GET | `/players/{roblox_user_id}/progress` | Retos completados y mejores tiempos |

Autenticación del MVP: encabezado `X-API-Key` (clave secreta compartida con el servidor de Roblox, nunca con el cliente).

## 7. Seguridad del sandbox SQL (obligatorio)
- Cada jugador ejecuta en un **esquema aislado** que se crea y se destruye por intento.
- Rol de base de datos de **permisos mínimos** (sin DDL fuera de su esquema, sin acceso a tablas de la aplicación).
- `statement_timeout` y límite de filas devueltas.
- Una sola sentencia por envío; rechazar múltiples sentencias.
- Nunca ejecutar SQL del jugador con el rol principal de la aplicación.
- Nunca ejecutar código Python del jugador dentro del proceso de FastAPI.

## 8. Integración con Roblox
- Las llamadas HTTP salen **solo desde scripts de servidor** (`HttpService` activado en el juego).
- El cliente de Roblox nunca recibe ni conoce la clave de la API.
- Pocas llamadas por minuto (hay límite de solicitudes de HttpService); agrupar y cachear en el servidor.

## 9. Despliegue (costo cero con salvedades)
- API: Render (plan gratuito; se duerme tras 15 min, el primer request tarda 30–60 s). Documentar el cold start.
- Base de datos: Neon (PostgreSQL gratuito permanente; escala a cero).
- Licencia MIT, repositorio público en GitHub.

## 10. Evaluación del proyecto (completar con el asesor)
- Métricas: tasa de retos superados, tiempo por reto, cobertura de pruebas, percepción de utilidad (encuesta breve a compañeros de UNICARIBE).
- Rúbrica: pendiente de definir.

## 11. Plan por fases
1. Repositorio + SPEC + AGENTS.md + Docker Compose con PostgreSQL.
2. Dominio y casos de uso con pruebas (sin base de datos).
3. Persistencia y migraciones (Alembic).
4. API FastAPI (3 endpoints) con pruebas.
5. Sandbox SQL + los 3 retos con su evaluador.
6. Cliente Roblox (una terminal).
7. Despliegue y prueba de cold start.
8. Pruebas con usuarios y redacción de resultados.

## 12. Definición de "terminado" por tarea
- Código con tipos, `ruff` y `mypy` sin errores.
- Pruebas nuevas pasando; ninguna prueba previa rota.
- Sin credenciales en el repositorio.
- Un commit con mensaje claro por tarea.
