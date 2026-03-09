import requests
import json
import os
import time
import gc

CACHE_FILE = "ck_cache.json"
CK_API_URL = "https://api.cardkingdom.com/api/v2/pricelist"

def download_pricelist():
    url = "https://api.cardkingdom.com/api/v2/pricelist"
    print(f"Downloading Card Kingdom pricelist from {url}...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    try:
        # 1. Descargar a archivo temporal para no agotar la RAM
        temp_raw_file = "ck_raw.json"
        print(f"Streaming Card Kingdom pricelist to {temp_raw_file}...")
        
        with requests.get(url, headers=headers, timeout=60, stream=True) as r:
            r.raise_for_status()
            with open(temp_raw_file, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        
        print(f"Descarga finalizada. Procesando archivo de {os.path.getsize(temp_raw_file)} bytes...")
        
        # 2. Cargar y procesar (usamos una carga controlada si es posible)
        with open(temp_raw_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Borrar el archivo raw inmediatamente para liberar espacio
        if os.path.exists(temp_raw_file):
            os.remove(temp_raw_file)
        
        gc.collect() # Forzar liberación de memoria del buffer de lectura

        raw_cards = []
        if isinstance(data, dict):
            raw_cards = data.get("data", [])
        elif isinstance(data, list):
            raw_cards = data
        
        # Liberar data original si es posible
        del data
        gc.collect()
        
        # 3. Construir caché optimizado
        processed_cache = {}
        for i, card in enumerate(raw_cards):
            name = card.get("name") or card.get("nm")
            edition = card.get("edition")
            # El screenshot muestra "price_retail"
            price = card.get("price_retail") or card.get("sell_price") or card.get("price")
            sf_id = card.get("scryfall_id")
            
            if name and price:
                is_foil = str(card.get("is_foil")).lower() == "true" or card.get("is_foil") is True
                foil_key = 'foil' if is_foil else 'non'
                
                # Guardamos por nombre/edicion (legacy)
                key_name = f"{name.strip()}|{edition.strip() if edition else ''}|{foil_key}"
                processed_cache[key_name] = float(price)
                
                # Guardamos por scryfall_id (exacto!)
                if sf_id:
                    key_id = f"sfid:{sf_id}|{foil_key}"
                    processed_cache[key_id] = float(price)
        
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(processed_cache, f)
        
        print(f"Sincronización CK exitosa: {len(processed_cache)} entradas.")
        return True
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
        
        foil_key = 'foil' if is_foil else 'non'

        # 0. Búsqueda por Scryfall ID
        # name puede ser un scryfall_id si viene con el prefijo sfid:
        if card_name.startswith("sfid:"):
            key_id = f"{card_name}|{foil_key}"
            if key_id in cache: 
                return cache[key_id]

        # 1. Resolución de nombre de edición (Set Code -> Full Name)
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
