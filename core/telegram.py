"""Cliente da API do Telegram (texto, foto, edição, botões inline, callbacks). Sem dependências extra.

Robustez (Fase 10): 429 espera o `retry_after` pedido pelo Telegram; erros de rede têm 3 tentativas; um 400 por HTML
inválido reenvia em texto simples (uma mensagem feia é melhor do que uma análise paga que não chega); mensagens
longas são partidas em linhas inteiras; o token nunca aparece nos erros.
"""
import html as _html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

MAX_TEXT, MAX_CAPTION, CHUNK = 4096, 1024, 3800


class TelegramError(Exception):
    def __init__(self, code: int, description: str, retry_after: float | None = None):
        super().__init__(f"Telegram {code}: {description}")
        self.code, self.description, self.retry_after = code, description, retry_after


def keyboard(rows: list[list[tuple[str, str]]]) -> dict:
    """[[('🧾 Razões', 'callback'), ...], ...] → reply_markup inline (callback_data ≤ 64 bytes)."""
    for row in rows:
        for _label, data in row:
            if len(data.encode()) > 64:
                raise ValueError(f"callback_data com mais de 64 bytes: {data}")
    return {"inline_keyboard": [[{"text": label, "callback_data": data} for label, data in row] for row in rows if row]}


def strip_html(text: str) -> str:
    return _html.unescape(re.sub(r"<[^>]+>", "", text))


def chunks(text: str, limit: int = CHUNK) -> list[str]:
    """Parte em blocos ≤ limit, sempre em fim de linha. Um <pre> que atravesse o corte é fechado e reaberto;
    uma linha maior do que o limite é partida em espaços."""
    out, cur, in_pre = [], "", False
    for line in text.split("\n"):
        while len(line) > limit:                       # linha gigante: corta em espaço
            cut = line.rfind(" ", 0, limit)
            cut = cut if cut > limit // 2 else limit
            head, line = line[:cut], line[cut:].lstrip()
            if cur.strip():
                out.append(cur + ("</pre>" if in_pre else ""))
                cur = "<pre>" if in_pre else ""
            out.append(head)
        if len(cur) + len(line) + 1 > limit and cur.strip():
            out.append(cur + ("</pre>" if in_pre else ""))
            cur = "<pre>" if in_pre else ""
        cur += line + "\n"
        opens, closes = line.count("<pre>"), line.count("</pre>")
        if opens != closes:
            in_pre = opens > closes
    if cur.strip():
        out.append(cur)
    return [c.rstrip("\n") for c in out]


