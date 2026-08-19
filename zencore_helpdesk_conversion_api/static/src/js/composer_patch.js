/** @odoo-module **/

import { Chatter } from "@mail/chatter/web_portal/chatter";
import { Composer } from "@mail/core/common/composer";
import { onMounted, onPatched } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { clearReplyParentId, getReplyParentId } from "@zencore_helpdesk_conversion_api/js/reply_parent_state";

patch(Chatter.prototype, {
    setup() {
        super.setup(...arguments);
        onMounted(() => this._zencoreApplyHelpdeskChatterClass());
        onPatched(() => this._zencoreApplyHelpdeskChatterClass());
    },

    _zencoreApplyHelpdeskChatterClass() {
        this.rootRef?.el?.classList.toggle(
            "o-zencore-helpdesk-chatter",
            this.state.thread?.model === "helpdesk.ticket"
        );
    },

    /**
     * Opening the normal helpdesk "Send Message" composer must always create a
     * root message. The custom Reply action calls this with force=true after it
     * sets composer.replyToMessage, so reply posts keep their parent_id.
     */
    toggleComposer(mode = false, options = {}) {
        if (
            mode === "message" &&
            !options.force &&
            this.state.thread?.model === "helpdesk.ticket"
        ) {
            this.state.thread.composer.replyToMessage = undefined;
            clearReplyParentId(this.state.thread.composer);
        }
        return super.toggleComposer(mode, options);
    },
});

patch(Composer.prototype, {
    get extraData() {
        const extraData = { ...(super.extraData || {}) };
        const composer = this.props.composer;
        const thread = composer?.thread;
        const replyParentId = getReplyParentId(composer);
        if (thread?.model === "helpdesk.ticket" && replyParentId) {
            extraData.context = {
                ...(extraData.context || {}),
                zencore_reply_parent_id: replyParentId,
            };
        }
        return extraData;
    },

    async _sendMessage(value, postData, extraData = {}) {
        const composer = this.props.composer;
        const thread = composer?.thread;
        const replyParentId = getReplyParentId(composer);
        if (thread?.model === "helpdesk.ticket" && replyParentId) {
            postData.parentId = replyParentId;
            extraData.context = {
                ...(extraData.context || {}),
                zencore_reply_parent_id: replyParentId,
            };
        }
        try {
            return await super._sendMessage(value, postData, extraData);
        } finally {
            clearReplyParentId(composer);
        }
    },
});
