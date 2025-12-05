# -*- coding: utf-8 -*-

#################################################################################
# Author      : Cyder Solutions (<www.cyder.com.au>)
# Copyright(c): 2021-now
# All Rights Reserved.
#
# This module is copyright property of the author mentioned above.
# You can't redistribute/reshare/recreate it for any purpose.
#
#################################################################################

{
    'name': 'Client Equipment',
    'version': '19.0.1.0.2',
    'category': 'Productivity',
    'author': 'Cyder Solutions',
    'website': 'https://www.cyder.com.au',
    'sequence': -45,
    'summary': 'Client Equipment Base',
    'description': """Client Equipment Management""",
    'depends':['mail', 'hr'],
    'data': [
        'security/client_equipment_security_groups.xml',
        'security/ir.model.access.csv',
        'views/menu.xml',
        'views/equipment_view.xml',
        'views/res_partner.xml',
        'report/service_history_report.xml',
    ],
    'demo': [
        'data/client_equipment_demo.xml',
    ],
    'images': ['static/description/banner.gif'],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
