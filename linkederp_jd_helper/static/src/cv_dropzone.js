/** @odoo-module **/
// Drag-and-drop box for CVs on a hiring request (HR Office, Recruitment room).
// Each dropped file is uploaded as an attachment and linked to x_cv_upload_ids; the
// "Hiring request: CVs dropped" automation then makes one candidate per file for the AI to read.
import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

const ALLOWED = /\.(pdf|docx|txt)$/i;

export class CvDropzone extends Component {
    static template = "linkederp_jd_helper.CvDropzone";
    static props = { ...standardWidgetProps };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.action = useService("action");
        this.state = useState({ over: false, busy: false });
    }

    onDragOver(ev) {
        ev.preventDefault();
        this.state.over = true;
    }

    onDragLeave() {
        this.state.over = false;
    }

    async onDrop(ev) {
        ev.preventDefault();
        this.state.over = false;
        await this.upload(ev.dataTransfer.files);
    }

    async onPick(ev) {
        await this.upload(ev.target.files);
        ev.target.value = "";
    }

    async upload(fileList) {
        const files = [...fileList];
        const ok = files.filter((f) => ALLOWED.test(f.name));
        if (!ok.length) {
            this.notification.add("Please drop PDF or Word (.docx) files.", { type: "warning" });
            return;
        }
        const record = this.props.record;
        if (record.isDirty || !record.resId) {
            await record.save();
        }
        this.state.busy = true;
        try {
            const ids = [];
            for (const file of ok) {
                const body = new FormData();
                body.append("ufile", file);
                body.append("model", record.resModel);
                body.append("id", record.resId);
                body.append("csrf_token", odoo.csrf_token);
                const res = await fetch("/web/binary/upload_attachment", { method: "POST", body });
                for (const att of await res.json()) {
                    if (att.error) {
                        throw new Error(att.error);
                    }
                    ids.push(att.id);
                }
            }
            await this.orm.write(record.resModel, [record.resId], { x_cv_upload_ids: [[6, 0, ids]] });
            const skipped = files.length - ok.length;
            this.notification.add(
                `${ids.length} CV(s) added as candidates. The AI is reading them now.` +
                    (skipped ? ` ${skipped} file(s) skipped: only PDF or Word (.docx).` : ""),
                { type: "success" }
            );
            await this.action.doAction({ type: "ir.actions.client", tag: "soft_reload" });
        } catch (e) {
            this.notification.add(`Could not add the CVs: ${e.message || e}`, { type: "danger" });
        } finally {
            this.state.busy = false;
        }
    }
}

registry.category("view_widgets").add("cv_dropzone", { component: CvDropzone });
