# Bitácora de Migración: Automatización iDempiere

**Fecha:** 2026-03-17

## Resumen rápido

Documento actualizado con logros, comandos útiles y la arquitectura actual (VPS → n8n → Scrapling). Contiene las rutas y el comando recomendado para ejecutar el scraper desde n8n vía SSH o `docker exec` en el host.

## Estado y logros

| Ítem                                                |         Estado | Detalle                                                                                 |
| --------------------------------------------------- | -------------: | --------------------------------------------------------------------------------------- |
| Contenedor `pyd4vinci/scrapling` desplegado         |  ✅ Completado | Imagen ejecutable en Docker, conectada a la red `proxy`.                                |
| Montaje de scripts host → contenedor                |  ✅ Completado | `/home/debian/n8n-produccion/scripts` → `/app/scripts` (modo `ro`).                     |
| `idempiere_scraper.py` creado y validado localmente |  ✅ Completado | Script parcheado que devuelve JSON diagnóstico y genera screenshot en `/tmp`.           |
| Diagnóstico de dependencias (curl-cffi, playwright) |     ✅ Parcial | Se identificaron dependencias faltantes; se instaló `scrapling` editable temporalmente. |
| Comando final para n8n (SSH)                        | ✅ Recomendado | Comando único y seguro con sustitución de credenciales.                                 |

## Arquitectura y flujo (actual)

| Origen              | Medio                  | Destino                   | Descripción                                                                                         |
| ------------------- | ---------------------- | ------------------------- | --------------------------------------------------------------------------------------------------- |
| VPS (host Docker)   | Docker network `proxy` | Contenedor `scrapling`    | `scrapling` corre en contenedor separado; scripts montados desde host.                              |
| n8n (Editor/Worker) | SSH (recomendado)      | Docker host               | n8n ejecuta `docker exec`/`docker run` en el host vía nodo SSH (evita montar docker socket en n8n). |
| n8n                 | Workflow               | `scrapling` stdout (JSON) | n8n captura stdout, parsea JSON y actúa según `login_detected`.                                     |

## Directorios clave

| Ruta en host                          | Punto en contenedor | Uso                                                                                                            |
| ------------------------------------- | ------------------- | -------------------------------------------------------------------------------------------------------------- |
| `/home/debian/n8n-produccion/scripts` | `/app/scripts`      | Ubicación de `idempiere_scraper.py` (montada `:ro`).                                                           |
| `/tmp` (contenedor)                   | `/tmp`              | Screenshot y archivos de diagnostico: `/tmp/idempiere_last_screenshot.png`, `/tmp/idempiere_last_action.json`. |

## Comandos útiles (resumen)

| Acción                                    | Comando                                                                                                                                                | Nota                                                    |
| ----------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------- |
| Ejecutar scraper (host, con PYTHONPATH)   | `docker run --rm -v /home/debian/n8n-produccion/scripts:/app/scripts -e PYTHONPATH=/app pyd4vinci/scrapling python3 /app/scripts/idempiere_scraper.py` | Útil para pruebas rápidas sin sobrescribir ENTRYPOINT.  |
| Ejecutar scraper en contenedor ya running | `docker exec scrapling sh -c 'IDEMPIERE_USER="USUARIO" IDEMPIERE_PASSWORD="PASSWORD" uv run python3 /app/scripts/idempiere_scraper.py'`                | Recomendada para n8n vía SSH (ver plantilla más abajo). |
| Instalar dependencias Python temporales   | `docker run --rm --entrypoint /bin/sh pyd4vinci/scrapling -c "python3 -m pip install -e /app curl-cffi playwright"`                                    | Instala `curl-cffi` y `playwright` (si faltan).         |
| Instalar navegadores Playwright           | `docker run --rm --entrypoint /bin/sh pyd4vinci/scrapling -c "python3 -m playwright install --with-deps"`                                              | Requiere herramientas OS; revisar logs en fallos.       |

### Plantilla para nodo SSH en n8n (una línea)

Usar esta línea dentro del nodo SSH de n8n (sin `-it`, con credenciales del nodo):

```bash
docker exec scrapling sh -c "IDEMPIERE_USER='{{$credentials.IDEMPIERE.user}}' IDEMPIERE_PASSWORD='{{$credentials.IDEMPIERE.password}}' uv run python3 /app/scripts/idempiere_scraper.py"
```

- Configure el timeout del nodo SSH a 60–120s.
- Capture `stdout` y pásalo a un nodo Function para `JSON.parse()`.

## Flujo recomendado paso a paso

1. En el host, asegúrate de que `/home/debian/n8n-produccion/scripts/idempiere_scraper.py` exista y sea la versión validada.
2. En n8n, crea credencial `IDEMPIERE` (user/password) y añade un nodo SSH que ejecute la plantilla anterior.
3. Añade un nodo Function que haga `const data = JSON.parse(items[0].json.stdout)` y valide `data.login_detected`.
4. Si `login_detected:true`, realizar acciones (notificación, guardar registro, copiar screenshot fuera del contenedor).

## Copiar screenshot fuera del contenedor (opcional)

Ejemplo para copiar la captura al host:

```bash
docker cp scrapling:/tmp/idempiere_last_screenshot.png /home/debian/n8n-produccion/scripts/idempiere_last_screenshot.png
```

## Notas de dependencias y solución de errores comunes

- Si el script falla con `ModuleNotFoundError: No module named 'curl_cffi'` o `No module named 'playwright'`, instalar dentro del contenedor las dependencias faltantes (ver comandos arriba).
- Respeta el `ENTRYPOINT` de la imagen (`uv run scrapling`). Para comandos arbitrarios prefija con `sh -c` o usa `docker exec` en contenedores ya running.
- Evitar montar el socket Docker dentro de n8n por seguridad; prefiera ejecución via SSH en el host.

## Salida JSON de ejemplo (resultado de prueba)

```json
[
  {
    "status": 200,
    "url": "https://<IDEMPIERE_HOST>/webui/",
    "cookies_count": 0,
    "cookie_names": [],
    "login_detected": true,
    "matched_selector": [
      "input[type=text]",
      "input[type=password]",
      "button:has-text(Ingresar)"
    ],
    "screenshot": "/tmp/idempiere_last_screenshot.png",
    "snippet": "<!DOCTYPE html><html><head>\\n<title>ERP iDempiere Powered By frontuari</title>\\n<meta http-equiv=\\\"X-UA-Compatible\\\" content=\\\"IE=edge\\\">\\n..."
  }
]
```

## Próximos pasos (pendientes)

- [x] ruta del script a utilizar C:\Users\MARIA\OneDrive\Documentos\CityNy Development\Scrapling Fork\Scrapling\scripts\idempiere_productinfo_scraper.py
- [ ] Integrar el workflow en n8n y validar E2E (ejecutar nodo SSH y parsear JSON).
- [ ] Añadir selectores robustos al `idempiere_scraper.py` según pruebas en entorno real.
- [ ] (Opcional) Crear una imagen derivada que incluya `curl-cffi` y Playwright para evitar instalaciones en tiempo de ejecución.

---

Actualizado: 2026-03-17 — preparado para integrarlo en n8n.
