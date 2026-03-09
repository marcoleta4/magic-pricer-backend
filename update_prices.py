import cardkingdom_sync
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

load_dotenv()

SHOPIFY_STORE_URL = os.getenv("SHOPIFY_STORE_URL")
SHOPIFY_CLIENT_ID = os.getenv("SHOPIFY_CLIENT_ID")
SHOPIFY_CLIENT_SECRET = os.getenv("SHOPIFY_CLIENT_SECRET")
API_VERSION = "2026-01"  # Updated according to your Shopify console

HEADERS = {
    "Content-Type": "application/json"
}

# Global margin used for updates
DEFAULT_MARGIN = float(os.environ.get("DEFAULT_MARGIN", "1.30"))
USD_TO_CLP = 970

def get_shopify_access_token():
    """
    Get access token from env or using Shopify's Client Credentials Grant flow.
    """
    # If we already have a direct Access Token (Custom App), use it.
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
        if hasattr(e, 'response') and e.response is not None:
             print(e.response.text)
        return None

def get_shopify_mtg_products():
    """
    Fetch products from Shopify. 
    You might want to filter by tags (e.g., 'MTG') or a specific collection.
    """
    products = []
    # Endpoint to get products
    url = f"https://{SHOPIFY_STORE_URL}/admin/api/{API_VERSION}/products.json?limit=250"
    
    while url:
        response = requests.get(url, headers=HEADERS)
        if response.status_code != 200:
            print(f"Error fetching products: {response.status_code} - {response.text}")
            break
        
        data = response.json()
        products.extend(data.get("products", []))
        
        # Pagination support (Shopify uses Link headers for pagination)
        links = response.headers.get("Link", "")
        next_url = None
        if "rel=\"next\"" in links:
            parts = links.split(",")
            for part in parts:
                if "rel=\"next\"" in part:
                    next_url = part.split(";")[0].strip("<> ")
        url = next_url

    return products

def calculate_clp_price(usd_str, eur_str, margin_pct=1.30, ck_price=None):
    """
    Applies unified formula: Average(Scryfall USD, Scryfall EUR*1.05, CK Price) -> CLP
    """
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
    
    ck = None
    if ck_price:
        try: ck = float(ck_price)
        except: pass

    vals = []
    if usd is not None: vals.append(usd)
    if eur is not None: vals.append(eur * EUR_TO_USD)
    if ck is not None: vals.append(ck)

    if not vals:
        return None

    avg_usd = sum(vals) / len(vals)
    cost_clp = avg_usd * USD_TO_CLP
    final_clp = cost_clp * margin_pct

    return {
        "cost": round(cost_clp),
        "final": round(final_clp)
    }

def get_product_metafield(product_id, namespace, key):
    """
    Fetch a specific metafield for a product.
    """
    url = f"https://{SHOPIFY_STORE_URL}/admin/api/{API_VERSION}/products/{product_id}/metafields.json"
    response = requests.get(url, headers=HEADERS)
    if response.status_code == 200:
        metafields = response.json().get('metafields', [])
        for mf in metafields:
            if mf.get('namespace') == namespace and mf.get('key') == key:
                return mf.get('value')
    return None

def get_scryfall_price_clp(card_name, set_code=None, is_foil=False, margin=1.30):
    """
    Get the price of a card from Scryfall and convert it to CLP Final Price.
    """
    # Simple search by exact name. For more precision, set_code should be used.
    query = f'!\"{card_name}\"'
    if set_code:
        query += f' set:{set_code}'
        
    url = f"https://api.scryfall.com/cards/search?q={query}"
    time.sleep(0.1)  # Scryfall rate limit consideration (10 requests per second)
    
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            if data['data']:
                card = data['data'][0]
                prices = card.get('prices', {})
                
                usd_key = 'usd_foil' if is_foil else 'usd'
                eur_key = 'eur_foil' if is_foil else 'eur'
                
                # --- INTEGRACIÓN CARD KINGDOM ---
                ck_price_usd = cardkingdom_sync.get_ck_price(card_name, set_code, is_foil)
                
                # Usar la nueva fórmula unificada (promedia Scryfall y CK si ambos existen)
                clp_data = calculate_clp_price(prices.get(usd_key), prices.get(eur_key), margin, ck_price_usd)
                
                if clp_data:
                    return {
                        "final_price": clp_data["final"],
                        "scryfall_clp": clp_data["final"], # Mantenemos key para compatibilidad
                        "ck_usd": ck_price_usd or 0,
                        "set_name": card.get("set_name", "")
                    }
        return None
    except Exception as e:
        print(f"Error fetching from Scryfall for {card_name}: {e}")
        return None

def update_shopify_variant_price(variant_id, new_price):
    """
    Update the price of a specific variant in Shopify.
    """
    if not new_price:
        return False
        
    url = f"https://{SHOPIFY_STORE_URL}/admin/api/{API_VERSION}/variants/{variant_id}.json"
    payload = {
        "variant": {
            "id": variant_id,
            "price": str(new_price)
        }
    }
    
    response = requests.put(url, headers=HEADERS, json=payload)
    if response.status_code == 200:
        return True
    else:
        print(f"Error updating variant {variant_id}: {response.status_code} - {response.text}")
        return False

