{
    'name': 'Jewellery Inventory Management',
    'version': '19.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': 'Stock counts for jewellery products (extends Jewellery Evaluator)',
    'description': """
        Jewellery Inventory Management
        ==============================
        Minimal inventory layer on top of Jewellery Evaluator.

        Adds a simple physical stock-count record linked to jewellery
        products. Depends on the jewellery_evaluator module and reuses its
        security groups.
    """,
    'author': 'Revenax Digital Services, Mohamed A. Abdallah',
    'website': 'https://www.revenax.com',
    'depends': [
        'jewellery_evaluator',
        'stock',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/jewellery_inventory_count_views.xml',
        'views/jewellery_weight_inventory_report_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'OPL-1',
} # type: ignore
