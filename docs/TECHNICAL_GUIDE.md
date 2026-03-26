# Technical Guide — Agentic MCP Itinerary PoC

> Guía técnica completa para desarrolladores. Objetivo: entender, replicar y extender este sistema desde cero.

---

## Índice

1. [¿Qué es esto y por qué importa?](#1-qué-es-esto-y-por-qué-importa)
2. [Arquitectura general](#2-arquitectura-general)
3. [Stack tecnológico](#3-stack-tecnológico)
4. [Protocolo MCP](#4-protocolo-mcp)
5. [FastMCP — el servidor MCP](#5-fastmcp--el-servidor-mcp)
6. [LangGraph — el agente interno](#6-langgraph--el-agente-interno)
7. [OAuth 2.1 — autenticación](#7-oauth-21--autenticación)
8. [MCP downstream — los mocks](#8-mcp-downstream--los-mocks)
9. [Deploy en Railway](#9-deploy-en-railway)
10. [Flujo completo de una petición](#10-flujo-completo-de-una-petición)
11. [Cómo replicarlo desde cero](#11-cómo-replicarlo-desde-cero)
12. [Extensiones y mejoras](#12-extensiones-y-mejoras)

---

## 1. ¿Qué es esto y por qué importa?

### El problema

Los clientes LLM modernos (Claude Desktop, ChatGPT, Cursor) soportan **MCP (Model Context Protocol)**: un estándar para que los modelos llamen a herramientas externas. Pero los MCP servers existentes son simples wrappers de APIs — el modelo cliente tiene que orquestar todo él solo.

### La propuesta

**Un MCP server que internamente corre su propio agente LLM.** El cliente ve una interfaz limpia (4-5 tools), pero detrás hay un agente con memoria, lógica de dominio, y capacidad de orquestar múltiples fuentes de datos en paralelo.

```
ANTES (patrón habitual):
  Claude Desktop → llama a flights_tool → llama a hotels_tool → llama a activities_tool
  (Claude orquesta todo, conoce los detalles de cada API)

AHORA (este patrón):
  Claude Desktop → llama a create_itinerary("viaje a Tokio 5 días")
  (El agente interno orquesta flights + hotels + activities en paralelo)
  ← devuelve itinerario completo con confirmation_code
```

### Por qué es relevante

- El cliente LLM es **stateless** respecto al dominio — no necesita conocer las APIs internas
- El agente interno puede ser **especializado** (mejor en su dominio que un modelo genérico)
- El estado del itinerario persiste **entre turns** del mismo cliente
- Patrón reutilizable para cualquier dominio vertical (legal, médico, e-commerce…)

---

## 2. Arquitectura general

```
┌─────────────────────────────────────────────────────────────────────┐
│                        CLIENTE EXTERNO                              │
│              Claude Desktop / ChatGPT / Cursor                      │
│                                                                     │
│  Conoce solo 5 tools:                                               │
│  create_itinerary | refine_itinerary | get_itinerary |              │
│  list_itineraries | confirm_itinerary                               │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             │ MCP Protocol (HTTP/SSE)
                             │ Auth: OAuth 2.1 Bearer JWT
                             │
┌────────────────────────────▼────────────────────────────────────────┐
│                    TRAVEL AGENT SERVER                              │
│                   (server/main.py)                                  │
│                                                                     │
│  FastMCP 3.1.1                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  MCP Tool Handlers                                           │   │
│  │  create_itinerary() → agent.run_graph(...)                  │   │
│  │  refine_itinerary() → agent.run_graph(...)                  │   │
│  │  get_itinerary()    → checkpointer.get(...)                 │   │
│  │  confirm_itinerary() → agent.run_graph(...)                 │   │
│  └────────────────────────────────────────────────────────────┬─┘   │
│                                                               │     │
│  SimpleOAuthProvider (server/auth.py)                        │     │
│  ┌─────────────────────────────────────┐                     │     │
│  │  /authorize → /oauth/authorize      │                     │     │
│  │  /oauth/authorize → login HTML form │                     │     │
│  │  /token → JWT HS256                 │                     │     │
│  └─────────────────────────────────────┘                     │     │
└──────────────────────────────────────────────────────────────┼──────┘
                                                               │
                                                               │ Invoca
                                                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    LANGGRAPH AGENT                                   │
│                   (server/agent.py)                                  │
│                                                                     │
│  ┌──────────┐     ┌─────────────────────────────────────────────┐   │
│  │  START   │────▶│              planner_node                   │   │
│  └──────────┘     │   Gemini Flash decide qué hacer             │   │
│                   └───────────────────┬─────────────────────────┘   │
│                                       │ fan-out paralelo             │
│                        ┌─────────────┼──────────────┐               │
│                        ▼             ▼              ▼               │
│               ┌──────────────┐ ┌──────────┐ ┌───────────────┐      │
│               │ flights_node │ │hotels_node│ │activities_node│      │
│               │  MCP client  │ │MCP client │ │  MCP client   │      │
│               └──────┬───────┘ └─────┬────┘ └───────┬───────┘      │
│                      └───────────────┼───────────────┘               │
│                                      │ fan-in                        │
│                                      ▼                               │
│                        ┌─────────────────────────┐                   │
│                        │      assembler_node      │                   │
│                        │  Gemini Flash compila    │                   │
│                        │  el itinerario final     │                   │
│                        └─────────────────────────┘                   │
│                                                                     │
│  Checkpointer: MemorySaver (estado persistente por thread_id)       │
└──────────────────────────────────────────────────────────────────────┘
                    │              │              │
                    │  MCP STDIO   │  MCP STDIO   │  MCP STDIO
                    ▼              ▼              ▼
          ┌──────────────┐ ┌──────────────┐ ┌───────────────────┐
          │ flights_mcp  │ │ hotels_mcp   │ │ activities_mcp    │
          │  (mock)      │ │  (mock)      │ │  (mock)           │
          └──────────────┘ └──────────────┘ └───────────────────┘
```

---

## 3. Stack tecnológico

### Dependencias principales

| Librería | Versión | Rol |
|---|---|---|
| `fastmcp` | 3.1.1 | Framework para construir MCP servers en Python |
| `mcp` | ≥1.0.0 | SDK oficial MCP (cliente STDIO para downstream) |
| `langgraph` | latest | Orquestador del agente interno (grafo de nodos) |
| `langchain-google-genai` | latest | Integración LangChain con Gemini |
| `PyJWT` | ≥2.0.0 | Firma y verificación de JWT para OAuth |
| `starlette` | (dep de fastmcp) | Routing HTTP adicional (form de login) |
| `httpx` | latest | Cliente HTTP async (usado por fastmcp internamente) |
| `python-dotenv` | latest | Variables de entorno en desarrollo local |

### Por qué FastMCP y no el SDK oficial

El SDK oficial de MCP (`mcp`) es bajo nivel — gestiona el protocolo pero no el servidor HTTP. **FastMCP** es un framework de alto nivel que:

- Convierte funciones Python en MCP tools con un decorator (`@mcp.tool()`)
- Gestiona el transport HTTP/SSE y STDIO
- Integra OAuth 2.1 mediante `OAuthProvider` (desde v3.x)
- Expone `/.well-known/oauth-authorization-server` automáticamente

### Por qué LangGraph y no LangChain/ReAct directo

LangGraph permite definir el agente como un **grafo dirigido** con nodos y edges. Ventajas clave para este caso:

- **Fan-out nativo**: puedes enviar el estado a múltiples nodos en paralelo y recoger los resultados (fan-in)
- **Checkpointing**: estado del grafo persiste entre invocaciones con el mismo `thread_id`
- **Control explícito del flujo**: no dependes de que el LLM decida cuándo llamar a qué tool

---

## 4. Protocolo MCP

MCP (Model Context Protocol, lanzado por Anthropic) es un estándar JSON-RPC sobre HTTP/SSE o STDIO. Define:

- **Tools**: funciones que el LLM puede llamar
- **Resources**: datos que el LLM puede leer
- **Prompts**: plantillas de prompts reutilizables

### Transports soportados

| Transport | Cuándo usarlo |
|---|---|
| STDIO | Desarrollo local; el cliente lanza el servidor como subproceso |
| HTTP/SSE | Producción; el servidor es un proceso independiente accesible por URL |
| Streamable HTTP | Nueva variante de HTTP/SSE (la que usa este proyecto en Railway) |

### Handshake MCP

```
Cliente → POST /mcp  {"method": "initialize", ...}
Servidor → {"capabilities": {"tools": {...}}, ...}
Cliente → POST /mcp  {"method": "tools/list"}
Servidor → lista de tools con schemas JSON
Cliente → POST /mcp  {"method": "tools/call", "params": {"name": "create_itinerary", ...}}
Servidor → resultado
```

### Discovery OAuth (RFC 8414)

Cuando el cliente intenta conectar a un MCP server remoto:
1. Hace GET `/.well-known/oauth-authorization-server`
2. Parsea los endpoints (`authorization_endpoint`, `token_endpoint`)
3. Inicia el Authorization Code Flow

FastMCP expone este endpoint automáticamente cuando se configura un `OAuthProvider`.

---

## 5. FastMCP — el servidor MCP

### `server/main.py` — estructura

```python
from fastmcp import FastMCP
from auth import SimpleOAuthProvider

# Configurar OAuth provider
oauth = SimpleOAuthProvider(
    base_url=os.getenv("MCP_BASE_URL", "http://localhost:8000")
)

# Crear servidor MCP con OAuth
mcp = FastMCP(
    name="travel-agent",
    auth=oauth,
)

# Definir tools
@mcp.tool()
async def create_itinerary(requirements: str) -> dict:
    """Crea un itinerario de viaje completo."""
    itinerary_id = str(uuid.uuid4())
    result = await run_graph(
        thread_id=itinerary_id,
        action="create",
        payload=requirements
    )
    return {"itinerary_id": itinerary_id, "draft": result}

# Health check público (sin auth)
@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    return JSONResponse({"status": "ok", "server": "travel-agent"})

# Arrancar servidor
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
```

### Anatomía de un MCP tool en FastMCP

```python
@mcp.tool()
async def mi_tool(param1: str, param2: int = 10) -> dict:
    """
    Descripción que ve el LLM cliente.
    
    Args:
        param1: Descripción del parámetro (el LLM la usa para entender qué poner)
        param2: Parámetro opcional con valor por defecto
    """
    # FastMCP infiere el JSON Schema automáticamente desde las type hints
    # El LLM cliente recibe:
    # {
    #   "name": "mi_tool",
    #   "description": "Descripción que ve el LLM cliente...",
    #   "inputSchema": {
    #     "type": "object",
    #     "properties": {
    #       "param1": {"type": "string", "description": "Descripción del parámetro"},
    #       "param2": {"type": "integer", "default": 10}
    #     },
    #     "required": ["param1"]
    #   }
    # }
    return {"resultado": "..."}
```

### `custom_route` para endpoints adicionales

```python
from starlette.responses import JSONResponse

@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    # Este endpoint NO requiere auth OAuth
    return JSONResponse({"status": "ok"})
```

---

## 6. LangGraph — el agente interno

### `server/state.py` — el estado del grafo

```python
from typing import TypedDict, Optional
from langgraph.checkpoint.memory import MemorySaver

class ItineraryState(TypedDict):
    action: str                    # "create" | "refine" | "confirm"
    requirements: Optional[str]    # Input del usuario
    change_request: Optional[str]  # Para refinements
    flights: Optional[dict]        # Resultado del nodo de vuelos
    hotels: Optional[dict]         # Resultado del nodo de hoteles
    activities: Optional[dict]     # Resultado del nodo de actividades
    draft: Optional[str]           # Itinerario compilado
    status: str                    # "draft" | "confirmed"
    confirmation_code: Optional[str]

# Checkpointer: guarda el estado entre invocaciones del grafo
# MemorySaver = en RAM (se pierde al reiniciar)
# SqliteSaver = en disco (persiste entre reinicios)
checkpointer = MemorySaver()
```

### `server/agent.py` — el grafo LangGraph

```python
from langgraph.graph import StateGraph, END
from langchain_google_genai import ChatGoogleGenerativeAI
from state import ItineraryState, checkpointer

llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash")

# Definir nodos
async def planner_node(state: ItineraryState) -> ItineraryState:
    """Decide qué hacer basándose en el estado actual."""
    # Para "create": lanza búsqueda en paralelo
    # Para "refine": actualiza el draft con el change_request
    # Para "confirm": genera confirmation_code
    ...

async def flights_node(state: ItineraryState) -> ItineraryState:
    """Busca vuelos via MCP downstream."""
    result = await call_flights_mcp(state["requirements"])
    return {**state, "flights": result}

async def hotels_node(state: ItineraryState) -> ItineraryState:
    """Busca hoteles via MCP downstream."""
    ...

async def activities_node(state: ItineraryState) -> ItineraryState:
    """Busca actividades via MCP downstream."""
    ...

async def assembler_node(state: ItineraryState) -> ItineraryState:
    """Compila vuelos + hoteles + actividades en un itinerario coherente."""
    prompt = f"""
    Compila este itinerario de viaje:
    VUELOS: {state['flights']}
    HOTELES: {state['hotels']}
    ACTIVIDADES: {state['activities']}
    REQUISITOS ORIGINALES: {state['requirements']}
    
    Genera un itinerario detallado día a día.
    """
    response = await llm.ainvoke(prompt)
    return {**state, "draft": response.content}

# Construir el grafo
builder = StateGraph(ItineraryState)
builder.add_node("planner", planner_node)
builder.add_node("flights", flights_node)
builder.add_node("hotels", hotels_node)
builder.add_node("activities", activities_node)
builder.add_node("assembler", assembler_node)

builder.set_entry_point("planner")

# Fan-out: planner → [flights, hotels, activities] en paralelo
builder.add_edge("planner", "flights")
builder.add_edge("planner", "hotels")
builder.add_edge("planner", "activities")

# Fan-in: [flights, hotels, activities] → assembler
builder.add_edge("flights", "assembler")
builder.add_edge("hotels", "assembler")
builder.add_edge("activities", "assembler")

builder.add_edge("assembler", END)

# Compilar con checkpointer
graph = builder.compile(checkpointer=checkpointer)

# Función helper para invocar el grafo
async def run_graph(thread_id: str, action: str, payload: str) -> dict:
    config = {"configurable": {"thread_id": thread_id}}
    initial_state = ItineraryState(
        action=action,
        requirements=payload if action == "create" else None,
        change_request=payload if action == "refine" else None,
        ...
    )
    result = await graph.ainvoke(initial_state, config=config)
    return result
```

### Cómo funciona el checkpointing

Cuando LangGraph ejecuta el grafo con un `thread_id`, guarda el estado tras cada nodo. En la siguiente invocación con el mismo `thread_id`, el grafo carga el estado anterior y continúa desde ahí.

```python
# Primera llamada — crea el itinerario
await graph.ainvoke(state, config={"configurable": {"thread_id": "abc-123"}})
# Estado guardado: {flights: ..., hotels: ..., activities: ..., draft: "..."}

# Segunda llamada — refina (carga el estado anterior automáticamente)
await graph.ainvoke(
    {"action": "refine", "change_request": "prefiero hotel 5 estrellas"},
    config={"configurable": {"thread_id": "abc-123"}}  # mismo thread_id
)
# El grafo tiene acceso al draft anterior + vuelos + hoteles anteriores
```

---

## 7. OAuth 2.1 — autenticación

### ¿Por qué OAuth 2.1 y no un Bearer token estático?

Un Bearer token estático es válido para demos pero tiene problemas:
- Cualquiera con la URL puede descubrir el token
- No hay expiración ni revocación
- Claude Desktop y ChatGPT ahora soportan OAuth nativo — el usuario hace login con su browser

### Flujo OAuth 2.1 Authorization Code + PKCE

```
Cliente MCP                  Travel Agent Server            Browser del usuario
     │                              │                              │
     │ GET /.well-known/...         │                              │
     │─────────────────────────────▶│                              │
     │◀─────────────────────────────│                              │
     │  {authorization_endpoint,    │                              │
     │   token_endpoint, ...}       │                              │
     │                              │                              │
     │ 1. Genera code_verifier      │                              │
     │    code_challenge = SHA256(code_verifier)                   │
     │                              │                              │
     │ GET /authorize?              │                              │
     │   client_id=...              │                              │
     │   redirect_uri=localhost:... │                              │
     │   code_challenge=...         │                              │
     │   response_type=code         │                              │
     │─────────────────────────────▶│                              │
     │                              │ Guarda pending_authorization │
     │                              │ Genera code temporal         │
     │◀─────────────────────────────│                              │
     │  302 → /oauth/authorize      │                              │
     │        ?code=<temp>          │                              │
     │                              │                              │
     │  Abre browser ──────────────────────────────────────────────▶
     │                              │ GET /oauth/authorize?code=... │
     │                              │◀─────────────────────────────│
     │                              │                              │
     │                              │ Muestra form HTML            │
     │                              │─────────────────────────────▶│
     │                              │   User entra user/pass       │
     │                              │◀─────────────────────────────│
     │                              │                              │
     │                              │ Valida credenciales          │
     │                              │ Emite auth_code real         │
     │                              │                              │
     │                              │ 302 → redirect_uri?code=...  │
     │                              │─────────────────────────────▶│
     │◀─────────────────────────────────────────────────────────────
     │  code=<auth_code>            │                              │
     │                              │                              │
     │ POST /token                  │                              │
     │   code=<auth_code>           │                              │
     │   code_verifier=...          │                              │
     │─────────────────────────────▶│                              │
     │                              │ Verifica PKCE                │
     │                              │ Emite JWT HS256 (1h)         │
     │◀─────────────────────────────│                              │
     │  access_token=<JWT>          │                              │
     │                              │                              │
     │ POST /mcp                    │                              │
     │   Authorization: Bearer <JWT>│                              │
     │─────────────────────────────▶│                              │
     │                              │ Verifica JWT                 │
     │                              │ Ejecuta tool                 │
     │◀─────────────────────────────│                              │
     │  resultado                   │                              │
```

### `server/auth.py` — implementación

La clase `SimpleOAuthProvider` extiende `OAuthProvider` de FastMCP. Métodos que hay que implementar:

```python
class SimpleOAuthProvider(OAuthProvider):
    
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        """
        Recupera info del cliente OAuth por client_id.
        En este PoC: cualquier client_id es válido (AnyRedirectClient).
        En producción: buscar en DB.
        """
    
    async def authorize(self, client, params: AuthorizationParams) -> str:
        """
        Llamado cuando el cliente inicia el Authorization Code Flow.
        Debe devolver la URL a la que redirigir al usuario (el form de login).
        """
        # Guardamos la pending_authorization con todos los params
        # Devolvemos la URL del form de login
        return f"/oauth/authorize?code={temp_code}"
    
    async def load_authorization_code(self, client, code: str) -> AuthorizationCode | None:
        """Recupera un auth code emitido por el login form."""
    
    async def exchange_authorization_code(self, client, auth_code) -> OAuthToken:
        """
        Intercambia el auth code por un access token.
        Aquí emitimos el JWT.
        """
        token = jwt.encode(payload, self._jwt_secret, algorithm="HS256")
        return OAuthToken(access_token=token, token_type="Bearer", expires_in=3600)
    
    async def load_access_token(self, token: str) -> AccessToken | None:
        """
        Verifica un JWT en cada request al MCP server.
        FastMCP llama a este método en cada tool call.
        """
        claims = jwt.decode(token, self._jwt_secret, algorithms=["HS256"])
        return AccessToken(token=token, client_id=..., scopes=..., expires_at=...)
    
    def get_routes(self, mcp_path=None) -> list[Route]:
        """
        Añade rutas adicionales al servidor Starlette.
        Aquí registramos /oauth/authorize (el form HTML).
        """
        routes = super().get_routes(mcp_path)
        routes.append(Route("/oauth/authorize", self._authorization_form, methods=["GET", "POST"]))
        return routes
```

### Clases auxiliares

**`AnyRedirectClient`**: subclase de `OAuthClientInformationFull` que acepta cualquier `redirect_uri`. Necesario porque Claude Desktop usa `localhost:PORT` dinámico como redirect.

```python
class AnyRedirectClient(OAuthClientInformationFull):
    def validate_redirect_uri(self, redirect_uri):
        if redirect_uri is None:
            raise InvalidRedirectUriError("redirect_uri must be specified")
        return redirect_uri  # Acepta cualquier redirect
```

**`PendingAuthorization`**: dataclass que guarda el estado entre el `/authorize` y el POST del form.

```python
@dataclass
class PendingAuthorization:
    client_id: str
    redirect_uri: Any
    scopes: list[str]
    code_challenge: str  # Para verificar PKCE
    state: str | None
    expires_at: float    # 10 minutos de validez
```

---

## 8. MCP downstream — los mocks

### Arquitectura

Cada mock es un FastMCP server **independiente** que se lanza como **subproceso STDIO**. Cuando el agente necesita buscar vuelos, lanza el proceso `flights_mcp.py`, le manda la petición MCP por stdin, y recibe la respuesta por stdout.

```python
# server/tools/flights.py
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def search_flights(origin: str, destination: str, date: str) -> dict:
    server_params = StdioServerParameters(
        command="python3",
        args=["mocks/flights_mcp.py"],
        env=None
    )
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "search_flights",
                {"origin": origin, "destination": destination, "date": date}
            )
            return result.content[0].text
```

### `mocks/flights_mcp.py` — estructura de un mock

```python
from fastmcp import FastMCP

mcp = FastMCP(name="flights-mock")

@mcp.tool()
async def search_flights(origin: str, destination: str, date: str) -> dict:
    """Busca vuelos disponibles (datos mock)."""
    return {
        "flights": [
            {
                "airline": "Iberia",
                "flight": "IB6821",
                "origin": origin,
                "destination": destination,
                "date": date,
                "price": 450,
                "duration": "12h30m"
            },
            # ... más vuelos
        ]
    }

if __name__ == "__main__":
    mcp.run(transport="stdio")  # STDIO para ser lanzado como subproceso
```

### Por qué STDIO y no HTTP para los mocks

En producción, los MCP downstream serían servicios HTTP independientes (Amadeus API wrapper, Booking.com MCP, etc.). Para el PoC, STDIO es más simple: no hay que gestionar puertos, los procesos mueren solos cuando termina la sesión.

---

## 9. Deploy en Railway

### Por qué Railway

- Deploy desde GitHub en un click
- Variables de entorno desde dashboard
- Dominio público automático (TLS incluido)
- Soporte nativo para Python

### Por qué RAILPACK y no nixpacks

Nixpacks (el builder por defecto de Railway) falla con proyectos Python que tienen dependencias complejas porque intenta instalar paquetes en un entorno Nix inmutable. RAILPACK detecta automáticamente el `pyproject.toml` y crea un virtualenv estándar.

### `railway.toml`

```toml
[build]
builder = "RAILPACK"

[deploy]
startCommand = "PYTHONPATH=server /opt/venv/bin/python3 server/main.py"
healthcheckPath = "/health"
healthcheckTimeout = 30
```

**`PYTHONPATH=server`**: permite que `main.py` haga `from auth import SimpleOAuthProvider` sin rutas relativas. Railway no añade el directorio del script al path automáticamente.

**`/opt/venv/bin/python3`**: ruta absoluta al Python del virtualenv que RAILPACK crea. Más robusto que `python3` (que podría apuntar al sistema).

### `pyproject.toml`

```toml
[project]
name = "agentic-mcp-itinerary"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastmcp>=3.1.1",
    "mcp>=1.0.0",
    "PyJWT>=2.0.0",
    "langgraph",
    "langchain-google-genai",
    "python-dotenv",
    "httpx",
]

[build-system]
requires = ["setuptools"]
build-backend = "setuptools.backends.legacy:build"
```

### Variables de entorno en Railway

| Variable | Valor en producción |
|---|---|
| `GEMINI_API_KEY` | API key de Google AI Studio |
| `MCP_USERNAME` | Usuario para el login |
| `MCP_PASSWORD` | Contraseña para el login |
| `MCP_JWT_SECRET` | `secrets.token_urlsafe(32)` — generar una vez |
| `MCP_BASE_URL` | `https://tu-proyecto.up.railway.app` |
| `PORT` | Railway lo inyecta automáticamente |

### Trigger de deploy por API

Railway NO hace deploy automático al hacer push (a menos que se configure). Para triggerarlo por API:

```bash
curl -X POST https://backboard.railway.app/graphql/v2 \
  -H "Authorization: Bearer $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation { serviceInstanceDeploy(serviceId: \"SERVICE_ID\", environmentId: \"ENV_ID\", latestCommit: true) }"
  }'
```

---

## 10. Flujo completo de una petición

### `create_itinerary("Viaje a Tokio 5 días, presupuesto 2000€")`

```
1. Claude Desktop
   └── POST /mcp
       Authorization: Bearer <JWT>
       {"method": "tools/call", "name": "create_itinerary",
        "arguments": {"requirements": "Viaje a Tokio 5 días..."}}

2. FastMCP (main.py)
   ├── SimpleOAuthProvider.load_access_token(JWT) → AccessToken válido
   └── Llama a create_itinerary("Viaje a Tokio 5 días...")

3. create_itinerary() en main.py
   ├── Genera itinerary_id = uuid4()
   └── await run_graph(thread_id=itinerary_id, action="create", payload="Viaje a Tokio...")

4. LangGraph (agent.py)
   ├── planner_node: Gemini Flash analiza los requisitos
   │   └── Determina: origen=Madrid, destino=Tokyo, fechas=..., budget=2000€
   │
   ├── [PARALELO] flights_node, hotels_node, activities_node
   │   ├── flights_node:
   │   │   ├── Lanza subproceso: python3 mocks/flights_mcp.py
   │   │   ├── MCP STDIO: call_tool("search_flights", {origin:"MAD", dest:"TYO"})
   │   │   └── Recibe: [{airline: "Iberia", price: 850, ...}, ...]
   │   │
   │   ├── hotels_node:
   │   │   ├── Lanza subproceso: python3 mocks/hotels_mcp.py
   │   │   ├── MCP STDIO: call_tool("search_hotels", {city: "Tokyo", nights: 5})
   │   │   └── Recibe: [{name: "Park Hyatt Tokyo", price: 320/noche, ...}, ...]
   │   │
   │   └── activities_node:
   │       ├── Lanza subproceso: python3 mocks/activities_mcp.py
   │       ├── MCP STDIO: call_tool("search_activities", {city: "Tokyo"})
   │       └── Recibe: [{name: "Templo Senso-ji", price: 0, ...}, ...]
   │
   └── assembler_node:
       ├── Gemini Flash recibe: flights + hotels + activities + requirements
       ├── Genera itinerario día a día
       └── State guardado en MemorySaver con key=itinerary_id

5. Respuesta a Claude Desktop:
   {
     "itinerary_id": "abc-123-...",
     "status": "draft",
     "draft": "## Itinerario Tokio 5 días\n\nDÍA 1: Llegada...",
     "budget_summary": {
       "vuelos": 850,
       "hoteles": 1600,
       "actividades": 150,
       "total": 2600
     }
   }

6. Claude Desktop muestra el resultado al usuario
```

### `refine_itinerary("abc-123-...", "Prefiero hotel más céntrico")`

```
1. LangGraph carga el estado previo de MemorySaver (thread_id="abc-123-...")
2. planner_node: Gemini Flash ve el historial + el change_request
3. Solo ejecuta hotels_node (vuelos y actividades no cambian)
4. assembler_node recompila con el nuevo hotel
5. Estado actualizado en MemorySaver
```

---

## 11. Cómo replicarlo desde cero

### Paso 1: Estructura del proyecto

```bash
mkdir mi-agentic-mcp && cd mi-agentic-mcp
mkdir server server/tools mocks tests
```

### Paso 2: `pyproject.toml`

```toml
[project]
name = "mi-agentic-mcp"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastmcp>=3.1.1",
    "mcp>=1.0.0",
    "PyJWT>=2.0.0",
    "langgraph",
    "langchain-google-genai",
    "python-dotenv",
]

[build-system]
requires = ["setuptools"]
build-backend = "setuptools.backends.legacy:build"
```

### Paso 3: MCP mocks (los servicios downstream)

Crea `mocks/mi_servicio_mcp.py`:

```python
from fastmcp import FastMCP

mcp = FastMCP(name="mi-servicio-mock")

@mcp.tool()
async def buscar_datos(query: str) -> dict:
    """Busca datos (mock)."""
    return {"resultados": [{"item": "ejemplo", "precio": 100}]}

if __name__ == "__main__":
    mcp.run(transport="stdio")
```

### Paso 4: Cliente MCP para los mocks

Crea `server/tools/mi_servicio.py`:

```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import json

async def buscar_datos(query: str) -> dict:
    params = StdioServerParameters(command="python3", args=["mocks/mi_servicio_mcp.py"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("buscar_datos", {"query": query})
            return json.loads(result.content[0].text)
```

### Paso 5: State y checkpointer

Crea `server/state.py`:

```python
from typing import TypedDict, Optional
from langgraph.checkpoint.memory import MemorySaver

class MiState(TypedDict):
    action: str
    input: Optional[str]
    resultado: Optional[dict]
    status: str

checkpointer = MemorySaver()
```

### Paso 6: Grafo LangGraph

Crea `server/agent.py`:

```python
from langgraph.graph import StateGraph, END
from langchain_google_genai import ChatGoogleGenerativeAI
from state import MiState, checkpointer
from tools.mi_servicio import buscar_datos

llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash")

async def mi_nodo(state: MiState) -> MiState:
    datos = await buscar_datos(state["input"])
    respuesta = await llm.ainvoke(f"Resume esto: {datos}")
    return {**state, "resultado": {"resumen": respuesta.content}, "status": "done"}

builder = StateGraph(MiState)
builder.add_node("mi_nodo", mi_nodo)
builder.set_entry_point("mi_nodo")
builder.add_edge("mi_nodo", END)
graph = builder.compile(checkpointer=checkpointer)

async def run_graph(thread_id: str, action: str, input_text: str) -> dict:
    config = {"configurable": {"thread_id": thread_id}}
    state = MiState(action=action, input=input_text, resultado=None, status="running")
    return await graph.ainvoke(state, config=config)
```

### Paso 7: OAuth provider

Copia `server/auth.py` de este repo (es genérico y reutilizable sin modificaciones).

Ajusta solo si necesitas:
- Múltiples usuarios (añade DB lookup en `handle_authorization_form`)
- Scopes personalizados (modifica `validate_scope` en `AnyRedirectClient`)
- Expiración diferente (cambia `DEFAULT_ACCESS_TOKEN_EXPIRY_SECONDS`)

### Paso 8: FastMCP server principal

Crea `server/main.py`:

```python
import os
import uuid
from fastmcp import FastMCP
from starlette.responses import JSONResponse
from auth import SimpleOAuthProvider
from agent import run_graph

oauth = SimpleOAuthProvider(base_url=os.getenv("MCP_BASE_URL", "http://localhost:8000"))
mcp = FastMCP(name="mi-agente", auth=oauth)

@mcp.tool()
async def procesar(input_text: str) -> dict:
    """Procesa una petición con el agente interno."""
    session_id = str(uuid.uuid4())
    result = await run_graph(thread_id=session_id, action="process", input_text=input_text)
    return {"session_id": session_id, "resultado": result["resultado"]}

@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    return JSONResponse({"status": "ok"})

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
```

### Paso 9: Deploy en Railway

```bash
# railway.toml
cat > railway.toml << EOF
[build]
builder = "RAILPACK"

[deploy]
startCommand = "PYTHONPATH=server /opt/venv/bin/python3 server/main.py"
healthcheckPath = "/health"
EOF

# Subir a GitHub
git init && git add -A && git commit -m "initial"
git remote add origin https://github.com/tu-user/mi-agentic-mcp.git
git push -u origin main

# Crear proyecto en Railway y enlazar el repo desde dashboard
# Añadir variables de entorno:
# GEMINI_API_KEY, MCP_USERNAME, MCP_PASSWORD, MCP_JWT_SECRET, MCP_BASE_URL
```

### Paso 10: Configurar Claude Desktop

En `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "mi-agente": {
      "type": "http",
      "url": "https://tu-proyecto.up.railway.app/mcp"
    }
  }
}
```

Reinicia Claude Desktop. La primera tool call abrirá el browser para el login OAuth.

---

## 12. Extensiones y mejoras

### Persistencia real (SqliteSaver)

Sustituir `MemorySaver` por `SqliteSaver`:

```python
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

async with AsyncSqliteSaver.from_conn_string("checkpoints.db") as checkpointer:
    graph = builder.compile(checkpointer=checkpointer)
```

Para Railway: usar un volumen persistente o Postgres con `PostgresSaver`.

### Multi-usuario OAuth

En lugar de env vars, usar una DB:

```python
async def handle_authorization_form(self, username, password, code, state):
    user = await db.get_user(username)
    if not user or not bcrypt.checkpw(password, user.password_hash):
        return HTMLResponse("Invalid credentials", 401)
    # ...
```

### MCP downstream reales

Reemplazar los mocks por wrappers de APIs reales:

```python
# server/tools/flights.py — con Amadeus API
import httpx

async def search_flights(origin: str, destination: str, date: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.amadeus.com/v2/shopping/flight-offers",
            headers={"Authorization": f"Bearer {AMADEUS_TOKEN}"},
            params={"originLocationCode": origin, ...}
        )
        return resp.json()
```

### Streaming de resultados

LangGraph soporta streaming del estado mientras el grafo se ejecuta:

```python
async for event in graph.astream_events(state, config=config, version="v2"):
    if event["event"] == "on_chain_stream":
        yield event["data"]  # FastMCP puede hacer streaming al cliente MCP
```

### Observabilidad con LangSmith

```python
import os
os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGCHAIN_API_KEY"] = "tu-langsmith-key"
# Cada invocación del grafo aparece en LangSmith con el trace completo
```

---

*Documentación generada para el PoC de Agentic MCP Itinerary — marzo 2026*
