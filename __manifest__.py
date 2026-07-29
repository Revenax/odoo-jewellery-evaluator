{
    'name': 'Jewellery Evaluator',
    'version': '19.0.3.3.0',
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
        'purchase',
    ],
    'data': [
        'jewellery_evaluator/security/jewellery_evaluator_security.xml',
        'jewellery_evaluator/security/ir.model.access.csv',
        'jewellery_evaluator/views/diamond_rap_views.xml',
        # Must load AFTER diamond_rap_views.xml — it references
        # action_diamond_rap_editor for the app's second menu entry.
        'jewellery_evaluator/views/jewellery_dashboard_views.xml',
        'jewellery_evaluator/views/jewellery_evaluator_config_views.xml',
        'jewellery_evaluator/views/pos_config_views.xml',
        'jewellery_evaluator/views/pos_order_views.xml',
        'jewellery_evaluator/views/product_template_views.xml',
        'jewellery_evaluator/views/account_move_views.xml',
        'jewellery_evaluator/report/paperformat_gold.xml',
        'jewellery_evaluator/report/external_layout_gold.xml',
        'jewellery_evaluator/report/report_invoice_gold.xml',
        'jewellery_evaluator/report/report_gift_invoice.xml',
        'jewellery_evaluator/data/jewellery_evaluator_cron.xml',
        'jewellery_evaluator/data/bought_from_customer_vendor.xml',
        'jewellery_evaluator/data/bulk_supplier_vendor.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'jewellery_evaluator/static/src/scss/orderline_below_min.scss',
            'jewellery_evaluator/static/src/scss/pos_rap_viewer.scss',
            'jewellery_evaluator/static/src/js/pos_discount_override.js',
            'jewellery_evaluator/static/src/js/pos_cash_ops.js',
            'jewellery_evaluator/static/src/js/pos_gift_invoice.js',
            'jewellery_evaluator/static/src/js/pos_rap_viewer.js',
            'jewellery_evaluator/static/src/xml/manager_override_popup.xml',
            'jewellery_evaluator/static/src/xml/orderline_below_min.xml',
            'jewellery_evaluator/static/src/xml/pos_cash_ops.xml',
            'jewellery_evaluator/static/src/xml/pos_gift_invoice.xml',
            'jewellery_evaluator/static/src/xml/pos_product_info.xml',
            'jewellery_evaluator/static/src/xml/pos_rap_viewer.xml',
        ],
        'web.assets_backend': [
            'jewellery_evaluator/static/src/scss/diamond_rap_editor.scss',
            'jewellery_evaluator/static/src/js/diamond_rap_editor.js',
            'jewellery_evaluator/static/src/xml/diamond_rap_editor.xml',
            'jewellery_evaluator/static/src/scss/jewellery_dashboard.scss',
            'jewellery_evaluator/static/src/js/jewellery_dashboard.js',
            'jewellery_evaluator/static/src/xml/jewellery_dashboard.xml',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'OPL-1',
} # type: ignore
