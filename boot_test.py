"""
Quick boot test: import api_enhanced without actually running uvicorn,
just to see what fails at import time.
"""
import sys, traceback

try:
    import api_enhanced
    print("IMPORT OK - app created:", api_enhanced.app.title)
except SystemExit as e:
    print("SystemExit:", e)
except Exception as e:
    print("IMPORT ERROR:")
    traceback.print_exc()
