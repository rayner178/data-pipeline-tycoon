--!strict
--[[
	Client-safe challenge metadata: pipeline node mapping, schema hints,
	starter SQL templates, and progressive hints in Spanish.
	Contains NO secrets and NO challenge solutions or expected outputs.
]]

export type ChallengeSupportMeta = {
	nodeName: string,
	difficultyLabel: string,
	schemaHint: string,
	starterSql: string,
	hints: { string },
}

local ChallengeCatalog = {}

ChallengeCatalog.ORDERED_CODES = {
	"dedupe-row-number",
	"fix-multiplying-join",
	"index-slow-query",
}

local BY_CODE: { [string]: ChallengeSupportMeta } = {
	["dedupe-row-number"] = {
		nodeName = "PipelineNode_1",
		difficultyLabel = "Fácil",
		schemaHint = table.concat({
			"Tabla disponible:",
			"• staging_customers (customer_id INT, full_name TEXT, email TEXT, updated_at DATE)",
			"",
			"Columnas esperadas en tu SELECT:",
			"• customer_id, full_name, email",
		}, "\n"),
		starterSql = table.concat({
			"-- Conserva solo la fila más reciente (mayor updated_at) por customer_id",
			"SELECT",
			"    customer_id,",
			"    full_name,",
			"    email",
			"FROM staging_customers;",
		}, "\n"),
		hints = {
			"Pista 1/2: Usa ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY updated_at DESC) dentro de una CTE (WITH ...).",
			"Pista 2/2: Filtra en el SELECT externo con WHERE rn = 1 y proyecta únicamente customer_id, full_name y email.",
		},
	},
	["fix-multiplying-join"] = {
		nodeName = "PipelineNode_2",
		difficultyLabel = "Media",
		schemaHint = table.concat({
			"Tablas disponibles:",
			"• customers (id INT, name TEXT)",
			"• orders (id INT, customer_id INT, total_amount NUMERIC)",
			"• payments (id INT, order_id INT, paid_amount NUMERIC)",
			"",
			"Columnas esperadas en tu SELECT:",
			"• customer_id, name, total_ordered, total_paid",
		}, "\n"),
		starterSql = table.concat({
			"-- Esta consulta duplica montos al unir orders y payments directamente; corrígela",
			"SELECT",
			"    c.id AS customer_id,",
			"    c.name,",
			"    COALESCE(SUM(o.total_amount), 0) AS total_ordered,",
			"    COALESCE(SUM(p.paid_amount), 0) AS total_paid",
			"FROM customers c",
			"LEFT JOIN orders o ON o.customer_id = c.id",
			"LEFT JOIN payments p ON p.order_id = o.id",
			"GROUP BY c.id, c.name",
			"ORDER BY c.id;",
		}, "\n"),
		hints = {
			"Pista 1/2: Unirse directamente a orders y payments multiplica las filas de pedidos cuando un pedido tiene varios pagos.",
			"Pista 2/2: Preagrega orders por customer_id y payments por customer_id (uniendo payments -> orders) en CTEs antes de unirlos a customers.",
		},
	},
	["index-slow-query"] = {
		nodeName = "PipelineNode_3",
		difficultyLabel = "Difícil",
		schemaHint = table.concat({
			"Tabla e índice disponibles:",
			"• events (id INT, user_id INT, created_at DATE, kind TEXT)",
			"• Índice compuesto: idx_events_user_created ON events (user_id, created_at)",
			"",
			"Columnas esperadas en tu SELECT (orden cronológico por created_at ASC, id ASC):",
			"• id, kind, created_at",
		}, "\n"),
		starterSql = table.concat({
			"-- Optimiza esta consulta para que PostgreSQL utilice idx_events_user_created",
			"SELECT",
			"    id,",
			"    kind,",
			"    created_at",
			"FROM events",
			"WHERE CAST(user_id AS TEXT) = '42'",
			"  AND created_at >= DATE '2026-08-01'",
			"ORDER BY created_at ASC, id ASC;",
		}, "\n"),
		hints = {
			"Pista 1/2: Envolver user_id en CAST(user_id AS TEXT) rompe la sargabilidad y obliga a PostgreSQL a hacer Seq Scan.",
			"Pista 2/2: Reemplaza la condición por user_id = 42 manteniendo created_at >= DATE '2026-08-01' para usar el índice compuesto.",
		},
	},
}

function ChallengeCatalog.getMeta(code: string): ChallengeSupportMeta?
	return BY_CODE[code]
end

function ChallengeCatalog.getNodeMap(): { [string]: string }
	local map: { [string]: string } = {}
	for code, meta in BY_CODE do
		map[code] = meta.nodeName
	end
	return map
end

function ChallengeCatalog.getDifficultyLabel(difficulty: number, code: string?): string
	if code ~= nil then
		local meta = BY_CODE[code]
		if meta ~= nil then
			return meta.difficultyLabel
		end
	end
	if difficulty <= 1 then
		return "Fácil"
	elseif difficulty == 2 then
		return "Media"
	else
		return "Difícil"
	end
end

return ChallengeCatalog
