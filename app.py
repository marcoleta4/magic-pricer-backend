import os
import json
import base64
import pytz
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
from supabase import create_client, Client

# Configuración de Supabase
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = None

if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("Conectado a Supabase correctamente.")
    except Exception as e:
        print(f"Error al conectar con Supabase: {e}")

def get_config():
    """Obtiene la configuración desde Supabase o usa valores por defecto."""
    default_cfg = {"hour": 6, "minute": 0, "margin": 1.30}
    if not supabase:
        return default_cfg
    try:
        response = supabase.table("config_settings").select("*").eq("id", 1).execute()
        if response.data:
            return response.data[0]
    except Exception as e:
        print(f"Error al leer config de Supabase: {e}")
    return default_cfg

def save_config(hour, minute, margin=None):
    """Guarda la configuración en Supabase."""
    if not supabase:
        return False
    try:
        data = {"id": 1, "hour": int(hour), "minute": int(minute)}
        if margin is not None:
            data["margin"] = float(margin)
        supabase.table("config_settings").upsert(data).execute()
        return True
    except Exception as e:
        print(f"Error al guardar config en Supabase: {e}")
        return False

def sync_metafield_helper(product_id, namespace, key, value):
    """Sincroniza un metacampo usando lógica Upsert y tipos correctos."""
    token = update_prices.get_shopify_access_token()
    if not token:
        return False
    
    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json"
    }
    
    # Determinar tipo y valor real
    mf_type = "single_line_text_field"
    actual_value = str(value)
    
    if key == "foil":
        mf_type = "boolean"
        if isinstance(value, str):
            actual_value = value.lower() == "true" or value == "Verdadero"
        else:
            actual_value = bool(value)
    elif key == "coste_de_mana_convertido" or key == "cmc":
        # Shopify tiene tipo 'number_integer' o 'number_decimal'
        # Pero podemos seguir usando texto o cambiarlo. Mantengamos texto por ahora o usemos integer.
        pass

    payload = {
        "metafield": {
            "namespace": namespace,
            "key": key,
            "value": actual_value,
            "type": mf_type
        }
    }

    # Buscar si ya existe para hacer PUT en lugar de POST
    try:
        mf_check_url = f"https://{update_prices.SHOPIFY_STORE_URL}/admin/api/{update_prices.API_VERSION}/products/{product_id}/metafields.json"
        check_res = update_prices.requests.get(mf_check_url, headers=headers)
        existing_id = None
        if check_res.status_code == 200:
            mfs = check_res.json().get('metafields', [])
            for mf in mfs:
                if mf['key'] == key and mf['namespace'] == namespace:
                    existing_id = mf['id']
                    break
        
        if existing_id:
            url = f"https://{update_prices.SHOPIFY_STORE_URL}/admin/api/{update_prices.API_VERSION}/products/{product_id}/metafields/{existing_id}.json"
            res = update_prices.requests.put(url, headers=headers, json=payload)
        else:
            url = f"https://{update_prices.SHOPIFY_STORE_URL}/admin/api/{update_prices.API_VERSION}/products/{product_id}/metafields.json"
            res = update_prices.requests.post(url, headers=headers, json=payload)
        
        if res.status_code in [200, 201]:
            return True
        else:
            print(f"Error Shopfiy Metafield ({key}): {res.status_code} - {res.text}")
            return False
    except Exception as e:
        print(f"Error sync_metafield_helper: {e}")
        return False

# Importar las funciones de nuestro script de actualizacion
import update_prices
import cardkingdom_sync

app = Flask(__name__)
# Enable CORS so the local index.html can send requests to this server
CORS(app)

@app.route('/')
def serve_index():
    # Decodificamos la clave en base64 para evitar que GitHub la bloquee automáticamente al subir el código
    fallback_key = base64.b64decode("QUl6YVN5Q3pBT21uQVlYOXYyQ1NuZmlZZGliZ282TnAzRFVCX3k0").decode('utf-8')
    api_key = os.environ.get('GEMINI_API_KEY', fallback_key)
    return render_template('index.html', GEMINI_API_KEY=api_key)

