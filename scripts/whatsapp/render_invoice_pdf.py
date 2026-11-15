# -*- coding: utf-8 -*-
# Copyright 2026 Revenax Digital Services
# Author: Mohamed A. Abdallah
# Website: https://www.revenax.com
"""Odoo-shell script: render a customer invoice to PDF with Marjaan's invoice layout.

    scripts/ops/run_odoo.sh scripts/whatsapp/render_invoice_pdf.py            # latest posted invoice
    scripts/ops/run_odoo.sh scripts/whatsapp/render_invoice_pdf.py INV=MJ-1617

Writes /tmp/wa_invoice.pdf on the server and prints the invoice summary (number, date,
customer, total, payment state, lines) used to write the WhatsApp caption. Read-only:
the transaction is rolled back. Then send it with scripts/whatsapp/send_document.py.
"""
import os

Move = env['account.move']
name = os.environ.get('INV')
domain = [('move_type', '=', 'out_invoice'), ('state', '=', 'posted')] + ([('name', '=', name)] if name else [])
inv = Move.search(domain, order='id desc', limit=1)
assert inv, f'no posted customer invoice {name or ""}'
# "Invoice PDF" = account.report_invoice_with_payments; jewellery_evaluator restyles it (gold A5 layout).
pdf, _ = env['ir.actions.report']._render_qweb_pdf('account.report_invoice_with_payments', inv.ids)
with open('/tmp/wa_invoice.pdf', 'wb') as f:
    f.write(pdf)
os.chmod('/tmp/wa_invoice.pdf', 0o644)
print('INV', inv.name, '|', inv.invoice_date, '|', inv.partner_id.name, '|', inv.partner_id.phone,
      '|', inv.amount_total, inv.currency_id.name, '|', inv.payment_state, '|', len(pdf), 'bytes')
for line in inv.invoice_line_ids.filtered(lambda l: l.display_type == 'product'):
    tmpl = line.product_id.product_tmpl_id
    title = tmpl.website_title if 'website_title' in tmpl._fields and tmpl.website_title else line.name
    print('  LINE', line.product_id.default_code, '|', title, '|', line.price_total)
env.cr.rollback()
