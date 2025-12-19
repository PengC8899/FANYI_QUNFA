import abc
import asyncio
from typing import Optional
import httpx
import logging

class Translator(abc.ABC):
    @abc.abstractmethod
    async def translate(self, text: str, source_lang: Optional[str] = None, target_lang: Optional[str] = None) -> str:
        raise NotImplementedError

class HttpTranslator(Translator):
    def __init__(self, provider: str, api_key: Optional[str], timeout: float = 10.0, max_retries: int = 3):
        self.provider = provider
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries

    async def translate(self, text: str, source_lang: Optional[str] = None, target_lang: Optional[str] = None) -> str:
        attempt = 0
        last_exc = None
        logger = logging.getLogger("tg-bot")
        while attempt < self.max_retries:
            try:
                if self.provider == "openai":
                    # Use configurable base_url and model from settings (passed via init if needed, or global)
                    # For now, let's assume this HttpTranslator is instantiated with specific args or uses settings
                    # But better to use the instance variables if we pass them.
                    # To keep it simple for now, we'll use settings import inside method or passed in __init__
                    # Let's import settings here to avoid circular dependency issues if any
                    from config import settings
                    
                    base_url = settings.LLM_API_BASE
                    model = settings.LLM_MODEL
                    api_key = self.api_key or settings.LLM_API_KEY
                    
                    if not api_key:
                        raise ValueError("LLM_API_KEY is not set")

                    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
                    
                    # Better system prompt for translation
                    sys_prompt = (
                        "You are a professional translation engine. "
                        "Translate the user's text to the target language directly. "
                        "Do not output any explanations, notes, or extra text. "
                        "If the text is already in the target language or consists only of emojis/numbers, return it as is."
                    )
                    if target_lang:
                        sys_prompt += f" Target Language: {target_lang.upper()}."
                    else:
                        sys_prompt += " Detect language automatically. If Chinese -> English; If English -> Chinese."

                    payload = {
                        "model": model,
                        "messages": [
                            {"role": "system", "content": sys_prompt},
                            {"role": "user", "content": text},
                        ],
                        "temperature": 0.3, # Slight flexibility for better fluency
                    }
                    from config import settings as _st
                    endpoint = _st.LLM_API_ENDPOINT or f"{base_url.rstrip('/')}/chat/completions"
                    
                    async with httpx.AsyncClient(timeout=self.timeout) as client:
                        r = await client.post(endpoint, headers=headers, json=payload)
                        r.raise_for_status()
                        data = r.json()
                        return data["choices"][0]["message"]["content"].strip()
                        
                elif self.provider == "deepl":
                    endpoint = "https://api.deepl.com/v2/translate"
                    if self.api_key and self.api_key.endswith(":fx"):
                        endpoint = "https://api-free.deepl.com/v2/translate"
                    async with httpx.AsyncClient(timeout=self.timeout) as client:
                        logger.info("deepl request endpoint=%s target=%s source=%s", endpoint, (target_lang or "EN").upper(), source_lang)
                        payload = {
                            "auth_key": self.api_key,
                            "text": text,
                            "target_lang": (target_lang or "EN").upper(),
                        }
                        if source_lang:
                            payload["source_lang"] = source_lang.upper()
                            
                        r = await client.post(
                            endpoint,
                            data=payload,
                        )
                        r.raise_for_status()
                        data = r.json()
                        return data["translations"][0]["text"].strip()
                elif self.provider == "google":
                    raise RuntimeError("Google provider not implemented. Use openai/deepl or extend.")
                else:
                    raise RuntimeError("Unknown provider")
            except Exception as e:
                logger.error("translator attempt=%s error=%s", attempt, e)
                last_exc = e
                attempt += 1
                await asyncio.sleep(2 ** attempt)
        raise RuntimeError(f"Translation failed: {last_exc}")

class FallbackTranslator(Translator):
    def __init__(self):
        pass

    async def translate(self, text: str, source_lang: Optional[str] = None, target_lang: Optional[str] = None) -> str:
        zh_map = {
            "你好": "hello",
            "谢谢": "thank you",
            "是": "is",
            "我": "I",
            "你": "you",
            "他": "he",
            "她": "she",
            "我们": "we",
            "好": "good",
            "不": "not",
            "请": "please",
        }
        en_map = {
            "hello": "你好",
            "thank": "谢谢",
            "you": "你",
            "is": "是",
            "i": "我",
            "he": "他",
            "she": "她",
            "we": "我们",
            "good": "好",
            "not": "不",
            "please": "请",
        }
        if target_lang == "en":
            out = text
            for k, v in zh_map.items():
                out = out.replace(k, v)
            return out
        if target_lang == "zh":
            words = text.split()
            res = []
            for w in words:
                lw = w.lower()
                res.append(en_map.get(lw, w))
            return "".join(res)
        return text
