# Propuesta de Integración: Scrapling ⇢ n8n / Portainer

## Resumen ejecutivo

Se proponen dos rutas limpias y produíbles para integrar Scrapling con n8n/Portainer evitando llamadas `docker exec` por SSH:

- Opción A (recomendado rápido): usar el servidor MCP de Scrapling en modo HTTP (ya documentado en el repo). Permite comunicación HTTP/stream con payloads JSON y mantiene proceso long-running.
- Opción B (alternativa): envolver la librería con una pequeña API HTTP (FastAPI + uvicorn) que reciba credenciales por POST y devuelva JSON.

Ambas opciones eliminan la fragilidad de ejecutar comandos remotos y facilitan el paso de JSON entre n8n y Scrapling.

## Arquitectura propuesta (alto nivel)

- n8n (workflow) → HTTP Request → Scrapling Service (contenedor)
- Scrapling Service → ejecuta spiders/stealth fetchers, mantiene sesiones Playwright y devuelve JSON.
- Opcional: volumen para `crawldir`/checkpoints para persistencia entre runs.

## Opción A — Usar MCP Server (HTTP transport) (RECOMENDADA)

Descripción: Scrapling ya soporta MCP y un "streamable HTTP" transport. Levantar el contenedor oficial con `scrapling mcp --http` expone un endpoint HTTP que acepta solicitudes MCP. n8n hace peticiones HTTP al servicio y recibe respuestas JSON/stream.

Ejemplo mínimo de `Dockerfile` para imagen de servicio MCP (basado en Dockerfile oficial):

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir .[ai]
EXPOSE 8000
CMD ["uv", "run", "scrapling", "mcp", "--http", "--host", "0.0.0.0", "--port", "8000"]
```

docker-compose (snippet) para desplegar con Portainer / n8n:

```yaml
version: "3.8"
services:
  scrapling:
    image: tu-registry/scrapling:latest
    build: .
    ports:
      - "8000:8000"
    volumes:
      - scrapling_data:/app/crawldir
    environment:
      - PYTHONUNBUFFERED=1

volumes:
  scrapling_data:
```

Uso práctico desde n8n (HTTP Request node):

- URL: `http://<SCRAPLING_HOST>:8000/mcp` (o la ruta que el transporte HTTP del MCP exponga)
- Method: `POST` (body → MCP envelope / JSON). Si usas la configuración de Streamable HTTP, puedes enviar el job y esperar respuesta.

Ejemplo de payload JSON (n8n HTTP Request body) — POST raw JSON:

```json
{
  "method": "run_spider",
  "params": {
    "spider": "idempiere_productinfo",
    "args": {
      "username": "IDEMPIERE_USER",
      "password": "IDEMPIERE_PASSWORD",
      "filters": { "category": "Electrónica" }
    }
  }
}
```

Ejemplo de mapping en n8n: usar el output JSON del nodo HTTP Request y mapear `body.result` al siguiente nodo.

## Opción B — FastAPI wrapper (más control, endpoints amigables)

Descripción: Crear un microservicio FastAPI que importe Scrapling (API Python) y ofrezca endpoints REST sencillos. Útil si prefieres endpoints con auth, rate-limiting y transformaciones propias.

Ejemplo de `app.py` (esqueleto):

```py
from fastapi import FastAPI
from pydantic import BaseModel
from scrapling.spiders import Spider  # import representativo

app = FastAPI()

class IdempierePayload(BaseModel):
    username: str
    password: str
    filters: dict | None = None

@app.post('/scrape/idempiere')
async def scrape_idempiere(payload: IdempierePayload):
    # Lógica: instanciar spider, ejecutar .start()/stream() y devolver JSON
    spider = Spider('idempiere_productinfo')
    result = spider.start(username=payload.username, password=payload.password)
    return {'result': result}

```

Dockerfile para FastAPI wrapper:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . /app
RUN pip install fastapi uvicorn .
EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
```

n8n request node (ejemplo):

- URL: `http://<FASTAPI_HOST>:8080/scrape/idempiere`
- Method: `POST`
- Body (JSON):

```json
{
  "username": "mi_usuario",
  "password": "mi_pass",
  "filters": { "category": "Electrónica" }
}
```

## Tablas resumidas — Comparativa rápida

| Criterio          |            MCP (HTTP) |      FastAPI wrapper | CLI via SSH (actual) |
| ----------------- | --------------------: | -------------------: | -------------------: |
| Latencia          |                  Baja |                Media |                 Alta |
| Soporte streaming |           Sí (nativo) | Posible (WebSockets) |                   No |
| Implementación    | Baja (usar existente) |  Media (desarrollar) |                  N/A |
| Control / auth    |              Limitado |                 Alto |                 Bajo |

## Recomendaciones prácticas y variables

- Volúmenes: montar `crawldir` a volumen persistente para checkpoints.
- Variables env sugeridas:
  - `SCRAPLING_CRAWLDIR=/data/crawldir`
  - `PLAYWRIGHT_BROWSERS=chromium`
  - `IDEMPIERE_USER`, `IDEMPIERE_PASSWORD` (preferir n8n credentials manager y pasarlas en el body)

## Ejemplo de docker-compose completo (FastAPI + Portainer-aware)

```yaml
version: "3.8"
services:
  scrapling-api:
    build: ./scrapling-api
    image: scrapling-api:latest
    ports:
      - "8080:8080"
    volumes:
      - scrapling_data:/data/crawldir
    environment:
      - PLAYWRIGHT_BROWSERS=chromium

volumes:
  scrapling_data:
```

## Ejemplo de respuesta esperada (JSON)

```json
{
  "result": [
    { "product_id": "1001", "name": "Producto A", "price": "12.50" },
    { "product_id": "1002", "name": "Producto B", "price": "9.99" }
  ],
  "meta": { "items": 2, "elapsed_seconds": 4.2 }
}
```

En n8n: usar un nodo `Set` para transformar `body.result` y luego `HTTP Request` u otros nodos para insertar/guardar datos.

## Riesgos y notas operativas

- Si usas Playwright dentro de contenedor, asegúrate de instalar binarios y configurar `--no-sandbox` si es necesario.
- `uvloop`/`winloop`: instalar según SO para mejora de rendimiento (docs del repo lo recomiendan).
- `typing-extensions` debe incluirse en el `pyproject`/`requirements` de la imagen para evitar instalaciones manuales en tiempo de contenedor.

## Próximos pasos (sugeridos)

1. Probar Opción A: levantar contenedor oficial con `scrapling mcp --http` y ejecutar un job de prueba desde n8n.
2. Si necesitas endpoints REST amigables con autenticación y control, implementar Opción B (FastAPI) como fachada.
3. Añadir healthchecks y monitorización (Prometheus / logs) antes de producción.

---

Archivo generado automáticamente: `docs/integration-n8n-proposal.md`
