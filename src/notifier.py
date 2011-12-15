#!/usr/bin/env python

# Copyright 2011, Justin Brown <justin.brown@fandingo.org>.
# 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


import sys
import argparse
import cPickle as pickle
import time
from lxml import html
from mechanize import Browser, CookieJar
import pynotify
import Pytane

global URL
URL = 'https://noctane.contegix.com'



def parser():
    '''
    Parse arguments
    '''
    parser_ = argparse.ArgumentParser(description='Advanced Noctane Notifier')
    parser_.add_argument('-u', '--user', nargs=1, help='Noctane user name')
    parser_.add_argument('-e', '--expire-time', type=int, dest='expire', default=10, metavar='N', help='Notifications expire after N seconds.')
    parser_.add_argument('-i', '--check-interval', type=int, dest='interval', default=60, metavar='N', help='Check for tickets every N seconds.')
    parser_.add_argument('-n', '--new-notify', type=int, dest='nnotify', default=60, metavar='N', help='Send notifications every N seconds for new tickets.')
    parser_.add_argument('-o', '--old-notify', type=int, dest='onotify', default=600, metavar='N', help='Send notifications every N seconds for old tickets.')
    parser_.add_argument('-d', '--detail', action='append_const', const=True, default=[], help='Increase notification detail. Add additional arguments to get more detail.')
    parser_.add_argument('-v', '--verbose', action='append_const', dest='verbosity', default=[], const=True, help='Verbose output to the terminal (does not affect notification verbosity). Add additional arguments to further increase.')
    group = parser_.add_mutually_exclusive_group()
    group.add_argument('-c', '--cookie-file', metavar='FILE', dest='cookie', default=None, help='Cookie file. If an existing cookie, it will be loaded. If a new file, cookie will be stored here.')
    try:
        args = parser_.parse_args(sys.argv[1:])
    except IOError as e:
        sys.exit(': '.join((e.strerror, e.filename)))
    else:
        if args.expire < 0 or args.interval < 0:
            sys.exit('Time must be positive')
        elif args.interval > 600:
            print('Warning: You chose an interval that will allow overdue tickets to accumulate.')
        args.verbosity = len(args.verbosity)
        args.detail = len(args.detail)
        return args

    
def notify(title, msg):
    '''
    Trigger notification system. Currently it just prints to 
    the terminal.
    '''
    newnotify = pynotify.Notification(title, msg)
    newnotify.set_urgency(pynotify.URGENCY_NORMAL)
    newnotify.show()
    return


def eventLoop(browser, interval, detail, nnotify, onotify):
    '''
    Check for tickets periodically.
    Support for three intervals complicates this function.
    interval: seconds between checks to Noctane.
    nnotify: seconds between sending notifications about new tickets.
    onotify: seconds between sending notifications about old tickets.
    '''
    last = 0
    nlast = 0
    olast = 0
    while True:
        try:
            print('loop')
            current = int(time.time())
            print('%i > %i + %i (%i)' % (current, last, interval, last + interval))
            if current > last + interval:
                print('load tickets')
                Pytane.loadTickets(browser)
                last = current
            else:
                print('Sleeping for %i' % (last + interval - current))
                if last + interval - current < 2:
                    # Corrects for rounding errors. Could avoid infinite, short sleeps.
                    time.sleep(2)
                else:
                    time.sleep(last + interval - current)
                continue
        except Pytane.WrongPageError as e:
            if e.page == URL + '/sign_in':
                notify("Fatal Error", 'Noctane session failed/expired. Rerun pytane to login again.')
                sys.exit(1)
        else:
            oldtickets, newtickets = Pytane.scrapTickets(browser, detail) 
            newtickets_shown = False
            if newtickets and current > nlast + nnotify:
                msg = []
                for i in newtickets:
                    msg.append('%s: %s\t\t%s' % (i.date_latest, i.description[:30], i.customer_name[:15]))
                notify("New Tickets", '\n=========\n'.join(msg))
                nlast = current
                newtickets_shown = True
            print('Old: %i > %i + %i (%i)' % (current, last, onotify, last + onotify))
            if oldtickets and current > olast + onotify:
                if newtickets_shown:
                    # Give new tickets notification a chance to clear.
                    time.sleep(10)
                msg = []
                for i in oldtickets:
                    msg.append('%s: %s\t\t%s' % (i.date_latest, i.description[:30], i.customer_name[:15]))
                notify("Old Tickets", '\n=========\n'.join(msg))
                olast = current

    return
    
if __name__ == '__main__':
    try:
        if not pynotify.init("Pytane"):
            sys.exit("Could not initialize notifications")
        args = parser()
        browser = Pytane.browserInit()
        
        cookie = None
        good_cookie = True
        if args.cookie:
            try:
                cookie = pickle.load(open(args.cookie))
                if not isinstance(cookie, CookieJar):
                    raise TypeError
            except (pickle.UnpicklingError, TypeError):
                sys.exit('%s is not a valid cookie' % args.cookie)
            except EOFError:
                pass
            except IOError:
                # File doesn't currently exist. Try to open
                # and see if we get an actual error.
                try:
                    a = open(args.cookie, 'w')
                    a.close()
                except IOError as e:
                    sys.exit(': '.join((e.strerror, e.filename)))
            else:
                browser.__dict__['_ua_handlers']['_cookies'].cookiejar = cookie

        try:
            Pytane.loadTickets(browser)
        except Pytane.WrongPageError as e:
            if e.page == URL + '/sign_in':
                if args.cookie:
                    good_cookie = False
                    print('Your cookie was invalid or new. Opening a new session.')
                    # Creating a new browser object in case invalid cookies aren't overwritten
                    # once we use password login page.
                    browser = Pytane.browserInit()
                try:
                    Pytane.login(browser, args.user)
                except Pytane.SessionFailureError:
                    sys.exit('Could not login to Noctane.')

    except (KeyboardInterrupt, SystemExit, EOFError):
        sys.exit('\n\nExiting on user command\n')

    try:
        eventLoop(browser, args.interval, args.detail, args.nnotify, args.onotify)
    except (KeyboardInterrupt, SystemExit, EOFError):
        print('\n\nExiting on user command\n')
    finally:
        if not good_cookie:
            sys.stdout.write('Saving cookie...')
            try:
                pickle.dump(browser.__dict__['_ua_handlers']['_cookies'].cookiejar, open(args.cookie, 'w'))
            except:
                print('  Failure!\n\n')
                sys.exit(1)
            else:
                print('  Success!\n\n')
