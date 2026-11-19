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
