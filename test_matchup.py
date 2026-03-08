import asyncio
import os
import sys

sys.path.append(os.getcwd())

from src.services.profile_generator import ProfileGeneratorService

def main():
    print("Starting test...")
    profiler = ProfileGeneratorService()
    print("Profiler instantiated.")
    try:
        print("Calling generate_matchup_analysis...")
        analysis = profiler.generate_matchup_analysis("Purdue", "Duke")
        print("Analysis generated!")
        print(analysis)
    except Exception as e:
        import traceback
        traceback.print_exc()
    print("Test complete.")

main()
