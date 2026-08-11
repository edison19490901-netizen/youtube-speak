# YouTube Speak 🎙️

从 YouTube 字幕（或本地 .srt / .txt 文件）生成**交互式英语口语练习册**。

## 快速开始

### 在线使用（无需安装）

部署到 [Render](https://render.com) 后，浏览器打开即可使用：
1. 粘贴 YouTube 链接或上传字幕文件
2. 选择英语水平
3. 等待 AI 分析（约 10-30 秒）
4. 在线查看 / 下载练习册

### 本地运行

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 设置 DeepSeek API Key
export DEEPSEEK_API_KEY="sk-xxxx"
# 获取: https://platform.deepseek.com/api_keys

# 3. 启动 Web 界面
python app.py
# 浏览器打开 http://localhost:5000

# 4. 或命令行直接生成
python -m youtube_speak -f subtitles.srt -t "标题"
```

## 输出内容

运行后在 `output/` 生成 `workbook.html`，包含：

| 板块 | 内容 |
|------|------|
| 摘要 | 中英文内容概要 |
| 复述 | 6-8 条分层提示 + 点击查看参考复述 |
| 词汇 | 重点词汇表（分难度、带语境例句） |
| 金句 | 口语句型模板 + 仿写练习区 |
| 跟读 | 影子跟读分段文本 + 发音提示 |
| 难点 | 俚语、文化梗等注释 |
| 统计 | 学习数据一览 |

所有板块在手机上一行横向切换，点击展开。

## Render 部署

| 配置项 | 值 |
|--------|-----|
| Build Command | `pip install -r requirements.txt` |
| Start Command | `gunicorn app:app --bind 0.0.0.0:$PORT` |
| Environment Variable | `DEEPSEEK_API_KEY` = 你的 API Key |

## 依赖

- **Flask** — Web 界面
- **youtube-transcript-api** — 字幕下载
- **DeepSeek API** — AI 分析（OpenAI 兼容，成本极低）
- **Jinja2** — 模板渲染
- **Click** — CLI 框架
