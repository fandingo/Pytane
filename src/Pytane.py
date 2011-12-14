import getpass
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
    Parses a Noctane ticket given a lxml.html.
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
    overduetickets_tree = parseTree.xpath('//tr[@class="ticket overdue"]')
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
    for i in overduetickets_tree:
        if scrap_level > 0:
            url = URL + TicketSummary(i).url
            browser.open(url)
            data = browser.response().read()
            newtickets.append(TicketComplete(html.document_fromstring(data)))
        else:
            newtickets.append(TicketSummary(i))
    return tickets, newtickets
