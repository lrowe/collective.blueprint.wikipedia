
import re
import logging

from zope.interface import implements
from zope.interface import classProvides

from collective.transmogrifier.interfaces import ISectionBlueprint
from collective.transmogrifier.interfaces import ISection

from lxml import etree

from wikimarkup import parse, registerInternalLinkHook

from wikimarkup import parse, registerInternalLinkHook

def wikipediaLinkHook(parser_env, namespace, body):
    # namespace is going to be 'Wikipedia'
    (article, pipe, text) = body.partition('|')
    href = article.strip().capitalize().replace(' ', '_')
    text = (text or article).strip()
    return '<a href="http://en.wikipedia.org/wiki/%s">%s</a>' % (href, text)

registerInternalLinkHook('Wikipedia', wikipediaLinkHook)

# global vars
categories = []
title_id = {}

def categoryLinkHook(parser_env, namespace, body):
    # namespace is going to be 'Category'
    global categories
    categories.append(body)
    return ''

registerInternalLinkHook('Category', categoryLinkHook)

def resolveuidLinkHook(parser_env, namespace, body):
    # namespace is going to be None
    global title_id
    (article, pipe, text) = body.partition('|')
    text = (text or article).strip()
    normalized = article.strip().lower().replace(' ', '_')
    pageid = title_id.get(normalized)
    if pageid is not None:
        uuid = '%032x' % pageid
        return '<a href="resolveuid/%s">%s</a>' % (uuid, text)
    else:
        return '<a class="missing" href=".">%s</a>' % text

registerInternalLinkHook(None, resolveuidLinkHook)

logger = logging.getLogger('wikipedia import')

XMLNS = '{http://www.mediawiki.org/xml/export-0.5/}'
LANGUAGE_PATTERN = re.compile(r'(\n)?\[\[\w\w:[^\]]+\]\](?(1)\n)')
WIKI_PATTERN = re.compile(r'\[\[([\w\W]+?)\]\]')


class Wikipedia(object):
    classProvides(ISectionBlueprint)
    implements(ISection)

    def __init__(self, transmogrifier, name, options, previous):
        self.previous, self.options = previous, options

    def __iter__(self):
        for item in self.previous:
            yield item

        if not self.options.get('xml', None):
            return

        start_at_number = int(self.options.get('start-at-number', 1))
        stop_at_number = int(self.options.get('stop-at-number', 0))
        commit_at_every = int(self.options.get('commit-at-every', 0))

        j = 1
        fxml = open(self.options['xml'])
        
        global title_id
        title_id.clear()
        context = etree.iterparse(fxml, tag=XMLNS+"page")
        for action, element in context:
            title = element.find(XMLNS+'title').text.strip().lower().replace(' ', '_')
            title_id[title] = int(element.find(XMLNS+'id').text)
        
        fxml.seek(0,0)
        context = etree.iterparse(fxml, tag=XMLNS+"page")
        for action, element in context:
            title = element.find(XMLNS+'title').text
            pageid = int(element.find(XMLNS+'id').text)
            text = unicode(element.find(XMLNS+'revision/'+XMLNS+'text').text)
            # remove i18n wiki links from text
            LANGUAGE_PATTERN.subn('', text)
            #import ipdb; ipdb.set_trace()

            global categories
            del categories[:]
            html = parse(text)


            j += 1
            if j < start_at_number:
                continue
            logger.warn(str(j-1)+': '+title)
            if title == 'Angiography':
                import ipdb; ipdb.set_trace()

            yield dict(
                    _wiki_title = title,
                    _wiki_text = text,
                    _wiki_html = html,
                    _wiki_categories = tuple(categories),
                    _wiki_id = pageid,
                    )

            if j == stop_at_number and stop_at_number != 0:
                break
            if commit_at_every != 0 and (j-1) % commit_at_every == 0:
                logger.warn( ('*'*10) + ' COMMITING ' + ('*'*10) )
                import transaction; transaction.commit()

            element.clear()
            parent = element.getparent()
            previous_sibling = element.getprevious()
            while previous_sibling is not None:
                parent.remove(previous_sibling)
                previous_sibling = element.getprevious()

        fxml.close()




