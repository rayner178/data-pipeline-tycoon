--!strict
--[[
	Server-only HTTP client for the Data Pipeline Tycoon FastAPI backend.
	Reads credentials dynamically from optional `Secrets` ModuleScript or
	`ServerStorage` Attributes, caches challenge definitions, and isolates
	all HttpService calls behind pcall with Spanish player-facing errors.
]]

local HttpService = game:GetService("HttpService")
local ServerStorage = game:GetService("ServerStorage")

local ApiClient = {}

local CHALLENGES_CACHE_TTL_SECONDS = 300
local PROGRESS_CACHE_TTL_SECONDS = 15
local HEALTH_COOLDOWN_SECONDS = 30

export type ChallengeSummary = {
	code: string,
	module: string,
	title: string,
	description: string,
	difficulty: number,
}

export type CompletedChallenge = {
	code: string,
	completed_at: string,
	best_ms: number,
}

export type PlayerProgressData = {
	roblox_user_id: number,
	completed: { CompletedChallenge },
}

export type SubmitOutputData = {
	passed: boolean,
	execution_ms: number?,
	message: string,
	columns: { string },
	preview_rows: { { string } },
}

export type ApiResult<T> = {
	ok: boolean,
	statusCode: number,
	message: string?,
	data: T?,
}

local cachedChallenges: { ChallengeSummary }? = nil
local cachedChallengesAt: number = 0

local progressCacheByUserId: { [number]: { fetchedAt: number, data: PlayerProgressData } } = {}

local warmupInFlight = false
local lastWarmupAttemptAt = 0
local missingConfigWarned = false

local function trimString(value: unknown): string
	if typeof(value) ~= "string" then
		return ""
	end
	return (value:gsub("^%s+", ""):gsub("%s+$", ""))
end

local function normalizeBaseUrl(rawUrl: unknown): string
	local trimmed = trimString(rawUrl)
	return (trimmed:gsub("/+$", ""))
end

local function readRuntimeConfig(): (string, string)
	local baseUrl = ""
	local apiKey = ""

	-- Dynamic lookup so server works whether Secrets.luau exists locally or not.
	local parentFolder = script.Parent
	local secretsInstance = if parentFolder ~= nil then parentFolder:FindFirstChild("Secrets") else nil
	if secretsInstance ~= nil and secretsInstance:IsA("ModuleScript") then
		local ok, loaded = pcall(require, secretsInstance)
		if ok and typeof(loaded) == "table" then
			baseUrl = normalizeBaseUrl(loaded.BASE_URL)
			apiKey = trimString(loaded.API_KEY)
		else
			warn("[DataPipelineTycoon] No se pudo cargar el ModuleScript Secrets:", loaded)
		end
	end

	-- Fallback or override via ServerStorage attributes (ideal for Studio/Cloud without local Secrets.luau).
	if baseUrl == "" then
		baseUrl = normalizeBaseUrl(ServerStorage:GetAttribute("BASE_URL"))
	end
	if apiKey == "" then
		apiKey = trimString(ServerStorage:GetAttribute("API_KEY"))
	end

	return baseUrl, apiKey
end

local function decodeErrorDetail(body: string): string?
	if body == "" then
		return nil
	end
	local ok, decoded = pcall(HttpService.JSONDecode, HttpService, body)
	if not ok or typeof(decoded) ~= "table" then
		return nil
	end
	if typeof(decoded.detail) == "string" and decoded.detail ~= "" then
		return decoded.detail
	end
	return nil
end

local function mapHttpError(statusCode: number, body: string): string
	if statusCode == 401 or statusCode == 403 then
		warn(string.format("[DataPipelineTycoon] Error de autenticación contra backend (HTTP %d).", statusCode))
		return "Error de configuración de acceso con el motor SQL. Avisa al creador de la experiencia."
	elseif statusCode == 404 then
		return "El reto solicitado no existe en el servidor."
	elseif statusCode == 422 then
		local detail = decodeErrorDetail(body)
		if detail ~= nil then
			return detail
		end
		return "La consulta SQL o los datos enviados no son válidos."
	elseif statusCode == 503 then
		return "El motor evaluador SQL está despertando o temporalmente ocupado. Intenta de nuevo en unos segundos."
	elseif statusCode >= 500 then
		return "El servidor de evaluación tuvo un problema interno. Intenta nuevamente más tarde."
	end
	return string.format("No se pudo completar la operación (código %d).", statusCode)
end

