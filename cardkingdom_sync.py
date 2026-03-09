import requests
import json
import os
import time

CACHE_FILE = "ck_cache.json"
CK_API_URL = "https://api.cardkingdom.com/api/v2/pricelist"

def download_pricelist():
    """Descarga la lista completa de precios de Card Kingdom y la procesa."""
    print("Iniciando descarga de precios de Card Kingdom...")
    try:
        response = requests.get(CK_API_URL, timeout=60)
        if response.status_code == 200:
            data = response.json()
            raw_cards = data.get("data", [])
            
            # Procesar para búsqueda rápida: "Nombre [Edicion]": precio
            processed_cache = {}
            for card in raw_cards:
                name = card.get("nm")
                edition = card.get("edition")
                price = card.get("sell_price")
                
                if name and edition and price:
                    # Guardamos tanto regular como foil (CK suele tener lineas distintas o flags)
                    # En la API v1, 'is_foil' indica si la entrada es foil.
                    is_foil = card.get("is_foil") == "true" or card.get("is_foil") is True
                    key = f"{name}|{edition}|{'foil' if is_foil else 'non'}"
                    processed_cache[key] = float(price)
            
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(processed_cache, f)
            
            print(f"Sincronización de Card Kingdom completada. {len(processed_cache)} entradas guardadas.")
            return True
        else:
            print(f"Error al descargar de CK: {response.status_code}")
            return False
    except Exception as e:
        print(f"Excepción en sincronización CK: {e}")
        return False

def get_ck_price(card_name, edition=None, is_foil=False):
    """Busca el precio de una carta en el caché local."""
    if not os.path.exists(CACHE_FILE):
        return None
    
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)
        
        # Intentar búsqueda exacta
        foil_key = 'foil' if is_foil else 'non'
        # CK usa nombres de ediciones completos (ej: 'Limited Edition Alpha', 'Fourth Edition')
        # A veces el 'edition' que pasamos es un set_code (ej: 'lea', '4ed').
        # Por ahora buscaremos por nombre exacto si el edition coincide o si no se provee.
        
        # Búsqueda optimista
        if edition:
            key = f"{card_name}|{edition}|{foil_key}"
            if key in cache:
                return cache[key]
        
        # Búsqueda por nombre (devuelve el primero que encuentre si no hay edicion exacta)
        # Nota: Esto es costoso si el cache es gigante, pero útil como fallback
        for key, price in cache.items():
            k_name, k_ed, k_foil = key.split('|')
            if k_name.lower() == card_name.lower() and k_foil == foil_key:
                return price
                
        return None
    except Exception as e:
        print(f"Error al leer caché de CK: {e}")
        return None

if __name__ == "__main__":
    # Prueba manual
    download_pricelist()
    p = get_ck_price("Black Lotus", "Limited Edition Alpha")
    print(f"Precio de prueba: {p}")
