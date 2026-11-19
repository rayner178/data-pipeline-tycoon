--!strict
--[[
	Template for local server configuration.
	Copy this file to `Secrets.luau` (gitignored) for local development, or
	configure `BASE_URL` and `API_KEY` as Attributes on `ServerStorage` in Studio.
	NEVER commit a real API key or tunnel token to git.
]]

return {
	-- Roblox HttpService blocks localhost/127.0.0.1. For local FastAPI testing,
	-- use an HTTPS tunnel URL (e.g. cloudflared/ngrok) or your Render URL.
	BASE_URL = "https://your-backend-or-tunnel.example.com",
	API_KEY = "",
}
