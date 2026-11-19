--!strict
--[[
	Programmatic Roblox SQL Terminal GUI & client-local PipelineNode coloring.
	Communicates strictly through RemoteEvents in ReplicatedStorage.
	Never reads or stores secrets, and never mutates shared server state.
]]

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local UserInputService = game:GetService("UserInputService")
local Workspace = game:GetService("Workspace")

local localPlayer = Players.LocalPlayer
local playerGui = localPlayer:WaitForChild("PlayerGui")

local SharedFolder = ReplicatedStorage:WaitForChild("DataPipelineTycoon")
local Remotes = require(SharedFolder:WaitForChild("Remotes"))
local ChallengeCatalog = require(SharedFolder:WaitForChild("ChallengeCatalog"))

local remoteFolder = ReplicatedStorage:WaitForChild(Remotes.FOLDER_NAME)
local requestDashboardRemote = remoteFolder:WaitForChild(Remotes.EVENTS.REQUEST_DASHBOARD) :: RemoteEvent
local dashboardLoadedRemote = remoteFolder:WaitForChild(Remotes.EVENTS.DASHBOARD_LOADED) :: RemoteEvent
local submitSqlRemote = remoteFolder:WaitForChild(Remotes.EVENTS.SUBMIT_SQL) :: RemoteEvent
local submissionResultRemote = remoteFolder:WaitForChild(Remotes.EVENTS.SUBMISSION_RESULT) :: RemoteEvent

type ChallengeSummary = {
	code: string,
	module: string,
	title: string,
	description: string,
	difficulty: number,
}

type CompletedEntry = {
	code: string,
	completed_at: string,
	best_ms: number?,
}

local COLOR_BG_MAIN = Color3.fromRGB(22, 27, 34)
local COLOR_BG_ELEVATED = Color3.fromRGB(13, 17, 23)
local COLOR_BG_CARD = Color3.fromRGB(30, 36, 46)
local COLOR_BORDER = Color3.fromRGB(56, 65, 78)
local COLOR_TEXT = Color3.fromRGB(235, 240, 245)
local COLOR_MUTED = Color3.fromRGB(150, 162, 178)
local COLOR_ACCENT = Color3.fromRGB(56, 139, 253)
local COLOR_GREEN = Color3.fromRGB(46, 204, 113)
local COLOR_GREEN_BG = Color3.fromRGB(20, 62, 42)
local COLOR_RED = Color3.fromRGB(220, 76, 76)
local COLOR_RED_BG = Color3.fromRGB(72, 24, 28)
local COLOR_AMBER = Color3.fromRGB(230, 165, 50)
local COLOR_AMBER_BG = Color3.fromRGB(70, 50, 18)

local NODE_PENDING_COLOR = Color3.fromRGB(200, 60, 60)
local NODE_COMPLETED_COLOR = Color3.fromRGB(46, 204, 113)

local ClientState = {
	challenges = {} :: { ChallengeSummary },
	completedByCode = {} :: { [string]: CompletedEntry },
	selectedCode = nil :: string?,
	draftSqlByCode = {} :: { [string]: string },
	hintStepByCode = {} :: { [string]: number },
	isSubmitting = false,
	activeSubmitToken = 0,
	isUpdatingEditorText = false,
}

-- Helper constructors for clean programmatic UI
local function addCorner(parent: GuiObject, radiusPx: number): UICorner
	local corner = Instance.new("UICorner")
	corner.CornerRadius = UDim.new(0, radiusPx)
	corner.Parent = parent
	return corner
end

local function addStroke(parent: GuiObject, color: Color3, thickness: number?): UIStroke
	local stroke = Instance.new("UIStroke")
	stroke.Color = color
	stroke.Thickness = thickness or 1
	stroke.ApplyStrokeMode = Enum.ApplyStrokeMode.Border
	stroke.Parent = parent
	return stroke
end

local function addPadding(parent: GuiObject, topPx: number, bottomPx: number, leftPx: number, rightPx: number): UIPadding
	local padding = Instance.new("UIPadding")
	padding.PaddingTop = UDim.new(0, topPx)
	padding.PaddingBottom = UDim.new(0, bottomPx)
	padding.PaddingLeft = UDim.new(0, leftPx)
	padding.PaddingRight = UDim.new(0, rightPx)
	padding.Parent = parent
	return padding
end

-- Client-only coloring of optional PipelineNode_1..3 in Workspace
local function applyNodeColor(target: Instance, color: Color3): ()
	if target:IsA("BasePart") then
		target.Color = color
	elseif target:IsA("Model") then
		for _, descendant in target:GetDescendants() do
			if descendant:IsA("BasePart") then
				descendant.Color = color
			end
		end
	end
end

local function updateLocalPipelineNodes(): ()
	local nodeMap = ChallengeCatalog.getNodeMap()
	for code, nodeName in nodeMap do
		local nodeInstance = Workspace:FindFirstChild(nodeName)
		if nodeInstance ~= nil then
			local isCompleted = ClientState.completedByCode[code] ~= nil
			applyNodeColor(nodeInstance, if isCompleted then NODE_COMPLETED_COLOR else NODE_PENDING_COLOR)
		end
	end
end

-- Build ScreenGui
local existingGui = playerGui:FindFirstChild("DataPipelineTycoonTerminal")
if existingGui ~= nil then
	existingGui:Destroy()
end

local screenGui = Instance.new("ScreenGui")
screenGui.Name = "DataPipelineTycoonTerminal"
screenGui.ResetOnSpawn = false
screenGui.ZIndexBehavior = Enum.ZIndexBehavior.Sibling
screenGui.Parent = playerGui

-- Toggle pill always accessible at top-center
local toggleButton = Instance.new("TextButton")
toggleButton.Name = "ToggleTerminalButton"
toggleButton.Size = UDim2.fromOffset(210, 34)
toggleButton.Position = UDim2.new(0.5, -105, 0, 12)
toggleButton.BackgroundColor3 = COLOR_BG_MAIN
toggleButton.TextColor3 = COLOR_TEXT
toggleButton.Font = Enum.Font.GothamBold
toggleButton.TextSize = 14
toggleButton.Text = "Terminal SQL [F2]"
toggleButton.AutoButtonColor = true
toggleButton.Parent = screenGui
addCorner(toggleButton, 8)
addStroke(toggleButton, COLOR_ACCENT, 1.5)

