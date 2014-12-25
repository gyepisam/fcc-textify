#!/bin/env python

"""
proceeding.py is responsible for adding new filings
for every proceeding we are interested in.

Since the remote system that does not keep track of what items we've seen,
there's a unique index on the filing.fcc_num  column
to prevent multiple submissions for the same data.

As a result, the update task is inelegantly simple minded and brutish:

Search the FCC site for all proceedings we care about.
Grab all relevant filings and add them to the table.
Existing records will fail and new records will succeed.

The initial search can be run with the command:

    python proceeding.py search

After the initial import, most runs will only add a few new records at a time,
if any.

It can be run once a day, perhap under cron, with the command

  python proceeding.py rss 

Note that the RSS feed data spans 30 days of records, so if the updates lapse
for more than 30 days, a search update must be run (once) to catch up before
restarting with the rss feeds.

The script uses the RAILS_ENV environment variable to determine run modes
so this should be set, either implicitly 

    rails runner "exec ..."
    
or explicitly

    env RAILS_ENV=production ...

It defaults to development when unset.

This script can be run in test mode with the command

    python proceeding.py test 12-375

which prints out the result of parsing the rss feed for proceeding 12-375.

Author: Gyepi Sam <self-github@gyepi.com>

"""

import re
import lxml
from utils import *
import db
import comment

def parse_proceeding_search(proceeding_num):
    """A generator that runs a search on FCC site and produces
    urls for comments and documents relating to specified proceeding number"""

    # In addition to search results, the first page also contains
    # links to subsequent pages
    # which will be subsequently followed.

    try:
        url = search_url(proceeding_num)
    
        content = lxml.html.parse(url)
    
        todo = [content] # addenda...

        pages = [] # pages to follow and process
        cache = {} # ensure unique set

        for url in content.xpath('//a[contains(@href, "/ecfs/comment_search/paginate")]/@href'):
            if not url in cache:
                pages.append(hostify_url(url))
                cache[url] = True

    except Exception as e:
        warn('url: ', url)
        raise e

    # Where there are more than 10 or so pages, the site lists the first N then the last page.
    # For a set of page numbers like 1 2 3 4 5 6 7  N
    # where N is the final page number, we interpolate from 7 + 1 to N - 1
    # If there are no missing values, 7 + 1 would be greater than N - 1 and the range would be empty.
    if len(pages) > 1:
        lastpage = pages.pop()

        lastpage_match = re.match('(.+pageNumber=)(\d+)', lastpage)
        penultimate_match = re.match('(.+pageNumber=)(\d+)', pages[-1])
        for number in range(int(penultimate_match.group(2)) + 1, int(lastpage_match.group(2)) - 1):
            pages.append(lastpage_match.group(1) + str(number))

        pages.append(lastpage)

    todo.extend(pages)
      
    for item in todo:
        if hasattr(item, 'xpath'):
            content = item 
        else:
            try:
                content = lxml.html.parse(item)
            except Exception as e:
                warn("Error fetching or parsing link", item, e)
                continue

        for href in content.xpath('//a[contains(@href, "/ecfs/comment/view")]/@href'):
            yield hostify_url(clean_url(href))

def parse_proceeding_rss(proceeding_num):
    """Parse comment urls out of rss feed. This is faster and less resource
       intensive and perfect for incremental updates"""

    url = rss_url(proceeding_num)
    content = lxml.etree.parse(url)

    for href in content.xpath('/rss/channel/item/link/text()'):
        yield href

def import_comments(proceeding_parser):
    """imports all proceeding comments into filing table and documents into
       filing_docs table. proceeding_parser is either based on a search or an rss feed"""

    conn = db.connection()
    cur = conn.cursor()
    cur.execute("SELECT id as proceeding_id, number FROM proceedings where status = 'Open'")

    try:
        proceedings = cur.fetchall()
    except Exception, e:
        warn("cannot fetch proceeding numbers", e)
        raise

    conn.commit()

    for proceeding_id, number in proceedings:
        for url in proceeding_parser(number):
            comment.import_comment(proceeding_id, url)

    conn.close()

def import_comments_search():
    """Imports comments based on searching for all comments. Useful for bulk
    loading"""
    import_comments(parse_proceeding_search)

def import_comments_rss():
    """Imports comments mentioned in RSS feed, which only covers recent items.
       Useful for incremental updates."""
    import_comments(parse_proceeding_rss)


if __name__ == "__main__":
    import pprint
    import sys
    
    dry_run = False
    proceeding_number = None

    action = sys.argv[1]
    if action == 'test':
        dry_run = True
        action = 'rss'
        proceeding_number = sys.argv[2]
    elif action == 'run':
        action = 'rss'

    runner = globals().get("import_comments_" + action)
    if runner:
        if dry_run:
            parser = globals()['parse_proceeding_' + action]
            pp = pprint.PrettyPrinter(indent=4)
            pp.pprint([x for x in parser(proceeding_number)])
        else:
            runner()
    else:
        warn("cannot understand task: " + action)
        sys.exit(2)
