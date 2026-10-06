# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Outgoing email for Odoo through the company's Zoho mailbox (idempotent).

Run through the Odoo shell:
  sudo -u odoo bash -c '/opt/odoo/ee-odoo-bin shell -c /etc/odoo.conf -d marjaan --no-http < configure_email.py'

marjaanjewellery.com mail is hosted at Zoho (MX mx.zoho.com, SPF includes
zohomail.com, DKIM selector "zmail"). Odoo sends as info@ through Zoho's
SMTP, so every message is signed and passes SPF like mail sent from Zoho
itself. The password is NOT set here: the owner pastes a Zoho app password
into Settings > Technical > Outgoing Mail Servers and presses Test Connection.

Odoo has no incoming mail server, so replies must reach a human inbox:
Reply-To (catchall) is info@ too. The CRM team alias "info" (leads by email,
which needs incoming mail) is released so the catchall can use the name.
Old failed emails (state exception) are never re-sent by Odoo.
"""
COMMIT = True
DOMAIN = 'marjaanjewellery.com'
SENDER = 'info'                      # info@marjaanjewellery.com, the Zoho mailbox
SMTP_HOST = 'smtppro.zoho.com'       # Zoho organisation accounts, US data centre (mx.zoho.com)
LOG = []


def log(msg):
    LOG.append(msg)
    print('MAIL', msg)


address = f'{SENDER}@{DOMAIN}'

# ── free "info" for the catchall ─────────────────────────────────────────
for alias in env['mail.alias'].sudo().search([('alias_name', '=', SENDER)]):
    owner = alias.alias_parent_model_id.model
    log(f'alias "{SENDER}" released from {alias.alias_model_id.model} (owner {owner} #{alias.alias_parent_thread_id}): '
        'needs incoming mail, which is not configured')
    alias.alias_name = False

# ── alias domain: From = info@, Reply-To = info@ ────────────────────────
AliasDomain = env['mail.alias.domain'].sudo()
ad = AliasDomain.search([('name', '=', DOMAIN)], limit=1)
wanted = {'default_from': SENDER, 'catchall_alias': SENDER, 'bounce_alias': 'bounce'}
if not ad:
    ad = AliasDomain.create({'name': DOMAIN, **wanted})
    log(f'alias domain {DOMAIN}: From {ad.default_from_email}, Reply-To {ad.catchall_email}')
else:
    diff = {k: v for k, v in wanted.items() if ad[k] != v}
    if diff:
        ad.write(diff)
        log(f'alias domain {DOMAIN} updated: {diff}')
for company in env['res.company'].sudo().with_context(active_test=False).search([]):
    if company.alias_domain_id != ad:
        company.alias_domain_id = ad
        log(f'company {company.name}: alias domain {DOMAIN}')

# ── the SMTP server ─────────────────────────────────────────────────────
Server = env['ir.mail_server'].sudo().with_context(active_test=False)
server = Server.search([('smtp_host', '=', SMTP_HOST), ('smtp_user', '=', address)], limit=1)
vals = {
    'name': f'Zoho ({address})',
    'smtp_host': SMTP_HOST, 'smtp_port': 465, 'smtp_encryption': 'ssl',
    'smtp_authentication': 'login', 'smtp_user': address,
    # Only info@ may be sent from: any other From (a salesperson's address)
    # is rewritten to "Name" <info@...>, and the envelope sender is info@,
    # which Zoho requires.
    'from_filter': address, 'sequence': 1, 'active': True,
}
if not server:
    server = Server.create(vals)
    log(f'mail server "{server.name}" created ({SMTP_HOST}:465 SSL) — password still to be set')
else:
    diff = {k: v for k, v in vals.items() if server[k] != v}
    if diff:
        server.write(diff)
        log(f'mail server "{server.name}" updated: {sorted(diff)}')
if not server.smtp_pass:
    print('MAIL TODO: paste the Zoho app password for', address, 'into', server.name, 'and press Test Connection')

if COMMIT:
    env.cr.commit()
    print('MAIL done,', len(LOG), 'changes')
else:
    env.cr.rollback()
    print('MAIL dry run,', len(LOG), 'changes rolled back')
