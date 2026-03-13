# image_server.py (ПОЛНАЯ И ФИНАЛЬНАЯ ВЕРСИЯ)
from fastapi import FastAPI, HTTPException, Request, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import logging
import uuid
import os
import random
import hashlib
import base64
import json
import time
import hmac
from urllib.parse import parse_qsl, urlencode
from dotenv import load_dotenv
import replicate
from deep_translator import GoogleTranslator
from pydantic import BaseModel, Field
from typing import List, Optional, Any, Dict # <--- ДОБАВЛЕНО
from typing import List, Optional
import database as db
import vk_api
from cachetools import TTLCache
from functools import wraps
import httpx
from fastapi import Response
from yookassa import Payment, Configuration # <--- Поднял импорт наверх!

# --- ПОДГОТОВКА И ЛОГИРОВАНИЕ ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
load_dotenv()

# Импорт логики генерации
from generation_logic import (
    generate_t2i, 
    generate_quick_edit,
    generate_vip_mix, 
    generate_i2v, 
    generate_t2v,
    generate_vip_clip, 
    generate_talking_photo,
    generate_chat_response, 
    generate_music, 
    generate_seadream_mix 
)

app = FastAPI(title="Neuro-Master API Brain")

# ✅ ШАГ 1: НАСТРОЙКА CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Конфигурация из .env
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
VK_TOKEN = os.getenv("VK_TOKEN")
VK_APP_SECRET = os.getenv("VK_SERVICE_KEY")
BOT_SECRET_TOKEN = os.getenv("BOT_SECRET_TOKEN")

# Настройки ЮKassa
Configuration.account_id = os.getenv("YUKASSA_SHOP_ID")
Configuration.secret_key = os.getenv("YUKASSA_SECRET_KEY")

# Инициализация сервисов
translator = GoogleTranslator(source='auto', target='en')
client = replicate.Client(api_token=REPLICATE_API_TOKEN)
vk_session = vk_api.VkApi(token=VK_TOKEN)
vk = vk_session.get_api()

# Очередь задач и кэш
tasks_queue = asyncio.Queue()
cache = TTLCache(maxsize=1000, ttl=1800)

# --- АДМИНКА ДЛЯ ВКОНТАКТЕ ---
async def send_admin_log(message: str):
    ADMIN_VK_ID = 233876992  
    try:
        safe_random_id = random.randint(1, 2147483647)
        await asyncio.to_thread(
            vk.messages.send,
            user_id=ADMIN_VK_ID,
            message=message,
            random_id=safe_random_id
        )
    except Exception as e:
        logging.error(f"Ошибка отправки лога в ВК: {e}")

# Стоимость услуг
COSTS = {
    "t2i": 1, "vip_edit": 1, "quick_edit": 2, "vip_mix": 3, "i2v": 3, "t2v": 5,
    "vip_clip": 10, "talking_photo": 10, "music": 2, "chat": 0,
    "seadream_mix": 3 
}

# --- Модели данных ---
class GenerationRequest(BaseModel):
    user_id: int
    model: str
    prompt: Optional[str] = None
    image_urls: List[str] = Field(default_factory=list) 
    audio_url: Optional[str] = None
    video_url: Optional[str] = None
    lyrics: Optional[str] = None
    style_prompt: Optional[str] = None

class ChatRequest(BaseModel):
    user_id: int
    prompt: str

class BonusRequest(BaseModel): 
    user_id: int

class YookassaRequest(BaseModel):
    user_id: int
    amount: int
    description: str

class PersonalAIRequest(BaseModel):
    user_id: int
    prompt: str 
    clear_history: bool = False 
    model_type: str = "llama3"