-- Main window
local mainWindow = Instance.new("Frame")
mainWindow.Name = "MainWindow"
mainWindow.AnchorPoint = Vector2.new(0.5, 0.5)
mainWindow.Position = UDim2.new(0.5, 0, 0.53, 0)
mainWindow.Size = UDim2.fromScale(0.88, 0.84)
mainWindow.BackgroundColor3 = COLOR_BG_MAIN
mainWindow.BorderSizePixel = 0
mainWindow.Visible = true
mainWindow.Parent = screenGui
addCorner(mainWindow, 12)
addStroke(mainWindow, COLOR_BORDER, 1.5)

local windowSizeConstraint = Instance.new("UISizeConstraint")
windowSizeConstraint.MinSize = Vector2.new(640, 440)
windowSizeConstraint.MaxSize = Vector2.new(1180, 780)
windowSizeConstraint.Parent = mainWindow

-- Header Bar
local headerBar = Instance.new("Frame")
headerBar.Name = "HeaderBar"
headerBar.Size = UDim2.new(1, 0, 0, 46)
headerBar.BackgroundColor3 = COLOR_BG_ELEVATED
headerBar.BorderSizePixel = 0
headerBar.Parent = mainWindow
addCorner(headerBar, 12)
addPadding(headerBar, 6, 6, 14, 14)

local headerTitle = Instance.new("TextLabel")
headerTitle.Size = UDim2.new(0.5, 0, 1, 0)
headerTitle.BackgroundTransparency = 1
headerTitle.Text = "Data Pipeline Tycoon — Terminal SQL"
headerTitle.TextColor3 = COLOR_TEXT
headerTitle.Font = Enum.Font.GothamBold
headerTitle.TextSize = 16
headerTitle.TextXAlignment = Enum.TextXAlignment.Left
headerTitle.Parent = headerBar

local progressSummaryLabel = Instance.new("TextLabel")
progressSummaryLabel.Size = UDim2.new(0.28, 0, 1, 0)
progressSummaryLabel.Position = UDim2.new(0.5, 0, 0, 0)
progressSummaryLabel.BackgroundTransparency = 1
progressSummaryLabel.Text = "Progreso: 0/3 nodos"
progressSummaryLabel.TextColor3 = COLOR_MUTED
progressSummaryLabel.Font = Enum.Font.GothamMedium
progressSummaryLabel.TextSize = 13
progressSummaryLabel.TextXAlignment = Enum.TextXAlignment.Right
progressSummaryLabel.Parent = headerBar

local refreshButton = Instance.new("TextButton")
refreshButton.Name = "RefreshButton"
refreshButton.AnchorPoint = Vector2.new(1, 0.5)
refreshButton.Position = UDim2.new(1, -44, 0.5, 0)
refreshButton.Size = UDim2.fromOffset(92, 28)
refreshButton.BackgroundColor3 = COLOR_BG_CARD
refreshButton.TextColor3 = COLOR_TEXT
refreshButton.Font = Enum.Font.GothamMedium
refreshButton.TextSize = 12
refreshButton.Text = "Actualizar"
refreshButton.Parent = headerBar
addCorner(refreshButton, 6)
addStroke(refreshButton, COLOR_BORDER, 1)

local closeButton = Instance.new("TextButton")
closeButton.Name = "CloseButton"
closeButton.AnchorPoint = Vector2.new(1, 0.5)
closeButton.Position = UDim2.new(1, 0, 0.5, 0)
closeButton.Size = UDim2.fromOffset(32, 28)
closeButton.BackgroundColor3 = COLOR_BG_CARD
closeButton.TextColor3 = COLOR_TEXT
closeButton.Font = Enum.Font.GothamBold
closeButton.TextSize = 14
closeButton.Text = "×"
closeButton.Parent = headerBar
addCorner(closeButton, 6)
addStroke(closeButton, COLOR_BORDER, 1)

-- Body Container
local bodyContainer = Instance.new("Frame")
bodyContainer.Name = "BodyContainer"
bodyContainer.Position = UDim2.fromOffset(10, 54)
bodyContainer.Size = UDim2.new(1, -20, 1, -64)
bodyContainer.BackgroundTransparency = 1
bodyContainer.Parent = mainWindow

-- Left Sidebar: Challenges List
local sidebarFrame = Instance.new("Frame")
sidebarFrame.Name = "Sidebar"
sidebarFrame.Size = UDim2.new(0.27, -6, 1, 0)
sidebarFrame.BackgroundColor3 = COLOR_BG_ELEVATED
sidebarFrame.BorderSizePixel = 0
sidebarFrame.Parent = bodyContainer
addCorner(sidebarFrame, 8)
addStroke(sidebarFrame, COLOR_BORDER, 1)
addPadding(sidebarFrame, 10, 10, 10, 10)

local sidebarHeader = Instance.new("TextLabel")
sidebarHeader.Size = UDim2.new(1, 0, 0, 22)
sidebarHeader.BackgroundTransparency = 1
sidebarHeader.Text = "RETOS DEL PIPELINE"
sidebarHeader.TextColor3 = COLOR_MUTED
sidebarHeader.Font = Enum.Font.GothamBold
sidebarHeader.TextSize = 12
sidebarHeader.TextXAlignment = Enum.TextXAlignment.Left
sidebarHeader.Parent = sidebarFrame

local challengeListScroll = Instance.new("ScrollingFrame")
challengeListScroll.Name = "ChallengeList"
challengeListScroll.Position = UDim2.fromOffset(0, 28)
challengeListScroll.Size = UDim2.new(1, 0, 1, -28)
challengeListScroll.BackgroundTransparency = 1
challengeListScroll.BorderSizePixel = 0
challengeListScroll.ScrollBarThickness = 5
challengeListScroll.CanvasSize = UDim2.new(0, 0, 0, 0)
challengeListScroll.AutomaticCanvasSize = Enum.AutomaticSize.Y
challengeListScroll.Parent = sidebarFrame

