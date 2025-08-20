/** @odoo-module */

import { onMounted } from "@odoo/owl";
import { patch } from '@web/core/utils/patch';
import { Navbar } from "@point_of_sale/app/navbar/navbar";

patch(Navbar.prototype, {
    setup() {
        super.setup();

        onMounted(() => {
            const logoEl = document.querySelector('.pos-centerheader img');
            if (logoEl) {
                logoEl.src = '/logo.png';
            }
        });
    },
});