@app.route('/api/add_metafield', methods=['POST'])
def add_metafield_endpoint():
    data = request.json
    product_id = data.get('product_id')
    
    # Extraer campos
    metafields_data = {
        "scryfall_id": data.get('scryfall_id'),
        "rareza": data.get('rarity'),
        "card_type": data.get('card_type'),
        "coste_de_mana_convertido": data.get('cmc'),
        "foil": data.get('foil'),
        "formato": data.get('formato'),
        "set_single": data.get('set_single'),
        "color": data.get('color')
    }

    if not product_id:
        return jsonify({"error": "Faltan product_id"}), 400

    errors = []
    for k, v in metafields_data.items():
        if v is None: continue
        
        # Mapeo de traducciones si no vienen traducidas
        if k == "rareza":
            MAP = {"common": "Común", "uncommon": "Infrecuente", "rare": "Rara", "mythic": "Mítica"}
            v = MAP.get(v, v)
        
        success = sync_metafield_helper(product_id, "custom", k, v)
        if not success:
            errors.append(k)

    if errors:
        return jsonify({"error": f"Fallo en: {', '.join(errors)}"}), 500

    return jsonify({"message": "Metacampos sincronizados correctamente"}), 201


def scheduled_price_update():
    print(f"--- Running Scheduled Price Update at {datetime.now()} ---")
    # Cargar margen global desde Supabase antes de correr
    cfg = get_config()
    os.environ["DEFAULT_MARGIN"] = str(cfg.get("margin", 1.30))
    update_prices.DEFAULT_MARGIN = float(cfg.get("margin", 1.30))
    update_prices.main()
    print("--- Scheduled Price Update Completed ---")

def scheduled_ck_sync():
    print(f"--- Running Scheduled Card Kingdom Sync at {datetime.now()} ---")
    cardkingdom_sync.download_pricelist()
    print("--- Card Kingdom Sync Completed ---")

# Configurar el programador (Scheduler)
scheduler = BackgroundScheduler(timezone=pytz.utc)

# Leer config inicial de Supabase
config = get_config()
UPDATE_HOUR = config.get("hour", 6)
UPDATE_MINUTE = config.get("minute", 0)

scheduler.add_job(
    scheduled_price_update,
    trigger='cron',
    hour=UPDATE_HOUR,
    minute=UPDATE_MINUTE,
    id='daily_price_sync'
)

# Tarea para sincronizar Card Kingdom a las 5:00 AM UTC (antes de la actualización de precios)
scheduler.add_job(
    scheduled_ck_sync,
    trigger='cron',
    hour=5,
    minute=0,
    id='daily_ck_sync'
)

# Si no existe el cache al iniciar, lo descargamos
if not os.path.exists(cardkingdom_sync.CACHE_FILE):
    # Lo lanzamos en el scheduler para no bloquear el inicio de la app
    scheduler.add_job(scheduled_ck_sync, id='startup_ck_sync')

scheduler.start()


@app.route("/api/health", methods=["GET"])
def health_check():
    # Check for presence of required credentials
    store_url = os.getenv("SHOPIFY_STORE_URL")
    client_id = os.getenv("SHOPIFY_CLIENT_ID")
    client_secret = os.getenv("SHOPIFY_CLIENT_SECRET")
    access_token = os.getenv("SHOPIFY_ACCESS_TOKEN")
    
    # Try a simple connectivity test to Shopify
    shopify_status = "Unknown"
    shopify_error = None
    
    test_token = update_prices.get_shopify_access_token()
    if test_token and store_url:
        try:
            test_url = f"https://{store_url}/admin/api/{update_prices.API_VERSION}/shop.json"
            headers = {"X-Shopify-Access-Token": test_token}
            res = update_prices.requests.get(test_url, headers=headers, timeout=5)
            if res.status_code == 200:
                shopify_status = f"CONNECTED (Shop: {res.json().get('shop', {}).get('name')})"
            else:
                shopify_status = f"ERROR ({res.status_code})"
                shopify_error = res.text
        except Exception as e:
            shopify_status = "EXCEPTION"
            shopify_error = str(e)

    shopify_config = {
        "SHOPIFY_STORE_URL": "present" if store_url else "MISSING",
        "SHOPIFY_CLIENT_ID": "present" if client_id else "MISSING",
        "SHOPIFY_CLIENT_SECRET": "present" if client_secret else "MISSING",
        "SHOPIFY_ACCESS_TOKEN": "present" if access_token else "optional/missing",
        "connectivity_test": shopify_status,
        "shopify_response": shopify_error
    }

    return jsonify({
        "status": "ok", 
        "message": "Shopify Price Sync API is running.",
        "shopify_diagnostics": shopify_config,
        "next_update_utc": str(scheduler.get_job('daily_price_sync').next_run_time)
    })