def fit_caption(caption: str, limit: int = MAX_CAPTION) -> str:
    """Legenda ≤ 1024 sem cortar a meio de uma etiqueta: tira linhas do fim até caber."""
    if len(caption) <= limit:
        return caption
    lines = caption.split("\n")
    while lines and len("\n".join(lines)) > limit - 2:
        lines.pop()
    text = "\n".join(lines).rstrip()
    for tag in ("b", "i", "pre", "a"):                 # fecha o que ficou aberto
        if text.count(f"<{tag}") > text.count(f"</{tag}>"):
            text += f"</{tag}>"
    return (text + "\n…")[:limit]


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
    def __init__(self, token: str, chat_id: str, *, retries: int = 3, sleep=time.sleep):
        self.base = f"https://api.telegram.org/bot{token}/"
        self.chat_id = str(chat_id)
        self._token, self.retries, self._sleep = token, retries, sleep

    def redact(self, text: str) -> str:
        return str(text).replace(self._token, "<token>") if self._token else str(text)

    # ------------------------------------------------------------------ transporte
    def _open(self, req, timeout: float):
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)

    def _request(self, method: str, data: bytes | None, headers: dict | None, http_timeout: float):
        """Uma chamada com tratamento de 429 e de falhas de rede. Devolve o `result` da resposta."""
        last = None
        for attempt in range(self.retries):
            try:
                req = urllib.request.Request(self.base + method, data, headers or {})
                out = self._open(req, http_timeout)
                if out.get("ok"):
                    return out.get("result")
                raise TelegramError(out.get("error_code", 0), out.get("description", "erro"),
                                    (out.get("parameters") or {}).get("retry_after"))
            except urllib.error.HTTPError as e:
                try:
                    body = json.loads(e.read().decode("utf-8", "replace"))
                except Exception:  # noqa: BLE001
                    body = {}
                err = TelegramError(e.code, body.get("description") or e.reason or "erro HTTP",
                                    (body.get("parameters") or {}).get("retry_after"))
                if e.code == 429 and attempt < self.retries - 1:
                    self._sleep(min(float(err.retry_after or 2), 30))
                    last = err
                    continue
                if 500 <= e.code < 600 and attempt < self.retries - 1:
                    self._sleep(1.5 * (attempt + 1))
                    last = err
                    continue
                raise err from None
            except TelegramError as e:
                if e.code == 429 and attempt < self.retries - 1:
                    self._sleep(min(float(e.retry_after or 2), 30))
                    last = e
                    continue
                raise
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                last = TelegramError(0, f"sem ligação ao Telegram ({type(e).__name__})")
                if attempt < self.retries - 1:
                    self._sleep(1.5 * (attempt + 1))
        raise last

    def call(self, method: str, http_timeout: float = 60, **params):
        """params são os da API do Telegram (ex.: getUpdates tem o seu próprio 'timeout' de long polling).
        Devolve o envelope {"ok": True, "result": ...} (compatível com o código anterior)."""
        result = self._request(method, urllib.parse.urlencode(params).encode(), None, http_timeout)
        return {"ok": True, "result": result}

    # ------------------------------------------------------------------ mensagens
    def _text_params(self, text: str, html: bool, buttons: dict | None) -> dict:
        p = {"chat_id": self.chat_id, "text": text, "disable_web_page_preview": "true"}
        if html:
            p["parse_mode"] = "HTML"
        if buttons:
            p["reply_markup"] = json.dumps(buttons)
        return p

    def send_message(self, text: str, html: bool = False, buttons: dict | None = None) -> dict | None:
        """Envia (partindo em blocos se for preciso; os botões vão no último). Devolve a última mensagem enviada.
        HTML recusado pelo Telegram (400) → o mesmo texto sem formatação."""
        parts, sent = chunks(text) or [""], None
        for i, part in enumerate(parts):
            kb = buttons if i == len(parts) - 1 else None
            try:
                sent = self._request("sendMessage", urllib.parse.urlencode(self._text_params(part, html, kb)).encode(),
                                     None, 60)
            except TelegramError as e:
                if e.code != 400 or not html:
                    raise
                sent = self._request("sendMessage", urllib.parse.urlencode(
                    self._text_params(strip_html(part), False, kb)).encode(), None, 60)
        return sent

    def edit_message(self, message_id: int, text: str, html: bool = False, buttons: dict | None = None) -> bool:
        """Edita uma mensagem de texto. False se já não der para editar (apagada, antiga) — o chamador envia uma nova."""
        p = self._text_params(text[:MAX_TEXT], html, buttons)
        p["message_id"] = message_id
        try:
            self._request("editMessageText", urllib.parse.urlencode(p).encode(), None, 60)
            return True
        except TelegramError as e:
            if "not modified" in e.description:
                return True
            if e.code == 400 and html and "parse" in e.description.lower():
                p = self._text_params(strip_html(text)[:MAX_TEXT], False, buttons)
                p["message_id"] = message_id
                try:
                    self._request("editMessageText", urllib.parse.urlencode(p).encode(), None, 60)
                    return True
                except TelegramError:
                    return False
            return False

    def send_photo(self, png: bytes, caption: str = "", html: bool = False, buttons: dict | None = None) -> dict | None:
        fields = {"chat_id": self.chat_id, "caption": fit_caption(caption)}
        if html:
            fields["parse_mode"] = "HTML"
        if buttons:
            fields["reply_markup"] = json.dumps(buttons)
        try:
            body, ctype = _multipart(fields, {"photo": ("cartao.png", png, "image/png")})
            return self._request("sendPhoto", body, {"Content-Type": ctype}, 90)
        except TelegramError as e:
            if e.code != 400 or not html:
                raise
            fields.pop("parse_mode", None)
            fields["caption"] = strip_html(fields["caption"])[:MAX_CAPTION]
            body, ctype = _multipart(fields, {"photo": ("cartao.png", png, "image/png")})
            return self._request("sendPhoto", body, {"Content-Type": ctype}, 90)

    def chat_action(self, action: str = "typing") -> None:
        try:
            self._request("sendChatAction", urllib.parse.urlencode({"chat_id": self.chat_id, "action": action}).encode(),
                          None, 15)
        except TelegramError:
            pass  # é só o "a escrever…"

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        try:
            self._request("answerCallbackQuery", urllib.parse.urlencode(
                {"callback_query_id": callback_id, "text": text[:190]}).encode(), None, 15)
        except TelegramError:
            pass  # toque antigo (o Telegram só aceita a resposta durante uns segundos): segue-se na mesma