local challengeListLayout = Instance.new("UIListLayout")
challengeListLayout.Padding = UDim.new(0, 8)
challengeListLayout.SortOrder = Enum.SortOrder.LayoutOrder
challengeListLayout.Parent = challengeListScroll

-- Right Workspace: Details + SQL Editor + Results Preview
local workspacePanel = Instance.new("Frame")
workspacePanel.Name = "WorkspacePanel"
workspacePanel.Position = UDim2.new(0.27, 6, 0, 0)
workspacePanel.Size = UDim2.new(0.73, -6, 1, 0)
workspacePanel.BackgroundTransparency = 1
workspacePanel.Parent = bodyContainer

local workspaceLayout = Instance.new("UIListLayout")
workspaceLayout.Padding = UDim.new(0, 8)
workspaceLayout.SortOrder = Enum.SortOrder.LayoutOrder
workspaceLayout.Parent = workspacePanel

-- 1) Challenge Description & Hints Card
local promptCard = Instance.new("Frame")
promptCard.Name = "PromptCard"
promptCard.LayoutOrder = 1
promptCard.Size = UDim2.new(1, 0, 0.29, 0)
promptCard.BackgroundColor3 = COLOR_BG_ELEVATED
promptCard.BorderSizePixel = 0
promptCard.Parent = workspacePanel
addCorner(promptCard, 8)
addStroke(promptCard, COLOR_BORDER, 1)
addPadding(promptCard, 8, 8, 12, 12)

local promptHeaderRow = Instance.new("Frame")
promptHeaderRow.Size = UDim2.new(1, 0, 0, 26)
promptHeaderRow.BackgroundTransparency = 1
promptHeaderRow.Parent = promptCard

local challengeTitleLabel = Instance.new("TextLabel")
challengeTitleLabel.Size = UDim2.new(0.76, 0, 1, 0)
challengeTitleLabel.BackgroundTransparency = 1
challengeTitleLabel.Text = "Cargando retos..."
challengeTitleLabel.TextColor3 = COLOR_TEXT
challengeTitleLabel.Font = Enum.Font.GothamBold
challengeTitleLabel.TextSize = 15
challengeTitleLabel.TextXAlignment = Enum.TextXAlignment.Left
challengeTitleLabel.TextTruncate = Enum.TextTruncate.AtEnd
challengeTitleLabel.Parent = promptHeaderRow

local hintButton = Instance.new("TextButton")
hintButton.Name = "HintButton"
hintButton.AnchorPoint = Vector2.new(1, 0.5)
hintButton.Position = UDim2.new(1, 0, 0.5, 0)
hintButton.Size = UDim2.fromOffset(105, 24)
hintButton.BackgroundColor3 = COLOR_BG_CARD
hintButton.TextColor3 = COLOR_AMBER
hintButton.Font = Enum.Font.GothamBold
hintButton.TextSize = 12
hintButton.Text = "Ver pista"
hintButton.Parent = promptHeaderRow
addCorner(hintButton, 6)
addStroke(hintButton, COLOR_AMBER, 1)

local promptScroll = Instance.new("ScrollingFrame")
promptScroll.Position = UDim2.fromOffset(0, 30)
promptScroll.Size = UDim2.new(1, 0, 1, -30)
promptScroll.BackgroundTransparency = 1
promptScroll.BorderSizePixel = 0
promptScroll.ScrollBarThickness = 5
promptScroll.CanvasSize = UDim2.new(0, 0, 0, 0)
promptScroll.AutomaticCanvasSize = Enum.AutomaticSize.Y
promptScroll.Parent = promptCard

local promptScrollLayout = Instance.new("UIListLayout")
promptScrollLayout.Padding = UDim.new(0, 6)
promptScrollLayout.SortOrder = Enum.SortOrder.LayoutOrder
promptScrollLayout.Parent = promptScroll

local descriptionLabel = Instance.new("TextLabel")
descriptionLabel.LayoutOrder = 1
descriptionLabel.Size = UDim2.new(1, -8, 0, 0)
descriptionLabel.AutomaticSize = Enum.AutomaticSize.Y
descriptionLabel.BackgroundTransparency = 1
descriptionLabel.Text = "Conectando con el backend para obtener los retos disponibles..."
descriptionLabel.TextColor3 = COLOR_TEXT
descriptionLabel.Font = Enum.Font.Gotham
descriptionLabel.TextSize = 13
descriptionLabel.TextWrapped = true
descriptionLabel.TextXAlignment = Enum.TextXAlignment.Left
descriptionLabel.TextYAlignment = Enum.TextYAlignment.Top
descriptionLabel.Parent = promptScroll

local schemaHintLabel = Instance.new("TextLabel")
schemaHintLabel.LayoutOrder = 2
schemaHintLabel.Size = UDim2.new(1, -8, 0, 0)
schemaHintLabel.AutomaticSize = Enum.AutomaticSize.Y
schemaHintLabel.BackgroundColor3 = COLOR_BG_MAIN
schemaHintLabel.TextColor3 = COLOR_MUTED
schemaHintLabel.Font = Enum.Font.Code
schemaHintLabel.TextSize = 13
schemaHintLabel.TextWrapped = true
schemaHintLabel.TextXAlignment = Enum.TextXAlignment.Left
schemaHintLabel.TextYAlignment = Enum.TextYAlignment.Top
schemaHintLabel.Text = ""
schemaHintLabel.Visible = false
schemaHintLabel.Parent = promptScroll
addCorner(schemaHintLabel, 6)
addPadding(schemaHintLabel, 6, 6, 8, 8)

local hintBannerLabel = Instance.new("TextLabel")
hintBannerLabel.LayoutOrder = 3
hintBannerLabel.Size = UDim2.new(1, -8, 0, 0)
hintBannerLabel.AutomaticSize = Enum.AutomaticSize.Y
hintBannerLabel.BackgroundColor3 = COLOR_AMBER_BG
hintBannerLabel.TextColor3 = Color3.fromRGB(255, 224, 150)
hintBannerLabel.Font = Enum.Font.GothamMedium
hintBannerLabel.TextSize = 12
hintBannerLabel.TextWrapped = true
hintBannerLabel.TextXAlignment = Enum.TextXAlignment.Left
hintBannerLabel.Text = ""
hintBannerLabel.Visible = false
hintBannerLabel.Parent = promptScroll
addCorner(hintBannerLabel, 6)
addPadding(hintBannerLabel, 6, 6, 8, 8)

