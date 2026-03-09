import requests
import json
import os
import time

CACHE_FILE = "ck_cache.json"
CK_API_URL = "https://api.cardkingdom.com/api/v2/pricelist"

def download_pricelist():
    url = "https://api.cardkingdom.com/api/v2/pricelist"
    print(f"Downloading Card Kingdom pricelist from {url}...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    try:
        response = requests.get(url, headers=headers, timeout=60)
        if response.status_code == 200:
            content_type = response.headers.get('Content-Type', 'unknown')
            content_len = len(response.content)
            print(f"Respuesta recibida: {content_type}, Tamaño: {content_len} bytes")
            
            data = response.json()
            # La API v2 puede devolver un dict con "data" o una lista directamente
            raw_cards = []
            if isinstance(data, dict):
                print(f"Estructura dict detectada. Claves: {list(data.keys())}")
                raw_cards = data.get("data", [])
            elif isinstance(data, list):
                print(f"Estructura list detectada. Items: {len(data)}")
                raw_cards = data
            
            print(f"Procesando {len(raw_cards)} cartas...")
            
            # Procesar para búsqueda rápida: "Nombre|Edicion|Foil": precio
            processed_cache = {}
            for i, card in enumerate(raw_cards):
                # v2 usa nm para name, edition para edition, sell_price para el precio
                name = card.get("nm") or card.get("name")
                edition = card.get("edition")
                price = card.get("sell_price") or card.get("price")
                
                if name and price:
                    is_foil = str(card.get("is_foil")).lower() == "true" or card.get("is_foil") is True
                    # Normalizar nombres para evitar fallos por espacios/caracteres
                    key = f"{name.strip()}|{edition.strip() if edition else ''}|{'foil' if is_foil else 'non'}"
                    processed_cache[key] = float(price)
                
                if i == 0:
                    print(f"Ejemplo de carta 0: {card}")
            
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
        
        # 0. Resolución de nombre de edición (Set Code -> Full Name)
        # CK usa nombres completos. Si edition es un código (ej: 'bok'), intentamos mapear.
        edition_full = edition
        common_sets = {
            "lea": "Limited Edition Alpha", "leb": "Limited Edition Beta", "2ed": "Unlimited Edition",
            "3ed": "Revised Edition", "4ed": "Fourth Edition", "5ed": "Fifth Edition",
            "bok": "Betrayers of Kamigawa", "chk": "Champions of Kamigawa", "sok": "Saviors of Kamigawa",
            "mrd": "Mirrodin", "dst": "Darksteel", "5dn": "Fifth Dawn",
            "rob": "Ravnica: City of Guilds", "gpt": "Guildpact", "dis": "Dissension",
            "inv": "Invasion", "pls": "Planeshift", "apc": "Apocalypse",
            "ody": "Odyssey", "tor": "Torment", "jud": "Judgment",
            "ons": "Onslaught", "lgn": "Legions", "scg": "Scourge"
        }
        if edition and edition.lower() in common_sets:
            edition_full = common_sets[edition.lower()]

        # 1. Búsqueda exacta (Nombre|Edición|Foil)
        foil_key = 'foil' if is_foil else 'non'
        if edition_full:
            # Intentar con el nombre resuelto
            key = f"{card_name}|{edition_full}|{foil_key}"
            if key in cache:
                return cache[key]
            
            # Intentar búsqueda insensible a mayúsculas
            search_key = key.lower()
            for k, price in cache.items():
                if k.lower() == search_key:
                    return price
            
            # Si el edition original también era algo distinto, intentarlo
            if edition and edition != edition_full:
                key_orig = f"{card_name}|{edition}|{foil_key}"
                if key_orig in cache: return cache[key_orig]

        # 2. Búsqueda por nombre (devuelve el primero que encuentre o el más barato)
        # Esto ayuda cuando el código de set de Scryfall no coincide exactamente con el nombre de edición de CK.
        matches = []
        c_name_lower = card_name.lower().strip()
        for key, price in cache.items():
            parts = key.split('|')
            if len(parts) < 3: continue
            k_name, k_ed, k_foil = parts
            if k_name.lower().strip() == c_name_lower and k_foil == foil_key:
                matches.append(float(price))
                
        if matches:
            # Ordenamos para obtener el más alto? No, el usuario quiere el que mejor coincida.
            # Sin edición exacta, devolvemos el más alto suele ser el más realista para retail.
            return max(matches)
                
        return None
    except Exception as e:
        print(f"Error al leer caché de CK: {e}")
        return None

if __name__ == "__main__":
    # Prueba manual
    download_pricelist()
    p = get_ck_price("Black Lotus", "Limited Edition Alpha")
    print(f"Precio de prueba: {p}")
