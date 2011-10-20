import logging
from lxml import etree
from subprocess import Popen, PIPE

logger = logging.getLogger('wikipedia import')

LANGUAGES = ['bg', 'ca', 'cs', 'cy', 'da', 'de', 'el', 'en', 'eo', 'es',
        'et', 'eu', 'fi', 'fr', 'ga', 'gl', 'he', 'hu', 'ia', 'id', 'is',
        'it', 'lv', 'mi', 'ms', 'mt', 'nl', 'nn', 'pl', 'pt', 'ro', 'ru',
        'sv', 'tl', 'tr', 'uk', 'yi']

def summarize(text, language='en', words=70, html=False):
    """ Summarize the given text in language to a maximum of words"""
    if html:
        text = interesting_html(text)
    text = unicode(text)
    txt_len = len(text.split())
    if txt_len == 0:
        return ''
    ratio = max([int(float(words)/float(txt_len) * 100), 2])
    ratio = min(ratio, 20)
    args =['ots']
    args.append('--ratio=%i' % ratio)
    if language in LANGUAGES:
        args.append('--dic=%s' % language)
    args.append('-')
    try:
        process = Popen(args, stdin=PIPE, stdout=PIPE, stderr=PIPE)
        result, err = process.communicate(text.encode('utf-8'))
        if process.returncode != 0:
            logger.error("ots error: %s" % err)
            return ''
    except OSError:
        logger.error("ots not found")
        return ''
    return result

def interesting_html(html):
    doc = etree.ElementTree(etree.HTML(html))
    for e in doc.xpath('//h1|//h2|//h3|//h4|//h5|//h6|/html/head'):
        e.clear()
    return ' '.join(doc.xpath('//text()'))
