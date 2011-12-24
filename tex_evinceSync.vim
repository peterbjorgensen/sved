" Vim global plugin for synchronizing vim and evince with synctex
" Last Change:  2011 July 12
" Maintainer:   Peter B. Jørgensen <peterbjorgensen@gmail.com>
" License:  This file is licensed under the BEER-WARE license rev 42.
"   THE BEER-WARE LICENSE" (Revision 42):
"   <peterbjorgensen@gmail.com> wrote this file. 
"   As long as you retain this notice you can do whatever you want with this stuff.
"   If we meet some day, and you think this stuff is worth it, you can buy me a beer in return.

if exists("g:loaded_evinceSync") || !has("gui_running")
    finish
endif
let g:loaded_evinceSync = 1

function! EVS_Sync()
python << endofpython
cursor = vim.current.window.cursor
filename = vim.current.buffer.name
evs_daemon.sync_view(filename, cursor)
endofpython
endfunction

function! EVS_StartDaemon()
python << endofpython
evs_daemon = EvinceSync(True)
evs_daemon.init_connection()
endofpython
endfunction

function! EVS_Define()
python << EOF
#!/usr/bin/python
# -*- coding: utf-8 -*-
import os
import dbus
from traceback import print_exc
from dbus.mainloop.glib import DBusGMainLoop
import vim
import glob
import time
import urllib

dbus.mainloop.glib.threads_init()
DBusGMainLoop(set_as_default=True)

