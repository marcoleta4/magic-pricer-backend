import os
import json
import base64
import pytz
import time
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
from supabase import create_client, Client
import update_prices
import cardkingdom_sync

# --- CONFIGURATION & SUPABASE ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = None

if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("Connected to Supabase correctly.")
    except Exception as e:
        print(f"Error connecting to Supabase: {e}")

def get_config():
    """Fetch config from Supabase or use defaults."""
    default_cfg = {"hour": 6, "minute": 0, "margin": 1.30}
    if not supabase: return default_cfg
    try:
        response = supabase.table("config_settings").select("*").eq("id", 1).execute()
        if response.data: return response.data[0]
    except Exception as e:
        print(f"Error reading config: {e}")
    return default_cfg

def save_config(hour, minute, margin=None):
    """Save config to Supabase."""
    if not supabase: return False
    try:
        data = {"id": 1, "hour": int(hour), "minute": int(minute)}
        if margin is not None: data["margin"] = float(margin)
        supabase.table("config_settings").upsert(data).execute()
        return True
    except Exception as e:
        print(f"Error saving config: {e}")
        return False

# --- HELPERS ---
def sync_metafield_helper(product_id, namespace, key, value):
    """Sync a metafield with upsert logic."""
    token = update_prices.get_shopify_access_token()
    if not token: return False
    
    headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}
    mf_type = "single_line_text_field"
    actual_value = str(value)
    
    if key == "foil":
        mf_type = "boolean"
        if isinstance(value, str): actual_value = value.lower() in ["true", "verdadero"]
        else: actual_value = bool(value)

    payload = {
        "metafield": {
            "namespace": namespace,
            "key": key,
            "value": actual_value,
            "type": mf_type
        }
    }

    try:
        # Check if exists
        check_url = f"https://{update_prices.SHOPIFY_STORE_URL}/admin/api/{update_prices.API_VERSION}/products/{product_id}/metafields.json"
        res = update_prices.requests.get(check_url, headers=headers)
        existing_id = None
        if res.status_code == 200:
            for mf in res.json().get('metafields', []):
                if mf['key'] == key and mf['namespace'] == namespace:
                    existing_id = mf['id']
                    break
        
        if existing_id:
            url = f"https://{update_prices.SHOPIFY_STORE_URL}/admin/api/{update_prices.API_VERSION}/products/{product_id}/metafields/{existing_id}.json"
            res = update_prices.requests.put(url, headers=headers, json=payload)
        else:
            url = f"https://{update_prices.SHOPIFY_STORE_URL}/admin/api/{update_prices.API_VERSION}/products/{product_id}/metafields.json"
            res = update_prices.requests.post(url, headers=headers, json=payload)
        return res.status_code in [200, 201]
    except Exception as e:
        print(f"Error in sync_metafield_helper: {e}")
        return False

# --- SCHEDULER ---
def scheduled_price_update():
    print(f"--- Running Scheduled Price Update at {datetime.now()} ---")
    cfg = get_config()
    update_prices.DEFAULT_MARGIN = float(cfg.get("margin", 1.30))
    update_prices.main()
    print("--- Scheduled Price Update Completed ---")

def scheduled_ck_sync():
    print(f"--- Running Scheduled Card Kingdom Sync at {datetime.now()} ---")
    cardkingdom_sync.download_pricelist()
    print("--- Card Kingdom Sync Completed ---")

scheduler = BackgroundScheduler(timezone=pytz.utc)
config = get_config()
scheduler.add_job(scheduled_price_update, trigger='cron', hour=config.get("hour", 6), minute=config.get("minute", 0), id='daily_price_sync')
scheduler.add_job(scheduled_ck_sync, trigger='cron', hour=5, minute=0, id='daily_ck_sync')

if not os.path.exists(cardkingdom_sync.CACHE_FILE):
    scheduler.add_job(scheduled_ck_sync, id='startup_ck_sync')

scheduler.start()

# --- APP & ROUTES ---
app = Flask(__name__)
CORS(app)

@app.route('/')
def serve_index():
    fallback_key = base64.b64decode("QUl6YVN5Q3pBT21uQVlYOXYyQ1NuZmlZZGliZ282TnAzRFVCX3k0").decode('utf-8')
    api_key = os.environ.get('GEMINI_API_KEY', fallback_key)
    return render_template('index.html', GEMINI_API_KEY=api_key)

@app.route('/api/add_metafield', methods=['POST'])
def add_metafield_endpoint():
    data = request.json
    pid = data.get('product_id')
    if not pid: return jsonify({"error": "Missing product_id"}), 400
    
    mf_data = {
        "scryfall_id": data.get('scryfall_id'),
        "rareza": {"common": "Común", "uncommon": "Infrecuente", "rare": "Rara", "mythic": "Mítica"}.get(data.get('rarity'), data.get('rarity')),
        "card_type": data.get('card_type'),
        "coste_de_mana_convertido": data.get('cmc'),
        "foil": data.get('foil'),
        "formato": data.get('formato'),
        "set_single": data.get('set_single'),
        "color": data.get('color')
    }
    errors = [k for k, v in mf_data.items() if v is not None and not sync_metafield_helper(pid, "custom", k, v)]
    if errors: return jsonify({"error": f"Failed for: {', '.join(errors)}"}), 500
    return jsonify({"message": "Successfully synced"}), 201

