/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const PALETTE = ["#2563eb", "#059669", "#f59e0b", "#dc2626", "#7c3aed", "#0891b2", "#db2777", "#475569"];
const SELECTED_DASHBOARD_KEY = "linkederp_dashboard_studio.selected_dashboard_id";

export class LinkedERPDashboardAction extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.bindTemplateMethods();

        const initialDashboardId = this.props.action && this.props.action.params
            ? this.props.action.params.dashboard_id
            : false;

        this.state = useState({
            loading: true,
            dashboard: false,
            dashboards: [],
            widgets: [],
            crmFilters: { enabled: false },
            filters: this.defaultFilters(),
            initialDashboardId,
        });

        onWillStart(() => this.load(initialDashboardId));
    }

    bindTemplateMethods() {
        for (const method of [
            "onDashboardChange",
            "applyFilters",
            "resetFilters",
            "setFilter",
            "openRecords",
            "formatNumber",
            "formatWidgetValue",
            "formatPointValue",
            "formatByType",
            "optionLabel",
            "isFilterSelected",
            "barStyle",
            "stackSegmentStyle",
            "gaugeStyle",
            "funnelStyle",
            "pointShare",
            "matrixCellValue",
            "pieStyle",
            "linePoints",
            "legendColor",
        ]) {
            this[method] = this[method].bind(this);
        }
    }

    defaultFilters() {
        const today = new Date();
        const start = new Date(today);
        start.setDate(today.getDate() - 29);
        return {
            dateFrom: this.dateToInput(start),
            dateTo: this.dateToInput(today),
            campaignId: "",
            userId: "",
            teamId: "",
            stageId: "",
        };
    }

    dateToInput(date) {
        return date.toISOString().slice(0, 10);
    }

    savedDashboardId() {
        const value = window.localStorage.getItem(SELECTED_DASHBOARD_KEY);
        return value ? Number(value) : false;
    }

    saveDashboardId(dashboardId) {
        if (dashboardId) {
            window.localStorage.setItem(SELECTED_DASHBOARD_KEY, String(dashboardId));
        }
    }

    async load(dashboardId) {
        this.state.loading = true;
        try {
            const targetDashboardId = dashboardId || this.savedDashboardId();
            const payload = await this.orm.call(
                "linkederp.dashboard",
                "get_dashboard_payload",
                [],
                {
                    dashboard_id: targetDashboardId || false,
                    date_from: this.state.filters.dateFrom || false,
                    date_to: this.state.filters.dateTo || false,
                    filters: {
                        campaign_id: this.state.filters.campaignId || false,
                        user_id: this.state.filters.userId || false,
                        team_id: this.state.filters.teamId || false,
                        stage_id: this.state.filters.stageId || false,
                    },
                }
            );
            this.state.dashboards = payload.dashboards || [];
            this.state.dashboard = payload.dashboard || false;
            this.state.widgets = payload.widgets || [];
            this.state.crmFilters = payload.crm_filters || { enabled: false };
            if (this.state.dashboard) {
                this.saveDashboardId(this.state.dashboard.id);
            }
        } catch (error) {
            this.notification.add(error.message || error.toString(), { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    async onDashboardChange(ev) {
        this.clearCrmFilters();
        const dashboardId = Number(ev.target.value);
        this.saveDashboardId(dashboardId);
        await this.load(dashboardId);
    }

    async applyFilters() {
        await this.load(this.state.dashboard && this.state.dashboard.id);
    }

    async resetFilters() {
        this.state.filters = this.defaultFilters();
        await this.applyFilters();
    }

    clearCrmFilters() {
        this.state.filters.campaignId = "";
        this.state.filters.userId = "";
        this.state.filters.teamId = "";
        this.state.filters.stageId = "";
    }

    setFilter(key, value) {
        this.state.filters[key] = value;
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

    formatByType(value, format) {
        const number = Number(value || 0);
        if (format === "percent") {
            return `${this.formatNumber(number)}%`;
        }
        if (format === "integer") {
            return new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(number);
        }
        if (format === "days") {
            return `${this.formatNumber(number)} days`;
        }
        return this.formatNumber(number);
    }

    formatWidgetValue(widget) {
        return this.formatByType(widget.value, widget.format);
    }

    formatPointValue(widget, value) {
        return this.formatByType(value, widget.format);
    }

    optionLabel(option) {
        return `${option.name} (${this.formatNumber(option.count)})`;
    }

    isFilterSelected(key, optionId) {
        return `${this.state.filters[key] || ""}` === `${optionId}`;
    }

    maxPointValue(widget) {
        const values = (widget.points || []).map((point) => Number(point.value || 0));
        return Math.max(...values, 1);
    }

    barStyle(widget, point) {
        const width = Math.max(3, (Number(point.value || 0) / this.maxPointValue(widget)) * 100);
        return `width: ${width}%; background: ${widget.color || "#2563eb"};`;
    }

    stackSegmentStyle(widget, point, index) {
        const total = (widget.points || []).reduce((sum, item) => sum + Number(item.value || 0), 0);
        const width = total ? Math.max(4, (Number(point.value || 0) / total) * 100) : 0;
        return `width: ${width}%; background: ${PALETTE[index % PALETTE.length]};`;
    }

    gaugeStyle(widget) {
        const value = Math.max(0, Math.min(100, Number(widget.value || 0)));
        return `background: conic-gradient(${widget.color || "#2563eb"} 0 ${value}%, #e5e7eb ${value}% 100%);`;
    }

    funnelStyle(widget, point) {
        const first = widget.points && widget.points.length ? Number(widget.points[0].value || 0) : 0;
        const width = first ? Math.max(3, (Number(point.value || 0) / first) * 100) : 3;
        return `width: ${width}%; background: ${widget.color || "#2563eb"};`;
    }

    pointShare(widget, point) {
        const first = widget.points && widget.points.length ? Number(widget.points[0].value || 0) : 0;
        if (!first) {
            return "0%";
        }
        return `${this.formatNumber((Number(point.value || 0) / first) * 100)}%`;
    }

    matrixCellValue(row, column) {
        return this.formatByType(row[column.key], column.format);
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
