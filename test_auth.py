
import requests
import os
from dotenv import load_dotenv

load_dotenv('.env.local')

def test_auth():
    url = "http://localhost:8000/api/stats"
    # 1. Read what python thinks the password is
    password = os.environ.get("BASEMENT_PASSWORD")
    print(f"Server configured password (from local env): '{password}'")
    
    # 2. Send Request
    print(f"Sending request to {url} with X-BASEMENT-KEY: '{password}'")
    try:
        res = requests.get(url, headers={"X-BASEMENT-KEY": password})
        print(f"Status Code: {res.status_code}")
        print(f"Response: {res.text[:200]}...")
    except Exception as e:
        print(f"Request failed: {e}")

if __name__ == "__main__":
    test_auth()
