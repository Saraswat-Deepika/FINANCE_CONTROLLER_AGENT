import os
from dotenv import load_dotenv

load_dotenv()
if not os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY") == "your_gemini_api_key_here":
    print("WARNING: GEMINI_API_KEY is not set in .env properly. Test may fail.")

from engine.gemini_client import call_gemini

print("====== GEMINI STANDALONE TEST ======")
try:
    print("Sending prompt to Gemini...")
    result = call_gemini("Hello! Just say 'Test Successful' if you can read this.", is_json=False)
    print("\n--- RESPONSE ---")
    print(result)
    print("----------------")
except Exception as e:
    print("\n--- ERROR ---")
    print(str(e))
    print("-------------")
