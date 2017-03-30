# -*- coding: utf-8 -*-
#
# Copyright (C) 2017 Miklos Molnar
#
# All rights reserved.
#
# This software is licensed as described in the file README.md, which
# you should have received as part of this distribution.
import pdb
from pkg_resources import resource_filename
from trac.admin import IAdminPanelProvider
from trac.core import Component, ExtensionPoint, implements
from trac.notification.model import Subscription
from trac.util.translation import _, dgettext
from trac.prefs.api import IPreferencePanelProvider
#from trac.prefs.web_ui import _do_save
from trac.web.chrome import Chrome, ITemplateProvider, add_notice, add_warning, web_context
from trac.web.api import IRequestHandler

from subscription import ISubscriptionInfoProvider, SubscriptionHandler

class IrkerPreferencePanel(Component):

    implements(IPreferencePanelProvider)

    _form_fields = ('irc_nick',)

    # IPreferencePanelProvider methods

    def get_preference_panels(self, req):
        yield 'irker_settings', _("Irker Settings")

    def render_preference_panel(self, req, panel):
        if req.method == 'POST':
            if req.args.get('unsub'):
                sel = req.args.get('unsub')
                sel = sel if isinstance(sel, list) else [sel]
                SubscriptionHandler.remove_subscriptions(self.env, self.log, req.session.sid, sel)
                add_notice(req, _("The selected subscriptions have been "
                                  "revoked."))
            #_do_save(req, panel, self._form_fields)
            self._do_save(req, panel)
        subscriptions = SubscriptionHandler.get_session_subscriptions(self.env,req.session.sid)
        subscriptions = [(x.strip(), x.strip().split('/')[-1]) for x in subscriptions.split(',')]
        ticket_subscriptions = sorted([(ox, '#%s'%x) for (ox, x) in subscriptions if x.isdigit()], key=lambda subs: int(subs[1].lstrip('#')))
        page_subscriptions = sorted([(ox, x) for (ox, x) in subscriptions if not x.isdigit()])
        subscriptions = ticket_subscriptions + page_subscriptions
        return 'prefs_irker.html', {'subscriptions' : subscriptions, \
                                    'context': web_context(req)
                                    }

    def _do_save(self, req, panel):
        for field in self._form_fields:
            val = req.args.get(field, '').strip()
            if val:
                    req.session[field] = val
            elif (field in req.args or field + '_cb' in req.args) and \
                    field in req.session:
                del req.session[field]
        add_notice(req, _("Your preferences have been saved."))
        #req.redirect(req.href.prefs(panel))
    
class IrkerAdminModule(Component):
    """Implements the admin page for workflow editing. See 'Ticket System' section."""

    implements(IAdminPanelProvider, ITemplateProvider)

    irc_subscribers = ExtensionPoint(ISubscriptionInfoProvider)
    
    # helper functions
    def _get_subscription_info(self):
        subscribers = {}
        for subscriber in self.irc_subscribers:
            name, desc, configurable, subs = subscriber.get_subscription_info()
            rule = {}
            rule['desc'] = desc
            rule['subs'] = subs
            rule['conf'] = configurable
            subscribers[name] = rule
        return subscribers

    def _get_validated_subscriptions(self, subscriptions, subscription_type):
        # for tickets only accept positive integers
        if subscription_type == 'ticket':
            filtered_subs = [x.strip() for x in subscriptions.split(',') if x.strip().isdigit()]
        else: # otherwise page name should be consist of alphanumeric characters
            filtered_subs = [x.strip() for x in subscriptions.split(',') if x.strip().isalnum()]
        subs = [ '/%s/%s' % (subscription_type, x) for x in filtered_subs]
        return set(subs)
            
    # IAdminPanelProvider methods
    def get_admin_panels(self, req):
        if 'TICKET_ADMIN' in req.perm:
            yield ('ticket', dgettext("messages", ("Ticket System")),
                   'irkeradmin', _("Irker Notifications"))

    def render_admin_panel(self, req, cat, page, path_info):
        req.perm.assert_permission('TICKET_ADMIN')

        subscribers = self._get_subscription_info()
        
        data = { 'subscribers': subscribers }
        if req.method == "GET":
            return ('irker_admin.html', data)
        
        if req.method == 'POST':
            if req.args.get('save'): # save changes from table
               for name, subscriber in subscribers.iteritems():
                    if not subscriber['conf']: # if subscriber class is not configurable do not display it in the table
                        continue
                    updated_subs = [x.strip() for x in req.args.get('subscribers_%s' % name).split(',')]
                    unhandled_subs = updated_subs
                    prev_subs = subscriber['subs']
                    for subscriber_id, sub_id in prev_subs: # iterate through previous subscriptions
                        self.log.debug('Subscriber removed from %s: %s' % (name, subscriber_id))
                        if subscriber_id in updated_subs: # if subscription is preserved just mark it as handled
                            unhandled_subs.remove(subscriber_id)
                        else: # otherwise delete subscription
                            Subscription.delete(self.env, sub_id)
                            SubscriptionHandler.remove_all_subscriptions(self.env,self.log,subscriber_id)
                    for sub in unhandled_subs:
                        SubscriptionHandler.add_subscription(self.env,self.log,sub,name)
            if req.args.get('remove'): # remove subscriptions from user
                if len(req.args.get('name')) == 0:
                    add_warning(req, _('Name field cannot be empty.'))
                else:
                    subs_to_remove = Subscription.find_by_sid_and_distributor(self.env, req.args.get('name'), 1, 'irc')
                    for sub in subs_to_remove:
                        Subscription.delete(self.env, sub['id'])
                        SubscriptionHandler.remove_all_subscriptions(self.env,self.log,subscriber_id)
                    add_notice(req, _('Subscriptions have been removed.'))
            if req.args.get('addsubs'): # add new subscriptions
                if len(req.args.get('subscribers')) == 0:
                    add_warning(req, _('First input field cannot be empty.'))
                else:
                    new_subs = [x.strip() for x in req.args.get('subscribers').split(',')]
                    res_subscriber = subscribers['ResourceChangeIrcSubscriber']
                    current_subs = res_subscriber['subs']
                    for subscriber_id in new_subs: # iterate throught new subscribers
                        if subscriber_id not in [ sid for sid, id in current_subs ]: # if it is not subscribed already
                            SubscriptionHandler.add_subscription(self.env,self.log,subscriber_id,'ResourceChangeIrcSubscriber')
                        # update session specific resource subscriptions
                        session_subs = SubscriptionHandler.get_session_subscriptions(self.env,subscriber_id)
                        session_subs_is_empty = len(session_subs) == 0
                        existing_subscriptions = set()
                        if not session_subs_is_empty:
                            existing_subscriptions = set([x.strip() for x in session_subs.split(',')])
                        added_subscriptions = self._get_validated_subscriptions(req.args.get('subscriptions'),req.args.get('subs_type'))
                        if len(added_subscriptions) == 0:
                            add_warning(req, _('There were no valid resource IDs provided! Please check the resource type before submitting.'))
                        else:
                            SubscriptionHandler.update_subscriptions(self.env,self.log,subscriber_id, ', '.join(list(existing_subscriptions | added_subscriptions)), session_subs_is_empty)
                            add_notice(req, _('Subscriptions have been added.'))
                
        data = { 'subscribers': self._get_subscription_info() }
        return ('irker_admin.html', data)

    # ITemplateProvider methods
    def get_htdocs_dirs(self):
        return []

    def get_templates_dirs(self):
        return [resource_filename(__name__, 'templates')]
