import os
import time
import json
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY", "")

if api_key and api_key != "your_gemini_api_key_here":
    client = genai.Client(api_key=api_key)
    MODEL_NAME = "gemini-3.6-flash"
else:
    client = None

# Global timestamp for rate limiting
last_call_time = 0

def call_gemini(prompt, is_json=False, temperature=0.2):
    global last_call_time
    
    if not client:
        raise Exception("Gemini API Key missing or invalid")
        
    # Rate limiting: wait if last call was < 3 seconds ago
    current_time = time.time()
    time_since_last = current_time - last_call_time
    if time_since_last < 3.0:
        sleep_time = 3.0 - time_since_last
        print(f"[Gemini Client] Rate limit throttle: Waiting {sleep_time:.2f}s...")
        time.sleep(sleep_time)
        
    mime_type = "application/json" if is_json else "text/plain"
    gen_config = types.GenerateContentConfig(
        response_mime_type=mime_type,
        temperature=temperature
    )
    
    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            print(f"[Gemini Client] Attempt {attempt + 1}/{max_attempts}...")
            
            # Update last call time just before calling
            last_call_time = time.time()
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=gen_config
            )
            
            content = response.text.strip()
            
            if is_json:
                start = content.find('[')
                end = content.rfind(']')
                if start != -1 and end != -1:
                    content = content[start:end+1]
                else:
                    start_dict = content.find('{')
                    end_dict = content.rfind('}')
                    if start_dict != -1 and end_dict != -1:
                        content = content[start_dict:end_dict+1]
                    else:
                        content = content.replace("```json", "").replace("```", "").strip()
                
                parsed_json = json.loads(content)
                print("[Gemini Client] SUCCESS (JSON parsed)")
                return parsed_json
            else:
                print("[Gemini Client] SUCCESS (Text returned)")
                return content
                
        except Exception as e:
            print(f"[Gemini Client] FAILED on attempt {attempt + 1}: {str(e)}")
            if attempt < max_attempts - 1:
                sleep_dur = 2 if attempt == 0 else 4
                print(f"[Gemini Client] Retrying in {sleep_dur} seconds...")
                time.sleep(sleep_dur)
            else:
                print("[Gemini Client] Exhausted all retries.")
                raise e
