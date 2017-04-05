# -*- coding: utf-8 -*-
#
# Copyright (C) 2017 Miklos Molnar
#
# All rights reserved.
#
# This software is licensed as described in the file README.md, which
# you should have received as part of this distribution.

from trac.core import Component, implements
from trac.notification.api import (
    NotificationEvent, NotificationSystem, INotificationFormatter)
from trac.web.api import IRequestFilter, ITemplateStreamFilter
from trac.web.chrome import add_notice
from trac.wiki.api import IWikiChangeListener
from trac.util.translation import _

from genshi.builder import tag
from genshi.filters.transform import Transformer
from genshi.input import HTML
from genshi.output import HTMLSerializer

from subscription import SubscriptionHandler


# ==================== Notification events ====================
class WikiPageChangeEvent(NotificationEvent):
    """Represent a wiki page change `NotificationEvent`."""

    def __init__(self, category, target, time, author, comment=None,
                 changes=None):
        super(WikiPageChangeEvent, self).__init__('wikipage', category, target,
                                                  time, author)
        self.comment = comment
        self.changes = changes or {}


# ==================== Notification formatters ====================
class ShortIrcNotificationFormatter(Component):

    implements(INotificationFormatter)

    # Supported styles
    support_styles = [('text/irc', 'ticket'), ('text/irc', 'wikipage')]

    # INotificationFormatter methods
    def get_supported_styles(self, transport):
        if transport == 'irc':
            for style in self.support_styles:
                yield style

    def format(self, transport, style, event):
        if transport != 'irc':
            return ''

        comment = self.smart_truncate(event.comment)
        if event.realm == 'ticket':
            return "Ticket #{0} | {1} by {2} | Comment: {3} | {4}" \
                .format(event.target.id, event.category, event.author,
                        comment, self.env.abs_href.ticket(event.target.id))
        if event.realm == 'wikipage':
            return "Page '{0}' | {1} by {2} | Comment: {3} | {4}" \
                .format(event.target.name, event.category, event.author,
                        comment, self.env.abs_href.wiki(event.target.name))
        return ''

    # helper functions
    def smart_truncate(self, content, length=80, suffix='...'):
        if len(content) <= length:
            return content
        else:
            return ' '.join(content[:length + 1].split(' ')[0:-1]) + suffix


# ==================== Notification plugin ====================
class IrkerNotifcationPlugin(Component):
    implements(IWikiChangeListener, ITemplateStreamFilter, IRequestFilter)
    MODULE_NAME = 'irker_plugin'

    # IRequestFilter methods
    def pre_process_request(self, req, handler):
        """Handles requests containing subscription related actions
        like subscribe and unsubscribe."""
        if not req.session.authenticated:
            return handler
        if req.method == 'GET' and 'subscribe' in req.args:
            if req.args.get('subscribe') == 'Subscribe':
                if not SubscriptionHandler. \
                    is_session_subscribed_for_ticket_changes(
                        self.env, req.session.sid):
                    SubscriptionHandler.add_subscription(
                        self.env, self.log, req.session.sid,
                        'ResourceChangeIrcSubscriber')
                prev_subs = req.session.get('subscriptions', '')
                if len(prev_subs) == 0:
                    req.session['subscriptions'] = req.path_info
                else:
                    req.session['subscriptions'] = \
                        req.session['subscriptions'] + ', %s' % req.path_info
                req.session.save()
                add_notice(req, _('You have subscribed successfully!'))
            else:
                updated_subscriptions = \
                    [x.strip() for x in req.session['subscriptions'].
                        split(',') if not x.strip() == req.path_info]
                req.session['subscriptions'] = ', '.join(updated_subscriptions)
                req.session.save()
                add_notice(req, _('You have unsubscribed successfully!'))
        return handler

    def post_process_request(self, req, template, data, content_type):
        return template, data, content_type

    # ITemplateStreamFilter methods
    def filter_stream(self, req, method, filename, stream, data):
        """Returns a transformed stream extended with irc subscribe button."""
        if not req.session.authenticated:
            return stream

        # Applying changes on ticket.html
        if filename == 'ticket.html':
            stream = stream | Transformer(
                'body//div[@class="trac-content "]').\
                prepend(HTML(self._get_button_html(req)))
            self.log.debug('#IrkerNotifcationPlugin filter_stream')

        if filename == 'wiki_view.html':
            stream = stream | Transformer(
                'body//div[@id="wikipage"]').\
                prepend(HTML(self._get_button_html(req)))
            self.log.debug('#IrkerNotifcationPlugin filter_stream')
        return stream

    def wiki_emit_event(self, page, action, time, author):
        event = WikiPageChangeEvent(action, page, time, author, page.comment)
        try:
            NotificationSystem(self.env).notify(event)
        except Exception as e:
            self.log.error("Failure sending notification when wiki page"
                           " '%s' has changed: %s ",
                           page.name, exception_to_unicode(e))

    def wiki_page_added(self, page):
        self.wiki_emit_event(page, 'added', None, page.author)

    def wiki_page_changed(self, page, version, t, comment, author, ipnr):
        self.wiki_emit_event(page, 'changed', t, page.author)

    def wiki_page_deleted(self, page):
        self.wiki_emit_event(page, 'deleted', None, '')

    def wiki_page_version_deleted(self, page):
        self.wiki_emit_event(page, 'version_deleted', None, '')

    # helper functions
    def _get_button_html(self, req):
        """The construction of subscribe button."""
        # TODO replace with genshi builder
        button = u'''<input type="submit" name="subscribe" value="%s" title="%s" />'''
        if SubscriptionHandler.\
                is_session_subscribed_to(self.env, req.session.sid,
                                         req.path_info):
            button = button % (_('Unsubscribe'), _(
                'Unsubscribe from IRC notifications'))
        else:
            button = button % (_('Subscribe'), _(
                'Subscribe to IRC notifications'))

        return u'''
        <form id="subscribe_irc" method="get" action="%s">
          <div style="float:right;top:0.3em;position:relative;" class="inlinebuttons">
            %s
          </div>
        </form>
        ''' % (req.href + req.path_info, button)
