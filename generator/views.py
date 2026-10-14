import base64
import io
import json

import segno
from django.core.exceptions import RequestDataTooBig
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

from .validation import MAX_URL_LENGTH, ValidationError, parse_request

MIME_TYPES = {"png": "image/png", "svg": "image/svg+xml"}
QUIET_ZONE = 4  # modules of white border the QR standard asks for


def _error(status, code, message, field=None, headers=None):
    body = {"error": {"code": code, "message": message}}
    if field:
        body["error"]["field"] = field
    response = JsonResponse(body, status=status, json_dumps_params={"ensure_ascii": False})
    for key, value in (headers or {}).items():
        response[key] = value
    return response


def render_qr(req):
    """Encode one validated request. Returns (image bytes, segno.QRCode)."""
    qr = segno.make_qr(req.url, error=req.error, boost_error=False)
    buffer = io.BytesIO()
    if req.format == "png":
        qr.save(buffer, kind="png", scale=req.scale, border=QUIET_ZONE)
    else:
        qr.save(buffer, kind="svg", scale=req.scale, border=QUIET_ZONE, xmldecl=False, title="QR code")
    return buffer.getvalue(), qr


@require_GET
def index(request):
    return render(request, "generator/index.html", {"max_url_length": MAX_URL_LENGTH})


@require_GET
def health(request):
    return JsonResponse({"status": "ok"})


# The API is stateless and reads no cookies or credentials, so a forged cross-site request can do nothing a direct
# one cannot. Exempting it lets other internal systems call it without a CSRF token.
@csrf_exempt
def qr_api(request):
    """POST /api/qr

    Request (JSON): {"url": "https://...", "format": "png"|"svg", "error_correction": "L"|"M"|"Q"|"H",
                     "scale": 1-40}
    Response (JSON): the image as a base64 data URI plus what was encoded and how.
    """
    if request.method != "POST":
        return _error(405, "method_not_allowed", "Use POST.", headers={"Allow": "POST"})

    if request.content_type != "application/json":
        return _error(415, "unsupported_media_type", "Send the request body as application/json.")

    try:
        raw = request.body
    except RequestDataTooBig:
        return _error(413, "body_too_large", "The request body is too large.")

    try:
        data = json.loads(raw.decode(request.encoding or "utf-8"))
    except (UnicodeDecodeError, ValueError):
        return _error(400, "invalid_json", "The request body is not valid JSON.")

    try:
        req = parse_request(data)
    except ValidationError as exc:
        return _error(400, exc.code, exc.message, exc.field)

    try:
        image, qr = render_qr(req)
    except segno.DataOverflowError:
        return _error(400, "url_too_long", "The link is too long to fit in a QR code at this error correction level.",
                      "url")

    width = qr.symbol_size(scale=1, border=0)[0]
    return JsonResponse(
        {
            "url": req.url,
            "format": req.format,
            "mime_type": MIME_TYPES[req.format],
            "data_uri": f"data:{MIME_TYPES[req.format]};base64,{base64.b64encode(image).decode('ascii')}",
            "bytes": len(image),
            "version": qr.version,
            "error_correction": qr.error,
            "modules": width,
            "size_px": (width + 2 * QUIET_ZONE) * req.scale,
        },
        json_dumps_params={"ensure_ascii": False},
    )
