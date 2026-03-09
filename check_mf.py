import os, sys, requests
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import update_prices

token = update_prices.get_shopify_access_token()
headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}

query = """
{
  metafieldDefinitions(first: 10, ownerType: PRODUCT) {
    edges {
      node {
        name
        namespace
        key
        useAsCollectionCondition
        visibleToStorefrontApi
      }
    }
  }
}
"""

url = f"https://{update_prices.SHOPIFY_STORE_URL}/admin/api/2024-10/graphql.json"
response = requests.post(url, headers=headers, json={"query": query})
print(response.json())
