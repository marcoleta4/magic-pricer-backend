import requests
import json

url = "https://api.cardkingdom.com/api/v2/pricelist"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}
try:
    response = requests.get(url, headers=headers, timeout=30)
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Keys in response: {list(data.keys())}")
        raw_cards = data.get("data", [])
        if raw_cards:
            print("First card sample:")
            print(json.dumps(raw_cards[0], indent=2))
        else:
            print("No data found in 'data' field.")
    else:
        print(f"Response: {response.text[:500]}")
except Exception as e:
    print(f"Error: {e}")
