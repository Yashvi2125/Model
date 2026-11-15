import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(override=True)

api_key = os.getenv("GEMINI_API_KEY")
print(f"Checking Gemini connection with key: {api_key[:10]}...")

client = OpenAI(
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    api_key=api_key,
    timeout=15.0,
)

candidate_models = [
    "gemini-3.5-flash",
    "gemini-3.7-flash",
    "gemini-2.5-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-2.5-pro",
    "gemini-3.8-flash",
    "gemini-flash-latest",
]

print("\nTesting available models...")
working_model = None

for model in candidate_models:
    print(f"Testing {model}...", end=" ", flush=True)
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Hello, reply with 3 words"}],
        )
        reply = response.choices[0].message.content.strip()
        print(f"SUCCESS! -> \"{reply}\"")
        working_model = model
        break
    except Exception as e:
        status = getattr(e, "status_code", None)
        msg = e.response.text if hasattr(e, "response") and e.response else str(e)
        if status:
            print(f"FAILED (HTTP {status})")
        else:
            print(f"FAILED: {msg[:100]}")

if working_model:
    print(f"\n Recommended working model: {working_model}")
    print(f"Updating your .env with GEMINI_MODEL={working_model}...")
    
    # Read current .env
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        with open(env_path, "w", encoding="utf-8") as f:
            for line in lines:
                if line.startswith("GEMINI_MODEL="):
                    f.write(f"GEMINI_MODEL={working_model}\n")
                else:
                    f.write(line)
        print(" .env successfully updated!")
        print(f"\nYou can now run: python main.py")
else:
    print("\nNo models succeeded. Please check your internet connection or Google AI Studio key.")
