/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const PALETTE = ["#2563eb", "#059669", "#f59e0b", "#dc2626", "#7c3aed", "#0891b2", "#db2777", "#475569"];

export class LinkedERPDashboardAction extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        const initialDashboardId = this.props.action && this.props.action.params
            ? this.props.action.params.dashboard_id
            : false;

        this.state = useState({
            loading: true,
            dashboard: false,
            dashboards: [],
            widgets: [],
            filters: this.defaultFilters(),
            initialDashboardId,
        });

        onWillStart(() => this.load(initialDashboardId));
    }

    defaultFilters() {
        const today = new Date();
        const start = new Date(today);
        start.setDate(today.getDate() - 29);
        return {
            dateFrom: this.dateToInput(start),
            dateTo: this.dateToInput(today),
        };
    }

    dateToInput(date) {
        return date.toISOString().slice(0, 10);
    }

    async load(dashboardId) {
        this.state.loading = true;
        try {
            const payload = await this.orm.call(
                "linkederp.dashboard",
                "get_dashboard_payload",
                [],
                {
                    dashboard_id: dashboardId || false,
                    date_from: this.state.filters.dateFrom || false,
                    date_to: this.state.filters.dateTo || false,
                }
            );
            this.state.dashboards = payload.dashboards || [];
            this.state.dashboard = payload.dashboard || false;
            this.state.widgets = payload.widgets || [];
        } catch (error) {
            this.notification.add(error.message || error.toString(), { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    async onDashboardChange(ev) {
        await this.load(Number(ev.target.value));
    }

    async applyFilters() {
        await this.load(this.state.dashboard && this.state.dashboard.id);
    }

    async resetFilters() {
        this.state.filters = this.defaultFilters();
        await this.applyFilters();
    }

    async openRecords(model, domain) {
        if (!model) {
            return;
        }
        const action = await this.orm.call(
            "linkederp.dashboard",
            "action_open_records",
            [],
            {
                model_name: model,
                domain: domain || [],
            }
        );
        this.action.doAction(action);
    }

    formatNumber(value) {
        const number = Number(value || 0);
        return new Intl.NumberFormat("en-IN", {
            maximumFractionDigits: Number.isInteger(number) ? 0 : 2,
        }).format(number);
    }

    maxPointValue(widget) {
        const values = (widget.points || []).map((point) => Number(point.value || 0));
        return Math.max(...values, 1);
    }

    barStyle(widget, point) {
        const width = Math.max(3, (Number(point.value || 0) / this.maxPointValue(widget)) * 100);
        return `width: ${width}%; background: ${widget.color || "#2563eb"};`;
    }

    pieStyle(widget) {
        const points = widget.points || [];
        const total = points.reduce((sum, point) => sum + Number(point.value || 0), 0);
        if (!points.length || !total) {
            return "background: #e5e7eb;";
        }

        let cursor = 0;
        const stops = points.map((point, index) => {
            const color = PALETTE[index % PALETTE.length];
            const start = cursor;
            cursor += (Number(point.value || 0) / total) * 100;
            return `${color} ${start}% ${cursor}%`;
        });
        return `background: conic-gradient(${stops.join(", ")});`;
    }

    linePoints(widget) {
        const values = (widget.points || []).map((point) => Number(point.value || 0));
        if (!values.length) {
            return "";
        }
        if (values.length === 1) {
            return "12,72 288,72";
        }
        const max = Math.max(...values);
        const min = Math.min(...values);
        const range = max - min || 1;
        return values
            .map((value, index) => {
                const x = 12 + (index / (values.length - 1)) * 276;
                const y = 92 - ((value - min) / range) * 72;
                return `${x},${y}`;
            })
            .join(" ");
    }

    legendColor(index) {
        return `background: ${PALETTE[index % PALETTE.length]};`;
    }
}

LinkedERPDashboardAction.template = "linkederp_dashboard_studio.DashboardAction";

registry.category("actions").add("linkederp_dashboard_studio.dashboard_action", LinkedERPDashboardAction);