-- 2) SQL Editor Card
local editorCard = Instance.new("Frame")
editorCard.Name = "EditorCard"
editorCard.LayoutOrder = 2
editorCard.Size = UDim2.new(1, 0, 0.37, 0)
editorCard.BackgroundColor3 = COLOR_BG_ELEVATED
editorCard.BorderSizePixel = 0
editorCard.Parent = workspacePanel
addCorner(editorCard, 8)
addStroke(editorCard, COLOR_BORDER, 1)
addPadding(editorCard, 8, 8, 12, 12)

local editorToolbar = Instance.new("Frame")
editorToolbar.Size = UDim2.new(1, 0, 0, 24)
editorToolbar.BackgroundTransparency = 1
editorToolbar.Parent = editorCard

local editorHeaderLabel = Instance.new("TextLabel")
editorHeaderLabel.Size = UDim2.new(0.45, 0, 1, 0)
editorHeaderLabel.BackgroundTransparency = 1
editorHeaderLabel.Text = "CONSULTA SQL (SOLO SELECT)"
editorHeaderLabel.TextColor3 = COLOR_MUTED
editorHeaderLabel.Font = Enum.Font.GothamBold
editorHeaderLabel.TextSize = 12
editorHeaderLabel.TextXAlignment = Enum.TextXAlignment.Left
editorHeaderLabel.Parent = editorToolbar

local charCountLabel = Instance.new("TextLabel")
charCountLabel.AnchorPoint = Vector2.new(1, 0.5)
charCountLabel.Position = UDim2.new(1, -158, 0.5, 0)
charCountLabel.Size = UDim2.fromOffset(90, 20)
charCountLabel.BackgroundTransparency = 1
charCountLabel.Text = "0 / 8000"
charCountLabel.TextColor3 = COLOR_MUTED
charCountLabel.Font = Enum.Font.Code
charCountLabel.TextSize = 12
charCountLabel.TextXAlignment = Enum.TextXAlignment.Right
charCountLabel.Parent = editorToolbar

local resetTemplateButton = Instance.new("TextButton")
resetTemplateButton.Name = "ResetTemplateButton"
resetTemplateButton.AnchorPoint = Vector2.new(1, 0.5)
resetTemplateButton.Position = UDim2.new(1, 0, 0.5, 0)
resetTemplateButton.Size = UDim2.fromOffset(148, 22)
resetTemplateButton.BackgroundColor3 = COLOR_BG_CARD
resetTemplateButton.TextColor3 = COLOR_TEXT
resetTemplateButton.Font = Enum.Font.GothamMedium
resetTemplateButton.TextSize = 11
resetTemplateButton.Text = "Restablecer plantilla"
resetTemplateButton.Parent = editorToolbar
addCorner(resetTemplateButton, 5)
addStroke(resetTemplateButton, COLOR_BORDER, 1)

local sqlScrollFrame = Instance.new("ScrollingFrame")
sqlScrollFrame.Name = "SqlScrollFrame"
sqlScrollFrame.Position = UDim2.fromOffset(0, 28)
sqlScrollFrame.Size = UDim2.new(1, 0, 1, -66)
sqlScrollFrame.BackgroundColor3 = Color3.fromRGB(9, 12, 17)
sqlScrollFrame.BorderSizePixel = 0
sqlScrollFrame.ScrollBarThickness = 6
sqlScrollFrame.CanvasSize = UDim2.new(0, 0, 0, 0)
sqlScrollFrame.AutomaticCanvasSize = Enum.AutomaticSize.Y
sqlScrollFrame.Parent = editorCard
addCorner(sqlScrollFrame, 6)
addStroke(sqlScrollFrame, COLOR_BORDER, 1)
addPadding(sqlScrollFrame, 6, 6, 8, 8)

local sqlTextBox = Instance.new("TextBox")
sqlTextBox.Name = "SqlTextBox"
sqlTextBox.Size = UDim2.new(1, -6, 0, 100)
sqlTextBox.AutomaticSize = Enum.AutomaticSize.Y
sqlTextBox.BackgroundTransparency = 1
sqlTextBox.ClearTextOnFocus = false
sqlTextBox.MultiLine = true
sqlTextBox.TextWrapped = true
sqlTextBox.TextXAlignment = Enum.TextXAlignment.Left
sqlTextBox.TextYAlignment = Enum.TextYAlignment.Top
sqlTextBox.Font = Enum.Font.Code
sqlTextBox.TextSize = 15
sqlTextBox.TextColor3 = COLOR_TEXT
sqlTextBox.PlaceholderText = "SELECT ..."
sqlTextBox.PlaceholderColor3 = Color3.fromRGB(100, 110, 125)
sqlTextBox.Text = ""
sqlTextBox.Parent = sqlScrollFrame

local editorActionRow = Instance.new("Frame")
editorActionRow.Position = UDim2.new(0, 0, 1, -32)
editorActionRow.Size = UDim2.new(1, 0, 0, 32)
editorActionRow.BackgroundTransparency = 1
editorActionRow.Parent = editorCard

local runSqlButton = Instance.new("TextButton")
runSqlButton.Name = "RunSqlButton"
runSqlButton.Size = UDim2.fromOffset(156, 30)
runSqlButton.BackgroundColor3 = COLOR_ACCENT
runSqlButton.TextColor3 = Color3.fromRGB(255, 255, 255)
runSqlButton.Font = Enum.Font.GothamBold
runSqlButton.TextSize = 13
runSqlButton.Text = "Ejecutar SQL"
runSqlButton.Parent = editorActionRow
addCorner(runSqlButton, 6)

