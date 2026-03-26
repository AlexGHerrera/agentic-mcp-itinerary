# Agentic MCP — Visión Ejecutiva

> Qué es, qué resuelve y por qué importa. Para perfiles no técnicos.

---

## El problema que existía antes

Los asistentes de IA como Claude o ChatGPT son muy potentes para conversar, pero cuando necesitan hacer algo real — buscar un vuelo, consultar stock, hacer una reserva — tienen que aprender a usar cada herramienta por separado.

Imagina pedirle a un asistente que organice un viaje de empresa:

> *"Organiza un viaje para 3 personas a Lisboa del 15 al 18 de abril, presupuesto 1.500€ por persona"*

Para responder bien, el asistente tiene que:
1. Buscar vuelos disponibles
2. Consultar hoteles en esas fechas
3. Revisar actividades o restaurantes
4. Cruzar toda esa información con el presupuesto
5. Presentar un plan coherente

Con los sistemas actuales, **el asistente gestiona todo esto él solo**, llamando a cada fuente una por una, recordando qué encontró, cruzando los datos... Es como pedirle a alguien que no conoce tu empresa que lo gestione todo sin ayuda.

El resultado: el asistente se "despista", pierde contexto, o simplemente da una respuesta genérica que no tiene en cuenta todos los factores.

---

## La solución: un experto detrás del asistente

**Agentic MCP** es un nuevo patrón tecnológico donde el asistente de IA no trabaja solo. En vez de eso, **delega en un agente especializado** que conoce el dominio en profundidad.

Funciona así:

```
El usuario habla con Claude o ChatGPT
         │
         │  "Organiza un viaje a Lisboa..."
         ▼
Claude reconoce que esto requiere al experto de viajes
         │
         │  Llama al Agente de Viajes →
         ▼
El Agente de Viajes trabaja en paralelo:
  ✈️  Busca vuelos         (simultáneamente)
  🏨  Busca hoteles        (simultáneamente)
  🎭  Busca actividades    (simultáneamente)
         │
         │  Cruza todo con el presupuesto y preferencias
         ▼
Devuelve un plan completo y coherente a Claude
         │
         ▼
Claude lo presenta al usuario de forma natural
```

**La diferencia clave**: el usuario sigue hablando con su asistente favorito. Pero detrás hay un experto que conoce cada detalle del dominio, trabaja más rápido, y recuerda toda la conversación.

---

## ¿Qué cambia en la práctica?

### Antes
- El asistente IA busca vuelos → espera → busca hotel → espera → busca actividades → espera → intenta compilar todo → da una respuesta aproximada
- Si el usuario refina la petición ("prefiero hotel más céntrico"), el asistente empieza casi desde cero
- El asistente no tiene "memoria" del proceso: cada conversación nueva es como empezar de cero

### Ahora
- El agente especializado busca vuelos + hoteles + actividades **al mismo tiempo** (hasta 3x más rápido)
- Si el usuario refina, el agente recuerda lo que ya encontró y solo actualiza lo que cambia
- El estado del itinerario persiste: se puede retomar días después, compartir con un compañero, o confirmar cuando se quiera

---

## Tres ejemplos de flujo real

### Ejemplo 1 — Planificación de viaje de empresa

**Usuario:** *"Necesito organizar una reunión en Madrid para el equipo de ventas, 8 personas, semana del 5 de mayo, máximo 800€ por persona"*

**Lo que hace el agente en segundo plano:**
- Busca vuelos desde las ciudades de origen de cada persona
- Encuentra un hotel con sala de reuniones disponible esa semana
- Reserva actividades de team building para la tarde del miércoles
- Calcula el coste total y advierte si alguna combinación supera el presupuesto

**Lo que ve el usuario:**
> *"He preparado dos opciones para la semana del 5 de mayo. La opción A incluye vuelos desde Barcelona y Sevilla, Hotel Marriott Madrid (sala de reuniones incluida), y una tarde en el Circuit de Jarama. Coste total estimado: 6.240€ (780€/persona). ¿Quieres que ajuste algo?"*

---

### Ejemplo 2 — Refinamiento iterativo

El usuario tiene el plan del ejemplo anterior pero quiere cambiarlo:

**Usuario:** *"El hotel me parece bien pero el Circuit está muy lejos, busca algo más céntrico"*

**Sin Agentic MCP:** el asistente recalcula todo desde cero.

**Con Agentic MCP:** el agente recuerda el contexto completo (vuelos ya fijados, hotel ya elegido, presupuesto restante) y solo busca una alternativa de actividad céntrica. Responde en segundos.