local function performRequest(
	method: "GET" | "POST",
	path: string,
	bodyTable: { [string]: any }?,
	requireAuth: boolean
): (boolean, number, any, string?)
	local baseUrl, apiKey = readRuntimeConfig()
	if baseUrl == "" or (requireAuth and apiKey == "") then
		if not missingConfigWarned then
			missingConfigWarned = true
			warn(
				"[DataPipelineTycoon] Configura BASE_URL y API_KEY en ServerScriptService/DataPipelineTycoonServer/Secrets o como Atributos en ServerStorage."
			)
		end
		return false, 0, nil, "El servidor del juego aún no tiene configurada la conexión al motor SQL."
	end

	local headers: { [string]: string } = {
		["Accept"] = "application/json",
	}
	if requireAuth then
		headers["X-API-Key"] = apiKey
	end

	local requestOptions: { [string]: any } = {
		Url = baseUrl .. path,
		Method = method,
		Headers = headers,
	}

	if method == "POST" and bodyTable ~= nil then
		local encodeOk, encodedBody = pcall(HttpService.JSONEncode, HttpService, bodyTable)
		if not encodeOk then
			warn("[DataPipelineTycoon] Error serializando JSON:", encodedBody)
			return false, 0, nil, "No se pudo preparar la consulta para enviarla al servidor."
		end
		headers["Content-Type"] = "application/json"
		requestOptions.Body = encodedBody
	end

	local requestOk, response = pcall(HttpService.RequestAsync, HttpService, requestOptions)
	if not requestOk then
		warn("[DataPipelineTycoon] Fallo de HttpService:", response)
		return false,
			0,
			nil,
			"No se pudo conectar con el motor SQL (verifica HttpService activo y el estado del servidor)."
	end

	local statusCode = response.StatusCode
	local rawBody = response.Body or ""

	if not response.Success then
		return false, statusCode, nil, mapHttpError(statusCode, rawBody)
	end

	if rawBody == "" then
		return true, statusCode, {}, nil
	end

	local decodeOk, decoded = pcall(HttpService.JSONDecode, HttpService, rawBody)
	if not decodeOk then
		warn("[DataPipelineTycoon] Respuesta JSON inválida del backend:", decoded)
		return false, statusCode, nil, "El motor SQL devolvió una respuesta ilegible."
	end

	return true, statusCode, decoded, nil
end

function ApiClient.warmupHealth(): ()
	local now = os.clock()
	if warmupInFlight or (lastWarmupAttemptAt > 0 and (now - lastWarmupAttemptAt) < HEALTH_COOLDOWN_SECONDS) then
		return
	end
	warmupInFlight = true
	lastWarmupAttemptAt = now

	local ok, statusCode = performRequest("GET", "/health", nil, false)
	warmupInFlight = false

	if not ok and statusCode ~= 0 then
		warn(string.format("[DataPipelineTycoon] Warm-up /health respondió HTTP %d.", statusCode))
	end
end

function ApiClient.listChallenges(forceRefresh: boolean?): ApiResult<{ ChallengeSummary }>
	local now = os.clock()
	if
		not forceRefresh
		and cachedChallenges ~= nil
		and (now - cachedChallengesAt) < CHALLENGES_CACHE_TTL_SECONDS
	then
		return {
			ok = true,
			statusCode = 200,
			data = cachedChallenges,
		}
	end

	local ok, statusCode, decoded, errMsg = performRequest("GET", "/challenges", nil, true)
	if not ok then
		return {
			ok = false,
			statusCode = statusCode,
			message = errMsg or "No se pudo obtener la lista de retos.",
		}
	end

	if typeof(decoded) ~= "table" then
		return {
			ok = false,
			statusCode = statusCode,
			message = "Formato inesperado al recibir los retos.",
		}
	end

	cachedChallenges = decoded :: { ChallengeSummary }
	cachedChallengesAt = os.clock()

	return {
		ok = true,
		statusCode = statusCode,
		data = cachedChallenges,
	}
end

function ApiClient.getPlayerProgress(robloxUserId: number, forceRefresh: boolean?): ApiResult<PlayerProgressData>
	local now = os.clock()
	local cached = progressCacheByUserId[robloxUserId]
	if not forceRefresh and cached ~= nil and (now - cached.fetchedAt) < PROGRESS_CACHE_TTL_SECONDS then
		return {
			ok = true,
			statusCode = 200,
			data = cached.data,
		}
	end

	local path = string.format("/players/%d/progress", robloxUserId)
	local ok, statusCode, decoded, errMsg = performRequest("GET", path, nil, true)
	if not ok then
		return {
			ok = false,
			statusCode = statusCode,
			message = errMsg or "No se pudo consultar tu progreso.",
		}
	end

	if typeof(decoded) ~= "table" or typeof(decoded.completed) ~= "table" then
		return {
			ok = false,
			statusCode = statusCode,
			message = "Formato inesperado al recibir el progreso del jugador.",
		}
	end

	local progressData = decoded :: PlayerProgressData
	progressCacheByUserId[robloxUserId] = {
		fetchedAt = os.clock(),
		data = progressData,
	}

	return {
		ok = true,
		statusCode = statusCode,
		data = progressData,
	}
end

function ApiClient.invalidatePlayerProgress(robloxUserId: number): ()
	progressCacheByUserId[robloxUserId] = nil
end

function ApiClient.submitSolution(
	robloxUserId: number,
	challengeCode: string,
	sql: string
): ApiResult<SubmitOutputData>
	local encodedCode = HttpService:UrlEncode(challengeCode)
	local path = string.format("/challenges/%s/submit", encodedCode)

	local ok, statusCode, decoded, errMsg = performRequest("POST", path, {
		roblox_user_id = robloxUserId,
		sql = sql,
	}, true)

	if not ok then
		return {
			ok = false,
			statusCode = statusCode,
			message = errMsg or "No se pudo evaluar la consulta SQL.",
		}
	end

	if typeof(decoded) ~= "table" then
		return {
			ok = false,
			statusCode = statusCode,
			message = "Respuesta inesperada al evaluar la consulta.",
		}
	end

	local payload: SubmitOutputData = {
		passed = decoded.passed == true,
		execution_ms = if typeof(decoded.execution_ms) == "number" then decoded.execution_ms else nil,
		message = if typeof(decoded.message) == "string" then decoded.message else "",
		columns = if typeof(decoded.columns) == "table" then decoded.columns else {},
		preview_rows = if typeof(decoded.preview_rows) == "table" then decoded.preview_rows else {},
	}

	if payload.passed then
		progressCacheByUserId[robloxUserId] = nil
	end

	return {
		ok = true,
		statusCode = statusCode,
		data = payload,
	}
end

return ApiClient
