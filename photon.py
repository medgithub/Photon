#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The Photon main part."""
from __future__ import print_function

import argparse
import os
import random
import re
import sys
import time
import warnings

import requests

import core.config
from core.updater import updater
from core.flash import flash
from core.mirror import mirror
from core.prompt import prompt
from core.requester import requester
from core.config import badTypes, intels
from core.zap import zap
from core.utils import top_level, extract_headers, verb, is_link, entropy, regxy, remove_regex, timer, writer
from core.colors import bad, good, info, run, green, red, white, end

try:
    from urllib.parse import urlparse  # For Python 3
    python2, python3 = False, True
except ImportError:
    from urlparse import urlparse  # For Python 2
    python2, python3 = True, False


try:
    input = raw_input
except NameError:
    pass


# Just a fancy ass banner
print('''%s      ____  __          __
     / %s__%s \/ /_  ____  / /_____  ____
    / %s/_/%s / __ \/ %s__%s \/ __/ %s__%s \/ __ \\
   / ____/ / / / %s/_/%s / /_/ %s/_/%s / / / /
  /_/   /_/ /_/\____/\__/\____/_/ /_/ %sv1.1.5%s\n''' %
      (red, white, red, white, red, white, red, white, red, white, red, white,
       red, white, end))

# Disable SSL related warnings
warnings.filterwarnings('ignore')

# Processing command line arguments
parser = argparse.ArgumentParser()
# Options
parser.add_argument('-u', '--url', help='root url', dest='root')
parser.add_argument('-c', '--cookie', help='cookie', dest='cook')
parser.add_argument('-r', '--regex', help='regex pattern', dest='regex')
parser.add_argument('-e', '--export', help='export format', dest='export')
parser.add_argument('-o', '--output', help='output directory', dest='output')
parser.add_argument('-l', '--level', help='levels to crawl', dest='level',
                    type=int)
parser.add_argument('-t', '--threads', help='number of threads', dest='threads',
                    type=int)
parser.add_argument('-d', '--delay', help='delay between requests',
                    dest='delay', type=float)
parser.add_argument('-v', '--verbose', help='verbose output', dest='verbose',
                    action='store_true')
parser.add_argument('-s', '--seeds', help='additional seed URLs', dest='seeds',
                    nargs="+", default=[])
parser.add_argument('--stdout', help='send variables to stdout', dest='std')
parser.add_argument('--user-agent', help='custom user agent(s)',
                    dest='user_agent')
parser.add_argument('--exclude', help='exclude URLs matching this regex',
                    dest='exclude')
parser.add_argument('--timeout', help='http request timeout', dest='timeout',
                    type=float)

# Switches
parser.add_argument('--clone', help='clone the website locally', dest='clone',
                    action='store_true')
parser.add_argument('--headers', help='add headers', dest='headers',
                    action='store_true')
parser.add_argument('--dns', help='enumerate subdomains and DNS data',
                    dest='dns', action='store_true')
parser.add_argument('--ninja', help='ninja mode', dest='ninja',
                    action='store_true')
parser.add_argument('--keys', help='find secret keys', dest='api',
                    action='store_true')
parser.add_argument('--update', help='update photon', dest='update',
                    action='store_true')
parser.add_argument('--only-urls', help='only extract URLs', dest='only_urls',
                    action='store_true')
parser.add_argument('--wayback', help='fetch URLs from archive.org as seeds',
                    dest='archive', action='store_true')
args = parser.parse_args()


# If the user has supplied --update argument
if args.update:
    updater()
    quit()

# If the user has supplied a URL
if args.root:
    main_inp = args.root
    if main_inp.endswith('/'):
        # We will remove it as it can cause problems later in the code
        main_inp = main_inp[:-1]
# If the user hasn't supplied an URL
else:
    print('\n' + parser.format_help().lower())
    quit()

clone = args.clone
headers = args.headers  # prompt for headers
verbose = args.verbose  # verbose output
delay = args.delay or 0  # Delay between requests
timeout = args.timeout or 6  # HTTP request timeout
cook = args.cook or None  # Cookie
api = bool(args.api)  # Extract high entropy strings i.e. API keys and stuff
ninja = bool(args.ninja)  # Ninja mode toggle
crawl_level = args.level or 2  # Crawling level
thread_count = args.threads or 2  # Number of threads
only_urls = bool(args.only_urls)  # Only URLs mode is off by default

