import abc
import asyncio
from typing import Optional
import httpx
import logging

class Translator(abc.ABC):
    @abc.abstractmethod
    async def translate(self, text: str, source_lang: Optional[str] = None, target_lang: Optional[str] = None, context: Optional[str] = None) -> str:
        raise NotImplementedError

class HttpTranslator(Translator):
    def __init__(self, provider: str, api_key: Optional[str], timeout: float = 10.0, max_retries: int = 3):
        self.provider = provider
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self._client = httpx.AsyncClient(timeout=self.timeout)

    async def translate(self, text: str, source_lang: Optional[str] = None, target_lang: Optional[str] = None, context: Optional[str] = None) -> str:
        attempt = 0
        last_exc = None
        logger = logging.getLogger("tg-bot")
        while attempt < self.max_retries:
            try:
                if self.provider in ("openai", "qwen"):
                    # Use configurable base_url and model from settings
                    from config import settings
                    
                    base_url = settings.LLM_API_BASE
                    model = settings.LLM_MODEL
                    api_key = self.api_key or settings.LLM_API_KEY
                    
                    if not api_key:
                        raise ValueError("LLM_API_KEY is not set")

                    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
                    
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

                    if context:
                        sys_prompt += f"\n\nContext for this translation:\n{context}\n\nUse this context to resolve ambiguities, but only translate the user's text."

                    payload = {
                        "model": model,
                        "messages": [
                            {"role": "system", "content": sys_prompt},
                            {"role": "user", "content": text},
                        ],
                        "temperature": 0.3,
                    }
                    from config import settings as _st
                    endpoint = _st.LLM_API_ENDPOINT or f"{base_url.rstrip('/')}/chat/completions"
                    
                    r = await self._client.post(endpoint, headers=headers, json=payload)
                    r.raise_for_status()
                    data = r.json()
                    return data["choices"][0]["message"]["content"].strip()
                else:
                    raise RuntimeError("Unknown provider, please use qwen")
            except Exception as e:
                logger.error("translator attempt=%s error=%s", attempt, e)
                last_exc = e
                attempt += 1
                await asyncio.sleep(2 ** attempt)
        raise RuntimeError(f"Translation failed: {last_exc}")

class FallbackTranslator(Translator):
    def __init__(self):
        pass

    async def translate(self, text: str, source_lang: Optional[str] = None, target_lang: Optional[str] = None, context: Optional[str] = None) -> str:
        # Fallback to returning original text if API fails completely
        return text
