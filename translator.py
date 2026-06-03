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

INDIAN BANK NAMES, ABBREVIATIONS & IFSC PREFIXES:
When you encounter these abbreviations or IFSC prefixes in the text, you MUST understand they refer to the corresponding Indian Bank. Keep them in English (do not translate to Chinese). If it's a known abbreviation, you can keep it as is or expand it to the full bank name in English, but NEVER translate the bank name to Chinese.

[Public Sector Banks]
SBI / SBIN -> State Bank of India
PNB / PUNB -> Punjab National Bank
BOB / BARB -> Bank of Baroda
BOI / BKID -> Bank of India
CANARA / CNRB -> Canara Bank
UBI / UBIN -> Union Bank of India
INDIAN -> Indian Bank
CBI -> Central Bank of India
UCO -> UCO Bank
BOM -> Bank of Maharashtra
PSB -> Punjab & Sind Bank
IOB / IOBA -> Indian Overseas Bank

[Major Private Banks]
HDFC -> HDFC Bank
ICICI / ICIC -> ICICI Bank
AXIS / UTIB -> Axis Bank
KOTAK / KKBK -> Kotak Mahindra Bank
INDUS / INDB -> IndusInd Bank
IDFC / IDFB -> IDFC FIRST Bank
YES / YESB -> YES BANK
RBL / RATN -> RBL Bank
FED / FDRL -> Federal Bank
DCB / DCBL -> DCB Bank
CSB -> CSB Bank
KARUR / KVB -> Karur Vysya Bank
TMB -> Tamilnad Mercantile Bank
CUB -> City Union Bank
SIB -> South Indian Bank
NBL -> Nainital Bank
Bandhan Bank, Karnataka Bank, Dhanlaxmi Bank

[Small Finance Banks (SFB)]
AU / AUBL -> AU Small Finance Bank
UJJIVAN -> Ujjivan Small Finance Bank
EQUITAS -> Equitas Small Finance Bank
JANA -> Jana Small Finance Bank
UTKARSH / UTKS -> Utkarsh Small Finance Bank
ESAF / ESFB -> ESAF Small Finance Bank
SURYODAY -> Suryoday Small Finance Bank
FINCARE -> Fincare Small Finance Bank
SHIVALIK -> Shivalik Small Finance Bank
Unity Small Finance Bank, Capital Small Finance Bank, North East Small Finance Bank

[Payments Banks]
Airtel Payments Bank, India Post Payments Bank (IPPB), Fino Payments Bank, NSDL Payments Bank, Jio Payments Bank.

[Foreign & Rural Banks]
HSBC India, Standard Chartered, Citibank India, Deutsche Bank, DBS Bank, Bank of America, JPMorgan Chase, Barclays, BNP Paribas.
Andhra Pradesh Grameena Vikas Bank, Telangana Grameena Bank, Kerala Gramin Bank, etc.
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
