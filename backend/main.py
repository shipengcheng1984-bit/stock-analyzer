from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
from collections import defaultdict
import tushare as ts
import requests
import datetime
import json
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 初始化 ────────────────────────────────────────────
TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "")
KIMI_API_KEY  = os.getenv("KIMI_API_KEY", "")

pro    = ts.pro_api(TUSHARE_TOKEN)
client = OpenAI(api_key=KIMI_API_KEY, base_url="https://api.moonshot.cn/v1")

# 全量股票列表
stock_list = []

# 每日查询限制
query_count = defaultdict(int)
query_date  = ""
DAILY_LIMIT = 10

# 热门股票缓存
hot_stocks_cache = []
hot_stocks_date  = ""

# AI 分析结果缓存
analysis_cache      = {}
analysis_cache_date = ""


# ── 启动时加载全量A股列表 ──────────────────────────────
@app.on_event("startup")
async def load_stock_list():
    global stock_list
    try:
        with open('stock_list.json', 'r', encoding='utf-8') as f:
            stock_list = json.load(f)
        print(f"✅ 从缓存加载股票列表，共 {len(stock_list)} 只")
    except FileNotFoundError:
        print("正在拉取股票列表...")
        try:
            import akshare as ak
            df = ak.stock_info_a_code_name()
            all_stocks = []
            for _, row in df.iterrows():
                code = str(row['code']).zfill(6)
                name = str(row['name']).strip()
                suffix = '.SH' if code.startswith('6') or code.startswith('9') else '.SZ'
                all_stocks.append({'ts_code': code + suffix, 'name': name, 'industry': ''})
            stock_list = all_stocks
            with open('stock_list.json', 'w', encoding='utf-8') as f:
                json.dump(stock_list, f, ensure_ascii=False)
            print(f"✅ 加载股票列表成功，共 {len(stock_list)} 只，已缓存到本地")
        except Exception as e:
            print(f"❌ 加载股票列表失败: {e}")

    # 后台预热热门股票
    import asyncio
    asyncio.create_task(preheat_hot_stocks())


async def preheat_hot_stocks():
    global hot_stocks_cache, hot_stocks_date
    try:
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        df = df.sort_values('涨跌幅', ascending=False).head(5)
        results = []
        for _, row in df.iterrows():
            code = str(row.get('代码', '')).zfill(6)
            name = str(row.get('名称', '')).strip()
            suffix = '.SH' if code.startswith('6') or code.startswith('9') else '.SZ'
            if code and name:
                results.append({'ts_code': code + suffix, 'name': name})
        hot_stocks_cache = results
        hot_stocks_date  = datetime.date.today().isoformat()
        print(f"✅ 热门股票预热完成，共 {len(results)} 只")
    except Exception as e:
        print(f"❌ 热门股票预热失败: {e}")


# ── 每日限流检查 ───────────────────────────────────────
def check_limit(ip: str) -> bool:
    global query_date
    today = datetime.date.today().isoformat()
    if query_date != today:
        query_count.clear()
        query_date = today
    return query_count[ip] < DAILY_LIMIT

def remaining_count(ip: str) -> int:
    return max(0, DAILY_LIMIT - query_count[ip])


# ── 股票搜索接口 ───────────────────────────────────────
@app.get("/search")
def search_stock(q: str = ""):
    if not q or len(q.strip()) < 1:
        return {"results": []}
    q = q.strip()
    q_upper = q.upper()
    results = [
        s for s in stock_list
        if q in s.get('name', '')
        or q_upper in s.get('ts_code', '')
        or s.get('ts_code', '').replace('.SH', '').replace('.SZ', '').startswith(q)
    ]
    return {"results": results[:10]}


# ── 热门股票接口 ───────────────────────────────────────
@app.get("/hot-stocks")
async def get_hot_stocks():
    global hot_stocks_cache, hot_stocks_date
    today = datetime.date.today().isoformat()

    if hot_stocks_date == today and hot_stocks_cache:
        return {"results": hot_stocks_cache}

    try:
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        df = df.sort_values('涨跌幅', ascending=False).head(5)
        results = []
        for _, row in df.iterrows():
            code = str(row.get('代码', '')).zfill(6)
            name = str(row.get('名称', '')).strip()
            suffix = '.SH' if code.startswith('6') or code.startswith('9') else '.SZ'
            if code and name:
                results.append({'ts_code': code + suffix, 'name': name})
        hot_stocks_cache = results
        hot_stocks_date  = today
        return {"results": results}
    except Exception as e:
        print(f"获取热门股票失败: {e}")
        return {"results": [
            {"ts_code": "600519.SH", "name": "贵州茅台"},
            {"ts_code": "300750.SZ", "name": "宁德时代"},
            {"ts_code": "002594.SZ", "name": "比亚迪"},
            {"ts_code": "000001.SZ", "name": "平安银行"},
            {"ts_code": "601318.SH", "name": "中国平安"},
        ]}


