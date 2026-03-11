import os
import requests
import time
import json
import csv
import datetime
from dotenv import load_dotenv
# import cardkingdom_sync
from supabase import create_client, Client

load_dotenv()

# Configuración de Supabase
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = None

if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"Error al conectar con Supabase en update_prices: {e}")

SHOPIFY_STORE_URL = os.getenv("SHOPIFY_STORE_URL")
SHOPIFY_CLIENT_ID = os.getenv("SHOPIFY_CLIENT_ID")
SHOPIFY_CLIENT_SECRET = os.getenv("SHOPIFY_CLIENT_SECRET")
API_VERSION = "2024-01"

HEADERS = {
    "Content-Type": "application/json"
}

# Global margin used for updates
DEFAULT_MARGIN = float(os.environ.get("DEFAULT_MARGIN", "1.30"))
USD_TO_CLP = 970

def _update_sync_history(sync_id, **fields):
    """Small helper to avoid duplicated Supabase update calls."""
    if not (supabase and sync_id):
        return
    try:
        supabase.table("sync_history").update(fields).eq("id", sync_id).execute()
    except Exception as e:
        print(f"Error updating sync_history: {e}")

def get_config_margin():
    """Fetches the margin from Supabase config_settings table."""
    if not supabase:
        return DEFAULT_MARGIN
    try:
        response = supabase.table("config_settings").select("margin").eq("id", 1).execute()
        if response.data:
            return float(response.data[0].get("margin", DEFAULT_MARGIN))
    except Exception as e:
        print(f"Error reading margin from Supabase: {e}")
    return DEFAULT_MARGIN

