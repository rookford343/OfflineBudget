# test_imports.py
try:
    import pandas as pd
    import keyring
    from cryptography.fernet import Fernet
    
    print("✅ pandas version:", pd.__version__)
    print("✅ keyring imported successfully")
    print("✅ cryptography imported successfully")
    print("All packages installed correctly!")
    
except ImportError as e:
    print("❌ Import error:", e)