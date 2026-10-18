"""Single-page GitHub Actions dashboard and stand-alone detailed HTML report.

Only uses the already-validated engine result. No new quote downloads.
"""
from __future__ import annotations

import html
import json
from pathlib import Path

from reports import fnum, fpct

SPARK_CHARS = "▁▂▃▄▅▆▇█"


def _spark(prices):
    values = [float(r["close"]) for r in (prices or [])]
    if not values:
        return "—"
    lo, hi = min(values), max(values)
    if hi == lo:
        return "▄" * len(values)
    return "".join(SPARK_CHARS[min(7, max(0, round((x-lo) * 7 / (hi-lo))))] for x in values)


def _md_cell(x):
    return str(x if x is not None else "—").replace("|", "&#124;").replace("\n", " ")


def _md_table(columns, data):
    if not data:
        return "無符合標的。\n"
    output = ["| " + " | ".join(columns) + " |",
              "| " + " | ".join("---" for _ in columns) + " |"]
    output.extend("| " + " | ".join(_md_cell(x) for x in row) + " |" for row in data)
    return "\n".join(output) + "\n"


def build_summary(result, info):
    day = result["latest"]
    watch = result["watchlist"]
    added = result["added"]
    removed = result["removed"]
    cont = sorted(result["continuous"], key=lambda m: (-m["cumulative_return_pct"], m["code"]))
    history = result.get("ledger", [])
    blocked = result.get("blocked", [])
    etf = info.get("etf", {})
    lines = [
        f"# 台股動能篩選｜{day}",
        "",
        f"**行情截止日：{day}**　｜　執行日期：{info.get('execution','—')}　｜　追蹤起點：{info['start']}",
        "",
        f"**觀察 {len(watch)} 檔　｜　新增 {len(added)} 檔　｜　剔除 {len(removed)} 檔　｜　連續收益 {len(cont)} 檔**",
        "",
        f"**資料完整性：** {info.get('coverage','未確認')}；已辨識股票 {info.get('universe_count','—')} 檔。",
        "",
        f"**ETF B1：** {etf.get('status','unknown')}（追蹤 {', '.join(etf.get('queried',[])) or '未提供'}）。"
        + (" 缺少授權資料，不代表 ETF 沒有加碼。" if etf.get("status") != "available" else ""),
        "",
    ]
    if info.get("report_mode") in ("manual_prior_session", "manual_exact_session"):
        lines.append("**注意：本次為指定日期／前一交易日回顧，並非當日新行情。**\n")
    lines += [
        "## 一、觀察清單",
        "",
        _md_table(
            ["代號", "名稱", "收盤價", "成交量(張)", "3／12量比", "當日漲跌幅",
             "MA20／60／120", "RSI／K／D", "入選訊號", "入選日期", "十日走勢"],
            [[m["code"],m["name"],fnum(m["close"]),fnum(m["volume_lots"],0),
              fnum(m["volume_ratio"]),fpct(m.get("daily_change_pct")),
              "/".join(fnum(m["ma"+str(n)],1) for n in (20,60,120)),
              "/".join(fnum(m[k],1) for k in ("rsi","k","d")),
              ",".join(m["entry_conditions"]),m["entry_date"],_spark(m.get("chart"))]
             for m in watch]
        ),
        "",
        "## 二、新增、剔除清單",
        "",
        "### 今日新增",
        "",
        _md_table(["代號","名稱","收盤價","當日漲跌幅","觸發條件"],
                  [[m["code"],m["name"],fnum(m["close"]),fpct(m.get("daily_change_pct")),
                    ",".join(m["entry_conditions"])] for m in added]),
        "",
        "### 今日剔除",
        "",
        _md_table(["代號","名稱","收盤價","當日漲跌幅","剔除原因","自入選報酬"],
                  [[m["code"],m["name"],fnum(m["close"]),fpct(m.get("daily_change_pct")),
                    ",".join(m["exit_conditions"]),fpct(m.get("cumulative_return_pct"))] for m in removed]),
        "",
        "## 三、連續收益",
        "",
        "持續觀察至少兩個交易日，按自入選以來累積漲跌幅由高至低排序。",
        "",
        _md_table(["排名","代號","名稱","入選日期","追蹤交易日","入選價","最新收盤","累積報酬","當日漲跌幅"],
                  [[i,m["code"],m["name"],m["entry_date"],m["held_sessions"],
                    fnum(m["entry_price"]),fnum(m["close"]),
                    fpct(m["cumulative_return_pct"]),fpct(m.get("daily_change_pct"))]
                   for i,m in enumerate(cont,1)]),
        "",
        "## 附錄：已結束的追蹤紀錄",
        "",
        _md_table(["代號","名稱","入選日","入選價","剔除日","剔除價","報酬","原因"],
                  [[m["code"],m["name"],m["entry_date"],fnum(m["entry_close"]),
                    m["exit_date"],fnum(m["exit_close"]),fpct(m["return_pct"]),
                    m["exit_conditions"]] for m in history]),
        "",
        "## 附錄：同日進場訊號遭汰除阻擋",
        "",
        _md_table(["代號","名稱","收盤","阻擋原因"],
                  [[m["code"],m["name"],fnum(m["close"]),m["reason"]] for m in blocked]),
        "",
        f"**行情來源：** {info.get('sources','—')}",
        "",
        "股價及績效使用未還原價格，不含配息、手續費及滑價；收盤後才出現的訊號，假設同日收盤成交僅屬理論追蹤。",
        "",
        "**十日型態** 欄使用迷你走勢線；獨立 HTML 報告包含真正折線圖及完整逐日明細。",
        "",
    ]
    return "\n".join(lines)


