/** @odoo-module **/
// HR Office home screen: one tile per HR area, with a live red badge when something is waiting.
import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class HrOffice extends Component {
    static template = "linkederp_jd_helper.HrOffice";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({ tiles: [] });
        onWillStart(async () => {
            this.state.tiles = (await this.orm.call("linkederp.hr.office", "get_overview", [])).tiles;
        });
    }

    open(tile) {
        if (!tile.built) {
            this.notification.add(`${tile.name} is coming soon.`, { type: "info" });
            return;
        }
        this.action.doAction(tile.action_id);
    }
}

registry.category("actions").add("linkederp_hr_office", HrOffice);
