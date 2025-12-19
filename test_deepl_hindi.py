import asyncio
import httpx

API_KEY = "0535f51b-d7b4-4855-9d28-959217727b3d:fx"
TEXT = "Kya keh rahe bhai"

async def test():
    endpoint = "https://api-free.deepl.com/v2/translate"
    print(f"Testing DeepL API with text: {TEXT}")
    async with httpx.AsyncClient() as client:
        # Test 1: No source_lang (Auto)
        print("\n--- Test 1: Auto Detect ---")
        try:
            r = await client.post(
                endpoint,
                data={
                    "auth_key": API_KEY,
                    "text": TEXT,
                    "target_lang": "ZH",
                },
            )
            print(f"Status: {r.status_code}")
            print(f"Response: {r.text}")
        except Exception as e:
            print(f"Error: {e}")

        # Test 2: source_lang=EN
        print("\n--- Test 2: Force EN ---")
        try:
            r = await client.post(
                endpoint,
                data={
                    "auth_key": API_KEY,
                    "text": TEXT,
                    "target_lang": "ZH",
                    "source_lang": "EN"
                },
            )
            print(f"Status: {r.status_code}")
            print(f"Response: {r.text}")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test())
