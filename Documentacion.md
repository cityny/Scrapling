## 📋 Potencial de tu nuevo Fork (Pre-Documentación)

Este sistema que construimos hoy tiene un potencial enorme:

Escalabilidad: Puedes tener 10 n8n diferentes consultando al mismo Scrapling.

Flexibilidad: Hoy scrapeamos iDempiere, mañana podemos usar el mismo nodo para calcular comisiones de la BVC enviando solo el código.

Mantenimiento Zero: Ya no tocas el VPS; el 100% de tu lógica vive en n8n o en GitHub.

## 🛠️ TROUBLESHOOTING: Truncamiento de Base64 y Errores de Sintaxis en n8n -> API Python

**Fecha:** Marzo 2026
**Stack Usado:** n8n, Docker (Portainer), VPS, Python (FastAPI), Scrapling (Playwright).
**Objetivo Logrado:** Envío de scripts dinámicos desde n8n a un contenedor API de Python y recuperación de archivos binarios pesados (imágenes/capturas) sin pérdida de datos.

### 🔴 Síntomas Reportados

1. **Truncamiento:** Al intentar devolver una imagen Base64 por el `stdout` de la API, el string llegaba cortado (`\n...[truncated]`) a n8n.
2. **Error de Aislamiento:** Al cambiar a guardar el archivo físico en `/tmp`, n8n arrojaba `No file(s) found`.
3. **SyntaxError (Python):** El endpoint `/run-python` devolvía `SyntaxError: invalid syntax` en la línea 1.
4. **Silencio de API:** La API devolvía `exit_code: 0` pero el `stdout` venía totalmente vacío.

### 🔍 Causas Raíz (Diagnóstico Técnico)

- **Causa 1 (Truncamiento):** Los búferes de `stdout` en subprocesos de FastAPI (vía `asyncio`) tienen límites de tamaño. Retornar Base64 masivos satura la tubería.
- **Causa 2 (Aislamiento):** En Docker, el contenedor de la API y el contenedor de n8n tienen sistemas de archivos independientes. Lo que la API guarda en su disco, n8n no lo puede ver.
- **Causa 3 (SyntaxError):** Al enviar el script vía JSON desde n8n, el motor elimina/escapa mal los saltos de línea (`\n`). El script llega a Python como una sola línea, colapsando los `import`.
- **Causa 4 (Silencio):** El subproceso de Python no estaba configurado en modo `Unbuffered` (`-u`), por lo que retenía los `print()` en memoria.

### ✅ Solución Arquitectónica y Configuraciones Clave

#### 1. Puente de Datos (Volúmenes Docker)

Para archivos pesados, **nunca** pasar por HTTP/Base64. En Portainer (`docker-compose.yml`), mapear una carpeta común del host a ambos contenedores:

- **Host (VPS):** `/home/debian/Downloads`
- **Contenedor n8n:** `/home/node/downloads`
- **Contenedor API:** `/app/downloads`

#### 2. Blindaje de Sintaxis en n8n (Payload Seguro)

Para sobrevivir a la serialización JSON de n8n y evitar que el código colapse en una sola línea:

- Usar **puntos y coma (`;`)** al final de los imports y líneas críticas.
- Usar estrictamente **comillas simples (`'`)** dentro del script de Python para evitar que rompan la estructura `"code": "..."` del JSON principal.

#### 3. Optimización del Fork (FastAPI)

Para garantizar que los logs viajen en tiempo real:

- Modificar la ejecución del subproceso en `main.py` añadiendo el flag `-u`:
  `asyncio.create_subprocess_exec(sys.executable, "-u", tmp_path, ...)`

### 💻 Plantilla de Script Base (Seguro para n8n)

```python
import sys; import os; import time; from scrapling.fetchers.stealth_chrome import StealthyFetcher

# Usar la ruta mapeada en el volumen compartido
PATH_FINAL = '/app/downloads/snapshot.png'

def mi_accion(page, *args, **kwargs):
    os.makedirs(os.path.dirname(PATH_FINAL), exist_ok=True);
    page.set_viewport_size({'width': 1280, 'height': 1200});
    page.goto('[https://url-objetivo.com](https://url-objetivo.com)', wait_until='networkidle');
    # Lógica de espera y captura...
    elemento = page.query_selector('.elemento');
    if elemento:
        elemento.screenshot(path=PATH_FINAL);
        return 'OK';
    return 'ERROR';

try:
    StealthyFetcher.fetch('[https://url-objetivo.com](https://url-objetivo.com)', page_action=mi_accion);
except Exception as e:
    print(f'ERROR: {str(e)}');
```

# 🛠️ Documentación de API: Scrapling Fork (n8n Optimized)

Esta tabla resume los 4 endpoints principales disponibles en el contenedor de Scrapling para su uso desde nodos **HTTP Request** en n8n.

### 📋 Tabla de Endpoints

| Endpoint      | Método | Propósito                                                         | Payload Clave                   | Uso Principal                                                    |
| :------------ | :----: | :---------------------------------------------------------------- | :------------------------------ | :--------------------------------------------------------------- |
| `/scrape`     | `POST` | Scrapeo con lógica de navegador (Playwright).                     | `url`, `stealth`, `page_action` | Capturas de pantalla, manipulación de DOM y extracción compleja. |
| `/run-python` | `POST` | Ejecución directa de scripts Python en el VPS.                    | `code`                          | Tareas de sistema, gestión de archivos PNG y lógica de backend.  |
| `/run-async`  | `POST` | Ejecución de scripts Python asíncronos (No bloqueantes).          | `code`, `env`, `timeout`        | Procesos largos o con esperas (`time.sleep`) sin colgar la API.  |
| `/check`      | `GET`  | Comprueba el estado y logs de una tarea lanzada por `/run-async`. | `task_id` (ruta)                | Consultas de estado, `stdout`/`stderr` parciales (cap 50000).    |
| `/healthz`    | `GET`  | Verificación de estado del contenedor (Liveness).                 | N/A                             | Monitoreo automático y alertas de "Server Down".                 |

