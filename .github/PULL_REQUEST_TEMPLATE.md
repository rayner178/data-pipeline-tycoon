## Descripción del cambio

<!-- Describe brevemente qué agrega, corrige o mejora este PR y si cierra algún Issue. -->

## Tipo de cambio

- [ ] Nuevo reto SQL en `challenges/<slug>/`
- [ ] Corrección / mejora en backend (`src/`)
- [ ] Mejora en cliente CLI (`src/cli/`) o cliente Roblox (`roblox/`)
- [ ] Documentación / CI / pruebas

## Checklist obligatoria

- [ ] No se agregaron secretos, archivos `.env`, ni `roblox/src/server/Secrets.luau`.
- [ ] Si es un reto nuevo en `challenges/<slug>/`: incluye los 5 archivos (`challenge.toml`, `setup.sql`, `expected_result.json`, `solution.sql`, `wrong_solution.sql`) y `code` en kebab-case coincide con la carpeta.
- [ ] `uv run --frozen --offline ruff check .` y `ruff format --check .` sin errores.
- [ ] `uv run --frozen --offline mypy` sin errores.
- [ ] `uv run --frozen --offline pytest -q` pasa al 100 % (sin omitir ni relajar pruebas).
- [ ] *(Si aplica `roblox/`)* `selene src/` pasa con 0 errores y 0 advertencias.
