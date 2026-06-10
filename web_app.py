#!/usr/bin/env python3
"""Local web interface for the Texas Hold'em GTO/EV calculator."""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import subprocess
import tempfile
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from gto_ev import calculate, parse_cards


ROOT = Path(__file__).resolve().parent
STATIC_ROOT = ROOT / "web"
ENV_FILE = ROOT / ".env"
WINDOWS_OCR_SCRIPT = ROOT / "windows_ocr.ps1"
VISION_FIELDS = (
    "players",
    "position",
    "hand",
    "board",
    "pot",
    "to_call",
    "raise_size",
)


def load_local_env() -> None:
    """Load local config without requiring python-dotenv."""
    if not ENV_FILE.is_file():
        return
    for raw_line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if name in {"AI_API_KEY", "AI_MODEL", "AI_BASE_URL"} and value:
            os.environ[name] = value


def ai_status() -> dict:
    load_local_env()
    missing = [name for name in ("AI_API_KEY", "AI_MODEL") if not os.environ.get(name)]
    model = os.environ.get("AI_MODEL")
    warnings = []
    if model and any(character.isspace() for character in model):
        warnings.append("AI_MODEL 包含空格，通常不是有效模型 ID")
    return {
        "configured": not missing,
        "usable": not missing and not warnings,
        "missing": missing,
        "warnings": warnings,
        "model": model,
        "base_url": os.environ.get("AI_BASE_URL", "https://api.openai.com/v1"),
        "endpoint": chat_completions_url(),
        "config_source": ".env" if ENV_FILE.is_file() else "environment",
    }


