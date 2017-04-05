# -*- coding: utf-8 -*-
#
# Copyright (C) 2017 Miklos Molnar
#
# All rights reserved.
#
# This software is licensed as described in the file README.md, which
# you should have received as part of this distribution.

import pdb
import json
import socket
import time
from trac.env import IEnvironmentSetupParticipant
from trac.config import (BoolOption, ConfigurationError, IntOption, Option,
                         OrderedExtensionsOption)
from trac.core import (Component, ExtensionPoint, Interface,
                       TracError, implements)
from trac.util.text import exception_to_unicode
from trac.util.translation import _
from trac.notification.api import (INotificationDistributor,
                                   INotificationFormatter)


class IIrcAddressResolver(Interface):
        """Map sessions to irc ids."""

        def get_target_for_session(sid, authenticated):
            """Map a session id and authenticated flag to an irc id.

            :param sid: the session id
            :param authenticated: 1 for authenticated sessions, 0 otherwise
            :return: an irc id or `None`
            """


class SessionIrcResolver(Component):
    """Gets the email address from the user preferences / session."""

    implements(IIrcAddressResolver)

    def get_target_for_session(self, sid, authenticated):
        with self.env.db_query as db:
            cursor = db.cursor()
            cursor.execute("""
                SELECT value
                  FROM session_attribute
                 WHERE sid=%s
                   AND authenticated=%s
                   AND name=%s
            """, (sid, 1 if authenticated else 0, 'irc_nick'))
            result = cursor.fetchone()
            if result:
                return result[0]
            # if there is no match use the session id as fallback
            return sid


class IrcDistributor(Component):
    """Distributes notification events as irc messages."""
    implements(INotificationDistributor, IEnvironmentSetupParticipant)
    host = Option('irker', 'host', 'localhost',
                  doc="Host on which the irker daemon resides.")
    port =\
        IntOption('irker', 'port', 6659,
                  doc="Irker listen port.")
    target_server = \
        Option('irker', 'target_host', 'irc://localhost/',
               doc="IRC server URL to which notifications are to be sent.")

    formatters = ExtensionPoint(INotificationFormatter)

    resolvers =\
        OrderedExtensionsOption('notification',
                                'irc_address_resolvers', IIrcAddressResolver,
                                'SessionIrcResolver', include_missing=False,
                                doc="""Comma seperated list of irc resolver
                                components in the order they will be called.
                                If an irc address is resolved, the remaining
                                resolvers will not be called.
                                """)

    # IEnvironmentSetupParticipant
    def environment_created(self):
        section = 'notification-subscriber'
        if section not in self.config.sections():
            self.config.set(section, 'always_notify_irc',
                            'AlwaysIrcSubscriber')
            self.config.set(section, 'always_notify_irc.distributor',
                            'irc')
            self.config.set(section, 'always_notify_irc.subscribers',
                            '')
            self.config.save()

    def environment_needs_upgrade(self):
        return False

    def upgrade_environment(self):
        pass

    # INotificationDistributor
    def transports(self):
        yield 'irc'

    def distribute(self, transport, recipients, event):
        if transport != 'irc':
            return
        self.log.debug('irc_distribute: %s / %s / %s' %
                       (transport, event.realm, event.category))
        formats = {}
        for f in self.formatters:
            for style, realm in f.get_supported_styles(transport):
                if realm == event.realm:
                    formats[style] = f
        if not formats:
            self.log.error("IrcDistributor No formats found for %s %s",
                           transport, event.realm)
            return
        self.log.debug("IrcDistributor has found the following formats "
                       "capable of handling '%s' of '%s': %s", transport,
                       event.realm, ', '.join(formats.keys()))

        targets = {}
        for sid, authed, target, fmt in recipients:
            if fmt not in formats:
                self.log.debug("IrcDistributor format %s not available for "
                               "%s %s", fmt, transport, event.realm)
                continue

            if sid and not target:
                for resolver in self.resolvers:
                    target = resolver.get_target_for_session(sid, authed)
                    if target:
                        status = 'authenticated' if authed else \
                                 'not authenticated'
                        self.log.debug("IrcDistributor found the target "
                                       "'%s' for '%s (%s)' via %s", target,
                                       sid, status,
                                       resolver.__class__.__name__)
                        break
            if target:
                targets.setdefault(fmt, set()).add(target)
            else:
                status = 'authenticated' if authed else 'not authenticated'
                self.log.debug("IrcDistributor was unable to find an "
                               "address for: %s (%s)", sid, status)

        outputs = {}
        failed = []
        for fmt, formatter in formats.iteritems():
            if fmt not in targets and fmt != 'text/irc':
                continue
            try:
                outputs[fmt] = formatter.format(transport, fmt, event)
            except Exception as e:
                self.log.warning('IrcDistributor caught exception while '
                                 'formatting %s to %s for %s: %s%s',
                                 event.realm, fmt, transport,
                                 formatter.__class__,
                                 exception_to_unicode(e, traceback=True))
                failed.append(fmt)

        # Fallback to text/plain when formatter is broken
        if failed and 'text/plain' in outputs:
            for fmt in failed:
                targets.setdefault('text/plain', set()) \
                         .update(targets.pop(fmt, ()))

        for fmt, trgs in targets.iteritems():
            self.log.debug("IrcDistributor is sending event as '%s' to: %s",
                           fmt, ', '.join(trgs))
            message = self._create_message(fmt, outputs)
            if message:
                trgs = set(trgs)
                for target in trgs:
                    self._do_send(transport, event, message, target)
            else:
                self.log.warning("IrcDistributor cannot send event '%s' as "
                                 "'%s': %s",
                                 event.realm, fmt, ', '.join(trgs))

    def _create_message(self, format, outputs):
        if format not in outputs:
            return None
        preferred = outputs[format]
        if format != 'text/irc' and 'text/irc' in outputs:
            preferred = outputs['text/irc']
        message = preferred
        return message

    def _do_send(self, transport, event, message, target):
        if (not target.startswith('#')):
            target = '%s,isnick' % target
        data = {"to": ('%s%s' % (self.target_server, target)).encode('utf-8').
                strip(), "privmsg": message.encode('utf-8').strip()}
        self.log.info('Send to: %s%s' % (self.target_server, target))
        try:
            s = socket.create_connection((self.host, self.port))
            s.sendall(json.dumps(data))
            s.shutdown(socket.SHUT_RDWR)
            s.close()
        except socket.error, e:
            self.log.info('Error: %s' % e)
            return False
        return True