def main():
    print("--- Starting Price Update Script ---")
    
    # 0. Crear registro de inicio en Supabase
    sync_id = None
    if supabase:
        try:
            res = supabase.table("sync_history").insert({"status": "running", "cards_processed": 0}).execute()
            if res.data:
                sync_id = res.data[0]["id"]
        except Exception as e:
            print(f"Error creating sync log: {e}")

    print("Authenticating with Shopify...")
    token = get_shopify_access_token()
    if not token:
        print("Failed to get Shopify access token. Exiting.")
        # If sync failed, update Supabase status
        if sync_id and supabase:
            supabase.table("sync_history").update({"status": "failed", "errors": "Failed to get Shopify access token"}).eq("id", sync_id).execute()
        return
        
    HEADERS["X-Shopify-Access-Token"] = token
    
    print("Fetching products from Shopify...")
    products = get_shopify_mtg_products()
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
            variant_data = {
                "product_id": product_id,
                "product_title": card_name,
                "set_code": set_code,
                "variant_id": variant.get("id"),
                "variant_title": variant.get("title", "").lower(),
                "current_price": variant.get("price")
            }
            all_variants.append(variant_data)
    
    total_cards = len(all_variants)
    if sync_id and supabase:
        supabase.table("sync_history").update({"total_cards": total_cards}).eq("id", sync_id).execute()

    for i, variant_data in enumerate(all_variants):
        # Update progress every 5 cards to avoid too many requests
        if i % 5 == 0 and sync_id and supabase:
            try:
                supabase.table("sync_history").update({
                    "cards_processed": i,
                    "updates_made": updates_made
                }).eq("id", sync_id).execute()
            except Exception as e:
                print(f"Error updating sync progress in Supabase: {e}")

        product_id = variant_data.get("product_id")
        card_name = variant_data.get("product_title")
        set_code = variant_data.get("set_code")
        variant_id = variant_data.get("variant_id")
        variant_title = variant_data.get("variant_title")
        current_price = variant_data.get("current_price")
        
        # Use the global margin from this module
        default_margin = DEFAULT_MARGIN
            
        # Intentamos obtener el margen personalizado guardado en un metacampo
        custom_margin_str = get_product_metafield(product_id, "custom", "custom_margin")
        try:
            margin = float(custom_margin_str) if custom_margin_str else default_margin
            if margin != default_margin:
                print(f" -> Usando margen personalizado: {margin}")
        except ValueError:
            margin = default_margin

        # You might have the set code in a tag or a metafield.
        tags = product.get("tags", "")
        set_code = None
        for tag in tags.split(","):
            if tag.strip().startswith("SET_"):
                set_code = tag.strip().split("_")[1].lower()
                
        for variant in product.get("variants", []):
            variant_id = variant.get("id")
            variant_title = variant.get("title", "").lower()
            current_price = variant.get("price")
            
            is_foil = "foil" in variant_title and "non-foil" not in variant_title
            
            print(f"Checking Price for: {card_name} [{set_code}] - Foil: {is_foil} (Margin: {margin})")
            
            card_info = get_scryfall_price_clp(card_name, set_code, is_foil, margin)
            new_price_clp = card_info["final_price"] if card_info else None

            if new_price_clp:
                # Compare as strings / numbers carefully
                try: current_price_float = float(current_price)
                except: current_price_float = 0
                
                if abs(current_price_float - new_price_clp) > 1:
                    print(f" -> Updating price from {current_price} to {new_price_clp} CLP")
                    success = update_shopify_variant_price(variant_id, new_price_clp)
                    if success:
                        updates_made += 1
                        import datetime
                        report_data.append({
                            "Fecha": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "Carta": card_name,
                            "Set": set_code or '',
                            "Set Name": card_info.get('set_name', ''),
                            "Foil": "Sí" if is_foil else "No",
                            "Precio Anterior": current_price,
                            "Precio Scryfall": card_info.get("scryfall_clp") or 0,
                            "Precio CK USD": card_info.get("ck_usd") or 0,
                            "Precio Nuevo": new_price_clp
                        })
                else:
                    print(f" -> Price is already up to date ({current_price} CLP).")
            else:
                print(f" -> No price found on Scryfall.")

    print(f"Finished. Updated {updates_made} variants.")
    
    # Save the report CSV (Use absolute path to ensure durability)
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    static_dir = os.path.join(BASE_DIR, 'static')
    os.makedirs(static_dir, exist_ok=True)
    report_path = os.path.join(static_dir, 'ultimo_reporte.csv')
    try:
        fieldnames = ["Fecha", "Carta", "Set", "Set Name", "Foil", "Precio Anterior", "Precio Scryfall", "Precio CK USD", "Precio Nuevo"]
        with open(report_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in report_data:
                writer.writerow(row)
        print(f"Report saved to absolute path: {report_path}")
        # Finalizar registro en Supabase
        if sync_id and supabase:
            from datetime import datetime
            supabase.table("sync_history").update({
                "status": "completed",
                "finished_at": datetime.now().isoformat(),
                "cards_processed": total_cards,
                "updates_made": updates_made,
                "report_available": True
            }).eq("id", sync_id).execute()

    except Exception as e:
        print(f"Failed to save report: {e}")
        if sync_id and supabase:
            supabase.table("sync_history").update({
                "status": "failed",
                "errors": str(e)
            }).eq("id", sync_id).execute()

if __name__ == "__main__":
    main()
