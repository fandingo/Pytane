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
import datetime
import cPickle as pickle
from time import sleep
from lxml import html
from mechanize import Browser, CookieJar

global URL
URL = 'https://noctane.contegix.com'


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
    
class TicketSummary:
    '''
    Parses a Noctane ticket summary given a lxml.html.HtmlElement object with 
    class="ticket"
    '''
    def __init__(self, ticket_tree, ticket=None):
        # Get the text fields about a ticket.
        # There is lots of whitespace and escape characters, so strip them.
        text = [x.strip() for x in ticket_tree.itertext() if x.strip()]
    
        self.ticket_num = text[0]
        # text[1] is also ticketNum
        self.description = text[2]
        self.url = '/noc/tickets/' + self.ticket_num
        self.customer_company = text[3]
        self.customer_name = text[4]
        self.engineer_name = text[5]
        self.engineer_status = text[6]
        # text[7] is a CSS comment
        self.ticket_status = text[8]
        self.date_opened = text[9]
        self.date_latest = text[10]

    def __str__(self):
        return '\n'.join([self.ticket_num, self.description, self.url, 
                          self.customer_company, self.customer_name, self.engineer_name, 
                          self.engineer_status, self.date_opened, self.date_latest])


class TicketComplete:
    '''
    Parses a Noctane ticket given a lxml.html
    '''
    def __init__(self, ticket_page):
        if ticket_page.xpath('//span[@class="response_due_badge"]'):
            self.response_needed = True
        else:
            self.response_needed = False

        origin_ticket = ticket_page.xpath('//div[@class="original_ticket healthy reply"]')[0]
        raw_origin = [x.strip() for x in origin_ticket.itertext() if x.strip()]
        customer_name = raw_origin[0].replace('Ticket created by ', '').split(' @ ')[0]
        self.organization_name = raw_origin[0].split(' @ ')[1].replace(' via', '')
        date = datetime.datetime.strptime(raw_origin[2], '%B %d, %Y @ %I:%M %p')
        self.origin_response = Response(customer_name, date, raw_origin[3:], Response.TICKET_OPENED)

        raw_responses = []
        for i in ticket_page.xpath('//ul[@class="ticket_responses"]')[0].iterchildren():
            # Insert insead of append, so we get the correct cronological order
            raw_responses.insert(0, i)
        self.responses = []
        for i in raw_responses[:-1]:
            resp = []
            for t in i.itertext():
                if t.strip():
                    resp.append(t.strip())
            comment_type = resp[0].replace(' from', '')
            name = resp[1]
            date = datetime.datetime.strptime(resp[2], '%B %d, %Y @ %I:%M %p')
            self.responses.append(Response(name, date, resp[3:], comment_type))
  
    def __str__(self):
        msg = 'Response Needed: %s\n' % self.response_needed
        msg += str(self.origin_response)
        msg += '\n======================\n'
        for i in self.responses:
            msg += 'From %s on %s\n' % (i.name, i.date.strftime('%H:%M %d/%m'))
        return msg
    
    def mostrecent(self):
        '''
        Get the most recent response. Returns a Response object.
        '''
        if self.responses:
            return self.responses[-1]
        else:
            return self.origin_response
        

class Response:
    '''
    Data about a Noctane response.
    '''
    def __init__(self, name, date, text, response_type):
        '''
        Create a response. date is a datetime object. The type of response can be INTERNAL_COMMENT, INTERNAL_REPLY,
        or EXTERNAL_REPLY.
        '''
        self.name = name
        self.date = date
        self.text = text
        self.response_type = response_type 
    
    def __str__(self):
        return '\n'.join((self.response_type, self.name, self.date.strftime('%H:%M %d/%m/%Y'), '\n'.join(self.text)))


# End Class definitions

