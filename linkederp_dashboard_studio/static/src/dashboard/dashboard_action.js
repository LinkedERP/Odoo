/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const PALETTE = ["#2563eb", "#059669", "#f59e0b", "#dc2626", "#7c3aed", "#0891b2", "#db2777", "#475569"];
const SELECTED_DASHBOARD_KEY = "linkederp_dashboard_studio.selected_dashboard_id";
const SELECTED_WEEK_KEY = "linkederp_dashboard_studio.ops_week";
const SELECTED_OPS_TEAM_KEY = "linkederp_dashboard_studio.ops_team";

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
            opsFilters: { enabled: false },
            filters: this.defaultFilters(),
            tooltip: { visible: false, x: 0, y: 0, title: "", detail: null },
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
            "onWeekChange",
            "isWeekSelected",
            "onOpsTeamChange",
            "isOpsTeamSelected",
            "openRecords",
            "formatNumber",
            "formatWidgetValue",
            "formatPointValue",
            "formatByType",
            "optionLabel",
            "isFilterSelected",
            "barStyle",
            "columnGridLines",
            "columnStyle",
            "columnTargetStyle",
            "comparisonBarStyle",
            "stackSegmentStyle",
            "gaugeStyle",
            "funnelStyle",
            "pointShare",
            "matrixCellValue",
            "pieStyle",
            "linePoints",
            "trendLinePoints",
            "trendMarkers",
            "showDetail",
            "moveDetail",
            "hideDetail",
            "tooltipStyle",
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
            week: window.localStorage.getItem(SELECTED_WEEK_KEY) || "",
            opsTeam: window.localStorage.getItem(SELECTED_OPS_TEAM_KEY) || "",
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
                        week: this.state.filters.week || false,
                        ops_team: this.state.filters.opsTeam || false,
                    },
                }
            );
            this.state.dashboards = payload.dashboards || [];
            this.state.dashboard = payload.dashboard || false;
            this.state.widgets = payload.widgets || [];
            this.state.crmFilters = payload.crm_filters || { enabled: false };
            this.state.opsFilters = payload.ops_filters || { enabled: false };
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
        window.localStorage.removeItem(SELECTED_WEEK_KEY);
        window.localStorage.removeItem(SELECTED_OPS_TEAM_KEY);
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

    async onWeekChange(ev) {
        this.state.filters.week = ev.target.value;
        window.localStorage.setItem(SELECTED_WEEK_KEY, ev.target.value || "");
        await this.load(this.state.dashboard && this.state.dashboard.id);
    }

    isWeekSelected(value) {
        const current = this.state.filters.week || this.state.opsFilters.selected;
        return `${current}` === `${value}`;
    }

    async onOpsTeamChange(ev) {
        this.state.filters.opsTeam = ev.target.value;
        window.localStorage.setItem(SELECTED_OPS_TEAM_KEY, ev.target.value || "");
        await this.load(this.state.dashboard && this.state.dashboard.id);
    }

    isOpsTeamSelected(value) {
        const current = this.state.filters.opsTeam || this.state.opsFilters.selected_team || "";
        return `${current}` === `${value}`;
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
        if (widget.target) {
            values.push(Number(widget.target));
        }
        // 12% headroom so the tallest bar's value label (and the target line) stay visible.
        return Math.max(...values, 1) * 1.12;
    }

    columnTargetStyle(widget) {
        const target = Number(widget.target || 0);
        if (!target) {
            return "display: none;";
        }
        // Bar plot area is 184px tall on a baseline 42px above the plot floor.
        const bottom = 42 + (target / this.maxPointValue(widget)) * 184;
        return `bottom: ${bottom}px;`;
    }

    barStyle(widget, point) {
        const width = Math.max(3, (Number(point.value || 0) / this.maxPointValue(widget)) * 100);
        return `width: ${width}%; background: ${widget.color || "#2563eb"};`;
    }

    columnGridLines(widget) {
        const max = this.maxPointValue(widget);
        return [max, max * 0.75, max * 0.5, max * 0.25, 0].map((value) => Math.round(value));
    }

    columnStyle(widget, point, index) {
        const value = Number(point.value || 0);
        const height = value ? Math.max(4, (value / this.maxPointValue(widget)) * 100) : 0;
        let color = widget.color || "#2563eb";
        if (point.color) {
            color = point.color;
        } else if (widget.id === "ai_call_outcomes") {
            color = PALETTE[index % PALETTE.length];
        }
        return `height: ${height}%; background: ${color};`;
    }

    comparisonMaxValue(widget) {
        const values = [];
        for (const row of widget.rows || []) {
            values.push(Number(row.generated || 0));
            values.push(Number(row.meetings || 0));
        }
        return Math.max(...values, 1);
    }

    comparisonBarStyle(widget, row, key) {
        const value = Number(row[key] || 0);
        const width = value ? Math.max(3, (value / this.comparisonMaxValue(widget)) * 100) : 0;
        const color = key === "meetings" ? "#059669" : "#2563eb";
        return `width: ${width}%; background: ${color};`;
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
        if (column.format === "text") {
            return row[column.key] || "";
        }
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

    trendCoords(widget) {
        const points = widget.points || [];
        const values = points.map((point) => Number(point.value || 0));
        if (!values.length) {
            return [];
        }
        const max = Math.max(...values);
        const min = Math.min(...values);
        const range = max - min || 1;
        const n = values.length;
        return points.map((point, index) => {
            const x = n === 1 ? 150 : 12 + (index / (n - 1)) * 276;
            const y = 90 - ((Number(point.value || 0) - min) / range) * 66;
            return {
                x,
                y,
                leftPct: (x / 300) * 100,
                topPct: y,
                color: point.color || "#003E99",
                label: point.label,
                detail: point.detail,
            };
        });
    }

    trendLinePoints(widget) {
        return this.trendCoords(widget).map((c) => `${c.x},${c.y}`).join(" ");
    }

    trendMarkers(widget) {
        return this.trendCoords(widget);
    }

    showDetail(ev, point) {
        if (!point || !point.detail) {
            return;
        }
        this.state.tooltip = {
            visible: true,
            x: ev.clientX,
            y: ev.clientY,
            title: point.label || "",
            detail: point.detail,
        };
    }

    moveDetail(ev) {
        if (this.state.tooltip.visible) {
            this.state.tooltip.x = ev.clientX;
            this.state.tooltip.y = ev.clientY;
        }
    }

    hideDetail() {
        this.state.tooltip.visible = false;
    }

    tooltipStyle() {
        const t = this.state.tooltip;
        // Flip to the left / up near the viewport edges so the panel stays on-screen.
        const w = window.innerWidth;
        const h = window.innerHeight;
        const left = t.x + 300 > w ? t.x - 300 : t.x + 16;
        const top = t.y + 240 > h ? Math.max(8, t.y - 240) : t.y + 16;
        return `left: ${left}px; top: ${top}px;`;
    }

    legendColor(index) {
        return `background: ${PALETTE[index % PALETTE.length]};`;
    }
}

LinkedERPDashboardAction.template = "linkederp_dashboard_studio.DashboardAction";

registry.category("actions").add("linkederp_dashboard_studio.dashboard_action", LinkedERPDashboardAction);
