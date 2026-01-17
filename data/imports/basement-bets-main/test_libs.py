try:
    import cbbdata.data as cbb
    print("cbbdata imported successfully.")
    # Try a simple fetch
    # According to docs (or assumption), maybe cbb.get_barttorvik_ratings?
    # User said "The Library: cbbdata".
    # I'll try to find a function.
    print("Dir:", dir(cbb))
except Exception as e:
    print(f"Error importing cbbdata: {e}")

try:
    import nfl_data_py as nfl
    print("nfl_data_py imported.")
except Exception as e:
    print(f"Error nfl: {e}")
