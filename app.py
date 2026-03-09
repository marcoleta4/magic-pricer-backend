from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
import pytz
from datetime import datetime

# Importar las funciones de nuestro script de actualizacion
import update_prices

app = Flask(__name__)
# Enable CORS so the local index.html can send requests to this server
CORS(app)

@app.route('/')
def serve_index():
    return render_template('index.html')

@app.route('/api/add_metafield', methods=['POST'])
def add_metafield_to_product():
    """
    Agrega manualmente el metacampo 'scryfall_id' a un producto existente.
    Esto se usa como alternativa porque la API bloquea metacampos síncronos en categorías estrictas.
    """
    token = update_prices.get_shopify_access_token()
    if not token:
        return jsonify({"error": "No se pudo obtener el token de acceso de Shopify"}), 500

    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json"
    }

    data = request.json
    product_id = data.get('product_id')
    scryfall_id = data.get('scryfall_id')

    if not product_id or not scryfall_id:
        return jsonify({"error": "Faltan datos obligatorios (product_id o scryfall_id)"}), 400

    mf_url = f"https://{update_prices.SHOPIFY_STORE_URL}/admin/api/{update_prices.API_VERSION}/products/{product_id}/metafields.json"
    mf_payload = {
        "metafield": {
            "namespace": "custom",
            "key": "scryfall_id",
            "value": str(scryfall_id),
            "type": "single_line_text_field"
        }
    }

    try:
        mf_res = update_prices.requests.post(mf_url, headers=headers, json=mf_payload)
        mf_res.raise_for_status()
        return jsonify({"message": "Metacampo añadido exitosamente"}), 201
    except Exception as e:
        error_msg = str(e)
        if hasattr(e, 'response') and e.response is not None:
            error_msg = e.response.text
        return jsonify({"error": error_msg}), 500


def scheduled_price_update():
    print(f"--- Running Scheduled Price Update at {datetime.now()} ---")
    update_prices.main()
    print("--- Scheduled Price Update Completed ---")

# Configurar el programador (Scheduler)
scheduler = BackgroundScheduler(timezone=pytz.utc)

# Leer a que hora correr (en UTC) desde las variables de entorno, por defecto a las 06:00 UTC (3 AM CLST)
UPDATE_HOUR = int(os.environ.get("UPDATE_HOUR", 6))
UPDATE_MINUTE = int(os.environ.get("UPDATE_MINUTE", 0))

scheduler.add_job(
    scheduled_price_update,
    trigger='cron',
    hour=UPDATE_HOUR,
    minute=UPDATE_MINUTE,
    id='daily_price_sync'
)
scheduler.start()


@app.route("/api/health", methods=["GET"])
def health_check():
    return jsonify({
        "status": "ok", 
        "message": "Shopify Price Sync API is running.",
        "next_update_utc": str(scheduler.get_job('daily_price_sync').next_run_time)
    })

@app.route("/api/update_schedule", methods=["POST"])
def update_schedule():
    """
    Endpoint para cambiar la hora de la actualización automática desde el HTML.
    Recibe la hora (0-23) y minuto (0-59).
    """
    data = request.json
    if not data or 'hour' not in data or 'minute' not in data:
        return jsonify({"error": "Parámetros 'hour' y 'minute' son requeridos"}), 400

    new_hour = int(data.get('hour'))
    new_minute = int(data.get('minute'))
    
    if not (0 <= new_hour <= 23) or not (0 <= new_minute <= 59):
         return jsonify({"error": "Hora (0-23) o minuto (0-59) inválidos"}), 400

    scheduler.reschedule_job(
        'daily_price_sync',
        trigger='cron',
        hour=new_hour,
        minute=new_minute
    )
    
    return jsonify({
        "message": "Horario actualizado",
        "next_update_utc": str(scheduler.get_job('daily_price_sync').next_run_time)
    })


