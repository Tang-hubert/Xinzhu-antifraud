import os
import json
import pandas as pd
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

def get_job_fraud_analysis(job_data, api_key: str = None) -> str:
    """
    分析職缺是否有詐騙疑慮 (已加入防呆機制，可接受 DataFrame/Series/Dict)
    """
    
    # 1. 資料格式防呆處理 (自動轉成 dict)
    # 如果傳入的是 Pandas DataFrame (例如 df.iloc[[0]])
    if isinstance(job_data, pd.DataFrame):
        if len(job_data) > 1:
            print("⚠️ 警告：傳入了多筆資料，只取第一筆進行分析。")
        # 將第一筆轉為 dict
        job_data = job_data.iloc[0].to_dict()
        
    # 如果傳入的是 Pandas Series (例如 df.iloc[0] 或是 row)
    elif isinstance(job_data, pd.Series):
        job_data = job_data.to_dict()

    # 2. 設定 API Key
    final_api_key = api_key or os.getenv("GEMINI_API_KEY")
    if not final_api_key:
        return "❌ 錯誤：找不到 API Key。"
    
    try:
        genai.configure(api_key=final_api_key)
        model = genai.GenerativeModel('gemini-2.0-flash')
    except Exception as e:
        return f"❌ 模型設定錯誤：{e}"

    # 3. 轉 JSON 字串 (加入 default=str 以防 Timestamp 或 NaN 報錯)
    try:
        # default=str 可以解決日期格式或特殊物件無法序列化的問題
        job_text = json.dumps(job_data, ensure_ascii=False, default=str)
    except Exception as e:
        return f"❌ 資料格式錯誤無法解析: {e}"

    prompt = f"""
    你是一名專業的求職詐騙分析師。請根據這筆職缺資料進行判斷：
    {job_text}

    請嚴格遵守以下「輸出格式」，只能回覆三句話 (繁體中文)：
    1. 第一句：直接下結論 (例如：這看起來很正常 / 這高機率是詐騙)。
    2. 第二句：指出判斷依據 (例如：公司知名且描述具體 / 薪資高得不合理且描述模糊)。
    3. 第三句：給予行動建議 (例如：放心投遞 / 千萬別去)。

    不要使用列點符號，不要換行，直接給出這三句話。
    """

    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f"❌ 分析過程發生錯誤：{e}"