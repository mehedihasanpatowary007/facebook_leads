/** @odoo-module **/

import { toRaw } from "@odoo/owl";

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { clearReplyParentId, setReplyParentId } from "@zencore_helpdesk_conversion_api/js/reply_parent_state";

const messageActions = registry.category("mail.message/actions");
const originalReplyAction = messageActions.contains("reply-to")
    ? messageActions.get("reply-to")
    : {};

function isHelpdeskCustomerMessage({ message, thread }) {
    const rawMessage = toRaw(message);
    const rawThread = toRaw(thread || rawMessage?.thread);
    return (
        rawMessage &&
        rawThread?.model === "helpdesk.ticket" &&
        rawMessage.message_type === "comment" &&
        !rawMessage.isSelfAuthored
    );
}

async function selectHelpdeskReply({ message: msg, owner, thread: thr }) {
    const message = toRaw(msg);
    const thread = toRaw(thr || message?.thread);
    const composer = thread?.composer;

    if (!thread || !composer) {
        console.error("[Zencore] Reply failed: missing thread/composer for message", message?.id);
        return;
    }

    const shouldClearReply = message.eq?.(composer.replyToMessage);
    composer.replyToMessage = shouldClearReply ? undefined : message;
    if (shouldClearReply) {
        clearReplyParentId(composer);
    } else {
        setReplyParentId(composer, message.id);
    }

    owner.env.inChatter?.toggleComposer("message", { force: true });
    if (!shouldClearReply) {
        composer.replyToMessage = message;
        setReplyParentId(composer, message.id);
    }
    if (!composer.isFocused) {
        composer.autofocus++;
    }
}

messageActions.add(
    "reply-to",
    {
        ...originalReplyAction,
        condition: (params) => {
            if (isHelpdeskCustomerMessage(params)) {
                return true;
            }
            return originalReplyAction.condition?.(params) ?? false;
        },
        icon: "fa fa-reply",
        name: _t("Reply"),
        onSelected: (params) => {
            if (isHelpdeskCustomerMessage(params)) {
                return selectHelpdeskReply(params);
            }
            return originalReplyAction.onSelected?.(params);
        },
        sequence: (params) => {
            if (isHelpdeskCustomerMessage(params)) {
                return 20;
            }
            const originalSequence = originalReplyAction.sequence;
            return typeof originalSequence === "function"
                ? originalSequence(params)
                : originalSequence ?? 20;
        },
    },
    { force: true }
);