> *"He sustituido el Circuit por el Escape Room de Gran Vía y una cena en el restaurante DiverXO. El coste total baja a 6.100€ (762€/persona). ¿Confirmamos?"*

---

### Ejemplo 3 — Confirmación con memoria

Tres días después, el responsable de RRHH retoma la conversación:

**Usuario:** *"Adelante, confirma el viaje de Madrid"*

El agente recuerda exactamente qué viaje era, con todos los detalles, y genera el código de confirmación sin necesidad de repetir nada.

---

## ¿En qué otros dominios aplica?

Este patrón no es solo para viajes. La misma arquitectura se puede adaptar a cualquier dominio donde haya que:
- Consultar múltiples fuentes de información
- Cruzar datos con reglas de negocio
- Mantener contexto entre varias conversaciones

| Dominio | Agente especializado | Fuentes que consulta |
|---|---|---|
| **Viajes** | Travel Agent | Vuelos, hoteles, actividades |
| **RRHH** | HR Agent | Nóminas, vacaciones, contratos, normativa |
| **Legal** | Legal Agent | Contratos, jurisprudencia, plazos |
| **Ventas** | Sales Agent | CRM, catálogo, stock, precios, descuentos |
| **Soporte IT** | IT Support Agent | Tickets, inventario, documentación técnica |
| **Finanzas** | Finance Agent | Facturas, presupuestos, bancos, contabilidad |

---

## Ventajas competitivas del patrón

### 1. Compatibilidad universal
El agente especializado funciona con **cualquier cliente IA**: Claude, ChatGPT, Cursor, o cualquier herramienta que adopte el estándar MCP (que ya es la mayoría del mercado en 2026). No hay que crear una app propia.

### 2. Velocidad
Al consultar múltiples fuentes en paralelo (no una detrás de otra), el tiempo de respuesta es significativamente menor para tareas complejas.

### 3. Contexto persistente
El agente recuerda el estado de cada conversación. No hay que repetir información. Se puede retomar una tarea días después.

### 4. Especialización
El agente interno puede tener instrucciones, reglas de negocio y conocimiento del dominio que el asistente genérico no tiene. Sabe qué proveedores usar, qué políticas aplicar, qué excepciones existen.

### 5. Seguridad
La autenticación OAuth 2.1 garantiza que solo usuarios autorizados pueden acceder al agente. Cada sesión tiene un token con expiración. Las credenciales nunca viajan en texto plano.

### 6. Escalabilidad
Al ser un servicio independiente desplegado en la nube, puede atender múltiples usuarios simultáneamente sin interferencia entre conversaciones.

---

## Estado actual del mercado

A fecha de marzo de 2026, **ninguna empresa ofrece este patrón como producto**. Existe:

- Wrappers simples de APIs como MCP tools (sin agente interno)
- Agentes LLM orquestando múltiples APIs directamente (sin exponer como MCP)
- Frameworks de orquestación multi-agente (sin la capa MCP estándar)

**Este PoC demuestra el patrón completo**: agente especializado + memoria persistente + orquestación paralela + autenticación enterprise + compatible con los clientes IA más usados del mercado.

---

## El PoC en números

| Métrica | Valor |
|---|---|
| Tiempo de desarrollo del PoC | ~2 días |
| Líneas de código | ~1.200 |
| Tools expuestas al cliente IA | 5 |
| Fuentes consultadas en paralelo | 3 |
| Tiempo hasta respuesta (estimado) | 3-8 segundos |
| Plataforma de deploy | Railway (cloud) |
| Coste de infraestructura (Railway) | ~5€/mes para PoC |
| Clientes IA compatibles | Claude Desktop, ChatGPT, Cursor, y cualquier cliente MCP |

---

## Próximos pasos naturales

Si se quiere convertir este PoC en un producto real:

1. **Conectar fuentes reales** — sustituir los mocks por APIs reales (Amadeus para vuelos, Booking para hoteles, etc.)
2. **Multi-usuario** — base de datos de usuarios en lugar de credenciales únicas
3. **Memoria a largo plazo** — historial de viajes anteriores, preferencias del usuario, proveedores favoritos
4. **Dashboard** — panel de administración para gestionar itinerarios, ver estadísticas, ajustar reglas de negocio
5. **Vertical propio** — aplicar el mismo patrón al dominio de negocio principal

---

*Documento de visión ejecutiva — Agentic MCP Itinerary PoC — marzo 2026*
