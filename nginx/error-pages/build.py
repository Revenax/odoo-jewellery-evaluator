# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Build the Revenax-branded nginx error pages (500/502/503/504).

Each page is ONE self-contained HTML file (logo SVG and the Fractul font are
inlined) because it is shown exactly when the app behind nginx is down, so it
cannot load anything from it.

    python3 nginx/error-pages/build.py      # writes nginx/error-pages/html/*.html

Branding is read from the Revenax-Landing repo (REVENAX_LANDING, default
~/Projects/Revenax-Landing). Install on the server with
scripts/install-error-pages.sh.
"""

import base64
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
LANDING = Path(os.environ.get('REVENAX_LANDING', Path.home() / 'Projects/Revenax-Landing'))

WHATSAPP_URL = 'https://wa.me/201063864994'
WHATSAPP_DISPLAY = '+20 106 386 4994'
EMAIL = 'info@revenax.com'

PAGES = {
    500: {
        'title': 'Something went wrong',
        'lead': 'The system hit an unexpected error while handling your request.',
    },
    502: {
        'title': 'The system is restarting',
        'lead': 'The system is not answering right now. It usually comes back on its own within a minute.',
    },
    503: {
        'title': 'Down for a moment',
        'lead': 'The system is briefly unavailable, often for an update. It should be back in a minute or two.',
    },
    504: {
        'title': 'This is taking too long',
        'lead': 'The system took too long to answer. It may be busy or restarting.',
    },
}

RETRY_SECONDS = 30

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{code} · {title} · Revenax</title>
<style>
@font-face {{ font-family: "Fractul"; src: url(data:font/otf;base64,{font}) format("opentype"); font-display: swap; }}
:root {{
  --ink: #353535; --muted: rgba(53,53,53,.72); --line: rgba(53,53,53,.12);
  --blue: #3E84FF; --blue-soft: rgba(62,132,255,.10); --coral: #FF7B87; --cyan: #E5F9FF;
  --bg: #ffffff; --card: rgba(255,255,255,.78);
}}
@media (prefers-color-scheme: dark) {{
  :root {{ --ink: #F2F2F2; --muted: rgba(242,242,242,.72); --line: rgba(255,255,255,.12);
          --blue-soft: rgba(62,132,255,.18); --bg: #17181B; --card: rgba(30,31,35,.82); }}
}}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; height: 100%; overflow: hidden; }}
body {{
  height: 100vh; height: 100dvh; display: flex; flex-direction: column; align-items: center; justify-content: center;
  padding: 16px; color: var(--ink); background: var(--bg);
  font: 16px/1.6 Poppins, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  background-image:
    radial-gradient(40rem 28rem at 12% 8%, rgba(62,132,255,.16), transparent 60%),
    radial-gradient(34rem 26rem at 92% 90%, rgba(255,123,135,.16), transparent 60%),
    radial-gradient(30rem 22rem at 85% 10%, rgba(229,249,255,.55), transparent 60%);
}}
main {{ width: 100%; max-width: 620px; text-align: center; }}
.logo {{ width: clamp(120px, 20vh, 170px); max-width: 60%; height: auto; color: var(--ink); margin-bottom: clamp(12px, 4vh, 32px); }}
.badge {{
  display: inline-flex; align-items: center; gap: 8px; padding: 6px 14px; border-radius: 999px;
  background: var(--blue-soft); color: var(--blue); font-size: 12px; font-weight: 600;
  letter-spacing: .14em; text-transform: uppercase;
}}
.dot {{ width: 8px; height: 8px; border-radius: 50%; background: var(--blue); animation: pulse 1.6s ease-in-out infinite; }}
@keyframes pulse {{ 50% {{ opacity: .3; }} }}
@media (prefers-reduced-motion: reduce) {{ .dot {{ animation: none; }} }}
h1 {{ font-family: "Fractul", Poppins, system-ui, sans-serif; font-weight: 800; font-size: clamp(28px, min(7vw, 6vh), 52px);
      line-height: 1.05; letter-spacing: -.02em; margin: clamp(10px, 2.5vh, 20px) 0 clamp(6px, 1.5vh, 12px); }}
.lead {{ color: var(--muted); font-size: 15px; line-height: 1.5; margin: 0 auto clamp(12px, 3vh, 24px); max-width: 30em; }}
.card {{ background: var(--card); border: 1px solid var(--line); border-radius: 16px; padding: clamp(12px, 2.5vh, 20px) 20px;
         text-align: left; backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px); }}
.card h2 {{ font-size: 13px; letter-spacing: .12em; text-transform: uppercase; color: var(--muted); margin: 0 0 12px; font-weight: 600; }}
ol {{ margin: 0; padding-left: 22px; }}
li {{ margin: 4px 0; font-size: 15px; }}
li strong {{ font-weight: 600; }}
.actions {{ display: flex; flex-wrap: nowrap; gap: 12px; justify-content: center; margin: clamp(12px, 3vh, 24px) 0 6px; }}
.btn {{ display: inline-flex; align-items: center; justify-content: center; gap: 8px; min-height: 46px; padding: 0 20px; white-space: nowrap;
        border-radius: 12px; font: inherit; font-size: 15px; font-weight: 600; text-decoration: none; cursor: pointer; }}
.btn-primary {{ background: var(--ink); color: var(--bg); border: 0; }}
.btn-ghost {{ background: transparent; color: var(--ink); border: 1px solid var(--line); }}
.btn:focus-visible {{ outline: 3px solid var(--blue); outline-offset: 2px; }}
.retry {{ color: var(--muted); font-size: 14px; min-height: 1.6em; margin: 4px 0 0; }}
.help {{ margin-top: clamp(10px, 2.5vh, 20px); padding-top: clamp(10px, 2.5vh, 18px); border-top: 1px solid var(--line); color: var(--muted); font-size: 14px; }}
.help a {{ color: var(--blue); font-weight: 600; text-decoration: none; }}
.help a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
<main>
  {logo}
  <div><span class="badge"><span class="dot" aria-hidden="true"></span>Error {code}</span></div>
  <h1>{title}</h1>
  <p class="lead">{lead}</p>

  <section class="card" aria-labelledby="steps">
    <h2 id="steps">What to do</h2>
    <ol>
      <li><strong>Wait a minute</strong>, then tap <strong>Try again</strong>.</li>
      <li><strong>Close the app or browser</strong> and open it again.</li>
      <li><strong>Restart the device.</strong></li>
    </ol>
  </section>

  <div class="actions">
    <button class="btn btn-primary" type="button" onclick="location.reload()">Try again</button>
    <a class="btn btn-ghost" href="{whatsapp}" target="_blank" rel="noopener">Contact Revenax</a>
  </div>
  <p class="retry" id="retry" aria-live="polite"></p>

  <div class="help">
    Still in trouble? Contact <strong>Revenax</strong>:<br>
    WhatsApp <a href="{whatsapp}" target="_blank" rel="noopener">{whatsapp_display}</a>
    · <a href="mailto:{email}?subject=Error%20{code}">{email}</a>
  </div>


</main>
<script>
(function () {{
  var left = {retry}, el = document.getElementById('retry');
  function tick() {{
    if (left <= 0) {{ el.textContent = 'Retrying…'; location.reload(); return; }}
    el.textContent = 'Retrying automatically in ' + left + 's';
    left -= 1; setTimeout(tick, 1000);
  }}
  tick();
}})();
</script>
</body>
</html>
"""


def logo_svg():
    svg = (LANDING / 'public/assets/logo-full.svg').read_text()
    svg = svg.replace('fill="#353535"', 'fill="currentColor"')
    svg = re.sub(r'<svg width="\d+" height="\d+"', '<svg class="logo" role="img" aria-label="Revenax"', svg, count=1)
    return svg.strip()


def main():
    font = base64.b64encode((LANDING / 'public/fonts/fonnts.com-fractul-regular.otf').read_bytes()).decode()
    logo = logo_svg()
    out = HERE / 'html'
    out.mkdir(exist_ok=True)
    for code, text in PAGES.items():
        html = TEMPLATE.format(code=code, font=font, logo=logo, whatsapp=WHATSAPP_URL,
                               whatsapp_display=WHATSAPP_DISPLAY, email=EMAIL, retry=RETRY_SECONDS, **text)
        (out / f'{code}.html').write_text(html)
        print('wrote', out / f'{code}.html', len(html), 'bytes')


if __name__ == '__main__':
    main()
