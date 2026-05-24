"""
Vercel serverless function — Telegram webhook handler (Flask/WSGI).

Receives Telegram updates and processes bot commands:
  /scan  — triggers the GitHub Actions scanner workflow
  /help  — shows available commands

Required Vercel environment variables:
  TELEGRAM_TOKEN   — bot token from @BotFather
  TELEGRAM_CHAT_ID — your personal chat ID (only this ID is accepted)
  GITHUB_PAT       — fine-grained PAT with Actions: write scope
"""
import json
import os

import requests
from flask import Flask, Response, request

app = Flask(__name__)   # Vercel WSGI entry point

GITHUB_REPO = "hdra22/trading-scanner"
WORKFLOW    = "scanner.yml"
BRANCH      = "master"


def _trigger_scan(github_pat: str) -> bool:
    r = requests.post(
        f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/{WORKFLOW}/dispatches",
        headers={
            "Authorization":        f"Bearer {github_pat}",
            "Accept":               "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json={"ref": BRANCH},
        timeout=10,
    )
    return r.status_code == 204


def _send(token: str, chat_id: str, text: str) -> None:
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
        timeout=10,
    )


@app.route("/", methods=["GET"])
@app.route("/webhook", methods=["GET"])
def health():
    return "Trading Scanner Webhook — OK"


@app.route("/", methods=["POST"])
@app.route("/webhook", methods=["POST"])
def webhook():
    # Always return 200 immediately — Telegram stops retrying on 200
    try:
        body = request.get_json(force=True, silent=True) or {}
    except Exception:
        return Response("OK", 200)

    token      = os.environ.get("TELEGRAM_TOKEN", "")
    allowed_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    github_pat = os.environ.get("GITHUB_PAT", "")

    msg     = body.get("message", {})
    text    = (msg.get("text") or "").strip()
    chat_id = str(msg.get("chat", {}).get("id", ""))

    if not text or chat_id != allowed_id:
        return Response("OK", 200)

    if text.startswith("/scan"):
        _send(token, chat_id, "⏳ A disparar scanner...")
        if _trigger_scan(github_pat):
            _send(
                token, chat_id,
                "✅ <b>Scanner em execução!</b>\n"
                "Resultados chegam em ~2 minutos via Telegram.",
            )
        else:
            _send(token, chat_id, "❌ Erro ao disparar scanner. Verifica o GITHUB_PAT.")

    elif text.startswith("/help") or text.startswith("/start"):
        _send(
            token, chat_id,
            "🤖 <b>Trading Scanner Bot</b>\n\n"
            "  /scan — dispara o scanner agora\n"
            "  /help — mostra esta ajuda\n\n"
            "⏰ <b>Automático:</b> 0h05, 4h05, 8h05, 12h05, 16h05, 20h05 (PT)\n"
            "📊 Dashboard disponível no Streamlit Cloud.",
        )

    else:
        _send(token, chat_id, "❓ Comando desconhecido. Usa /help para ver os comandos disponíveis.")

    return Response("OK", 200)
