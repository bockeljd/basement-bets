from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt
import os

from typing import Optional

security = HTTPBearer(auto_error=False)

SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET")

def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Security(security)):
    """
    Verifies the Supabase JWT and returns the user payload.
    """
    if not credentials:
        # If no token provided and we are in dev/no secret, allow fallback
        if not SUPABASE_JWT_SECRET:
             return {"sub": "00000000-0000-0000-0000-000000000000", "email": "dev@example.com"}
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = credentials.credentials
    try:
        if not SUPABASE_JWT_SECRET:
            # Fallback for dev if secret not provided
            return {"sub": "dev-user", "email": "dev@example.com"}
            
        payload = jwt.decode(
            token, 
            SUPABASE_JWT_SECRET, 
            algorithms=["HS256"], 
            options={"verify_aud": False}
        )
        return payload
    except Exception as e:
        raise HTTPException(
            status_code=401,
            detail=f"Could not validate credentials: {str(e)}"
        )
