// /** @odoo-module **/

// import { registry } from "@web/core/registry";
// import { reactive } from "@odoo/owl";

// export const chatReplyService = {
//     start() {

//         return reactive({
//             replyMessage: null,
//         });

//     },
// };

// registry.category("services").add(
//     "chatReply",
//     chatReplyService
// );
/** @odoo-module **/

import { registry } from "@web/core/registry";
import { reactive } from "@odoo/owl";

export const chatReplyService = {
    start() {

        return reactive({
            replyMessage: null,
        });

    },
};

registry.category("services").add(
    "chatReply",
    chatReplyService
);