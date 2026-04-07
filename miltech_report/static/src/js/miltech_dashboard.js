/** @odoo-module */

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { download } from "@web/core/network/download";


class MiltechDashboard extends Component {
    static template = "miltech_report.Dashboard";

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.uiService = useService("ui");

        this.state = useState({
            wizardId: null,
            kpis: {},
            byStage: [],
            byCustomer: [],
            bySalesperson: [],
            filters: { salespeople: [], partners: [], stages: [] },
            filterValues: {
                date_from: "",
                date_to: "",
                salesperson_id: false,
                partner_id: false,
                stage_ids: [],
            },
            loading: true,
        });

        onWillStart(async () => {
            await this._createWizard();
            await this._loadData();
        });
    }

    // -------------------------------------------------------------------------
    // Data loading
    // -------------------------------------------------------------------------

    async _createWizard() {
        const ids = await this.orm.create("miltech.report", [{}]);
        this.state.wizardId = Array.isArray(ids) ? ids[0] : ids;
    }

    async _loadData() {
        this.state.loading = true;
        try {
            const data = await this.orm.call(
                "miltech.report",
                "get_dashboard_data",
                [this.state.wizardId],
            );
            this._applyData(data);
        } catch (e) {
            console.error("Miltech Dashboard: failed to load data", e);
        }
        this.state.loading = false;
    }

    _applyData(data) {
        this.state.kpis = data.kpis || {};
        this.state.byStage = data.by_stage || [];
        this.state.byCustomer = data.by_customer || [];
        this.state.bySalesperson = data.by_salesperson || [];
        if (data.filters) {
            this.state.filters = data.filters;
        }
    }

    // -------------------------------------------------------------------------
    // Filters
    // -------------------------------------------------------------------------

    onDateFromChange(ev) {
        this.state.filterValues.date_from = ev.target.value || "";
    }

    onDateToChange(ev) {
        this.state.filterValues.date_to = ev.target.value || "";
    }

    onSalespersonChange(ev) {
        const val = parseInt(ev.target.value);
        this.state.filterValues.salesperson_id = val || false;
    }

    onCustomerChange(ev) {
        const val = parseInt(ev.target.value);
        this.state.filterValues.partner_id = val || false;
    }

    async onApplyFilters() {
        this.state.loading = true;
        try {
            const data = await this.orm.call(
                "miltech.report",
                "apply_filters",
                [this.state.wizardId, this.state.filterValues],
            );
            this._applyData(data);
        } catch (e) {
            console.error("Miltech Dashboard: filter apply failed", e);
        }
        this.state.loading = false;
    }

    async onClearFilters() {
        this.state.filterValues = {
            date_from: "",
            date_to: "",
            salesperson_id: false,
            partner_id: false,
            stage_ids: [],
        };
        await this.onApplyFilters();
    }

    _toISODate(d) {
        return d.toISOString().slice(0, 10);
    }

    async onPresetToday() {
        const today = new Date();
        const iso = this._toISODate(today);
        this.state.filterValues.date_from = iso;
        this.state.filterValues.date_to = iso;
        await this.onApplyFilters();
    }

    async onPresetWeek() {
        const today = new Date();
        const day = today.getDay();
        const monday = new Date(today);
        monday.setDate(today.getDate() - (day === 0 ? 6 : day - 1));
        const sunday = new Date(monday);
        sunday.setDate(monday.getDate() + 6);
        this.state.filterValues.date_from = this._toISODate(monday);
        this.state.filterValues.date_to = this._toISODate(sunday);
        await this.onApplyFilters();
    }

    async onPresetMonth() {
        const today = new Date();
        const first = new Date(today.getFullYear(), today.getMonth(), 1);
        const last = new Date(today.getFullYear(), today.getMonth() + 1, 0);
        this.state.filterValues.date_from = this._toISODate(first);
        this.state.filterValues.date_to = this._toISODate(last);
        await this.onApplyFilters();
    }

    // -------------------------------------------------------------------------
    // XLSX Export
    // -------------------------------------------------------------------------

    async onExportXlsx() {
        this.uiService.block();
        try {
            await download({
                url: "/miltech/xlsx_report",
                data: { wizard_id: this.state.wizardId || 0 },
            });
        } catch (e) {
            console.error("Miltech Dashboard: XLSX export failed", e);
        }
        this.uiService.unblock();
    }

    // -------------------------------------------------------------------------
    // Navigation helpers
    // -------------------------------------------------------------------------

    viewStageLeads(stageId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Opportunities",
            res_model: "crm.lead",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain: [["stage_id", "=", stageId]],
            target: "current",
        });
    }

    viewCustomerLeads(partnerId) {
        if (!partnerId) return;
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Opportunities",
            res_model: "crm.lead",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain: [["partner_id", "=", partnerId]],
            target: "current",
        });
    }

    viewSalespersonLeads(userId) {
        if (!userId) return;
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Opportunities",
            res_model: "crm.lead",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain: [["user_id", "=", userId]],
            target: "current",
        });
    }

    // -------------------------------------------------------------------------
    // Formatting
    // -------------------------------------------------------------------------

    formatCurrency(val) {
        if (val === undefined || val === null) return "$0";
        return "$" + Number(val).toLocaleString("en-US", {
            minimumFractionDigits: 0,
            maximumFractionDigits: 0,
        });
    }

    formatPct(val) {
        if (val === undefined || val === null) return "0%";
        return Number(val).toFixed(1) + "%";
    }
}

registry.category("actions").add("miltech_report.Dashboard", MiltechDashboard);
