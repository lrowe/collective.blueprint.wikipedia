
import re
import logging

from zope.interface import implements
from zope.interface import classProvides

from collective.transmogrifier.interfaces import ISectionBlueprint
from collective.transmogrifier.interfaces import ISection

from lxml import etree

from wikimarkup.parser import Parser

from summarize import summarize

EXTERNAL_WIKIS = dict(
    wikipedia = "http://en.wikipedia.org/wiki",
    w = "http://en.wikipedia.org/wiki",
    wiktionary = "http://en.wiktionary.org/wiki",
    )

def externalWikiLinkHook(parser_env, namespace, body):
    namespace = namespace.lower()
    (article, pipe, text) = body.partition('|')
    base = EXTERNAL_WIKIS[namespace]
    name = article.strip().capitalize().replace(' ', '_')
    text = (text or article).strip()
    return '<a href="%s/%s">%s</a>' % (base, name, text)


logger = logging.getLogger('wikipedia import')

XMLNS = '{http://www.mediawiki.org/xml/export-0.5/}'
LANGUAGE_PATTERN = re.compile(r'(\n)?\[\[\w\w:[^\]]+\]\](?(1)\n)')
WIKI_PATTERN = re.compile(r'\[\[([\w\W]+?)\]\]')

class Wikipedia(object):
    classProvides(ISectionBlueprint)
    implements(ISection)

    def __init__(self, transmogrifier, name, options, previous):
        self.previous, self.options = previous, options
        self.title_id = {}
        self.item_categories = [] # Must be cleared between items
        self.parser = self.makeParser()
        
        self.path_xml = options.get('xml', None)
        self.start_at_number = int(options.get('start-at-number', 1))
        self.stop_at_number = int(options.get('stop-at-number', 0))
        self.commit_at_every = int(options.get('commit-at-every', 0))
        self.summarize = options.get('summarize', 'false').lower() in ('on', 'true', 'yes')
        namespace_filter = options.get('namespaces', None)
        if namespace_filter is not None:
            namespace_filter = set(namespace_filter.split())
            if 'Main' in namespace_filter:
                namespace_filter.remove('Main')
                namespace_filter.add(None)
        self.namespace_filter = namespace_filter

    def categoryLinkHook(self, parser_env, namespace, body):
        """Internal link hook to record categories"""
        self.item_categories.append(body)
        return ''

    def resolveuidLinkHook(self, parser_env, namespace, body):
        # namespace is going to be None
        (article, pipe, text) = body.partition('|')
        text = (text or article).strip()
        normalized = article.strip().lower().replace(' ', '_')
        pageid = self.title_id.get(normalized)
        if pageid is not None:
            uuid = '%032x' % pageid
            return '<a href="resolveuid/%s">%s</a>' % (uuid, text)
        else:
            return '<a class="missing" href=".">%s</a>' % text

    def makeParser(self):
        parser = Parser()
        parser.registerInternalLinkHook('Wikipedia', externalWikiLinkHook)
        parser.registerInternalLinkHook('w', externalWikiLinkHook)
        parser.registerInternalLinkHook('wiktionary', externalWikiLinkHook)
        parser.registerInternalLinkHook('Category', self.categoryLinkHook)
        parser.registerInternalLinkHook(None, self.resolveuidLinkHook)
        return parser

    def __iter__(self):
        for item in self.previous:
            yield item

        if not self.path_xml:
            return
        fxml = open(self.path_xml)
        j = 0
        
        fxml.seek(0,0)
        _, siteinfo = etree.iterparse(fxml, tag=XMLNS+"siteinfo").next()
        namespace_key = dict((n.text, n.get('key')) for n in siteinfo.find(XMLNS+'namespaces').findall(XMLNS+'namespace'))
        sitename = siteinfo.find(XMLNS+'sitename').text
        sitebase = siteinfo.find(XMLNS+'base').text

        fxml.seek(0,0)
        context = etree.iterparse(fxml, tag=XMLNS+"page")
        for action, element in context:
            title = element.find(XMLNS+'title').text.strip().lower().replace(' ', '_')
            self.title_id[title] = int(element.find(XMLNS+'id').text)
        
        fxml.seek(0,0)
        context = etree.iterparse(fxml, tag=XMLNS+"page")
        for action, element in context:
            title = element.find(XMLNS+'title').text
            namespace = None
            title_parts = title.split(':', 1)
            if len(title_parts) == 2:
                if title_parts[0] in namespace_key:
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
                # remove i18n wiki links from text
                LANGUAGE_PATTERN.subn('', text)
                #import ipdb; ipdb.set_trace()

                del self.item_categories[:]
                html = self.parser.parse(text, show_toc=False)

                j += 1
                if j < self.start_at_number:
                    continue
                logger.warn(str(j)+': '+title)

                item = dict(
                        _wiki_sitename = sitename,
                        _wiki_sitebase = sitebase,
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

        fxml.close()
