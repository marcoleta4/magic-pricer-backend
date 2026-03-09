import os, requests
from dotenv import load_dotenv

load_dotenv()
SHOPIFY_STORE_URL = os.environ.get("SHOPIFY_STORE_URL")
import update_prices

token = update_prices.get_shopify_access_token()
headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}

query = """
{
  __type(name: "ProductInput") {
    inputFields {
      name
      type {
        name
        kind
      }
    }
  }
}
"""

url = f"https://{SHOPIFY_STORE_URL}/admin/api/2024-10/graphql.json"
response = requests.post(url, headers=headers, json={"query": query})
print(response.json())
