import json
import copy
import pandas 
# 定義配色與狀態文字
STYLE_CONFIG = {
    "SAFE": {
        "color": "#06C755",  # LINE Green
        "title": "✅ 安全連結",
        "risk_text": "低風險"
    },
    "WARNING": {
        "color": "#FFC107",  # Amber
        "title": "⚠️ 需謹慎",
        "risk_text": "中風險"
    },
    "DANGER": {
        "color": "#FF4B4B",  # Red
        "title": "🚫 疑似詐騙",
        "risk_text": "高風險"
    }
}

def create_fraud_check_flex(model_data: pandas.DataFrame, gemini_text, target_url):
    """
    根據模型資料生成 Flex Message
    """
    
    # 1. 解析資料
    is_fraud = model_data['is_fraud'][0]
    risk_level = model_data["risk_level"][0]
    confidence_score = model_data["confidence_score"][0]
    gemini_caption = gemini_text

    # 2. 決定顯示風格 (Safe / Warning / Danger)
    # 這裡可以根據你的業務邏輯調整，例如 risk_level == 'Medium' 走 WARNING
    if is_fraud or risk_level == "High":
        style = STYLE_CONFIG["DANGER"]
    elif risk_level == "Medium":
        style = STYLE_CONFIG["WARNING"]
    else:
        style = STYLE_CONFIG["SAFE"]

    # 格式化分數 (例如 0.012 -> 1.2)
    score_percent = f"{confidence_score * 100:.1f}"

    # 3. 讀取並替換 JSON 模板
    # 為了簡單演示，這裡使用字串取代 (String Replace)，
    # 實際專案中也可以讀取後用 Dict 操作，但字串取代對模板佔位符最直觀。
    try:
        with open('template.json', 'r', encoding='utf-8') as f:
            template_str = f.read()
            
        # 執行替換
        rendered_str = template_str.replace("{THEME_COLOR}", style["color"]) \
                                   .replace("{STATUS_TITLE}", style["title"]) \
                                   .replace("{RISK_LEVEL_TEXT}", style["risk_text"]) \
                                   .replace("{SCORE_PERCENT}", score_percent) \
                                   .replace("{GEMINI_TEXT}", gemini_caption) \
                                   .replace("{JOB_URL}", target_url)
        
        # 轉回 JSON 物件
        flex_bubble = json.loads(rendered_str)
        
        # 回傳完整的 Flex Message 格式
        return {
            "type": "flex",
            "altText": f"連結檢測結果：{style['risk_text']}",
            "contents": flex_bubble
        }
        
    except Exception as e:
        print(f"Error generating flex message: {e}")
        return None

# --- 模擬你的系統使用情境 ---

# 模擬資料輸入 (你的 Model output)
# model_output_example = {
#     "is_fraud": False,
#     "confidence_score": 0.012,
#     "risk_level": "Low"
# }

# gemini_text = f"這看起來很正常。公司名稱明確，工作內容描述詳細，且要求與金融業職位匹配。放心投遞。"

# # 產生 Flex Message
# flex_message = create_fraud_check_flex(model_output_example, gemini_text)

# # (給開發者看) 印出結果，你可以把這個 dict 丟給 line_bot_api.reply_message
# import pprint
# print("=== Generated Flex Message ===")
# # pprint.pprint(flex_message) 

# # 如果你需要測試 json 字串
# print(json.dumps(flex_message, ensure_ascii=False, indent=2))