/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { Thread } from "@mail/core/common/thread";
import { onMounted, onPatched } from "@odoo/owl";

/**
 * Patch Thread component to add 'o-zencore-helpdesk-thread' on the root DOM
 * element when the thread belongs to a helpdesk.ticket record.
 *
 * ── Why patch Thread instead of Message ─────────────────────────────────────
 *   There is one Thread per ticket chatter vs N Message components per ticket.
 *   Patching Thread is cheaper and gives a CSS parent scope:
 *
 *     .o-zencore-helpdesk-thread .o-mail-Message { ... }  → scoped to helpdesk
 *     .o-zencore-helpdesk-thread .o-mail-Message.o-selfAuthored { ... }  → agent
 *
 * ── Why onMounted + onPatched ────────────────────────────────────────────────
 *   OWL 2 does not expose a public this.el property.  The root DOM element
 *   lives inside the component's internal virtual DOM tree (__owl__.bdom).
 *   We walk common bdom node shapes until we find an HTMLElement, then
 *   add the class via the native classList API.
 *
 *   onPatched re-runs after every reactive update (e.g. new messages loaded)
 *   to re-apply the class in case the root element is replaced.
 */
patch(Thread.prototype, {

    setup() {
        super.setup(...arguments);

        const applyHelpdeskClass = () => {
            const thread = this.props?.thread;

            // Only apply to helpdesk.ticket threads
            if (!thread || thread.model !== "helpdesk.ticket") return;

            const el = this._zencoreGetRootEl();
            if (!el) return;

            el.classList.add("o-zencore-helpdesk-thread");
        };

        onMounted(applyHelpdeskClass);
        onPatched(applyHelpdeskClass);
    },

    /**
     * Walk OWL 2's internal bdom tree to find the root HTMLElement.
     *
     * OWL 2 virtual DOM node shapes:
     *   BDomNode    → node.el (HTMLElement or Text)
     *   BDomList    → node.children[0].el
     *   BDomComp    → node.component.__owl__.bdom.el (recursive)
     *
     * We stop at the first HTMLElement (nodeType === 1).
     */
    _zencoreGetRootEl() {
        try {
            let bdom = this.__owl__?.bdom;
            // Walk up to 5 levels of wrapping nodes
            for (let i = 0; i < 5 && bdom; i++) {
                if (bdom.el instanceof HTMLElement) return bdom.el;
                // BDomList / multi-root fragment
                if (Array.isArray(bdom.children)) {
                    for (const child of bdom.children) {
                        if (child?.el instanceof HTMLElement) return child.el;
                    }
                }
                // Descend into child or component
                bdom = bdom.child
                    || bdom.component?.__owl__?.bdom
                    || null;
            }
        } catch (_) {
            // Swallow — OWL internals may vary across patch versions
        }
        return null;
    },
});