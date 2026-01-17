import sys
import os

# Add the parent directory (project root) to sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.api import app

# Vercel looks for 'app' in this file to handle requests
