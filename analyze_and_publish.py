"""一键分析本地文档并上传 GitHub。

流程：
  1. 弹出文件选择框（或通过 --file 指定文档）
  2. 生成智读解读看板（workbook.html）
  3. 生成背诵版（recite.html + 每块翻译），并嵌入看板「背诵」Tab
  4. 把 output/<材料>/ 提交并推送到 GitHub

用法：
    python analyze_and_publish.py                 # 弹出文件选择框
    python analyze_and_publish.py --pick          # 同上（显式指定）
    python analyze_and_publish.py --file 文章.txt  # 直接分析指定文档
    python analyze_and_publish.py --file 文章.txt --no-push  # 只生成不推送
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT_ROOT = ROOT / "output"

sys.path.insert(0, str(ROOT))

from article_understand.analyzer import analyze, save_analysis  # noqa: E402
from article_understand.downloader import SubtitleInfo  # noqa: E402
from article_understand.outputs.workbook import generate as generate_workbook  # noqa: E402
from article_understand.parser import detect_language, parse_file  # noqa: E402
from article_understand.recite.analyzer import (  # noqa: E402
    analyze as recite_analyze,
    save_material as save_recite_material,
)
from article_understand.recite.outputs.recite_book import (  # noqa: E402
    build_context as build_recite_context,
    generate as generate_recite_book,
)
from article_understand.recite.planner import build_schedule  # noqa: E402

SUPPORTED_EXTS = (".docx", ".txt", ".md", ".srt", ".pdf", ".rtf")
MODEL = "deepseek-chat"


def main() -> int:
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="分析本地文档并上传 GitHub")
    parser.add_argument("--file", "-f", type=Path, default=None, help="要分析的文档路径")
    parser.add_argument("--pick", action="store_true", help="弹出文件选择框")
    parser.add_argument("--title", "-t", default=None, help="材料标题（默认用文件名）")
    parser.add_argument("--no-push", action="store_true", help="只生成看板，不提交/推送")
    args = parser.parse_args()

    file_path = args.file
    if args.pick or file_path is None:
        try:
            file_path = pick_file()
        except RuntimeError as e:
            print(f"[错误] {e}")
            return 1
        if file_path is None:
            print("已取消，未选择文档。")
            return 0

    file_path = file_path.expanduser().resolve()
    if not file_path.exists():
        print(f"[错误] 文件不存在：{file_path}")
        return 1
    if file_path.suffix.lower() not in SUPPORTED_EXTS:
        print(
            f"[错误] 不支持的格式：{file_path.suffix or '（无扩展名）'}\n"
            f"        支持：{' / '.join(SUPPORTED_EXTS)}"
        )
        return 1

    api_key = load_api_key()
    if not api_key:
        print(
            "[错误] 未找到 DEEPSEEK_API_KEY。\n"
            "       请在项目根目录 .env 中写入 DEEPSEEK_API_KEY=sk-xxxx，"
            "或设置同名环境变量。"
        )
        return 1

    title = (args.title or file_path.stem).strip() or "未命名材料"
    try:
        return run_pipeline(file_path, title, api_key, push=not args.no_push)
    except (ValueError, RuntimeError) as e:
        print(f"\n[失败] {e}")
        return 1
    except KeyboardInterrupt:
        print("\n已中断。")
        return 130
    except Exception as e:  # noqa: BLE001 - 面向普通用户的脚本，给出简洁错误
        print(f"\n[失败] 未知错误：{e}")
        return 1


# ── 主流程 ───────────────────────────────────────


def run_pipeline(file_path: Path, title: str, api_key: str, push: bool) -> int:
    print(f"\n[1/4] 读取文档：{file_path.name}")
    parsed = parse_file(file_path)
    lang = detect_language(parsed.full_text)
    if parsed.word_count == 0:
        raise ValueError("文档中没有可解析的文字内容。")
    print(f"      语言：{'中文' if lang == 'zh' else 'English'} · 字数/词数：{parsed.word_count}")

    safe_id = safe_dirname(file_path.stem)
    out_dir = OUTPUT_ROOT / safe_id
    out_dir.mkdir(parents=True, exist_ok=True)
    source_type = "subtitle" if file_path.suffix.lower() == ".srt" else "article"

    info = SubtitleInfo(
        video_id=safe_id,
        video_title=title,
        uploader="本地文件",
        duration_seconds=parsed.sentence_count * 5,
        subtitle_path=file_path,
        subtitle_type=source_type,
        language=lang,
    )

    # 保存原文，供网页版「背诵」复用 / 重新生成
    (out_dir / "source.json").write_text(
        json.dumps(
            {
                "title": title,
                "uploader": "本地文件",
                "duration_seconds": info.duration_seconds,
                "language": lang,
                "source_type": source_type,
                "word_count": parsed.word_count,
                "full_text": parsed.full_text,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("\n[2/4] AI 生成解读看板（约 10-60 秒）…")
    analysis = analyze(
        full_text=parsed.full_text,
        title=title,
        source_type=source_type,
        language=lang,
        api_key=api_key,
        model=MODEL,
    )
    save_analysis(analysis, out_dir / "analysis.json")
    workbook_path = out_dir / "workbook.html"
    generate_workbook(analysis, info, parsed, workbook_path)
    if analysis.usage and analysis.usage.total_tokens:
        print(f"      看板：{workbook_path}（API 费用 ¥{analysis.usage.cost_cny:.4f}）")
    else:
        print(f"      看板：{workbook_path}")

    print("\n[3/4] AI 生成背诵版（意群分块 + 译文，约 10-60 秒）…")
    recite_ctx = None
    if parsed.word_count < 20:
        print("      文档过短，跳过背诵版。")
    else:
        try:
            recite_result = recite_analyze(
                full_text=parsed.full_text,
                title=title,
                language=lang,
                source_type=source_type,
                api_key=api_key,
                model=MODEL,
            )
            material = recite_result.material
            if not material.chunks:
                raise RuntimeError("AI 未能切分出有效意群块。")
            schedule = build_schedule(len(material.chunks))
            meta = {
                "material_id": safe_id,
                "title": title,
                "language": lang,
                "source_type": source_type,
                "truncated": recite_result.truncated,
                "created": date.today().isoformat(),
            }
            save_recite_material(material, meta, recite_result.usage, out_dir / "material.json")
            generate_recite_book(
                material, meta, parsed, schedule, recite_result.usage,
                out_dir / "recite.html",
            )
            recite_ctx = build_recite_context(material, meta, parsed, schedule, recite_result.usage)
            # 把背诵内容嵌入看板「背诵」Tab
            generate_workbook(analysis, info, parsed, workbook_path, recite=recite_ctx)
            translated = sum(1 for c in material.chunks if c.translation)
            print(
                f"      背诵版：{out_dir / 'recite.html'}\n"
                f"      {len(material.chunks)} 块 · 已附译文 {translated}/{len(material.chunks)} 块"
            )
            if translated < len(material.chunks):
                print("      [提示] 部分块未返回译文，对应块的翻译区会自动隐藏。")
        except (ValueError, RuntimeError) as e:
            print(f"      [警告] 背诵版生成失败：{e}\n      解读看板仍可用。")

    print("\n[4/4] 上传到 GitHub…")
    if not push:
        print("      已跳过（--no-push）。")
        print(f"\n完成！打开看板：{workbook_path}")
        return 0

    ok = git_publish(out_dir, title)
    print(f"\n完成！打开看板：{workbook_path}")
    return 0 if ok else 1


# ── 文件选择 ─────────────────────────────────────


def pick_file() -> Path | None:
    """弹出 Windows 文件选择框，返回选中的文档路径。"""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:
        raise RuntimeError("当前 Python 缺少 tkinter，无法弹出文件选择框。请改用 --file 指定文档。")

    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass
    selected = filedialog.askopenfilename(
        title="选择要分析的文档",
        initialdir=str(ROOT),
        filetypes=[
            ("支持的文档", "*.docx *.txt *.md *.srt *.pdf *.rtf"),
            ("Word 文档", "*.docx"),
            ("文本 / 字幕", "*.txt *.md *.srt"),
            ("PDF", "*.pdf"),
            ("所有文件", "*.*"),
        ],
    )
    root.destroy()
    return Path(selected) if selected else None


# ── GitHub ──────────────────────────────────────


def git_publish(out_dir: Path, title: str) -> bool:
    """提交 output/<材料>/ 并推送当前分支。"""
    if not shutil.which("git"):
        print("      [错误] 未找到 git，请先安装 Git。")
        return False

    rel = out_dir.relative_to(ROOT).as_posix()

    added = _run(["git", "add", "--", rel])
    if added.returncode != 0:
        print(f"      [错误] git add 失败：\n{_output(added)}")
        return False

    # 只看这个材料目录，避免把其它已暂存的改动一并提交
    changed = _run(["git", "diff", "--cached", "--quiet", "--", rel])
    if changed.returncode == 0:
        print("      没有新的改动需要提交。")
        return True

    message = f"新增看板：{title}"
    committed = _run(["git", "commit", "-m", message, "--", rel])
    if committed.returncode != 0:
        print(f"      [错误] git commit 失败：\n{_output(committed)}")
        return False
    print(f"      已提交：{message}")

    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip() or "main"
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes -o ConnectTimeout=15")
    pushed = _run(["git", "push", "origin", branch], env=env)
    if pushed.returncode != 0:
        print(
            "      [错误] git push 失败，分析结果已保存在本地。\n"
            f"{_output(pushed)}\n"
            f"      可稍后手动推送：git push origin {branch}"
        )
        return False

    print(f"      已推送到 origin/{branch}")
    return True


def _run(cmd: list[str], env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=str(ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        env=env,
    )


def _output(result: subprocess.CompletedProcess) -> str:
    text = (result.stderr or "") + (result.stdout or "")
    return text.strip() or f"（退出码 {result.returncode}）"


# ── 辅助 ────────────────────────────────────────


def load_api_key() -> str:
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if key:
        return key
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("DEEPSEEK_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def safe_dirname(stem: str) -> str:
    """与网页版上传逻辑一致：保留字母/数字/中文/_-，其余替换为下划线。"""
    safe = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in stem)
    return safe or "document"


if __name__ == "__main__":
    raise SystemExit(main())
