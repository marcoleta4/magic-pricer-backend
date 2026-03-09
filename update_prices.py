import os
import requests
import time
from dotenv import load_dotenv

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

def calculate_clp_price(usd_str, eur_str, margin_pct=1.30):
    """
    Applies the same formula as the frontend to convert USD/EUR to Final CLP price.
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

    vals = []
    if usd is not None: vals.append(usd)
    if eur is not None: vals.append(eur * EUR_TO_USD)

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
                
                clp_data = calculate_clp_price(prices.get(usd_key), prices.get(eur_key), margin)
                if clp_data:
                    return clp_data["final"]
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
    print("Authenticating with Shopify...")
    token = get_shopify_access_token()
    if not token:
        print("Failed to get Shopify access token. Exiting.")
        return
        
    HEADERS["X-Shopify-Access-Token"] = token
    
    print("Fetching products from Shopify...")
    products = get_shopify_mtg_products()
    print(f"Found {len(products)} products.")

    updates_made = 0
    report_data = []
    
    for product in products:
        product_id = product.get("id")
        card_name = product.get("title")
        
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
            
            new_price_clp_data = get_scryfall_price_clp(card_name, set_code, is_foil, margin)
            new_price_clp = new_price_clp_data # Assuming scryfall_price_clp returns the float directly as per its definition

            if new_price_clp:
                # Compare as strings / numbers carefully, ignoring decimals if comparing CLP integers
                try:
                    current_price_float = float(current_price)
                except:
                    current_price_float = 0
                
                if abs(current_price_float - new_price_clp) > 1: # Tolerance of 1 peso
                    print(f" -> Updating price from {current_price} to {new_price_clp} CLP")
                    success = update_shopify_variant_price(variant_id, new_price_clp)
                    if success:
                        updates_made += 1
                        import datetime
                        report_data.append({
                            "Fecha": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "Carta": card_name,
                            "Set": set_code or '',
                            "Foil": "Sí" if is_foil else "No",
                            "Precio Anterior": current_price,
                            "Precio Nuevo": new_price_clp
                        })
                else:
                    print(f" -> Price is already up to date ({current_price} CLP).")
            else:
                print(f" -> No price found on Scryfall.")

    print(f"Finished. Updated {updates_made} variants.")
    
    import csv
    # Save the report CSV
    os.makedirs('static', exist_ok=True)
    report_path = os.path.join('static', 'ultimo_reporte.csv')
    try:
        with open(report_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=["Fecha", "Carta", "Set", "Foil", "Precio Anterior", "Precio Nuevo"])
            writer.writeheader()
            for row in report_data:
                writer.writerow(row)
        print(f"Report saved to {report_path}")
    except Exception as e:
        print(f"Failed to save report: {e}")

if __name__ == "__main__":
    main()
