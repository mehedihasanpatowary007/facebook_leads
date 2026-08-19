/** @odoo-module **/

import { registry } from "@web/core/registry";

const messageActions = registry.category("mail.message/actions");

for (const id of ["reply-to", "reply", "reply-to-message"]) {
    if (messageActions.contains(id)) {
        messageActions.add(
            id,
            {
                ...messageActions.get(id),
                condition: () => false,
            },
            { force: true },
        );
    }
}
