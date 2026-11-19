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
- **No finitos:** `NaN`, `sNaN` e `±Infinity` nunca coinciden, ni siquiera consigo mismos. Un `Challenge` rechaza un `expected_result` que los contenga, para que ningún reto sea imposible de superar.
- **Texto:** comparación exacta; distingue mayúsculas y espacios.
- **Tipos:** se admiten `str`, `int`, `float`, `Decimal`, `bool` y `None`. Las fechas, `UUID` y otros tipos de PostgreSQL los convierte la infraestructura (fase 5).
- `Challenge` guarda `expected_result` como tupla de tuplas (inmutable) y exige que todas las filas tengan el mismo número de columnas.

### Tiempo límite
- `max_seconds` no afecta a `passed` en el dominio: `passed` depende solo del resultado (SPEC §5). El sandbox aplica el límite como `statement_timeout` (fase 5).

### Progreso (`domain/progress.py`)
- Por reto: `completed_at` es la fecha del primer intento exitoso y `best_ms` es el menor `execution_ms` entre los intentos exitosos. Los intentos fallidos no cuentan para el mejor tiempo.
- Un intento exitoso siempre tiene `execution_ms` y nunca tiene `error_message`.
- El resultado se ordena por `completed_at` y, en caso de empate, por `challenge_id`.
- Recibir intentos de otro jugador es un error (`DomainValidationError`).

### Reto 3 (índice)
- No se puede validar solo por el resultado: la consulta devuelve las mismas filas con o sin índice. En la fase 5 se evaluará además con el plan de ejecución (`EXPLAIN`), y `SubmitSolution` combinará ambas reglas: resultado correcto **y** plan que usa el índice esperado.
