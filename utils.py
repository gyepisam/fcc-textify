import re
import sys

HOST = 'http://apps.fcc.gov'

def hostify_url(url):
	"""Prepend protocol and host if necessary"""
	if url[0] == '/':
		return HOST + url
	else:
		return url

def search_url(proceeding_num, pagesize=100):
	return hostify_url("/ecfs/comment_search/execute?proceeding=%s&pageSize=%s" % (proceeding_num, pagesize))

def rss_url(proceeding_num):
    return hostify_url("/ecfs/comment_search/rss?proceeding=" + str(proceeding_num))

def warn(*msg):
  """prints msg to stderr"""
  print >> sys.stderr, ' '.join([str(x) for x in msg])

def clean_url(url):
    """removes session id and extra spaces from url"""
    return re.sub(';jsessionid=.+\?', '?', url).strip()