@app.route("/api/add_card", methods=["POST"])
def add_card_to_shopify():
    """
    Endpoint para que index.html envíe una carta y se cree en Shopify.
    """
    if not update_prices.SHOPIFY_STORE_URL or not update_prices.SHOPIFY_CLIENT_ID:
        return jsonify({"error": "Shopify credentials not configured in server."}), 500

    data = request.json
    if not data or 'card' not in data:
        return jsonify({"error": "Invalid payload, missing 'card' data."}), 400

    card = data['card']
    
    # 1. Autenticarse
    token = update_prices.get_shopify_access_token()
    if not token:
        return jsonify({"error": "Failed to authenticate with Shopify."}), 500

    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json"
    }

    # 2. Calcular los precios en CLP
    prices = card.get('prices', {})
    usd = prices.get('usd')
    eur = prices.get('eur')
    
    # Check if a custom margin was sent, otherwise use default 1.30
    margin = data.get('margin', 1.30)
    try:
        margin = float(margin)
    except ValueError:
        margin = 1.30
        
    clp_non_foil = update_prices.calculate_clp_price(usd, eur, margin)

    usd_foil = prices.get('usd_foil')
    eur_foil = prices.get('eur_foil')
    clp_foil = update_prices.calculate_clp_price(usd_foil, eur_foil, margin)

    if clp_non_foil is None and clp_foil is None:
         return jsonify({"error": "No price available in Scryfall (USD or EUR) to calculate CLP."}), 400

    # 3. Preparar el Payload del Producto
    tags = "singlemtg, single mtg"
    
    html_description = """
<p>Ganar en Magic: The Gathering muchas veces depende de tener la carta correcta. En la apertura al azar de productos sellados no puedes asegurar que obtendrás la carta específica ni el playset completo (las cuatro copias permitidas en algunos formatos), por eso buscar cartas sueltas o singles Magic es una estrategia clave en el deckbuilding y la construcción de tu mazo.</p>
<p>Las cartas Magic individuales te permiten optimizar tu estrategia en formatos como Commander, Standard, Pauper o Legacy, asegurando exactamente la pieza que necesitas sin depender del azar.</p>
<p>Magic no es solo un juego competitivo; también es colección, historia y comunidad. Cada mazo que construyes cuenta algo, y a veces solo te falta ese comandante, planeswalker o criatura que completa tu idea.</p>
<p>Los precios de nuestros singles de Magic: The Gathering se ajustan desde el 01.03.2026 según la base de datos internacional Scryfall. El valor de una carta puede variar día a día, pero las colecciones de Magic han demostrado valorizarse con el tiempo.</p>
<p>Realizamos envíos el mismo día dentro de Santiago hasta las 11:00 am y entregas en 1 a 2 días hábiles según tu ubicación.</p>
"""
    
    status = data.get('status', 'active')
    try:
        inventory_quantity = int(data.get('stock', 0))
    except (ValueError, TypeError):
        inventory_quantity = 0

    try:
        inventory_quantity_foil = int(data.get('stockFoil', 0))
    except (ValueError, TypeError):
        inventory_quantity_foil = 0

    variants = []
    
    if clp_non_foil:
        variants.append({
            "option1": "Non-Foil",
            "price": str(clp_non_foil["final"]),
            "cost": str(clp_non_foil["cost"]),
            "inventory_management": "shopify",
            "inventory_quantity": inventory_quantity
        })
        
    if clp_foil:
        variants.append({
            "option1": "Foil",
            "price": str(clp_foil["final"]),
            "cost": str(clp_foil["cost"]),
            "inventory_management": "shopify",
            "inventory_quantity": inventory_quantity_foil
        })

    # Imágenes
    images = []
    image_uri = card.get('image_uris', {}).get('normal', '')
    if image_uri:
        images.append({"src": image_uri})

    # Metacampos se aplicarán en un segundo paso debido a restricciones de API de Shopify
    
    product_payload = {
        "product": {
            "title": card.get('name'),
            "body_html": html_description,
            "vendor": "",
            "product_type": "singlemtg",
            "tags": tags,
            "template_suffix": "singles",
            "options": [{"name": "Finish"}],
            "variants": variants,
            "images": images,
            "status": status
        }
    }

    # 4. Enviar a Shopify (Crear Producto)
    url = f"https://{update_prices.SHOPIFY_STORE_URL}/admin/api/{update_prices.API_VERSION}/products.json"
    
    try:
        response = update_prices.requests.post(url, headers=headers, json=product_payload)
        response.raise_for_status()
        created_product = response.json().get('product', {})
        product_id = created_product.get('id')
        
        # 5. Configurar Stock (Inventory Level)
        # Buscar la Location principal
        loc_url = f"https://{update_prices.SHOPIFY_STORE_URL}/admin/api/{update_prices.API_VERSION}/locations.json"
        loc_res = update_prices.requests.get(loc_url, headers=headers)
        if loc_res.status_code == 200 and loc_res.json().get('locations'):
            location_id = loc_res.json()['locations'][0]['id']
            # Para cada variante, establecer su inventario
            for variant in created_product.get('variants', []):
                inv_item_id = variant.get('inventory_item_id')
                if inv_item_id:
                    is_foil = variant.get('option1') == 'Foil'
                    qty = inventory_quantity_foil if is_foil else inventory_quantity
                    
                    inv_url = f"https://{update_prices.SHOPIFY_STORE_URL}/admin/api/{update_prices.API_VERSION}/inventory_levels/set.json"
                    inv_payload = {
                        "location_id": location_id,
                        "inventory_item_id": inv_item_id,
                        "available": qty
                    }
                    update_prices.requests.post(inv_url, headers=headers, json=inv_payload)

        # 6. Intentar agregar el metacampo (puede fallar por las restricciones de categoría en Shopify)
        metafield_warning = None
        if card.get('id'):
            mf_url = f"https://{update_prices.SHOPIFY_STORE_URL}/admin/api/{update_prices.API_VERSION}/products/{product_id}/metafields.json"
            mf_payload = {
                "metafield": {
                    "namespace": "custom",
                    "key": "scryfall_id",
                    "value": str(card.get('id')),
                    "type": "single_line_text_field"
                }
            }
            mf_res = update_prices.requests.post(mf_url, headers=headers, json=mf_payload)
            if mf_res.status_code != 201:
                metafield_warning = "La carta fue creada exitosamente en Shopify, pero Shopify bloqueó el metacampo 'scryfall_id' debido a la restricción de 'Asignaciones de Categorías'. Para que se guarde automático, debes quitar la restricción del metacampo en Shopify."

        return jsonify({
            "message": "Product created successfully",
            "product_id": product_id,
            "handle": created_product.get('handle'),
            "warning": metafield_warning
        }), 201
    except Exception as e:
        error_msg = str(e)
        if hasattr(e, 'response') and e.response is not None:
            error_msg = e.response.text
        print(f"Error creating product: {error_msg}")
        return jsonify({"error": f"Failed to create product in Shopify: {error_msg}"}), 500

if __name__ == "__main__":
    # Correr localmente
    port = int(os.environ.get("PORT", 5000))
    # use_reloader=False es necesario cuando se usa APScheduler con el servidor de desarrollo de Flask
    # para evitar que el scheduler se inicie dos veces.
    app.run(host="0.0.0.0", port=port, use_reloader=False)

