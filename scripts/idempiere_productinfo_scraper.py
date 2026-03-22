#!/usr/bin/env python3
"""
idempiere_productinfo_scraper.py

Automatiza la descarga de Product Info desde iDempiere usando Scrapling
StealthyFetcher + Playwright.

Reglas clave:
- Logs en stderr con formato [HH:MM:SS] [PASO] Mensaje.
- Si falla cualquier paso, toma screenshot en /tmp/error.png y termina lanzando excepción.
- Variables de entorno: IDEMPIERE_USER, IDEMPIERE_PASSWORD, IDEMPIERE_URL (hay un valor por defecto).
- La función `page_action(page, context, params)` devuelve un dict que `main()` imprimirá como JSON.
"""
import os
import sys
import json
import time
from datetime import datetime, timedelta, timezone

from scrapling.fetchers.stealth_chrome import StealthyFetcher


# Variables globales (pegadas al margen izquierdo)
IDEMPIERE_URL = os.getenv("IDEMPIERE_URL")
USER = os.getenv("IDEMPIERE_USER")
PASSWORD = os.getenv("IDEMPIERE_PASSWORD")
# Generar timestamp usando hora de Venezuela (UTC-4)
# Ajuste manual para Venezuela (UTC-4)
# Usar datetime aware en UTC y restar 4 horas para hora de Venezuela
now = datetime.now(timezone.utc) - timedelta(hours=4)
timestamp = now.strftime("%d-%m-%y_%I-%M%p").lower()  # Ejemplo: 19-03-26_10-23am

# Nueva ruta dinámica (usar /app/exports/AlmacenX10)
DOWNLOAD_DIR = "/app/exports/AlmacenX10"
# Asegurar que la carpeta exista
try:
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
except Exception:
    # Si fallara la creación, continuamos; el intento de guardado fallará y quedará registrado
    pass
# Limpieza selectiva: eliminar solo archivos .xls y .xlsx en DOWNLOAD_DIR
removed = 0
try:
    try:
        entries = os.listdir(DOWNLOAD_DIR)
    except Exception:
        entries = []
    for fname in entries:
        path = os.path.join(DOWNLOAD_DIR, fname)
        try:
            if os.path.isfile(path) and fname.lower().endswith(('.xls', '.xlsx')):
                try:
                    os.remove(path)
                    removed += 1
                except Exception:
                    # No detenerse por errores al eliminar un archivo individual
                    pass
        except Exception:
            pass
except Exception:
    pass
# Reportar limpieza (timestamped) en stderr
t = datetime.now().strftime("%H:%M:%S")
print(f"[{t}] [CLEANUP] Archivos Excel antiguos eliminados de AlmacenX10 (removed={removed})", file=sys.stderr, flush=True)
DOWNLOAD_PATH = os.path.join(DOWNLOAD_DIR, f"productos_idempiere_fecha_{timestamp}.xls")

def log(step: str, msg: str):
    t = datetime.now().strftime("%H:%M:%S")
    global LAST_STEP
    # Track last meaningful STEP for error reporting
    if step == 'STEP':
        LAST_STEP = msg
    print(f"[{t}] [{step}] {msg}", file=sys.stderr, flush=True)


def fail_and_exit(page=None, exc: Exception = None):
    """Intentar tomar screenshot y propagar la excepción."""
    try:
        # do not overwrite LAST_STEP here; log only for stderr output
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [ERROR] Falló el proceso, intentando tomar screenshot en /tmp/error.png", file=sys.stderr, flush=True)
        if page is not None:
            try:
                page.screenshot(path='/tmp/error.png', full_page=True)
                print(f"[{datetime.now().strftime('%H:%M:%S')}] [ERROR] Screenshot guardado en /tmp/error.png", file=sys.stderr, flush=True)
            except Exception as e:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] [ERROR] No se pudo tomar screenshot: {e}", file=sys.stderr, flush=True)
    except Exception:
        pass
    # Include LAST_STEP context when raising
    info = f" (last_step={LAST_STEP})" if 'LAST_STEP' in globals() and LAST_STEP else ''
    if exc is not None:
        raise RuntimeError(str(exc) + info)
    raise RuntimeError('Proceso fallido sin excepción específica' + info)


