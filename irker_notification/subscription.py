# -*- coding: utf-8 -*-
#
# Copyright (C) 2017 Miklos Molnar
#
# All rights reserved.
#
# This software is licensed as described in the file README.md, which
# you should have received as part of this distribution.

from trac.core import Component, Interface, implements
from trac.notification.api import  INotificationSubscriber, NotificationSystem, INotificationFormatter
from trac.notification.mail import RecipientMatcher
from trac.notification.model import Subscription
from trac.util.translation import _
from trac.web.href import Href

# Subscriber interface
class ISubscriptionInfoProvider(Interface):
	    """Interface for querying subscriber information for administrative user"""
	
	    def get_subscription_info(self):
	        """Map a session id and authenticated flag to an irc id.
	
	        :param sid: the session id
	        :param authenticated: 1 for authenticated sessions, 0 otherwise
	        :return: tuple (<Name>, <Description>, <IsConfigurable>, <Subcribers>)
	        """  
            
# Subscriber interface implementations            
class TicketReporterAndOwnerSubscriber(Component):
    """Allows the users to subscribe to tickets that they report."""

    implements(INotificationSubscriber, ISubscriptionInfoProvider)

    # INotificationSubscriber methods
    def matches(self, event):
        if event.realm != 'ticket':
            return
        if event.category not in ('created', 'changed', 'attachment added',
                                  'attachment deleted'):
            return

        ticket = event.target
        format = 'text/irc'
        matcher = RecipientMatcher(self.env)
        for role in ('reporter', 'owner'):
            recipient = matcher.match_recipient(ticket[role])
            if not recipient:
                return
            sid, auth, addr = recipient

            # Default subscription
            for s in self.default_subscriptions():
                yield s[0], s[1], sid, auth, addr, s[2], s[3], s[4]

            if sid:
                class_name = self.__class__.__name__
                for s in Subscription \
                        .find_by_sids_and_class(self.env, ((sid, auth),), class_name):
                    yield s.subscription_tuple()

    def description(self):
        return _("Ticket that I reported or I am assigned to is modified")

    def default_subscriptions(self):
        class_name = self.__class__.__name__
        return NotificationSystem(self.env).default_subscriptions(class_name)

    def requires_authentication(self):
        return True
        
    # ISubscriptionInfoProvider methods
    def get_subscription_info(self):
        class_name = self.__class__.__name__
        subscriptions = Subscription.find_by_class(self.env,class_name)
        return self.__class__.__name__, self.description(), False, [(s['sid'], s['id']) for s in subscriptions]

       
class ResourceChangeIrcSubscriber(Component):
    """Implement a policy to send an irc message to a certain target if it's subscribed
       for the notifications for the given resource."""

    implements(INotificationSubscriber, ISubscriptionInfoProvider)
    
    # INotificationSubscriber methods
    def matches(self, event):
        class_name = self.__class__.__name__
        format = 'text/irc'
        priority = 0
        href = Href('')
        resource_id = ''
        if event.realm == 'ticket' or event.realm == 'wikipage':
            resource = event.target.resource()
            resource_id = href(resource.realm, resource.id)
        else:
            return
        # Managed subscriptions
        for s in Subscription.find_by_class(self.env,class_name):
            sub = list(s.subscription_tuple())
            if not SubscriptionHandler.is_session_subscribed_to(self.env, sub[2], resource_id):
                continue
            sub[4] = sub[2]
            sub = tuple(sub)
            yield sub

    def description(self):
        return _("Notify about ticket and wiki changes for subscribers")

    def requires_authentication(self):
        return False

    def default_subscriptions(self):
        class_name = self.__class__.__name__
        return NotificationSystem(self.env).default_subscriptions(class_name)
        
    # ISubscriptionInfoProvider methods
    def get_subscription_info(self):
        class_name = self.__class__.__name__
        subscriptions = Subscription.find_by_class(self.env,class_name)
        return self.__class__.__name__, self.description(), True, [(s['sid'], s['id']) for s in subscriptions]
        
# Subscription handler
class SubscriptionHandler(Component):
    
    @classmethod
    def add_subscription(cls, env, logger, sub, name):
        rule = Subscription(env)
        rule['sid'] = sub
        rule['authenticated'] = 1
        rule['distributor'] = 'irc'
        rule['format'] = 'text/irc'
        rule['adverb'] = 'always'
        rule['class'] = name
        Subscription.add(env, rule)
        logger.debug('Subscriber added to %s: %s' % (name, sub))

    @classmethod
    def update_subscriptions(cls, env, logger, sub_name, updated_subscriptions, insert):
        with env.db_transaction as db:
            if insert:
                db("INSERT INTO session_attribute VALUES (%s,%s,'subscriptions',%s)",
                    (sub_name, 1, updated_subscriptions)
                )
                logger.debug('Subscriptions were inserted into session_attribute table for %s.' % sub_name)
            else:
                db("""UPDATE session_attribute SET value=%s WHERE sid=%s and authenticated=1 and name='subscriptions'""",
                    (updated_subscriptions, sub_name)
                   )
                logger.debug('Subscriptions were updated for %s.' % sub_name)
        env.invalidate_known_users_cache()
    
    @classmethod
    def get_session_subscriptions(cls, env, sid):    
        with env.db_query as db:
            cursor = db.cursor()
            cursor.execute("""
                SELECT value
                  FROM session_attribute
                 WHERE sid=%s
                   AND authenticated=%s
                   AND name=%s
            """, (sid, 1, 'subscriptions'))
            result = cursor.fetchone()
            if result:
                return result[0]
            return ''

    @classmethod
    def is_session_subscribed_to(cls, env, sid, resource_id):
        with env.db_query as db:
            cursor = db.cursor()
            cursor.execute("""
                SELECT value
                  FROM session_attribute
                 WHERE sid=%s
                   AND authenticated=%s
                   AND name=%s
            """, (sid, 1, 'subscriptions'))
            result = cursor.fetchone()
            if result:
                split_res = [x.strip() for x in result[0].split(',')]
                return resource_id in split_res
            return False

    @classmethod
    def is_session_subscribed_for_ticket_changes(cls, env, sid):
        with env.db_query as db:
            result = Subscription.find_by_sids_and_class(env, ((sid, 1),), 'ResourceChangeIrcSubscriber')
            return len(result) != 0