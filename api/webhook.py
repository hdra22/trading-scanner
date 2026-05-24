"""
Vercel serverless function — Telegram webhook handler.

Receives Telegram updates and processes bot commands:
  /scan  — triggers the GitHub Actions scanner workflow
  /help  — shows available commands

Required environment variables (set in Vercel project settings):
  TELEGRAM_TOKEN   — bot token from @BotFather
  TELEGRAM_CHAT_ID — your personal chat ID (only this ID is accepted)
  GITHUB_PAT       — fine-grained PAT with Actions: write + Contents: read
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import requests  # available via requirements.txt

GITHUB_REPO = "hdra22/trading-scanner"
WORKFLOW    = "scanner.yml"
BRANCH      = "master"


def _trigger_scan(github_pat: str) -> bool:
    """Dispatch workflow_dispatch event on the scanner workflow."""
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
    """Send a Telegram message (HTML parse mode)."""
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
        timeout=10,
    )


class handler(BaseHTTPRequestHandler):
    """Vercel Python runtime entry point."""

    # ── health check ──────────────────────────────────────────────────────────
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Trading Scanner Webhook — OK")

    # ── Telegram update ───────────────────────────────────────────────────────
    def do_POST(self):
        # Always respond 200 immediately so Telegram doesn't retry
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

        # Parse body
        try:
            length = int(self.headers.get("content-length", 0))
            body   = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return

        token      = os.environ.get("TELEGRAM_TOKEN", "")
        allowed_id = os.environ.get("TELEGRAM_CHAT_ID", "")
        github_pat = os.environ.get("GITHUB_PAT", "")

        msg     = body.get("message", {})
        text    = (msg.get("text") or "").strip()
        chat_id = str(msg.get("chat", {}).get("id", ""))

        # Ignore messages from other chats
        if not text or chat_id != allowed_id:
            return

        # ── command router ───────────────────────────────────────────────────
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
            _send(
                token, chat_id,
                "❓ Comando desconhecido. Usa /help para ver os comandos disponíveis.",
            )

    def log_message(self, *args):
        pass  # suppress default stderr logging
