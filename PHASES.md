# PHASES.md — Plan de fases con puertas de verificación

Regla: **no se avanza a la siguiente fase sin pasar la puerta de verificación y sin aprobación del dueño del proyecto.**
Al terminar cada fase el agente debe reportar la lista de comprobación marcando cada punto como CUMPLE / NO CUMPLE, con evidencia (salida de comandos).

## Puerta estándar (se aplica a TODAS las fases)
Comandos (deben terminar sin errores):
```
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
git status          # árbol limpio, todo commiteado
git log --oneline   # un commit por tarea, mensajes claros
```
Comprobaciones manuales:
- [ ] No se tocó nada fuera del alcance de la fase.
- [ ] No hay credenciales ni `.env` en git (`git ls-files`).
- [ ] Capas respetadas: `domain` no importa nada externo; `application` no importa FastAPI ni SQLAlchemy.
- [ ] Hay pruebas nuevas, incluidos casos negativos.
- [ ] Ninguna prueba previa se rompió ni se borró para "hacer pasar" el resultado.

---

## Fase 2 — Dominio y casos de uso (sin base de datos)
**Modelo sugerido:** Claude Opus 5.5 (diseño); Orchestrator (Argon) o Sonnet 5.5 para el resto.

### Tarea 2.1 — `domain/`
```
Lee SPEC.md, AGENTS.md y PHASES.md. Fase 2, tarea 1: SOLO domain/, sin frameworks.
- Entidades Player, Challenge, Attempt (sección 5 del SPEC), con dataclasses.
- Servicio de dominio que decide si un resultado coincide con expected_result. Define y documenta qué pasa con el orden de filas, None y decimales.
- Reglas: un reto se supera cuando el resultado coincide; el progreso se calcula desde el primer intento exitoso.
- Pruebas primero en tests/domain/ (incluye casos negativos).
- Muéstrame el plan antes de crear archivos. No toques application/, infrastructure/ ni api/.
```
Puerta extra:
- [ ] `domain/` solo usa la librería estándar.
- [ ] La comparación de resultados está definida y probada (orden, None, decimales).
- [ ] Casos: sin intentos, varios fallos antes del acierto, resultado distinto.

### Tarea 2.2 — Puertos y casos de uso
```
Fase 2, tarea 2: application/. Define puertos (interfaces abstractas) para repositorios y para el evaluador de SQL. Implementa los casos de uso ListChallenges, SubmitSolution y GetProgress. Pruebas con repositorios falsos en memoria (en tests/, no en src/). Plan primero.
```
Puerta extra:
- [ ] Los casos de uso dependen solo de puertos, nunca de implementaciones.
- [ ] SubmitSolution guarda SIEMPRE el intento (acierto o fallo).
- [ ] Pruebas de cada caso de uso, incluido reto inexistente y jugador nuevo.

### Tarea 2.3 — Cierre de fase
Revisión completa de 2.1 y 2.2, limpieza y documentación de decisiones en `docs/decisions.md` (breve).

---

## Fase 3 — Persistencia y migraciones
**Requisito:** Docker levantado en Ubuntu (`sudo service docker start`, luego `docker compose up -d`).
```
Fase 3: infrastructure/ con SQLAlchemy 2 y Alembic.
- Modelos ORM separados de las entidades de dominio, con mapeo explícito.
- Repositorios que implementan los puertos.
- Migración inicial con Alembic para Player, Challenge, Attempt.
- Pruebas de integración contra PostgreSQL real (docker compose), aisladas y repetibles.
- Seed de los 3 retos del MVP en una migración o script aparte.
Plan primero. Pide aprobación antes de cualquier comando de docker o de instalación.
```
Puerta extra:
- [ ] `alembic upgrade head` y `alembic downgrade base` funcionan.
- [ ] Las pruebas de integración usan una base de pruebas, no la de desarrollo.
- [ ] Consultas parametrizadas; ningún SQL armado por concatenación.
- [ ] `DATABASE_URL` sale de variables de entorno.

---

