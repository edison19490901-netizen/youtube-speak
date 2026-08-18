# Handoff — 项目交接说明

## 推送 output 内容到 GitHub

在项目根目录 `D:\Claudeee\article_understand` 下执行：

```bash
# 1. 查看当前状态（确认有哪些改动/未跟踪文件）
git status

# 2. 把 output 目录里的所有改动加入暂存区
git add output/

# 3. 提交，-m 后面是提交说明（可自行修改）
git commit -m "新增看板：<看板名称>"

# 4. 推送到 GitHub
git push origin main
```

一次性执行可写成：

```bash
git add output/ && git commit -m "提交说明" && git push origin main
```

### 说明
- **只推 output**：`git add output/` 只会暂存 output 里的内容，根目录的 `.docx` / `要求.txt` 等不受影响。
- **提交前先看**：`git status` 会列出将要提交的文件，确认无误再 `commit`。
- **覆盖更新**：若重新生成看板覆盖了旧的 `analysis.json` / `workbook.html`，命令完全一样，改提交说明即可。
- **远端**：`origin` 使用 SSH 方式 `git@github.com:edison19490901-netizen/youtube-speak.git`，需配好 SSH key。
- **推送后验证**：`git log --oneline -3` 查看最近提交。

## 参考
- 2026-08-17 已推送提交 `775edd3`「新增看板：财富是信息不对称决定的、战争阴霾下的新世界」
