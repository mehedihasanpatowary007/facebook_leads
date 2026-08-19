/** @odoo-module **/

const replyParentByComposer = new WeakMap();

export function setReplyParentId(composer, messageId) {
    if (!composer || !messageId) {
        return;
    }
    replyParentByComposer.set(composer, messageId);
}

export function getReplyParentId(composer) {
    return composer ? replyParentByComposer.get(composer) : undefined;
}

export function clearReplyParentId(composer) {
    if (composer) {
        replyParentByComposer.delete(composer);
    }
}
