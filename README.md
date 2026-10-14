# Suwon Immigration QR Generator

A small QR code service for sharing file links. Staff paste a link, the server turns it into a QR code, and they save
it as PNG or SVG to print or hand out. Everything runs on the machine that hosts it: no paid QR service, no CDN, no
third-party API.

![The generator after creating a QR code](demo/screens/04-success.png)

## Project Overview
This project was developed during my service as a Public Service Officer at the **Suwon Immigration Office (Ministry of Justice)**. It aims to efficiently distribute digital media to participants of citizenship ceremonies through a secure, localized system.

### Key Problems Solved
- **Cost Reduction**: Eliminated the need for recurring subscription fees to commercial QR generation services by implementing an in-house solution.
- **Privacy & Security**: Developed a **standalone tool** that operates entirely on local hardware, ensuring 100% compliance with government security protocols and preventing unauthorized data leaks to external servers.
- **Operational Efficiency**: Digitized the manual, paper-based attendee tracking and distribution process, significantly reducing administrative overhead and wait times.

## Two versions in this repository

| Version | Files | What it is |
| --- | --- | --- |
| Original static tool (February 2026) | `index.html`, `qrcode.min.js` | One HTML page that draws the QR code in the browser with the open-source qrcode.js library. Kept unchanged for reference. |
| Django API version (October 2026) | `qrservice/`, `generator/`, `manage.py` | A **rewrite** of the original tool. QR codes are generated on the server by a JSON API, and a redesigned page calls it. |

The rewrite keeps the original purpose and the Korean interface, and moves the encoding behind an HTTP API so other
internal tools can request a QR code the same way the page does.

## Tech stack (Django API version)

- **Python 3.14, Django 6.0**: a stateless service, with no database, sessions or accounts.
- **segno**: QR encoding on the server (PNG and SVG), no image library needed.
- **Vanilla HTML, CSS and JavaScript** for the page, served by Django: system fonts, a strict Content Security Policy, and nothing loaded from other hosts.
- **WhiteNoise and gunicorn** for the Docker image.

## Running it locally

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py runserver
```

Open http://127.0.0.1:8000. Development mode (`DJANGO_DEBUG=1`) is the default, and it needs no other settings.

Run the tests:

```sh
.venv/bin/python manage.py test
```

### With Docker

```sh
docker build -t qr-generator .
docker run --rm -p 8000:8000 \
  -e DJANGO_SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(50))')" \
  -e DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1 \
  qr-generator
```

The image runs with `DJANGO_DEBUG=0`, gunicorn on port 8000, and a non-root user. Behind HTTPS, also consider setting
`SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS` and `CSRF_COOKIE_SECURE` (the warnings from `manage.py check --deploy`).
They are left off because an office intranet deployment may be plain HTTP.

| Variable | Default | Meaning |
| --- | --- | --- |
| `DJANGO_DEBUG` | `1` | `0` in production |
| `DJANGO_SECRET_KEY` | random per process in development | required when `DJANGO_DEBUG=0` |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | comma-separated host names |

## API

### `POST /api/qr`

Request body (`Content-Type: application/json`):

| Field | Required | Values | Default |
| --- | --- | --- | --- |
| `url` | yes | an absolute `http://` or `https://` link, up to 1024 characters | |
| `format` | no | `png` or `svg` | `png` |
| `error_correction` | no | `L` (7%), `M` (15%), `Q` (25%), `H` (30%) | `M` |
| `scale` | no | pixels per module, 1 to 40 | `10` |

```sh
curl -s -X POST http://127.0.0.1:8000/api/qr \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://github.com/JihoonChoi1/Suwon-Immigration-QR-Generator"}'
```

Response `200` (recorded from a real run; `data_uri` shortened here):

```json
{
  "url": "https://github.com/JihoonChoi1/Suwon-Immigration-QR-Generator",
  "format": "png",
  "mime_type": "image/png",
  "data_uri": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAZ...",
  "bytes": 600,
  "version": 4,
  "error_correction": "M",
  "modules": 33,
  "size_px": 410
}
```

Errors return a status code and a stable `code`:

```json
{ "error": { "code": "missing_scheme", "message": "The link must start with http:// or https://.", "field": "url" } }
```

| Status | `code` | When |
| --- | --- | --- |
| 400 | `missing_url` | no `url`, or only whitespace |
| 400 | `missing_scheme` | `example.com/a`, `localhost:8000/a` |
| 400 | `unsupported_scheme` | `javascript:`, `ftp:`, `file:`, `data:`, `mailto:` … |
| 400 | `invalid_url` | no host, a bad host name or port, or spaces and control characters |
| 400 | `url_too_long` | more than 1024 characters |
| 400 | `credentials_in_url` | `https://user:password@host/…` (it would be printed on paper) |
| 400 | `invalid_option` | a bad `format`, `error_correction` or `scale` |
| 400 | `invalid_json`, `invalid_body` | the body is not a JSON object |
| 405 | `method_not_allowed` | anything but POST |
| 413 | `body_too_large` | a body over 16 KB |
| 415 | `unsupported_media_type` | not `application/json` |

Intranet links such as `http://fileserver/share/video.mp4` and IP addresses are accepted on purpose: office file
servers often have no public domain name. The API keeps no state and reads no cookies, so it does not require a CSRF
token.

### `GET /api/health`

Returns `{"status": "ok"}` (for container health checks).

## Project layout

```
manage.py
qrservice/            settings, URLs, WSGI
generator/
  validation.py       input rules (scheme, host, length, options)
  views.py            the page, POST /api/qr, GET /api/health
  tests.py            Django test runner tests
  templates/generator/index.html
  static/generator/   app.css, app.js, favicon.svg
demo/                 screenshots and the script that captured them
index.html, qrcode.min.js   the original static tool
```

## Third-party code

- [segno](https://github.com/heuer/segno) (BSD-3-Clause), [Django](https://www.djangoproject.com/) (BSD-3-Clause),
  [WhiteNoise](https://github.com/evansd/whitenoise) (MIT), [gunicorn](https://gunicorn.org/) (MIT).
- `qrcode.min.js`, used only by the original static page, is [QRCode.js](https://github.com/davidshimjs/qrcodejs)
  by davidshimjs (MIT).
