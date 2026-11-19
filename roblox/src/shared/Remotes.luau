--!strict
--[[
	Shared constants for RemoteEvents and Zero-Trust validation limits.
	Never store API keys, base URLs, or secrets in ReplicatedStorage.
]]

local Remotes = {}

Remotes.FOLDER_NAME = "DataPipelineTycoonRemotes"

Remotes.EVENTS = {
	REQUEST_DASHBOARD = "RequestDashboard",
	DASHBOARD_LOADED = "DashboardLoaded",
	SUBMIT_SQL = "SubmitSql",
	SUBMISSION_RESULT = "SubmissionResult",
}

Remotes.LIMITS = {
	MAX_SQL_LENGTH = 8000,
	MAX_CODE_LENGTH = 64,
	SUBMIT_COOLDOWN_SECONDS = 3,
	DASHBOARD_COOLDOWN_SECONDS = 1,
}

return Remotes
