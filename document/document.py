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
gi.require_version('GtkSource', '3.0')
from gi.repository import GtkSource

import os.path
import pickle
import base64

import document.document_builder as document_builder
import document.document_controller as document_controller
import document.document_presenter as document_presenter
import document.shortcutsbar.shortcutsbar_presenter as shortcutsbar_presenter
import document.document_viewgtk as document_view
import document.build_widget.build_widget as build_widget
import document.search.search as search
import document.autocomplete.autocomplete as autocomplete
from helpers.observable import *
from app.service_locator import ServiceLocator

import re


class Document(Observable):

    def __init__(self, data_pathname):
        Observable.__init__(self)

        self.displayname = ''
        self.filename = None
        self.pdf_filename = None
        self.pdf_date = None
        self.pdf_position = None
        self.last_activated = 0
        self.is_master = False
        self.has_been_built = False
        
        self.source_buffer = None
        self.search_settings = None
        self.search_context = None
        self.init_buffer()
        
        # possible states: idle, ready_for_building
        # building_in_progress, building_to_stop
        self.state = 'idle'
        
        self.data_pathname = data_pathname
        self.document_data = dict()

        self.settings = ServiceLocator.get_settings()

        self.view = document_view.DocumentView(self)
        self.search = search.Search(self, self.view, self.view.search_bar)

    def set_search_text(self, search_text):
        self.search_settings.set_search_text(search_text)
        
    def init_buffer(self):
        self.source_buffer = GtkSource.Buffer()

        # set source language for syntax highlighting
        self.source_language_manager = GtkSource.LanguageManager()
        self.source_language_manager.set_search_path((os.path.dirname(__file__) + '/../resources/gtksourceview/language-specs',))
        self.source_language = self.source_language_manager.get_language(self.get_gsv_language_name())
        self.source_buffer.set_language(self.source_language)
        self.source_buffer.set_highlight_matching_brackets(False)
        
        self.source_style_scheme_manager = GtkSource.StyleSchemeManager()
        self.source_style_scheme_manager.set_search_path((os.path.dirname(__file__) + '/../resources/gtksourceview/styles',))
        self.source_style_scheme_light = self.source_style_scheme_manager.get_scheme('setzer')
        self.source_style_scheme_dark = self.source_style_scheme_manager.get_scheme('setzer-dark')

        self.search_settings = GtkSource.SearchSettings()
        self.search_context = GtkSource.SearchContext.new(self.source_buffer, self.search_settings)
        self.search_context.set_highlight(True)

        self.source_buffer.connect('changed', self.on_buffer_change)
        self.source_buffer.connect('insert-text', self.on_insert_text)
        self.source_buffer.connect('delete-range', self.on_delete_range)

        self.add_change_code('buffer_ready')

    def on_buffer_change(self, buffer):
        if self.source_buffer.get_end_iter().get_offset() > 0:
            self.add_change_code('document_not_empty')
        else:
            self.add_change_code('document_empty')
        
    def on_insert_text(self, buffer, location_iter, text, text_len):
        pass

    def on_delete_range(self, buffer, start_iter, end_iter):
        pass

    def set_use_dark_scheme(self, use_dark_scheme):
        if use_dark_scheme: self.source_buffer.set_style_scheme(self.source_style_scheme_dark)
        else: self.source_buffer.set_style_scheme(self.source_style_scheme_light)
    
    def get_buffer(self):
        return self.source_buffer

    def get_filename(self):
        return self.filename
        
    def set_filename(self, filename):
        self.filename = filename
        self.add_change_code('filename_change', filename)
        if self.filename != None:
            pathname = self.filename.rsplit('/', 1)
            pdf_filename = pathname[0] + '/' + pathname[1].rsplit('.', 1)[0] + '.pdf'
            if os.path.exists(pdf_filename):
                self.set_pdf_filename(pdf_filename)
        
    def get_pdf_filename(self):
        return self.pdf_filename
        
    def set_pdf_filename(self, pdf_filename):
        self.pdf_filename = pdf_filename
        self.set_pdf_date()
        self.add_change_code('pdf_update', pdf_filename)
        
    def set_pdf(self, pdf_filename, pdf_position=None):
        self.pdf_filename = pdf_filename
        self.set_pdf_date()
        self.pdf_position = pdf_position
        self.add_change_code('pdf_update', pdf_filename)
        
    def get_pdf_position(self):
        return self.pdf_position
        
    def set_pdf_date(self):
        if self.pdf_filename != None:
            self.pdf_date = os.path.getmtime(self.pdf_filename)
    
    def get_pdf_date(self):
        return self.pdf_date
        
    def get_displayname(self):
        if self.filename != None:
            return self.get_filename()
        else:
            return self.displayname
        
    def set_displayname(self, displayname):
        self.displayname = displayname
        self.add_change_code('displayname_change')
        
    def get_last_activated(self):
        return self.last_activated
        
    def set_last_activated(self, date):
        self.last_activated = date
        
    def get_modified(self):
        return self.get_buffer().get_modified()
        
    def populate_from_filename(self):
        if self.filename == None: return False
        if not os.path.isfile(self.filename): return False
        if self.get_buffer() == None: return False

        try: filehandle = open(self.data_pathname + '/' + base64.urlsafe_b64encode(str.encode(self.filename)).decode() + '.pickle', 'rb')
        except IOError: pass
        else:
            try: data = pickle.load(filehandle)
            except EOFError: pass
            else:
                self.document_data = data
    
        with open(self.filename) as f:
            text = f.read()
            source_buffer = self.get_buffer()
            source_buffer.begin_not_undoable_action()
            source_buffer.set_text(text)
            source_buffer.end_not_undoable_action()
            source_buffer.set_modified(False)
            source_buffer.place_cursor(source_buffer.get_start_iter())
                
    def save_to_disk(self):
        if self.filename == None: return False
        if self.get_buffer() == None: return False
        else:
            buff = self.get_buffer()
            text = buff.get_text(buff.get_start_iter(), buff.get_end_iter(), True)
            with open(self.filename, 'w') as f:
                f.write(text)
                buff.set_modified(False)
                
    def parse_result_blob(self):
        result = MarkdownResult(self.result_blob)
        self.set_result(result)
        
    def get_state(self):
        return self.state

    def change_state(self, state):
        self.state = state
        self.add_change_code('document_state_change', self.state)

    def save_document_data(self):
        if self.filename != None:
            try: filehandle = open(self.data_pathname + '/' + base64.urlsafe_b64encode(str.encode(self.filename)).decode() + '.pickle', 'wb')
            except IOError: pass
            else: pickle.dump(self.document_data, filehandle)
    
    def build(self):
        if self.filename != None:
            self.change_state('ready_for_building')

    def stop_building(self):
        self.change_state('building_to_stop')
        
    def cleanup_build_files(self):
        file_endings = ['.aux', '.blg', '.bbl', '.dvi', '.fdb_latexmk', '.fls', '.idx' ,'.ilg', '.ind', '.log', '.nav', '.out', '.snm', '.synctex.gz', '.toc']
        pathname = self.get_filename().rsplit('/', 1)
        for ending in file_endings:
            filename = pathname[0] + '/' + pathname[1].rsplit('.', 1)[0] + ending
            try: os.remove(filename)
            except FileNotFoundError: pass
        self.add_change_code('cleaned_up_build_files')

    def set_is_master(self, is_master):
        self.is_master = is_master
        self.add_change_code('master_state_change', is_master)

    def insert_text_at_cursor(self, text, indent_lines=True):
        buff = self.get_buffer()
        if buff != False:
            buff.begin_user_action()

            # replace tabs with spaces, if set in preferences
            if self.settings.get_value('preferences', 'spaces_instead_of_tabs'):
                number_of_spaces = self.settings.get_value('preferences', 'tab_width')
                text = text.replace('\t', ' ' * number_of_spaces)

            dotcount = text.count('•')
            insert_iter = buff.get_iter_at_mark(buff.get_insert())
            bounds = buff.get_selection_bounds()
            if dotcount == 1:
                bounds = buff.get_selection_bounds()
                if len(bounds) > 0:
                    selection = buff.get_text(bounds[0], bounds[1], True)
                    if len(selection) > 0:
                        text = text.replace('•', selection, 1)

            if indent_lines:
                line_iter = buff.get_iter_at_line(insert_iter.get_line())
                ws_line = buff.get_text(line_iter, insert_iter, False)
                lines = text.splitlines()
                ws_number = len(ws_line) - len(ws_line.lstrip())
                whitespace = ws_line[:ws_number]
                final_text = ''
                for no, line in enumerate(lines):
                    if no != 0:
                        final_text += '\n' + whitespace
                    final_text += line
            else:
                final_text = text

            buff.delete_selection(False, False)
            buff.insert_at_cursor(final_text)

            dotindex = text.find('•')
            if dotcount == 1:
                start = buff.get_iter_at_mark(buff.get_insert())
                start.backward_chars(abs(dotindex + len(selection) - len(text)))
                buff.place_cursor(start)
            elif dotcount > 0:
                start = buff.get_iter_at_mark(buff.get_insert())
                start.backward_chars(abs(dotindex - len(text)))
                end = start.copy()
                end.forward_char()
                buff.select_range(start, end)
            self.view.source_view.scroll_to_mark(buff.get_insert(), 0, False, 0, 0)

            buff.end_user_action()

    def replace_range(self, start_iter, end_iter, text, indent_lines=True):
        buffer = self.get_buffer()
        if buffer != None:
            buffer.begin_user_action()

            if indent_lines:
                line_iter = buffer.get_iter_at_line(start_iter.get_line())
                ws_line = buffer.get_text(line_iter, start_iter, False)
                lines = text.splitlines()
                ws_number = len(ws_line) - len(ws_line.lstrip())
                whitespace = ws_line[:ws_number]
                final_text = ''
                for no, line in enumerate(lines):
                    if no != 0:
                        final_text += '\n' + whitespace
                    final_text += line
            else:
                final_text = text

            buffer.delete(start_iter, end_iter)
            buffer.insert(start_iter, final_text)

            dotindex = final_text.find('•')
            if dotindex > -1:
                start_iter.backward_chars(abs(dotindex - len(final_text)))
                bound = start_iter.copy()
                bound.forward_chars(1)
                buffer.select_range(start_iter, bound)
            buffer.end_user_action()

    def insert_before_after(self, before, after):
        ''' wrap text around current selection. '''

        buff = self.get_buffer()
        if buff != False:
            bounds = buff.get_selection_bounds()
            buff.begin_user_action()
            if len(bounds) > 1:
                text = before + buff.get_text(*bounds, 0) + after
                buff.delete_selection(False, False)
                buff.insert_at_cursor(text)
                cursor_pos = buff.get_iter_at_mark(buff.get_insert())
                cursor_pos.backward_chars(len(after))
                buff.place_cursor(cursor_pos)
                self.view.source_view.scroll_to_mark(buff.get_insert(), 0, False, 0, 0)
            else:
                text = before + '•' + after
                buff.insert_at_cursor(text)
                cursor_pos = buff.get_iter_at_mark(buff.get_insert())
                cursor_pos.backward_chars(len(after))
                bound = cursor_pos.copy()
                bound.backward_chars(1)
                buff.select_range(bound, cursor_pos)
                self.view.source_view.scroll_to_mark(buff.get_insert(), 0, False, 0, 0)
            buff.end_user_action()


class LaTeXDocument(Document):

    def __init__(self, data_pathname):
        Document.__init__(self, data_pathname)

        self.build_log_items = list()
        self.build_widget = build_widget.BuildWidget(self)

        self.autocomplete = autocomplete.Autocomplete(self, self.view)
        self.builder = document_builder.DocumentBuilder(self)
        self.presenter = document_presenter.DocumentPresenter(self, self.view)
        self.shortcutsbar = shortcutsbar_presenter.ShortcutsbarPresenter(self, self.view)
        self.controller = document_controller.DocumentController(self, self.view)

    def get_file_ending(self):
        return 'tex'

    def get_gsv_language_name(self):
        return 'latex'


class BibTeXDocument(Document):

    def __init__(self, data_pathname):
        Document.__init__(self, data_pathname)

        self.autocomplete = None
        self.builder = None
        self.presenter = document_presenter.DocumentPresenter(self, self.view)
        self.shortcutsbar = shortcutsbar_presenter.ShortcutsbarPresenter(self, self.view)
        self.controller = document_controller.DocumentController(self, self.view)

    def get_file_ending(self):
        return 'bib'

    def get_gsv_language_name(self):
        return 'bibtex'