# Variables we are gonna use later to store stuff
keys = set()  # High entropy strings, prolly secret keys
files = set()  # The pdf, css, png, etc files.
intel = set()  # The email addresses, website accounts, AWS buckets etc.
robots = set()  # The entries of robots.txt
custom = set()  # Strings extracted by custom regex pattern
failed = set()  # URLs that photon failed to crawl
scripts = set()  # THe Javascript files
external = set()  # URLs that don't belong to the target i.e. out-of-scope
# URLs that have get params in them e.g. example.com/page.php?id=2
fuzzable = set()
endpoints = set()  # URLs found from javascript files
processed = set()  # URLs that have been crawled
# URLs that belong to the target i.e. in-scope
internal = set([s for s in args.seeds])

everything = []
bad_intel = set()  # Unclean intel urls
bad_scripts = set()  # Unclean javascript file urls

core.config.verbose = verbose

if headers:
    headers = extract_headers(prompt())

# If the user hasn't supplied the root URL with http(s), we will handle it
if main_inp.startswith('http'):
    main_url = main_inp
else:
    try:
        requests.get('https://' + main_inp)
        main_url = 'https://' + main_inp
    except:
        main_url = 'http://' + main_inp

schema = main_url.split('//')[0] # https: or http:?
# Adding the root URL to internal for crawling
internal.add(main_url)
# Extracts host out of the URL
host = urlparse(main_url).netloc

output_dir = args.output or host

try:
    domain = top_level(main_url)
except:
    domain = host

if args.user_agent:
    user_agents = args.user_agent.split(',')
else:
    with open(sys.path[0] + '/core/user-agents.txt', 'r') as uas:
        user_agents = [agent.strip('\n') for agent in uas]


supress_regex = False

def intel_extractor(response):
    """Extract intel from the response body."""
    matches = re.findall(r'([\w\.-]+s[\w\.-]+\.amazonaws\.com)|([\w\.-]+@[\w\.-]+\.[\.\w]+)', response)
    if matches:
        for match in matches:
            verb('Intel', match)
            bad_intel.add(match)


def js_extractor(response):
    """Extract js files from the response body"""
    # Extract .js files
    matches = re.findall(r'<(script|SCRIPT).*(src|SRC)=([^\s>]+)', response)
    for match in matches:
        match = match[2].replace('\'', '').replace('"', '')
        verb('JS file', match)
        bad_scripts.add(match)

def extractor(url):
    """Extract details from the response body."""
    response = requester(url, main_url, delay, cook, headers, timeout, host, ninja, user_agents, failed, processed)
    if clone:
        mirror(url, response)
    matches = re.findall(r'<[aA].*(href|HREF)=([^\s>]+)', response)
    for link in matches:
        # Remove everything after a "#" to deal with in-page anchors
        link = link[1].replace('\'', '').replace('"', '').split('#')[0]
        # Checks if the URLs should be crawled
        if is_link(link, processed, files):
            if link[:4] == 'http':
                if link.startswith(main_url):
                    verb('Internal page', link)
                    internal.add(link)
                else:
                    verb('External page', link)
                    external.add(link)
            elif link[:2] == '//':
                if link.split('/')[2].startswith(host):
                    verb('Internal page', link)
                    internal.add(schema + link)
                else:
                    verb('External page', link)
                    external.add(link)
            elif link[:1] == '/':
                verb('Internal page', link)
                internal.add(main_url + link)
            else:
                verb('Internal page', link)
                internal.add(main_url + '/' + link)

    if not only_urls:
        intel_extractor(response)
        js_extractor(response)
    if args.regex and not supress_regex:
        regxy(args.regex, response, supress_regex, custom)
    if api:
        matches = re.findall(r'[\w-]{16,45}', response)
        for match in matches:
            if entropy(match) >= 4:
                verb('Key', match)
                keys.add(url + ': ' + match)


def jscanner(url):
    """Extract endpoints from JavaScript code."""
    response = requester(url, main_url, delay, cook, headers, timeout, host, ninja, user_agents, failed, processed)
    # Extract URLs/endpoints
    matches = re.findall(r'[\'"](/.*?)[\'"]|[\'"](http.*?)[\'"]', response)
    # Iterate over the matches, match is a tuple
    for match in matches:
        # Combining the items because one of them is always empty
        match = match[0] + match[1]
        # Making sure it's not some JavaScript code
        if not re.search(r'[}{><"\']', match) and not match == '/':
            verb('JS endpoint', match)
            endpoints.add(match)