local statusLabel = Instance.new("TextLabel")
statusLabel.Name = "StatusLabel"
statusLabel.Position = UDim2.fromOffset(168, 0)
statusLabel.Size = UDim2.new(1, -168, 1, 0)
statusLabel.BackgroundTransparency = 1
statusLabel.Text = ""
statusLabel.TextColor3 = COLOR_AMBER
statusLabel.Font = Enum.Font.GothamMedium
statusLabel.TextSize = 12
statusLabel.TextXAlignment = Enum.TextXAlignment.Left
statusLabel.TextTruncate = Enum.TextTruncate.AtEnd
statusLabel.Parent = editorActionRow

-- 3) Verdict & Results Preview Card
local resultsCard = Instance.new("Frame")
resultsCard.Name = "ResultsCard"
resultsCard.LayoutOrder = 3
resultsCard.Size = UDim2.new(1, 0, 0.34, -16)
resultsCard.BackgroundColor3 = COLOR_BG_ELEVATED
resultsCard.BorderSizePixel = 0
resultsCard.Parent = workspacePanel
addCorner(resultsCard, 8)
addStroke(resultsCard, COLOR_BORDER, 1)
addPadding(resultsCard, 8, 8, 12, 12)

local verdictBanner = Instance.new("Frame")
verdictBanner.Name = "VerdictBanner"
verdictBanner.Size = UDim2.new(1, 0, 0, 42)
verdictBanner.BackgroundColor3 = COLOR_BG_CARD
verdictBanner.BorderSizePixel = 0
verdictBanner.Parent = resultsCard
addCorner(verdictBanner, 6)
addStroke(verdictBanner, COLOR_BORDER, 1)
addPadding(verdictBanner, 4, 4, 10, 10)

local verdictMessageLabel = Instance.new("TextLabel")
verdictMessageLabel.Size = UDim2.new(0.80, 0, 1, 0)
verdictMessageLabel.BackgroundTransparency = 1
verdictMessageLabel.Text = "Selecciona un reto y ejecuta tu consulta SQL para ver el resultado."
verdictMessageLabel.TextColor3 = COLOR_MUTED
verdictMessageLabel.Font = Enum.Font.GothamMedium
verdictMessageLabel.TextSize = 12
verdictMessageLabel.TextWrapped = true
verdictMessageLabel.TextXAlignment = Enum.TextXAlignment.Left
verdictMessageLabel.Parent = verdictBanner

local verdictTimingLabel = Instance.new("TextLabel")
verdictTimingLabel.Position = UDim2.new(0.80, 0, 0, 0)
verdictTimingLabel.Size = UDim2.new(0.20, 0, 1, 0)
verdictTimingLabel.BackgroundTransparency = 1
verdictTimingLabel.Text = ""
verdictTimingLabel.TextColor3 = COLOR_TEXT
verdictTimingLabel.Font = Enum.Font.Code
verdictTimingLabel.TextSize = 12
verdictTimingLabel.TextXAlignment = Enum.TextXAlignment.Right
verdictTimingLabel.Parent = verdictBanner

local previewHeaderLabel = Instance.new("TextLabel")
previewHeaderLabel.Position = UDim2.fromOffset(0, 46)
previewHeaderLabel.Size = UDim2.new(1, 0, 0, 18)
previewHeaderLabel.BackgroundTransparency = 1
previewHeaderLabel.Text = "VISTA PREVIA DE TU SALIDA (máximo 10 filas)"
previewHeaderLabel.TextColor3 = COLOR_MUTED
previewHeaderLabel.Font = Enum.Font.GothamBold
previewHeaderLabel.TextSize = 11
previewHeaderLabel.TextXAlignment = Enum.TextXAlignment.Left
previewHeaderLabel.Parent = resultsCard

local previewTableScroll = Instance.new("ScrollingFrame")
previewTableScroll.Name = "PreviewTableScroll"
previewTableScroll.Position = UDim2.fromOffset(0, 66)
previewTableScroll.Size = UDim2.new(1, 0, 1, -66)
previewTableScroll.BackgroundColor3 = Color3.fromRGB(9, 12, 17)
previewTableScroll.BorderSizePixel = 0
previewTableScroll.ScrollBarThickness = 6
previewTableScroll.ScrollingDirection = Enum.ScrollingDirection.XY
previewTableScroll.CanvasSize = UDim2.new(0, 0, 0, 0)
previewTableScroll.AutomaticCanvasSize = Enum.AutomaticSize.XY
previewTableScroll.Parent = resultsCard
addCorner(previewTableScroll, 6)
addStroke(previewTableScroll, COLOR_BORDER, 1)
addPadding(previewTableScroll, 4, 4, 6, 6)

local previewRowsLayout = Instance.new("UIListLayout")
previewRowsLayout.Padding = UDim.new(0, 2)
previewRowsLayout.SortOrder = Enum.SortOrder.LayoutOrder
previewRowsLayout.Parent = previewTableScroll

local function updateCharCounter(): ()
	local count = #sqlTextBox.Text
	charCountLabel.Text = string.format("%d / %d", count, Remotes.LIMITS.MAX_SQL_LENGTH)
	if count > Remotes.LIMITS.MAX_SQL_LENGTH then
		charCountLabel.TextColor3 = COLOR_RED
	elseif count >= Remotes.LIMITS.MAX_SQL_LENGTH - 500 then
		charCountLabel.TextColor3 = COLOR_AMBER
	else
		charCountLabel.TextColor3 = COLOR_MUTED
	end
end

local function setEditorTextProgrammatically(textValue: string): ()
	ClientState.isUpdatingEditorText = true
	sqlTextBox.Text = textValue
	ClientState.isUpdatingEditorText = false
	updateCharCounter()
end

local function setSubmittingState(submitting: boolean, statusText: string?): ()
	ClientState.isSubmitting = submitting
	runSqlButton.Active = not submitting
	runSqlButton.AutoButtonColor = not submitting
	runSqlButton.BackgroundColor3 = if submitting then Color3.fromRGB(48, 65, 92) else COLOR_ACCENT
	runSqlButton.Text = if submitting then "Evaluando..." else "Ejecutar SQL"
	statusLabel.Text = statusText or ""
end

