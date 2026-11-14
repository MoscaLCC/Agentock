"""Cliente mínimo da API do Telegram (texto, foto com legenda, botões inline, callbacks). Sem dependências extra."""
import json
import urllib.parse
import urllib.request
import uuid


def keyboard(rows: list[list[tuple[str, str]]]) -> dict:
    """[[('🧾 Razões', 'callback'), ...], ...] → reply_markup inline (callback_data ≤ 64 bytes)."""
    for row in rows:
        for _label, data in row:
            if len(data.encode()) > 64:
                raise ValueError(f"callback_data com mais de 64 bytes: {data}")
    return {"inline_keyboard": [[{"text": label, "callback_data": data} for label, data in row] for row in rows]}


def _multipart(fields: dict, files: dict) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    out = bytearray()
    for k, v in fields.items():
        out += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
    for k, (filename, content, ctype) in files.items():
        out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{filename}\"\r\n"
                f"Content-Type: {ctype}\r\n\r\n").encode() + content + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


class TelegramAPI:
    def __init__(self, token: str, chat_id: str):
        self.base = f"https://api.telegram.org/bot{token}/"
        self.chat_id = str(chat_id)

    def call(self, method: str, http_timeout: int = 60, **params):
        """params são os da API do Telegram (ex.: getUpdates tem o seu próprio 'timeout' de long polling)."""
        data = urllib.parse.urlencode(params).encode()
        with urllib.request.urlopen(self.base + method, data, timeout=http_timeout) as r:
            return json.load(r)

    def send_message(self, text: str, html: bool = False, buttons: dict | None = None) -> bool:
        p = {"chat_id": self.chat_id, "text": text, "disable_web_page_preview": "true"}
        if html:
            p["parse_mode"] = "HTML"
        if buttons:
            p["reply_markup"] = json.dumps(buttons)
        return bool(self.call("sendMessage", **p).get("ok"))

    def send_photo(self, png: bytes, caption: str = "", html: bool = False, buttons: dict | None = None) -> bool:
        fields = {"chat_id": self.chat_id, "caption": caption[:1024]}
        if html:
            fields["parse_mode"] = "HTML"
        if buttons:
            fields["reply_markup"] = json.dumps(buttons)
        body, ctype = _multipart(fields, {"photo": ("cartao.png", png, "image/png")})
        req = urllib.request.Request(self.base + "sendPhoto", body, {"Content-Type": ctype})
        with urllib.request.urlopen(req, timeout=60) as r:
            return bool(json.load(r).get("ok"))

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        self.call("answerCallbackQuery", callback_query_id=callback_id, text=text)
