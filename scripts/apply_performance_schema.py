
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from src.database import init_performance_objects

if __name__ == "__main__":
    init_performance_objects()
