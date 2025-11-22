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

from utils import download_multiple
from typing import cast
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)



@asynccontextmanager
async def lifespan(app: FastAPI):
    BUCKET_NAME = "hsinchu-hackerthon-storage"
    
    # 定義 GCS 上的來源路徑 (這就是您原本的 FILES)
    # 假設 Bucket 裡面的結構是:
    # hsinchu-hackerthon-storage/model/fraud_detection_model.pth
    FILES_SOURCE = ["model/fraud_detection_model.pth", "model/scaler.pkl"]

    # 定義 Cloud Run 容器內的目標路徑 (必須在 /tmp 下)
    # 我們要把檔案存成:
    # /tmp/model/fraud_detection_model.pth
    # /tmp/model/scaler.pkl
    
    # 1. 先建立本地資料夾 (非常重要，否則下載會報錯 FileNotFoundError)
    os.makedirs("/tmp/model", exist_ok=True)

    # 2. 執行下載
    # 注意：這裡假設您的 download_multiple 可能需要修改，
    # 或者我們直接在這裡用 google-cloud-storage 套件寫一個簡單的迴圈比較保險
    from google.cloud import storage
    storage_client = storage.Client()
    bucket = storage_client.bucket(BUCKET_NAME)

    logger.info("Start downloading models to /tmp...")
    
    for blob_name in FILES_SOURCE:
        blob = bucket.blob(blob_name)
        # 組合本地絕對路徑: /tmp/ + blob_name
        destination_filename = f"/tmp/{blob_name}"
        
        logger.info(f"Downloading {blob_name} to {destination_filename}...")
        blob.download_to_filename(destination_filename)

    logger.info("Download finished.")

    # 3. 初始化 Predictor，使用 /tmp 下的路徑
    # 這裡要對應上面下載的 destination_filename
    app.state.predictor = FraudPredictor(
        model_path="/tmp/model/fraud_detection_model.pth", 
        scaler_path="/tmp/model/scaler.pkl"
    )
    
    logger.info("Init predictor success")
    yield  # 服務開始運行
    
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

    url_pattern = r'https?://www\.104\.com\.tw/job/[a-zA-Z0-9]+'
    
    match = re.search(url_pattern, user_text)

    if match:
        
        target_url = match.group(0)
        logger.info(f"Searching job info for target_url: {target_url}")
        job_data = process_job_url(target_url)
        
        #TODO threads

        if job_data.empty:
             reply = TextSendMessage(text="❌ 無法讀取職缺資料，請確認該職缺是否已下架。")
             line_bot_api.reply_message(event.reply_token, reply)
             return
        logger.info(f"Got job data for {target_url}")

        gemini_text = get_job_fraud_analysis(job_data.head(1)) 

        predictor = FraudPredictor()
        predict_risk = predictor.predict_csv(job_data)

        # line_bot_api.reply_message(event.reply_token, TextSendMessage(text=gemini_text))

        flex_payload = create_fraud_check_flex(predict_risk, gemini_text)
        
        
        if flex_payload:
            line_bot_api.reply_message(
                event.reply_token,
                FlexSendMessage(
                    alt_text=flex_payload["altText"],
                    contents=flex_payload["contents"]
                )
            )

    else:
        # 選項 B: 引導使用者 (適合一對一)
        reply_text = "請貼上 104 職缺連結 (例如: https://www.104.com.tw/job/xxxxx)，我會幫您分析風險。"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)