local function renderPreviewTable(columns: { string }, previewRows: { { string } }): ()
	for _, child in previewTableScroll:GetChildren() do
		if not child:IsA("UIListLayout") and not child:IsA("UIPadding") and not child:IsA("UICorner") and not child:IsA("UIStroke") then
			child:Destroy()
		end
	end

	if #columns == 0 and #previewRows == 0 then
		local emptyLabel = Instance.new("TextLabel")
		emptyLabel.Size = UDim2.new(1, -12, 0, 28)
		emptyLabel.BackgroundTransparency = 1
		emptyLabel.Text = "(Sin columnas o filas de salida para mostrar)"
		emptyLabel.TextColor3 = COLOR_MUTED
		emptyLabel.Font = Enum.Font.Code
		emptyLabel.TextSize = 13
		emptyLabel.TextXAlignment = Enum.TextXAlignment.Left
		emptyLabel.Parent = previewTableScroll
		return
	end

	local colCount = #columns
	if colCount == 0 and #previewRows > 0 then
		colCount = #previewRows[1]
	end

	local colWidths: { number } = {}
	for colIdx = 1, colCount do
		local maxChars = if columns[colIdx] ~= nil then #columns[colIdx] else 6
		for _, row in previewRows do
			local cellVal = row[colIdx]
			if cellVal ~= nil and #cellVal > maxChars then
				maxChars = #cellVal
			end
		end
		colWidths[colIdx] = math.clamp(maxChars * 8 + 24, 96, 260)
	end

	local function buildRowFrame(orderIndex: number, cells: { string }, isHeader: boolean, rowBg: Color3): ()
		local rowFrame = Instance.new("Frame")
		rowFrame.LayoutOrder = orderIndex
		rowFrame.AutomaticSize = Enum.AutomaticSize.X
		rowFrame.Size = UDim2.fromOffset(0, if isHeader then 26 else 24)
		rowFrame.BackgroundColor3 = rowBg
		rowFrame.BorderSizePixel = 0
		rowFrame.Parent = previewTableScroll

		local rowLayout = Instance.new("UIListLayout")
		rowLayout.FillDirection = Enum.FillDirection.Horizontal
		rowLayout.SortOrder = Enum.SortOrder.LayoutOrder
		rowLayout.Padding = UDim.new(0, 4)
		rowLayout.Parent = rowFrame

		for colIdx = 1, colCount do
			local cellLabel = Instance.new("TextLabel")
			cellLabel.LayoutOrder = colIdx
			cellLabel.Size = UDim2.fromOffset(colWidths[colIdx], if isHeader then 26 else 24)
			cellLabel.BackgroundTransparency = 1
			cellLabel.Text = if cells[colIdx] ~= nil then tostring(cells[colIdx]) else ""
			cellLabel.TextColor3 = if isHeader then COLOR_ACCENT elseif cells[colIdx] == "NULL" then COLOR_MUTED else COLOR_TEXT
			cellLabel.Font = if isHeader then Enum.Font.GothamBold else Enum.Font.Code
			cellLabel.TextSize = if isHeader then 12 else 13
			cellLabel.TextXAlignment = Enum.TextXAlignment.Left
			cellLabel.TextTruncate = Enum.TextTruncate.AtEnd
			cellLabel.Parent = rowFrame
			addPadding(cellLabel, 2, 2, 4, 4)
		end
	end

	if #columns > 0 then
		buildRowFrame(0, columns, true, Color3.fromRGB(22, 30, 44))
	end

	for rowIdx, rowCells in previewRows do
		local bgColor = if rowIdx % 2 == 0 then Color3.fromRGB(16, 21, 29) else Color3.fromRGB(12, 16, 22)
		buildRowFrame(rowIdx, rowCells, false, bgColor)
	end
end

local function setVerdictBanner(kind: "neutral" | "pass" | "fail" | "error", message: string, executionMs: number?): ()
	local bannerStroke = verdictBanner:FindFirstChildOfClass("UIStroke")
	if kind == "pass" then
		verdictBanner.BackgroundColor3 = COLOR_GREEN_BG
		if bannerStroke then
			bannerStroke.Color = COLOR_GREEN
		end
		verdictMessageLabel.TextColor3 = Color3.fromRGB(210, 255, 225)
	elseif kind == "fail" then
		verdictBanner.BackgroundColor3 = COLOR_RED_BG
		if bannerStroke then
			bannerStroke.Color = COLOR_RED
		end
		verdictMessageLabel.TextColor3 = Color3.fromRGB(255, 215, 215)
	elseif kind == "error" then
		verdictBanner.BackgroundColor3 = COLOR_AMBER_BG
		if bannerStroke then
			bannerStroke.Color = COLOR_AMBER
		end
		verdictMessageLabel.TextColor3 = Color3.fromRGB(255, 232, 180)
	else
		verdictBanner.BackgroundColor3 = COLOR_BG_CARD
		if bannerStroke then
			bannerStroke.Color = COLOR_BORDER
		end
		verdictMessageLabel.TextColor3 = COLOR_MUTED
	end

	verdictMessageLabel.Text = message
	if executionMs ~= nil then
		verdictTimingLabel.Text = string.format("%d ms", executionMs)
	else
		verdictTimingLabel.Text = ""
	end
end