class EvinceSync:
    """A DBus proxy for an Evince Window"""
    
    def __init__(self, debug=False):
        self.bus = None
        self.daemon = None
        self.evince_name = ""
        self.sync_queue = []
        if debug:
            self.debug = self.debug_to_file
            self.debug_file = open(os.path.expanduser("~/evslog.txt"), "w")
        else:
            self.debug = self.debug_dummy

    def init_connection(self):
        """Connect to session bus and daemon"""
        if self.bus is None:
            try: 
                self.connect_bus()
            except dbus.DBusException:
                print_exc()
        if self.daemon is None:
            try:
                self.connect_daemon()
            except dbus.DBusException:
                print_exc()

    def connect_bus(self):
        """Establish connection to dbus session bus"""
        self.debug("connect_bus: connecting to dbus")
        self.bus = dbus.SessionBus()
        self.bus.add_signal_receiver(self.on_document_load,
               signal_name = "DocumentLoaded",
               dbus_interface = "org.gnome.evince.Window",
               sender_keyword = "sender")
        self.bus.add_signal_receiver(self.on_sync_source,
                signal_name = "SyncSource",
                dbus_interface = "org.gnome.evince.Window")

    def connect_daemon(self):
        """Establish connection to Evince dbus Daemon"""
        self.debug("connect_daemon: connecting to Evince daemon")
        self.daemon = self.bus.get_object(
                    "org.gnome.evince.Daemon",
                    "/org/gnome/evince/Daemon")

    def sync_view(self, source_file, data):
        """Forward sync Evince with source_file and data (line,column)"""
        self.debug("sync_view: Forward syncing")
        self.connect_daemon()
        try:
            pdf_uri, source_file = self.get_pdf_file_uri(source_file)
        except:
            self.debug("sync_view: Failed to get main pdf uri")
            return
        if pdf_uri:
            self.debug("sync_view: Found main pdf uri: %s" % (pdf_uri))
        else:
            self.debug("sync_view: Failed to get main pdf uri")
            return
        self.sync_queue.append((pdf_uri, source_file, data))
        self.daemon.FindDocument(pdf_uri, True,
            dbus_interface="org.gnome.evince.Daemon",
            reply_handler=self.handle_find_document_reply,
            error_handler=self.handle_find_document_error )

    def on_sync_source(self, input_file, source_link, timestamp):
        """Handle SyncSource signal from evince.Window"""
        self.debug( "on_sync_source received: %s %s" 
                % (input_file, source_link) )
        #find uri separator
        index = input_file.find("://")
        if index == -1:
            self.debug("on_sync_source: '://' not found in input_file")
            return
        source = urllib.unquote(input_file[index+3:]).replace(" ","\\ ")
        line = source_link[0]
        cmd = "edit! +%d %s" % (line, source)
        self.debug("on_sync_source: Executing %s" % (cmd))
        try:
            vim.command(cmd)
        except vim.error:
            self.debug("on_sync_source: Vim error")

    def on_document_load(self, uri, sender=None):
        """Handle DocumentLoaded signal from evince.Window"""
        self.debug("on_document_load received: %s, %s" % (uri, sender))

    def handle_find_document_reply(self, evince_name):
        self.debug("handle_find_document_reply: Find document reply: "
                + evince_name)
        if evince_name != "":
            self.evince_name = evince_name
            ev = self.bus.get_object(evince_name, "/org/gnome/evince/Evince")
            ev.GetWindowList(reply_handler = self.handle_get_window_list_reply,
                            error_handler = self.handle_get_window_list_error,
                            dbus_interface = "org.gnome.evince.Application")

    def handle_find_document_error(self, err):
        self.debug("handle_find_document_error: "
                + err.get_dbus_message())
        self.sync_queue = []

    def handle_get_window_list_reply(self, window_list):
        self.debug("handle_get_window_list_reply: " + str(window_list))
        if len(self.sync_queue) > 0 and len(window_list) > 0:
            pdf_uri, source_file, data = self.sync_queue.pop(0)
            window_path = window_list[0]
            window_proxy = self.bus.get_object(self.evince_name, window_path)
            self.debug("handle_get_window_list_reply: calling SyncView %s %s" %
                (source_file, data) )
            window_proxy.SyncView(source_file, data, 0, 
                        dbus_interface="org.gnome.evince.Window")
        else:
            self.debug("handle_get_window_list_reply: empty sync" +
                    " queue or window list")
            self.sync_queue = []
        

    def handle_get_window_list_error(self, err):
        self.debug("handle_get_window_list_error: "
                + err.get_dbus_message())
        self.sync_queue = []

    def debug_to_file(self, s):
        self.debug_file.write(str(time.time()) + " " + s + " \n")
        self.debug_file.flush()
        os.fsync(self.debug_file)

    def debug_dummy(self, s):
        pass
        
    def get_pdf_file_uri(self, source_file):
        """Find mainfile of latex project - expect the use
        of *.latexmain. Returns:
            * pdf file uri 
            * source_file with '/.' added at the main file location 
                (TexLive 2011 workaround)"""
        path = vim.current.buffer.name
        if path is None:
            path = vim.eval("getcwd()")
        while (path != "/"):
            mainfile = glob.glob(path + "/*.latexmain")
            if mainfile:
                self.debug("get_pdf_file_uri: Found master file %s" % (mainfile))
                break
            path = os.path.dirname(path)
        pdffile = None
        for name in mainfile:
            #Remove .latexmain
            filepath = name.rpartition(".")[0] 
            if os.path.exists(filepath + ".pdf"):
                pdffile = "file://" + urllib.quote(filepath) + ".pdf"
                break
            self.debug("get_pdf_file_uri: No pdf at: " + filepath + ".pdf")
            #Remove .tex
            filepath = filepath.rpartition(".")[0] 
            if os.path.exists(filepath + ".pdf"):
                pdffile = "file://" + urllib.quote(filepath) + ".pdf"
                break
            self.debug("get_pdf_file_uri: No pdf at: " + filepath + ".pdf")
        mainfolder = filepath.rpartition("/")[0]
        source = source_file.replace(mainfolder, mainfolder + "/.", 1)
        return pdffile, source

EOF
endfunction

" main
if has("python")
    call EVS_Define()
    call EVS_StartDaemon()
endif
