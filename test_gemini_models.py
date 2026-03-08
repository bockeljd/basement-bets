import requests
import os
import sys
from dotenv import load_dotenv

sys.path.append(os.getcwd())
load_dotenv('.env')

from src.services.profile_generator import ProfileGeneratorService

def main():
    profiler = ProfileGeneratorService()
    key = profiler.gemini_key
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"
    res = requests.get(url)
    if res.status_code == 200:
        for m in res.json().get('models', []):
            if 'gemini' in m['name'].lower():
                print(m['name'])
    else:
        print("Error:", res.status_code, res.text)

main()