def page_action(page, context, params):
    """Acción que ejecuta el browser. Debe aceptar (page, context, params).

    Retorna un dict con status/file/duration en caso de éxito.
    """
    start = time.time()

    # Validar credenciales
    if not USER or not PASSWORD:
        fail_and_exit(page, RuntimeError('Faltan variables de entorno IDEMPIERE_USER/IDEMPIERE_PASSWORD'))

    # Asegurar que la URL global sea un string
    if not isinstance(IDEMPIERE_URL, str):
        fail_and_exit(page, RuntimeError('IDEMPIERE_URL no es un string válido'))

    try:
        log('STEP', f'Navegando a la URL de iDempiere: {IDEMPIERE_URL}')
        page.goto(IDEMPIERE_URL, timeout=120000)

        # Login: llenar user/pass y esperar "Log out" o "Cerrar sesión"
        log('STEP', 'Buscando campos de usuario y contraseña')
        selectors_user = ["input[name='user']", "input[name='username']", "input[id='login']", "input[type='text']"]
        selectors_pass = ["input[name='password']", "input[type='password']"]

        found_user = None
        for s in selectors_user:
            el = page.query_selector(s)
            if el:
                found_user = s
                break
        if not found_user:
            fail_and_exit(page, RuntimeError('No se encontró input de usuario'))

        found_pass = None
        for s in selectors_pass:
            el = page.query_selector(s)
            if el:
                found_pass = s
                break
        if not found_pass:
            fail_and_exit(page, RuntimeError('No se encontró input de contraseña'))

        log('STEP', f'Rellenando credenciales (user field: {found_user}, pass field: {found_pass})')
        page.fill(found_user, USER)
        page.fill(found_pass, PASSWORD)

        # Enviar login
        submit_selectors = ["button[type='submit']", "button:has-text('Login')", "input[type='submit']"]
        submitted = False
        for s in submit_selectors:
            try:
                btn = page.query_selector(s)
                if btn:
                    btn.click()
                    submitted = True
                    break
            except Exception:
                continue
        if not submitted:
            page.press(found_pass, 'Enter')

        log('STEP', 'Esperando indicador de sesión activa ("Log out" o "Cerrar sesión")')
        try:
            page.wait_for_selector('text=Log out', timeout=30000)
        except Exception:
            try:
                page.wait_for_selector('text=Cerrar sesión', timeout=30000)
            except Exception:
                fail_and_exit(page, RuntimeError('Login falló: no apareció "Log out" ni "Cerrar sesión"'))

        log('STEP', 'Login exitoso')
        # Captura intermedia y vigilancia de indicadores de carga
        try:
            page.screenshot(path='/tmp/after_login.png', full_page=True)
            log('STEP', 'Screenshot after login guardado en /tmp/after_login.png')
        except Exception as e:
            log('STEP', f'No se pudo guardar after_login screenshot: {e}')

        # Helper: esperar que no queden indicadores de carga (Processing / z-loading-indicator)
        def wait_until_no_loading(timeout_ms=300000):
            end = time.time() + timeout_ms / 1000.0
            next_log = time.time() + 30
            while time.time() < end:
                busy = False
                try:
                    busy = page.locator("span.busy-dialog-label:has-text('Processing')").count() > 0 and page.locator("span.busy-dialog-label:has-text('Processing')").is_visible()
                except Exception:
                    try:
                        busy = bool(page.query_selector("span.busy-dialog-label:has-text('Processing')"))
                    except Exception:
                        busy = False
                try:
                    if page.locator('div.z-loading-indicator').count() > 0 and page.locator('div.z-loading-indicator').is_visible():
                        busy = True
                except Exception:
                    try:
                        if page.query_selector('div.z-loading-indicator'):
                            busy = True
                    except Exception:
                        pass

                # También comprobar si existe la máscara modal que bloquea la UI
                try:
                    if page.locator('.z-modal-mask').count() > 0 and page.locator('.z-modal-mask').first.is_visible():
                        busy = True
                except Exception:
                    try:
                        if page.query_selector('.z-modal-mask'):
                            busy = True
                    except Exception:
                        pass

                if not busy:
                    # Anti-parpadeo: esperar 3s y verificar de nuevo que no reaparezca
                    log('STEP', 'No se detectó processing/mask; verificando anti-parpadeo (3s)...')
                    try:
                        page.wait_for_timeout(3000)
                    except Exception:
                        time.sleep(3)
                    # Re-evaluar
                    busy_post = False
                    try:
                        busy_post = page.locator("span.busy-dialog-label:has-text('Processing')").count() > 0 and page.locator("span.busy-dialog-label:has-text('Processing')").is_visible()
                    except Exception:
                        try:
                            busy_post = bool(page.query_selector("span.busy-dialog-label:has-text('Processing')"))
                        except Exception:
                            busy_post = False
                    try:
                        if page.locator('div.z-loading-indicator').count() > 0 and page.locator('div.z-loading-indicator').is_visible():
                            busy_post = True
                    except Exception:
                        try:
                            if page.query_selector('div.z-loading-indicator'):
                                busy_post = True
                        except Exception:
                            pass
                    try:
                        if page.locator('.z-modal-mask').count() > 0 and page.locator('.z-modal-mask').first.is_visible():
                            busy_post = True
                    except Exception:
                        try:
                            if page.query_selector('.z-modal-mask'):
                                busy_post = True
                        except Exception:
                            pass

                    if not busy_post:
                        log('STEP', 'Anti-parpadeo OK: processing/mask ausente de forma estable')
                        return True
                    # Si reapareció, continuar esperando
                    log('STEP', 'El indicador reapareció durante la verificación anti-parpadeo; continúo esperando')
                if time.time() >= next_log:
                    log('STEP', 'Sigo esperando a que el servidor termine de procesar...')
                    next_log += 30
                time.sleep(0.5)
            return False

        # Esperar que cualquier indicador posterior al login desaparezca antes de tocar el menú
        ok = wait_until_no_loading(timeout_ms=300000)
        if not ok:
            fail_and_exit(page, RuntimeError('Indicadores de carga no se eliminaron tras el login dentro del timeout'))

        # Navegación a Product Info usando selectores más robustos
        log('STEP', 'Buscando enlace o botón "Product Info" / "Información de Producto"')
        try:
            english_selector = ".z-treecell-content:has-text('Product Info'), .z-menu-item-content:has-text('Product Info'), .z-navitem-content:has-text('Product Info')"
            spanish_selector = ".z-treecell-content:has-text('Información de Producto'), .z-menu-item-content:has-text('Información de Producto'), .z-navitem-content:has-text('Información de Producto')"

            # Logs de diagnóstico: listar textos visibles en elementos de menu/tree
            try:
                visible_texts = page.locator('.z-treecell-content, .z-menu-item-content, .z-navitem-content').all_text_contents()
            except Exception:
                visible_texts = []
            log('STEP', f'Textos de menú detectados (muestra): {visible_texts[:20]}')

            # Espera extendida para que el menú/árbol renderice (hasta 8 minutos)
            menu_end = time.time() + 480000 / 1000.0
            next_menu_log = time.time() + 30
            found = False
            while time.time() < menu_end:
                try:
                    if page.locator(english_selector).count() > 0:
                        page.locator(english_selector).first.click(force=True)
                        found = True
                        break
                    if page.locator(spanish_selector).count() > 0:
                        page.locator(spanish_selector).first.click(force=True)
                        found = True
                        break
                    # fallback text selectors
                    if page.query_selector("text=Product Info"):
                        page.click("text=Product Info", force=True)
                        found = True
                        break
                    if page.query_selector("text=Información de Producto"):
                        page.click("text=Información de Producto", force=True)
                        found = True
                        break
                except Exception:
                    pass
                if time.time() >= next_menu_log:
                    log('STEP', 'Sigo esperando a que el servidor termine de procesar...')
                    next_menu_log += 30
                time.sleep(0.5)

            if not found:
                log('STEP', f'No se encontró Product Info; botones visibles: {visible_texts[:20]}')
                fail_and_exit(page, RuntimeError('No se encontró "Product Info" ni "Información de Producto" tras espera extendida'))
        except Exception as e:
            fail_and_exit(page, e)

        # Señal de pestaña: esperar que el botón de export esté adjunto en el DOM
        try:
            page.wait_for_selector('.btn-export', state='attached', timeout=45000)
            log('STEP', 'Pestaña detectada via botón exportar')
        except Exception:
            fail_and_exit(page, RuntimeError('Timeout esperando a que la pestaña de Product Info cargue (btn-export no presente)'))

        # Acción simple: presionar Enter en el primer input visible o en la página
        log('STEP', 'Presionando Enter en el primer input visible o en la página para iniciar búsqueda')
        try:
            try:
                # Preferir el primer input visible dentro de la ventana ZK activa si existe
                zk_window = page.locator('.z-window-highlighted, .z-window-embedded').first
                first_input = zk_window.locator('input.z-textbox:visible, input.z-bandbox-input:visible').first
                if first_input.count() and first_input.is_visible():
                    first_input.press('Enter')
                else:
                    page.keyboard.press('Enter')
            except Exception:
                # Fallback: intentar presionar Enter en el primer input visible de la página
                try:
                    first_input = page.locator('input.z-textbox:visible, input.z-bandbox-input:visible').first
                    if first_input.count() and first_input.is_visible():
                        first_input.press('Enter')
                    else:
                        page.keyboard.press('Enter')
                except Exception:
                    page.keyboard.press('Enter')
        except Exception as e:
            fail_and_exit(page, e)

        # Espera activa para 'Processing' y máscara modal (con validación anti-parpadeo)
        log('STEP', "Esperando indicador 'Processing' o máscara modal (aparezca hasta 30s, luego asegurando ocultamiento estable hasta 300s)...")
        try:
            try:
                # Esperar hasta 30s a que alguno aparezca (si aparece)
                page.wait_for_selector(".z-modal-mask, span.busy-dialog-label:has-text('Processing')", state='visible', timeout=30000)
                log('STEP', "Indicador modal/Processing apareció, esperando que desaparezca de forma estable")
                ok = wait_until_no_loading(timeout_ms=300000)
                if not ok:
                    fail_and_exit(page, RuntimeError("Timeout esperando que 'Processing' y la máscara modal desaparezcan de forma estable"))
                log('STEP', "El indicador modal/Processing ha desaparecido de forma estable, procediendo a verificar botón de exportar")
            except Exception:
                # Si no apareció en 30s, aún debemos asegurar que no esté presente antes de continuar
                log('STEP', "Indicador modal/Processing no apareció en 30s; asegurando ocultamiento estable (esperar hasta 300s)")
                ok = wait_until_no_loading(timeout_ms=300000)
                if not ok:
                    fail_and_exit(page, RuntimeError("Timeout asegurando que 'Processing' y la máscara modal no estén presentes"))
                log('STEP', "Confirmado: modal/Processing no presente de forma estable, procediendo a verificar botón de exportar")
        except Exception:
            fail_and_exit(page, RuntimeError("Timeout esperando que 'Processing' desaparezca"))

        # Verificar botón de export: visible y no-disabled
        log('STEP', 'Esperando que .btn-export esté visible y habilitado (max 60s)')
        try:
            try:
                page.wait_for_selector('.btn-export:not([disabled])', state='visible', timeout=60000)
            except Exception:
                # fallback: comprobar ausencia de clase disabled
                # tomar screenshot diagnóstica
                try:
                    page.screenshot(path='/tmp/error_export_disabled.png', full_page=True)
                    log('STEP', 'Screenshot error_export_disabled.png guardado')
                except Exception:
                    pass
                fail_and_exit(page, RuntimeError('Botón de exportación no visible/habilitado tras 60s'))

            export_btn = page.locator('.btn-export').first
            log('STEP', '.btn-export visible y habilitado, listo para click')
        except Exception as e:
            fail_and_exit(page, e)

        # Bucle resiliente de export: hasta 30 intentos
        try:
            attempt = 0
            dialog_found = None
            while attempt < 30:
                attempt += 1
                log('STEP', f'Intento de export #{attempt}: verificando precondiciones')

                # 1) botón visible y no disabled
                try:
                    btn_ok = page.locator('.btn-export:not([disabled])').count() > 0 and page.locator('.btn-export:not([disabled])').first.is_visible()
                except Exception:
                    btn_ok = bool(page.query_selector('.btn-export:not([disabled])'))

                # 2) no hay indicadores de carga
                busy = False
                try:
                    busy = (page.locator("span.busy-dialog-label:has-text('Processing')").count() > 0 and page.locator("span.busy-dialog-label:has-text('Processing')").is_visible())
                except Exception:
                    busy = bool(page.query_selector("span.busy-dialog-label:has-text('Processing')")) if page is not None else False
                try:
                    if page.locator('div.z-loading-indicator').count() > 0 and page.locator('div.z-loading-indicator').is_visible():
                        busy = True
                except Exception:
                    if page.query_selector('div.z-loading-indicator'):
                        busy = True

                # 3) al menos una fila de datos
                try:
                    rows_ok = page.locator('.z-listitem, .z-row').count() > 0
                except Exception:
                    rows_ok = bool(page.query_selector('.z-listitem') or page.query_selector('.z-row'))

                # Si el servidor sigue ocupado, loguear mensaje informativo para diagnóstico
                if busy:
                    log('STEP', 'El servidor de San Simón sigue procesando datos pesados (busy) — esperando antes de reintentar')

                if (not busy) and btn_ok and rows_ok:
                    log('STEP', 'Precondiciones OK — intentando click en .btn-export')
                    try:
                        page.locator('.btn-export').first.click(force=True)
                    except Exception:
                        try:
                            page.query_selector('.btn-export').click()
                        except Exception:
                            log('STEP', 'Click en export falló en este intento')
                    # Esperar corto por el diálogo
                    try:
                        dialog_found = page.wait_for_selector(".z-button:has-text('Save to File'), .z-button:has-text('OK')", state='visible', timeout=5000)
                        log('STEP', 'Dialogo de export encontrado')
                        break
                    except Exception:
                        log('STEP', 'Reintentando clic en exportar... el diálogo aún no aparece')
                        try:
                            page.wait_for_timeout(8000)
                        except Exception:
                            time.sleep(8)
                        continue
                else:
                    log('STEP', 'Precondiciones no satisfechas para export (busy/button/rows) — reintentando')
                    try:
                        page.wait_for_timeout(8000)
                    except Exception:
                        time.sleep(8)
                    continue

            if not dialog_found:
                try:
                    page.screenshot(path='/tmp/debug_export_loop_failed.png', full_page=True)
                except Exception:
                    pass
                fail_and_exit(page, RuntimeError('No se pudo abrir diálogo de export tras 30 intentos'))

            # Cuando el diálogo fue detectado, realizar la descarga usando event-driven download
            try:
                with page.expect_download(timeout=90000) as download_info:
                    page.locator(".z-button:has-text('Save to File'), .z-button:has-text('OK')").first.click()
                download = download_info.value
                download.save_as(DOWNLOAD_PATH)
                log('STEP', f'Descarga completada y guardada en {DOWNLOAD_PATH}')
                # Imprimir ruta de resultado para que n8n la capture fácilmente
                try:
                    print(f"RESULT_FILE: {DOWNLOAD_PATH}", flush=True)
                except Exception:
                    pass
            except Exception as e:
                fail_and_exit(page, e)
        except Exception as e:
            fail_and_exit(page, e)

        duration = int(time.time() - start)
        result = {'status': 'ok', 'file': DOWNLOAD_PATH, 'duration': f"{duration}s"}
        return result

    except Exception as e:
        fail_and_exit(page, e)