def parser():
    '''
    Parse arguments
    '''
    parser_ = argparse.ArgumentParser(description='Advanced Noctane Notifier')
    parser_.add_argument('-u', '--user', nargs=1, help='Noctane user name')
    parser_.add_argument('-e', '--expire-time', type=int, dest='expire', default=10, metavar='N', help='Notifications expire after N seconds.')
    parser_.add_argument('-i', '--check-interval', type=int, dest='interval', default=60, metavar='N', help='Check for tickets every N seconds.')
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

def browserInit():
    '''
    Set standard, initial browser configuration.
    '''
    browser = Browser()
    browser.set_handle_equiv(True)
    browser.set_handle_redirect(True)
    browser.set_handle_referer(True)
    browser.set_handle_robots(False)
    browser.addheaders = [('user-agent', '   Mozilla/5.0 (X11; U; Linux x86_64; en-US) Mechanize/0.2.4 Fedora/16 (Verne) Pytane/0.2'),
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
        browser.open(URL + '/sign_in')
        try:
            if browser.title() != 'Noctane Login':
                raise WrongPageError(browser.title())
        except Browser.BrowserStateError:
            raise WrongPageError(None)
        browser.select_form(nr=0)
        browser.form['session[email]'] = username
        browser.form['session[password]'] = password
        browser.submit()
        if browser.geturl() not in (URL + '/dashboard', URL + '/noc/tickets/mine'):
            print(URL + '/noc/tickets/mine')
            print(browser.title())
            print(browser.geturl())
            browser.back()
        else:
            return

    raise SessionFailureError(browser.title())

def loadTickets(browser):
    '''
    Load webpage that lists tickets. Nothing further.
    '''

    browser.open(URL + '/noc/tickets/mine')
    if browser.title() != 'Tickets Assigned to Me \xe2\x80\x93 Noctane':
        raise WrongPageError(browser.geturl())
    return

def scrapTickets(browser, scrap_level=1):
    '''
    Parse ticket page and return a list of ticket data.
    Scrap_level determines how much ticket data is collected:
    0 = do not fetch full data about any tickets
    1 = fetch full data for new tickets only
    2 = fetch full data for all tickets
    Summary data will be fetched for all tickets.
    '''
    data = browser.response().read()
    parseTree = html.document_fromstring(data)
    existingtickets_tree = parseTree.xpath('//tr[@class="ticket"]')
    newtickets_tree = parseTree.xpath('//tr[@class="ticket due"]')
    tickets = []
    newtickets = []
    for i in existingtickets_tree:
        if scrap_level > 1:
            url = URL + TicketSummary(i).url
            browser.open(url)
            data = browser.response().read()
            tickets.append(TicketComplete(html.document_fromstring(data)))
        else:
            tickets.append(TicketSummary(i))
    for i in newtickets_tree:
        if scrap_level > 0:
            url = URL + TicketSummary(i).url
            browser.open(url)
            data = browser.response().read()
            newtickets.append(TicketComplete(html.document_fromstring(data)))
        else:
            newtickets.append(TicketSummary(i))
    return tickets, newtickets
    
def notify(oldtickets, newtickets):
    '''
    Trigger notification system. Currently it just prints to 
    the terminal.
    '''
    if newtickets:
        print('New Tickets')
    for i in newtickets:
        print(i)
        print('==========')
    if oldtickets:
        print('Old Tickets')
    for i in oldtickets:
        print(i)
        print('==========')
    return

def notifyLogin():
    '''
    Send a notification that communication was lost with Noctane and pytane quit.
    '''
    pass

def eventLoop(browser, interval, detail):
    '''
    Check for tickets periodically.
    '''
    while True:
        try:
            loadTickets(browser)
        except WrongPageError as e:
            if e.page == URL + '/sign_in':
                notifyLogin()
                sys.exit('Noctane session failed/expired. Rerun pytane to login again.')
        else:
            oldtickets, newtickets = scrapTickets(browser, detail) 
            notify(oldtickets, newtickets)
            sleep(interval)
    
if __name__ == '__main__':
    try:
        args = parser()
        browser = browserInit()
        
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
            if e.page == URL + '/sign_in':
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
        eventLoop(browser, args.interval, args.detail)
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
