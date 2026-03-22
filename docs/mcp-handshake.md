# MCP Streamable-HTTP — Handshake, endpoint y ejemplos prácticos

Resumen rápido:

- El transporte `streamable-http` usa SSE (Server-Sent Events). Debes abrir primero una conexión SSE (GET con `Accept: text/event-stream`) para crear/recibir la `sessionId`. Luego envías POSTs JSON que referencien esa `sessionId` para ejecutar herramientas.
- Error "Bad Request: Missing session ID" significa que estás enviando el POST sin indicar la `sessionId` asociada al canal SSE.

1. Ruta del endpoint

- Por defecto Scrapling levanta `FastMCP` en el host/puerto que pases. El handler HTTP suele estar en la raíz (`/`). Algunos proxies o deploys pueden exponer `/mcp` — prueba ambas rutas.

Prueba rápida (verifica cuál responde):

```bash
curl -i -H "Accept: text/event-stream" http://HOST:8000/
curl -i -H "Accept: text/event-stream" http://HOST:8000/mcp
```

2. Secuencia exacta (handshake + ejecutar herramienta)

a) Abrir SSE (crea la sesión y recibe sessionId)

```bash
# Mantén esta conexión abierta; el servidor enviará eventos SSE
curl -v -N \
  -H "Accept: text/event-stream" \
  http://HOST:8000/ > sse.out &

# Observa el primer bloque 'data:' para encontrar la sessionId
sed -n '1,20p' sse.out
```

Nota: el servidor suele enviar mensajes SSE en formato `data: {...}`. Busca un campo `sessionId` o `id` en ese JSON.

b) Extraer programáticamente la `sessionId` (ejemplo con jq)

```bash
# lee la primera línea de data: y parsea JSON
session_id=$(sed -n '1,20p' sse.out | grep '^data:' | sed 's/^data: //' | head -n1 | jq -r '.sessionId // .id')
echo "session: $session_id"
```

c) Enviar el job POST asociado a la sesión (ejemplo: `fetch`)

Headers y verbo:

- POST to `/` (o `/mcp`)
- `Content-Type: application/json`
- Añade `X-Session-Id: <session_id>` (cabecera recomendada) o `?sessionId=<session_id>` como query param si tu stack lo prefiere.

Ejemplo de body (MCP envelope que solicita la herramienta `fetch`):

```json
{
  "id": "req-1",
  "method": "fetch",
  "params": {
    "url": "https://example.com",
    "headless": true
  }
}
```

curl ejemplo:

```bash
curl -v -X POST http://HOST:8000/ \
  -H "Content-Type: application/json" \
  -H "X-Session-Id: ${session_id}" \
  -d '{"id":"req-1","method":"fetch","params":{"url":"https://example.com","headless":true}}'
```

d) Leer la respuesta SSE

- El cliente SSE que abriste en (a) recibirá eventos `data: ...` relacionados con `req-1`. Mantén la conexión SSE abierta para recolectar resultados o estados intermedios.

3. ¿Se puede usar un sessionId arbitrario o hay que pedirlo con GET?

- No envíes un sessionId arbitrario salvo que la implementación del servidor lo permita explícitamente. El flujo correcto y fiable es abrir la conexión SSE (GET) y leer la `sessionId` proporcionada por el servidor. Algunos servidores pueden aceptar `sessionId` generados por cliente, pero Scrapling usa `FastMCP` y típicamente crea la sesión en la conexión SSE.

4. Sobre `run_script` / ejecución de scripts

- El MCP server de Scrapling expone herramientas concretas: `get`, `bulk_get`, `fetch`, `bulk_fetch`, `stealthy_fetch`, `bulk_stealthy_fetch` (ver `Scrapling/core/ai.py`). No existe `run_script` por defecto. Para ejecutar scripts arbitrarios via MCP tienes dos opciones:
  - Añadir una herramienta personalizada al `ScraplingMCPServer` (modificar `Scrapling/core/ai.py` para `server.add_tool(...)`).
  - Ejecutar el script a través de una de las herramientas existentes (por ejemplo, hacer que `fetch` cargue una URL que dispare la lógica esperada) o implementar una fachada FastAPI que ejecute scripts locales.

5. Diagnóstico del error "Missing session ID"

- Causas comunes:
  - Hiciste directamente un POST sin abrir antes el GET SSE.
  - Abriste la SSE pero te conectaste a una ruta distinta (p. ej. SSE en `/` y POST en `/mcp`).
  - No pasaste la `sessionId` en la cabecera/query esperada por la implementación (prueba X-Session-Id y query param `sessionId`).

Comprobaciones rápidas:

```bash
# 1) Asegura que SSE responde con JSON inicial (tiene sessionId)
curl -s -N -H "Accept: text/event-stream" http://HOST:8000/ | sed -n '1,10p'

# 2) Si SSE no devuelve sessionId, mira logs del contenedor:
docker logs -f <scrapling_container>

# 3) Prueba POST con header y query param alternativos
curl -v -X POST http://HOST:8000/?sessionId=${session_id} -H "Content-Type: application/json" -d '{...}'

```

6. Ejemplo Node.js completo (handshake + POST + escucha)

```js
// scripts/mcp_client.js (node 18+)
import http from "http";
import { spawn } from "child_process";

const HOST = "HOST";
const PORT = 8000;

// 1) open SSE connection
const sseReq = http.request(
  {
    hostname: HOST,
    port: PORT,
    path: "/",
    method: "GET",
    headers: { Accept: "text/event-stream" },
  },
  (res) => {
    res.setEncoding("utf8");
    res.on("data", (chunk) => {
      process.stdout.write(chunk);
      // try to parse sessionId from first data event
    });
  },
);
sseReq.end();

// 2) after you parsed the sessionId from the SSE output, POST the job (example shown earlier)
```

7. Healthcheck / Docker

- Para healthcheck sencillo en Docker: comprobar TCP + respuesta SSE básica:

```dockerfile
HEALTHCHECK --interval=30s --timeout=5s \
  CMD curl -s -H "Accept: text/event-stream" http://127.0.0.1:8000/ || exit 1
```

8. Resumen de pasos concretos

1) Abrir GET SSE con `Accept: text/event-stream` en `/` (o `/mcp`).
2) Leer `sessionId` del primer evento `data:`.
3) Enviar POST JSON a `/` con `Content-Type: application/json` y `X-Session-Id: <sessionId>` (o `?sessionId=<sessionId>`). Body → MCP envelope con `id`, `method`, `params`.
4) Leer resultados por la conexión SSE.

Si quieres, creo un `scripts/mcp_wrapper.py` (logger DEBUG) y un `scripts/mcp_client_example.sh` en el repo para que pruebes localmente. ¿Lo agrego?