def get_shopify_access_token():
    token = os.getenv("SHOPIFY_ACCESS_TOKEN")
    if token:
        return token

    if not SHOPIFY_STORE_URL or not SHOPIFY_CLIENT_ID or not SHOPIFY_CLIENT_SECRET:
        print("Missing Shopify credentials in .env")
        return None

    url = f"https://{SHOPIFY_STORE_URL}/admin/oauth/access_token"
    payload = {
        "grant_type": "client_credentials",
        "client_id": SHOPIFY_CLIENT_ID,
        "client_secret": SHOPIFY_CLIENT_SECRET
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        return data.get("access_token")
    except Exception as e:
        print(f"Error authenticating with Shopify: {e}")
        return None

def get_shopify_mtg_products():
    products = []
    url = f"https://{SHOPIFY_STORE_URL}/admin/api/{API_VERSION}/products.json?limit=250"
    while url:
        response = requests.get(url, headers=HEADERS)
        if response.status_code != 200:
            print(f"Error fetching products: {response.status_code} - {response.text}")
            break
        data = response.json()
        products.extend(data.get("products", []))
        links = response.headers.get("Link", "")
        next_url = None
        if "rel=\"next\"" in links:
            parts = links.split(",")
            for part in parts:
                if "rel=\"next\"" in part:
                    next_url = part.split(";")[0].strip("<> ")
        url = next_url
    return products

def calculate_clp_price(usd_str, eur_str, margin_pct=1.30):
    USD_TO_CLP = 970
    EUR_TO_USD = 1.05
    usd = None
    if usd_str:
        try: usd = float(usd_str)
        except: pass
    eur = None
    if eur_str:
        try: eur = float(eur_str)
        except: pass
    if usd is not None: vals.append(usd)
    if eur is not None: vals.append(eur * EUR_TO_USD)
    if not vals:
        return None
    avg_usd = sum(vals) / len(vals)
    cost_clp = avg_usd * USD_TO_CLP
    final_clp = cost_clp * margin_pct
    return {"cost": round(cost_clp), "final": round(final_clp)}

def get_product_metafield(product_id, namespace, key):
    url = f"https://{SHOPIFY_STORE_URL}/admin/api/{API_VERSION}/products/{product_id}/metafields.json"
    response = requests.get(url, headers=HEADERS)
    if response.status_code == 200:
        metafields = response.json().get('metafields', [])
        for mf in metafields:
            if mf.get('namespace') == namespace and mf.get('key') == key:
                return mf.get('value')
    return None

def get_scryfall_price_clp(card_name, set_code=None, is_foil=False, margin=1.30):
    query = f'!\"{card_name}\"'
    if set_code:
        query += f' set:{set_code}'
    url = f"https://api.scryfall.com/cards/search?q={query}"
    time.sleep(0.1)
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            if data['data']:
                card = data['data'][0]
                prices = card.get('prices', {})
                usd_key = 'usd_foil' if is_foil else 'usd'
                eur_key = 'eur_foil' if is_foil else 'eur'
                # ck_price_usd = cardkingdom_sync.get_ck_price(card_name, set_code, is_foil)
                clp_data = calculate_clp_price(prices.get(usd_key), prices.get(eur_key), margin)
                if clp_data:
                    return {
                        "final_price": clp_data["final"],
                        "scryfall_clp": clp_data["final"],
                        "ck_usd": 0,
                        "set_name": card.get("set_name", "")
                    }
        return None
    except Exception as e:
        print(f"Error fetching from Scryfall for {card_name}: {e}")
        return None

def update_shopify_variant_price(variant_id, new_price):
    if not new_price:
        return False
    url = f"https://{SHOPIFY_STORE_URL}/admin/api/{API_VERSION}/variants/{variant_id}.json"
    payload = {"variant": {"id": variant_id, "price": str(new_price)}}
    response = requests.put(url, headers=HEADERS, json=payload)
    return response.status_code == 200

def main():
    try:
        _run_main()
    except Exception as e:
        import traceback
        try:
            # Attempt to persist an error report so the UI has something to download
            BASE_DIR = os.path.dirname(os.path.abspath(__file__))
            static_dir = os.path.join(BASE_DIR, 'static')
            os.makedirs(static_dir, exist_ok=True)
            report_path = os.path.join(static_dir, 'ultimo_reporte.csv')
            with open(report_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(["ERROR DE EJECUCIÓN", "FECHA"])
                writer.writerow([f"Global Error: {e}", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
        except Exception:
            pass
        with open("error_log.txt", "a") as f:
            f.write(f"Global Error: {datetime.datetime.now()}\n{traceback.format_exc()}\n")

def _run_main():
    print("--- Starting Price Update Script ---")
    
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    static_dir = os.path.join(BASE_DIR, 'static')
    os.makedirs(static_dir, exist_ok=True)
    report_path = os.path.join(static_dir, 'ultimo_reporte.csv')
    last_error = None
    sync_status = "running"
    
    def save_error_report(error_msg):
        try:
            with open(report_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(["ERROR DE EJECUCIÓN", "FECHA"])
                writer.writerow([error_msg, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
        except Exception as e:
            print(f"No se pudo guardar el reporte de error: {e}")
        finally:
            nonlocal last_error
            last_error = error_msg

    sync_id = None
    if supabase:
        try:
            res = supabase.table("sync_history").insert({"status": "running", "cards_processed": 0}).execute()
            if res.data:
                sync_id = res.data[0]["id"]
        except Exception as e:
            print(f"Error creating sync log in Supabase: {e}")
    
    margin = get_config_margin()
    print(f"--- Iniciar Sincronización (Margen: {margin}) ---")
    
    # Check if CK cache exists (SKIP)
    # if not os.path.exists(cardkingdom_sync.CACHE_FILE):
    #     print(f"WARN: {cardkingdom_sync.CACHE_FILE} not found. Card Kingdom prices will be skipped.")

    token = get_shopify_access_token()
    if not token:
        msg = "Error: No se pudo obtener el token de acceso de Shopify. Revisa tus credenciales."
        print(msg)
        save_error_report(msg)
        _update_sync_history(sync_id, status="failed", errors=msg, report_available=True)
        return
        
    HEADERS["X-Shopify-Access-Token"] = token
    
    try:
        products = get_shopify_mtg_products()
    except Exception as e:
        msg = f"Error al obtener productos de Shopify: {e}"
        print(msg)
        save_error_report(msg)
        _update_sync_history(sync_id, status="failed", errors=msg, report_available=True)
        return
        
    print(f"Found {len(products)} products.")
    updates_made = 0
    report_data = []
    all_variants = []

    for product in products:
        product_id = product.get("id")
        card_name = product.get("title")
        tags = product.get("tags", "")
        set_code = None
        for tag in tags.split(","):
            if tag.strip().startswith("SET_"):
                set_code = tag.strip().split("_")[1].lower()

        for variant in product.get("variants", []):
            all_variants.append({
                "product_id": product_id,
                "product_title": card_name,
                "set_code": set_code,
                "variant_id": variant.get("id"),
                "variant_title": variant.get("title", "").lower(),
                "current_price": variant.get("price")
            })
    
    total_cards = len(all_variants)
    if sync_id and supabase:
        try: supabase.table("sync_history").update({"total_cards": total_cards}).eq("id", sync_id).execute()
        except: pass

    try:
        for i, variant_data in enumerate(all_variants):
            if i % 5 == 0:
                _update_sync_history(sync_id, cards_processed=i, updates_made=updates_made)

            margin = DEFAULT_MARGIN
            try:
                custom_margin_str = get_product_metafield(variant_data["product_id"], "custom", "custom_margin")
                if custom_margin_str: margin = float(custom_margin_str)
            except: pass

            is_foil = "foil" in variant_data["variant_title"] and "non-foil" not in variant_data["variant_title"]
            
            try:
                card_info = get_scryfall_price_clp(variant_data["product_title"], variant_data["set_code"], is_foil, margin)
            except: continue
                
            new_price_clp = card_info["final_price"] if card_info else None
            if new_price_clp:
                try: current_price_float = float(variant_data["current_price"])
                except: current_price_float = 0
                
                if abs(current_price_float - new_price_clp) > 1:
                    if update_shopify_variant_price(variant_data["variant_id"], new_price_clp):
                        updates_made += 1
                        report_data.append({
                            "Fecha": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "Carta": variant_data["product_title"],
                            "Set": variant_data["set_code"] or '',
                            "Set Name": card_info.get('set_name', ''),
                            "Foil": "Sí" if is_foil else "No",
                            "Precio Anterior": variant_data["current_price"],
                            "Precio Scryfall": card_info.get("scryfall_clp") or 0,
                            "Precio CK USD": card_info.get("ck_usd") or 0,
                            "Precio Nuevo": new_price_clp
                        })

        print(f"Finished. Updated {updates_made} variants.")
        
        fieldnames = ["Fecha", "Carta", "Set", "Set Name", "Foil", "Precio Anterior", "Precio Scryfall", "Precio CK USD", "Precio Nuevo"]
        with open(report_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            if not report_data:
                writer.writerow({"Fecha": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "Carta": "SIN CAMBIOS DETECTADOS", "Set": "-", "Set Name": "-", "Foil": "-", "Precio Anterior": "-", "Precio Scryfall": "-", "Precio CK USD": "-", "Precio Nuevo": "-"})
            else:
                for row in report_data:
                    writer.writerow(row)
        
        _update_sync_history(
            sync_id,
            status="completed",
            finished_at=datetime.datetime.now().isoformat(),
            cards_processed=total_cards,
            updates_made=updates_made,
            report_available=True
        )
        sync_status = "completed"
    except Exception as e:
        msg = f"Fallo al guardar reporte final: {e}"
        print(f"Failed to save report: {e}")
        save_error_report(msg)
        _update_sync_history(sync_id, status="failed", errors=msg, report_available=True)
        sync_status = "failed"
    finally:
        if sync_status == "running":
            # If we reach here without explicitly completing, consider it failed.
            fallback_msg = last_error or "Proceso interrumpido antes de finalizar."
            _update_sync_history(sync_id, status="failed", errors=fallback_msg, report_available=bool(last_error))

if __name__ == "__main__":
    main()