## Fase 4 — API (FastAPI)
```
Fase 4: api/ con FastAPI. Agrega uvicorn (pídeme aprobación).
- Endpoints de la sección 6 del SPEC: GET /challenges, POST /challenges/{code}/submit, GET /players/{roblox_user_id}/progress, más GET /health.
- Autenticación por encabezado X-API-Key leída de variable de entorno; comparación en tiempo constante.
- Esquemas Pydantic de entrada/salida; inyección de dependencias hacia los casos de uso.
- Pruebas con TestClient, incluida la ausencia o error de la clave.
Plan primero.
```
Puerta extra:
- [ ] Los routers no contienen lógica de negocio.
- [ ] Sin clave o con clave incorrecta responde 401/403 en todos los endpoints protegidos.
- [ ] `/docs` (OpenAPI) coincide con el contrato del SPEC.
- [ ] Los mensajes de error no filtran detalles internos.

---

## Fase 5 — Sandbox SQL y los 3 retos  (la fase más crítica)
**Modelo sugerido:** Claude Opus 5.5. Revisión obligatoria por una persona y, de ser posible, por un modelo distinto.
```
Fase 5: sandbox SQL y evaluador, según la sección 7 del SPEC.
- Esquema aislado por intento, creado y destruido en cada ejecución.
- Rol de base de datos de permisos mínimos para ejecutar el SQL del jugador; nunca el rol principal.
- statement_timeout, límite de filas devueltas, una sola sentencia por envío.
- Los 3 retos con sus datos de prueba y expected_result.
- Pruebas de seguridad: intentar leer tablas de la aplicación, DROP/ALTER fuera del esquema, múltiples sentencias, pg_sleep largo, resultado gigante, funciones peligrosas.
Plan primero y explica cada decisión de seguridad.
```
Puerta extra:
- [ ] Todas las pruebas de ataque fallan como deben (el ataque es bloqueado).
- [ ] El rol del sandbox no puede ver ni modificar tablas de la aplicación.
- [ ] Un envío lento o enorme termina con error controlado, sin colgar la API.
- [ ] El esquema temporal se elimina incluso si la consulta falla.
- [ ] Cada reto tiene al menos una solución correcta y una incorrecta probadas.

---

## Fase 6 — Cliente Roblox
Nota: el código Luau no se prueba con pytest; se prueba a mano en Roblox Studio.
```
Fase 6: roblox/. Un ServerScript que use HttpService para llamar a la API y una terminal interactiva (TextBox) para enviar SQL. La clave de la API solo vive en el servidor. Agrupa/cachea llamadas y maneja errores y tiempos de espera. Documenta en roblox/README.md cómo activar HttpService y configurar la URL y la clave.
```
Puerta extra:
- [ ] La clave de la API no aparece en ningún script de cliente ni en el repositorio.
- [ ] El servidor no confía en datos del cliente (valida longitud y tipo antes de enviar).
- [ ] Probado en Studio: reto correcto, reto incorrecto, API caída, API lenta.

---

## Fase 7 — Despliegue (Render + Neon)
```
Fase 7: preparar despliegue. Comando de arranque con uvicorn, variables de entorno, migraciones en el despliegue, cadena de conexión de Neon con SSL, /health. Documenta en README.md los pasos y el efecto del cold start de Render gratuito (el servicio se duerme tras 15 min).
```
Puerta extra:
- [ ] Ningún secreto en el repositorio; todo por variables de entorno del proveedor.
- [ ] `/health` responde en producción.
- [ ] Se midió el tiempo del primer request tras dormirse (dato para la tesis).
- [ ] Roblox funciona contra la URL pública.

---

## Fase 8 — Pruebas con usuarios y cierre
- [ ] Prueba con un grupo pequeño de compañeros (consentimiento y anonimato).
- [ ] Métricas del SPEC sección 10 recogidas: retos superados, tiempo por reto, encuesta breve.
- [ ] Rúbrica de evaluación acordada con el asesor.
- [ ] README final, licencia MIT, repositorio limpio.
- [ ] Auditoría final del proyecto completo (arquitectura, seguridad, pruebas) antes de la entrega.