def main():
    # Configuración global para evitar advertencias de deprecated
    log('MAIN', f'Iniciando fetch en URL: {IDEMPIERE_URL}')
    try:
        StealthyFetcher.configure(headless=True)
    except Exception:
        # Si configure no existe, continuar
        pass

    try:
        # Adapter: some versions of StealthyFetcher call page_action(page)
        # while newer versions call page_action(page, context, params).
        # Provide a wrapper that accepts any signature and forwards to the
        # canonical `page_action(page, context, params)` so we keep a single
        # definition of `page_action` as required.
        def _page_action_adapter(*args, **kwargs):
            if len(args) == 1 and not kwargs:
                return page_action(args[0], None, None)
            return page_action(*args, **kwargs)

        resp = StealthyFetcher.fetch(IDEMPIERE_URL, page_action=_page_action_adapter)
    except Exception as e:
        log('MAIN', f'Excepción durante fetch: {e}')
        out = {'status': 'error', 'error': str(e)}
        if 'LAST_STEP' in globals() and LAST_STEP:
            out['last_step'] = LAST_STEP
        print(json.dumps(out))
        sys.exit(1)
    # El fetcher no propaga el valor retornado por page_action; asumimos que
    # la descarga fue guardada en DOWNLOAD_PATH por page_action.
    try:
        duration = None
        try:
            duration = int(time.time() - resp.meta.get('start_time')) if getattr(resp, 'meta', None) and resp.meta.get('start_time') else None
        except Exception:
            duration = None

        # Si page_action guardó el archivo, úsalo; si no existe, informar error
        if os.path.exists(DOWNLOAD_PATH):
            total_duration = int(time.time() - os.path.getmtime(DOWNLOAD_PATH)) if duration is None else duration
            out = {'status': 'ok', 'file': DOWNLOAD_PATH, 'duration': f"{total_duration}s"}
            print(json.dumps(out))
            return
        else:
            # Si no se encuentra el archivo, devolver información útil desde la respuesta
            out = {
                'status': 'error',
                'error': 'Descarga no creada en expected path',
                'response_url': getattr(resp, 'url', None)
            }
            if 'LAST_STEP' in globals() and LAST_STEP:
                out['last_step'] = LAST_STEP
            print(json.dumps(out))
            sys.exit(1)
    except Exception as e:
        log('MAIN', f'Error final construyendo JSON: {e}')
        out = {'status': 'error', 'error': str(e)}
        print(json.dumps(out))
        sys.exit(1)


if __name__ == '__main__':
    main()