# --- СИСТЕМА ЗАЩИТЫ ---
def verify_safe_call(target_user_id: int, x_vk_sign: str = None, x_bot_token: str = None):
    if x_bot_token and x_bot_token == BOT_SECRET_TOKEN:
        return True
    
    if not x_vk_sign:
        raise HTTPException(status_code=403, detail="Missing Authorization Header")
        
    try:
        query_params = dict(parse_qsl(x_vk_sign, keep_blank_values=True))
        vk_sign = query_params.pop('sign', None)
        
        ordered_params = sorted(query_params.items())
        params_str = urlencode(ordered_params, safe=':/')
        
        secret_bytes = VK_APP_SECRET.encode('utf-8')
        params_bytes = params_str.encode('utf-8')
        decoded_hash = base64.b64encode(hmac.new(secret_bytes, params_bytes, hashlib.sha256).digest()).decode('utf-8')
        
        if decoded_hash.rstrip('=') != vk_sign.rstrip('=').replace('-', '+').replace('_', '/'):
            raise HTTPException(status_code=403, detail="Invalid VK signature")
            
        real_user_id = int(query_params.get('vk_user_id', 0))
        if real_user_id != target_user_id:
            raise HTTPException(status_code=403, detail="User identity mismatch")
            
    except Exception as e:
        raise HTTPException(status_code=403, detail="Authentication failed")

# --- ЭНДПОИНТЫ API ОСНОВНОГО БОТА ---
@app.on_event("startup")
async def startup_event():
    db.init_db()
    asyncio.create_task(worker())
    logging.info("🚀 Сервер Neuro-Master Brain запущен.")

@app.get("/api/user/{user_id}")
async def get_or_create_user(user_id: int, x_vk_sign: Optional[str] = Header(None), x_bot_token: Optional[str] = Header(None)):
    verify_safe_call(user_id, x_vk_sign, x_bot_token)
    balance = db.get_balance(user_id)
    if balance is None:
        db.add_user(user_id, username='user', initial_balance=5)
        balance = 5
        asyncio.create_task(send_admin_log(f"🥳 НОВЫЙ ПОЛЬЗОВАТЕЛЬ!\nVK ID: {user_id}\nВыдан баланс: {balance} кр."))
    return {"success": True, "balance": balance}

@app.post("/api/bonus")
async def give_welcome_bonus(request: BonusRequest, x_vk_sign: Optional[str] = Header(None)):
    verify_safe_call(request.user_id, x_vk_sign)
    balance = db.get_balance(request.user_id)
    if balance is not None and balance < 20: 
        db.update_balance(request.user_id, 5)
        asyncio.create_task(send_admin_log(f"🎁 Юзер {request.user_id} разрешил сообщения и получил +5 кр!"))
        return {"success": True}
    else:
        raise HTTPException(status_code=400, detail="Вы уже получали бонус или ваш баланс слишком высок.")

@app.post("/api/generate")
async def handle_unified_generation(request: GenerationRequest, x_vk_sign: Optional[str] = Header(None), x_bot_token: Optional[str] = Header(None)):
    verify_safe_call(request.user_id, x_vk_sign, x_bot_token)
    cost = COSTS.get(request.model)
    balance = db.get_balance(request.user_id)
    
    if cost is None:
        raise HTTPException(status_code=400, detail="Неизвестная модель генерации")
    if balance is None or balance < cost:
        raise HTTPException(status_code=402, detail="Недостаточно кредитов на балансе")
        
    db.update_balance(request.user_id, -cost)
    asyncio.create_task(send_admin_log(f"▶️ ЗАПУСК ГЕНЕРАЦИИ\nЮзер: {request.user_id}\nМодель: {request.model}\nЦена: {cost} кр."))
    
    task_id = str(uuid.uuid4())
    await tasks_queue.put({**request.dict(), "task_id": task_id})
    return {"success": True, "task_id": task_id}

@app.get("/api/task_status/{task_id}")
async def get_task_status(task_id: str, user_id: int, x_vk_sign: Optional[str] = Header(None), x_bot_token: Optional[str] = Header(None)):
    verify_safe_call(user_id, x_vk_sign, x_bot_token)
    if task_id in cache:
        result = cache[task_id]
        if result.get("user_id") != user_id:
            raise HTTPException(status_code=403, detail="Это не ваша задача")
        return result
    return {"success": True, "status": "pending"}

