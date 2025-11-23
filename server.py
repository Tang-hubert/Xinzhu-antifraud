from contextlib import asynccontextmanager
import re
import os
from fastapi import FastAPI, Request, HTTPException
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FlexSendMessage

from config import line_bot_api, handler
from services.process_job_link import process_job_url
from services.predict import FraudPredictor
from services.gemini_explain_risk import get_job_fraud_analysis
from services.message_builder import create_fraud_check_flex
from scrape_threads_link import scrape_threads_from_inputs
# 移除 utils 的引用，直接在 lifespan 處理，避免 utils 裡面有額外依賴導致報錯
# from utils import download_multiple 
from typing import cast
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    BUCKET_NAME = "hsinchu-hackerthon-storage"
    FILES_SOURCE = ["model/fraud_detection_model.pth", "model/scaler.pkl"]
    
    # 確保 /tmp 存在
    os.makedirs("/tmp/model", exist_ok=True)

    # 在這裡 import，確保只有執行時需要
    from google.cloud import storage
    
    # 使用 Application Default Credentials (Cloud Run 會自動抓)
    storage_client = storage.Client()
    bucket = storage_client.bucket(BUCKET_NAME)

    logger.info("Start downloading models to /tmp...")
    
    for blob_name in FILES_SOURCE:
        blob = bucket.blob(blob_name)
        destination_filename = f"/tmp/{blob_name}"
        
        # 檢查檔案是否已存在 (加速重啟速度)
        if not os.path.exists(destination_filename):
            logger.info(f"Downloading {blob_name} to {destination_filename}...")
            blob.download_to_filename(destination_filename)
        else:
            logger.info(f"File {destination_filename} already exists, skipping download.")

    logger.info("Download finished.")

    # 初始化 Predictor，指定 /tmp 路徑
    app.state.predictor = FraudPredictor(
        model_path="/tmp/model/fraud_detection_model.pth", 
        scaler_path="/tmp/model/scaler.pkl"
    )
    
    logger.info("Init predictor success")
    yield
    
    # 清理資源
    del app.state.predictor
    logger.info("Terminated")
    
app = FastAPI(title="Job Scam Detector", lifespan=lifespan)

@app.get("/")
async def root():
    return {"message": "Job Scam Detector Running"}

@app.post("/webhook")
async def webhook(request: Request):
    body = await request.body()
    signature = request.headers.get("X-Line-Signature", "")
    try:
        handler.handle(body.decode(), signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    return "OK"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_text = event.message.text.strip()

    url_pattern_104 = r'https?://www\.104\.com\.tw/job/[a-zA-Z0-9]+'
    match_104 = re.search(url_pattern_104, user_text)

    url_pattern_threads = r'https?://www\.threads\.com/@[a-zA-Z0-9_.-]/post/[a-zA-Z0-9]+'
    match_threads = re.search(url_pattern_threads, user_text)

    if match_104 or match_threads:
        if match_104:
            search_104(event, match_104)
        elif match_threads:
            search_threads(event, match_threads, url=user_text)

def search_104(event, match: re.Match[str]):
    target_url = match.group(0)
    logger.info(f"Searching job info for target_url: {target_url}")
    job_data = process_job_url(target_url)
    
    if job_data.empty:
         reply = TextSendMessage(text="❌ 無法讀取職缺資料，請確認該職缺是否已下架。")
         line_bot_api.reply_message(event.reply_token, reply)
         return
    logger.info(f"Got job data for {target_url}")

    # 1. 取得 Gemini 分析
    gemini_text = get_job_fraud_analysis(job_data.head(1)) 

    # 2. 使用 lifespan 初始化好的 predictor (修正重點！)
    # 不要 new FraudPredictor()，而是用 app.state.predictor
    predictor = cast(FraudPredictor, app.state.predictor)
    predict_risk = predictor.predict_csv(job_data)

    # 3. 建立 Flex Message
    flex_payload = create_fraud_check_flex(predict_risk, gemini_text, target_url)
    
    if flex_payload:
        line_bot_api.reply_message(
            event.reply_token,
            FlexSendMessage(
                alt_text=flex_payload["altText"],
                contents=flex_payload["contents"]
            )
        )
    else:
        reply_text = "請貼上 104 職缺連結 (例如: https://www.104.com.tw/job/xxxxx)，我會幫您分析風險。"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

def search_threads(event, match: re.Match[str], url):
    outputs = scrape_threads_from_inputs([url])
    if outputs:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=outputs[0]["fraud_analysis"])
        )
    else:
        reply_text = "請貼上 threads 連結 (例如: https://www.threads.com/post/xxxxx)，我會幫您分析風險。"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
    pass

if __name__ == "__main__":
    import uvicorn
    # 為了本地測試方便，加入 PORT 判斷
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)