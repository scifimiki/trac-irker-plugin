# -*- coding: utf-8 -*-
#
# Copyright (C) 2017 Miklos Molnar
#
# All rights reserved.
#
# This software is licensed as described in the file README.md, which
# you should have received as part of this distribution.

from collections import defaultdict
from trac.config import ConfigSection
from trac.core import Component, Interface, implements, ExtensionPoint
from trac.notification.api import (
     INotificationSubscriber, NotificationSystem, INotificationFormatter)
from trac.notification.mail import RecipientMatcher
from trac.notification.model import Subscription
from trac.util.translation import _
from trac.perm import IPermissionGroupProvider
from trac.web.href import Href


# Subscriber interface
class ISubscriptionInfoProvider(Interface):
        """Interface for querying subscriber information for
           administrative user"""

        def get_subscription_info(self):
            """Map a session id and authenticated flag to an irc id.

            :param sid: the session id
            :param authenticated: 1 for authenticated sessions, 0 otherwise
            :return: tuple (<Name>, <Description>, <IsConfigurable>,
                            <Subcribers>)
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
                        .find_by_sids_and_class(self.env, ((sid, auth),),
                                                class_name):
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
        subscriptions = Subscription.find_by_class(self.env, class_name)
        return self.__class__.__name__, self.description(), False, \
            [(s['sid'], s['id']) for s in subscriptions]


class ResourceChangeIrcSubscriber(Component):
    """Implements a policy to send an irc message to a certain target if it's
       subscribed for the notifications for the given resource."""

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
        for s in Subscription.find_by_class(self.env, class_name):
            sub = list(s.subscription_tuple())
            if not SubscriptionHandler.is_session_subscribed_to(self.env,
               sub[2], resource_id):
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
        subscriptions = Subscription.find_by_class(self.env, class_name)
        return self.__class__.__name__, self.description(), True, \
            [(s['sid'], s['id']) for s in subscriptions]


class CustomQueryIrcSubscriber(Component):
    """Implements notification based on configurable
       custom queries. Conditions can be specified for the change
       content, ticket status."""

    implements(INotificationSubscriber, ISubscriptionInfoProvider)

    irker_custom_config_section = \
        ConfigSection('irker-custom-queries',
                      doc="""
        Custom queries can be assembled by defining conditions with predefined
        elements. The targets of the notifications can also be specified.
        All settings element should start with the name of the custom query
        Custom query has 3 required attributes:
            - description: can be specified simply by <query_name> = <desc>
            - targets: recepients listed separated by comma
                (ex. mmolnar, agal, #IT, #lobby)
                there are special targets marked with '_' prefix
                such as _reporter, _owner, _involved
                Example: <query_name>.targets = <target1>, <target2>, _owner
            - conditions: notification is only sent if all the listed
                conditions are fullfilled. Available condition properties:
                status, type, resolution, owner, reporter, involved
                There is modifier prefix '_' which modifies the conditions to
                check property changes rather that states.
                Conditions should be listed in the following way:
                <query_name>.conditions = <[_]property>:<value>;...
        Here is an exapmle how the custom query can be configured in the
        Trac.ini:
        {{{
        [irker-custom-queries]
        approved_IT = Sends a notification to #IT chan if status is approved
        approved_IT.targets = #IT
        approved_IT.conditions = _resolution:approved
        }}}
        """)

    group_providers = ExtensionPoint(IPermissionGroupProvider)

    # Innec class
    class ConfigurableSubscriber:

        _special_targets = ['_reporter', '_owner', '_involved', '_group']
        _conditions = ['status', 'type', 'resolution', 'owner', 'reporter',
                       'involved']

        def __init__(self, id, desc, targets, conditions, outer_subscriber):
            self.id = id
            self.desc = desc
            self.targets = [x.strip() for x in targets.split(',')]
            self.conditions = self.process_conditions(conditions)
            self.group_providers = outer_subscriber.group_providers
            self.env = outer_subscriber.env
            self.log = outer_subscriber.log

        def process_conditions(self, rawconditions):
            conditions = {}
            for condition in rawconditions.split(';'):
                split_cond = condition.split(':', 1)
                if len(split_cond) != 2:
                    continue
                rule = split_cond[0].strip()
                req = split_cond[1].strip()
                conditions[rule] = req
            return conditions

        def yield_targets(self, ticket, changes):
            for target in self.targets:
                if target.startswith('_'):
                    for spec_target in self.\
                         _handle_special_targets(target, ticket):
                        if spec_target is not None:
                            yield spec_target
                else:
                    yield target

        def is_applicable(self, ticket, changes):
            return self._check_conditions(ticket, changes)

        def _handle_special_targets(self, target, ticket, changes):
            if target not in self._special_targets:
                return None
            if target == '_owner':
                owner_list = [ticket['owner'], ]
                if 'owner' in changes['fields']:
                    owner_list.append(changes['fields']['owner']['new'])
                return owner_list
            if target == '_reporter':
                return [ticket['reporter'], ]
            if target == '_involved':
                return self._get_related_users(ticket, changes)
            if target == '_group':
                # TODO
                pass

        def _get_related_users(self, ticket, changes):
            related_users = [ticket['owner'], ticket['reporter']]
            related_users += \
                [x.strip() for x in (ticket['cc'] or '').split(',')]
            if 'owner' in changes['fields']:
                related_users.append(changes['fields']['owner']['new'])
            for previous_owner in self.env.db_query("""
                    SELECT DISTINCT oldvalue FROM ticket_change
                    WHERE ticket=%s AND field='owner'
                    """, (ticket.id, )):
                related_users.append(previous_owner[0])
            return related_users

        def _check_conditions(self, ticket, changes):
            passed_check = True
            for rawprop, req in self.conditions.iteritems():
                prop = rawprop.lstrip('_')
                if prop not in self._conditions:
                    continue
                # property change related conditions have '_' prefix
                if rawprop != prop:
                    passed_check &= self.\
                        _check_changed(ticket, changes, prop, req)
                elif prop == 'involved':
                    passed_check &= self.\
                        _check_involved(ticket, changes, req)
                else:
                    passed_check &= ticket[prop] == req
            return passed_check

        def _check_changed(self, ticket, changes, prop, req):
            if prop not in changes['fields']:
                return False
            return changes['fields'][prop]['new'] == req

        def _check_involved(self, ticket, changes, req):
            # TODO cache groups
            related_users = set(self._get_related_users(ticket, changes))
            if req in related_users:
                return True
            for sid in related_users:
                groups = self._get_groups_for_user(sid)
                groups = [x for x in groups if
                          x not in ['somebody', 'anonymous', '']]
                self.log.debug('#_check_involved: user: %s, groups: %s'
                               % (sid, ', '.join(groups)))
                if req in groups:
                    return True
            return False

        def _get_groups_for_user(self, sid):
            subjects = set()
            for provider in self.group_providers:
                subjects.update(provider.get_permission_groups(sid) or [])
            return subjects

    def __init__(self):
        # init list of custom queries
        self.custom_queries = self._get_custom_queries()

    # INotificationSubscriber methods
    def matches(self, event):
        class_name = self.__class__.__name__
        format = 'text/irc'
        priority = 0
        href = Href('')
        resource_id = ''
        if event.realm == 'ticket':
            resource = event.target.resource()
            resource_id = href(resource.realm, resource.id)
        else:
            return
        # Managed subscriptions
        for query in self.custom_queries:
            if not query.is_applicable(event.target, event.changes):
                continue
            targets = query.yield_targets(event.target, event.changes)
            for s in Subscription.find_by_class(self.env, class_name):
                sub = list(s.subscription_tuple())
                if sub[2] not in targets:
                    continue
                sub[4] = sub[2]
                sub = tuple(sub)
                yield sub

    def description(self):
        return _("Notify about ticket changes based on custom queries")

    def requires_authentication(self):
        return False

    def default_subscriptions(self):
        class_name = self.__class__.__name__
        return NotificationSystem(self.env).default_subscriptions(class_name)

    # ISubscriptionInfoProvider methods
    def get_subscription_info(self):
        class_name = self.__class__.__name__
        subscriptions = Subscription.find_by_class(self.env, class_name)
        return self.__class__.__name__, self.description(), True, \
            [(s['sid'], s['id']) for s in subscriptions]

    # private methods
    def _get_custom_queries(self):
        required_attrs = {
            'targets': '_owner',
            'conditions': 'always',
        }
        optional_attrs = {}
        known_attrs = required_attrs.copy()
        known_attrs.update(optional_attrs)

        byname = defaultdict(dict)
        for option, value in self.irker_custom_config_section.options():
            parts = option.split('.', 1)
            name = parts[0]
            if len(parts) == 1:
                byname[name].update({'name': name, 'desc': value.strip()})
            else:
                attribute = parts[1]
                known = known_attrs.get(attribute)
                if known is None or isinstance(known, basestring):
                    pass
                elif isinstance(known, int):
                    value = int(value)
                elif isinstance(known, bool):
                    value = as_bool(value)
                elif isinstance(known, list):
                    value = to_list(value)
                byname[name][attribute] = value

        custom_queries = []
        # construct list of custom queries
        for name, attributes in byname.iteritems():
            targets = attributes['targets']
            conditions = attributes['conditions']
            desc = attributes['desc']
            custom_queries.append(CustomQueryIrcSubscriber.
                                  ConfigurableSubscriber(name, desc, targets,
                                                         conditions, self))
        return custom_queries


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
    def update_subscriptions(cls, env, logger, sid, updated_subscriptions,
                             insert):
        remove_subscriptions = len(updated_subscriptions) == 0
        with env.db_transaction as db:
            cursor = db.cursor()
            if remove_subscriptions:
                cursor.execute("""DELETE FROM session_attribute
                      WHERE sid=%s AND authenticated=1 and name='subscriptions'
                      """, (self.sid))
                logger.debug('Subscriptions were removed for %s.' % sid)
            elif insert:
                cursor.execute("""INSERT INTO session_attribute VALUES
                               (%s,%s,'subscriptions',%s)""",
                               (sid, 1, updated_subscriptions)
                               )
                logger.debug(
                    'Subscriptions were inserted into '
                    'session_attribute table for %s.' % sid)
            else:
                cursor.execute("""UPDATE session_attribute SET value=%s
                      WHERE sid=%s and authenticated=1 and name='subscriptions'
                      """, (updated_subscriptions, sid)
                      )
                logger.debug('Subscriptions were updated for %s.' % sid)
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
            result = Subscription. \
                find_by_sids_and_class(env, ((sid, 1),),
                                       'ResourceChangeIrcSubscriber')
            return len(result) != 0

    @classmethod
    def remove_all_subscriptions(cls, env, logger, sid):
        session_subs = SubscriptionHandler.get_session_subscriptions(env, sid)
        session_subs_is_empty = len(session_subs) == 0
        if session_subs_is_empty:
            return
        SubscriptionHandler.update_subscriptions(env, logger, sid, '',
                                                 session_subs_is_empty)

    @classmethod
    def remove_subscriptions(cls, env, logger, sid, subs_to_remove):
        if len(subs_to_remove) == 0:
            return
        session_subs = SubscriptionHandler.get_session_subscriptions(env, sid)
        session_subs_is_empty = len(session_subs) == 0
        existing_subscriptions = set()
        if not session_subs_is_empty:
            existing_subscriptions = \
                set([x.strip() for x in session_subs.split(',')])
        removed_subscriptions = set(subs_to_remove)
        SubscriptionHandler. \
            update_subscriptions(env, logger, sid,
                                 ', '.join(list(existing_subscriptions -
                                                removed_subscriptions)),
                                 session_subs_is_empty)