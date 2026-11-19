# Cliente Roblox — Data Pipeline Tycoon

Cliente Luau Open Source compatible con [Rojo](https://rojo.space/) para jugar a **Data Pipeline Tycoon** desde Roblox Studio o una experiencia publicada, conectado de forma segura al backend FastAPI.

## Estructura (`roblox/`)

```text
roblox/
├── default.project.json            # Mapeo Rojo -> ReplicatedStorage / ServerScriptService / StarterPlayerScripts
├── README.md
└── src/
    ├── shared/                     # ReplicatedStorage.DataPipelineTycoon (sin secretos ni soluciones)
    │   ├── Remotes.luau            # Nombres de RemoteEvents y límites compartidos
    │   └── ChallengeCatalog.luau   # Esquemas de tablas, plantillas iniciales y pistas por reto
    ├── server/                     # ServerScriptService.DataPipelineTycoonServer (único origen HTTP)
    │   ├── Secrets.example.luau    # Plantilla segura (copiar a Secrets.luau, ignorado por git)
    │   ├── ApiClient.luau          # Cliente HttpService con cache, warm-up y manejo de errores en español
    │   └── TerminalServer.server.luau # Validación Zero-Trust, cooldowns, concurrencia y manejo Studio UserId<=0
    └── client/                     # StarterPlayerScripts.DataPipelineTycoonClient
        └── TerminalGui.client.luau # Terminal SQL programática, tabla preview_rows y nodos locales
```

## Principios de seguridad aplicados

- **Cero secretos en el cliente ni en Git:** `API_KEY` y `BASE_URL` viven únicamente en el servidor (`Secrets.luau` ignorado por `.gitignore` o atributos de `ServerStorage`).
- **Validación Zero-Trust en servidor:** el cliente solo envía `(challengeCode, sql)` por `RemoteEvent`; el servidor valida tipos, patrón del código de reto, longitud SQL (`1..8000`), concurrencia por jugador y cooldown (3 s entre envíos, 1 s en recarga de panel). El `roblox_user_id` siempre se deriva de `player.UserId` en servidor.
- **Visuales aislados por jugador:** `PipelineNode_1..3` en `Workspace` se colorean **solo en el cliente** (`TerminalGui.client.luau`), evitando que el progreso de un jugador altere visualmente el pipeline de otros jugadores en el mismo servidor.

---

## Instalación en Roblox Studio

### Opción 1: Con Rojo (recomendado)

1. Instala [Rojo](https://rojo.space/docs/v7/getting-started/installation/) y el plugin **Rojo** en Roblox Studio.
2. En una terminal dentro de `roblox/`, inicia el servidor de sincronización:
   ```bash
   rojo serve default.project.json
   ```
3. Abre un place nuevo (ej. Baseplate) en Roblox Studio, abre el plugin de Rojo y haz clic en **Connect** (`localhost:34872`).

### Opción 2: Sin Rojo (copia manual en Studio)

Si prefieres no instalar Rojo, crea la siguiente jerarquía en Roblox Studio copiando el contenido de cada archivo `.luau`:

1. En `ReplicatedStorage`, crea un `Folder` llamado **`DataPipelineTycoon`**:
   - Dentro, crea `ModuleScript` **`Remotes`** <- `src/shared/Remotes.luau`
   - Dentro, crea `ModuleScript` **`ChallengeCatalog`** <- `src/shared/ChallengeCatalog.luau`
2. En `ServerScriptService`, crea un `Folder` llamado **`DataPipelineTycoonServer`**:
   - Dentro, crea `ModuleScript` **`ApiClient`** <- `src/server/ApiClient.luau`
   - Dentro, crea `Script` **`TerminalServer`** <- `src/server/TerminalServer.server.luau`
3. En `StarterPlayer` -> `StarterPlayerScripts`, crea un `Folder` llamado **`DataPipelineTycoonClient`**:
   - Dentro, crea `LocalScript` **`TerminalGui`** <- `src/client/TerminalGui.client.luau`

---

## Configuración obligatoria antes de dar Play

### 1. Habilitar `HttpService`

En Roblox Studio:
- Ve a **Home -> Game Settings -> Security** y activa **Allow HTTP Requests** (`ON`).
- *(Alternativa rápida si el place aún no está guardado en la nube)*: ejecuta en la **Command Bar** de Studio:
  ```lua
  game:GetService("HttpService").HttpEnabled = true
  ```

### 2. Configurar `BASE_URL` y `API_KEY` en el servidor

El servidor busca la configuración primero en un `ModuleScript` opcional llamado `Secrets` junto a `ApiClient`, y si no existe o está vacío, usa atributos en **`ServerStorage`**. Elige **una** de las dos opciones:

- **Opción A — Archivo local (con Rojo):**
  1. Copia `roblox/src/server/Secrets.example.luau` a `roblox/src/server/Secrets.luau` (ya está en `.gitignore`).
  2. Rellena `BASE_URL` y `API_KEY` con la clave configurada en tu backend FastAPI.

- **Opción B — Atributos en `ServerStorage` (sin archivo local):**
  1. Selecciona **`ServerStorage`** en el Explorer de Studio.
  2. En la ventana **Properties -> Attributes**, crea dos atributos de tipo **`string`**:
     - `BASE_URL`: URL HTTPS pública de tu API (sin `/` final).
     - `API_KEY`: clave secreta del encabezado `X-API-Key`.

> **Importante sobre `localhost` / `127.0.0.1`:**
> `HttpService` de Roblox **bloquea por seguridad peticiones a `localhost`, `127.0.0.1` e IPs privadas** incluso dentro de Roblox Studio.
> Para probar contra tu backend FastAPI corriendo localmente en el puerto `8000`, expón el puerto con un túnel HTTPS temporal y coloca la URL HTTPS generada en `BASE_URL`:
> - Con Cloudflare Tunnel: `cloudflared tunnel --url http://127.0.0.1:8000`
> - Con ngrok: `ngrok http 8000`
> - O bien apunta directamente a la URL HTTPS desplegada en Render (Fase 7).

### 3. Nodos visuales opcionales en `Workspace`

Si quieres ver los nodos 3D iluminarse según tu progreso:
1. Crea tres `Part` (o `Model` con `BasePart` hijos) directamente dentro de **`Workspace`**.
2. Nómbralos exactamente:
   - `PipelineNode_1` (se enciende con `dedupe-row-number`)
   - `PipelineNode_2` (se enciende con `fix-multiplying-join`)
   - `PipelineNode_3` (se enciende con `index-slow-query`)
3. Al cargar el juego se teñirán en rojo (pendiente) o verde (completado) solo en tu pantalla. Si no existen en `Workspace`, la terminal funciona sin errores.

> **Nota sobre Local Server en Studio (`UserId <= 0`):**
> Al probar con *Test -> Local Server* en Studio, Roblox asigna `UserId <= 0` (`0`, `-1`, `-2`...). Cuando `RunService:IsStudio()` es `true`, `TerminalServer` asigna un ID positivo determinista (`900000000 + |UserId|`) y registra un `warn` en Output para poder guardar y consultar progreso contra el backend. Fuera de Studio, cualquier `UserId <= 0` es rechazado.

---

## Pruebas manuales de verificación (Puerta de Fase 6)

Presiona **Play** en Roblox Studio (la terminal abre automáticamente y puedes minimizarla/abrirla con el botón superior o **`F2`**) y valida estos 4 escenarios:

1. **Reto correcto (`dedupe-row-number`):**
   - Selecciona el primer reto y envía una consulta con `ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY updated_at DESC)`.
   - **Esperado:** Banner verde con `execution_ms`, tabla inferior mostrando columnas `(customer_id, full_name, email)` y filas de tu salida, reto marcado con `✓` y `Mejor: X ms`, nodo `PipelineNode_1` en verde (si existe). Recarga o reinicia Play y confirma que sigue completado.
2. **Reto incorrecto:**
   - Selecciona `fix-multiplying-join` y presiona **Ejecutar SQL** con la plantilla inicial defectuosa (o escribe una consulta con sintaxis SQL inválida).
   - **Esperado:** Banner rojo con diagnóstico claro en español (sin revelar la respuesta correcta ni `setup_sql`) y, si el SQL fue válido, tabla inferior mostrando hasta 10 filas de tu propia salida errónea.
3. **API caída / túnel detenido:**
   - Detén temporalmente el backend o el túnel HTTPS y presiona **Ejecutar SQL** o **Actualizar**.
   - **Esperado:** El botón vuelve a habilitarse, el cliente muestra un mensaje legible en español indicando que no se pudo conectar con el motor SQL, y en Output no se filtran claves ni stacktraces al jugador.
4. **API lenta / cold start (> 2 s):**
   - Simula latencia > 2 segundos en el servidor (o prueba en el primer arranque tras reposo de Render) y ejecuta una consulta.
   - **Esperado:** Mientras dura la llamada, el botón **Ejecutar SQL** queda bloqueado (`Evaluando...`) y tras 2 segundos el indicador de estado cambia a *"Conectando con el motor SQL..."* hasta recibir respuesta.