@app.post("/api/chat")
async def handle_chat(request: ChatRequest, x_vk_sign: Optional[str] = Header(None), x_bot_token: Optional[str] = Header(None)):
    verify_safe_call(request.user_id, x_vk_sign, x_bot_token)
    if len(request.prompt) > 2000:
        raise HTTPException(status_code=400, detail="Текст запроса превышает допустимый лимит (2000 символов).")
        
    balance = db.get_balance(request.user_id)
    if balance is None or balance < 1:
        raise HTTPException(status_code=402, detail="Для доступа к Нейро-Помощнику на балансе должно быть не менее 1 кр.")
        
    try:
        response_text = generate_chat_response(request.prompt, request.user_id, client)
        return {"success": True, "response": response_text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/download")
async def download_media(url: str):
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid URL")
    try:
        async with httpx.AsyncClient(timeout=60.0) as client_http:
            resp = await client_http.get(url)
            resp.raise_for_status()
            
        content_type = "image/jpeg"
        filename = "neuro_master_image.jpg"
        if url.endswith(".mp4"):
            content_type = "video/mp4"
            filename = "neuro_master_video.mp4"
        elif url.endswith(".mp3"):
            content_type = "audio/mpeg"
            filename = "neuro_master_audio.mp3"
            
        headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
        return Response(content=resp.content, media_type=content_type, headers=headers)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Не удалось скачать файл")

# --- СЕКРЕТНЫЙ ЛИЧНЫЙ ПОМОЩНИК (С БАЗОЙ ДАННЫХ И УМНЫМ ВЫБОРОМ МОДЕЛЕЙ) ---

# Класс Message уже определен в database.py, но FastAPI его требует в BaseModel
class Message(BaseModel):
    role: str
    content: str

class PersonalAIRequest(BaseModel):
    user_id: int
    prompt: str 
    clear_history: bool = False 
    model_type: str = "gpt4o_mini" # По умолчанию быстрый и дешевый
    attachments: Optional[List[str]] = [] # URL картинок для анализа

@app.post("/api/my_personal_ai")
async def handle_personal_ai(request: PersonalAIRequest):
    MY_SECRET_VK_ID = 233876992  
    
    # Исправление для мобильных: логгируем, если ID не совпал
    if request.user_id != MY_SECRET_VK_ID:
        logging.warning(f"Попытка доступа: {request.user_id}")
        return {"success": False, "error": "Доступ разрешен только админу."}

    if request.clear_history:
        db.clear_chat_history(request.user_id)
        return {"success": True, "response": "Память очищена! Я готов к новой задаче. 🧹"}
        
    try:
        db.save_chat_message(request.user_id, "user", request.prompt)
        # Берем последние 20 сообщений для контекста
        history_from_db = db.get_chat_history(request.user_id, limit=20)
        
        # --- УМНАЯ ЛОГИКА ВЫБОРА МОДЕЛИ ---
        chosen_model = request.model_type
        
        # Авто-определение кодинга (если есть ключевые слова)
        code_keywords = ["код", "rust", "python", "скрипт", "ошибка", "напиши функцию", "sql", "css"]
        if any(word in request.prompt.lower() for word in code_keywords):
            chosen_model = "gemini_31_pro"

        model_id = ""
        model_params = {"temperature": 0.7}

        # Настраиваем параметры под выбранную модель из твоего списка
        if chosen_model == "gemini_31_pro":
            model_id = "google/gemini-3.1-pro" # [cite: 1]
            model_params.update({
                "prompt": request.prompt,
                "thinking_level": "high", # Включаем глубокое мышление для кода [cite: 4]
                "max_output_tokens": 65535
            })
        elif chosen_model == "gemini_flash":
            model_id = "google/gemini-3-flash" # [cite: 58]
            model_params.update({
                "prompt": request.prompt,
                "max_output_tokens": 65535
            })
            # Если прислали фото — добавляем в Gemini 
            if request.attachments:
                model_params["images"] = [{"value": url} for url in request.attachments]
        else:
            model_id = "openai/gpt-4o-mini" # [cite: 151]
            model_params.update({
                "prompt": request.prompt,
                "max_completion_tokens": 4096
            })

        # Запуск нейросети через Replicate [cite: 4, 115]
        output = client.run(model_id, input=model_params)
        full_response = "".join(output)
        
        db.save_chat_message(request.user_id, "assistant", full_response)
        return {"success": True, "response": full_response}
        
    except Exception as e:
        logging.error(f"Ошибка ИИ: {e}")
        return {"success": False, "error": f"Ошибка: {str(e)}"}
        
# --- ИНТЕГРАЦИЯ ЮKASSA ДЛЯ ВК ---
@app.post("/api/yookassa/create-payment")
async def create_yookassa_payment(request: YookassaRequest, x_vk_sign: Optional[str] = Header(None)):
    try:
        credits_to_add = 15 if request.amount == 150 else 100
        if request.amount == 250: credits_to_add = 30
        
        payment = Payment.create({
            "amount": {"value": f"{request.amount}.00", "currency": "RUB"},
            "confirmation": {"type": "redirect", "return_url": "https://vk.com/app51884181"},
            "capture": True,
            "description": request.description,
            "metadata": {"user_id": request.user_id, "credits": credits_to_add}
        }, uuid.uuid4())
        
        return {"success": True, "payment_url": payment.confirmation.confirmation_url}
    except Exception as e:
        logging.error(f"Ошибка ЮKassa: {e}")
        raise HTTPException(status_code=500, detail="Ошибка кассы")

@app.post("/api/yookassa/webhook")
async def yookassa_webhook(request: Request):
    try:
        event_json = await request.json()
        if event_json.get("event") == "payment.succeeded":
            metadata = event_json.get("object", {}).get("metadata", {})
            user_id = metadata.get("user_id")
            credits_to_add = metadata.get("credits")
            
            if user_id and credits_to_add:
                db.update_balance(int(user_id), int(credits_to_add))
                asyncio.create_task(send_admin_log(f"💰 УСПЕШНАЯ ОПЛАТА!\nЮзер: {user_id}\nНачислено: {credits_to_add} кр."))
        return {"success": True}
    except Exception as e:
        return {"success": False}

# --- ВОРКЕР (СЕРДЦЕ СЕРВЕРА) ---
async def worker():
    while True:
        task = await tasks_queue.get()
        task_id = task.get("task_id")
        user_id = task.get("user_id")
        model = task.get("model")
        
        try:
            result_url = None
            if model == 't2i': result_url = generate_t2i(task['prompt'], client, translator, task.get('image_urls', []))
            elif model == 'quick_edit': result_url = generate_quick_edit(task['prompt'], task['image_urls'], client, translator)
            elif model == 'vip_mix': result_url = generate_vip_mix(task['prompt'], task['image_urls'], client, translator)
            elif model == 'seadream_mix': result_url = generate_seadream_mix(task['prompt'], task['image_urls'], client, translator)
            elif model == 'i2v': result_url = generate_i2v(task['prompt'], task['image_urls'][0], client, translator)
            elif model == 't2v': result_url = generate_t2v(task['prompt'], client, translator)
            elif model == 'vip_clip': result_url = generate_vip_clip(task['image_urls'][0], task['video_url'], client)
            elif model == 'talking_photo': result_url = generate_talking_photo(task['image_urls'][0], task['audio_url'], client)
            elif model == 'music': result_url = generate_music(task['lyrics'], task['style_prompt'], client, translator)
                
            cache[task_id] = {
                "success": True, "result_url": result_url, 
                "model": model, "user_id": user_id, "status": "ready"
            }
        except Exception as e:
            logging.error(f"Воркер ОШИБКА: {e}")
            cache[task_id] = {"success": False, "error": str(e), "user_id": user_id}
            db.update_balance(user_id, COSTS.get(model, 0))
        finally:
            tasks_queue.task_done()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("image_server:app", host="0.0.0.0", port=8001, workers=1)

