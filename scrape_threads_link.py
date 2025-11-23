import sys
import json
import re
import time
import os
from typing import Dict, Optional, List
from urllib.parse import urlparse
from dotenv import load_dotenv
import google.generativeai as genai
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

load_dotenv()

# # Configure Gemini API
os.environ["GEMINI_API_KEY"] = "AIzaSyD_pvlH9aTESxlM6TrD5W9xyCObFB44kO4"
genai.configure(api_key=os.environ["GEMINI_API_KEY"])


def extract_username_from_url(url: str) -> Optional[str]:
    """Parse username from Threads URL like https://www.threads.com/@user/post/..."""
    try:
        path = urlparse(url).path
        parts = [p for p in path.split("/") if p]
        if parts and parts[0].startswith("@"):
            return parts[0]
    except Exception:
        pass
    return None


def clean_text(raw_text: str) -> str:
    """Clean unwanted UI text and numbers."""
    if not raw_text:
        return ""

    lines = [line.strip() for line in raw_text.splitlines()]
    cleaned = []

    blacklist = {
        "Log in", "Get app", "Translate", "Open Threads", "Threads Terms",
        "Privacy Policy", "Cookies Policy", "Report a problem",
        "Get the full app experience", "Unlock more features and see what people are talking about right now."
    }

    for line in lines:
        if not line:
            continue
        if line in blacklist:
            continue
        if re.fullmatch(r"\d+[KkMm]?", line):
            continue
        if re.fullmatch(r"\d+\s*[smhdw]", line):
            continue

        cleaned.append(line)

    return "\n".join(cleaned)


def scrape_single_threads_post(url: str, headless: bool = True) -> Optional[Dict]:
    """Scrape Threads.com page and extract visible text content."""
    username = extract_username_from_url(url)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)

        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                "Version/16.0 Mobile/15E148 Safari/604.1"
            ),
            viewport={"width": 430, "height": 932},
        )

        page = context.new_page()

        try:
            page.goto(url, wait_until="networkidle", timeout=80000)
            page.wait_for_timeout(3500)

            # Try several selectors
            article = (
                page.query_selector("article")
                or page.query_selector("div[role='article']")
                or page.query_selector("div[data-pressable-container='true']")
            )

            # Try to scroll to load full
            page.mouse.wheel(0, 2000)
            page.wait_for_timeout(2000)

            if article:
                raw_text = article.inner_text()
            else:
                raw_text = page.inner_text("body")

            cleaned = clean_text(raw_text)

            result = {
                "url": url,
                "username": username,
                "content": cleaned
            }

            browser.close()
            return result

        except Exception as e:
            print(f"[ERROR] {e}", file=sys.stderr)
            try:
                browser.close()
            finally:
                return None


def scrape_threads_from_inputs(inputs: List[str]) -> List[Dict]:
    results = []
    for u in inputs:
        print(f"🚀 Scraping: {u}", file=sys.stderr)
        data = scrape_single_threads_post(u, headless=True)
        if data and data.get("content"):
            print(f"🤖 Analyzing with Gemini...", file=sys.stderr)
            analysis = analyze_content_with_gemini(data["content"])
            data["fraud_analysis"] = analysis
            results.append(data)
        else:
            print(f"⚠️ No content found for: {u}", file=sys.stderr)
    return results


def analyze_content_with_gemini(content: str, api_key=None) -> str:
    """Analyze content using Gemini API to detect potential fraud risks."""
    try:

        final_api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not final_api_key:
            return "❌ 錯誤：找不到 API Key。"
        
        try:
            genai.configure(api_key=final_api_key)
            model = genai.GenerativeModel('gemini-2.5-flash')
        except Exception as e:
            return f"❌ 模型設定錯誤：{e}"

        # Use the model specified by the user
        # model = genai.GenerativeModel('gemini-2.5-flash') # gemini-2.5-pro
        
        prompt = f"""
        請扮演一位專業的詐騙防治專家。以下是一篇從 Threads 社群平台抓取的貼文內容。
        請仔細閱讀並分析這篇內容是否包含潛在的詐騙風險。

        貼文內容：
        {content}

        請針對一般民眾提供分析報告，包含：
        1. 風險評估：(高/中/低/無)
        2. 潛在風險點：指出具體哪些用語、行為或模式可能是詐騙手法。
        3. 防範建議：給予民眾具體的建議，如何查證或避免受騙。
        
        請用通俗易懂的語言回答，並在50字以內完成。
        """
        
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Gemini Analysis Error: {str(e)}"

def print_pretty_results(data: List[Dict]) -> None:
    """Pretty-print results to terminal for humans."""
    if not data:
        print("⚠️ No valid results.")
        return

    for idx, item in enumerate(data, start=1):
        url = item.get("url", "")
        username = item.get("username", "")
        content = item.get("content", "").strip()
        analysis = item.get("fraud_analysis", "").strip()

        print("=" * 80)
        print(f"[{idx}] URL      : {url}")
        print(f"    Username: {username}")
        print("-" * 80)
        print("📌 Post content:")
        print(content)
        print("-" * 80)
        print("🛡️  Fraud analysis (Gemini):")
        print(analysis)
        print()  # extra blank line

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scrape_threads_link.py <threads_post_url or file_with_urls>")
        sys.exit(1)

    arg = sys.argv[1].strip()
    import os
    from datetime import datetime

    urls: List[str] = []
    if os.path.isfile(arg):
        with open(arg, "r", encoding="utf-8") as f:
            urls = [l.strip() for l in f if l.strip()]
    else:
        urls = [arg]

    data = scrape_threads_from_inputs(urls)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_filename = f"threads_result_{timestamp}.json"

    with open(output_filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n💾 Saved to: {output_filename}\n")
    print_pretty_results(data)

