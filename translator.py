import abc
import asyncio
from typing import Optional
import httpx
import logging

BUSINESS_CONTEXT = """
You are a professional translation engine specializing in financial, payment, and banking terms in the Indian market.
Translate the user's text to the target language directly.
Do not output any explanations, notes, or extra text.
If the text is already in the target language or consists only of emojis/numbers, return it as is.

IMPORTANT DOMAIN KNOWLEDGE & TERMINOLOGY:
1. Core Business: Renting/buying Indian bank cards (Visa/Mastercard) for online payments (gaming/stock funds).
2. Key terms that MUST remain in English (DO NOT translate them to Chinese, keep them exactly as they are):
   - USDT, F2F (Face-to-Face), Visa, Mastercard, IOB, UPI, MQR.
   - Enterprise, Company, Trade, Pvt Ltd, lakh (or lakhs).

INDIAN BANK NAMES (DO NOT TRANSLATE, KEEP EXACTLY AS WRITTEN):
- Public Sector Banks: State Bank of India (SBI), Punjab National Bank (PNB), Bank of Baroda (BOB), Canara Bank, Union Bank of India, Indian Bank, Bank of India (BOI), Central Bank of India, UCO Bank, Bank of Maharashtra, Punjab & Sind Bank, Indian Overseas Bank (IOB).
- Major Private Banks: HDFC Bank, ICICI Bank, Axis Bank, Kotak Mahindra Bank, IndusInd Bank, IDFC FIRST Bank, YES BANK, RBL Bank, Federal Bank, DCB Bank, Bandhan Bank, South Indian Bank, Karnataka Bank, Karur Vysya Bank (KVB), Tamilnad Mercantile Bank (TMB), City Union Bank (CUB), CSB Bank, Dhanlaxmi Bank, Nainital Bank.
- Small Finance Banks: AU Small Finance Bank, Ujjivan Small Finance Bank, Equitas Small Finance Bank, Jana Small Finance Bank, Utkarsh Small Finance Bank, ESAF Small Finance Bank, Suryoday Small Finance Bank, Unity Small Finance Bank, Capital Small Finance Bank, North East Small Finance Bank, Fincare Small Finance Bank, Shivalik Small Finance Bank.
- Payments Banks: Airtel Payments Bank, India Post Payments Bank (IPPB), Fino Payments Bank, NSDL Payments Bank, Jio Payments Bank.
- Foreign Banks: HSBC India, Standard Chartered Bank, Citibank India, Deutsche Bank India, DBS Bank India, Bank of America India, JPMorgan Chase India, Barclays Bank India, BNP Paribas India, Credit Agricole India.
- Regional Rural Banks: Andhra Pradesh Grameena Vikas Bank, Andhra Pragathi Grameena Bank, Telangana Grameena Bank, Karnataka Gramin Bank, Kerala Gramin Bank, Maharashtra Gramin Bank, Punjab Gramin Bank, Uttar Bihar Gramin Bank, Baroda UP Bank, Uttarakhand Gramin Bank.
"""

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
                    
                    sys_prompt = BUSINESS_CONTEXT
                    if target_lang:
                        sys_prompt += f"\nTarget Language: {target_lang.upper()}."
                    else:
                        sys_prompt += "\nDetect language automatically. If Chinese -> English; If English -> Chinese."

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