# ── 请求/响应格式 ──────────────────────────────────────
class StockRequest(BaseModel):
    ts_code: str
    stock_name: str

class AnalysisResponse(BaseModel):
    stock_name: str
    ts_code: str
    summary: str
    sentiment: str
    key_points: list[str]
    news_count: int
    remaining: int
    price: float = 0.0
    change_pct: float = 0.0


# ── 分析接口 ───────────────────────────────────────────
@app.post("/analyze", response_model=AnalysisResponse)
async def analyze_stock(req: StockRequest, request: Request):
    global analysis_cache_date
    ip = request.client.host
    today = datetime.date.today().isoformat()

    # 日期变了清空分析缓存
    if analysis_cache_date != today:
        analysis_cache.clear()
        analysis_cache_date = today

    # 命中缓存直接返回，不扣次数
    if req.ts_code in analysis_cache:
        print(f"命中缓存：{req.stock_name}")
        result = analysis_cache[req.ts_code]
        result.remaining = remaining_count(ip)
        return result

    # 没有缓存才检查限流
    if not check_limit(ip):
        raise HTTPException(
            status_code=429,
            detail=f"今日查询次数已达上限（{DAILY_LIMIT}次），明天再来吧 🙏"
        )

    query_count[ip] += 1

    news_text = fetch_news(req.ts_code, req.stock_name)
    if not news_text:
        raise HTTPException(status_code=404, detail=f"未找到 {req.stock_name} 的相关新闻")

    result = call_kimi(req.stock_name, req.ts_code, news_text)
    result.remaining = remaining_count(ip)

    # 获取实时价格
    try:
        import akshare as ak
        symbol = req.ts_code.replace('.SH', '').replace('.SZ', '')
        df = ak.stock_bid_ask_em(symbol=symbol)
        if df is not None and not df.empty:
            price_row = df[df['item'] == '最新']
            chg_row = df[df['item'] == '涨幅']
            if not price_row.empty:
                result.price = float(price_row.iloc[0]['value'])
            if not chg_row.empty:
                result.change_pct = float(chg_row.iloc[0]['value'])
    except Exception as e:
        print(f"获取价格失败: {e}")

    # 存入当日缓存
    analysis_cache[req.ts_code] = result
    return result


# ── 抓取新闻 ───────────────────────────────────────────
def fetch_news(ts_code: str, stock_name: str) -> str:
    news_items = []
    try:
        import akshare as ak
        symbol = ts_code.replace('.SH', '').replace('.SZ', '')
        df = ak.stock_news_em(symbol=symbol)
        if df is not None and not df.empty:
            for _, row in df.head(15).iterrows():
                title   = str(row.get('新闻标题', '')).strip()
                content = str(row.get('新闻内容', '')).strip()[:100]
                source  = str(row.get('文章来源', '')).strip()
                time    = str(row.get('发布时间', '')).strip()
                if title:
                    news_items.append(f"【{source} {time[:10]}】{title}。{content}")
    except Exception as e:
        print(f"获取新闻失败: {e}")

    return "\n".join(news_items) if news_items else ""


# ── 调用 Kimi 分析 ─────────────────────────────────────
def call_kimi(stock_name: str, ts_code: str, news_text: str) -> AnalysisResponse:
    prompt = f"""你是一个专业的A股市场信息分析助手。

以下是关于【{stock_name}（{ts_code}）】的最新新闻：

{news_text}

请基于以上信息，用简洁的中文输出（注意：只做信息整理，不做投资建议）：

1. 核心摘要：用2-3句话概括最重要的信息
2. 市场情绪：只输出"正面"、"负面"或"中性"三个词之一
3. 关键点：列出3-5个投资者需要关注的信息点，每点一句话

严格按以下格式输出，不要有多余内容：
摘要：xxx
情绪：xxx
关键点：
- xxx
- xxx
- xxx"""

    response = client.chat.completions.create(
        model="kimi-k2-0711-preview",
        messages=[{"role": "user", "content": prompt}]
    )
    raw = response.choices[0].message.content
    return parse_response(stock_name, ts_code, raw, news_text)


def parse_response(stock_name, ts_code, raw, news_text) -> AnalysisResponse:
    lines = raw.strip().split('\n')
    summary, sentiment, key_points = "", "中性", []

    for line in lines:
        line = line.strip()
        if line.startswith("摘要："):
            summary = line.replace("摘要：", "").strip()
        elif line.startswith("情绪："):
            sentiment = line.replace("情绪：", "").strip()
        elif line.startswith("- "):
            key_points.append(line[2:].strip())

    return AnalysisResponse(
        stock_name=stock_name,
        ts_code=ts_code,
        summary=summary or raw[:150],
        sentiment=sentiment,
        key_points=key_points,
        news_count=news_text.count('\n') + 1 if news_text else 0,
        remaining=0,
        price=0.0,
        change_pct=0.0
    )


# ── 健康检查 ──────────────────────────────────────────
@app.get("/")
def root():
    return {"status": "ok", "message": "股票新闻分析服务运行中"}