---

### 🚀 Detalles de Implementación (n8n)

#### 1. Endpoint: `/scrape`

Permite inyectar código JavaScript directamente en el navegador (`page_action`). Ideal para remover elementos molestos (`remove()`) antes de una captura.

- **Nota Técnica:** Devuelve un buffer que puede convertirse a Base64 para ser procesado por n8n.

#### 2. Endpoint: `/run-python`

El motor principal para automatización de archivos.

- **Ejemplo de uso:** Verificar si un snapshot existe en `/tmp` o `/app/downloads` antes de enviarlo por Telegram.

#### 3. Endpoint: `/run-async`

Versión optimizada de ejecución. Permite definir variables de entorno (`env`) personalizadas para el script y un tiempo límite de ejecución independiente del nodo HTTP.

#### 4. Endpoint: `/healthz`

Endpoint de diagnóstico. Si devuelve un status `200 OK`, el motor de Python y el navegador están listos para recibir peticiones.

#### 5. Endpoint: `/check`

Consulta el estado y logs parciales de una tarea iniciada con `/run-async`.

- Ruta: `GET /check/{task_id}` (recibe `task_id` en la ruta).
- Respuesta: JSON con `status` (p. ej. `running`, `finished`, `error`, `not_found`), `exit_code`, `stdout` y `stderr`.
- Notas: `stdout` y `stderr` se devuelven como texto parcial (recorte a los últimos 50000 caracteres).

Recomendado en n8n: usar un nodo `HTTP Request` (GET) apuntando a `http://<scrapling-host>/check/{{ $json["task_id"] }}` y reintentar/poll hasta que `status` deje de ser `running`.

Ejemplo de respuesta:

```json
{
  "status": "running",
  "exit_code": null,
  "stdout": "Últimos 50000 caracteres de stdout...",
  "stderr": ""
}
```

---

> **⚠️ Configuración Recomendada en n8n:**
>
> - **Timeout:** Se recomienda subir el timeout de los nodos HTTP a `120000` (120s) para procesos que involucren renderizado de gráficos pesados.
> - **Response:** Configurar siempre en "Full Response" para auditar `stdout` y `stderr` en caso de errores de Python.

Proyecto: BCV Scraper (Tasas del Sistema Bancario)
🎯 Objetivo
Extracción automatizada de los indicadores de compra y venta de divisas por institución financiera publicados por el Banco Central de Venezuela (BCV).

🛠️ Stack Técnico
Orquestación: n8n.

Lenguaje: Python (vía API /run-python).

Librería de Scraping: Scrapling (Fork avanzado de StealthyFetcher).

Entorno: VPS con Debian/Docker.

🔍 Lo que hemos probado y los resultados
❌ Lo que NO funciona (Lecciones aprendidas)
Selectores por adivinación: Intentar usar clases estándar de Drupal (.views-row) sin antes mapear el DOM. El BCV usa identificadores dinámicos o clases muy específicas.

Tratamiento de Objetos Selector: Intentar aplicar métodos de cadena (.strip(), .replace()) directamente sobre el resultado de page.css().

Error: 'Selector' object has no attribute 'strip'.

Causa: El motor devuelve un objeto tipo puntero, no el texto.

Llamadas masivas de métodos: El uso de .get_all() falló en ciertas instancias del fork; se determinó que es más seguro iterar y usar .get() por cada elemento.

✅ Lo que SÍ funciona (La solución técnica)
Bypass SSL/Anti-Bot: El uso de StealthyFetcher.fetch(url, verify=False) es obligatorio para evitar bloqueos por el handshake de seguridad del BCV.

Mapeo por Clases de Campo: Usar selectores basados en las clases semánticas de Drupal:

Banco: .views-field-views-conditional

Compra: .views-field-field-tasa-compra

Venta: .views-field-field-tasa-venta

Conversión de Tipos: Reemplazar , por . antes de convertir a float para asegurar que n8n procese los datos como números y no como texto.

🏗️ Arquitectura del Código Final
from scrapling import StealthyFetcher
import json

# Conexión con bypass de seguridad

page = StealthyFetcher.fetch('https://www.bcv.org.ve/tasas-informativas-sistema-bancario', verify=False)

# Localización de filas en la tabla principal

filas = page.css('.view-tasas-sistema-bancario-full tbody tr')

resultados = []
for fila in filas: # IMPORTANTE: .get() es necesario para extraer el String del Selector
fecha = fila.css('.views-field-field-fecha-del-indicador span::text').get(default='').strip()
banco = fila.css('.views-field-views-conditional::text').get(default='').strip()
compra = fila.css('.views-field-field-tasa-compra::text').get(default='').strip()
venta = fila.css('.views-field-field-tasa-venta::text').get(default='').strip()

    if banco:
        resultados.append({
            "fecha": fecha,
            "banco": banco,
            "compra": float(compra.replace(',', '.')),
            "venta": float(venta.replace(',', '.'))
        })

print(json.dumps(resultados))
