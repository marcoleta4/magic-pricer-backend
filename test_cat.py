import os, requests
from dotenv import load_dotenv

load_dotenv()
SHOPIFY_STORE_URL = os.environ.get("SHOPIFY_STORE_URL")
import update_prices

token = update_prices.get_shopify_access_token()
headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}

# The product I made a minute ago with GraphQL: 10269701701951
product_id = "10269701701951"

mf_url = f"https://{SHOPIFY_STORE_URL}/admin/api/2024-10/products/{product_id}/metafields.json"
mf_payload = {
    "metafield": {
        "namespace": "custom",
        "key": "scryfall_id",
        "value": "delayed-test",
        "type": "single_line_text_field"
    }
}
mf_res = requests.post(mf_url, headers=headers, json=mf_payload)
print(mf_res.status_code, mf_res.text)
