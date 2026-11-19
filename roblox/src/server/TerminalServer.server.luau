--!strict
--[[
	Server coordinator for the Data Pipeline Tycoon SQL terminal.
	Creates RemoteEvents, enforces Zero-Trust input validation, rate limits and
	per-player concurrency locks, runs health warm-up on player join, and never
	mutates shared Workspace nodes (visual progress is strictly client-local).
]]

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")

local SharedFolder = ReplicatedStorage:WaitForChild("DataPipelineTycoon")
local Remotes = require(SharedFolder:WaitForChild("Remotes"))
local ApiClient = require(script.Parent:WaitForChild("ApiClient"))

local STUDIO_TEST_USER_BASE = 900000000

local function ensureRemoteFolder(): Folder
	local existing = ReplicatedStorage:FindFirstChild(Remotes.FOLDER_NAME)
	if existing ~= nil and existing:IsA("Folder") then
		return existing
	end
	local folder = Instance.new("Folder")
	folder.Name = Remotes.FOLDER_NAME
	folder.Parent = ReplicatedStorage
	return folder
end

local function ensureRemoteEvent(folder: Folder, eventName: string): RemoteEvent
	local existing = folder:FindFirstChild(eventName)
	if existing ~= nil and existing:IsA("RemoteEvent") then
		return existing
	end
	local remote = Instance.new("RemoteEvent")
	remote.Name = eventName
	remote.Parent = folder
	return remote
end

local remoteFolder = ensureRemoteFolder()
local requestDashboardRemote = ensureRemoteEvent(remoteFolder, Remotes.EVENTS.REQUEST_DASHBOARD)
local dashboardLoadedRemote = ensureRemoteEvent(remoteFolder, Remotes.EVENTS.DASHBOARD_LOADED)
local submitSqlRemote = ensureRemoteEvent(remoteFolder, Remotes.EVENTS.SUBMIT_SQL)
local submissionResultRemote = ensureRemoteEvent(remoteFolder, Remotes.EVENTS.SUBMISSION_RESULT)

local submitInFlightByUserId: { [number]: boolean } = {}
local lastSubmitAtByUserId: { [number]: number } = {}
local dashboardInFlightByUserId: { [number]: boolean } = {}
local lastDashboardAtByUserId: { [number]: number } = {}
local warnedStudioUserIds: { [number]: boolean } = {}

local function resolveBackendUserId(player: Player): number?
	local rawId = player.UserId
	if rawId > 0 then
		return rawId
	end

	if RunService:IsStudio() then
		local studioTestId = STUDIO_TEST_USER_BASE + math.abs(rawId)
		if not warnedStudioUserIds[rawId] then
			warnedStudioUserIds[rawId] = true
			warn(
				string.format(
					"[DataPipelineTycoon] Player %s tiene UserId=%d en Studio; usando ID determinista de prueba %d.",
					player.Name,
					rawId,
					studioTestId
				)
			)
		end
		return studioTestId
	end

	return nil
end

local function validateChallengeCode(rawCode: unknown): (boolean, string)
	if typeof(rawCode) ~= "string" then
		return false, "Código de reto inválido."
	end
	if #rawCode < 1 or #rawCode > Remotes.LIMITS.MAX_CODE_LENGTH then
		return false, "Longitud del código de reto inválida."
	end
	if string.match(rawCode, "^[a-z0-9][a-z0-9%-_]*$") == nil then
		return false, "El código de reto contiene caracteres no permitidos."
	end
	return true, rawCode
end

local function validateSqlInput(rawSql: unknown): (boolean, string)
	if typeof(rawSql) ~= "string" then
		return false, "La consulta SQL debe ser texto."
	end
	if #rawSql > Remotes.LIMITS.MAX_SQL_LENGTH then
		return false, string.format("La consulta SQL excede el máximo de %d caracteres.", Remotes.LIMITS.MAX_SQL_LENGTH)
	end
	local trimmed = (rawSql:gsub("^%s+", ""):gsub("%s+$", ""))
	if trimmed == "" then
		return false, "Escribe una consulta SELECT antes de ejecutar."
	end
	return true, rawSql
end

local function onPlayerAdded(player: Player): ()
	resolveBackendUserId(player)
	task.spawn(ApiClient.warmupHealth)
end

local function onPlayerRemoving(player: Player): ()
	local userId = resolveBackendUserId(player)
	if userId ~= nil then
		submitInFlightByUserId[userId] = nil
		lastSubmitAtByUserId[userId] = nil
		dashboardInFlightByUserId[userId] = nil
		lastDashboardAtByUserId[userId] = nil
		ApiClient.invalidatePlayerProgress(userId)
	end
end

Players.PlayerAdded:Connect(onPlayerAdded)
Players.PlayerRemoving:Connect(onPlayerRemoving)
for _, existingPlayer in Players:GetPlayers() do
	onPlayerAdded(existingPlayer)
end

