#!/usr/bin/env python3
"""Email a validated daily momentum report via authenticated Gmail SMTP.

Secrets are supplied by GitHub Actions environment variables, never committed:
  REPORT_SMTP_USER, REPORT_SMTP_APP_PASSWORD, REPORT_EMAIL_TO
Does not send on days when there is no completed report.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from pathlib import Path

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


def valid_single_email(value: str, field: str) -> str:
    value = (value or "").strip()
    _, address = parseaddr(value)
    # Require a single simple mailbox: no display names, commas or whitespace.
    if (
        not value or address != value or
        not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", value)
        or ".." in value
    ):
        raise ValueError(f"{field} must contain exactly one valid email address")
    if value.lower().endswith("@gmai.com"):
        raise ValueError(f"{field} ends with @gmai.com; check whether @gmail.com was intended")
    return value


def prepare_message(
    sender: str, recipient: str, report_html: str, plain_text: str, metadata: dict,
    filename: str = "momentum-report.html"
) -> EmailMessage:
    source_date = metadata.get("as_of") or metadata.get("source_date")
    if not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", str(source_date or "")):
        raise ValueError("Report metadata is missing a valid trading date")
    counts = metadata.get("counts", {})
    summary = (
        f"觀察 {counts.get('watchlist', '—')}、"
        f"新增 {counts.get('added', '—')}、"
        f"剔除 {counts.get('removed', '—')}、"
        f"連續收益 {counts.get('continuous', '—')}"
    )
    msg = EmailMessage()
    msg["From"] = formataddr(("台股動能篩選系統", sender))
    msg["To"] = recipient
    msg["Subject"] = f"[台股動能] {source_date} 盤後報告｜{summary}"
    intro = (
        f"行情截止日：{source_date}\n"
        f"執行日期：{metadata.get('execution','—')}\n"
        f"{summary}\n"
        f"ETF B1：{metadata.get('etf',{}).get('status','unknown')}\n\n"
        "本信附上完整 report.html，可直接在瀏覽器開啟十日股價折線圖與全部追蹤紀錄。\n"
        "若郵件服務未顯示嵌入式圖形，請開啟附件。\n\n"
    )
    msg.set_content(intro + plain_text)
    # Many mail clients sanitize inline SVG/CSS; the attachment remains intact.
    msg.add_alternative(report_html, subtype="html")
    msg.add_attachment(
        report_html.encode("utf-8"), maintype="text", subtype="html",
        filename=filename
    )
    return msg


def send_report(
    report: Path, metadata_path: Path, markdown_path: Path,
    *, sender: str, password: str, recipient: str
) -> str:
    sender = valid_single_email(sender, "REPORT_SMTP_USER")
    recipient = valid_single_email(recipient, "REPORT_EMAIL_TO")
    if not password.strip():
        raise ValueError("REPORT_SMTP_APP_PASSWORD is missing")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("coverage") != "full-market coverage checks passed":
        raise RuntimeError("Refusing to email a report without verified full-market coverage")
    report_html = report.read_text(encoding="utf-8")
    plain_text = markdown_path.read_text(encoding="utf-8")
    if "<html" not in report_html.lower() or not all(
        section in report_html for section in ("一、觀察清單", "二、新增、剔除清單", "三、連續收益")
    ):
        raise RuntimeError("Incomplete HTML report; email was not sent")
    message = prepare_message(sender, recipient, report_html, plain_text, metadata)
    with smtplib.SMTP_SSL(
        SMTP_HOST, SMTP_PORT, timeout=45, context=ssl.create_default_context()
    ) as smtp:
        smtp.login(sender, password.replace(" ", ""))
        smtp.send_message(message)
    return str(metadata.get("as_of") or metadata.get("source_date"))


def main() -> int:
    p = argparse.ArgumentParser(description="Email the completed momentum report")
    p.add_argument("--report", default="output/report.html")
    p.add_argument("--metadata", default="output/metadata.json")
    p.add_argument("--markdown", default="output/report.md")
    args = p.parse_args()

    paths = [Path(args.report), Path(args.metadata), Path(args.markdown)]
    if not all(path.is_file() for path in paths):
        print("EMAIL SKIP: completed screening report not available (non-trading day or scan not completed).", flush=True)
        return 0

    sender = os.environ.get("REPORT_SMTP_USER","").strip()
    password = os.environ.get("REPORT_SMTP_APP_PASSWORD","")
    recipient = os.environ.get("REPORT_EMAIL_TO","").strip()

    if not all((sender,password,recipient)):
        missing = [k for k,v in (
            ("REPORT_SMTP_USER",sender),
            ("REPORT_SMTP_APP_PASSWORD",password),
            ("REPORT_EMAIL_TO",recipient)
        ) if not v]
        print("EMAIL NOT CONFIGURED: add GitHub Actions Secrets " + ", ".join(missing), flush=True)
        summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary_file:
            with open(summary_file, "a", encoding="utf-8") as out:
                out.write("\n### 郵件尚未設定\n請先加入 GitHub Secrets：" + ", ".join(missing) + "\n")
        return 0

    trade_date = send_report(
        paths[0], paths[1], paths[2],
        sender=sender, password=password, recipient=recipient
    )
    print(f"EMAIL SENT: verified report date {trade_date}; recipient configured. SMTP accepted message.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