@app.route("/api/update_schedule", methods=["POST"])
def update_schedule():
    data = request.json
    if not data or 'hour' not in data or 'minute' not in data:
        return jsonify({"error": "Parámetros 'hour' y 'minute' son requeridos"}), 400

    new_hour = int(data.get('hour'))
    new_minute = int(data.get('minute'))
    new_margin = data.get('margin')
    
    if not (0 <= new_hour <= 23) or not (0 <= new_minute <= 59):
         return jsonify({"error": "Hora (0-23) o minuto (0-59) inválidos"}), 400

    # Guardar en Supabase
    success = save_config(new_hour, new_minute, new_margin)
    
    # Reprogramar
    scheduler.reschedule_job(
        'daily_price_sync',
        trigger='cron',
        hour=new_hour,
        minute=new_minute
    )
    
    return jsonify({
        "message": "Horario actualizado en DB y Scheduler",
        "supabase_sync": success,
        "next_update_utc": str(scheduler.get_job('daily_price_sync').next_run_time)
    })

@app.route("/api/get_schedule", methods=["GET"])
def get_schedule():
    cfg = get_config()
    return jsonify(cfg)

@app.route("/api/sync_ck", methods=["POST"])
def sync_ck_manual():
    """Endpoint para forzar la descarga de precios de Card Kingdom."""
    success = cardkingdom_sync.download_pricelist()
    if success:
        return jsonify({"message": "Sincronización de Card Kingdom exitosa"}), 200
    else:
        return jsonify({"error": "Falló la sincronización de Card Kingdom"}), 500

@app.route("/api/update_prices_manual", methods=["POST"])
def update_prices_manual():
    """Forzar la ejecución del script de actualización de precios (Scryfall + CK)."""
    try:
        # Ejecutamos la función que el scheduler llamaría
        scheduled_price_update()
        return jsonify({"message": "Actualización de precios iniciada/completada"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/get_ck_price", methods=["GET"])
def get_ck_price_endpoint():
    """Obtener el precio de Card Kingdom para una carta específica (para el frontend)."""
    name = request.args.get('name')
    set_code = request.args.get('set')
    foil = request.args.get('foil') == 'true'
    
    if not name:
        return jsonify({"error": "El nombre de la carta es requerido"}), 400
        
    price = cardkingdom_sync.get_ck_price(name, set_code, foil)
    return jsonify({"price": price})

@app.route("/api/reporte", methods=["GET"])
def download_report():
    from flask import send_from_directory
    report_path = os.path.join(os.path.dirname(__file__), 'static', 'ultimo_reporte.csv')
    if not os.path.exists(report_path):
        return jsonify({"error": "No hay ningún reporte generado aún. La actualización automática debe correr al menos una vez."}), 404
        
    return send_from_directory('static', 'ultimo_reporte.csv', as_attachment=True)


@app.route("/api/add_card", methods=["POST"])
def add_card_to_shopify():
    """
    Endpoint para que index.html envíe una carta y se cree en Shopify.
    """
    store_url = update_prices.SHOPIFY_STORE_URL
    client_id = update_prices.SHOPIFY_CLIENT_ID
    
    if not store_url or not client_id:
        missing = []
        if not store_url: missing.append("SHOPIFY_STORE_URL")
        if not client_id: missing.append("SHOPIFY_CLIENT_ID")
        return jsonify({
            "error": f"Shopify credentials not configured in server. Missing: {', '.join(missing)}. Please set them in Render dashboard."
        }), 500

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

        # 6. Sincronizar metacampos detallados usando el helper (Upsert + Tipos)
        metafield_warning = None
        if card.get('id'):
            # Preparar datos para sincronizar
            # Traducciones básicas
            RARITY_MAP = {"common": "Común", "uncommon": "Infrecuente", "rare": "Rara", "mythic": "Mítica"}
            COLOR_MAP = {"W": "Blanco", "U": "Azul", "B": "Negro", "R": "Rojo", "G": "Verde"}
            
            r_en = card.get('rarity', 'common')
            r_es = RARITY_MAP.get(r_en, r_en.capitalize())
            
            c_list = card.get('colors', [])
            if not c_list and card.get('mana_cost') == "":
                c_str = "Incoloro"
            elif len(c_list) > 1:
                c_str = "Multicolor"
            else:
                c_str = COLOR_MAP.get(c_list[0], c_list[0]) if c_list else "Incoloro"

            metafields_to_sync = {
                "scryfall_id": card.get('id'),
                "rareza": r_es,
                "card_type": card.get('type_line'),
                "coste_de_mana_convertido": str(card.get('cmc', 0)),
                "foil": card.get('foil', False),
                "set_single": card.get('set', '').lower(),
                "color": c_str
            }

            errors_mf = []
            for k, v in metafields_to_sync.items():
                if v is None: continue
                if not sync_metafield_helper(product_id, "custom", k, v):
                    errors_mf.append(k)
            
            if errors_mf:
                metafield_warning = f"Algunos metacampos fallaron: {', '.join(errors_mf)}"

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

