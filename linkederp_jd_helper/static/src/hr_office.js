/** @odoo-module **/
// HR Office home screen: the pixel office with walking people, a live badge per room and a "Needs you" list.
import { Component, onMounted, onWillStart, onWillUnmount, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const W = 1344, H = 752, P = 3.3; // picture size; P = picture pixels per sprite pixel
const LOOKS = [
    { shirt: "#2061F7", trim: "#ffffff", pants: "#1c2b55", skin: "#e9b48a", hair: "#3b2416" },
    { shirt: "#EE2E24", trim: "#ffffff", pants: "#1c2b55", skin: "#c98a62", hair: "#1a1a1a", long: 1 },
    { shirt: "#ffffff", trim: "#2061F7", pants: "#2b3a66", skin: "#f1c7a3", hair: "#6b3d1e" },
    { shirt: "#3B7BFF", trim: "#0B1B3F", pants: "#3a3a48", skin: "#a86b45", hair: "#1a1a1a" },
    { shirt: "#ffffff", trim: "#EE2E24", pants: "#1c2b55", skin: "#e0a77d", hair: "#2a1a10", long: 1 },
    { shirt: "#0B1B3F", trim: "#3B7BFF", pants: "#3a3a48", skin: "#f1c7a3", hair: "#8a5a2b" },
    { shirt: "#EE2E24", trim: "#0B1B3F", pants: "#2b3a66", skin: "#c98a62", hair: "#3b2416" },
];
// [x, y (feet), wait frames]; each walker loops its route
const ROUTES = [
    [[670, 725, 40], [670, 668, 90], [250, 668, 0], [250, 505, 0], [390, 478, 160], [250, 505, 0], [250, 668, 0]],
    [[670, 725, 120], [670, 668, 70], [1080, 668, 0], [1080, 505, 0], [990, 482, 170], [1080, 505, 0], [1080, 668, 0]],
    [[900, 668, 30], [900, 545, 0], [690, 515, 0], [795, 470, 200], [690, 515, 0], [900, 545, 0], [900, 668, 0], [670, 725, 60]],
    [[140, 240, 120], [360, 240, 90]],
    [[525, 242, 100], [840, 242, 140]],
    [[935, 242, 90], [1180, 242, 120]],
    [[110, 665, 60], [470, 665, 0], [880, 668, 0], [1250, 665, 80], [880, 668, 0], [470, 665, 0]],
];

function drawPerson(g, x, y, o, f, moving, dir) {
    const R = (rx, ry, w, h, c) => { g.fillStyle = c; g.fillRect(Math.round(rx), Math.round(ry), Math.ceil(w * P), Math.ceil(h * P)); };
    const L = x - 5 * P, T = y - 17 * P;
    const px = (cx, cy, w, h, c) => R(L + cx * P, T + cy * P, w, h, c);
    const T2 = T + (moving && f % 2 ? -P : 0);
    const p2 = (cx, cy, w, h, c) => R(L + cx * P, T2 + cy * P, w, h, c);
    g.fillStyle = "#0B1B3F33"; g.beginPath(); g.ellipse(x, y, 6 * P, 2 * P, 0, 0, 7); g.fill();
    const l1 = moving && f === 1 ? 1 : 0, l2 = moving && f === 3 ? 1 : 0;
    px(2, 12, 3, 4 - l1, o.pants); px(5, 12, 3, 4 - l2, o.pants); px(2, 16 - l1, 3, 1, "#1a1a2a"); px(5, 16 - l2, 3, 1, "#1a1a2a");
    p2(1, 7, 8, 5, o.shirt); p2(1, 7, 8, 1, o.trim);
    const a = moving ? (f === 1 ? 1 : f === 3 ? -1 : 0) : 0;
    p2(0, 7 + a, 1, 4, o.shirt); p2(9, 7 - a, 1, 4, o.shirt); p2(0, 11 + a, 1, 1, o.skin); p2(9, 11 - a, 1, 1, o.skin);
    p2(2, 1, 6, 6, o.skin); p2(2, 0, 6, 2, o.hair); p2(1, 1, 1, 4, o.hair); p2(8, 1, 1, 4, o.hair);
    if (dir === "up") {
        p2(2, 2, 6, 4, o.hair);
    } else {
        p2(3, 4, 1, 1, "#1a1a2a"); p2(6, 4, 1, 1, "#1a1a2a");
        if (o.long) { p2(1, 5, 1, 3, o.hair); p2(8, 5, 1, 3, o.hair); }
    }
}

export class HrOffice extends Component {
    static template = "linkederp_jd_helper.HrOffice";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.canvas = useRef("walkers");
        this.state = useState({ data: { rooms: [], todo: [] }, hover: null });
        onWillStart(async () => {
            this.state.data = await this.orm.call("linkederp.hr.office", "get_overview", []);
        });
        onMounted(() => this.startWalkers());
        onWillUnmount(() => cancelAnimationFrame(this.frame));
    }

    pos(box) {
        const [l, t, r, b] = box;
        return `left:${(l / W) * 100}%;top:${(t / H) * 100}%;width:${((r - l) / W) * 100}%;height:${((b - t) / H) * 100}%;`;
    }

    openRoom(room) {
        if (!room.built) {
            this.notification.add(`${room.name} (${room.manager}'s room) is coming soon.`, { type: "info" });
            return;
        }
        this.action.doAction(room.action_id);
    }

    open(item) {
        this.action.doAction(item.action);
    }

    startWalkers() {
        const cv = this.canvas.el;
        if (!cv) {
            return;
        }
        const g = cv.getContext("2d");
        const walkers = ROUTES.map((rt, i) => ({ rt, i: 1 % rt.length, x: rt[0][0], y: rt[0][1], wait: rt[0][2] + i * 25, o: LOOKS[i], t: 0, dir: "down" }));
        const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        const step = () => {
            g.clearRect(0, 0, W, H);
            for (const w of walkers) {
                w.moving = false;
                if (w.wait > 0) {
                    w.wait--;
                } else {
                    const [tx, ty, tw] = w.rt[w.i], dx = tx - w.x, dy = ty - w.y, d = Math.hypot(dx, dy);
                    if (d <= 1.1) {
                        w.x = tx; w.y = ty; w.wait = tw; w.i = (w.i + 1) % w.rt.length;
                    } else {
                        w.x += (dx / d) * 1.1; w.y += (dy / d) * 1.1; w.moving = true;
                        w.dir = Math.abs(dy) > Math.abs(dx) && dy < 0 ? "up" : "down"; w.t++;
                    }
                }
            }
            [...walkers].sort((a, b) => a.y - b.y).forEach((w) => drawPerson(g, w.x, w.y, w.o, (w.t >> 3) % 4, w.moving, w.dir));
            if (!reduce) {
                this.frame = requestAnimationFrame(step);
            }
        };
        step();
    }
}

registry.category("actions").add("linkederp_hr_office", HrOffice);