local function renderHintBannerForSelection(): ()
	local code = ClientState.selectedCode
	if code == nil then
		hintBannerLabel.Visible = false
		hintButton.Text = "Ver pista"
		return
	end
	local meta = ChallengeCatalog.getMeta(code)
	if meta == nil or #meta.hints == 0 then
		hintBannerLabel.Visible = false
		hintButton.Visible = false
		return
	end

	hintButton.Visible = true
	local step = ClientState.hintStepByCode[code] or 0
	if step <= 0 then
		hintBannerLabel.Visible = false
		hintButton.Text = "Ver pista"
	else
		local clampedStep = math.min(step, #meta.hints)
		hintBannerLabel.Text = meta.hints[clampedStep]
		hintBannerLabel.Visible = true
		if clampedStep < #meta.hints then
			hintButton.Text = "Siguiente pista"
		else
			hintButton.Text = "Ocultar pista"
		end
	end
end

local function findChallengeByCode(code: string?): ChallengeSummary?
	if code == nil then
		return nil
	end
	for _, item in ClientState.challenges do
		if item.code == code then
			return item
		end
	end
	return nil
end

local renderChallengeSidebar: () -> ()

local function selectChallenge(code: string): ()
	local challenge = findChallengeByCode(code)
	if challenge == nil then
		return
	end

	ClientState.selectedCode = code
	local meta = ChallengeCatalog.getMeta(code)
	local diffLabel = ChallengeCatalog.getDifficultyLabel(challenge.difficulty, code)
	local completedInfo = ClientState.completedByCode[code]
	local completionTag = if completedInfo ~= nil then "✓ Completado" else "Pendiente"

	challengeTitleLabel.Text = string.format("%s [%s · %s]", challenge.title, diffLabel, completionTag)
	descriptionLabel.Text = challenge.description

	if meta ~= nil and meta.schemaHint ~= "" then
		schemaHintLabel.Text = meta.schemaHint
		schemaHintLabel.Visible = true
	else
		schemaHintLabel.Text = ""
		schemaHintLabel.Visible = false
	end

	local savedDraft = ClientState.draftSqlByCode[code]
	if savedDraft == nil then
		savedDraft = if meta ~= nil then meta.starterSql else ""
		ClientState.draftSqlByCode[code] = savedDraft
	end
	setEditorTextProgrammatically(savedDraft)

	renderHintBannerForSelection()
	renderChallengeSidebar()
end

renderChallengeSidebar = function(): ()
	for _, child in challengeListScroll:GetChildren() do
		if child:IsA("TextButton") then
			child:Destroy()
		end
	end

	local completedCount = 0
	for index, challenge in ClientState.challenges do
		local isDone = ClientState.completedByCode[challenge.code] ~= nil
		if isDone then
			completedCount += 1
		end
		local isSelected = ClientState.selectedCode == challenge.code
		local diffLabel = ChallengeCatalog.getDifficultyLabel(challenge.difficulty, challenge.code)
		local bestText = ""
		if isDone then
			local entry = ClientState.completedByCode[challenge.code]
			if entry.best_ms ~= nil then
				bestText = string.format(" · Mejor: %d ms", entry.best_ms)
			end
		end

		local cardButton = Instance.new("TextButton")
		cardButton.Name = "Challenge_" .. challenge.code
		cardButton.LayoutOrder = index
		cardButton.Size = UDim2.new(1, -4, 0, 56)
		cardButton.BackgroundColor3 = if isSelected then Color3.fromRGB(32, 46, 68) else COLOR_BG_CARD
		cardButton.Text = ""
		cardButton.AutoButtonColor = true
		cardButton.Parent = challengeListScroll
		addCorner(cardButton, 6)
		addStroke(
			cardButton,
			if isSelected then COLOR_ACCENT elseif isDone then COLOR_GREEN else COLOR_BORDER,
			if isSelected then 1.5 else 1
		)
		addPadding(cardButton, 6, 6, 8, 8)

		local titleText = Instance.new("TextLabel")
		titleText.Size = UDim2.new(1, 0, 0, 22)
		titleText.BackgroundTransparency = 1
		titleText.Text = string.format("%s %s", if isDone then "✓" else "•", challenge.title)
		titleText.TextColor3 = if isDone then COLOR_GREEN else COLOR_TEXT
		titleText.Font = Enum.Font.GothamBold
		titleText.TextSize = 13
		titleText.TextXAlignment = Enum.TextXAlignment.Left
		titleText.TextTruncate = Enum.TextTruncate.AtEnd
		titleText.Parent = cardButton

		local subText = Instance.new("TextLabel")
		subText.Position = UDim2.fromOffset(0, 22)
		subText.Size = UDim2.new(1, 0, 0, 20)
		subText.BackgroundTransparency = 1
		subText.Text = string.format("%s%s", diffLabel, bestText)
		subText.TextColor3 = COLOR_MUTED
		subText.Font = Enum.Font.GothamMedium
		subText.TextSize = 11
		subText.TextXAlignment = Enum.TextXAlignment.Left
		subText.TextTruncate = Enum.TextTruncate.AtEnd
		subText.Parent = cardButton

		cardButton.Activated:Connect(function()
			selectChallenge(challenge.code)
		end)
	end

	local totalCount = math.max(#ClientState.challenges, #ChallengeCatalog.ORDERED_CODES)
	progressSummaryLabel.Text = string.format("Progreso: %d/%d nodos", completedCount, totalCount)
end

-- Event Wiring
toggleButton.Activated:Connect(function()
	mainWindow.Visible = not mainWindow.Visible
end)

closeButton.Activated:Connect(function()
	mainWindow.Visible = false
end)

UserInputService.InputBegan:Connect(function(input: InputObject, gameProcessed: boolean)
	if gameProcessed or UserInputService:GetFocusedTextBox() ~= nil then
		return
	end
	if input.KeyCode == Enum.KeyCode.F2 then
		mainWindow.Visible = not mainWindow.Visible
	end
end)

sqlTextBox:GetPropertyChangedSignal("Text"):Connect(function()
	if not ClientState.isUpdatingEditorText and ClientState.selectedCode ~= nil then
		ClientState.draftSqlByCode[ClientState.selectedCode] = sqlTextBox.Text
	end
	updateCharCounter()
end)

resetTemplateButton.Activated:Connect(function()
	local code = ClientState.selectedCode
	if code == nil then
		return
	end
	local meta = ChallengeCatalog.getMeta(code)
	local starter = if meta ~= nil then meta.starterSql else ""
	ClientState.draftSqlByCode[code] = starter
	setEditorTextProgrammatically(starter)
end)

hintButton.Activated:Connect(function()
	local code = ClientState.selectedCode
	if code == nil then
		return
	end
	local meta = ChallengeCatalog.getMeta(code)
	if meta == nil or #meta.hints == 0 then
		return
	end
	local currentStep = ClientState.hintStepByCode[code] or 0
	if currentStep >= #meta.hints then
		ClientState.hintStepByCode[code] = 0
	else
		ClientState.hintStepByCode[code] = currentStep + 1
	end
	renderHintBannerForSelection()
end)

refreshButton.Activated:Connect(function()
	statusLabel.Text = "Actualizando retos..."
	requestDashboardRemote:FireServer({ forceRefresh = true })
end)

runSqlButton.Activated:Connect(function()
	if ClientState.isSubmitting then
		return
	end
	local code = ClientState.selectedCode
	if code == nil then
		setVerdictBanner("error", "Primero selecciona un reto de la lista.", nil)
		return
	end

	local sql = sqlTextBox.Text
	local trimmed = (sql:gsub("^%s+", ""):gsub("%s+$", ""))
	if trimmed == "" then
		setVerdictBanner("error", "Escribe una consulta SELECT antes de ejecutar.", nil)
		return
	end
	if #sql > Remotes.LIMITS.MAX_SQL_LENGTH then
		setVerdictBanner(
			"error",
			string.format("Tu consulta excede el límite de %d caracteres.", Remotes.LIMITS.MAX_SQL_LENGTH),
			nil
		)
		return
	end

	ClientState.activeSubmitToken += 1
	local requestToken = ClientState.activeSubmitToken
	setSubmittingState(true, "Enviando consulta al servidor...")

	task.delay(2, function()
		if ClientState.isSubmitting and ClientState.activeSubmitToken == requestToken then
			statusLabel.Text = "Conectando con el motor SQL..."
		end
	end)

	task.delay(35, function()
		if ClientState.isSubmitting and ClientState.activeSubmitToken == requestToken then
			ClientState.activeSubmitToken += 1
			setSubmittingState(false, "")
			setVerdictBanner(
				"error",
				"La petición tardó demasiado en responder. Verifica tu conexión e intenta de nuevo.",
				nil
			)
		end
	end)

	submitSqlRemote:FireServer(code, sql)
end)

dashboardLoadedRemote.OnClientEvent:Connect(function(payload: any)
	if typeof(payload) ~= "table" then
		return
	end

	if not payload.ok then
		statusLabel.Text = ""
		if not payload.busy then
			local errText = if typeof(payload.message) == "string"
				then payload.message
				else "No se pudieron cargar los retos."
			challengeTitleLabel.Text = "Sin conexión al backend"
			descriptionLabel.Text = errText
			setVerdictBanner("error", errText, nil)
		end
		return
	end

	statusLabel.Text = ""
	ClientState.challenges = if typeof(payload.challenges) == "table" then payload.challenges else {}

	local nextCompleted: { [string]: CompletedEntry } = {}
	if typeof(payload.completed) == "table" then
		for _, entry in payload.completed do
			if typeof(entry) == "table" and typeof(entry.code) == "string" then
				nextCompleted[entry.code] = {
					code = entry.code,
					completed_at = if typeof(entry.completed_at) == "string" then entry.completed_at else "",
					best_ms = if typeof(entry.best_ms) == "number" then entry.best_ms else nil,
				}
			end
		end
	end
	ClientState.completedByCode = nextCompleted
	updateLocalPipelineNodes()

	if typeof(payload.progressWarning) == "string" and payload.progressWarning ~= "" then
		statusLabel.Text = payload.progressWarning
	end

	local selectedCode = ClientState.selectedCode
	if selectedCode == nil or findChallengeByCode(selectedCode) == nil then
		if #ClientState.challenges > 0 then
			selectChallenge(ClientState.challenges[1].code)
		else
			challengeTitleLabel.Text = "No hay retos disponibles"
			descriptionLabel.Text = "La base de datos no devolvió retos activos."
			renderChallengeSidebar()
		end
	else
		selectChallenge(selectedCode)
	end
end)

submissionResultRemote.OnClientEvent:Connect(function(payload: any)
	ClientState.activeSubmitToken += 1
	setSubmittingState(false, "")

	if typeof(payload) ~= "table" then
		setVerdictBanner("error", "Se recibió una respuesta inválida del servidor.", nil)
		return
	end

	if not payload.ok then
		local errText = if typeof(payload.message) == "string"
			then payload.message
			else "No se pudo evaluar la consulta SQL."
		setVerdictBanner("error", errText, nil)
		return
	end

	local passed = payload.passed == true
	local executionMs = if typeof(payload.execution_ms) == "number" then payload.execution_ms else nil
	local msg = if typeof(payload.message) == "string" then payload.message else ""
	local columns = if typeof(payload.columns) == "table" then payload.columns else {}
	local previewRows = if typeof(payload.preview_rows) == "table" then payload.preview_rows else {}

	setVerdictBanner(if passed then "pass" else "fail", msg, executionMs)
	renderPreviewTable(columns, previewRows)

	if passed then
		if typeof(payload.completed) == "table" then
			local nextCompleted: { [string]: CompletedEntry } = {}
			for _, entry in payload.completed do
				if typeof(entry) == "table" and typeof(entry.code) == "string" then
					nextCompleted[entry.code] = {
						code = entry.code,
						completed_at = if typeof(entry.completed_at) == "string" then entry.completed_at else "",
						best_ms = if typeof(entry.best_ms) == "number" then entry.best_ms else nil,
					}
				end
			end
			ClientState.completedByCode = nextCompleted
		elseif typeof(payload.challengeCode) == "string" then
			local existing = ClientState.completedByCode[payload.challengeCode]
			local prevBest = if existing ~= nil then existing.best_ms else nil
			local nextBest = executionMs
			if prevBest ~= nil and (nextBest == nil or prevBest < nextBest) then
				nextBest = prevBest
			end
			ClientState.completedByCode[payload.challengeCode] = {
				code = payload.challengeCode,
				completed_at = "",
				best_ms = nextBest,
			}
		end

		updateLocalPipelineNodes()
		local currentCode = ClientState.selectedCode
		if currentCode ~= nil then
			selectChallenge(currentCode)
		else
			renderChallengeSidebar()
		end
	end
end)

-- Initial visual state & dashboard fetch
updateLocalPipelineNodes()
updateCharCounter()
requestDashboardRemote:FireServer({ forceRefresh = false })