def chat_completions_url() -> str:
    base_url = os.environ.get("AI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    return base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"


def optional_float(payload: dict, name: str) -> float | None:
    value = payload.get(name)
    return None if value in (None, "") else float(value)


def calculate_request(payload: dict) -> dict:
    result = calculate(
        players=int(payload.get("players", 6)),
        position=str(payload.get("position", "BTN")),
        hand=parse_cards(str(payload.get("hand", ""))),
        board=parse_cards(str(payload.get("board", ""))),
        strategy=str(payload.get("strategy", "balanced")),
        opponent_range=optional_float(payload, "opponent_range"),
        fold_to_raise=optional_float(payload, "fold_to_raise"),
        pot=float(payload.get("pot", 1.5)),
        to_call=float(payload.get("to_call", 0)),
        raise_size=float(payload.get("raise_size", 3)),
        simulations=int(payload.get("simulations", 5000)),
        seed=int(payload["seed"]) if payload.get("seed") not in (None, "") else None,
    )
    data = asdict(result)
    data["strategy_script"] = generate_strategy_script(data)
    return data


def generate_strategy_script(result: dict) -> str:
    action_names = {
        "fold": "弃牌",
        "check": "过牌",
        "call": "跟注",
        "bet": "下注",
        "raise": "加注",
    }
    best = result["recommended_action"]
    lines = [
        "# 单节点策略脚本",
        (
            f"WHEN players={result['players']} AND position={result['position']} "
            f"AND hand=\"{' '.join(result['hand'])}\" "
            f"AND board=\"{' '.join(result['board']) or '-'}\""
        ),
        f"THEN {best.upper()}  # {action_names.get(best, best)}",
        "",
        "MIX:",
    ]
    for action, frequency in result["mixed_strategy"].items():
        lines.append(
            f"  {action.upper():<6} {frequency * 100:>6.2f}%"
            f"  EV={result['action_ev'][action]:+.4f} BB"
        )
    lines.append("")
    raise_range = result.get("raise_recommendation")
    if raise_range:
        lines.extend(
            [
                (
                    "RAISE_RANGE "
                    f"total={raise_range['total_range'] * 100:.2f}% "
                    f"value={raise_range['value_range'] * 100:.2f}% "
                    f"bluff={raise_range['bluff_range'] * 100:.2f}% "
                    f"size={raise_range['recommended_size']:.2f}BB"
                ),
                "",
            ]
        )
    lines.append(
        f"META equity={result['equity'] * 100:.2f}% "
        f"range={result['opponent_range'] * 100:.2f}% "
        f"fold_to_raise={result['fold_to_raise'] * 100:.2f}% "
        f"simulations={result['simulations']}"
    )
    return "\n".join(lines)


def ai_configured() -> bool:
    return ai_status()["usable"]


def parse_ai_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("AI 未返回可解析的 JSON")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("AI 返回内容必须是 JSON 对象")
    return {key: data[key] for key in VISION_FIELDS if data.get(key) not in (None, "")}


def recognize_image_with_ai(image_data_url: str) -> dict:
    if not ai_configured():
        raise ValueError("AI API 未配置，请设置 AI_API_KEY 和 AI_MODEL")
    if not image_data_url.startswith("data:image/"):
        raise ValueError("仅支持图片 Data URL")
    encoded = image_data_url.partition(",")[2]
    if not encoded:
        raise ValueError("图片数据为空")
    try:
        image_bytes = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise ValueError("图片 Base64 数据无效") from exc
    if len(image_bytes) > 8_000_000:
        raise ValueError("截图不能超过 8 MB")

    prompt = (
        "Analyze this Texas Hold'em table screenshot. Return JSON only. "
        "Extract only values clearly visible in the screenshot. Use card notation As Kh, "
        "positions UTG/UTG+1/MP/HJ/CO/BTN/SB/BB, and numeric chip values in BB when visible. "
        'Schema: {"players": number|null, "position": string|null, "hand": string|null, '
        '"board": string|null, "pot": number|null, "to_call": number|null, '
        '"raise_size": number|null}. Do not guess unclear values.'
    )
    body = json.dumps(
        {
            "model": os.environ["AI_MODEL"],
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_data_url}},
                    ],
                }
            ],
            "temperature": 0,
            "max_tokens": 400,
        }
    ).encode("utf-8")
    request = Request(
        chat_completions_url(),
        data=body,
        headers={
            "Authorization": f"Bearer {os.environ['AI_API_KEY']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=45) as response:
            payload = json.loads(response.read())
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise ValueError(f"AI API 返回 HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise ValueError(f"无法连接 AI API: {exc.reason}") from exc
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("AI API 返回格式不兼容") from exc
    return parse_ai_json(content)


def decode_image_data_url(image_data_url: str) -> tuple[bytes, str]:
    if not image_data_url.startswith("data:image/"):
        raise ValueError("仅支持图片 Data URL")
    header, _, encoded = image_data_url.partition(",")
    if not encoded:
        raise ValueError("图片数据为空")
    try:
        image_bytes = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise ValueError("图片 Base64 数据无效") from exc
    if len(image_bytes) > 8_000_000:
        raise ValueError("截图不能超过 8 MB")
    extension = ".png" if "png" in header.lower() else ".jpg"
    return image_bytes, extension


def windows_ocr_available() -> bool:
    return os.name == "nt" and WINDOWS_OCR_SCRIPT.is_file()


def recognize_image_with_windows_ocr(image_data_url: str) -> str:
    if not windows_ocr_available():
        raise ValueError("Windows 本地 OCR 不可用")
    image_bytes, extension = decode_image_data_url(image_data_url)
    image_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=extension, delete=False) as image_file:
            image_file.write(image_bytes)
            image_path = image_file.name
        process = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(WINDOWS_OCR_SCRIPT),
                "-ImagePath",
                image_path,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=45,
            check=False,
        )
        if process.returncode:
            detail = (process.stderr or process.stdout).strip()[:400]
            raise ValueError(f"Windows OCR 失败: {detail}")
        return process.stdout.strip()
    except subprocess.TimeoutExpired as exc:
        raise ValueError("Windows OCR 处理超时") from exc
    finally:
        if image_path:
            Path(image_path).unlink(missing_ok=True)


class AppHandler(BaseHTTPRequestHandler):
    server_version = "GtoEvWeb/1.0"

    def send_json(self, data: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        request_path = urlparse(self.path).path
        if request_path not in ("/api/calculate", "/api/vision", "/api/ocr"):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 12_000_000:
                raise ValueError("请求内容过大")
            payload = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(payload, dict):
                raise ValueError("请求必须是 JSON 对象")
            if request_path == "/api/vision":
                state = recognize_image_with_ai(str(payload.get("image", "")))
                self.send_json({"ok": True, "state": state})
            elif request_path == "/api/ocr":
                text = recognize_image_with_windows_ocr(str(payload.get("image", "")))
                self.send_json({"ok": True, "text": text})
            else:
                self.send_json({"ok": True, "result": calculate_request(payload)})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception:
            self.send_json(
                {"ok": False, "error": "计算失败，请检查输入后重试。"},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def do_GET(self) -> None:
        request_path = urlparse(self.path).path
        if request_path == "/api/health":
            status = ai_status()
            self.send_json(
                {
                    "ok": True,
                    "ai_configured": status["usable"],
                    "ai": status,
                    "windows_ocr_available": windows_ocr_available(),
                }
            )
            return

        relative = "index.html" if request_path in ("", "/") else request_path.lstrip("/")
        candidate = (STATIC_ROOT / relative).resolve()
        if STATIC_ROOT.resolve() not in candidate.parents or not candidate.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        body = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in ("application/javascript",):
            content_type += "; charset=utf-8"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        print(f"[web] {self.address_string()} - {format % args}")


def main() -> int:
    parser = argparse.ArgumentParser(description="启动德州扑克 GTO/EV 浏览器界面")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), AppHandler)
    print(f"GTO/EV Web UI: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