# Records the time at which crawling started
then = time.time()

# Step 1. Extract urls from robots.txt & sitemap.xml
zap(main_url, args.archive, domain, host, internal, robots)

# This is so the level 1 emails are parsed as well
internal = set(remove_regex(internal, args.exclude))

# Step 2. Crawl recursively to the limit specified in "crawl_level"
for level in range(crawl_level):
    # Links to crawl = (all links - already crawled links) - links not to crawl
    links = remove_regex(internal - processed, args.exclude)
    # If links to crawl are 0 i.e. all links have been crawled
    if not links:
        break
    # if crawled links are somehow more than all links. Possible? ;/
    elif len(internal) <= len(processed):
        if len(internal) > 2 + len(args.seeds):
            break
    print('%s Level %i: %i URLs' % (run, level + 1, len(links)))
    try:
        flash(extractor, links, thread_count)
    except KeyboardInterrupt:
        print('')
        break

if not only_urls:
    for match in bad_scripts:
        if match.startswith(main_url):
            scripts.add(match)
        elif match.startswith('/') and not match.startswith('//'):
            scripts.add(main_url + match)
        elif not match.startswith('http') and not match.startswith('//'):
            scripts.add(main_url + '/' + match)
    # Step 3. Scan the JavaScript files for endpoints
    print('%s Crawling %i JavaScript files' % (run, len(scripts)))
    flash(jscanner, scripts, thread_count)

    for url in internal:
        if '=' in url:
            fuzzable.add(url)

    for match in bad_intel:
        for x in match:  # Because "match" is a tuple
            if x != '':  # If the value isn't empty
                intel.add(x)
        for url in external:
            try:
                if top_level(url, fix_protocol=True) in intels:
                    intel.add(url)
            except:
                pass

# Records the time at which crawling stopped
now = time.time()
# Finds total time taken
diff = (now - then)
minutes, seconds, time_per_request = timer(diff, processed)

# Step 4. Save the results
if not os.path.exists(output_dir): # if the directory doesn't exist
    os.mkdir(output_dir) # create a new directory

datasets = [files, intel, robots, custom, failed, internal, scripts,
            external, fuzzable, endpoints, keys]
dataset_names = ['files', 'intel', 'robots', 'custom', 'failed', 'internal',
                 'scripts', 'external', 'fuzzable', 'endpoints', 'keys']

writer(datasets, dataset_names, output_dir)
# Printing out results
print(('%s-%s' % (red, end)) * 50)
for dataset, dataset_name in zip(datasets, dataset_names):
    if dataset:
        print('%s %s: %s' % (good, dataset_name.capitalize(), len(dataset)))
print(('%s-%s' % (red, end)) * 50)

print('%s Total requests made: %i' % (info, len(processed)))
print('%s Total time taken: %i minutes %i seconds' % (info, minutes, seconds))
print('%s Requests per second: %i' % (info, int(len(processed)/diff)))

datasets = {
    'files': list(files), 'intel': list(intel), 'robots': list(robots),
    'custom': list(custom), 'failed': list(failed), 'internal': list(internal),
    'scripts': list(scripts), 'external': list(external),
    'fuzzable': list(fuzzable), 'endpoints': list(endpoints),
    'keys' : list(keys)
}

if args.dns:
    print('%s Enumerating subdomains' % run)
    from plugins.find_subdomains import find_subdomains
    subdomains = find_subdomains(domain)
    print('%s %i subdomains found' % (info, len(subdomains)))
    writer([subdomains], ['subdomains'], output_dir)
    datasets['subdomains'] = subdomains
    from plugins.dnsdumpster import dnsdumpster
    print('%s Generating DNS map' % run)
    dnsdumpster(domain, output_dir)

if args.export:
    from plugins.exporter import exporter
    # exporter(directory, format, datasets)
    exporter(output_dir, args.export, datasets)

print('%s Results saved in %s%s%s directory' % (good, green, output_dir, end))

if args.std:
    for string in datasets[args.std]:
        sys.stdout.write(string + '\n')
