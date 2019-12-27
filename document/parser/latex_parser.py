#!/usr/bin/env python3
# coding: utf-8

# Copyright (C) 2017, 2018 Robert Griesel
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>

import gi
from gi.repository import GObject

from helpers.observable import *
from helpers.helpers import timer
from app.service_locator import ServiceLocator
import _thread as thread, queue
import time


class LaTeXParser(Observable):

    def __init__(self, document):
        Observable.__init__(self)
        self.document = document

        self.symbols = dict()
        self.symbols['labels'] = set()
        self.symbols['includes'] = set()
        self.symbols['inputs'] = set()
        self.symbols['bibliographies'] = set()
        self.labels_changed = True
        self.symbols_lock = thread.allocate_lock()

        self.blocks = list()
        self.blocks_changed = True
        self.blocks_lock = thread.allocate_lock()

        self.parse_jobs = dict()
        self.parse_jobs['symbols'] = None
        self.parse_jobs['blocks'] = None
        self.parse_symbols_job_running = False
        self.parse_blocks_job_running = False
        self.parse_jobs_lock = thread.allocate_lock()

        GObject.timeout_add(50, self.compute_loop)

    def on_buffer_changed(self):
        text = self.document.get_text()
        self.parse_jobs_lock.acquire()
        self.parse_jobs['symbols'] = ParseJob(time.time() + 1, text)
        self.parse_jobs['blocks'] = ParseJob(time.time() + 1, text)
        self.parse_jobs_lock.release()

    def compute_loop(self):
        self.parse_jobs_lock.acquire()
        job = self.parse_jobs['symbols']
        self.parse_jobs_lock.release()
        if job != None:
            self.parse_jobs_lock.acquire()
            parse_symbols_job_running = self.parse_symbols_job_running
            self.parse_jobs_lock.release()
            if not parse_symbols_job_running and job.starting_time < time.time():
                self.parse_jobs_lock.acquire()
                self.parse_jobs['symbols'] = None
                self.parse_jobs_lock.release()
                thread.start_new_thread(self.parse_symbols, (job.text, ))

        self.parse_jobs_lock.acquire()
        job = self.parse_jobs['blocks']
        self.parse_jobs_lock.release()
        if job != None:
            self.parse_jobs_lock.acquire()
            parse_blocks_job_running = self.parse_blocks_job_running
            self.parse_jobs_lock.release()
            if not parse_blocks_job_running and job.starting_time < time.time():
                self.parse_jobs_lock.acquire()
                self.parse_jobs['blocks'] = None
                self.parse_jobs_lock.release()
                thread.start_new_thread(self.parse_blocks, (job.text, ))

        return True

    def get_labels(self):
        self.document.parser.symbols_lock.acquire()
        if self.labels_changed:
            result = self.symbols['labels'].copy()
        else:
            result = None
        self.labels_changed = False
        self.document.parser.symbols_lock.release()
        return result

    #@timer
    def parse_blocks(self, text):
        self.parse_jobs_lock.acquire()
        self.parse_blocks_job_running = True
        self.parse_jobs_lock.release()

        blocks = dict()
        for match in ServiceLocator.get_blocks_regex().finditer(text):
            if match.group(1) == 'begin':
                try: blocks[match.group(2)].append([match.start(), None])
                except KeyError: blocks[match.group(2)] = [[match.start(), None]]
            else:
                try: begins = blocks[match.group(2)]
                except KeyError: pass
                else:
                    for block in reversed(begins):
                        if block[1] == None:
                            block[1] = match.start()
                            break

        blocks_list = list()
        for single_list in blocks.values():
            blocks_list += single_list
        blocks_list = sorted(blocks_list, key=lambda block: block[0])

        self.blocks_lock.acquire()
        self.blocks = blocks_list
        self.blocks_changed = True
        self.blocks_lock.release()

        self.parse_jobs_lock.acquire()
        self.parse_blocks_job_running = False
        self.parse_jobs_lock.release()

    #@timer
    def parse_symbols(self, text):
        self.parse_jobs_lock.acquire()
        self.parse_symbols_job_running = True
        self.parse_jobs_lock.release()
        labels = set()
        includes = set()
        inputs = set()
        bibliographies = set()
        for match in ServiceLocator.get_symbols_regex().finditer(text):
            if match.group(1) == 'label':
                labels = labels | {match.group(2).strip()}
            elif match.group(1) == 'include':
                includes = includes | {match.group(2).strip()}
            elif match.group(1) == 'input':
                inputs = inputs | {match.group(2).strip()}
            elif match.group(1) == 'bibliography':
                bibfiles = match.group(2).strip().split(',')
                for entry in bibfiles:
                    bibliographies = bibliographies | {entry.strip()}

        self.symbols_lock.acquire()
        self.symbols['labels'] = labels
        self.symbols['includes'] = includes
        self.symbols['inputs'] = inputs
        self.symbols['bibliographies'] = bibliographies
        self.labels_changed = True
        self.symbols_lock.release()
        self.parse_jobs_lock.acquire()
        self.parse_symbols_job_running = False
        self.parse_jobs_lock.release()


class ParseJob():

    def __init__(self, starting_time, text):
        self.starting_time = starting_time
        self.text = text


