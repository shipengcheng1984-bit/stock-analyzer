# 股票新闻速览 - 快速上手指南

## 项目结构
```
stock-analyzer/
├── backend/
│   ├── main.py          # FastAPI 后端
│   ├── requirements.txt # 依赖包
│   └── .env.example     # 环境变量模板
└── frontend/
    └── index.html       # 前端页面（单文件）
```

## 第一步：准备 Token

1. **tushare token**
   - 注册：https://tushare.pro/register
   - 注册后在个人中心找到 token

2. **Claude API key**
   - 注册：https://console.anthropic.com
   - 充值后在 API Keys 页面创建

## 第二步：启动后端

```bash
cd backend

# 安装依赖
pip install -r requirements.txt

# 复制环境变量文件
cp .env.example .env
# 用编辑器打开 .env，填入你的两个 token

# 启动服务
uvicorn main:app --reload --port 8000
```

看到 `Uvicorn running on http://127.0.0.1:8000` 就成功了。

## 第三步：打开前端

直接用浏览器打开 `frontend/index.html` 即可。

输入股票代码（如 `000001.SZ`）和名称（如 `平安银行`），点击分析。

## 股票代码格式

| 市场 | 格式 | 例子 |
|------|------|------|
| 深交所 | xxxxxx.SZ | 000001.SZ |
| 上交所 | xxxxxx.SH | 600519.SH |
| 创业板 | xxxxxx.SZ | 300750.SZ |

## 部署上线（可选）

后端部署到 Railway：
1. 注册 https://railway.app
2. 新建项目，连接你的 GitHub 仓库
3. 设置环境变量（TUSHARE_TOKEN、ANTHROPIC_API_KEY）
4. 自动部署完成后，把前端里的 API_BASE 改成你的 Railway 域名

## 常见问题

**Q: 新闻数据很少怎么办？**
A: tushare 免费版数据有限，先验证流程跑通，后期可升级 tushare 积分获取更多数据源。

**Q: API 报错怎么办？**
A: 检查 .env 里的 token 是否正确填写，tushare token 注册后需要几分钟才能生效。
