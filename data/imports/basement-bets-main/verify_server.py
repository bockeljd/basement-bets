import requests
import time
import sys

def check_endpoint(name, url):
    try:
        start = time.time()
        resp = requests.get(url, timeout=2)
        elapsed = time.time() - start
        if resp.status_code == 200:
            print(f"[PASS] {name}: {url} ({elapsed:.3f}s)")
            return True
        else:
            print(f"[FAIL] {name}: {url} (Status: {resp.status_code})")
            return False
    except Exception as e:
        print(f"[FAIL] {name}: {url} (Error: {e})")
        return False

def main():
    print("=== Basement Bets Server Verification ===")
    
    # Check 1: Backend Root
    backend_ok = check_endpoint("Backend Root", "http://localhost:8000/")
    
    # Check 2: API Stats
    api_ok = check_endpoint("API Stats", "http://localhost:8000/api/stats")
    
    # Check 3: Frontend (Vite)
    frontend_ok = check_endpoint("Frontend Root", "http://localhost:5173/")
    
    if backend_ok and api_ok and frontend_ok:
        print("\nAll systems operational.")
        sys.exit(0)
    else:
        print("\nSome systems are down.")
        sys.exit(1)

if __name__ == "__main__":
    main()
