# trac-irker-plugin

Plugin to announce Trac changes via Irker.


## Installation

Deploy to a specific Trac environment:

    $ cd /path/to/pluginsource
    $ python setup.py bdist_egg
    $ cp dist/*.egg /path/to/projenv/plugins

Enable plugin in trac.ini:

    [components]
    irker_notification.* = enabled

Configuration in trac.ini:

    [irker]
    host = localhost
    port = 6659
    target = irc://localhost/#commits


## Usage

The nick name used in IRC can be specified in Preferences / 
Irker Settings page. The default nick is the username (sid).
The user can manage his/her existing subscriptions on the
preferences page too.

The authenticated user can subscribe/unsubscribe with the
appropriate buttons, that can be found at the top right corner
of the ticket and wiki page boxes.

The trac administrator can remove all subscriptions from a user
and create new subscriptions (even for irc channels) from the
Admin / Irker Notifications page.
    
## License

Copyright (c) 2014, Sebastian Southen
Copyright (c) 2017, Miklos Molnar

All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions
are met:

1. Redistributions of source code must retain the above copyright
   notice, this list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright
   notice, this list of conditions and the following disclaimer in
   the documentation and/or other materials provided with the
   distribution.
3. The name of the author may not be used to endorse or promote
   products derived from this software without specific prior
   written permission.

THIS SOFTWARE IS PROVIDED BY THE AUTHOR `AS IS'' AND ANY EXPRESS
OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY
DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE
GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
