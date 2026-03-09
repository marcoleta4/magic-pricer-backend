# MTG Shopify Auto-Pricer

Este es un script en Python que revisa tu tienda de Shopify y actualiza automáticamente los precios de tus cartas de Magic: The Gathering (tanto Foil como Non-Foil) basándose en los datos más recientes de Scryfall.

## Estructura
- `update_prices.py`: El script principal.
- `requirements.txt`: Dependencias de Python (requests, python-dotenv).
- `.env.example`: Plantilla para las variables de entorno.
- `.github/workflows/update_prices.yml`: Configuración para ejecutar el script gratis automáticamente todos los días en GitHub.

## Cómo probar localmente antes de usar la nube

1. Renombra `.env.example` a `.env` y añade tu URL de la tienda, el "Client ID" (Clave API) y el "Client Secret" (Clave secreta) de tu aplicación de Shopify.
2. Abre una terminal en esta carpeta.
3. Instala las dependencias: `pip install -r requirements.txt`
4. Ejecuta el script: `python update_prices.py`

## Cómo publicarlo y automatizarlo GRATIS (Recomendado: GitHub)

GitHub Actions te da horas gratuitas más que suficientes para ejecutar este script una vez al día.

1. Crea un repositorio privado en tu cuenta de GitHub y sube todos los archivos de esta carpeta (`shopify-pricer`).
2. Ve a los **Settings** (Configuración) de ese repositorio en GitHub -> **Secrets and variables** -> **Actions**.
3. Añade tres "New repository secrets":
   - **Name:** `SHOPIFY_STORE_URL` | **Secret:** (tu URL, ej. `mitienda.myshopify.com`)
   - **Name:** `SHOPIFY_CLIENT_ID` | **Secret:** (tu Clave API de Shopify)
   - **Name:** `SHOPIFY_CLIENT_SECRET` | **Secret:** (tu Clave secreta de Shopify)
4. ¡Y listo! El archivo `.github/workflows/update_prices.yml` está configurado para ejecutarse todos los días a las 00:00 UTC automáticamente. También puedes ir a la pestaña "Actions" y ejecutarlo manualmente haciendo clic en "Run workflow".

## Opciones alternativas (Render)

Si aún prefieres usar Render:
- Si creas un "Background Worker" en Render, necesitas modificar el script `update_prices.py` para que tenga un bucle infinito con un límite de tiempo (ej. `time.sleep(86400)` para que espere 24 horas entre ejecuciones), o usar una librería como `schedule`.
- *Nota: Los Background Workers de Render no son gratuitos. La forma de hacerlo gratis en Render es con un Web Service que una página como `cron-job.org` visite diariamente.* Por lo tanto, GitHub Actions es mucho más fácil y totalmente gratuito.
