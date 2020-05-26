#!/usr/bin/env python

from __future__ import print_function, absolute_import, division

# -*- coding: utf-8 -*-
"""
Copyright (c) 2011, Kenneth Reitz <me@kennethreitz.com>

Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted, provided that the above
copyright notice and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

clint.textui.progress
~~~~~~~~~~~~~~~~~

This module provides the progressbar functionality.

"""
import sys
import time
import tarfile
import zipfile
import argparse
import subprocess
import shutil
import hashlib

import os
import yaml

try:
    import requests
except ImportError:
    print('this download script requires the requests module: conda install requests')
    sys.exit(1)

from collections import OrderedDict

from os import path

STREAM = sys.stderr

BAR_TEMPLATE = '%s[%s%s] %i/%i - %s\r'
MILL_TEMPLATE = '%s %s %i/%i\r'

DOTS_CHAR = '.'
BAR_FILLED_CHAR = '#'
BAR_EMPTY_CHAR = ' '
MILL_CHARS = ['|', '/', '-', '\\']

# How long to wait before recalculating the ETA
ETA_INTERVAL = 1
# How many intervals (excluding the current one) to calculate the simple moving
# average
ETA_SMA_WINDOW = 9


class Bar(object):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.done()
        return False  # we're not suppressing exceptions

    def __init__(self, label='', width=32, hide=None, empty_char=BAR_EMPTY_CHAR,
                 filled_char=BAR_FILLED_CHAR, expected_size=None, every=1):
        self.label = label
        self.width = width
        self.hide = hide
        # Only show bar in terminals by default (better for piping, logging etc.)
        if hide is None:
            try:
                self.hide = not STREAM.isatty()
            except AttributeError:  # output does not support isatty()
                self.hide = True
        self.empty_char =    empty_char
        self.filled_char =   filled_char
        self.expected_size = expected_size
        self.every =         every
        self.start =         time.time()
        self.ittimes =       []
        self.eta =           0
        self.etadelta =      time.time()
        self.etadisp =       self.format_time(self.eta)
        self.last_progress = 0
        if (self.expected_size):
            self.show(0)

    def show(self, progress, count=None):
        if count is not None:
            self.expected_size = count
        if self.expected_size is None:
            raise Exception("expected_size not initialized")
        self.last_progress = progress
        if (time.time() - self.etadelta) > ETA_INTERVAL:
            self.etadelta = time.time()
            self.ittimes = \
                self.ittimes[-ETA_SMA_WINDOW:] + \
                    [-(self.start - time.time()) / (progress+1)]
            self.eta = \
                sum(self.ittimes) / float(len(self.ittimes)) * \
                (self.expected_size - progress)
            self.etadisp = self.format_time(self.eta)
        x = int(self.width * progress / self.expected_size)
        if not self.hide:
            if ((progress % self.every) == 0 or      # True every "every" updates
                (progress == self.expected_size)):   # And when we're done
                STREAM.write(BAR_TEMPLATE % (
                    self.label, self.filled_char * x,
                    self.empty_char * (self.width - x), progress,
                    self.expected_size, self.etadisp))
                STREAM.flush()

    def done(self):
        self.elapsed = time.time() - self.start
        elapsed_disp = self.format_time(self.elapsed)
        if not self.hide:
            # Print completed bar with elapsed time
            STREAM.write(BAR_TEMPLATE % (
                self.label, self.filled_char * self.width,
                self.empty_char * 0, self.last_progress,
                self.expected_size, elapsed_disp))
            STREAM.write('\n')
            STREAM.flush()

    def format_time(self, seconds):
        return time.strftime('%H:%M:%S', time.gmtime(seconds))


def bar(it, label='', width=32, hide=None, empty_char=BAR_EMPTY_CHAR,
        filled_char=BAR_FILLED_CHAR, expected_size=None, every=1):
    """Progress iterator. Wrap your iterables with it."""

    count = len(it) if expected_size is None else expected_size

    with Bar(label=label, width=width, hide=hide, empty_char=BAR_EMPTY_CHAR,
             filled_char=BAR_FILLED_CHAR, expected_size=count, every=every) \
            as bar:
        for i, item in enumerate(it):
            yield item
            bar.show(i + 1)

def ordered_load(stream, Loader=yaml.Loader, object_pairs_hook=OrderedDict):
    class OrderedLoader(Loader):
        pass
    def construct_mapping(loader, node):
        loader.flatten_mapping(node)
        return object_pairs_hook(loader.construct_pairs(node))
    OrderedLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
        construct_mapping)
    return yaml.load(stream, OrderedLoader)


