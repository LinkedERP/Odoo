/** @odoo-module **/

import { Component, onWillStart, useExternalListener, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const PALETTE = ["#2563eb", "#059669", "#f59e0b", "#dc2626", "#7c3aed", "#0891b2", "#db2777", "#475569"];
const SELECTED_DASHBOARD_KEY = "linkederp_dashboard_studio.selected_dashboard_id";
const SELECTED_WEEK_KEY = "linkederp_dashboard_studio.ops_week";
const SELECTED_OPS_TEAM_KEY = "linkederp_dashboard_studio.ops_team";
const SELECTED_MONTH_KEY = "linkederp_dashboard_studio.awards_month";
const SELECTED_TEAM_WEEK_KEY = "linkederp_dashboard_studio.teams_week";
const SELECTED_MGMT_TEAM_KEY = "linkederp_dashboard_studio.mgmt_team";
const SELECTED_SALES_YEAR_KEY = "linkederp_dashboard_studio.sales_year";
const SELECTED_SALES_PERSON_KEY = "linkederp_dashboard_studio.sales_person";
const SELECTED_SALES_COMPANY_KEY = "linkederp_dashboard_studio.sales_company";
const SELECTED_SALES_TEAMS_KEY = "linkederp_dashboard_studio.sales_teams";
const SELECTED_SLA_CUSTOMER_KEY = "linkederp_dashboard_studio.sla_customer";

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
            bucketOrder: [],
            widgets: [],
            crmFilters: { enabled: false },
            opsFilters: { enabled: false },
            awardsFilters: { enabled: false },
            weeklyFilters: { enabled: false },
            mgmtFilters: { enabled: false },
            salesFilters: { enabled: false },
            slaFilters: { enabled: false },
            modal: false,
            filters: this.defaultFilters(),
            tooltip: { visible: false, x: 0, y: 0, title: "", detail: null },
            initialDashboardId,
        });

        useExternalListener(window, "keydown", (ev) => {
            if (ev.key === "Escape" && this.state.modal) {
                this.closeModal();
            }
        });

        onWillStart(() => this.load(initialDashboardId));
    }

    bindTemplateMethods() {
        for (const method of [
            "onDashboardChange",
            "bucketGroups",
            "onKpiClick",
            "sparkTitle",
            "closeModal",
            "onModalBackdropClick",
            "onMgmtTeamChange",
            "isMgmtTeamSelected",
            "onSalesYearChange",
            "isSalesYearSelected",
            "onSalesPersonChange",
            "isSalesPersonSelected",
            "onSalesCompanyChange",
            "isSalesCompanySelected",
            "onSalesTeamToggle",
            "isSalesTeamSelected",
            "clearSalesTeams",
            "onSlaCustomerChange",
            "isSlaCustomerSelected",
            "onSlaExportPdf",
            "columns2Style",
            "comboBarStyle",
            "comboLinePoints",
            "comboMarkers",
            "applyFilters",
            "resetFilters",
            "setFilter",
            "onWeekChange",
            "isWeekSelected",
            "onOpsTeamChange",
            "isOpsTeamSelected",
            "onMonthChange",
            "isMonthSelected",
            "podiumBarStyle",
            "onTeamWeekToggle",
            "clearTeamWeek",
            "showDetailFor",
            "dualLine",
            "dualMarkers",
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
            "matrixCellAlign",
            "matrixCellTone",
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
            month: window.localStorage.getItem(SELECTED_MONTH_KEY) || "",
            teamWeek: window.localStorage.getItem(SELECTED_TEAM_WEEK_KEY) || "",
            mgmtTeam: window.localStorage.getItem(SELECTED_MGMT_TEAM_KEY) || "",
            salesYear: window.localStorage.getItem(SELECTED_SALES_YEAR_KEY) || "",
            salesPerson: window.localStorage.getItem(SELECTED_SALES_PERSON_KEY) || "",
            salesCompany: window.localStorage.getItem(SELECTED_SALES_COMPANY_KEY) || "",
            salesTeams: this.parseSalesTeams(window.localStorage.getItem(SELECTED_SALES_TEAMS_KEY)),
            slaCustomer: window.localStorage.getItem(SELECTED_SLA_CUSTOMER_KEY) || "",
        };
    }

    parseSalesTeams(raw) {
        try {
            const parsed = JSON.parse(raw || "[]");
            if (Array.isArray(parsed)) {
                return parsed.map(Number).filter((id) => Number.isFinite(id) && id > 0);
            }
        } catch {
            // Garbage in localStorage: fall through to no selection.
        }
        return [];
    }

    saveSalesTeams() {
        window.localStorage.setItem(
            SELECTED_SALES_TEAMS_KEY, JSON.stringify(this.state.filters.salesTeams || []));
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

    onKpiClick(widget) {
        if (widget.modal_table) {
            this.state.modal = widget.modal_table;
            return;
        }
        this.openRecords(widget.model, widget.domain);
    }

    sparkTitle(widget) {
        return (widget.points || [])
            .map((p) => `${p.label}: ${this.formatByType(p.value, widget.format)}`)
            .join("  ·  ");
    }

    closeModal() {
        this.state.modal = false;
    }

    onModalBackdropClick(ev) {
        if (ev.target === ev.currentTarget) {
            this.closeModal();
        }
    }

    async onMgmtTeamChange(ev) {
        this.state.filters.mgmtTeam = ev.target.value || "";
        window.localStorage.setItem(SELECTED_MGMT_TEAM_KEY, this.state.filters.mgmtTeam);
        await this.load(this.state.dashboard && this.state.dashboard.id);
    }

    isMgmtTeamSelected(value) {
        return (this.state.filters.mgmtTeam || "") === value;
    }

    async onSalesYearChange(ev) {
        this.state.filters.salesYear = ev.target.value || "";
        window.localStorage.setItem(SELECTED_SALES_YEAR_KEY, this.state.filters.salesYear);
        await this.load(this.state.dashboard && this.state.dashboard.id);
    }

    isSalesYearSelected(value) {
        return `${this.state.filters.salesYear || ""}` === `${value}`;
    }

    async onSalesPersonChange(ev) {
        this.state.filters.salesPerson = ev.target.value || "";
        window.localStorage.setItem(SELECTED_SALES_PERSON_KEY, this.state.filters.salesPerson);
        await this.load(this.state.dashboard && this.state.dashboard.id);
    }

    isSalesPersonSelected(value) {
        return `${this.state.filters.salesPerson || ""}` === `${value}`;
    }

    async onSalesCompanyChange(ev) {
        this.state.filters.salesCompany = ev.target.value || "";
        window.localStorage.setItem(SELECTED_SALES_COMPANY_KEY, this.state.filters.salesCompany);
        await this.load(this.state.dashboard && this.state.dashboard.id);
    }

    isSalesCompanySelected(value) {
        return `${this.state.filters.salesCompany || ""}` === `${value}`;
    }

    async onSalesTeamToggle(teamId) {
        const id = Number(teamId);
        const current = (this.state.filters.salesTeams || []).slice();
        const index = current.indexOf(id);
        if (index === -1) {
            current.push(id);
        } else {
            current.splice(index, 1);
        }
        this.state.filters.salesTeams = current;
        this.saveSalesTeams();
        await this.load(this.state.dashboard && this.state.dashboard.id);
    }

    isSalesTeamSelected(teamId) {
        return (this.state.filters.salesTeams || []).indexOf(Number(teamId)) !== -1;
    }

    async clearSalesTeams() {
        this.state.filters.salesTeams = [];
        this.saveSalesTeams();
        await this.load(this.state.dashboard && this.state.dashboard.id);
    }

    async onSlaCustomerChange(ev) {
        this.state.filters.slaCustomer = ev.target.value || "";
        window.localStorage.setItem(SELECTED_SLA_CUSTOMER_KEY, this.state.filters.slaCustomer);
        await this.load(this.state.dashboard && this.state.dashboard.id);
    }

    isSlaCustomerSelected(value) {
        return `${this.state.filters.slaCustomer || ""}` === `${value}`;
    }

    async onSlaExportPdf() {
        const action = await this.orm.call(
            "linkederp.dashboard",
            "action_export_sla_pdf",
            [],
            { customer_id: this.state.filters.slaCustomer || false }
        );
        this.action.doAction(action);
    }

    columns2Max(widget) {
        const values = [];
        for (const point of widget.points || []) {
            values.push(Number(point.a || 0));
            values.push(Number(point.b || 0));
        }
        return Math.max(...values, 1) * 1.15;
    }

    columns2Style(widget, point, key) {
        const value = Number(point[key] || 0);
        const height = value ? Math.max(4, (value / this.columns2Max(widget)) * 100) : 2;
        const color = key === "a" ? "#b03030" : "#2e7d2e";
        return `height: ${height}%; background: ${color};`;
    }

    comboMax(widget) {
        const values = [];
        for (const point of widget.points || []) {
            values.push(Number(point.line || 0));
            values.push(Number(point.bar || 0));
        }
        return Math.max(...values, 1) * 1.15;
    }

    comboBarStyle(widget, point) {
        const value = Number(point.bar || 0);
        const height = value ? Math.max(3, (value / this.comboMax(widget)) * 100) : 2;
        return `height: ${height}%;`;
    }

    comboCoords(widget) {
        const points = widget.points || [];
        const n = points.length;
        if (!n) {
            return [];
        }
        const max = this.comboMax(widget);
        return points.map((point, index) => {
            const x = ((index + 0.5) / n) * 600;
            const y = 140 - (Number(point.line || 0) / max) * 128;
            const topPct = (y / 150) * 100;
            return {
                point,
                x,
                y,
                leftPct: (x / 600) * 100,
                topPct,
                valueTopPct: Math.max(2, topPct - 13),
            };
        });
    }

    comboLinePoints(widget) {
        return this.comboCoords(widget).map((c) => `${c.x},${c.y}`).join(" ");
    }

    comboMarkers(widget) {
        return this.comboCoords(widget);
    }

    bucketGroups() {
        const order = this.state.bucketOrder || [];
        const groups = [];
        const known = new Set();
        for (const bucket of order) {
            known.add(bucket.key);
            const dashboards = this.state.dashboards.filter((d) => d.bucket === bucket.key);
            if (dashboards.length) {
                groups.push({ key: bucket.key, label: bucket.label, dashboards });
            }
        }
        const orphans = this.state.dashboards.filter((d) => !known.has(d.bucket));
        if (orphans.length) {
            groups.push({ key: "other", label: "Other", dashboards: orphans });
        }
        return groups;
    }

    async load(dashboardId) {
        this.state.loading = true;
        this.state.modal = false;
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
                        month: this.state.filters.month || false,
                        team_week: this.state.filters.teamWeek || false,
                        mgmt_team: this.state.filters.mgmtTeam || false,
                        sales_year: this.state.filters.salesYear || false,
                        sales_person_id: this.state.filters.salesPerson || false,
                        sales_company_id: this.state.filters.salesCompany || false,
                        sales_team_ids: this.state.filters.salesTeams || [],
                        sla_customer_id: this.state.filters.slaCustomer || false,
                    },
                }
            );
            this.state.dashboards = payload.dashboards || [];
            this.state.bucketOrder = payload.bucket_order || [];
            this.state.dashboard = payload.dashboard || false;
            this.state.widgets = payload.widgets || [];
            this.state.crmFilters = payload.crm_filters || { enabled: false };
            this.state.opsFilters = payload.ops_filters || { enabled: false };
            this.state.awardsFilters = payload.awards_filters || { enabled: false };
            this.state.weeklyFilters = payload.weekly_filters || { enabled: false };
            this.state.mgmtFilters = payload.mgmt_filters || { enabled: false };
            this.state.salesFilters = payload.sales_filters || { enabled: false };
            this.state.slaFilters = payload.sla_filters || { enabled: false };
            if (this.state.slaFilters.enabled) {
                this.state.filters.slaCustomer = String(this.state.slaFilters.customer || "");
                window.localStorage.setItem(SELECTED_SLA_CUSTOMER_KEY, this.state.filters.slaCustomer);
            }
            if (this.state.salesFilters.enabled) {
                // The server echoes the VALIDATED values: write them back so
                // stale localStorage self-heals (same pattern as teamWeek).
                this.state.filters.salesYear = String(this.state.salesFilters.year || "");
                this.state.filters.salesPerson = String(this.state.salesFilters.salesperson || "");
                this.state.filters.salesCompany = String(this.state.salesFilters.company || "");
                this.state.filters.salesTeams = (this.state.salesFilters.team_ids || []).slice();
                window.localStorage.setItem(SELECTED_SALES_YEAR_KEY, this.state.filters.salesYear);
                window.localStorage.setItem(SELECTED_SALES_PERSON_KEY, this.state.filters.salesPerson);
                window.localStorage.setItem(SELECTED_SALES_COMPANY_KEY, this.state.filters.salesCompany);
                this.saveSalesTeams();
            }
            if (this.state.mgmtFilters.enabled) {
                this.state.filters.mgmtTeam = this.state.mgmtFilters.team || "";
                window.localStorage.setItem(SELECTED_MGMT_TEAM_KEY, this.state.filters.mgmtTeam);
            }
            if (this.state.weeklyFilters.enabled) {
                this.state.filters.teamWeek = this.state.weeklyFilters.selected || "";
                window.localStorage.setItem(SELECTED_TEAM_WEEK_KEY, this.state.filters.teamWeek);
            }
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
        window.localStorage.removeItem(SELECTED_MONTH_KEY);
        window.localStorage.removeItem(SELECTED_TEAM_WEEK_KEY);
        window.localStorage.removeItem(SELECTED_MGMT_TEAM_KEY);
        window.localStorage.removeItem(SELECTED_SALES_YEAR_KEY);
        window.localStorage.removeItem(SELECTED_SALES_PERSON_KEY);
        window.localStorage.removeItem(SELECTED_SALES_COMPANY_KEY);
        window.localStorage.removeItem(SELECTED_SALES_TEAMS_KEY);
        window.localStorage.removeItem(SELECTED_SLA_CUSTOMER_KEY);
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

    async onMonthChange(ev) {
        this.state.filters.month = ev.target.value;
        window.localStorage.setItem(SELECTED_MONTH_KEY, ev.target.value || "");
        await this.load(this.state.dashboard && this.state.dashboard.id);
    }

    isMonthSelected(value) {
        const current = this.state.filters.month || this.state.awardsFilters.selected;
        return `${current}` === `${value}`;
    }

    podiumBarStyle(widget, point) {
        const values = (widget.points || []).map((p) => Number(p.value || 0));
        const max = Math.max(...values, 1);
        const height = Math.max(12, (Number(point.value || 0) / max) * 150);
        const color = point.rank === 1 ? (widget.color || "#1d4ed8") : "#cbd5e1";
        return `height: ${height}px; background: ${color};`;
    }

    async onTeamWeekToggle(week) {
        const current = this.state.filters.teamWeek || "";
        this.state.filters.teamWeek = current === week ? "" : week;
        window.localStorage.setItem(SELECTED_TEAM_WEEK_KEY, this.state.filters.teamWeek);
        await this.load(this.state.dashboard && this.state.dashboard.id);
    }

    async clearTeamWeek() {
        this.state.filters.teamWeek = "";
        window.localStorage.removeItem(SELECTED_TEAM_WEEK_KEY);
        await this.load(this.state.dashboard && this.state.dashboard.id);
    }

    showDetailFor(ev, label, detail) {
        if (!detail) {
            return;
        }
        this.state.tooltip = {
            visible: true,
            x: ev.clientX,
            y: ev.clientY,
            title: label || "",
            detail,
        };
    }

    dualCoords(widget) {
        const points = widget.points || [];
        const n = points.length;
        if (!n) {
            return [];
        }
        const values = [];
        for (const p of points) {
            values.push(Number(p.fail || 0));
            values.push(Number(p.bill || 0));
        }
        const max = Math.max(...values, 100) * 1.08;
        return points.map((p, i) => {
            const x = n === 1 ? 300 : 16 + (i / (n - 1)) * 568;
            const yFail = 128 - (Number(p.fail || 0) / max) * 118;
            const yBill = 128 - (Number(p.bill || 0) / max) * 118;
            return {
                point: p,
                x,
                yFail,
                yBill,
                leftPct: (x / 600) * 100,
                topFailPct: (yFail / 150) * 100,
                topBillPct: (yBill / 150) * 100,
            };
        });
    }

    dualLine(widget, series) {
        return this.dualCoords(widget)
            .map((c) => `${c.x},${series === "fail" ? c.yFail : c.yBill}`)
            .join(" ");
    }

    dualMarkers(widget) {
        return this.dualCoords(widget);
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
        if (format === "usd") {
            const abs = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(Math.abs(number));
            return `${number < 0 ? "-" : ""}$${abs}`;
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
        // abs() so charts of negative values (e.g. loss-making customers)
        // still scale their bars by magnitude.
        const values = (widget.points || []).map((p) => Math.abs(Number(p.value || 0)));
        const max = Math.max(...values, 1);
        const width = Math.max(3, (Math.abs(Number(point.value || 0)) / max) * 100);
        return `width: ${width}%; background: ${point.color || widget.color || "#2563eb"};`;
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
        if (column.format === "text" || column.format === "money") {
            return row[column.key] || "";
        }
        return this.formatByType(row[column.key], column.format);
    }

    matrixCellAlign(column) {
        let align = "text-center";
        if (column.format === "text") {
            align = "text-start";
        } else if (column.format === "money") {
            align = "text-end";
        }
        return align;
    }

    matrixCellTone(row, column) {
        const tone = row.tones && row.tones[column.key];
        return tone ? ` o_lds_cell_${tone}` : "";
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
                valueTopPct: Math.max(2, y - 16),
                value: point.value,
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
