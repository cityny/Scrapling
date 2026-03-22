# MCP Deep Analysis — Endpoints, Session Handshake y opciones

Resumen ejecutivo:

- Scrapling delega la lógica HTTP/Streamable transport al paquete `mcp` (clase `FastMCP`). Scrapling no implementa handlers HTTP custom adicionales; expone `ScraplingMCPServer` que registra herramientas y llama a `server.run(transport=...)`.
- En la práctica esto significa que la negociación del `sessionId`, validación de POSTs y rutas HTTP las maneja `FastMCP` (fuera del repo). No hay endpoint "oculto" en el código de Scrapling para evitar la negociación SSE.

Evidencia en el repositorio:

- Comando CLI que inicia el servidor: [Scrapling/cli.py](Scrapling/cli.py#L120-L160) — `mcp(http, host, port)` llama a `ScraplingMCPServer().serve(http, host, port)`.
- Registro de herramientas y ejecución del servidor: [Scrapling/core/ai.py](Scrapling/core/ai.py#L360-L420) — `server = FastMCP(...); server.add_tool(...); server.run(transport=...)`.
- Gestión de sesiones internas de spiders: [Scrapling/spiders/session.py](Scrapling/spiders/session.py#L1-L80) — existe `SessionManager` y `default_session_id`, lo que demuestra que Scrapling espera sesiones identificadas.

Respuestas concretas

1. Endpoints ocultos que acepten JSON-RPC POST sin abrir SSE?

- No hay en Scrapling (repo) ningún endpoint HTTP adicional implementado que acepte una RPC POST sin sesión SSE previa. El servidor Streamable-HTTP es provisto por `FastMCP`; Scrapling no implementa rutas `/post` o `/call` ni handlers REST propios.
- Prueba recomendada: usar `curl -v -H "Accept: text/event-stream" http://HOST:8000/` y revisar la respuesta; después intentar `POST` y observar logs del contenedor.

2. Parámetros para desactivar validación estricta de sessionId en `server.run(transport='streamable-http')`?

- En Scrapling NO hay parámetros adicionales: la llamada es exactamente `server.run(transport="streamable-http")` (sin flags extras) — ver [Scrapling/core/ai.py](Scrapling/core/ai.py#L410-L420).
- Cualquier capacidad para relajar validaciones depende de `FastMCP` (paquete externo). Para permitir sesiones stateless habría que: (a) cambiar cómo se instancia `FastMCP` pasando parámetros que la clase acepte (si los soporta), o (b) modificar/envolver la lógica de transporte en código propio (ej. implementar un wrapper HTTP que traduzca REST→MCP). Scrapling no ofrece esto nativamente.

3. ¿Existe `scrapling serve --api` o `scrapling mcp --rest`?

- No. El CLI expone `mcp` (streamable-http vs stdio) y comandos `extract`, `install`, `shell`, etc. No hay comando nativo para exponer las herramientas como REST puro; la opción nativa es MCP (stdio o streamable-http).

4. Si recibes `400 Bad Request: Missing session ID` incluso en la petición GET inicial SSE — ¿qué espera el servidor?

- Observaciones técnicas:
  - El flujo correcto es: primero abrir una conexión SSE (GET) con `Accept: text/event-stream` para que el transporte cree la sesión y envíe el `sessionId` en un evento `data: { ... }` inicial.
  - Si el GET devuelve 400, motivos probables:
    - No se envía el header `Accept: text/event-stream` (el servidor esperando SSE puede rechazar otras cabeceras).
    - Un proxy (nginx, Traefik) está alterando/mapeando la petición (p. ej. bloqueando `Transfer-Encoding: chunked` o `Connection`), o está exigiendo `Host`/`Origin`/`Upgrade` headers distintos.
    - Política CORS o un middleware de autenticación que exige autorización previa.
  - No hay en Scrapling código que valide cookies o cabeceras específicas; la exigencia viene de `FastMCP`.

Recomendaciones de diagnóstico si GET SSE devuelve 400:

- 1. Ejecuta un `curl -v` y copia la salida (headers request/response):

```bash
curl -v -N -H "Accept: text/event-stream" http://HOST:8000/ 2>&1 | sed -n '1,120p'
```

- 2. Prueba con ruta alternativa `/mcp`:

```bash
curl -v -N -H "Accept: text/event-stream" http://HOST:8000/mcp
```

- 3. Revisa `docker logs -f <container>` para ver el motivo exacto del 400.

- 4. Prueba con headers extra (a veces `Origin`/`User-Agent` u `Accept` son relevantes):

```bash
curl -v -N \
  -H "Accept: text/event-stream" \
  -H "Origin: http://localhost" \
  -H "User-Agent: curl/7" \
  http://HOST:8000/
```

5. Posible workaround si necesitas POST sin handshake SSE

- Implementa una fachada REST (FastAPI) que actúe como cliente MCP: la fachada abre internamente la sesión SSE (o mantiene una por contenedor) y expone endpoints REST que traduzcan calls REST→MCP. Ventajas:
  - Control de auth, healthcheck y compatibilidad REST para n8n.
  - Puedes centralizar sesiones persistentes (evitar handshake por cada request).

Ejemplo esqueleto (fastapi que reenvía a MCP via SSE o stdio):

```py
from fastapi import FastAPI, Request
import requests

app = FastAPI()

@app.post('/api/fetch')
async def api_fetch(body: dict):
    # implementación: abrir o reusar session SSE con FastMCP
    # enviar JSON-RPC y devolver resultado
    return {"ok": True}
```

6. Conclusión y acciones recomendadas

- Resumen de limitaciones: Scrapling no ofrece endpoints REST directos ni parámetros para relajar la validación de sessionId; todo ello depende del paquete `mcp` (FastMCP). Para eliminar la dependencia del handshake SSE en n8n debes:
  1. Crear una fachada REST que gestione sesiones SSE internamente (recomendado).
  2. O modificar cómo se instancia `FastMCP` (si la clase pública lo permite) para aceptar sesiones stateless — esto requiere revisar la documentación/implementación de `mcp`.

Referencias en el repo (evidencia rápida):

- `Scrapling/cli.py` — comando `mcp` → `ScraplingMCPServer().serve(...)`.
- `Scrapling/core/ai.py` — `FastMCP` import y `server.run(transport="streamable-http")`.
- `Scrapling/spiders/session.py` — `SessionManager` y `default_session_id`.

Si quieres, puedo:

- A) añadir un ejemplo `scripts/mcp_wrapper.py` que inicialice logging DEBUG y mantenga una sesión SSE reusable; o
- B) crear una pequeña fachada `scripts/mcp_facade/` con `FastAPI` que encapsule el handshake y exponga `/api/fetch` listo para n8n.

Indica si quieres la opción A o B y la creo en el repo.
