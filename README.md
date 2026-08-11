# YouTube Speak 🎙️

从 YouTube 长视频字幕生成英语口语练习材料的 CLI 工具。

**核心流程**: 下载字幕 → AI 智能提炼 → 多格式输出

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 设置 DeepSeek API Key
# 获取: https://platform.deepseek.com/api_keys
export DEEPSEEK_API_KEY="sk-xxxx"

# 3. 一键生成
python -m youtube_speak "https://youtube.com/watch?v=Ggio3AqKYXo"
```

## 输出内容

运行后会在 `output/{video_id}/` 目录下生成：

| 文件 | 说明 |
|------|------|
| `notes.md` | Markdown 学习笔记（适合个人博客） |
| `cards/cards.html` | 社交图文卡片（适合分享到小红书/公众号） |
| `workbook.pdf` | PDF 练习册（可打印，含默写栏和笔记区） |
| `analysis.json` | AI 分析原始数据（可复用） |
| `*.srt` | 下载的字幕文件 |

### 学习笔记包含

- 📝 中英文内容摘要
- 🗣️ 复述练习提示
- ⭐ 金句模板（带场景和中文说明）
- 📖 重点词汇（分难度等级）
- 📄 影子跟读分段文本（带重音连读提示）
- 💡 难点注释（俚语、文化梗等）

## CLI 选项

```bash
# 选择性输出
python -m youtube_speak "URL" --output notes     # 只要笔记
python -m youtube_speak "URL" --output cards     # 只要卡片
python -m youtube_speak "URL" --output pdf       # 只要练习册

# 难度等级
python -m youtube_speak "URL" --level beginner     # 初级（默认）
python -m youtube_speak "URL" --level intermediate # 中级
python -m youtube_speak "URL" --level advanced     # 高级

# 模型和 API
python -m youtube_speak "URL" --model deepseek-chat
python -m youtube_speak "URL" --api-key "sk-xxxx"

# 自定义输出目录
python -m youtube_speak "URL" --output-dir ./my_notes
```

## 依赖

- **yt-dlp**: YouTube 字幕下载
- **DeepSeek API**: AI 分析（OpenAI 兼容接口，成本极低）
- **Jinja2**: 模板渲染
- **WeasyPrint**: PDF 生成（可选，仅 PDF 输出需要）
- **Click**: CLI 框架

## 适用场景

- 英语口语练习者（尤其是初级→中级过渡期）
- 通过播客/访谈学习地道口语表达
- 制作个人学习笔记并分享到社交平台
- 英语学习博主批量生产内容

## 路线图

- [ ] 音频切片 + 逐句播放
- [ ] Web 界面管理学习材料
- [ ] 支持更多语言
- [ ] 间隔重复复习系统
- [ ] Anki 卡片导出
