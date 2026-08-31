import requests

CLIENT_ID = "5ea0256b-98c5-48d6-a3de-09fc6fdafaaa_9c5f7d90-674a-43fc-918a-e82444d2341e"
CLIENT_SECRET = "yHFKFA7wkiXLrqGKDB9B57UU0xkUxTHPFzF2CtIVA38="

TOKEN_URL = "https://icdaccessmanagement.who.int/connect/token"

data = {
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "grant_type": "client_credentials",
    "scope": "icdapi_access"
}

headers = {
    "Content-Type": "application/x-www-form-urlencoded"
}

response = requests.post(
    TOKEN_URL,
    data=data,
    headers=headers,
    timeout=30
)

print("Status:", response.status_code)
print("Response:", response.text)

if response.status_code == 200:

    token = response.json()["access_token"]

    print("\nSUCCESS!")
    print("Access token received.")