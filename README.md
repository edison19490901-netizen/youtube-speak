# 智读 🧠

从**中文/英文文章、博客、视频字幕、文档**生成**深度解读材料**，一次 AI 分析产出：

| 板块 | 内容 |
|------|------|
| **口播总结** | 中文要点 + 英文要点 + 中文口播稿 + 英文口播稿（可照读） |
| **解构** | 文章怎么写：写法总览、逐部分论点/论据/写作技巧、可借鉴技巧清单 |
| **实际应用** | 可操作技能（照做的方法）+ 可迁移的思维模型 |
| **金句单词** | 值得摘抄背诵的原文金句 + 重点单词表（仅英文材料） |
| **统计** | 字数、各板块数量、API 费用 |

## 快速开始

### 在线使用（无需安装）

部署到 [Render](https://render.com) 后，浏览器打开即可使用：
1. 粘贴文本 / 输入视频或文章链接 / 上传文档（.srt / .txt / .md / .docx / .pdf）
2. 等待 AI 解读（约 10-60 秒）
3. 在线查看 / 打印解读看板

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
#    从网页文章 URL
python -m article_understand "https://example.com/blog/post"
#    从 YouTube 字幕
python -m article_understand "https://www.youtube.com/watch?v=xxx"
#    从本地文件
python -m article_understand -f subtitles.srt
#    从 stdin 粘贴
cat article.txt | python -m article_understand -t "标题"
```

运行后在 `output/` 生成 `workbook.html`，手机/浏览器直接打开。

### 输入方式

| 方式 | 说明 |
|------|------|
| 粘贴文本 | 直接把文章/博客正文粘贴到网页或 stdin |
| 链接 | 视频链接自动获取字幕；网页文章链接自动抓取正文 |
| 文件 | `.srt` 按字幕处理；`.txt` / `.md` / `.docx` / `.pdf` 按文章处理 |

语言自动检测（中文材料不生成「金句单词」板块）。

## Render 部署

| 配置项 | 值 |
|--------|-----|
| Build Command | `pip install -r requirements.txt` |
| Start Command | `gunicorn app:app --bind 0.0.0.0:$PORT` |
| Environment Variable | `DEEPSEEK_API_KEY` = 你的 API Key |

## 依赖

- **Flask** — Web 界面
- **youtube-transcript-api** — YouTube 字幕下载
- **trafilatura** — 网页文章正文提取
- **DeepSeek API** — AI 解读（OpenAI 兼容，成本极低）
- **Jinja2** — 模板渲染
- **Click** — CLI 框架