def _html_table(rows, columns):
    if not rows:
        return "<p>目前無紀錄</p>"
    header = "".join("<th>" + html.escape(title) + "</th>" for title, _ in columns)
    body = []
    for row in rows:
        body.append("<tr>" + "".join(
            "<td>" + html.escape(str(row.get(key, "—"))) + "</td>"
            for _, key in columns
        ) + "</tr>")
    return '<div class="overflow"><table><thead><tr>' + header + "</tr></thead><tbody>" + "".join(body) + "</tbody></table></div>"


def enrich_html(report_path, result, info):
    p = Path(report_path)
    document = p.read_text(encoding="utf-8")
    if "</main>" not in document:
        raise ValueError("report.html missing its main section")
    appendices = [
        "<section><h2>四、完整回測與追蹤明細</h2>",
        "<details><summary>已結束交易紀錄（" + str(len(result.get("ledger", []))) + " 筆）</summary>",
        _html_table(result.get("ledger", []), [
            ("代號","code"),("名稱","name"),("入選日","entry_date"),
            ("入選價","entry_close"),("剔除日","exit_date"),("剔除價","exit_close"),
            ("累積報酬(%)","return_pct"),("入選條件","entry_conditions"),
            ("剔除條件","exit_conditions")]), "</details>",
        "<details><summary>完整逐日追蹤紀錄（" + str(len(result.get("daily_rows", []))) + " 筆）</summary>",
        _html_table(result.get("daily_rows", []), [
            ("日期","date"),("代號","code"),("名稱","name"),("報價日","quote_date"),
            ("入選日","entry_date"),("入選價","entry_close"),("收盤價","close"),
            ("累積報酬(%)","return_pct"),("追蹤日數","held_sessions"),
            ("報價是否陳舊","stale")]), "</details>",
        "<details><summary>全部新增、剔除事件（" + str(len(result.get("changes", []))) + " 筆）</summary>",
        _html_table(result.get("changes", []), [
            ("日期","date"),("代號","code"),("異動類型","type"),("原因","reason")]), "</details>",
        "<details><summary>資料來源、完整性與執行設定</summary><pre style='white-space:pre-wrap'>",
        html.escape(json.dumps(info, ensure_ascii=False, indent=2)),
        "</pre></details></section>"
    ]
    p.write_text(document.replace("</main>", "".join(appendices) + "</main>", 1), encoding="utf-8")


def write_dashboard(output_dir, result, info):
    root = Path(output_dir)
    (root/"report.md").write_text(build_summary(result, info), encoding="utf-8")
    enrich_html(root/"report.html", result, info)
