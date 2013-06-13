#!/bin/env python

"""task.py manages the pdf text extraction process for FCC documents
  using a set of distributed machines, currently based on the AWS infrastructure.

  inject finds new documents that require extraction and puts a task on the SQS queue.
  extract runs the extraction script and puts the resulting data on S3 and sets a result through SQS.
  collect retrieves the results of the work from SQS and S3 and updates the database.
"""

import json
import tempfile
import os.path as path
import subprocess
import re
import glob
import shutil

import boto.sqs
from boto.sqs.message import Message
from boto.s3.connection import S3Connection
from boto.s3.key import Key

from utils import *
import db
import dictconfig


CONFIG = None

def config(key):
    global CONFIG
    if not CONFIG:
        CONFIG = dictconfig.parse()

    return CONFIG[key]

def get_sqs_connection():
    return boto.sqs.connect_to_region(config('aws.region'))

def get_queue(sqs_conn, name):
    try:
        queue = sqs_conn.get_queue(name)
    except:
        warn("error getting queue", name)
        raise

    if not queue:
        raise Exception("SQS queue %s does not exist. Please create it" % (name,)) 
    return queue

def get_s3_connection():
    return S3Connection()

def dict_to_msg(data):
    m = Message()
    m.set_body(json.dumps(data))
    return m

def msg_to_dict(msg):
    return json.loads(msg.get_body())

def inject(limit=None):
    """Submit extraction tasks to the queue.
       This part runs on the local machine."""

    conn = db.connection()
    cur = conn.cursor()

    sqs_conn = get_sqs_connection()
    queue = get_queue(sqs_conn, config('default.injector-queue'))
    
    query = "SELECT id, fcc_num, url FROM filing_docs WHERE status = 'new'"
    if limit:
        query = query + " LIMIT %d" % (int(limit),)

    cur.execute(query)

    for filing_doc_id, fcc_num, url in cur:
        queue.write(dict_to_msg(dict(filing_doc_id=filing_doc_id, fcc_num=fcc_num, url=url)))  #TODO batch sends

    conn.close()

def extract(limit=None, queue_results=True):
    """Extract texts of pdf files specified in queue.
       Result files are placed in S3, along with associated metadata.
       If queue_results is is true, result data is placed on the output queue.
       This part runs on EC2."""

    sqs_conn = get_sqs_connection()
    in_queue = get_queue(sqs_conn, config('default.injector-queue'))

    if queue_results:
        out_queue = get_queue(sqs_conn, config('default.collector-queue'))

    s3_conn = get_s3_connection()
    bucket = s3_conn.get_bucket(config('default.text-bucket'), validate=False)

    counter = 0
    if limit:
        limit = int(limit)

    while True:
        m = sqs_conn.receive_message(in_queue)
        if not len(m):
            continue

        try:
            data = msg_to_dict(m[0])
            warn("extract: input", data)
        except:
            warn("cannot extract data from", m[0].get_body())
            continue

        docid = data['filing_doc_id']
        workdir = tempfile.mkdtemp(prefix="extraction-", suffix='-' + str(docid))
        script = path.join(path.abspath(path.dirname(sys.argv[0])), 'extract')
        rc = subprocess.call(['/bin/sh', script, data['url'], workdir])

        result = {'filing_doc_id': docid, 'fcc_num': data['fcc_num'] }

        if rc != 0:
            result['status'] = 'failed'
        else:
            result['status'] = 'public'
            content = []
            pages = []
            offset = 0
          
            for name in glob.glob(workdir  + '/text/*.txt'):
                m = re.search('page-(\d+).txt', name)
                if not m:
                    warn("Cannot extract page number from filename", name)
                    sys.exit(1)

                f = open(name)
                txt = f.read()
                size = len(txt)

                pages.append({'number': m.group(1), 'size': size, 'offset': offset})
                content.append(txt)

                offset += size
                f.close()
           
            if len(pages):
                content_key = Key(bucket)
                result['content_key'] = content_key.key = "%s.txt" % (docid,) 

                for name, value in result.iteritems():
                    content_key.set_metadata(name, str(value))

                content_key.set_metadata('pagecount', str(len(pages)))

                for idx, page in enumerate(pages):
                    for name, value in page.iteritems():
                        content_key.set_metadata('page.%d.%s' % (idx, name), str(value))

                result['pages'] = pages

                content_key.set_contents_from_string(''.join(content))

        warn("extract output", result)

        if queue_results:
            out_queue.write(dict_to_msg(result))
        
        shutil.rmtree(workdir, True)

        counter += 1
        if limit and counter == int(limit):
            break

   
