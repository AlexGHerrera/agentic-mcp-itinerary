# Agentic MCP Itinerary PoC

PoC de un servidor MCP que orquesta búsquedas paralelas de vuelos, hoteles y actividades, con estado persistente vía LangGraph + SQLite.

## Requisitos

- Python 3.11+
- `ANTHROPIC_API_KEY` configurada

## Instalación

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Ejecutar mocks (3 procesos)

Los clientes MCP de `server/tools/` lanzan los mocks por STDIO en procesos separados cuando se requieren. Para depuración manual puedes iniciarlos en terminales separadas:

```bash
python mocks/flights_mcp.py
```

```bash
python mocks/hotels_mcp.py
```

```bash
python mocks/activities_mcp.py
```

## Ejecutar el servidor principal (STDIO)

```bash
python server/main.py
```

El estado persistente se guarda en `storage/checkpoints.db`.

## Claude Desktop

1. Copia el archivo `claude_desktop_config.json` y actualiza la ruta absoluta al `server/main.py`.
2. Asegura `ANTHROPIC_API_KEY` en el bloque `env`.
3. Reinicia Claude Desktop y habilita el MCP server `travel-agent`.

## Deploy en Railway

1. Crea un nuevo servicio y apunta el repo.
2. Configura las variables de entorno requeridas:
   - `GEMINI_API_KEY`
   - `MCP_API_KEY`
3. El servicio expone `/health` para checks y usa `PORT` inyectado por Railway.

## Notas de PoC

- El agente interno usa el modelo `claude-3-5-haiku-20241022`.
- Las búsquedas de vuelos/hoteles/actividades se hacen en paralelo.
- Si un mock falla, el itinerario se genera con los datos disponibles y se agrega un aviso.
- El coste total nunca excede el presupuesto indicado.
