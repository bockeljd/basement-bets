import os
import requests
import time
from src.config import settings

def generate_content(
    model: str,
    system_prompt: str,
    json_mode: bool = False,
    max_tokens: int = 1024,
    retries: int = 5,
    timeout: int = 25,
    max_wait_sec: float = 12.0,
) -> str:
    # Read key at call time so Vercel env vars injected after cold-start are always current.
    api_key = os.environ.get("GEMINI_API_KEY") or settings.GEMINI_API_KEY
    if not api_key:
        error_msg = "GEMINI_API_KEY not set."
        if settings.is_prod or settings.is_preview:
            error_msg += " CRITICAL: Missing from Vercel Dashboard. Please add GEMINI_API_KEY to Environment Variables and REDEPLOY."
        raise ValueError(error_msg)

    in_vercel = bool(os.environ.get("VERCEL") or settings.is_prod or settings.is_preview)
    if in_vercel:
        retries = min(int(retries), 2)
        timeout = min(int(timeout), 20)

    # Map legacy retired 1.5 names to supported fast 2.5 models; preserve modern names verbatim.
    if model in ["gemini-1.5-flash", "gemini-1.5-flash-latest", "gemini-flash-latest"]:
        model = "gemini-2.5-flash-lite"
    elif model in ["gemini-1.5-pro", "gemini-1.5-pro-latest", "gemini-pro-latest"]:
        model = "gemini-2.5-pro"

    fallback_model = "gemini-2.5-flash-lite" if model != "gemini-2.5-flash-lite" else None

    def _build_url(m: str) -> str:
        m_path = m if m.startswith("models/") else f"models/{m}"
        return f"https://generativelanguage.googleapis.com/v1beta/{m_path}:generateContent?key={api_key}"

    payload = {
        "contents": [{
            "parts": [{"text": system_prompt}]
        }],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": max_tokens
        }
    }

    if json_mode:
        payload["generationConfig"]["responseMimeType"] = "application/json"

    slept_total = 0.0
    current_model = model
    for attempt in range(max(1, int(retries))):
        try:
            resp = requests.post(_build_url(current_model), json=payload, timeout=timeout)

            # On 404 for an unavail model alias, fall back once immediately without sleeping.
            if resp.status_code == 404 and fallback_model and current_model != fallback_model:
                print(f"[Gemini API] 404 for {current_model}; falling back to {fallback_model}")
                current_model = fallback_model
                continue

            # 429: Too Many Requests / Quota Exceeded
            if resp.status_code == 429:
                error_body = resp.json() if resp.text else {}
                msg = str(error_body.get('error', {}).get('message', '')).lower()
                if "daily" in msg:
                    raise RuntimeError(f"GEMINI_QUOTA_EXHAUSTED: {msg}")
                if attempt < retries - 1:
                    wait_s = min(2.0 if in_vercel else 15.0 * (2 ** attempt), max(0.0, max_wait_sec - slept_total))
                    if wait_s > 0.2:
                        time.sleep(wait_s)
                        slept_total += wait_s
                        continue
                resp.raise_for_status()

            if resp.status_code >= 400:
                print(f"[Gemini API Error] {resp.status_code} ({current_model}) - {resp.text[:300]}")
                # Non-429 4xx client/auth/model errors are non-retryable — fail fast.
                if 400 <= resp.status_code < 500:
                    resp.raise_for_status()

            resp.raise_for_status()
            data = resp.json()
            try:
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                return text if text is not None else ""
            except (KeyError, IndexError):
                return ""

        except requests.exceptions.RequestException as e:
            status_code = getattr(getattr(e, "response", None), "status_code", None)
            if status_code is not None and 400 <= int(status_code) < 500 and int(status_code) != 429:
                raise e
            if attempt < retries - 1:
                wait_s = min(1.5 if in_vercel else 10.0 * (2 ** attempt), max(0.0, max_wait_sec - slept_total))
                if wait_s > 0.2:
                    time.sleep(wait_s)
                    slept_total += wait_s
                    continue
            raise e
        except (KeyError, IndexError) as e:
            if attempt < retries - 1:
                time.sleep(1)
                continue
            raise ValueError(f"Unexpected Gemini response format: {resp.json() if 'resp' in locals() else str(e)}")

def embed_content(
    model: str,
    content: str,
    title: str = None,
    task_type: str = "RETRIEVAL_QUERY",
    retries: int = 3,
    timeout: int = 12,
    max_wait_sec: float = 8.0,
) -> list[float]:
    api_key = os.environ.get('GEMINI_API_KEY') or settings.GEMINI_API_KEY
    if not api_key:
        raise ValueError("GEMINI_API_KEY not set")

    in_vercel = bool(os.environ.get("VERCEL") or settings.is_prod or settings.is_preview)
    if in_vercel:
        retries = min(int(retries), 2)
        timeout = min(int(timeout), 10)

    # Standardize embedding model
    if "embedding" not in model:
        model = "text-embedding-004"

    model_path = model if model.startswith("models/") else f"models/{model}"
    url = f"https://generativelanguage.googleapis.com/v1beta/{model_path}:embedContent?key={api_key}"

    payload = {
        "model": model_path,
        "content": {"parts": [{"text": content}]},
        "taskType": task_type
    }

    if title:
        payload["title"] = title

    slept_total = 0.0
    for attempt in range(max(1, int(retries))):
        try:
            resp = requests.post(url, json=payload, timeout=timeout)
            if resp.status_code == 429 and attempt < retries - 1:
                wait_s = min(1.5 if in_vercel else 15.0 * (2 ** attempt), max(0.0, max_wait_sec - slept_total))
                if wait_s > 0.2:
                    time.sleep(wait_s)
                    slept_total += wait_s
                    continue
            resp.raise_for_status()
            data = resp.json()
            return data["embedding"]["values"]
        except requests.exceptions.RequestException as e:
            status_code = getattr(getattr(e, "response", None), "status_code", 500)
            if attempt < retries - 1 and (status_code >= 500 or status_code == 429):
                wait_s = min(1.5 if in_vercel else 15.0 * (2 ** attempt), max(0.0, max_wait_sec - slept_total))
                if wait_s > 0.2:
                    time.sleep(wait_s)
                    slept_total += wait_s
                    continue
            raise e