def extract_batch(limit=None):
    """Extracts data without placing results in sqs"""
    extract(limit=limit, queue_results=False)

def extract_online(limit=None):
    """Extracts data and places result data in queue"""
    extract(limit=limit, queue_results=True)

def update_document(data, content=None):
    """updates database with extracted data."""

    conn = db.connection()
    cur = conn.cursor()

    if data.get('status') == 'public':
        #TODO: avoid doing repeated work. Probably easiest to ignore
        #  use dedicted buckets for batch and online extraction.
        cur.execute("update filing_docs set status = 'public' where id = %s", (data['filing_doc_id'],))

        if 'pages' in data:
            if not content:
                raise Exception("content is unexpectedly empty for data: %s" % (str(data),))

            for page in data['pages']:
                offset, size = page['offset'], page['size']
                pagetext = content[offset:offset+size]
                wordcount = len(pagetext.split(' ')) #roughly
                record = dict(filing_doc_id=data['filing_doc_id'],
                      pagenumber=page['number'],
                      pagetext=pagetext,
                      wordcount=wordcount)

                cur.execute(*db.dict_to_sql_insert('doc_pages', record))
    else:
        cur.execute("update filing_docs set status = 'failed' where id = %s", (data['filing_doc_id'],))

    warn("updated", data)
    conn.commit()
        
def collect(limit=None):
    """Collect extraction results from queue and S3 and stores them in database.
       This part runs on the local machine."""

    sqs_conn = get_sqs_connection()
    queue = get_queue(sqs_conn, config('default.collector-queue'))

    s3_conn = get_s3_connection()

    bucket_name = config('default.text-bucket')
    bucket = s3_conn.lookup(bucket_name, validate=False)
    if not bucket:
        raise Exception("Bucket %s does not exist. Please create it!" % (bucket_name,))

    if limit:
        limit = int(limit)

    msgcount = 0
    process_queue = True

    while process_queue:
        for msg in sqs_conn.receive_message(queue):
            data = msg_to_dict(msg)
            if not isinstance(data, dict):
                warn("sqs msg is not in json format")
                continue
            else:
                warn("process: got data", data) 

            status = data.get('status')
            if status != 'public':
                update_document(data)
                sqs_conn.delete_message(queue, msg)
                continue
           
            try:
                key_value = data['content_key']
            except KeyError:
                warn("cannot get content_key value for data", data)
                sqs_conn.delete_message(queue, msg)
                continue

            content_key = Key(bucket)
            content_key.key = key_value 

            try:
                content = content_key.get_contents_as_string()
            except:
                warn("cannot get extracted S3 text for:", data)
                sqs_conn.delete_message(queue, msg)
                continue

            update_document(data, content)
            content_key.delete()
            sqs_conn.delete_message(queue, msg)
            
            msgcount += 1
            if limit and msgcount == limit:
                process_queue = False
                break

        else: # for loop
            # no more messages
            process_queue = False

def collect_batch(limit=None):
    """Collects completed jobs from S3 and updates database. Needs to avoid repeated work."""

    s3_conn = get_s3_connection()

    bucket_name = config('default.text-bucket')
    bucket = s3_conn.lookup(bucket_name, validate=False)
  
    if not bucket:
        raise Exception("Bucket %s does not exist. Please create it!" % (bucket_name,))

    if limit:
        limit = int(limit)


    for bucket_key in bucket.list():
        
        key = bucket.get_key(bucket_key.key) # need do do a head request to get metadata

        data = {}

        for name in ('filing_doc_id', 'fcc_num', 'pagecount'):
            data[name] = key.get_metadata(name)
   
        try:
            data['pagecount'] = int(data['pagecount'])
        except:
            data['pagecount'] = 0

        pages = []
        for idx in range(data['pagecount']):
            page = {}
            for name in ('number', 'size', 'offset'):
                page[name] = key.get_metadata('page.%d.%s' % (idx, name))
            pages.append(page)

        if len(pages):
            data['pages'] = pages
       
        update_document(data, key.get_contents_as_string())

if __name__ == "__main__":
    import sys

    try:
        action = globals()[sys.argv[1]]
    except:
        warn("cannot find action: ", sys.argv[1])
        sys.exit(1)

    try:
        limit = sys.argv[2]
    except:
        pass

    action(limit)