requestDashboardRemote.OnServerEvent:Connect(function(player: Player, options: unknown)
	local userId = resolveBackendUserId(player)
	if userId == nil then
		dashboardLoadedRemote:FireClient(player, {
			ok = false,
			message = "No se pudo verificar tu cuenta de Roblox.",
		})
		return
	end

	local forceRefresh = false
	if typeof(options) == "table" and (options :: { [string]: any }).forceRefresh == true then
		forceRefresh = true
	end

	if dashboardInFlightByUserId[userId] then
		dashboardLoadedRemote:FireClient(player, {
			ok = false,
			busy = true,
			message = "Ya se está cargando el panel de retos.",
		})
		return
	end

	local now = os.clock()
	local lastAt = lastDashboardAtByUserId[userId]
	if lastAt ~= nil then
		local elapsed = now - lastAt
		if elapsed < Remotes.LIMITS.DASHBOARD_COOLDOWN_SECONDS then
			dashboardLoadedRemote:FireClient(player, {
				ok = false,
				busy = true,
				message = "Espera un momento antes de actualizar de nuevo.",
			})
			return
		end
	end

	dashboardInFlightByUserId[userId] = true
	lastDashboardAtByUserId[userId] = now

	local callOk, callErr = pcall(function()
		local challengesRes = ApiClient.listChallenges(forceRefresh)
		if not challengesRes.ok or challengesRes.data == nil then
			dashboardLoadedRemote:FireClient(player, {
				ok = false,
				message = challengesRes.message or "No se pudieron cargar los retos.",
			})
			return
		end

		local progressRes = ApiClient.getPlayerProgress(userId, forceRefresh)
		local completedList = {}
		local progressWarning: string? = nil
		if progressRes.ok and progressRes.data ~= nil then
			completedList = progressRes.data.completed
		else
			progressWarning = progressRes.message
		end

		if player.Parent ~= Players then
			return
		end

		dashboardLoadedRemote:FireClient(player, {
			ok = true,
			challenges = challengesRes.data,
			completed = completedList,
			progressWarning = progressWarning,
		})
	end)

	dashboardInFlightByUserId[userId] = nil

	if not callOk then
		warn("[DataPipelineTycoon] Error inesperado en RequestDashboard:", callErr)
		if player.Parent == Players then
			dashboardLoadedRemote:FireClient(player, {
				ok = false,
				message = "Error interno del servidor al cargar los retos.",
			})
		end
	end
end)

submitSqlRemote.OnServerEvent:Connect(function(player: Player, rawCode: unknown, rawSql: unknown)
	local userId = resolveBackendUserId(player)
	if userId == nil then
		submissionResultRemote:FireClient(player, {
			ok = false,
			message = "No se pudo verificar tu cuenta de Roblox.",
		})
		return
	end

	local codeOk, codeOrErr = validateChallengeCode(rawCode)
	if not codeOk then
		submissionResultRemote:FireClient(player, {
			ok = false,
			message = codeOrErr,
		})
		return
	end
	local challengeCode = codeOrErr

	local sqlOk, sqlOrErr = validateSqlInput(rawSql)
	if not sqlOk then
		submissionResultRemote:FireClient(player, {
			ok = false,
			challengeCode = challengeCode,
			message = sqlOrErr,
		})
		return
	end
	local sql = sqlOrErr

	if submitInFlightByUserId[userId] then
		submissionResultRemote:FireClient(player, {
			ok = false,
			challengeCode = challengeCode,
			message = "Ya hay una evaluación en curso. Espera la respuesta antes de enviar otra.",
		})
		return
	end

	local now = os.clock()
	local lastSubmit = lastSubmitAtByUserId[userId]
	if lastSubmit ~= nil then
		local elapsed = now - lastSubmit
		if elapsed < Remotes.LIMITS.SUBMIT_COOLDOWN_SECONDS then
			local remaining = Remotes.LIMITS.SUBMIT_COOLDOWN_SECONDS - elapsed
			submissionResultRemote:FireClient(player, {
				ok = false,
				challengeCode = challengeCode,
				message = string.format("Espera %.1f s antes de ejecutar otra consulta.", remaining),
			})
			return
		end
	end

	submitInFlightByUserId[userId] = true
	lastSubmitAtByUserId[userId] = now

	local callOk, callErr = pcall(function()
		local submitRes = ApiClient.submitSolution(userId, challengeCode, sql)
		if player.Parent ~= Players then
			return
		end

		if not submitRes.ok or submitRes.data == nil then
			submissionResultRemote:FireClient(player, {
				ok = false,
				challengeCode = challengeCode,
				message = submitRes.message or "No se pudo evaluar la consulta SQL.",
			})
			return
		end

		local resultData = submitRes.data
		local completedList = nil
		if resultData.passed then
			local progressRes = ApiClient.getPlayerProgress(userId, true)
			if progressRes.ok and progressRes.data ~= nil then
				completedList = progressRes.data.completed
			end
		end

		if player.Parent ~= Players then
			return
		end

		submissionResultRemote:FireClient(player, {
			ok = true,
			challengeCode = challengeCode,
			passed = resultData.passed,
			execution_ms = resultData.execution_ms,
			message = resultData.message,
			columns = resultData.columns,
			preview_rows = resultData.preview_rows,
			completed = completedList,
		})
	end)

	submitInFlightByUserId[userId] = nil

	if not callOk then
		warn("[DataPipelineTycoon] Error inesperado en SubmitSql:", callErr)
		if player.Parent == Players then
			submissionResultRemote:FireClient(player, {
				ok = false,
				challengeCode = challengeCode,
				message = "Error interno del servidor al procesar tu consulta.",
			})
		end
	end
end)
