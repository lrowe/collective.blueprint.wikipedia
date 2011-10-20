
import re
import logging

from zope.interface import implements
from zope.interface import classProvides

from collective.transmogrifier.interfaces import ISectionBlueprint
from collective.transmogrifier.interfaces import ISection

from lxml import etree
from urllib2 import urlopen
from urllib import quote
from urlparse import urljoin

from wikimarkup.parser import Parser

from summarize import summarize

logger = logging.getLogger('wikipedia import')

XMLNS = '{http://www.mediawiki.org/xml/export-0.5/}'
PARAM_PATTERN = re.compile(r'\{\{\{[^\}]*\}\}\}')
TRANSCLUSION_PATTERN = re.compile(r'\{\{[^\}]*\}\}')

class Wikipedia(object):
    classProvides(ISectionBlueprint)
    implements(ISection)

    def __init__(self, transmogrifier, name, options, previous):
        self.previous, self.options = previous, options
        self.title_id = {}
        self.item_categories = [] # Must be cleared between items
        self.parser = self.makeParser()
        
        self.fxml = open(options['xml'])
        self.start_at_number = int(options.get('start-at-number', 1))
        self.stop_at_number = int(options.get('stop-at-number', 0))
        self.commit_at_every = int(options.get('commit-at-every', 0))
        self.summarize = options.get('summarize', 'false').lower() in ('on', 'true', 'yes')
        self.sitecode = options.get('site-code', 'wiki')
        self.api = options.get('api', "http://en.wikipedia.org/w/api.php")
        namespace_filter = options.get('namespaces', None)
        if namespace_filter is not None:
            namespace_filter = set(namespace_filter.split())
            if 'Main' in namespace_filter:
                namespace_filter.remove('Main')
                namespace_filter.add(None)
        self.namespace_filter = namespace_filter
        self.parseSiteInfo()
        self.interwikimap = self.fetchInterwikiMap()
        self.languages = self.fetchLanguageMatrix()

    def parseSiteInfo(self):
        self.fxml.seek(0,0)
        _, siteinfo = etree.iterparse(self.fxml, tag=XMLNS+"siteinfo").next()
        self.namespace_key = dict((n.text, n.get('key')) for n in siteinfo.find(XMLNS+'namespaces').findall(XMLNS+'namespace'))
        self.sitename = siteinfo.find(XMLNS+'sitename').text
        self.sitebase = siteinfo.find(XMLNS+'base').text

    def fetchInterwikiMap(self):
        # http://www.mediawiki.org/wiki/Interwiki
        url = self.api + "?action=query&meta=siteinfo&siprop=interwikimap&format=xml"
        doc = etree.parse(urlopen(url))
        interwikimap = doc.getroot().find('query').find('interwikimap')
        # add in missing ones..
        for prefix in ('w', 'wikipedia'):
            interwikimap.append(etree.Element('iw',
                    dict(prefix=prefix, local="", language="English", url="http://en.wikipedia.org/wiki/$1", wikiid="", api="",),
                )
            )
        return dict((e.get('prefix'), e) for e in interwikimap.iterchildren())

    def fetchLanguageMatrix(self):
        # http://www.mediawiki.org/wiki/Interwiki
        url = self.api + "?action=sitematrix&smtype=language&format=xml"
        doc = etree.parse(urlopen(url))
        return dict((lang.get('code'), lang) for lang in doc.xpath('/api/sitematrix/language[site/site[@code="%s"]]' % self.sitecode))

    def normalize(self, name):
        name = name.strip()
        if not name:
            return name
        namespace = colon = ''
        if ':' in name:
            (namespace, colon, remainder) = name.partition(':')
            if namespace in self.namespace_key:
                name = remainder
            else:
                namespace = colon = ''
        name = name.strip().replace(' ', '_')
        name = name[0].upper() + name[1:]
        return namespace + colon + name

    def categoryLinkHook(self, parser_env, namespace, body):
        """Internal link hook to record categories"""
        (article, pipe, text) = body.partition('|')
        if article:
            self.item_categories.append(article)
        return ''

    def linkHook(self, parser_env, namespace, body):
        (article, pipe, text) = body.partition('|')
        name = article
        name = self.normalize(name)
        if not text:
            if namespace is None:
                text = article
            else:
                text = "%s:%s" % (namespace, article)
        text = text.strip()
        if namespace in self.namespace_key:
            url = None
            if self.namespace_filter is not None and namespace not in self.namespace_filter:
                if namespace is not None:
                    name = "%s:%s" % (namespace, article)
                url = urljoin(self.sitebase, quote(unicode(name).encode('utf-8')))
            else:
                pageid = self.title_id.get(name)
                if pageid is not None:
                    url = 'resolveuid/%032x' % pageid
            if url:
                return '<a href="%s">%s</a>' % (url, text)
            else:
                return '<span class="missing">%s</span>' % text
        if namespace in self.languages:
            # Filter out language links
            return ''
        iw = self.interwikimap.get(namespace.lower())
        if iw is not None:
            text = (text or article).strip()
            url = iw.get('url').replace('$1', quote(unicode(name).encode('utf-8')))
            return '<a href="%s">%s</a>' % (url, text)
        return ''

    def makeParser(self):
        parser = Parser()
        parser.registerInternalLinkHook('Category', self.categoryLinkHook)
        parser.registerInternalLinkHook('*', self.linkHook)
        return parser

    def __iter__(self):
        for item in self.previous:
            yield item

        j = 0

        self.fxml.seek(0,0)
        context = etree.iterparse(self.fxml, tag=XMLNS+"page")
        for action, element in context:
            title = self.normalize(element.find(XMLNS+'title').text)
            self.title_id[title] = int(element.find(XMLNS+'id').text)
        
        self.fxml.seek(0,0)
        context = etree.iterparse(self.fxml, tag=XMLNS+"page")
        for action, element in context:
            title = element.find(XMLNS+'title').text
            namespace = None
            title_parts = title.split(':', 1)
            if len(title_parts) == 2:
                if title_parts[0] in self.namespace_key:
                    namespace, title = title_parts
            if self.namespace_filter is None or namespace in self.namespace_filter:
                pageid = int(element.find(XMLNS+'id').text)
                revision = element.find(XMLNS+'revision')
                timestamp = revision.find(XMLNS+'timestamp').text
                text = unicode(revision.find(XMLNS+'text').text)
                comment = revision.find(XMLNS+'comment')
                if comment is not None:
                    comment = unicode(comment.text or '')
                contributor = revision.find(XMLNS+'contributor')
                username = contributor.find(XMLNS+'username')
                if username is not None:
                    username = unicode(username.text)

                text, subs = PARAM_PATTERN.subn('', text)
                subs = 1
                while subs:
                    text, subs = TRANSCLUSION_PATTERN.subn('', text)

                del self.item_categories[:]
                html = self.parser.parse(text, show_toc=False)

                j += 1
                if j < self.start_at_number:
                    continue
                logger.warn(str(j)+': '+title)

                item = dict(
                        _wiki_sitename = self.sitename,
                        _wiki_sitebase = self.sitebase,
                        _wiki_namespace = namespace,
                        _wiki_title = title,
                        _wiki_text = text,
                        _wiki_html = html,
                        _wiki_categories = tuple(self.item_categories),
                        _wiki_id = pageid,
                        _wiki_timestamp = timestamp,
                        _wiki_comment = comment,
                        _wiki_username = username,
                        )

                if self.summarize:
                    item['_wiki_summary'] = summarize(html, html=True)

                yield item

                if j == self.stop_at_number and self.stop_at_number != 0:
                    break
                if self.commit_at_every != 0 and j % self.commit_at_every == 0 and j != 0:
                    logger.warn( ('*'*10) + ' COMMITING ' + ('*'*10) )
                    import transaction; transaction.commit()

            element.clear()
            parent = element.getparent()
            previous_sibling = element.getprevious()
            while previous_sibling is not None:
                parent.remove(previous_sibling)
                previous_sibling = element.getprevious()

        #self.fxml.close()