def verify_sha256(filename, dataset):
    "Verify the SHA256 sum if declared in the manifest"
    if 'sha256' not in dataset:
        return

    with open(filename, 'rb') as f:
        m = hashlib.sha256()
        m.update(f.read())
        file_digest = m.digest().hex()
    if dataset['sha256'] != str(file_digest):
        print("The declared SHA256 sum %r does not match the digest "
              "of the downloaded file %r" % (dataset['sha256'], file_digest))
        sys.exit(1)

class DirectoryContext(object):
    """
    Context Manager for changing directories
    """
    def __init__(self, path):
        self.old_dir = os.getcwd()
        self.new_dir = path

    def __enter__(self):
        os.chdir(self.new_dir)

    def __exit__(self, *args):
        os.chdir(self.old_dir)

def _process_file(dataset, output_file):
    requires_download = False

    if not dataset.get('title', False):
        dataset['title'] = output_file

    if path.exists(output_file):
        print('Skipping {0}'.format(dataset['title']))
        return

    print('Downloading {0}'.format(dataset['title']))
    r = requests.get(dataset['url'], stream=True)
    with open(output_file, 'wb') as f:
        total_length = int(r.headers.get('content-length'))
        for chunk in bar(r.iter_content(chunk_size=1024), expected_size=(total_length/1024) + 1):
            if chunk:
                f.write(chunk)
                f.flush()

    verify_sha256(output_file, dataset)


def _process_dataset(dataset, output_dir):

    if not path.exists(output_dir):
        os.makedirs(output_dir)

    with DirectoryContext(output_dir) as d:

        output_path = path.split(dataset['url'])[1]

        if not dataset.get('title', False):
            dataset['title'] = output_path

        if path.exists(output_path):
            print('Skipping download {0}'.format(dataset['title']))
            return

        print('Downloading {0}'.format(dataset['title']))
        r = requests.get(dataset['url'], stream=True)
        with open(output_path, 'wb') as f:
            total_length = int(r.headers.get('content-length'))
            for chunk in bar(r.iter_content(chunk_size=1024), expected_size=(total_length/1024) + 1):
                if chunk:
                    f.write(chunk)
                    f.flush()

        verify_sha256(output_path, dataset)

        # extract content
        if output_path.endswith("tar.gz"):
            with tarfile.open(output_path, "r:gz") as tar:
                tar.extractall()
            os.remove(output_path)
        elif output_path.endswith("tar"):
            with tarfile.open(output_path, "r:") as tar:
                tar.extractall()
            os.remove(output_path)
        elif output_path.endswith("tar.bz2"):
            with tarfile.open(output_path, "r:bz2") as tar:
                tar.extractall()
            os.remove(output_path)
        elif output_path.endswith("zip"):
            with zipfile.ZipFile(output_path, 'r') as zipf:
                zipf.extractall()
            os.remove(output_path)

def _post_install(dataset):
    post_install = dataset.get('post_install', False)
    if not post_install:
        return
    else:
        print('{} post install'.format(dataset['title']))
        for line in post_install:
            subprocess.check_call(line, shell=True)

def main(args):
    info = ordered_load(args.file)

    here = contrib_dir = path.abspath(path.join(path.split(__file__)[0]))

    if not path.exists(path.join(here, 'downloads')):
        os.makedirs(path.join(here, 'downloads'))

    with DirectoryContext(path.join(here,'downloads')):
        for topic, downloads in info.items():
            if len(downloads) > 1:
                # topic becomes a directory
                for d in downloads:
                    _process_dataset(d, topic)
                    if args.post_install:
                        _post_install(d)

            elif len(downloads) == 1:
                # topic becomes the filename
                _process_file(downloads[0], topic)
                if args.post_install:
                    _post_install(downloads[0])

    if args.archive:
        print("Creating downloads.tar.bz2")
        with tarfile.open('downloads.tar.bz2', 'w:bz2') as z:
            z.add('downloads/', 'downloads')

        print("Removing downloads/ directory")
        shutil.rmtree('downloads')

def cli():
    parser = argparse.ArgumentParser(description='Download files defined in a manifest')
    parser.add_argument('-f', '--file', help='The manifset YAML file',
                        default='manifest.yml', type=argparse.FileType('r'))

    parser.add_argument('--archive',
                        help='Archive the downloads directory to downloads.tar.bz2 and remove the downloads directory',
                        action='store_true')
    parser.add_argument('--post-install', help='Run post_install scripts', action='store_true')
    return parser

if __name__ == '__main__':
    args=cli().parse_args()
    main(args)