@app.route("/api/health", methods=["GET"])
def health_check():
    store_url = os.getenv("SHOPIFY_STORE_URL")
    status = "Unknown"
    token = update_prices.get_shopify_access_token()
    if token and store_url:
        try:
            res = update_prices.requests.get(f"https://{store_url}/admin/api/{update_prices.API_VERSION}/shop.json", headers={"X-Shopify-Access-Token": token}, timeout=5)
            status = f"CONNECTED ({res.json().get('shop', {}).get('name')})" if res.status_code == 200 else f"ERROR ({res.status_code})"
        except Exception as e: status = str(e)
    
    return jsonify({
        "status": "ok", 
        "shopify": status,
        "next_sync": str(scheduler.get_job('daily_price_sync').next_run_time)
    })

@app.route("/api/sync_status", methods=["GET"])
def get_sync_status():
    if not supabase: return jsonify({"status": "idle"})
    try:
        res = supabase.table("sync_history").select("*").eq("status", "running").order("started_at", desc=True).limit(1).execute()
        return jsonify(res.data[0] if res.data else {"status": "idle"})
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route("/api/sync_history", methods=["GET"])
def get_sync_history():
    if not supabase: return jsonify([])
    try:
        res = supabase.table("sync_history").select("*").order("started_at", desc=True).limit(10).execute()
        return jsonify(res.data or [])
    except Exception as e: return jsonify([])

@app.route("/api/update_schedule", methods=["POST"])
def update_schedule():
    data = request.json
    h, m, margin = int(data.get('hour', 6)), int(data.get('minute', 0)), data.get('margin')
    if not (0 <= h <= 23 and 0 <= m <= 59): return jsonify({"error": "Invalid time"}), 400
    save_config(h, m, margin)
    scheduler.reschedule_job('daily_price_sync', trigger='cron', hour=h, minute=m)
    return jsonify({"message": "Updated", "next": str(scheduler.get_job('daily_price_sync').next_run_time)})

@app.route("/api/get_schedule", methods=["GET"])
def get_schedule():
    return jsonify(get_config())

@app.route("/api/sync_ck", methods=["POST"])
def sync_ck_manual():
    scheduler.add_job(scheduled_ck_sync, trigger='date', run_date=datetime.now(), id=f'manual_ck_sync_{int(time.time())}')
    return jsonify({"message": "Started"}), 202

@app.route("/api/update_prices_manual", methods=["POST"])
def update_prices_manual():
    scheduler.add_job(scheduled_price_update, trigger='date', run_date=datetime.now(), id=f'manual_price_sync_{int(time.time())}')
    return jsonify({"message": "Started"}), 202

@app.route("/api/reporte", methods=["GET"])
def download_report():
    from flask import send_from_directory
    path = os.path.join(os.path.dirname(__file__), 'static', 'ultimo_reporte.csv')
    if not os.path.exists(path): return jsonify({"error": "No report"}), 404
    return send_from_directory(os.path.dirname(path), 'ultimo_reporte.csv', as_attachment=True)

@app.route("/api/add_card", methods=["POST"])
def add_card_to_shopify():
    data = request.json
    card = data['card']
    token = update_prices.get_shopify_access_token()
    if not token: return jsonify({"error": "Auth failed"}), 500
    
    margin = float(data.get('margin', 1.30))
    clp_n = update_prices.calculate_clp_price(card['prices'].get('usd'), card['prices'].get('eur'), margin, card.get('ck_price'))
    clp_f = update_prices.calculate_clp_price(card['prices'].get('usd_foil'), card['prices'].get('eur_foil'), margin, card.get('ck_price_foil'))
    
    if not clp_n and not clp_f: return jsonify({"error": "No price"}), 400

    variants = []
    if clp_n: variants.append({"option1": "Non-Foil", "price": str(clp_n["final"]), "cost": str(clp_n["cost"]), "inventory_management": "shopify", "inventory_quantity": int(data.get('stock', 0))})
    if clp_f: variants.append({"option1": "Foil", "price": str(clp_f["final"]), "cost": str(clp_f["cost"]), "inventory_management": "shopify", "inventory_quantity": int(data.get('stockFoil', 0))})

    payload = {
        "product": {
            "title": card.get('name'),
            "body_html": "<p>MTG Single.</p>",
            "product_type": "singlemtg",
            "status": data.get('status', 'active'),
            "variants": variants,
            "images": [{"src": card.get('image_uris', {}).get('normal', '')}]
        }
    }
    url = f"https://{update_prices.SHOPIFY_STORE_URL}/admin/api/{update_prices.API_VERSION}/products.json"
    res = update_prices.requests.post(url, headers={"X-Shopify-Access-Token": token}, json=payload)
    if res.status_code != 201: return jsonify({"error": res.text}), 500
    
    product_id = res.json()['product']['id']
    mfs = {"scryfall_id": card.get('id'), "rareza": card.get('rarity'), "card_type": card.get('type_line'), "coste_de_mana_convertido": str(card.get('cmc', 0)), "foil": card.get('foil', False), "set_single": card.get('set', '').lower()}
    for k, v in mfs.items(): sync_metafield_helper(product_id, "custom", k, v)
    return jsonify({"message": "Created", "product_id": product_id}), 201

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), use_reloader=False)
