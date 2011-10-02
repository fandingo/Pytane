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


import getpass
import sys
import argparse
import cPickle as pickle
from time import sleep
from lxml import html
from mechanize import Browser, CookieJar

class WrongPageError(Exception):
    '''
    Error to raise when an unexpected page loads.
    Program should recover from this.
    '''
    def __init__(self, page):
        self.page = page
        
    def __repr__(self):
        return self.page

class SessionFailureError(Exception):
    '''
    Raised when a session expires unexpectedily.
    '''
    def __init__(self, page):
        self.page = page
        
    def __repr__(self):
        return 'Session failed on %s' % self.page

class ScrapingFailureError(Exception):
    '''
    General error that data parsing failed.
    '''
    def __init__(self, url, tree=None):
        self.url = url
        self.tree = tree
    def __repr__(self):
        return self.url
    
class Ticket:
    '''
    Parses a Noctane ticket given a lxml.html.HtmlElement object with 
    class="ticket"
    '''
    def __init__(self, ticketTree):
        # Get the text fields about a ticket.
        # There is lots of whitespace and escape characters, so strip them.
        text = [x.strip() for x in ticketTree.itertext() if x.strip()]
    
        self.ticketNum = text[0]
        self.description = text[2]
        self.URLPath = '/noc/tickets/' + self.ticketNum
        self.customerCompany = text[3]
        self.customerName = text[4]
        self.engineerName = text[5]
        self.engineerStatus = text[6]
        self.ticketStatus = text[8]
        self.dateOpened = text[9]
        self.dateLatest = text[10]

    def __str__(self):
        return '\n'.join([self.ticketNum, self.description, self.URLPath, 
                          self.customerCompany, self.customerName, self.engineerName, 
                          self.engineerStatus, self.dateOpened, self.dateLatest])

# End Class definitions

def parser():
    '''
    Parse arguments
    '''
    parser_ = argparse.ArgumentParser(description='Advanced Noctane Notifier')
    parser_.add_argument('-u', '--user', nargs=1, help='Noctane user name')
    parser_.add_argument('-e', '--expire-time', type=int, dest='expire', default=10, metavar='N', help='Notifications expire after N seconds.')
    parser_.add_argument('-i', '--check-interval', type=int, dest='interval', default=60, metavar='N', help='Check for tickets every N seconds.')
    parser_.add_argument('-d', '--detail', action='append_const', const=True, help='Increase notification detail. Add additional arguments to get more detail.')
    parser_.add_argument('-v', '--verbose', action='append_const', const=True, help='Verbose output to the terminal (does not affect notification verbosity). Add additional arguments to further increase.')
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
        return args

def browserInit():
    '''
    Set standard, initial browser configuration.
    '''
    browser = Browser()
    browser.set_handle_equiv(True)
    browser.set_handle_redirect(True)
    browser.set_handle_referer(True)
    browser.set_handle_robots(False)
    browser.addheaders = [('user-agent', '   Mozilla/5.0 (X11; U; Linux x86_64; en-US) Mechanize/0.2.4 Fedora/16 (Verne) Pytane/0.1'),
('accept', 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8')]
    return browser


def login(browser, user, tries=3):
    '''
    Login to website.
    '''
    for i in xrange(1, 4):
        if i > 1:
            print('Invalid credentials. Attempt %i/3' % i)
        if not user or i > 1:
            username = raw_input('Noctane user name: ')
        password = getpass.getpass('Noctane password: ')
        browser.open('https://noctane.contegix.com/sign_in')
        try:
            if browser.title() != 'Noctane Login':
                raise WrongPageError(browser.title())
        except Browser.BrowserStateError:
            raise WrongPageError(None)
        browser.select_form(nr=0)
        browser.form['session[email]'] = username
        browser.form['session[password]'] = password
        browser.submit()
        if browser.title() != 'Dashboard \xe2\x80\x93 Noctane':
            browser.back()
        else:
            return

    raise SessionFailureError(browser.title())



def loadTickets(browser):
    '''
    Load webpage that lists tickets. Nothing further.
    '''
    url = 'https://noctane.contegix.com/noc/tickets/mine'
    browser.open(url)
    if browser.title() != 'Tickets Assigned to Me \xe2\x80\x93 Noctane':
        raise WrongPageError(browser.geturl())
    return

def scrapTickets(browser):
    '''
    Parse ticket page and return a list of ticket data.
    '''
    data = browser.response().read()
    parseTree = html.document_fromstring(data)
    ticketTree = parseTree.xpath('//tr[@class="ticket"]')
    tickets = []
    for i in ticketTree:
        print(i)
        tickets.append(Ticket(i))
    return tickets
    
def notify(listData):
    '''
    Trigger notification system. Triggers one notification for entire list.
    '''
    for i in listData:
        print(i)
        print('==========')
    return

def notifyLogin():
    '''
    Send a notification that communication was lost with Noctane and pytane quit.
    '''
    pass

def eventLoop(browser, interval):
    '''
    Check for tickets periodically.
    '''
    while True:
        try:
            loadTickets(browser)
        except WrongPageError as e:
            if e.page == 'https://noctane.contegix.com/sign_in':
                notifyLogin()
                sys.exit('Noctane session failed/expired. Rerun pytane to login again.')
        else:
            notify(scrapTickets(browser))
            print('\n')
            sleep(interval)
    
if __name__ == '__main__':
    try:
        browser = browserInit()
        args = parser()
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
            loadTickets(browser)
        except WrongPageError as e:
            if e.page == 'https://noctane.contegix.com/sign_in':
                if args.cookie:
                    good_cookie = False
                    print('Your cookie was invalid or new. Opening a new session.')
                    # Creating a new browser object in case invalid cookies aren't overwritten
                    # once we use password login page.
                    browser = browserInit()
                try:
                    login(browser, args.user)
                except SessionFailureError:
                    sys.exit('Could not login to Noctane.')
    except (KeyboardInterrupt, SystemExit, EOFError):
        sys.exit('\n\nExiting on user command\n')
	
    try:
        eventLoop(browser, args.interval)
    except (KeyboardInterrupt, SystemExit, EOFError):
        print('\n\nExiting on user command\n')
    finally:
        if not good_cookie:
            sys.stdout.write('Saving cookie...')
            pickle.dump(browser.__dict__['_ua_handlers']['_cookies'].cookiejar, open(args.cookie, 'w'))
            print('  Success!\n\n')
