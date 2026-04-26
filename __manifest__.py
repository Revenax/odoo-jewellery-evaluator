{
    'name': 'Jewellery Evaluator',
    'version': '19.0.3.0.0',
    'category': 'Sales/Point of Sale',
    'summary': 'Automated gold pricing with live API updates and POS price enforcement',
    'description': """
        Jewellery Evaluator for Jewelry Business
        =========================================
        Version: 19.0.3.0.0

        This module provides:
        * Automated gold price updates from external API (every 10 minutes)
        * Product pricing based on weight, purity, and markup
        * POS price enforcement to prevent sales below minimum price
        * Real-time cost and sale price calculations

        Features:
        - Extends product.template with gold-specific fields
        - Automatic price updates via cron job
        - Backend and frontend POS validation
        - Batch processing for performance
    """,
    'author': 'Revenax Digital Services, Mohamed A. Abdallah',
    'website': 'https://www.revenax.com',
    'depends': [
        'base',
        'product',
        'point_of_sale',
        'account',
        'web',
        'stock',
    ],
    'data': [
        'jewellery_evaluator/security/jewellery_evaluator_security.xml',
        'jewellery_evaluator/security/ir.model.access.csv',
        'jewellery_evaluator/views/jewellery_evaluator_config_views.xml',
        'jewellery_evaluator/views/pos_config_views.xml',
        'jewellery_evaluator/views/pos_order_views.xml',
        'jewellery_evaluator/views/product_template_views.xml',
        'jewellery_evaluator/views/account_move_views.xml',
        'jewellery_evaluator/report/paperformat_gold.xml',
        'jewellery_evaluator/report/report_invoice_gold.xml',
        'jewellery_evaluator/report/external_layout_gold.xml',
        'jewellery_evaluator/data/jewellery_evaluator_cron.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'jewellery_evaluator/static/src/js/pos_discount_override.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'OPL-1',
}
